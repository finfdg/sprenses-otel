"""Banka ↔ Sedna mutabakat motoru (accounting.mutabakat — Uyuşmayan Veriler).

Kural hiyerarşisi (kullanıcı kararı, 2026-07-11): **banka ekstresi HER ZAMAN doğru** —
motor hiçbir bank_transactions satırını DEĞİŞTİRMEZ, yalnız sınıflandırır. Sedna
girişleri geç (p90=27 gün) ve hatalı (fişlerin %36'sı sonradan düzeltiliyor)
olabildiğinden uyuşmazlıklar kalıcı kayda yazılır; Sedna sonradan girilince /
düzeltilince kayıt OTOMATİK kapanır (resolution='auto') ve açık listeden düşer.

3 geçişli, adet-duyarlı eşleştirme (canlı ölçüm: geçiş 1 tek başına Sedna
satırlarının ~%97'sini kapatır):
  1. (tarih, yönlü tutar) anahtarında k↔k adet eşleme (maaş serisi gibi aynı-tutar
     mükerrer satırlar adetle korunur; Sedna adedi fazlaysa fark = mükerrer şüphesi)
  2. ±3 gün pencere (canlı veride tek istisna +3 gündü; genişi yanlış-pozitif üretir)
  3. Gün-içi küçük küme toplamı (k≤4, iki yönlü): banka 1 ↔ Sedna N (KDV+damga
     bölmesi) ve banka N ↔ Sedna 1 (ücret+BSMV → tek satır)

Nakit-dışı Sedna satırları (ay sonu kur farkı değerlemesi: Owner.Type=4 veya dövizde
Rate=0 & CurrDebit=CurrCredit=0) eşleştirme evrenine ALINMAZ — bankada karşılığı
olmayan defter-içi düzeltmedir; filtrelenmezse her ay sonu sahte uyuşmazlık üretir.

Koşu bütünlüğü: Sedna verisi TEK sorguyla gelir — tünel koparsa SednaUnavailable
yükselir ve HİÇBİR kayıt değiştirilmez (kısmi veriyle sahte uyuşmazlık yazılmaz).

Router (accounting/mutabakat.py) ve onay executor'ı AYNI fonksiyonları çağırır
(CLAUDE.md D1-2 ortak-service deseni).
"""
import logging
import re
from datetime import date, datetime, timedelta
from itertools import combinations
from typing import Callable, Dict, List, Optional, Tuple

import pytz
from sqlalchemy.orm import Session

from app.constants import ReconStatus
from app.models import BankAccount, BankTransaction, SednaBankRecon, SednaReconRun
from app.models.sedna_recon import RESOLUTION_AUTO, RESOLUTION_IGNORED, RESOLUTION_MANUAL
from app.utils import sedna_client
from app.utils.text_match import _norm_tokens

logger = logging.getLogger(__name__)

tz_istanbul = pytz.timezone("Europe/Istanbul")

# Eşleştirme parametreleri (tek yerde — bkz. docs/modules/sedna-mutabakat.md)
DATE_WINDOW_DAYS = 3          # geçiş 2 penceresi
SUBSET_MAX_K = 4              # geçiş 3 küme boyutu üst sınırı
SUBSET_TOLERANCE = 0.02       # küme toplamı toleransı (kuruş yuvarlaması)
SUBSET_DAY_CAP = 12           # aynı günde bu kadardan çok aday varsa kombinasyon denenmez
DEFAULT_WINDOW_DAYS = 45      # varsayılan tarama penceresi (giriş gecikmesi p90=27 gün)
PENDING_ALERT_DAYS = 15       # bu yaştan eski 'Sedna bekliyor' bildirim konusu olur

# Sedna Curr değeri 'TRY' bilmez — hesap para birimi çevrimi
_CURRENCY_TO_SEDNA = {"TRY": "TL"}

_DIGIT_GROUP_RE = re.compile(r"\d{6,}")


def _today() -> date:
    """İstanbul-açık bugün (sunucu UTC — TZ drop-in'e örtük güvenme, CLAUDE.md)."""
    return datetime.now(tz_istanbul).date()


def _r2(x) -> float:
    return round(float(x or 0), 2)


# ─── Hesap eşleme önerileri ─────────────────────────────────────────────────

def suggest_account_mappings(db: Session, leafs: Optional[List[dict]] = None) -> dict:
    """bank_accounts ↔ Sedna 102 leaf eşleme önerileri.

    Sedna'da IBAN alanları fiilen boş olduğundan anahtar: Remark'a gömülü hesap
    numarası (≥6 haneli rakam grubu, bizim IBAN/hesap-no rakamlarında geçmeli) +
    banka adı token kesişimi + para birimi. `leafs` test için enjekte edilebilir.
    """
    if leafs is None:
        leafs = sedna_client.fetch_bank_leaf_accounts()
    # Leaf = 3+ nokta (102.02.03.0002); parent satırlar elenir
    leafs = [l for l in leafs if (l.get("code") or "").count(".") >= 3]

    accounts = db.query(BankAccount).filter(BankAccount.is_active == True).all()  # noqa: E712
    used_codes = {a.sedna_account_code for a in accounts if a.sedna_account_code}

    suggestions = []
    suggested_codes = set()
    for acc in accounts:
        our_digits = re.sub(r"\D", "", (acc.iban or "")) + "|" + re.sub(r"\D", "", (acc.account_no or ""))
        our_alnum = re.sub(r"[^0-9A-Za-z]", "", (acc.account_no or "")).upper()
        acc_ccy = _CURRENCY_TO_SEDNA.get(acc.currency or "TRY", acc.currency or "TRY")
        bank_tokens = _norm_tokens(acc.bank_name or "")

        best = None
        for leaf in leafs:
            code, remark = leaf.get("code") or "", leaf.get("remark") or ""
            if code in used_codes and code != acc.sedna_account_code:
                continue
            score = 0
            reasons = []
            # Rakam grubu eşleşmesi (ana sinyal)
            for grp in _DIGIT_GROUP_RE.findall(remark):
                if grp in our_digits or (our_alnum and grp in our_alnum):
                    score += 60
                    reasons.append(f"hesap no {grp}")
                    break
            # Banka adı token kesişimi
            if bank_tokens & _norm_tokens(remark):
                score += 25
                reasons.append("banka adı")
            # Para birimi
            if (leaf.get("curr") or "TL").strip().upper() == acc_ccy:
                score += 15
                reasons.append("para birimi")
            if best is None or score > best["score"]:
                best = {"code": code, "remark": remark, "curr": leaf.get("curr"),
                        "score": score, "reason": " + ".join(reasons)}
        if best is not None and best["score"] >= 60:
            suggested_codes.add(best["code"])
        suggestions.append({
            "account_id": acc.id,
            "bank_name": acc.bank_name,
            "iban": acc.iban,
            "currency": acc.currency,
            "current_code": acc.sedna_account_code,
            "confirmed": bool(acc.sedna_code_confirmed),
            "suggestion": best if (best and best["score"] >= 60 and not acc.sedna_account_code) else None,
        })

    mapped = {a.sedna_account_code for a in accounts if a.sedna_account_code}
    unmatched_leafs = [l for l in leafs if l["code"] not in mapped and l["code"] not in suggested_codes]
    return {"accounts": suggestions, "unmatched_sedna": unmatched_leafs}


def set_account_mapping(db: Session, account_id: int, sedna_account_code: Optional[str],
                        confirmed: bool) -> BankAccount:
    """Hesabın Sedna kodunu ata/onayla/temizle (router + onay executor ORTAK)."""
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise ValueError(f"Banka hesabı bulunamadı: {account_id}")
    code = (sedna_account_code or "").strip() or None
    if code is not None:
        sedna_client._safe_codes([code])  # karakter doğrulaması (harf/rakam/nokta)
        if not code.startswith("102"):
            raise ValueError("Sedna banka hesabı kodu 102 ile başlamalıdır")
    acc.sedna_account_code = code
    acc.sedna_code_confirmed = bool(confirmed) if code else False
    db.flush()
    return acc


# ─── Sedna satır sınıflandırma ──────────────────────────────────────────────

def classify_sedna_row(row: dict, account_currency: str) -> Tuple[str, float]:
    """Sedna fiş satırı → ('cash'|'valuation', işaretli tutar hesap para biriminde).

    İşaret kuralı (canlı doğrulandı): bizim amount>0 (giriş) = Sedna 102 Borç.
    Döviz hesabında tutar CurrDebit/CurrCredit; TL hesapta Debit/Credit.
    """
    sedna_ccy = _CURRENCY_TO_SEDNA.get(account_currency or "TRY", account_currency or "TRY")
    if sedna_ccy == "TL":
        amount = _r2(row.get("debit")) - _r2(row.get("credit"))
        kind = "valuation" if row.get("owner_type") == 4 else "cash"
        return kind, round(amount, 2)
    amount = _r2(row.get("curr_debit")) - _r2(row.get("curr_credit"))
    is_valuation = row.get("owner_type") == 4 or (
        _r2(row.get("rate")) == 0 and _r2(row.get("curr_debit")) == 0 and _r2(row.get("curr_credit")) == 0
    )
    return ("valuation" if is_valuation else "cash"), round(amount, 2)


# ─── Eşleştirme çekirdeği (saf — test edilebilir) ───────────────────────────

def _match_account(bank_rows: List[dict], sedna_rows: List[dict],
                   sedna_max_date: Optional[date]) -> List[dict]:
    """Tek hesabın açık bulgularını üret. Girdi:
    bank_rows: {id, date, amount, description} (işaretli tutar)
    sedna_rows: {rec_id, owner_id, voucher, fiche_date, amount, remark, record_user, change_date}
    Dönen bulgu: {status, btx_id?, sedna?, amount, event_date, description?, ...}
    """
    b_open = list(bank_rows)
    s_open = list(sedna_rows)

    # Geçiş 1: (tarih, tutar) k↔k adet eşleme
    def _key(d, a):
        return (d, round(a, 2))

    from collections import defaultdict
    b_by_key: Dict[tuple, list] = defaultdict(list)
    s_by_key: Dict[tuple, list] = defaultdict(list)
    for b in b_open:
        b_by_key[_key(b["date"], b["amount"])].append(b)
    for s in s_open:
        s_by_key[_key(s["fiche_date"], s["amount"])].append(s)

    findings: List[dict] = []
    b_rest: List[dict] = []
    s_rest: List[dict] = []
    dup_suspects: List[dict] = []
    for key, blist in b_by_key.items():
        slist = s_by_key.pop(key, [])
        n = min(len(blist), len(slist))
        # n adet eşleşti (kayıt üretilmez); artanlar havuzda
        b_rest.extend(blist[n:])
        if len(slist) > len(blist) and blist:
            # Sedna adedi fazla + bankada bu anahtar VAR → mükerrer giriş şüphesi
            dup_suspects.extend(slist[n:])
        else:
            s_rest.extend(slist[n:])
    for key, slist in s_by_key.items():
        s_rest.extend(slist)

    # Geçiş 2: ±3 gün pencere (aynı tutar, en yakın tarih)
    still_b = []
    for b in b_rest:
        cand = None
        for s in s_rest:
            if round(s["amount"], 2) == round(b["amount"], 2):
                dd = abs((s["fiche_date"] - b["date"]).days)
                if dd <= DATE_WINDOW_DAYS and (cand is None or dd < cand[0]):
                    cand = (dd, s)
        if cand:
            s_rest.remove(cand[1])
        else:
            still_b.append(b)
    b_rest = still_b

    # Yön-tersi: aynı gün + aynı mutlak tutar + zıt işaret (canlı 3 vaka bu desendi)
    still_b = []
    for b in b_rest:
        flip = next((s for s in s_rest
                     if s["fiche_date"] == b["date"] and round(s["amount"], 2) == round(-b["amount"], 2)), None)
        if flip:
            s_rest.remove(flip)
            findings.append({"status": ReconStatus.DIRECTION_FLIP, "btx": b, "sedna": flip})
        else:
            still_b.append(b)
    b_rest = still_b

    # Geçiş 3: gün-içi küme toplamı (k≤4, iki yönlü)
    def _subset_pass(singles: List[dict], pools: List[dict], single_amt, pool_amt, pool_date):
        used_pool_ids = set()
        remaining_singles = []
        for one in singles:
            day = one.get("date") or one.get("fiche_date")
            cands = [p for p in pools if id(p) not in used_pool_ids and pool_date(p) == day]
            if not cands or len(cands) > SUBSET_DAY_CAP:
                remaining_singles.append(one)
                continue
            hit = None
            for k in range(2, min(SUBSET_MAX_K, len(cands)) + 1):
                for combo in combinations(cands, k):
                    if abs(sum(pool_amt(p) for p in combo) - single_amt(one)) <= SUBSET_TOLERANCE:
                        hit = combo
                        break
                if hit:
                    break
            if hit:
                for p in hit:
                    used_pool_ids.add(id(p))
            else:
                remaining_singles.append(one)
        new_pools = [p for p in pools if id(p) not in used_pool_ids]
        return remaining_singles, new_pools, len(pools) - len(new_pools)

    # banka 1 ↔ Sedna N (KDV+damga bölmesi)
    b_rest, s_rest, _ = _subset_pass(
        b_rest, s_rest, lambda b: b["amount"], lambda s: s["amount"], lambda s: s["fiche_date"])
    # banka N ↔ Sedna 1 (ücret+BSMV → tek satır)
    s_rest, b_rest, _ = _subset_pass(
        s_rest, b_rest, lambda s: s["amount"], lambda b: b["amount"], lambda b: b["date"])

    # Kalan sınıflandırma
    for s in dup_suspects:
        findings.append({"status": ReconStatus.DUPLICATE_SUSPECT, "btx": None, "sedna": s})
    for b in b_rest:
        if sedna_max_date is None or b["date"] > sedna_max_date:
            st = ReconStatus.SEDNA_PENDING  # Sedna henüz oraya gelmedi (gecikme)
        else:
            st = ReconStatus.SEDNA_MISSING  # dönem içi, girilmemiş
        findings.append({"status": st, "btx": b, "sedna": None})
    for s in s_rest:
        findings.append({"status": ReconStatus.SEDNA_EXTRA, "btx": None, "sedna": s})

    return findings


# ─── Koşu (fetch + sınıflandır + kalıcılaştır + otomatik kapat) ─────────────

def run_reconciliation(
    db: Session,
    window_days: int = DEFAULT_WINDOW_DAYS,
    triggered_by: Optional[int] = None,
    fetch_rows: Optional[Callable[[List[str], str], List[dict]]] = None,
    fetch_max_dates: Optional[Callable[[List[str]], dict]] = None,
    notify: bool = True,
) -> dict:
    """Mutabakat koşusu. Sedna erişilemezse SednaUnavailable yükselir ve HİÇBİR kayıt
    değiştirilmez. Dönen özet sedna_sync._summarize ile uyumludur."""
    fetch_rows = fetch_rows or sedna_client.fetch_bank_ledger_rows
    fetch_max_dates = fetch_max_dates or sedna_client.fetch_bank_ledger_max_dates

    today = _today()
    window_start = today - timedelta(days=window_days)

    accounts = (
        db.query(BankAccount)
        .filter(BankAccount.is_active == True,  # noqa: E712
                BankAccount.sedna_account_code.isnot(None),
                BankAccount.sedna_code_confirmed == True)  # noqa: E712
        .all()
    )
    total_accounts = db.query(BankAccount).filter(BankAccount.is_active == True).count()  # noqa: E712

    summary = {"accounts_scanned": 0, "accounts_skipped": total_accounts - len(accounts),
               "matched": 0, "open": 0, "new": 0, "auto_closed": 0}
    if not accounts:
        run = SednaReconRun(window_start=window_start, window_end=today, triggered_by=triggered_by,
                            accounts_skipped=summary["accounts_skipped"],
                            note="Eşlenmiş (onaylı) Sedna kodu olan hesap yok")
        db.add(run)
        db.commit()
        return summary

    codes = [a.sedna_account_code for a in accounts]
    # Tek sorgu — kopukta exception yükselir, kayıtlara DOKUNULMAZ (koşu bütünlüğü)
    raw_rows = fetch_rows(codes, window_start.isoformat())
    max_dates = fetch_max_dates(codes)

    rows_by_code: Dict[str, List[dict]] = {}
    for r in raw_rows:
        rows_by_code.setdefault(r["code"], []).append(r)

    now = datetime.now(tz_istanbul)
    new_items: List[SednaBankRecon] = []

    for acc in accounts:
        sedna_cash = []
        for r in rows_by_code.get(acc.sedna_account_code, []):
            kind, amount = classify_sedna_row(r, acc.currency or "TRY")
            if kind != "cash" or amount == 0:
                continue
            sedna_cash.append({
                "rec_id": r.get("rec_id"), "owner_id": r.get("owner_id"),
                "voucher": r.get("voucher"), "fiche_date": r.get("fiche_date"),
                "amount": amount, "remark": r.get("remark"),
                "record_user": r.get("record_user"), "change_date": r.get("change_date"),
            })
        bank_rows = [
            {"id": t.id, "date": t.date, "amount": _r2(t.amount), "description": t.description}
            for t in db.query(BankTransaction)
            .filter(BankTransaction.account_id == acc.id, BankTransaction.date >= window_start)
            .all()
        ]

        findings = _match_account(bank_rows, sedna_cash, max_dates.get(acc.sedna_account_code))
        summary["accounts_scanned"] += 1
        summary["matched"] += len(bank_rows) - sum(1 for f in findings if f["btx"])

        # Kalıcılaştırma: kimlik = (btx_id, sedna_rec_id)
        open_rows = (
            db.query(SednaBankRecon)
            .filter(SednaBankRecon.bank_account_id == acc.id,
                    SednaBankRecon.resolved_at.is_(None),
                    SednaBankRecon.event_date >= window_start)
            .all()
        )
        ignored_ids = {
            (r.bank_transaction_id, r.sedna_trans_rec_id)
            for r in db.query(SednaBankRecon)
            .filter(SednaBankRecon.bank_account_id == acc.id,
                    SednaBankRecon.resolution == RESOLUTION_IGNORED)
            .all()
        }
        existing = {(r.bank_transaction_id, r.sedna_trans_rec_id): r for r in open_rows}
        seen_keys = set()

        for f in findings:
            b, s = f.get("btx"), f.get("sedna")
            key = (b["id"] if b else None, s["rec_id"] if s else None)
            if key in ignored_ids:
                continue  # kullanıcı bilinçli yoksaydı — yeniden açma
            seen_keys.add(key)
            row = existing.get(key)
            if row:
                row.status = f["status"]
                row.last_seen_at = now
                if s:
                    row.sedna_change_date = s.get("change_date")
                continue
            item = SednaBankRecon(
                bank_account_id=acc.id,
                bank_transaction_id=b["id"] if b else None,
                sedna_trans_rec_id=s["rec_id"] if s else None,
                sedna_owner_id=s["owner_id"] if s else None,
                sedna_voucher=str(s["voucher"]) if s and s.get("voucher") is not None else None,
                status=f["status"],
                amount=(b["amount"] if b else s["amount"]),
                currency=acc.currency or "TRY",
                event_date=(b["date"] if b else s["fiche_date"]),
                description=(b.get("description") or "")[:500] if b else None,
                sedna_description=(s.get("remark") or "")[:500] if s else None,
                sedna_record_user=(s.get("record_user") or None) if s else None,
                sedna_change_date=s.get("change_date") if s else None,
                detected_at=now, last_seen_at=now,
            )
            db.add(item)
            new_items.append(item)

        # Bulgularda artık görünmeyen açık kayıt → OTOMATİK KAPANIR (Sedna girildi/düzeltildi)
        for key, row in existing.items():
            if key not in seen_keys:
                row.status = ReconStatus.MATCHED
                row.resolution = RESOLUTION_AUTO
                row.resolved_at = now
                summary["auto_closed"] += 1

    db.flush()
    summary["new"] = len(new_items)
    summary["open"] = (
        db.query(SednaBankRecon).filter(SednaBankRecon.resolved_at.is_(None)).count()
    )

    run = SednaReconRun(
        window_start=window_start, window_end=today, triggered_by=triggered_by,
        accounts_scanned=summary["accounts_scanned"], accounts_skipped=summary["accounts_skipped"],
        matched_count=summary["matched"], open_count=summary["open"],
        new_count=summary["new"], auto_closed_count=summary["auto_closed"],
    )
    db.add(run)
    db.commit()

    if notify and new_items:
        _notify_new_items(db, new_items)
    return summary


_CRITICAL_STATUSES = frozenset({
    ReconStatus.DIRECTION_FLIP, ReconStatus.DUPLICATE_SUSPECT,
    ReconStatus.SEDNA_MISSING, ReconStatus.SEDNA_EXTRA,
})

_STATUS_LABELS = {
    ReconStatus.SEDNA_PENDING: "Sedna bekliyor",
    ReconStatus.SEDNA_MISSING: "Sedna'da eksik",
    ReconStatus.SEDNA_EXTRA: "Sedna'da fazla",
    ReconStatus.DIRECTION_FLIP: "Yön ters",
    ReconStatus.DUPLICATE_SUSPECT: "Mükerrer şüphesi",
    ReconStatus.MATCHED: "Mutabık",
}


def _notify_new_items(db: Session, items: List[SednaBankRecon]) -> None:
    """Yeni KRİTİK uyuşmazlıklar için tek toplu bildirim (accounting.mutabakat görenlere)."""
    critical = [i for i in items if i.status in _CRITICAL_STATUSES]
    if not critical:
        return
    try:
        from app.models import Module, RoleModulePermission, User
        from app.utils.notification import create_and_send_notifications_sync

        mod = db.query(Module).filter(Module.code == "accounting.mutabakat").first()
        if not mod:
            return
        rows = (
            db.query(User.id)
            .join(RoleModulePermission, User.role_id == RoleModulePermission.role_id)
            .filter(RoleModulePermission.module_id == mod.id,
                    RoleModulePermission.can_view == True,  # noqa: E712
                    User.is_active == True)  # noqa: E712
            .all()
        )
        user_ids = [r.id for r in rows]
        if not user_ids:
            return
        by_status: Dict[str, int] = {}
        for i in critical:
            by_status[i.status] = by_status.get(i.status, 0) + 1
        parts = [f"{n} {_STATUS_LABELS.get(st, st)}" for st, n in sorted(by_status.items())]
        create_and_send_notifications_sync(
            db, user_ids, type="recon",
            title="Sedna uyuşmazlığı tespit edildi",
            body=" · ".join(parts) + " — Uyuşmayan Veriler ekranından inceleyin",
            link="/dashboard/muhasebe/mutabakat",
        )
        now = datetime.now(tz_istanbul)
        for i in critical:
            i.notified_at = now
        db.commit()
    except Exception as e:  # bildirim hatası koşuyu düşürmesin
        logger.error("Mutabakat bildirimi gönderilemedi: %s", e)


# ─── Kullanıcı aksiyonları (router + onay executor ORTAK) ───────────────────

def resolve_recon_item(db: Session, item_id: int, action: str,
                       note: Optional[str], user_id: Optional[int]) -> SednaBankRecon:
    """Uyuşmazlık kaydını çöz/yoksay/yeniden aç.

    action: 'resolve' (elle çözüldü) | 'ignore' (bilinçli fark, koşularda yeniden
    açılmaz) | 'reopen' (kapanmışı geri aç).
    """
    item = db.query(SednaBankRecon).filter(SednaBankRecon.id == item_id).first()
    if not item:
        raise ValueError(f"Mutabakat kaydı bulunamadı: {item_id}")
    now = datetime.now(tz_istanbul)
    if action == "resolve":
        item.resolution = RESOLUTION_MANUAL
        item.resolved_at = now
        item.resolved_by = user_id
        item.resolution_note = (note or "")[:500] or None
    elif action == "ignore":
        item.resolution = RESOLUTION_IGNORED
        item.resolved_at = now
        item.resolved_by = user_id
        item.resolution_note = (note or "")[:500] or None
    elif action == "reopen":
        item.resolution = None
        item.resolved_at = None
        item.resolved_by = None
        item.resolution_note = None
    else:
        raise ValueError(f"Geçersiz aksiyon: {action}")
    db.flush()
    return item
