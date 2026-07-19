"""EUR bazlı bakiye hesaplama — günlük ve aylık projeksiyon."""

import bisect
from collections import defaultdict
from datetime import date as date_cls

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import eur_balances_limiter
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.models.transaction_category import TransactionCategory
from app.models.user import User
from app.utils.finance_helpers import MIN_DATE

router = APIRouter()


def compute_eur_balances(db: Session) -> dict:
    """Günlük ve aylık EUR bazlı toplam banka bakiyesi hesabı.

    `eur-balances` endpoint'i ile nakit akım PDF raporunun (report.py) ORTAK
    çekirdeği — iki tüketici de aynı sayıları göstersin diye tek fonksiyon.

    Banka işlemleri + çekler + kredi ödemeleri dahil.
    Son banka bakiyesi gelecek günlere taşınır, çek/kredi giderleri düşülür.
    """
    today_date = date_cls.today()

    # Beklemeye alınmış (hold) future-pending kalemler projeksiyondan dışlanır → nakit akıma dahil
    # edilmez (tutar "parkta"; bakiye düşmez). Vade geçince overdue (bakiyeden zaten düşülmüyor),
    # ödenince gerçek banka hareketiyle doğal olarak işlenir. Yalnız event_date >= bugün için geçerli.
    from app.services.hold_service import get_hold_set
    hold_set = get_hold_set(db)

    def _is_held_future(st, sid, dt):
        return dt >= today_date and (st, sid) in hold_set

    # Tüm hesaplar
    accounts = db.query(BankAccount).all()
    acc_map = {a.id: a for a in accounts}
    acc_blocked = {a.id: float(a.blocked_amount) if a.blocked_amount else 0 for a in accounts}

    # Dahili transfer / iade kategori ID'leri (gelir/giderden çıkarılacak).
    # "Pos Bloke Çözme" (2026-07-18): POS bloke çözümü hesaplar arası virmandır —
    # iki bacağı da günlük gelir/gider toplamına girmez (bakiye zaten banka
    # ekstresinden gelir, etkilenmez). "Döviz Satışı" (2026-07-19): iki bacaklı
    # hesaplar arası dönüşüm — aynı muamele.
    transfer_cat_ids = set()
    for cat in db.query(TransactionCategory).filter(
        TransactionCategory.name.in_(["Virman", "Döviz Satım", "İade", "Pos Bloke Çözme", "Döviz Satışı"])
    ).all():
        transfer_cat_ids.add(cat.id)

    # Banka işlemleri
    txs = (
        db.query(
            BankTransaction.account_id,
            BankTransaction.date,
            BankTransaction.balance,
            BankTransaction.type,
            BankTransaction.amount,
            BankTransaction.id,
            BankTransaction.category_id,
        )
        .filter(BankTransaction.date >= MIN_DATE)
        .order_by(BankTransaction.date, BankTransaction.id)
        .all()
    )

    # Tüm çekler (eşleşen + bekleyen — banka tarafı hariç tutulduğu için çek tarafı dahil)
    all_checks = (
        db.query(Check)
        .filter(Check.due_date >= MIN_DATE)
        .all()
    )
    # Sadece bekleyen çekler (gelecek bakiye hesaplaması için — iptal çekler hariç)
    pending_checks = [c for c in all_checks if c.bank_transaction_id is None and c.status != "cancelled"]

    # Tüm kredi ödemeleri (banka eşleşmesi olmayanlar — eşleşenler banka tarafında)
    all_credit_payments = (
        db.query(CreditPayment)
        .join(CreditProduct, CreditPayment.credit_product_id == CreditProduct.id)
        .filter(
            CreditPayment.due_date >= MIN_DATE,
            CreditProduct.status == "active",  # kapalı kredilerin taksitleri EUR projeksiyonuna girmez
        )
        .all()
    )
    # Banka eşleşmesi olmayanlar
    pending_payments = [p for p in all_credit_payments if not p.bank_transaction_id and not p.is_paid]
    # Gelir/gider hesabı için: banka eşleşmesi olmayanlar (eşleşenler banka tarafında zaten var)
    unmatched_credit_payments = [p for p in all_credit_payments if not p.bank_transaction_id]

    # Her hesap için günlük son bakiye
    acc_daily_balance = defaultdict(dict)
    for tx in txs:
        if tx.balance is not None:
            acc_daily_balance[tx.account_id][tx.date] = float(tx.balance)

    # Pencere-öncesi tohum bakiyeleri (2026-07-19 — Ocak açılış artefaktı düzeltmesi):
    # MIN_DATE kesimi hesapları pencere-içi İLK satırlarına kadar "yok" sayıyordu → 1 Ocak
    # açılışı eksik ölçülüyordu (yalnız 1 hesap görünür, ~€30K; gerçek ~€289K). Her hesap
    # pencere başında pencere-ÖNCESİ son bilinen ekstre bakiyesiyle tohumlanır. Tohum akım
    # üretmez ("Devir gelir değildir" — income/expense toplamları değişmez), yalnız seviye
    # düzeltir. Sıralama (date, id) — max(id) KULLANILMAZ: sonradan eklenen (backfill)
    # eski-tarihli satırlar id sırasını bozar (canlı hesap 9/10 kanıtı; Garanti filtreli
    # PDF tuzağı sınıfı). Pencere-içi acc_daily_balance kurulumuyla aynı konvansiyon.
    pre_rows = (
        db.query(BankTransaction.account_id, BankTransaction.balance)
        .filter(BankTransaction.date < MIN_DATE, BankTransaction.balance.isnot(None))
        .order_by(BankTransaction.date, BankTransaction.id)
        .all()
    )
    seed_balance = {}
    for r in pre_rows:
        seed_balance[r.account_id] = float(r.balance)  # (date,id) son satır kazanır

    # Bekleyen cari ödemeler — FIFO tutarları finance_events'ten oku
    vendor_fe_payments = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.source_type == "vendor_payment",
            FinanceEvent.is_matched == False,
        )
        .all()
    )

    # Tüm tarihleri topla (banka + çek + kredi + cari)
    all_date_set = set(tx.date for tx in txs)
    for c in all_checks:
        if c.status != "cancelled":
            all_date_set.add(c.due_date if not c.bank_transaction_id else c.due_date)
    for p in unmatched_credit_payments:
        all_date_set.add(p.due_date)
    for vfe in vendor_fe_payments:
        all_date_set.add(vfe.event_date)
    all_dates = sorted(all_date_set)

    # Tüm EUR/USD kurlarını tek sorguda al ve tarih bazlı cache oluştur
    all_eur_rates = (
        db.query(ExchangeRate.date, ExchangeRate.forex_buying)
        .filter(ExchangeRate.currency_code == "EUR")
        .order_by(ExchangeRate.date)
        .all()
    )
    all_usd_rates = (
        db.query(ExchangeRate.date, ExchangeRate.forex_buying)
        .filter(ExchangeRate.currency_code == "USD")
        .order_by(ExchangeRate.date)
        .all()
    )

    # Tarih → kur dict
    eur_rate_list = [(r.date, float(r.forex_buying)) for r in all_eur_rates if r.forex_buying]
    usd_rate_list = [(r.date, float(r.forex_buying)) for r in all_usd_rates if r.forex_buying]

    # Binary search ile en yakın önceki kuru bul
    eur_dates = [r[0] for r in eur_rate_list]
    usd_dates = [r[0] for r in usd_rate_list]
    eur_cache = {}
    usd_cache = {}

    def get_eur(dt):
        if dt not in eur_cache:
            idx = bisect.bisect_right(eur_dates, dt) - 1
            eur_cache[dt] = eur_rate_list[idx][1] if idx >= 0 else 1.0
        return eur_cache[dt]

    def get_usd(dt):
        if dt not in usd_cache:
            idx = bisect.bisect_right(usd_dates, dt) - 1
            usd_cache[dt] = usd_rate_list[idx][1] if idx >= 0 else 1.0
        return usd_cache[dt]

    def to_eur(amount, currency, dt):
        if currency == "EUR":
            return amount
        if currency == "TRY":
            rate = get_eur(dt)
            return round(amount / rate, 2) if rate > 0 else 0
        if currency == "USD":
            return round((amount * get_usd(dt)) / get_eur(dt), 2) if get_eur(dt) > 0 else 0
        return amount

    # Kalıcı öteleme haritası (R5 2026-07-11): çek/kredi/KK ham tablolardan okunduğundan
    # deferral'ın FE'ye işlediği yeni tarih burada görünmüyordu → RunwayChart/PDF eski,
    # T-Hesap/runway yeni tarihte gösteriyordu (sessiz drift). Harita ile hizalanır.
    from app.services.deferral_service import get_deferral_map
    deferral_map = get_deferral_map(db)

    # Çek → banka tarihi eşlemesini toplu yükle (N+1 engeli)
    check_btx_ids = [c.bank_transaction_id for c in all_checks if c.bank_transaction_id]
    btx_date_map = {}
    if check_btx_ids:
        btx_dates = db.query(BankTransaction.id, BankTransaction.date).filter(
            BankTransaction.id.in_(check_btx_ids)
        ).all()
        btx_date_map = {bid: bdate for bid, bdate in btx_dates}

    # Çek giderlerini gün bazlı topla (EUR cinsinden — iptal çekler hariç)
    check_expense_by_date = defaultdict(float)
    for c in all_checks:
        if c.status == "cancelled":
            continue
        amt = float(c.amount_currency)
        curr = "EUR" if c.currency != "TL" else "TRY"
        if curr == "TRY":
            amt = float(c.amount_tl)
        if c.bank_transaction_id:
            check_date = btx_date_map.get(c.bank_transaction_id, c.due_date)
        else:
            check_date = deferral_map.get(("check", c.id)) or c.due_date
        check_expense_by_date[check_date] += to_eur(amt, curr, check_date)
        # Ötelenmiş tarih daily/monthly eksenine girsin — all_date_set yalnız doğal
        # due_date'i içeriyordu; eff tarih sette yoksa gider sessizce kayboluyordu
        # (KK dalı eff_cc'yi zaten ekliyor — aynı kural).
        all_date_set.add(check_date)

    # Kredi ürün para birimlerini toplu yükle (N+1 engeli)
    credit_product_ids = list({p.credit_product_id for p in pending_payments})
    credit_currency_map = {}
    if credit_product_ids:
        prods = db.query(CreditProduct.id, CreditProduct.currency).filter(
            CreditProduct.id.in_(credit_product_ids)
        ).all()
        credit_currency_map = {pid: curr or "TRY" for pid, curr in prods}

    # Kredi ödemelerini gün bazlı topla (EUR cinsinden — banka eşleşmesi olmayanlar)
    credit_expense_by_date = defaultdict(float)
    for p in pending_payments:
        if _is_held_future("credit", p.id, p.due_date):
            continue  # beklemeye alınmış kredi taksiti → akım-dışı
        curr = credit_currency_map.get(p.credit_product_id, "TRY")
        eff_due = deferral_map.get(("credit", p.id)) or p.due_date
        if curr == "TRY":
            credit_expense_by_date[eff_due] += to_eur(float(p.amount), "TRY", eff_due)
        else:
            credit_expense_by_date[eff_due] += float(p.amount) if curr == "EUR" else to_eur(float(p.amount), curr, eff_due)
        all_date_set.add(eff_due)  # ötelenmiş taksit tarihi daily/monthly eksenine girsin (çek notuyla aynı)

    # Ödenmemiş ve vadesi gelmemiş kredi kartı ekstreleri (son ödeme tarihine göre)
    # Vadesi geçmiş ekstreler hariç — gerçek ödeme banka kaydında zaten var
    cc_expense_by_date = defaultdict(float)
    unpaid_cc_stmts = (
        db.query(CreditCardStatement)
        .filter(
            CreditCardStatement.son_odeme_tarihi >= MIN_DATE,
            CreditCardStatement.son_odeme_tarihi >= today_date,
            CreditCardStatement.is_paid == False,
        )
        .all()
    )
    for stmt in unpaid_cc_stmts:
        eff_cc = deferral_map.get(("cc_payment", stmt.id)) or stmt.son_odeme_tarihi
        if _is_held_future("cc_payment", stmt.id, eff_cc):
            continue  # beklemeye alınmış KK ekstresi → akım-dışı
        kalan = float(stmt.toplam_borc) - float(stmt.paid_amount or 0)
        if kalan > 0:
            cc_expense_by_date[eff_cc] += to_eur(kalan, "TRY", eff_cc)
            all_date_set.add(eff_cc)

    # Tahmini kredi kartı ekstresi rezervi (yüklenmemiş cari ay = kart limiti) — nakit akım
    # tablosuyla aynı sayı EUR başlığında/projeksiyonda da görünsün (kullanıcı isteği 2026-07-04).
    # Yalnız tutar taşıyan son-ödeme kalemleri (kesim hatırlatıcıları tutar 0 → etkisiz).
    from app.services.cc_projection_service import due_reserve_projections
    cc_projection_expense_by_date = defaultdict(float)
    for proj in due_reserve_projections(db, today=today_date):
        # Kart bazında beklemeye alınmış projeksiyon rezervi → projeksiyona (bakiyeye) girmez
        _pcid = proj.get("card_id")
        if _pcid is not None and ("cc_projection", _pcid) in hold_set:
            continue
        pdt = date_cls.fromisoformat(proj["date"])
        cc_projection_expense_by_date[pdt] += to_eur(float(proj["amount"]), "TRY", pdt)
        all_date_set.add(pdt)

    # Kontrat taksitleri (advances'a netlenmiş) + TAM CİRO tahsilat projeksiyonu
    # (#26 kararı varyant iii, 2026-07-17 — okuma-anında servis, FE YAZILMAZ;
    # çift-sayım korumaları contract_projection_service docstring'inde).
    from app.services.contract_projection_service import contract_inflow_projections
    contract_income_by_date = defaultdict(float)
    _cproj = contract_inflow_projections(db, today=today_date)
    for _ci in _cproj["installments"] + _cproj["ciro_monthly"]:
        _cdt = date_cls.fromisoformat(_ci["date"])
        if _cdt <= today_date:
            continue  # vadesi geçmiş taksit bakiyeye eklenmez (runway "Vadesi Geçen Tahsilatlar"da)
        contract_income_by_date[_cdt] += float(_ci["amount_eur"])
        all_date_set.add(_cdt)

    # CC/kontrat tarihleri eklenmiş olabilir, yeniden sırala
    all_dates = sorted(all_date_set)

    # Çekle eşleşen banka işlem ID'leri (çift sayım engeli)
    matched_btx_ids = set(
        r[0] for r in
        db.query(Check.bank_transaction_id)
        .filter(Check.bank_transaction_id.isnot(None))
        .all()
    )

    # Banka gelir/gider gün bazlı EUR (Virman, Döviz Satım, İade hariç + çek eşleşenleri hariç)
    bank_income_by_date = defaultdict(float)
    bank_expense_by_date = defaultdict(float)
    for tx in txs:
        # Dahili transferler gelir/gider toplamına dahil edilmez
        if tx.category_id and tx.category_id in transfer_cat_ids:
            continue
        # Çekle eşleşen banka işlemleri hariç (çek tarafında zaten sayılıyor)
        if tx.id in matched_btx_ids:
            continue
        currency = acc_map[tx.account_id].currency if tx.account_id in acc_map else "TRY"
        eur_amt = to_eur(abs(float(tx.amount)), currency, tx.date)
        if tx.type == "income":
            bank_income_by_date[tx.date] += eur_amt
        else:
            bank_expense_by_date[tx.date] += eur_amt

    # Cari ödemeleri gün bazlı topla (EUR cinsinden — FIFO tutarlarıyla)
    vendor_expense_by_date = defaultdict(float)
    for vfe in vendor_fe_payments:
        if _is_held_future(vfe.source_type, vfe.source_id, vfe.event_date):
            continue  # beklemeye alınmış cari ödeme → akım-dışı
        vendor_expense_by_date[vfe.event_date] += to_eur(float(vfe.amount), vfe.currency or "TRY", vfe.event_date)

    # Bekleyen avanslar (vadesi gelmemiş — gelir olarak bakiyeye eklenecek)
    advance_income_by_date = defaultdict(float)
    advance_fes = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.source_type == "advance",
            FinanceEvent.is_matched == False,
            FinanceEvent.is_realized == False,
            FinanceEvent.direction == 1,  # gelir
        )
        .all()
    )
    for afe in advance_fes:
        if _is_held_future(afe.source_type, afe.source_id, afe.event_date):
            continue  # beklemeye alınmış avans → akım-dışı
        advance_income_by_date[afe.event_date] += to_eur(float(afe.amount), afe.currency or "EUR", afe.event_date)
        all_date_set.add(afe.event_date)
    # Tarih seti güncellendi, yeniden sırala
    all_dates = sorted(all_date_set)

    # Planlı gider/gelir (vergi, düzenli ödeme, maaş, stopaj, kiralar) + temettü net/stopaj
    scheduled_types = ("tax", "recurring", "salary", "withholding", "rent_income", "rent_expense", "sgk", "dividend", "dividend_stopaj")
    scheduled_fes = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.source_type.in_(scheduled_types),
            FinanceEvent.is_matched == False,
        )
        .all()
    )
    scheduled_income_by_date = defaultdict(float)
    scheduled_expense_by_date = defaultdict(float)
    for sfe in scheduled_fes:
        if _is_held_future(sfe.source_type, sfe.source_id, sfe.event_date):
            continue  # beklemeye alınmış planlı gider/gelir → akım-dışı
        eur_amt = to_eur(float(sfe.amount), sfe.currency or "TRY", sfe.event_date)
        if sfe.direction == 1:  # gelir (alınan kira)
            scheduled_income_by_date[sfe.event_date] += eur_amt
        else:  # gider
            scheduled_expense_by_date[sfe.event_date] += eur_amt
        all_date_set.add(sfe.event_date)
    # Tarih seti güncellendi, yeniden sırala
    all_dates = sorted(all_date_set)

    # Bekleyen çek giderleri (gelecek bakiye projeksiyonu için — eşleşenler banka bakiyesinde)
    # Ötelenmiş çek bakiyeden de ötelenmiş tarihte düşer (gider çizgisiyle aynı eksen — R5)
    pending_check_expense_by_date = defaultdict(float)
    for c in pending_checks:
        amt = float(c.amount_currency)
        curr = "EUR" if c.currency != "TL" else "TRY"
        if curr == "TRY":
            amt = float(c.amount_tl)
        eff_check = deferral_map.get(("check", c.id)) or c.due_date
        pending_check_expense_by_date[eff_check] += to_eur(amt, curr, eff_check)

    # Kümülatif bakiye hesapla — pencere-öncesi tohumlarla başlar (yukarıdaki nota bkz):
    # tohumlu hesap pencere-içi ilk kendi satırına kadar devir bakiyesiyle toplamda yer alır,
    # ilk satırı geldiği gün kendi ekstre bakiyesi devralır (süreklilik; sıçrama yok).
    acc_running_balance = dict(seed_balance)
    last_known_bank_eur = 0
    if acc_running_balance and all_dates:
        # İlk banka gününden önceki (planlı-kalem) günler de gerçek devir seviyesini görsün.
        # Kur = gösterim günü kuru (fonksiyonun her banka-gününde yeniden değerleme konvansiyonu).
        _seed_dt = all_dates[0]
        last_known_bank_eur = round(sum(
            to_eur(bal - acc_blocked.get(acc_id, 0), acc_map[acc_id].currency, _seed_dt)
            for acc_id, bal in acc_running_balance.items() if acc_id in acc_map
        ), 2)
    bank_date_set = set(tx.date for tx in txs)
    last_bank_date = max(bank_date_set) if bank_date_set else all_dates[0] if all_dates else None
    cumulative_future_expense = 0

    # NOT — VADESİ GEÇMİŞ ÖDENMEMİŞ KALEMLER BAKİYEDEN DÜŞÜLMEZ (kullanıcı kararı 2026-07-06):
    # "vadesi geçeni bakiyeden düşemezsin çünkü ödenmedi — para hâlâ bankada". Vadesi geçmiş çek/cari
    # ödenene kadar banka nakdi yerinde durur; ödendiğinde gerçek banka hareketiyle bakiye düşer.
    # O ana kadar bunlar yalnızca ayrı bir "Vadesi Geçenler" uyarısıdır, bakiyeyi azaltmaz (Panel
    # runway grafiği + T-Hesap eğrisi de aynı: overdue'yu bakiyeye katmaz, ayrı listeler). Eski
    # "overdue_total bloke düş" mantığı kaldırıldı → iki görünüm de gerçek banka nakdini gösterir.

    daily = {}
    for dt in all_dates:
        # Banka bakiyelerini güncelle
        for acc_id in acc_daily_balance:
            if dt in acc_daily_balance[acc_id]:
                acc_running_balance[acc_id] = acc_daily_balance[acc_id][dt]

        # Banka tarihlerindeyken bakiyeyi banka hesaplarından hesapla
        if dt in bank_date_set:
            bank_eur = 0
            for acc_id, bal in acc_running_balance.items():
                if acc_id in acc_map:
                    effective_bal = bal - acc_blocked.get(acc_id, 0)
                    bank_eur += to_eur(effective_bal, acc_map[acc_id].currency, dt)
            last_known_bank_eur = round(bank_eur, 2)
            # Bakiye = GERÇEK banka nakdi (vadesi geçmiş ödenmemiş düşülmez — yukarıdaki nota bkz)
            total_balance = last_known_bank_eur
        elif last_bank_date and dt > last_bank_date:
            # Projeksiyona YALNIZ bugünden SONRAKİ (dt > bugün) planlı kalemler girer — bugün
            # (ve son ekstre ile bugün arası) vadeli ödenmemiş kalem bakiyeden DÜŞÜLMEZ
            # (kullanıcı kararı 2026-07-18: "henüz ödenmedi, ödenip ödenmeyeceği belli değil" —
            # bugün noktası = saf banka nakdi, Bankadaki Nakit başlığıyla eşit; kalem ödenince
            # gerçek banka hareketiyle düşer, o ana kadar Vadesi Geçenler'de izlenir).
            if dt > today_date:
                cumulative_future_expense += pending_check_expense_by_date.get(dt, 0)
                cumulative_future_expense += credit_expense_by_date.get(dt, 0)
                cumulative_future_expense += cc_expense_by_date.get(dt, 0)
                cumulative_future_expense += cc_projection_expense_by_date.get(dt, 0)
                cumulative_future_expense += vendor_expense_by_date.get(dt, 0)
                cumulative_future_expense += scheduled_expense_by_date.get(dt, 0)
                # Bekleyen avanslar ve planlı gelirler gelir olarak eklenir (giderden düşülür)
                cumulative_future_expense -= advance_income_by_date.get(dt, 0)
                cumulative_future_expense -= scheduled_income_by_date.get(dt, 0)
                # Kontrat taksitleri (net) + beklenen ciro tahsilatı (#26-iii)
                cumulative_future_expense -= contract_income_by_date.get(dt, 0)
            total_balance = round(last_known_bank_eur - cumulative_future_expense, 2)
        else:
            total_balance = last_known_bank_eur

        # Günlük gelir/gider EUR (tüm kaynaklar dahil)
        inc_eur = (bank_income_by_date.get(dt, 0) + advance_income_by_date.get(dt, 0) +
                   scheduled_income_by_date.get(dt, 0) + contract_income_by_date.get(dt, 0))
        exp_eur = (bank_expense_by_date.get(dt, 0) + check_expense_by_date.get(dt, 0) +
                   credit_expense_by_date.get(dt, 0) + cc_expense_by_date.get(dt, 0) +
                   cc_projection_expense_by_date.get(dt, 0) +
                   vendor_expense_by_date.get(dt, 0) + scheduled_expense_by_date.get(dt, 0))

        daily[str(dt)] = {
            "income_eur": round(inc_eur, 2),
            "expense_eur": round(exp_eur, 2),
            "balance_eur": total_balance,
        }

    # Aylık özet
    monthly = defaultdict(lambda: {"income_eur": 0, "expense_eur": 0, "balance_eur": 0})
    for day_key, vals in daily.items():
        month_key = day_key[:7]
        monthly[month_key]["income_eur"] += vals["income_eur"]
        monthly[month_key]["expense_eur"] += vals["expense_eur"]
    # Ayın son gününün bakiyesi = aylık bakiye
    for month_key in monthly:
        month_days = [d for d in daily if d.startswith(month_key)]
        if month_days:
            last_day = max(month_days)
            monthly[month_key]["balance_eur"] = daily[last_day]["balance_eur"]
    # Gelir/gider EUR yuvarla
    for mk in monthly:
        monthly[mk]["income_eur"] = round(monthly[mk]["income_eur"], 2)
        monthly[mk]["expense_eur"] = round(monthly[mk]["expense_eur"], 2)

    today = date_cls.today()
    return {
        "daily": daily,
        "monthly": dict(monthly),
        "total_balance_eur": daily.get(str(today), {}).get("balance_eur", last_known_bank_eur),
        "eur_rate": get_eur(today),
        "usd_rate": get_usd(today),
    }


@router.get("/cash-flow/eur-balances")
def eur_balances(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Günlük ve aylık EUR bazlı toplam banka bakiyesi."""
    eur_balances_limiter.check(f"eur-bal-{current_user.id}")
    return compute_eur_balances(db)
