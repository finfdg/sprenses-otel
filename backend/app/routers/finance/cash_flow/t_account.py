"""Nakit Akım T Hesap Cetveli — dönem bazlı giriş/çıkış gruplaması (EUR).

Panel yeniden tasarımındaki T-hesap görünümü için: seçilen dönemdeki
(gün/hafta/ay/yıl) eşleşmemiş finance_events kayıtları giriş (direction=+1)
ve çıkış (direction=-1) sütunlarına ayrılır, kaynak/kategori bazında
gruplanır ve tüm tutarlar o günkü TCMB EUR alış kuruyla EUR'a çevrilir (Sedna defter kuru hizası, 2026-07-11).
USD kalemler USD/EUR çaprazıyla doğrudan çevrilir (amount × USD alış / EUR alış —
eur_balances `to_eur` ile aynı; 2026-07-19 öncesi amount_try NULL olduğundan atlanıyorlardı).

Transfer kategorileri (Virman / Döviz Satım / İade) frontend `groupByMonth`
ile aynı kuralla tamamen hariç tutulur — bunlar hesaplar arası iç hareket
olduğundan gerçek giriş/çıkış değildir.
"""

import calendar
from datetime import date as date_cls
from datetime import timedelta
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import RateLimiter
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    SOURCE_BANK,
    FinanceEvent,
)
from app.models.user import User
from app.utils.finance_helpers import MIN_DATE

# Transfer kategorileri — frontend groupByMonth (TRANSFER_CATEGORIES) ile birebir aynı
TRANSFER_CATEGORIES = ("Virman", "Döviz Satım", "İade")

# Toplam-dışı bilgi kategorileri (2026-07-18, kullanıcı isteği): POS bloke çözümü
# hesaplar arası virmandır (karşılığı başka banka hesabına geçer) — kalemleri kendi
# başlığı altında GÖRÜNÜR ama kolon toplamı / net / gerçekleşen sayaçlarına GİRMEZ.
# Virman'dan farkı: Virman tamamen gizlenir, bunlar bilgi amaçlı listelenir.
# Frontend `in_total=False` bayrağıyla "toplam dışı" rozeti çizer ve tarih
# görünümündeki gün toplamlarından hariç tutar (CashFlowTAccount.svelte).
# "Döviz Satışı" (2026-07-19, kullanıcı isteği): döviz bozdurma iki bacaklıdır
# (EUR hesabından çıkış + TRY hesabına giriş) — hesaplar arası dönüşümdür, gerçek
# gelir/gider değildir; Pos Bloke Çözme ile aynı toplam-dışı muamele.
INFO_CATEGORIES = ("Pos Bloke Çözme", "Döviz Satışı")

# Grup başına yanıtta dönecek en fazla kalem (item_count gerçek sayıyı taşır). 500: aylık/haftalık/
# günlük görünümü tam kapsar (yoğun ay cari ~142); yalnız yıllık gibi uç toplamalar "+N kalem daha"
# ile Nakit Akım sayfasına yönlendirir. GZip + frontend cari-birleştirme yükü tolere eder (2026-07-07).
MAX_ITEMS_PER_GROUP = 500

# Banka dışı kaynaklar için sabit Türkçe grup etiketleri
# (bank → category_name ile gruplanır, bilinmeyen kaynak → source_type)
# Personel birleştirmesi (2026-07-18, kullanıcı isteği — aynı gün revize): YALNIZ maaş
# planlı kalemleri banka "Personel" kategorisiyle AYNI string'i taşır → tek "Personel"
# grubu. Stopaj/SGK vergisel yükümlülüktür → banka "Vergi/SGK" kategorisiyle aynı
# string'i taşır ve o grupla birleşir (grup anahtarı etikettir; DB source_type değişmez).
# Kredi birleştirmesi (2026-07-18, kullanıcı isteği): planlı kredi taksitleri banka
# "Kredi/Leasing" kategorisiyle (eski adı "Kredi"; leasing ödemeleri de artık bu
# kategoride) AYNI string'i taşır → tek "Kredi/Leasing" grubu. Ödenen taksit banka
# bacağında realized, ödenmemişi planlı bacakta pending olarak aynı başlıkta görünür
# (Personel birleştirmesiyle aynı desen; grup anahtarı etikettir, DB source_type değişmez).
SOURCE_LABELS = {
    "check": "Verilen Çekler",
    "credit": "Kredi/Leasing",
    "cc_payment": "KK Borç Ödemeleri",
    "vendor_payment": "Cari Ödemeleri",
    "advance": "Avanslar",
    "tax": "Vergiler",
    "recurring": "Düzenli Ödemeler",
    "salary": "Personel",
    "withholding": "Vergi/SGK",
    "sgk": "Vergi/SGK",
    "dividend": "Temettü",
    # Kâr payı stopajı da vergisel yükümlülük → "Vergi/SGK" grubuyla birleşir
    # (2026-07-18 kullanıcı isteği — stopaj/SGK revizyonuyla aynı gün)
    "dividend_stopaj": "Vergi/SGK",
    "rent_expense": "Verilen Kiralar",
    "rent_income": "Alınan Kiralar",
}

UNTAGGED_LABEL = "Etiketsiz"

# Faaliyet / Finansman ayrımı (Nakit Akım 3a tasarımı, 2026-07-04). Finansman = nakdi
# etkileri olan ama faaliyet gelir/gideri OLMAYAN hareketler (avans = firmalardan alınan
# yükümlülük, kredi = anapara/çekim). Diğer her şey faaliyet. Bu SALT bir yeniden-mercektir:
# Net = Faaliyet Neti + Finansman Neti = total_in − total_out (toplam DEĞİŞMEZ, sapma yok).
# NOT: kredi taksiti anapara+faiz olarak AYRIŞTIRILAMADIĞINDAN taksitin tamamı finansmanda
# gösterilir (faiz kısmı finance_events'te ayrı tutulmuyor).
FINANSMAN_SOURCES = {"advance", "credit"}


def _section(source_type: str, label: Optional[str] = None) -> str:
    # "Kredi/Leasing" grubu karma kaynaklıdır (planlı credit + banka bacağı) — section
    # ilk event'in kaynağına göre değişmesin diye etiket bazında finansmana sabitlenir
    # (kredi taksit/leasing ödemesi nakit akışı finansmandır; 2026-07-18 birleştirmesi).
    if label == SOURCE_LABELS["credit"]:
        return "finansman"
    return "finansman" if source_type in FINANSMAN_SOURCES else "faaliyet"

# Tarih gezgini ok tıklamaları art arda istek üretir — heavy_limiter (10/dk) gezinmeyi
# boğuyordu (12 ay geriye = 12 istek); okuma-ağırlıklı bu endpoint için daha geniş pencere
taccount_limiter = RateLimiter(max_requests=30, window_seconds=60)

router = APIRouter()


def _period_range(period: str, offset: int, today: date_cls) -> Tuple[date_cls, date_cls]:
    """Dönem başlangıç/bitiş tarihleri — Europe/Istanbul bugününe göre.

    offset=0 içinde bulunulan dönem; negatif değer dönem birimi kadar geçmiş.
    weekly: Pazartesi–Pazar; monthly: takvim ayı (calendar.monthrange).
    """
    if period == "daily":
        d = today + timedelta(days=offset)
        return d, d
    if period == "weekly":
        monday = today - timedelta(days=today.weekday())
        start = monday + timedelta(weeks=offset)
        return start, start + timedelta(days=6)
    if period == "monthly":
        total = today.year * 12 + (today.month - 1) + offset
        year, month0 = divmod(total, 12)
        month = month0 + 1
        last_day = calendar.monthrange(year, month)[1]
        return date_cls(year, month, 1), date_cls(year, month, last_day)
    # yearly
    year = today.year + offset
    return date_cls(year, 1, 1), date_cls(year, 12, 31)


def _rate_for(db: Session, dt: date_cls, code: str,
              cache: Dict[Tuple[str, date_cls], Optional[float]]) -> Optional[float]:
    """dt tarihindeki (<= en yakın) TCMB {code} alış kuru; hiç kur yoksa None.

    Tek istekte en çok birkaç yüz farklı tarih olduğundan basit sorgu + dict
    cache yeterli (eur_balances'taki bisect-cache burada gereksiz karmaşıklık).
    """
    key = (code, dt)
    if key not in cache:
        row = (
            db.query(ExchangeRate.forex_buying, ExchangeRate.unit)
            .filter(
                ExchangeRate.currency_code == code,
                ExchangeRate.date <= dt,
                ExchangeRate.forex_buying.isnot(None),
            )
            .order_by(ExchangeRate.date.desc())
            .first()
        )
        if row and row.forex_buying:
            cache[key] = float(row.forex_buying) / float(row.unit or 1)
        else:
            cache[key] = None
    return cache[key]


def _eur_rate_for(db: Session, dt: date_cls, cache: Dict[Tuple[str, date_cls], Optional[float]]) -> Optional[float]:
    return _rate_for(db, dt, "EUR", cache)


def _event_eur(db: Session, fe: FinanceEvent, cache: Dict[Tuple[str, date_cls], Optional[float]]) -> Optional[float]:
    """Kalemi EUR'a çevir; çevrilemiyorsa None (çağıran skipped_no_rate sayar).

    EUR kalem → amount aynen; USD kalem → USD/EUR çaprazı (amount × USD alış /
    EUR alış — eur_balances `to_eur` ile aynı formül; amount_try'a BAKILMAZ,
    USD banka satırlarında amount_try dolmuyordu → panel USD'ye kördü, 2026-07-19).
    Diğerleri → TRY değeri / o tarihteki EUR kuru. TRY değeri: amount_try, yoksa
    currency TRY ise amount. Kur ya da TRY değeri bilinemiyorsa kalem
    1 TL = 1 EUR gibi saçma bir varsayımla ÇEVRİLMEZ — dışarıda bırakılır.
    """
    currency = (fe.currency or "TRY").upper()
    if currency == "EUR":
        return float(fe.amount)

    if currency == "USD":
        usd = _rate_for(db, fe.event_date, "USD", cache)
        eur = _eur_rate_for(db, fe.event_date, cache)
        if not usd or not eur:
            return None
        return float(fe.amount) * usd / eur

    if fe.amount_try is not None:
        try_value = float(fe.amount_try)
    elif currency in ("TRY", "TL"):
        try_value = float(fe.amount)
    else:
        return None  # döviz kalem, TRY karşılığı bilinmiyor

    rate = _eur_rate_for(db, fe.event_date, cache)
    if not rate:
        return None
    return try_value / rate


def _group_label(fe: FinanceEvent) -> str:
    """Grup etiketi: banka → kategori adı (yoksa Etiketsiz), diğerleri sabit etiket."""
    if fe.source_type == SOURCE_BANK:
        return fe.category_name or UNTAGGED_LABEL
    return SOURCE_LABELS.get(fe.source_type, fe.source_type)


# Acenta kalemlerinde görünen ad tag_note'tan gelir (auto_tagger acente adını çözer)
AGENCY_LABEL = "Acenta"


def _item_name(fe: FinanceEvent) -> str:
    """Kalem adı: (Acenta → çözülen acente adı) → açıklama → banka adı → çek no → etiket.

    Acenta tahsilatlarının banka açıklaması kırpık/karışıktır ("Diğer Diğer
    TRAVE/020726/278982", "Swift şubeden para yatırma Ref: …") — auto_tagger
    eşleşen acente adını tag_note'a yazar; kullanıcı satırda onu görür (2026-07-13).
    """
    if fe.source_type == SOURCE_BANK and fe.category_name == AGENCY_LABEL:
        note = (fe.tag_note or "").strip()
        if note:
            return note
    return (
        (fe.description or "").strip()
        or (fe.bank_name or "").strip()
        or (fe.check_no or "").strip()
        or _group_label(fe)
    )


@router.get("/cash-flow/t-account")
def t_account(
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|yearly)$"),
    offset: int = Query(0, le=24, ge=-120, description="0=bu dönem, negatif=geçmiş, pozitif=gelecek dönem"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Dönem bazlı T hesap cetveli — giriş/çıkış grupları, EUR karşılıklarıyla."""
    taccount_limiter.check(f"cashflow-taccount-{current_user.id}")

    today = date_cls.today()
    start, end = _period_range(period, offset, today)

    events = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.is_matched == False,
            FinanceEvent.event_date >= MIN_DATE,
            FinanceEvent.event_date >= start,
            FinanceEvent.event_date <= end,
            # NULL kategori NOT IN'de UNKNOWN döner → or_ ile açıkça dahil edilir
            or_(
                FinanceEvent.category_name.is_(None),
                ~FinanceEvent.category_name.in_(TRANSFER_CATEGORIES),
            ),
        )
        .order_by(FinanceEvent.event_date.asc(), FinanceEvent.id.asc())
        .all()
    )

    groups = {DIRECTION_INCOME: {}, DIRECTION_EXPENSE: {}}
    totals = {DIRECTION_INCOME: 0.0, DIRECTION_EXPENSE: 0.0}
    # is_realized (gerçekleşmiş — ör. banka hareketi) EUR toplamı; kalan = bekleyen (planlı)
    realized = {DIRECTION_INCOME: 0.0, DIRECTION_EXPENSE: 0.0}
    skipped_no_rate = 0
    rate_cache: Dict[Tuple[str, date_cls], Optional[float]] = {}
    # Beklemeye alınmış (hold) future-pending kalemler LİSTEDE KALIR (kullanıcı isteği 2026-07-07:
    # "eski yerinde sarı kalsın") ama kolon toplamı / net / bekleyen toplamına GİRMEZ (akım-dışı park).
    # Ayrıca Bekleme Listesi'nde (runway.held) de gösterilir. Çek bekletilemez (HOLDABLE'dan çıkarıldı).
    from app.services.hold_service import get_hold_set
    hold_set = get_hold_set(db)

    for fe in events:
        if fe.direction not in groups:
            continue
        # Vadesi geçmiş VEYA BUGÜN vadeli GERÇEKLEŞMEMİŞ kalemler bu listeye GİRMEZ (hem GİDER hem
        # GELİR): gerçekleştiyse zaten realized görünür; olmadıysa GİDER "Vadesi Geçenler", GELİR
        # "Vadesi Geçen Tahsilatlar" bölümünde takip edilir → bekleyen giriş/çıkış şişmez.
        # `<= today` (bugün dahil, kullanıcı isteği 2026-07-16): bugün vadeli ama ödenmemiş kalem de
        # overdue sayılır → `runway.py` ile aynı sınır; kalem ya akışta ya overdue'da (çift gösterim
        # yok, tipping "nakit yetmiyor" bugünkü ödenmemiş kaleme basılmaz). Realized (ödenmiş) bugünkü
        # kalem AKIŞTA KALIR (Gerçekleşen). (Kullanıcı: gider 2026-07-05, gelir 2026-07-07.)
        if not fe.is_realized and fe.event_date <= today:
            continue
        eur = _event_eur(db, fe, rate_cache)
        if eur is None:
            skipped_no_rate += 1
            continue

        # Beklemeye alınmış (future-pending, gerçekleşmemiş) → sarı gösterilir, toplama KATILMAZ.
        is_held = (not fe.is_realized) and ((fe.source_type, fe.source_id) in hold_set)

        label = _group_label(fe)
        # Toplam-dışı bilgi grubu (POS bloke çözümü): grup kendi toplamını taşır ama
        # kolon toplamı/net/gerçekleşen sayaçlarına eklenmez
        in_total = label not in INFO_CATEGORIES
        group = groups[fe.direction].setdefault(
            label, {"label": label, "total_eur": 0.0, "item_count": 0,
                    "realized_eur": 0.0, "realized_count": 0,
                    "held_eur": 0.0, "held_count": 0,
                    "in_total": in_total,
                    "section": _section(fe.source_type, label), "items": []}
        )
        group["item_count"] += 1
        # Grup bazında gerçekleşen/bekleyen bölünmesi (2026-07-06): frontend ödenmişleri
        # ayrı "Gerçekleşen" listesinde gösterir, ana liste yalnız bekleyenleri taşır.
        # items MAX_ITEMS_PER_GROUP ile kırpıldığından bölme SAYAÇLARLA yapılır (itemlardan değil).
        if is_held:
            # Held → toplama/net'e GİRMEZ; yalnız ayrı held sayaçları (sarı gösterim + Bekleme Listesi)
            group["held_eur"] += eur
            group["held_count"] += 1
        else:
            group["total_eur"] += eur
            if in_total:
                totals[fe.direction] += eur
            if fe.is_realized:
                group["realized_eur"] += eur
                group["realized_count"] += 1
                if in_total:
                    realized[fe.direction] += eur
        if len(group["items"]) < MAX_ITEMS_PER_GROUP:
            group["items"].append({
                "name": _item_name(fe),
                "date": fe.event_date.isoformat(),
                "amount_eur": round(eur, 2),
                # Kalem kendi para biriminde de dönülür (detay native gösterir; grup/kolon toplamı EUR)
                "amount_native": round(float(fe.amount), 2),
                "currency": (fe.currency or "TRY").upper(),
                "is_realized": bool(fe.is_realized),
                "is_held": is_held,  # sarı gösterim + toplam-dışı (frontend)
                # Bekletme (hold) kimliği — frontend bu kalemi beklemeye alabilsin
                "source_type": fe.source_type,
                "source_id": fe.source_id,
                # Banka amblemi (frontend satır başı rozeti) — banka hareketi / çek
                # ödeme bankası / kredi taksit bankası; bilinmiyorsa None (rozet çizilmez)
                "bank_name": fe.bank_name,
            })

    # Tahmini kredi kartı ekstresi rezervi (yüklenmemiş cari ay = kart limiti) — dönemi kapsayan
    # son-ödeme kalemleri ÇIKIŞ "KK Borç Ödemeleri" grubuna eklenir → panel/nakit akım tablosu +
    # EUR bakiye + runway ile aynı rezerv (kullanıcı isteği 2026-07-04; tek kaynak
    # due_reserve_projections). Cari-ay dışı dönemlerde (geçmiş offset) due tarihi aralık dışıdır.
    from app.services.cc_projection_service import due_reserve_projections
    for proj in due_reserve_projections(db, today=today):
        due = date_cls.fromisoformat(proj["date"])
        if due < start or due > end:
            continue
        rate = _eur_rate_for(db, due, rate_cache)
        if not rate:
            skipped_no_rate += 1
            continue
        eur = float(proj["amount"]) / rate
        # Projeksiyon rezervi KART bazında beklemeye alınabilir (source_type="cc_projection",
        # source_id=card_id). Held ise sarı gösterilir, toplama/net'e girmez (gerçek kalemlerle aynı).
        proj_card_id = proj.get("card_id")
        proj_held = proj_card_id is not None and ("cc_projection", proj_card_id) in hold_set
        label = SOURCE_LABELS["cc_payment"]
        group = groups[DIRECTION_EXPENSE].setdefault(
            label, {"label": label, "total_eur": 0.0, "item_count": 0,
                    "realized_eur": 0.0, "realized_count": 0,
                    "held_eur": 0.0, "held_count": 0,
                    "section": "faaliyet", "items": []}
        )
        group["item_count"] += 1
        if proj_held:
            group["held_eur"] += eur
            group["held_count"] += 1
        else:
            group["total_eur"] += eur
            totals[DIRECTION_EXPENSE] += eur
        if len(group["items"]) < MAX_ITEMS_PER_GROUP:
            group["items"].append({
                "name": f"{proj['description']} (Tahmini)",
                "date": proj["date"],
                "amount_eur": round(eur, 2),
                "amount_native": round(float(proj["amount"]), 2),
                "currency": "TRY",
                "is_realized": False,  # projeksiyon = her zaman bekleyen rezerv
                "is_held": proj_held,
                # Kart bazlı bekletme kimliği (gerçek FE değil ama kart CreditProduct.id'siyle bekletilir)
                "source_type": "cc_projection" if proj_card_id is not None else None,
                "source_id": proj_card_id,
                "bank_name": proj.get("bank_name"),
            })

    # Kontrat taksitleri (advances'a netlenmiş) + TAM CİRO tahsilat projeksiyonu — GİRİŞ
    # tarafına iki projeksiyon grubu (#26 kararı varyant iii, 2026-07-17; okuma-anında
    # servis, FE yazılmaz — cc_projection deseniyle aynı). Vadesi geçmiş taksitler burada
    # GÖSTERİLMEZ (runway "Vadesi Geçen Tahsilatlar" bölümünde — çift gösterim yok).
    from app.services.contract_projection_service import contract_inflow_projections
    _cproj = contract_inflow_projections(db, today=today)
    _contract_feed = (
        [("Kontrat Taksitleri (Projeksiyon)", "finansman", i,
          i["label"] + (" — KOŞULLU" if i.get("conditional") else ""))
         for i in _cproj["installments"]] +
        [("Beklenen Ciro Tahsilatı (Projeksiyon)", "faaliyet", i, i["label"])
         for i in _cproj["ciro_monthly"]]
    )
    for _glabel, _section_name, _ci, _iname in _contract_feed:
        _cdt = date_cls.fromisoformat(_ci["date"])
        if _cdt < start or _cdt > end or _cdt <= today:
            continue
        _eur = float(_ci["amount_eur"])
        group = groups[DIRECTION_INCOME].setdefault(
            _glabel, {"label": _glabel, "total_eur": 0.0, "item_count": 0,
                      "realized_eur": 0.0, "realized_count": 0,
                      "held_eur": 0.0, "held_count": 0,
                      "section": _section_name, "items": []}
        )
        group["item_count"] += 1
        group["total_eur"] += _eur
        totals[DIRECTION_INCOME] += _eur
        if len(group["items"]) < MAX_ITEMS_PER_GROUP:
            group["items"].append({
                "name": _iname,
                "date": _ci["date"],
                "amount_eur": round(_eur, 2),
                "amount_native": round(_eur, 2),
                "currency": "EUR",
                "is_realized": False,
                "is_held": False,
                "source_type": None,  # FE değil — bekletme kimliği yok (projeksiyon)
                "source_id": None,
                "bank_name": None,
            })

    def _finalize(direction: int) -> list:
        result = list(groups[direction].values())
        for g in result:
            g["total_eur"] = round(g["total_eur"], 2)
            g["realized_eur"] = round(g.get("realized_eur", 0.0), 2)
            g["held_eur"] = round(g.get("held_eur", 0.0), 2)
            # CC projeksiyonları grup SONUNA kart sırasıyla eklenir → tarih sırası bozulabilir;
            # frontend tarih-bucket'ları (keyed each) sıralı items varsayar. ISO string sort = kronolojik.
            g["items"].sort(key=lambda i: i["date"])
        result.sort(key=lambda g: g["total_eur"], reverse=True)
        return result

    total_in = round(totals[DIRECTION_INCOME], 2)
    total_out = round(totals[DIRECTION_EXPENSE], 2)

    giris = _finalize(DIRECTION_INCOME)
    cikis = _finalize(DIRECTION_EXPENSE)

    # Faaliyet / Finansman neti (yalnız yeniden-mercek — net toplamı değiştirmez).
    # Toplam-dışı bilgi grupları (in_total=False) burada da hariç — aksi halde
    # faaliyet_net + finansman_net = net_eur eşitliği bozulur.
    def _section_net(section: str) -> float:
        inc = sum(g["total_eur"] for g in giris if g.get("section") == section and g.get("in_total", True))
        exp = sum(g["total_eur"] for g in cikis if g.get("section") == section and g.get("in_total", True))
        return round(inc - exp, 2)

    faaliyet_net = _section_net("faaliyet")
    finansman_net = _section_net("finansman")

    return {
        "period": period,
        "offset": offset,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "giris": giris,
        "cikis": cikis,
        "total_in_eur": total_in,
        "total_out_eur": total_out,
        "realized_in_eur": round(realized[DIRECTION_INCOME], 2),
        "realized_out_eur": round(realized[DIRECTION_EXPENSE], 2),
        "net_eur": round(total_in - total_out, 2),
        "faaliyet_net_eur": faaliyet_net,
        "finansman_net_eur": finansman_net,
        "skipped_no_rate": skipped_no_rate,
    }
