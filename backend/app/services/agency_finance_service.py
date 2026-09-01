"""Aylık acente finans görünümü domain servisi (HTTP'siz, salt-okuma).

Sedna'dan yerel aynalara alınan 120 fatura/tahsilat ve 340 avans hareketlerini,
PMS rezervasyonlarını ve yerel vade tanımlarını tek ``ay × acente`` veri kümesinde
birleştirir. Tüm tutarlar karşılaştırılabilir olması için EUR olarak döner.

KUR TARİHİ KURALI (2026-09-01, denetim O1):
- AKIŞLAR (alınan/mahsup avans, haricen tahsilat, kesilen fatura) hareketin KENDİ
  tarihindeki TCMB alış kuruyla çevrilir (`_to_eur_on` + `utils/fx_rates.RateBook`) —
  T-Hesap / runway / grafik `_event_eur` ile aynı kural; USD/GBP çapraz (native × kur / EUR).
- STOKLAR (açık alacak kalanı, kalan avans havuzu) BUGÜNKÜ kurla değerlenir (`_to_eur_today`):
  tahsil edilecek EUR tahsilat günündeki kura bağlıdır; Hak Ediş ve kontrat projeksiyonu da
  açık alacağı böyle ölçer.
- Kur bulunamayan hareket 1 TL = 1 EUR sayılmaz: 0 yazılır + `source_counts.skipped_no_rate`.
Önceki davranış (05–31 Ağu): tüm TL/USD tutarlar bugünkü kurla → Ocak TL faturası T-Hesap'tan
~%20 düşük görünüyordu (TL değer kaybı kadar).
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.reservation import Reservation
from app.models.sales_invoice import (
    SalesAdvance,
    SalesAdvanceTransaction,
    SalesCollection,
    SalesInvoice,
)
from app.services.agency_settlement_service import _agency_group_maps
from app.services.receivable_service import _group_map, _latest_rates, get_terms_map
from app.services.sales_invoice_service import _compute_cached, _f
from app.utils.fx_rates import CROSS_EUR_CURRENCIES, RateBook
from app.utils.text_match import _norm_tokens

_MONTH_NAMES = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
_OTHER_ID = 0
_OTHER_NAME = "Diğer / Eşleşmeyen"
_MONEY_KEYS = (
    "advance_received", "advance_applied", "collections", "reservation_amount", "invoiced_amount",
    "overdue", "open_due", "projected_gross", "projected_advance",
    "projected_due", "month_end_receivable",
)


def _empty_metrics() -> dict:
    return {
        "advance_received": 0.0,
        "advance_applied": 0.0,
        "collections": 0.0,
        "reservation_amount": 0.0,
        "invoiced_amount": 0.0,
        "reservation_count": 0,
        "overdue": 0.0,
        "open_due": 0.0,
        "projected_gross": 0.0,
        "projected_advance": 0.0,
        "projected_due": 0.0,
        "month_end_receivable": 0.0,
    }


def _round_metrics(metrics: dict) -> dict:
    out = {key: round(float(metrics.get(key, 0) or 0), 2) for key in _MONEY_KEYS}
    out["reservation_count"] = int(metrics.get("reservation_count", 0) or 0)
    return out


def _add(target: dict, key: str, amount: float) -> None:
    target[key] = float(target.get(key, 0) or 0) + float(amount or 0)


def _cur(currency: Optional[str]) -> str:
    return (currency or "TL").strip().upper() or "TL"


def _to_eur_today(native: float, amount_tl: float, currency: str, eur_rate: float,
                  rates: Optional[dict] = None) -> float:
    """STOK değerlemesi — BUGÜNKÜ TCMB kuruyla EUR (açık alacak kalanı gibi "hâlâ tahsil
    edilecek" tutarlar). Tahsil edilecek EUR karşılığı tahsilat günündeki kura bağlı olduğundan
    en iyi tahmin bugünkü kurdur; Hak Ediş (`receivable_service`) ve kontrat projeksiyonu da açık
    alacağı böyle değerler. Geçmiş AKIŞLAR için `_to_eur_on` kullanılır (denetim O1).

    EUR kaydında native tutar kur farkından etkilenmez. Diğer hareketlerde fişteki gerçek TL
    karşılığı kullanılır; TL yoksa native × bugünkü kur (bilinmeyen döviz → 0, 1:1 sayılmaz).
    """
    cur = _cur(currency)
    if cur == "EUR" and _f(native) > 0:
        return round(_f(native), 2)
    if _f(amount_tl) > 0 and eur_rate > 0:
        return round(_f(amount_tl) / eur_rate, 2)
    if rates and eur_rate > 0 and _f(native) > 0:
        fx = float(rates.get(cur, 0) or 0)
        return round(_f(native) * fx / eur_rate, 2) if fx > 0 else 0.0
    return 0.0


def _to_eur_on(book: RateBook, native: float, amount_tl: float, currency: str,
               on_date: Optional[date]) -> Optional[float]:
    """AKIŞ değerlemesi — hareketi KENDİ TARİHİNDEKİ TCMB kuruyla EUR'a çevir (2026-09-01,
    denetim O1: T-Hesap / runway / grafik `_event_eur` ile aynı kural; önceden bugünkü kur
    kullanılıyordu ve aynı TL fatura iki ekranda farklı EUR gösteriyordu).

    EUR → native aynen · USD/GBP → native × {kur}(t) / EUR(t) (çapraz; amount_try'a bakılmaz) ·
    TL → fişteki TL / EUR(t) · çapraz kur yoksa TL bacağına düşer · EUR kuru da yoksa **None**
    (çağıran `skipped_no_rate` sayar; 1 TL = 1 EUR varsayımı YAPILMAZ).
    """
    cur = _cur(currency)
    if cur == "EUR" and _f(native) > 0:
        return round(_f(native), 2)
    if on_date is None:
        return None
    if cur in CROSS_EUR_CURRENCIES and _f(native) > 0:
        value = book.to_eur(_f(native), cur, on_date)
        if value is not None:
            return round(value, 2)
    if _f(amount_tl) > 0:
        eur = book.eur(on_date)
        return round(_f(amount_tl) / eur, 2) if eur else None
    if _f(native) > 0:  # TL kaydında yalnız native gelebilir (özet fallback) → TL'dir
        value = book.to_eur(_f(native), cur, on_date)
        return None if value is None else round(value, 2)
    return 0.0


def _firm_tokens(db: Session) -> dict:
    """120 cari kodu → muhasebe adı token'ları (340 adını cari koda bağlamak için)."""
    names: dict = {}
    for code, name in db.query(SalesInvoice.customer_code, SalesInvoice.customer_name).all():
        if code and name:
            names[code] = name
    for code, name in db.query(SalesCollection.customer_code, SalesCollection.customer_name).all():
        if code and name and code not in names:
            names[code] = name
    return {code: _norm_tokens(name or code) for code, name in names.items()}


def _match_advance_group(name: str, firm_tokens: dict, code_to_gid: dict) -> int:
    """340 muhasebe adını en güçlü 120 cari adıyla, oradan acente grubuyla eşleştir."""
    advance_tokens = _norm_tokens(name or "")
    best_code = None
    best_score = 0
    for code, tokens in firm_tokens.items():
        if not advance_tokens or not tokens:
            continue
        if advance_tokens <= tokens or tokens <= advance_tokens:
            score = len(advance_tokens & tokens) + 10
        else:
            overlap = len(advance_tokens & tokens)
            score = overlap if overlap >= 2 else 0
        if score > best_score:
            best_code, best_score = code, score
    return int(code_to_gid.get(best_code, _OTHER_ID))


def compute_agency_finance(
    db: Session,
    year: int,
    today: Optional[date] = None,
) -> dict:
    """Seçili yıl için acente × ay finansal takip veri kümesini üret.

    ``month_end_receivable`` iki bileşendir: kullanılmamış 340 avansı önce FIFO mahsup edilmiş
    açık gerçek faturalar (``open_due``) + açık faturalardan artan avansla mahsup edilmiş ileri
    rezervasyon tahmini (``projected_due``). ``overdue``, bu mahsup sırasından sonra kalan açık
    gerçek hak edişlerin vadesi geçmiş alt kümesidir.
    """
    today = today or date.today()
    rates = _latest_rates(db)
    eur_rate = float(rates.get("EUR", 0) or 0)
    book = RateBook.load(db)  # akışlar için tarih bazlı kur defteri (tek sorgu + bisect)
    skipped_no_rate = 0

    def _flow(native, amount_tl, currency, on_date) -> float:
        """Akış kalemi → EUR (hareket tarihi kuru); kur yoksa 0 + sayaç (boşluk raporda görünür)."""
        nonlocal skipped_no_rate
        value = _to_eur_on(book, native, amount_tl, currency, on_date)
        if value is None:
            skipped_no_rate += 1
            return 0.0
        return value
    group_meta, member_to_gid = _agency_group_maps(db)
    group_meta[_OTHER_ID]["name"] = _OTHER_NAME
    customer_group = {code: int(meta["id"]) for code, meta in _group_map(db).items()}
    firm_tokens = _firm_tokens(db)

    # Her acente için 12 aylık boş matris. Veri gelmeyen tanımlı gruplar yanıta eklenmez.
    matrix: dict = {
        gid: [_empty_metrics() for _ in range(12)] for gid in group_meta
    }

    # Grup içi üye kırılımı (yıllık toplam): kaynak kimliği kaynağa göre değişir —
    # rezervasyonlarda PMS acente adı, fatura/tahsilatta Sedna 120 cari adı, avansta 340
    # hesap adı. Aynı üyenin farklı yazımları ayrı satır olarak listelenir (bilinçli:
    # kullanıcı grubun hangi kaynaklardan beslendiğini görür).
    member_matrix: dict = {gid: {} for gid in group_meta}
    member_labels: dict = {gid: {} for gid in group_meta}

    def _member(gid: int, label: str) -> dict:
        key = (label or "").strip().upper() or "BİLİNMEYEN"
        slots = member_matrix[gid]
        if key not in slots:
            slots[key] = _empty_metrics()
            member_labels[gid][key] = (label or "").strip() or "Bilinmeyen"
        return slots[key]

    # ── 340 alınan avans hareketleri ────────────────────────────
    # AKIŞ (aylık advance_received/applied): hareketin KENDİ tarihindeki kur (`_flow`, denetim O1).
    # HAVUZ (kalan avans stoku): para birimi bazında NATIVE biriktirilir, BUGÜNKÜ kurla EUR'a
    # çevrilir — ileri fatura/rezervasyona mahsup edilecek değer bugünün kuruyla ölçülür (Hak Ediş
    # `advance_received_tl` yaklaşımı). Aynı 340 adı için grup eşleşmesi memo'lanır (denetim O3).
    pool_native: dict = {gid: defaultdict(float) for gid in group_meta}
    group_memo: dict = {}

    def _advance_gid(label: str) -> int:
        if label not in group_memo:
            group_memo[label] = _match_advance_group(label, firm_tokens, customer_group)
        return group_memo[label]

    advance_rows = db.query(SalesAdvanceTransaction).all()
    last_sync_at = None
    for tx in advance_rows:
        gid = _advance_gid(tx.name or tx.code)
        pool_native[gid][_cur(tx.currency)] += _f(tx.received) - _f(tx.consumed)
        if tx.transaction_date and tx.transaction_date.year == year:
            received = _flow(tx.received, tx.received_tl, tx.currency, tx.transaction_date)
            consumed = _flow(tx.consumed, tx.consumed_tl, tx.currency, tx.transaction_date)
            month = matrix[gid][tx.transaction_date.month - 1]
            _add(month, "advance_received", received)
            _add(month, "advance_applied", consumed)
            member = _member(gid, tx.name or tx.code)
            _add(member, "advance_received", received)
            _add(member, "advance_applied", consumed)
        if tx.created_at and (last_sync_at is None or tx.created_at > last_sync_at):
            last_sync_at = tx.created_at

    # İlk deploy sonrası detay senkronu henüz koşmadıysa güncel avans bakiyesi kaybolmasın.
    # Aylık hareket kırılımı yalnız detay snapshot geldikten sonra oluşur.
    if not advance_rows:
        for row in db.query(SalesAdvance).all():
            gid = _advance_gid(row.name or row.code)
            pool_native[gid][_cur(row.currency)] += _f(row.received) - _f(row.consumed)

    advance_balance: dict = {gid: 0.0 for gid in group_meta}
    for gid, per_currency in pool_native.items():
        total = 0.0
        for cur, amount in per_currency.items():
            if abs(amount) < 0.005:
                continue
            if cur == "EUR":
                total += amount
            elif eur_rate > 0:
                fx = float(rates.get(cur, 0) or 0)  # TL/TRY → 1.0; bilinmeyen döviz havuza girmez
                if fx > 0:
                    total += amount * fx / eur_rate
        advance_balance[gid] = round(total, 2)

    # ── 120 haricen tahsilatlar (340 virman/mahsup hariç) ───────
    collection_count = 0
    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    collections = db.query(SalesCollection).filter(
        SalesCollection.collection_date >= start,
        SalesCollection.collection_date < end,
    ).all()
    for collection in collections:
        desc = (collection.description or "").upper()
        if "VİRMAN" in desc or "VIRMAN" in desc:
            continue
        gid = customer_group.get(collection.customer_code, _OTHER_ID)
        value = _flow(
            collection.amount_currency, collection.amount, collection.currency,
            collection.collection_date,
        )
        _add(matrix[gid][collection.collection_date.month - 1], "collections", value)
        _add(_member(gid, collection.customer_name or collection.customer_code), "collections", value)
        collection_count += 1

    # ── PMS rezervasyonları: çıkış ayında ciro/adet ─────────────
    reservations = db.query(Reservation).filter(or_(
        and_(Reservation.checkout_date >= start, Reservation.checkout_date < end),
        Reservation.checkout_date >= today,
    )).all()
    projected: dict = {gid: [] for gid in group_meta}
    selected_reservation_count = 0
    for reservation in reservations:
        gid = member_to_gid.get((reservation.agency or "").strip().upper(), _OTHER_ID)
        amount = _f(reservation.eur_total)
        if reservation.checkout_date.year == year:
            slot = matrix[gid][reservation.checkout_date.month - 1]
            _add(slot, "reservation_amount", amount)
            slot["reservation_count"] += 1
            selected_reservation_count += 1
            member = _member(gid, reservation.agency)
            _add(member, "reservation_amount", amount)
            member["reservation_count"] += 1
        if reservation.checkout_date >= today and amount > 0:
            term_days = int(group_meta[gid].get("term_days", 30) or 0)
            due_date = reservation.checkout_date + timedelta(days=term_days)
            projected[gid].append((due_date, amount, reservation.agency))

    # ── Seçili yılda kesilen acente faturaları: fatura tarihinde brüt tutar ─
    issued_invoices = db.query(SalesInvoice).filter(
        SalesInvoice.is_munferit.is_(False),
        SalesInvoice.invoice_date >= start,
        SalesInvoice.invoice_date < end,
    ).all()
    for invoice in issued_invoices:
        gid = customer_group.get(invoice.customer_code, _OTHER_ID)
        value = _flow(
            invoice.amount_currency, invoice.amount, invoice.currency, invoice.invoice_date,
        )
        _add(matrix[gid][invoice.invoice_date.month - 1], "invoiced_amount", value)
        _add(_member(gid, invoice.customer_name or invoice.customer_code), "invoiced_amount", value)

    # ── Açık gerçek faturalar: kullanılmamış 340 avansı önce bunlara FIFO mahsup et ─
    invoice_map, _ = _compute_cached(db)
    terms = get_terms_map(db)
    open_invoice_count = 0
    overdue_invoice_count = 0
    open_by_group: dict = {gid: [] for gid in group_meta}
    for invoice in db.query(SalesInvoice).filter(SalesInvoice.is_munferit.is_(False)).all():
        status = invoice_map.get(invoice.id, {})
        remaining_tl = round(_f(invoice.amount) - _f(status.get("collected_tl", 0)), 2)
        if remaining_tl <= 0.01:
            continue
        native_total = _f(invoice.amount_currency) or _f(invoice.amount)
        remaining_native = round(native_total - _f(status.get("collected", 0)), 2)
        # STOK: hâlâ tahsil edilecek kalan → bugünkü kur (fatura tarihi kuru değil; docstring)
        remaining_eur = _to_eur_today(
            remaining_native, remaining_tl, invoice.currency, eur_rate, rates,
        )
        gid = customer_group.get(invoice.customer_code, _OTHER_ID)
        due_date = invoice.invoice_date + timedelta(
            days=int(terms.get(invoice.customer_code, 30)),
        )
        due_month = None
        if due_date.year == year:
            due_month = due_date.month
        elif year == today.year and due_date.year < year:
            due_month = 1  # önceki yıldan devreden açık/gecikmiş hak ediş
        open_by_group[gid].append((
            due_date, invoice.invoice_date, invoice.id, remaining_eur, due_month,
            invoice.customer_name or invoice.customer_code,
        ))

    for gid, items in open_by_group.items():
        # Eşleşmeyen 340 bakiyesini farklı carilerin ortak havuzuna dönüştürme.
        balance = max(0.0, advance_balance.get(gid, 0.0)) if gid != _OTHER_ID else 0.0
        for due_date, invoice_date, invoice_id, remaining_eur, due_month, label in sorted(
            items, key=lambda item: (item[0], item[1], item[2]),
        ):
            applied = min(balance, remaining_eur)
            balance = round(balance - applied, 2)
            net = round(remaining_eur - applied, 2)
            if net <= 0.01:
                continue
            if due_month is not None:
                slot = matrix[gid][due_month - 1]
                _add(slot, "open_due", net)
                _add(slot, "month_end_receivable", net)
                member = _member(gid, label)
                _add(member, "open_due", net)
                _add(member, "month_end_receivable", net)
            if due_date < today and due_month is not None:
                _add(matrix[gid][due_month - 1], "overdue", net)
                _add(_member(gid, label), "overdue", net)
                overdue_invoice_count += 1
            open_invoice_count += 1
        advance_balance[gid] = balance

    # ── İleri rezervasyon hak edişleri: açık faturadan artan 340 avansla FIFO mahsup ─
    for gid, items in projected.items():
        # Eşleşmeyen 340 hesaplarını, ilgisiz grup-dışı rezervasyonlara mahsup etme.
        balance = max(0.0, advance_balance.get(gid, 0.0)) if gid != _OTHER_ID else 0.0
        for due_date, gross, label in sorted(items, key=lambda item: item[0]):
            applied = min(balance, gross)
            balance = round(balance - applied, 2)
            net = round(gross - applied, 2)
            if due_date.year != year:
                continue
            slot = matrix[gid][due_date.month - 1]
            _add(slot, "projected_gross", gross)
            _add(slot, "projected_advance", applied)
            _add(slot, "projected_due", net)
            _add(slot, "month_end_receivable", net)
            member = _member(gid, label)
            _add(member, "projected_gross", gross)
            _add(member, "projected_advance", applied)
            _add(member, "projected_due", net)
            _add(member, "month_end_receivable", net)

    # ── Yanıt: acente satırları + ay/genel toplamlar ────────────
    agency_rows = []
    for gid, months in matrix.items():
        rounded_months = []
        totals = _empty_metrics()
        for index, raw in enumerate(months):
            metrics = _round_metrics(raw)
            rounded_months.append({"month": index + 1, "name": _MONTH_NAMES[index], **metrics})
            for key in _MONEY_KEYS:
                _add(totals, key, metrics[key])
            totals["reservation_count"] += metrics["reservation_count"]
        totals = _round_metrics(totals)
        if not any(totals[key] > 0.005 for key in _MONEY_KEYS) and totals["reservation_count"] == 0:
            continue
        members = []
        for key, raw in member_matrix[gid].items():
            member_totals = _round_metrics(raw)
            if (not any(member_totals[k] > 0.005 for k in _MONEY_KEYS)
                    and member_totals["reservation_count"] == 0):
                continue
            members.append({"name": member_labels[gid][key], "totals": member_totals})
        members.sort(key=lambda member: (
            -(member["totals"]["month_end_receivable"] + member["totals"]["reservation_amount"]),
            member["name"],
        ))
        agency_rows.append({
            "agency_id": gid,
            "agency": group_meta[gid]["name"],
            "color": group_meta[gid]["color"],
            "term_days": int(group_meta[gid].get("term_days", 30) or 0),
            "months": rounded_months,
            "totals": totals,
            "members": members,
        })

    agency_rows.sort(key=lambda row: (
        row["agency_id"] == _OTHER_ID,
        -(row["totals"]["month_end_receivable"] + row["totals"]["reservation_amount"]),
        row["agency"],
    ))

    month_rows = []
    grand = _empty_metrics()
    for month_index in range(12):
        totals = _empty_metrics()
        for agency in agency_rows:
            metrics = agency["months"][month_index]
            for key in _MONEY_KEYS:
                _add(totals, key, metrics[key])
            totals["reservation_count"] += metrics["reservation_count"]
        totals = _round_metrics(totals)
        month_rows.append({"month": month_index + 1, "name": _MONTH_NAMES[month_index], **totals})
        for key in _MONEY_KEYS:
            _add(grand, key, totals[key])
        grand["reservation_count"] += totals["reservation_count"]

    return {
        "year": year,
        "today": today.isoformat(),
        "currency": "EUR",
        "eur_rate": round(eur_rate, 4),
        "last_advance_sync_at": last_sync_at.isoformat() if last_sync_at else None,
        "totals": _round_metrics(grand),
        "months": month_rows,
        "agencies": agency_rows,
        "source_counts": {
            "advance_transactions": len(advance_rows),
            "collections": collection_count,
            "reservations": selected_reservation_count,
            "invoices": len(issued_invoices),
            "open_invoices": open_invoice_count,
            "overdue_invoices": overdue_invoice_count,
            # tarihinde TCMB kuru bulunamayan akış hareketi (0 yazıldı; UI not gösterir)
            "skipped_no_rate": skipped_no_rate,
        },
    }
