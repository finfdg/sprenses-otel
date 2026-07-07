"""Düzenli ödeme (recurring) ↔ cari senkronizasyonu testleri.

Cari-bağlı (vendor_id) recurring tanımlarının aylık girişleri, carinin gerçek aylık
faturası (alacak) + FIFO ödeme durumuyla senkronlanır. Nakit akımı HER ZAMAN recurring
FE temsil eder (2026-07-07 flip): bağlı carinin vendor_payment FE'si üretilmez; ödenen
ayın recurring FE'si silinir (banka gerçeği temsil eder), ödenmemiş ayın FE'si FIFO
kalanıyla yaşar. Fatura ayı bitmeden gelen ve tahmini aşmayan faturalar ara fatura
sayılır → aylık plan tutarı korunur.
"""
from datetime import date

from app.models.finance_event import FinanceEvent
from app.models.scheduled import ScheduledDefinition
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload
from app.utils.entry_generator import generate_entries
from app.utils.recurring_vendor_sync import sync_recurring_from_vendors
from app.utils.sync_vendor_fifo import sync_vendor_finance_events

PREFIX = "/api/accounting/recurring"


def _seed(db, *, invoices, payments=None, amount=1000.0, start_month=1, year=2026,
          link=True, offset=0, due_dates=False, hesap_kodu="320.TEST.SYNC",
          name="Test Elektrik"):
    """Cari + (opsiyonel bağlı) recurring tanım yarat. invoices/payments = [(date, tutar)].

    ``due_dates=True`` → faturalara payment_due_date yazılır (vendor_payment FE üretimi
    için gerekli — sync_vendor_finance_events testlerinde kullanılır).
    """
    upload = VendorUpload(file_name="t.xlsx", file_url="/t")
    db.add(upload)
    db.flush()
    vendor = Vendor(hesap_kodu=hesap_kodu, hesap_adi="TEST ELEKTRİK A.Ş.")
    db.add(vendor)
    db.flush()
    for d, amt in invoices:
        db.add(VendorTransaction(vendor_id=vendor.id, upload_id=upload.id, date=d,
                                 borc=0, alacak=amt, bakiye=0, tx_hash=f"inv-{hesap_kodu}-{d}-{amt}",
                                 payment_due_date=d if due_dates else None))
    for d, amt in (payments or []):
        db.add(VendorTransaction(vendor_id=vendor.id, upload_id=upload.id, date=d,
                                 borc=amt, alacak=0, bakiye=0, tx_hash=f"pay-{hesap_kodu}-{d}-{amt}"))
    defn = ScheduledDefinition(
        source_type="recurring", name=name, category="Fatura",
        amount=amount, currency="TRY", frequency="monthly", payment_day=10,
        start_month=start_month, year=year, is_active=True,
        vendor_id=vendor.id if link else None, billing_offset_months=offset,
    )
    db.add(defn)
    db.flush()
    generate_entries(db, defn, direction=-1)
    db.flush()
    return defn, vendor


def _entries_by_period(defn):
    return {(e.period_year, e.period_month): e for e in defn.entries.all()}


def _fe(db, entry_id):
    return db.query(FinanceEvent).filter(
        FinanceEvent.source_type == "recurring", FinanceEvent.source_id == entry_id
    ).first()


def _fe_count(db, entry_id):
    return db.query(FinanceEvent).filter(
        FinanceEvent.source_type == "recurring", FinanceEvent.source_id == entry_id
    ).count()


def test_sync_actual_amount_and_paid_status(db):
    """Faturası gelen (kapanmış) ay GERÇEK tutara + cari FIFO ödeme durumuna çekilir; gelecek ay tahmini kalır."""
    # Ocak fatura 1500 (1500 ödeme ile kapanır) + Şubat fatura 800 (ödenmemiş)
    defn, _ = _seed(db, invoices=[(date(2026, 1, 5), 1500), (date(2026, 2, 5), 800)],
                    payments=[(date(2026, 1, 20), 1500)], amount=1000)
    res = sync_recurring_from_vendors(db)
    assert res["definitions"] == 1 and res["entries_synced"] == 2

    e = _entries_by_period(defn)
    jan, feb, mar = e[(2026, 1)], e[(2026, 2)], e[(2026, 3)]
    # Ocak: gerçek 1500 + ödendi (FIFO kapandı)
    assert float(jan.amount) == 1500.0 and jan.is_paid is True and jan.synced_from_cari is True
    # Şubat: gerçek 800 + ödenmemiş (kısmi/açık)
    assert float(feb.amount) == 800.0 and feb.is_paid is False and feb.synced_from_cari is True
    # Mart: faturası yok → tahmini 1000 kalır, senkron değil
    assert float(mar.amount) == 1000.0 and mar.synced_from_cari is False


def test_paid_month_fe_removed_unpaid_month_fe_remainder(db):
    """Ödenen ayın recurring FE'si silinir (banka temsil eder); ödenmemiş ayın FE'si FIFO KALANI ile yaşar."""
    # Ocak 1500 tam ödendi; Şubat 800'ün 300'ü ödendi (FIFO: Oca kapandı, Şub kalan 500)
    defn, _ = _seed(db, invoices=[(date(2026, 1, 5), 1500), (date(2026, 2, 5), 800)],
                    payments=[(date(2026, 1, 20), 1500), (date(2026, 2, 20), 300)], amount=1000)
    e = _entries_by_period(defn)
    jan, feb, mar = e[(2026, 1)], e[(2026, 2)], e[(2026, 3)]
    assert _fe_count(db, jan.id) == 1  # generate_entries her ay için FE üretti

    sync_recurring_from_vendors(db)
    assert _fe_count(db, jan.id) == 0                      # ödendi → FE kalktı
    fe_feb = _fe(db, feb.id)
    assert fe_feb is not None and float(fe_feb.amount) == 500.0  # kalan borç (800 değil)
    assert fe_feb.is_realized is False
    fe_mar = _fe(db, mar.id)
    assert fe_mar is not None and float(fe_mar.amount) == 1000.0  # gelecek ay tahmini korunur


def test_fe_enforced_every_run(db):
    """FE zorlaması idempotent: başka bir akış FE'yi geri getirse/silse bile senkron düzeltir."""
    from app.utils.finance_event_service import finance_event_svc

    defn, _ = _seed(db, invoices=[(date(2026, 1, 5), 1500)],
                    payments=[(date(2026, 1, 20), 1500)], amount=1000)
    e = _entries_by_period(defn)
    jan = e[(2026, 1)]
    sync_recurring_from_vendors(db)
    assert _fe_count(db, jan.id) == 0

    # Başka bir akış (ör. regenerate) ödenmiş ayın FE'sini geri getirdi → ikinci senkron temizler
    finance_event_svc.upsert_scheduled_entry(db, jan, direction=-1)
    assert _fe_count(db, jan.id) == 1
    res = sync_recurring_from_vendors(db)
    assert res["entries_synced"] == 0          # entry alanları değişmedi
    assert _fe_count(db, jan.id) == 0          # ama FE durumu yine de zorlandı


def test_partial_open_month_keeps_estimate(db):
    """Fatura ayı BİTMEDEN gelen ve tahmini aşmayan fatura ara faturadır → plan tutarı korunur."""
    # Temmuz'da 50 TL ek fatura (30'u ödendi); tahmin 1000; bugün = 7 Tem (ay açık)
    defn, _ = _seed(db, invoices=[(date(2026, 7, 2), 50)],
                    payments=[(date(2026, 7, 5), 30)], amount=1000)
    sync_recurring_from_vendors(db, today=date(2026, 7, 7))
    jul = _entries_by_period(defn)[(2026, 7)]
    assert float(jul.amount) == 1000.0 and jul.is_paid is False and jul.synced_from_cari is True
    fe = _fe(db, jul.id)
    # FE = FIFO kalan (20) + henüz faturalanmamış plan (1000 − 50) = 970
    assert fe is not None and float(fe.amount) == 970.0

    # Ay kapanınca gerçek tutara döner: entry 50, FE = kalan 20
    sync_recurring_from_vendors(db, today=date(2026, 8, 1))
    db.refresh(jul)
    assert float(jul.amount) == 50.0
    assert float(_fe(db, jul.id).amount) == 20.0


def test_partial_open_month_exceeding_estimate_syncs_real(db):
    """Ay açık olsa da gelen toplam tahmini AŞARSA gerçek tutar kullanılır (su senaryosu)."""
    defn, _ = _seed(db, invoices=[(date(2026, 7, 3), 1800)], amount=1000)
    sync_recurring_from_vendors(db, today=date(2026, 7, 7))
    jul = _entries_by_period(defn)[(2026, 7)]
    assert float(jul.amount) == 1800.0 and jul.synced_from_cari is True
    assert float(_fe(db, jul.id).amount) == 1800.0


def test_idempotent(db):
    """İkinci senkron değişiklik üretmez."""
    _seed(db, invoices=[(date(2026, 1, 5), 1500)], amount=1000)
    assert sync_recurring_from_vendors(db)["entries_synced"] >= 1
    assert sync_recurring_from_vendors(db)["entries_synced"] == 0


def test_revert_to_estimate_when_invoice_removed(db):
    """Daha önce senkronlanmış ay faturasını kaybederse tahmine döner + FE tahmine güncellenir."""
    defn, vendor = _seed(db, invoices=[(date(2026, 1, 5), 1500)], amount=1000)
    sync_recurring_from_vendors(db)
    jan = _entries_by_period(defn)[(2026, 1)]
    assert jan.synced_from_cari is True
    assert float(_fe(db, jan.id).amount) == 1500.0  # ödenmemiş → FE gerçek kalanla yaşar

    db.query(VendorTransaction).filter(VendorTransaction.vendor_id == vendor.id).delete()
    db.flush()
    sync_recurring_from_vendors(db)
    db.refresh(jan)
    assert jan.synced_from_cari is False and float(jan.amount) == 1000.0
    assert float(_fe(db, jan.id).amount) == 1000.0  # tahmini FE geri geldi


def test_unlinked_definition_unaffected(db):
    """vendor_id'siz recurring tanım senkrondan etkilenmez."""
    _seed(db, invoices=[(date(2026, 1, 5), 1500)], amount=500, link=False)
    res = sync_recurring_from_vendors(db)
    assert res["definitions"] == 0


def test_vendor_fe_suppressed_for_linked_vendor(db):
    """Bağlı carinin vendor_payment FE'si üretilmez/silinir; bağsız cari normal FE alır.

    Ayrıca sync_vendor_finance_events zinciri bağlı recurring girişlerini de senkronlar.
    """
    defn, linked_vendor = _seed(db, invoices=[(date(2026, 1, 5), 1500)], amount=1000,
                                due_dates=True)
    _, free_vendor = _seed(db, invoices=[(date(2026, 1, 8), 700)], amount=1000,
                           link=False, due_dates=True,
                           hesap_kodu="320.TEST.FREE", name="Bağsız Test")

    # Bağlı cari için eski bir vendor FE bırak (geçiş senaryosu) → sync temizlemeli
    vtx = db.query(VendorTransaction).filter(
        VendorTransaction.vendor_id == linked_vendor.id, VendorTransaction.alacak > 0
    ).first()
    db.add(FinanceEvent(source_type="vendor_payment", source_id=vtx.id,
                        event_date=date(2026, 1, 5), amount=1500, direction=-1,
                        currency="TRY", description="ESKİ", payment_method="cari",
                        vendor_id=linked_vendor.id, is_matched=False, is_realized=False))
    db.flush()

    sync_vendor_finance_events(db)

    linked_fes = db.query(FinanceEvent).filter(
        FinanceEvent.source_type == "vendor_payment",
        FinanceEvent.vendor_id == linked_vendor.id).count()
    free_fes = db.query(FinanceEvent).filter(
        FinanceEvent.source_type == "vendor_payment",
        FinanceEvent.vendor_id == free_vendor.id).count()
    assert linked_fes == 0   # bağlı cari: FE yok (eski de silindi)
    assert free_fes == 1     # bağsız cari: normal FIFO FE'si

    # Zincir çalıştı: bağlı tanımın Ocak girişi cari faturasıyla senkronlandı
    jan = _entries_by_period(defn)[(2026, 1)]
    assert jan.synced_from_cari is True and float(jan.amount) == 1500.0
    assert float(_fe(db, jan.id).amount) == 1500.0  # nakit akımı recurring FE temsil eder


def test_sync_endpoint_requires_use(client, viewer_user_headers):
    assert client.post(f"{PREFIX}/sync-vendors", headers=viewer_user_headers).status_code == 403


def test_sync_endpoint_works(client, auth_headers, db):
    """POST /recurring/sync-vendors — admin ile çalışır, senkron sayısını döner."""
    _seed(db, invoices=[(date(2026, 1, 5), 1500)], amount=1000)
    r = client.post(f"{PREFIX}/sync-vendors", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entries_synced"] >= 1 and body["definitions"] == 1
    assert body["details"][0]["vendor_name"] == "TEST ELEKTRİK A.Ş."


def test_billing_offset_shifts_invoice_to_consumption_month(db):
    """offset=1 → ay başı faturası önceki ay tüketimine atanır (su: Haz faturası → May entry)."""
    # Haziran-3 faturası 1200 (su: Mayıs tüketimi), Mayıs-4 faturası 900 (Nisan tüketimi)
    defn, _ = _seed(db, invoices=[(date(2026, 5, 4), 900), (date(2026, 6, 3), 1200)],
                    amount=1000, offset=1)
    sync_recurring_from_vendors(db)
    e = _entries_by_period(defn)
    # Haziran faturası → MAYIS entry (offset 1)
    assert float(e[(2026, 5)].amount) == 1200.0 and e[(2026, 5)].synced_from_cari is True
    # Mayıs faturası → NİSAN entry
    assert float(e[(2026, 4)].amount) == 900.0 and e[(2026, 4)].synced_from_cari is True
    # Haziran entry faturasız (Temmuz faturası gelmedi) → tahmini
    assert float(e[(2026, 6)].amount) == 1000.0 and e[(2026, 6)].synced_from_cari is False


def test_offset_zero_same_month(db):
    """offset=0 (elektrik) → fatura kendi ayına atanır (kayma yok)."""
    defn, _ = _seed(db, invoices=[(date(2026, 5, 31), 1500)], amount=1000, offset=0)
    sync_recurring_from_vendors(db)
    e = _entries_by_period(defn)
    assert float(e[(2026, 5)].amount) == 1500.0 and e[(2026, 5)].synced_from_cari is True


def test_start_month_change_regenerates_and_resyncs(client, auth_headers, db):
    """start_month değişince girişler yeniden üretilir + cari-bağlı ise otomatik yeniden senkronlanır."""
    defn, _ = _seed(db, invoices=[(date(2026, 1, 5), 1500), (date(2026, 5, 5), 900)],
                    amount=1000, start_month=5)
    # Başlangıçta Mayıs–Aralık (8 entry), Ocak yok
    periods = {(e.period_year, e.period_month) for e in defn.entries.all()}
    assert (2026, 1) not in periods and len(periods) == 8

    # start_month=1'e çek (API) → regenerate + otomatik cari senkron
    r = client.patch(f"{PREFIX}/{defn.id}", json={"start_month": 1}, headers=auth_headers)
    assert r.status_code == 200, r.text

    db.refresh(defn)
    e = _entries_by_period(defn)
    assert len(e) == 12  # Ocak–Aralık
    # Ocak faturası (1500, ödenmemiş) otomatik senkronlandı; FE gerçek kalanla yaşıyor
    assert float(e[(2026, 1)].amount) == 1500.0 and e[(2026, 1)].synced_from_cari is True
    assert float(_fe(db, e[(2026, 1)].id).amount) == 1500.0
    # Faturası olmayan ay (Şubat) tahmini kaldı
    assert float(e[(2026, 2)].amount) == 1000.0 and e[(2026, 2)].synced_from_cari is False


def test_other_modules_have_no_sync_endpoint(client, auth_headers):
    """Vendor-sync yalnız recurring'de; vergiler'de POST /sync-vendors YOK.

    Path GET /{defn_id} desenine düşer → POST için 405 (route yok). recurring'de ise 200.
    """
    assert client.post("/api/accounting/taxes/sync-vendors", headers=auth_headers).status_code == 405