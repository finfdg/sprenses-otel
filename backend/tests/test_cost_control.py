"""Maliyet Kontrol + Yönetim Paneli — operasyonel KPI füzyonu (stok tüketim ÷ doluluk).

occupancy_metrics + operational-kpi + price-variance + yonetim endpoint'leri.
"""
from datetime import date

from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.stock import StockDepot, StockMovement, StockProduct
from app.models.vendor_upload import VendorUpload
from app.utils.occupancy import occupancy_metrics

PREFIX = "/api/stok"
YPREFIX = "/api/yonetim"


def _seed_occupancy(db):
    """1 oda tipi (100 oda) + Mart konaklaması: 03-02→03-04 (2 gece), 1 oda, 2 yetişkin."""
    db.add(RoomType(code="STD", name="Standart", total_rooms=100, is_active=True))
    db.add(Reservation(
        rec_id=900001, checkin_date=date(2026, 3, 2), checkout_date=date(2026, 3, 4), nights=2,
        record_date=date(2026, 1, 1), rooms=1, adult=2, child_paid=0, child_free=0, baby=0,
        agency="TESTACENTE", nation="DE", board="AI", eur_total=300, currency="EUR", rez_status="Definite",
    ))
    db.flush()


def _seed_stock_consume(db, period_amounts):
    """fb (002) tüketim hareketleri. period_amounts = {period: amount}."""
    db.add(StockDepot(code="002", name="ANA MUTFAK", cost_group="fb"))
    db.flush()
    lid = 50000
    for period, amt in period_amounts.items():
        y, m = map(int, period.split("-"))
        lid += 1
        db.add(StockMovement(sedna_line_id=lid, date=date(y, m, 15), period=period,
                             type_code=29, type_label="Tüketim", direction="consume",
                             cons_depot="002", quantity=1, unit_cost=amt, net_amount=amt))
    db.flush()


def _seed_purchases(db, product_id, costs):
    """Bir ürün için alış hareketleri (fiyat sapması). costs = [(date, unit_cost)]."""
    up = VendorUpload(file_name="t", file_url="/t"); db.add(up); db.flush()
    db.add(StockProduct(sedna_id=product_id, code="P", name="DOMATES", current_stock=0, last_cost=0))
    lid = 60000
    for d, c in costs:
        lid += 1
        db.add(StockMovement(sedna_line_id=lid, date=d, period=d.strftime("%Y-%m"),
                             type_code=12, type_label="Alış", direction="in",
                             product_sedna_id=product_id, product_name="DOMATES",
                             quantity=1, unit_cost=c, net_amount=c, supplier_name="TEDARİK"))
    db.flush()


def test_occupancy_metrics(db):
    """Geceleme = pax×gece (overlap): 2 yetişkin × 2 gece = 4; oda-gece = 1×2 = 2."""
    _seed_occupancy(db)
    m = occupancy_metrics(db, date(2026, 3, 1), date(2026, 3, 31))
    assert m["guest_nights"] == 4 and m["room_nights"] == 2 and m["capacity"] == 100


def test_operational_kpi_fusion(db, client, auth_headers):
    """Kişi başı F&B maliyeti = fb tüketim ÷ geceleme (eşleşen ay). Mart: 400 ÷ 4 = 100 TL."""
    _seed_occupancy(db)
    _seed_stock_consume(db, {"2026-03": 400})
    r = client.get(f"{PREFIX}/operational-kpi", headers=auth_headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["kpi"]["cost_per_guest_night_try"] == 100.0
    assert j["kpi"]["matched_periods"] == ["2026-03"]
    assert j["consumption"]["fb"] == 400.0
    # Mart aylık satırı eşleşmiş
    mar = next(m for m in j["monthly"] if m["period"] == "2026-03")
    assert mar["matched"] is True and mar["guest_nights"] == 4


def test_operational_kpi_unmatched_month_excluded(db, client, auth_headers):
    """Tüketimi olmayan (geç post) ay headline'a girmez — dilüsyon yok."""
    _seed_occupancy(db)  # sadece Mart doluluk
    _seed_stock_consume(db, {"2026-03": 400, "2026-05": 0})  # Mayıs tüketim 0
    j = client.get(f"{PREFIX}/operational-kpi", headers=auth_headers).json()
    # Yalnız Mart eşleşir (Mayıs'ta tüketim yok); 400÷4=100
    assert j["kpi"]["matched_periods"] == ["2026-03"] and j["kpi"]["cost_per_guest_night_try"] == 100.0


def test_price_variance(db, client, auth_headers):
    """Son alış vs medyan: 100, 150 → medyan 125, son 150, sapma %20 (gerçek hareket)."""
    _seed_purchases(db, 7001, [(date(2026, 1, 5), 100), (date(2026, 3, 5), 150)])
    j = client.get(f"{PREFIX}/price-variance", headers=auth_headers).json()
    item = next(x for x in j["items"] if x["product_id"] == 7001)
    assert item["avg_cost"] == 125.0 and item["last_cost"] == 150.0 and item["variance_pct"] == 20.0
    assert item["category"] == "price"


def test_price_anomaly_split(db, client, auth_headers):
    """Medyandan >3× sapan son alış → 'anomalies' (birim/miktar hatası), 'items'a GİRMEZ.

    Medyan aykırı girişe dayanıklı: 4 normal + 1 dev alış → medyan normal kalır.
    """
    _seed_purchases(db, 7002, [
        (date(2026, 1, 5), 38), (date(2026, 1, 10), 40), (date(2026, 2, 1), 39),
        (date(2026, 2, 10), 41), (date(2026, 3, 1), 2100),  # son alış: çuval-adedi hatası gibi
    ])
    j = client.get(f"{PREFIX}/price-variance", headers=auth_headers).json()
    assert 7002 not in {x["product_id"] for x in j["items"]}        # gerçek harekete girmez
    anom = {x["product_id"]: x for x in j["anomalies"]}
    assert 7002 in anom                                             # anomali olarak işaretlenir
    a = anom[7002]
    assert a["median_cost"] == 40.0 and a["last_cost"] == 2100.0 and a["category"] == "entry"


def test_product_purchases_pdf_turkish_name(db, client, auth_headers):
    """PDF endpoint Türkçe karakterli ürün adında 200 döner (header latin-1 regresyonu).

    HTTP header'ları latin-1 olmalı → ürün adı (ör. 'PED BEYAZ CİLA', İ=U+0130) header'a
    konulamaz. Eskiden X-Doc-Name header'ına ürün adı yazılıyordu → İ'li üründe 500.
    """
    _seed_purchases(db, 7050, [(date(2026, 1, 5), 100), (date(2026, 3, 5), 150)])
    # Ürün adını Türkçe karakterli yap
    p = db.query(StockProduct).filter(StockProduct.sedna_id == 7050).first()
    p.name = "PED BEYAZ CİLA 51 CM"
    db.query(StockMovement).filter(StockMovement.product_sedna_id == 7050).update(
        {StockMovement.product_name: "PED BEYAZ CİLA 51 CM"}
    )
    db.flush()
    r = client.get(f"{PREFIX}/product-purchases/7050/pdf", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"


def test_yonetim_dashboard(db, client, auth_headers):
    """Dashboard tüm bölümleri döndürür + doluluk/maliyet füzyonu içerir."""
    _seed_occupancy(db)
    _seed_stock_consume(db, {"2026-03": 400})
    j = client.get(f"{YPREFIX}/dashboard", headers=auth_headers).json()
    assert "occupancy" in j and "cost" in j and "finance" in j and "gop_approx_try" in j
    assert j["cost"]["cost_per_guest_night_try"] == 100.0
    assert j["food_cost_pct"] is None  # all-inclusive: ayrı F&B geliri yok → kavramsal olarak N/A


def test_yonetim_alerts_and_classification(db, client, auth_headers):
    j = client.get(f"{YPREFIX}/alerts", headers=auth_headers).json()
    assert "price_variance" in j and "supplier_debt_top" in j and "critical_stock" in j
    c = client.get(f"{YPREFIX}/cost-classification", headers=auth_headers).json()
    assert len(c["items"]) == 3 and {x["key"] for x in c["items"]} == {"variable", "semi", "fixed"}


def test_yonetim_requires_permission(client, no_perm_user_headers):
    assert client.get(f"{YPREFIX}/dashboard", headers=no_perm_user_headers).status_code == 403
    assert client.get(f"{YPREFIX}/alerts", headers=no_perm_user_headers).status_code == 403
