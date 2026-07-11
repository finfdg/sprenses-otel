"""Verilen çek Sedna içe-aktarma mantığı (HTTP'siz domain katmanı).

`checks.py` router'ından ayrıştırıldı (dosya boyutu + tek-sorumluluk). Router endpoint'leri
(`checks.py`) ve merkezi Sedna orchestrator (`sedna_sync.py`) buradan import eder. Bu modül
router'dan import ETMEZ (tek yön → cycle yok). Dedup/status anahtar helper'ları hem Excel
yükleme (checks.py) hem Sedna import tarafından paylaşıldığından burada (alt katman) tutulur.
"""
import bisect
import logging
import re
from datetime import datetime
from typing import Optional

import pytz
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import SourceType
from app.models.check import Check, CheckUpload
from app.models.user import User
from app.utils.audit import log_action
from app.utils.finance_event_service import finance_event_svc
from app.utils.matching_service import _match_checks_to_bank
from app.utils.sedna_client import SednaUnavailable, fetch_issued_checks, sedna_configured

logger = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Istanbul")

_INFER_MAX_GAP = 50  # iki onaylı çapa arası en fazla bu kadar fark → aynı çek defteri sayılır
_ISSUED_SCOPE_PREFIXES = ("320", "159", "335")  # Sedna verilen-çek hesap önekleri


# ── Anahtar / durum helper'ları (Excel yükleme ile paylaşılır) ─

def _check_status_from_pos(max_pos: Optional[int]) -> str:
    """Sedna çek pozisyonu → bizim durum. 101/102 Bankadan/Kasadan Ödeme=paid,
    103 Geri Al=cancelled, gerisi (100 Verilen, 104 Protesto, 105 Takipte)=pending."""
    if max_pos in (101, 102):
        return "paid"
    if max_pos == 103:
        return "cancelled"
    return "pending"


def _check_dedup_key(check_no, vendor_code, currency, amount_tl, amount_currency):
    """Çek dedup anahtarı: (check_no, vendor_code, currency, NATIVE tutar).

    `due_date` ANAHTARDA YOK → vade değişimi mükerrer üretmez. Tutar olarak **para birimi cinsi
    yüz değer** kullanılır: TL çek → `amount_tl` (sabit); döviz çek → `amount_currency` (EUR/USD
    yüz değeri, sabit). `amount_tl` döviz çekte TL değerlemesidir ve KUR ile değişir → anahtarda
    kullanılamaz (her kur hareketinde "yeni" çek sanılır)."""
    curr = (currency or "TL").strip().upper()
    if curr in ("TL", "TRY", ""):
        return (check_no, vendor_code, "TL", round(float(amount_tl or 0), 2))
    return (check_no, vendor_code, curr, round(float(amount_currency or amount_tl or 0), 2))


def _check_group_key(vendor_code, currency, amount_tl, amount_currency, due_date):
    """Çek-no'SUZ kimlik: (cari, para, NATIVE tutar, vade). Aynı çekin farklı/typo'lu no ile
    tekrarını yakalamak için (sütun-kayması mükerrer tespiti / removal-sweep)."""
    curr = (currency or "TL").strip().upper()
    if curr in ("TL", "TRY", ""):
        return (vendor_code, "TL", round(float(amount_tl or 0), 2), due_date)
    return (vendor_code, curr, round(float(amount_currency or amount_tl or 0), 2), due_date)


def _checkno_to_int(check_no):
    """Çek no → int (baştaki sıfırlar atılır). Sayısal değilse (ör. bozuk 'ANTALYA') None."""
    s = (check_no or "").strip()
    return int(s) if s.isdigit() else None


def _norm_bank(b):
    """Banka adı karşılaştırması için Türkçe-duyarsız normalizasyon."""
    s = (b or "").upper().replace(" ", "")
    for a, k in (("İ", "I"), ("Ş", "S"), ("Ğ", "G"), ("Ç", "C"), ("Ö", "O"), ("Ü", "U")):
        s = s.replace(a, k)
    return s


# ── Banka tahmini / anomali / bayat süpürme ───────────────────

def infer_check_banks(db: Session) -> int:
    """Bankası boş çekleri ardışık çek-no komşularından TAHMİN et (aynı çek defteri = aynı banka).

    Yalnız INTERPOLASYON: çekin sayısal alt + üst **onaylı** (inferred=False) komşusu aynı bankada
    ve aralarındaki fark ≤ _INFER_MAX_GAP ise o banka atanır (`bank_name_inferred=True`). Çapa olarak
    yalnız onaylı bankalar kullanılır (tahmin-üstüne-tahmin yok). İzole/uçtaki + sayısal-olmayan çekler
    atlanır. Idempotent; çapa kalkarsa eski tahmini temizler. Döner: değişen çek sayısı.
    """
    all_checks = db.query(Check).all()
    anchors = sorted(
        (_checkno_to_int(c.check_no), c.bank_name)
        for c in all_checks
        if c.bank_name and not c.bank_name_inferred and _checkno_to_int(c.check_no) is not None
    )
    nums = [a[0] for a in anchors]
    changed = 0
    for c in all_checks:
        if c.bank_name and not c.bank_name_inferred:
            continue  # onaylı banka → asla dokunma
        inferred = None
        n = _checkno_to_int(c.check_no)
        if n is not None and anchors:
            i = bisect.bisect_left(nums, n)
            lower = anchors[i - 1] if i - 1 >= 0 and anchors[i - 1][0] < n else None
            upper = anchors[i] if i < len(anchors) and anchors[i][0] > n else None
            if (lower and upper and _norm_bank(lower[1]) == _norm_bank(upper[1])
                    and (upper[0] - lower[0]) <= _INFER_MAX_GAP):
                inferred = lower[1]
        if inferred:
            if c.bank_name != inferred or not c.bank_name_inferred:
                c.bank_name = inferred
                c.bank_name_inferred = True
                finance_event_svc.upsert_check(db, c)
                changed += 1
        elif c.bank_name_inferred:  # artık tahmin edilemiyor → eski tahmini temizle
            c.bank_name = None
            c.bank_name_inferred = False
            finance_event_svc.upsert_check(db, c)
            changed += 1
    if changed:
        db.flush()
    return changed


def detect_check_no_mismatches(db: Session) -> list:
    """check_no ile açıklamadaki 6-7 haneli numara uyuşmuyorsa olası giriş hatası listele (DÜZELTMEZ).

    Excel/cari açıklamasında gerçek çek no gömülü olur; check_no'dan farklıysa transkripsiyon hatası
    olabilir (ör. 0012119 vs açıklama 0012419 → '4' yerine '1'). Yalnız TESPİT — düzeltme insan kararı
    (off-by-1 farklar açıklamanın komşu çeke referansı da olabilir). Açıklama-no'su check_no ile eşleşen
    veya açıklamada 6-7 haneli no içermeyen çekler raporlanmaz.
    """
    out = []
    for ch in db.query(Check).filter(Check.description.isnot(None)).all():
        cn = _checkno_to_int(ch.check_no)
        if cn is None:
            continue
        for tok in re.findall(r"\d{6,7}", ch.description or ""):
            ti = _checkno_to_int(tok)
            if ti is not None and ti != cn:
                out.append({
                    "id": ch.id, "check_no": ch.check_no, "description_no": tok,
                    "vendor_code": ch.vendor_code, "vendor_name": ch.vendor_name,
                    "amount_tl": float(ch.amount_tl), "currency": ch.currency, "status": ch.status,
                })
                break
    return out


def _sweep_stale_checks(db: Session, sedna_rows: list) -> int:
    """Sedna = tek doğru kaynak: Sedna'da OLMAYAN ama Sedna'da AYNI (cari+para+tutar+vade) çeki
    bulunan EŞLEŞMEMİŞ lokal çekleri sil → lokali Sedna'ya hizalar (sütun-kayması/typo mükerrerleri).

    Güvenlik: yalnız (a) eşleşmemiş (banka/cari bağı yok), (b) verilen-çek kapsamı (320/159/335),
    (c) Sedna'da birebir (no dahil) karşılığı OLMAYAN, AMA (d) Sedna'da no'suz kimliği (cari+para+
    tutar+vade) BULUNAN çekler silinir → Sedna'da hiç eşi olmayan (legit) çeke DOKUNMAZ; eşleşmişe DOKUNMAZ.
    """
    sedna_exact, sedna_group = set(), set()
    for r in sedna_rows:
        code = (r.get("vendor_code") or "").strip()
        no = (str(r.get("check_no")) or "").strip()[:50]
        curr = (r.get("currency") or "TL").strip() or "TL"
        amt_tl = float(r.get("amount_tl") or 0)
        cur_amt = float(r.get("amount_currency") or 0)
        native = cur_amt if (curr != "TL" and cur_amt) else amt_tl
        due = r.get("due_date")
        if not no or not code or not due:
            continue
        sedna_exact.add(_check_dedup_key(no, code, curr, amt_tl, native))
        sedna_group.add(_check_group_key(code, curr, amt_tl, native, due))

    removed = 0
    locals_ = db.query(Check).filter(
        Check.bank_transaction_id.is_(None), Check.match_number.is_(None),
    ).all()
    for ch in locals_:
        code = ch.vendor_code or ""
        if not any(code.startswith(p) for p in _ISSUED_SCOPE_PREFIXES):
            continue
        ek = _check_dedup_key(ch.check_no, ch.vendor_code, ch.currency,
                              float(ch.amount_tl or 0), float(ch.amount_currency or 0))
        if ek in sedna_exact:
            continue  # Sedna ile birebir (no dahil) → koru
        gk = _check_group_key(ch.vendor_code, ch.currency,
                              float(ch.amount_tl or 0), float(ch.amount_currency or 0), ch.due_date)
        if gk in sedna_group:  # Sedna'da aynı çek farklı no ile var → bu lokal kayıt bayat typo-dup
            finance_event_svc.invalidate(db, SourceType.CHECK, ch.id)
            logger.warning("Bayat çek silindi (Sedna'da yok): no=%s cari=%s tutar=%s vade=%s",
                           ch.check_no, ch.vendor_code, ch.amount_tl, ch.due_date)
            db.delete(ch)
            removed += 1
    if removed:
        db.flush()
    return removed


# ── İçe-aktarma çekirdek ──────────────────────────────────────

def _build_existing_and_stale(db: Session):
    """Mevcut çekleri dedup-key haritasına diz + vade değişiminden kalan eşleşmemiş
    mükerrerleri tespit et. Dönüş: (existing: dict[key→Check], stale_dupes: list[Check]).

    Dedup anahtarı: (check_no, vendor_code, currency, NATIVE tutar) — bk. _check_dedup_key.
    """
    existing = {}
    stale_dupes = []
    for c in db.query(Check).order_by(Check.id).all():
        k = _check_dedup_key(c.check_no, c.vendor_code, c.currency, c.amount_tl, c.amount_currency)
        prev = existing.get(k)
        if prev is None:
            existing[k] = c
            continue
        c_matched = bool(c.bank_transaction_id or c.match_number)
        prev_matched = bool(prev.bank_transaction_id or prev.match_number)
        if prev_matched and not c_matched:
            stale_dupes.append(c)                       # eşleşmiş prev korunur
        elif c_matched and not prev_matched:
            stale_dupes.append(prev); existing[k] = c   # eşleşmiş c korunur
        elif not c_matched and not prev_matched:
            stale_dupes.append(prev); existing[k] = c   # ikisi de eşleşmemiş → yeni (c) tut, eskiyi sil
        # else: ikisi de eşleşmiş → gerçek ayrı ödemeler olabilir, DOKUNMA
    return existing, stale_dupes


def _import_one_check_row(db: Session, r: dict, upload_id: int, existing: dict,
                          diff_ids=None) -> str:
    """Tek Sedna çek satırını içe aktar. Dönüş: 'new' | 'updated' | 'skipped'.

    `existing` (dedup-key → Check) YERİNDE güncellenir. Her satır kendi SAVEPOINT'inde
    işlenir → bir kısıt çakışması tüm içe aktarmayı düşürmez (IntegrityError → 'skipped').
    Faz B: EŞLEŞMİŞ çekteki Sedna sapması artık sessiz atlanmaz — `diff_ids` verildiyse
    Uyuşmayan Veriler'e 'Sedna sapması' kaydı yazılır (yerel kayıt DEĞİŞTİRİLMEZ).
    """
    check_no = (str(r.get("check_no")) or "").strip()[:50]
    vendor_code = (r.get("vendor_code") or "").strip() or None
    due_date = r.get("due_date")
    if not check_no or not due_date:
        return "skipped"
    curr = (r.get("currency") or "TL").strip() or "TL"
    amount_tl = float(r.get("amount_tl") or 0)
    cur_amt = float(r.get("amount_currency") or 0)
    amount_currency = cur_amt if (curr != "TL" and cur_amt) else amount_tl
    new_status = _check_status_from_pos(r.get("max_pos"))
    bank = (r.get("bank") or "").strip() or None
    rec_id = r.get("check_rec_id")
    key = _check_dedup_key(check_no, vendor_code, curr, amount_tl, amount_currency)

    def _report_matched_diff(chk):
        """Eşleşmiş çekte önemli Sedna farkı → Uyuşmayan Veriler (vade/tutar/iptal)."""
        if diff_ids is None:
            return
        important = (
            chk.due_date != due_date
            or round(float(chk.amount_currency or 0), 2) != round(amount_currency, 2)
            or (new_status == "cancelled" and chk.status != "cancelled")
        )
        if not important:
            return
        from app.services.sedna_recon_service import report_entity_diff
        report_entity_diff(
            db, "check", chk.id,
            amount=amount_currency, currency=("TRY" if curr == "TL" else curr),
            event_date=due_date,
            description=(f"Yerel çek {chk.check_no}: vade {chk.due_date} tutar "
                         f"{chk.amount_currency} {chk.currency} durum {chk.status} (eşleşmiş)"),
            sedna_description=(f"Sedna: vade {due_date} tutar {amount_currency} {curr} "
                               f"durum {new_status}"),
            sedna_rec_id=int(rec_id) if rec_id is not None else None,
        )
        diff_ids.add(chk.id)

    try:
        with db.begin_nested():
            ex = existing.get(key)
            if ex is not None:
                # eşleşmemiş çek → Sedna güncel durumunu yansıt (VADE + durum + banka); eşleşmişe dokunma.
                # Banka farkı/eksiği de tetikler → mevcut çeklerde bank_name geriye doldurulur (re-sync backfill).
                if rec_id is not None and ex.sedna_check_rec_id is None:
                    ex.sedna_check_rec_id = int(rec_id)  # kalıcı kimlik geri-doldurma (Faz B)
                if ex.bank_transaction_id is None and ex.match_number is None:
                    # Sedna gerçek banka verdi → tahminse de güncelle (inferred=False)
                    bank_changed = bool(bank) and (ex.bank_name != bank or ex.bank_name_inferred)
                    if ex.due_date != due_date or ex.status != new_status or bank_changed:
                        ex.due_date = due_date
                        ex.status = new_status
                        ex.amount_currency = amount_currency
                        ex.currency = curr
                        if bank:
                            ex.bank_name = bank
                            ex.bank_name_inferred = False
                        finance_event_svc.upsert_check(db, ex)
                        return "updated"
                    return "skipped"
                _report_matched_diff(ex)   # eşleşmiş çekte sapma → sessiz atlama yerine kayıt
                return "skipped"
            # Bu dedup-key (no,vendor,para,tutar) yok. Ama AYNI (no,vendor,vade) UNIQUE
            # üçlüsünde bir kayıt olabilir → tutar/para BİRİMİ kaymış (ör. PEKSAN 0353816
            # bizde 30.000 TL sanılmış, Sedna'da 30.000 EUR = 1.596.726 TL). Eşleşmemişse
            # Sedna'ya HİZALA (INSERT yerine UPDATE) — aksi halde UNIQUE çakışıp sessizce
            # atlanır ve yanlış tutar kalıcı olur (nakit akım eksik). Eşleşmişe DOKUNMA
            # (mutabık verimiz korunur, ör. 714659 paid+banka-eşleşmiş EUR/TL etiketi).
            drift = db.query(Check).filter(
                Check.check_no == check_no,
                Check.vendor_code == vendor_code,
                Check.due_date == due_date,
            ).first()
            if drift is not None and drift.bank_transaction_id is None and drift.match_number is None:
                if rec_id is not None and drift.sedna_check_rec_id is None:
                    drift.sedna_check_rec_id = int(rec_id)
                drift.amount_tl = amount_tl
                drift.amount_currency = amount_currency
                drift.currency = curr
                drift.status = new_status
                if bank:
                    drift.bank_name = bank
                    drift.bank_name_inferred = False
                finance_event_svc.upsert_check(db, drift)
                existing[key] = drift
                return "updated"
            if drift is not None:
                _report_matched_diff(drift)    # eşleşmiş çekte tutar/para kayması → kayıt
                return "skipped"               # eşleşmiş çek → dokunma (benign)
            chk = Check(
                upload_id=upload_id,
                check_type=None,
                check_no=check_no,
                vendor_code=vendor_code,
                vendor_name=(r.get("vendor_name") or "").strip() or check_no,
                bank_name=bank,                   # çekin ödeneceği banka (Sedna AccCheck.Bank)
                city=(r.get("city") or "").strip() or None,
                due_date=due_date,
                amount_tl=amount_tl,
                currency=curr,
                amount_currency=amount_currency,
                transaction_type="Verilen Çek",
                status=new_status,
                sedna_check_rec_id=int(rec_id) if rec_id is not None else None,
            )
            db.add(chk)
            db.flush()
            finance_event_svc.upsert_check(db, chk)
            existing[key] = chk
            return "new"
    except IntegrityError:
        logger.warning("Çek kısıt çakışması, atlandı: no=%s vendor=%s vade=%s tutar=%s %s",
                       check_no, vendor_code, due_date, amount_tl, curr)
        return "skipped"


def run_check_import(db: Session, current_user: User, ip=None) -> dict:
    """Sedna'dan verilen çekleri çek (320 satıcı + 159 avans + 335 personel/ortak) + dedup ile içe aktar.

    **Dedup key: (check_no, vendor_code, currency, NATIVE tutar)** — `due_date` ANAHTARDA YOK. Sedna'da
    çekin vadesi değişince (yeniden vadelendirme) yeni kayıt değil **mevcut kaydın güncellenmesi** gerekir;
    tutar yeniden vadelendirmede sabittir ama aynı no'lu farklı çekleri ayırır. Mevcut çek **banka/cari
    eşleşmesi yoksa** vade + durum Sedna'dan güncellenir; eşleşmişe dokunulmaz. Vade değişiminden kalan
    eşleşmemiş mükerrerler temizlenir (geçmiş kayıtların hayalet gösterimi engellenir).

    **Tutar-kayması iyileştirmesi:** dedup-key bulunamayıp aynı `(check_no, vendor_code, due_date)` UNIQUE
    üçlüsünde EŞLEŞMEMİŞ bir kayıt varsa (tutar/para birimi bizde bozuk), INSERT yerine Sedna'ya hizalanır
    — aksi halde UNIQUE çakışıp sessizce atlanır ve yanlış tutar kalıcı olurdu (ör. PEKSAN 0353816 bizde
    30.000 TL sanılmış, Sedna'da 30.000 EUR=1.596.726 TL). Eşleşmiş kayda dokunulmaz (mutabık veri korunur).

    Sonunda banka eşleştirme çalışır. Servis fonksiyonu (HTTP'siz, broadcast'siz) — endpoint + merkezi sync ortak.
    """
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        rows = fetch_issued_checks()
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Sedna çek sorgu hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Sedna çek verisi alınamadı. Lütfen tekrar deneyin.")

    if not rows:
        raise HTTPException(status_code=400, detail="Sedna'dan verilen çek alınamadı (0 satır).")

    upload = CheckUpload(
        file_name=f"Sedna çek içe aktarma · {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}",
        file_url="sedna://import",
        uploaded_by=current_user.id,
    )
    db.add(upload)
    db.flush()

    # Mevcut çekler + vade değişiminden kalan eşleşmemiş mükerrerleri tespit et (temizlik için).
    existing, stale_dupes = _build_existing_and_stale(db)

    new_count = updated_count = skipped_count = removed_dupes = 0
    check_diff_ids: set = set()  # Faz B: eşleşmiş çeklerde raporlanan Sedna sapmaları
    try:
        # Vade değişiminden kalan eşleşmemiş mükerrerleri ÖNCE temizle — güncelleme döngüsünde
        # mevcut kaydı yeni vadeye çekerken UNIQUE(check_no,vendor_code,due_date) çakışmasını önler.
        for d in stale_dupes:
            finance_event_svc.invalidate(db, "check", d.id)
            db.delete(d)
            removed_dupes += 1
        if removed_dupes:
            db.flush()

        for r in rows:
            outcome = _import_one_check_row(db, r, upload.id, existing, diff_ids=check_diff_ids)
            if outcome == "new":
                new_count += 1
            elif outcome == "updated":
                updated_count += 1
            else:
                skipped_count += 1

        upload.total_checks = len(rows)
        upload.new_checks = new_count
        upload.skipped_checks = skipped_count
        # Sedna = tek doğru kaynak: Sedna'da olmayan eşleşmemiş typo/sütun-kayması mükerrerlerini sil
        swept_count = _sweep_stale_checks(db, rows)
        # Bankası boş çekleri komşu çek-no'larından tahmin et (Sedna güncellemeleri + süpürme bittikten SONRA)
        inferred_count = infer_check_banks(db)
        # Faz B: bu koşuda artık raporlanmayan eşleşmiş-çek sapmalarını otomatik kapat
        from app.services.sedna_recon_service import close_stale_entity_diffs
        close_stale_entity_diffs(db, "check", check_diff_ids)
        # Olası check_no↔açıklama-no uyuşmazlıklarını tespit et + uyar (düzeltmez — insan kararı)
        anomalies = detect_check_no_mismatches(db)
        if anomalies:
            logger.warning("Olası çek-no uyuşmazlığı (%d): %s", len(anomalies),
                           ", ".join(f"{a['check_no']}≠{a['description_no']}" for a in anomalies[:20]))
        log_action(
            db, current_user.id, "create", "check_upload", entity_id=upload.id,
            details=f"Sedna çek içe aktarma: {new_count} yeni, {updated_count} güncel (vade/durum), "
                    f"{removed_dupes} mükerrer temizlendi, {swept_count} bayat süpürüldü, "
                    f"{skipped_count} atlandı, {inferred_count} banka tahmini",
            ip_address=ip,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Sedna çek içe aktarma DB hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Çek içe aktarma sırasında veritabanı hatası oluştu.")

    # Yeni/güncellenen çekleri MEVCUT banka hareketleriyle eşleştir: ekstre daha önce
    # yüklenmiş olabilir (matcher yalnız ekstre yüklemede çalışıyordu) — banka kanıtı
    # varsa çek "ödendi" olur (Sedna ödemeyi henüz işlememiş olsa bile).
    matched = 0
    try:
        matched = _match_checks_to_bank(db).get("matched", 0)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Sedna çek import sonrası banka eşleştirme hatası: %s", e)

    return {
        "upload_id": upload.id,
        "total_fetched": len(rows),
        "new_checks": new_count,
        "updated_checks": updated_count,
        "removed_dupes": removed_dupes,
        "swept_stale": swept_count,
        "skipped_checks": skipped_count,
        "matched_to_bank": matched,
        "number_anomalies": len(anomalies),
    }
