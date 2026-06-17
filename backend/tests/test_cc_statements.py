"""Kredi Kartı Ekstreleri (cc_statements) — listele / detay / sil + RBAC.

PDF yükleme (parser) hariç tutuldu — gerçek PDF fixture'ı gerektirir. Audit'te
'testi olmayan finansal modül' (Yüksek) olarak işaretlenmişti.
"""

from datetime import date
from uuid import uuid4

from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditProduct

API = "/api/finance/krediler/kart"


def _make_product_with_statement(db):
    prod = CreditProduct(type="kredi_karti", name="Test Kart", currency="TRY")
    db.add(prod)
    db.flush()
    stmt = CreditCardStatement(
        credit_product_id=prod.id, ekstre_no=uuid4().hex[:8],
        kesim_tarihi=date(2026, 5, 1), son_odeme_tarihi=date(2026, 5, 20),
        toplam_borc=12500.50, asgari_odeme=1250.0, is_paid=False, paid_amount=0,
    )
    db.add(stmt)
    db.commit()
    return prod, stmt


class TestListStatements:
    def test_list(self, client, auth_headers, db):
        prod, stmt = _make_product_with_statement(db)
        r = client.get(f"{API}/{prod.id}/statements", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert stmt.id in [s["id"] for s in r.json()]

    def test_list_non_cc_product_404(self, client, auth_headers, db):
        # kredi_karti olmayan ürün için liste 404
        prod = CreditProduct(type="taksitli", name="Taksitli Kredi", currency="TRY")
        db.add(prod)
        db.commit()
        assert client.get(f"{API}/{prod.id}/statements", headers=auth_headers).status_code == 404

    def test_list_requires_view(self, client, no_perm_user_headers, db):
        prod, _ = _make_product_with_statement(db)
        assert client.get(f"{API}/{prod.id}/statements", headers=no_perm_user_headers).status_code == 403


class TestGetStatement:
    def test_get(self, client, auth_headers, db):
        prod, stmt = _make_product_with_statement(db)
        r = client.get(f"{API}/{prod.id}/statements/{stmt.id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert float(r.json()["toplam_borc"]) == 12500.50

    def test_get_404(self, client, auth_headers, db):
        prod, _ = _make_product_with_statement(db)
        assert client.get(f"{API}/{prod.id}/statements/99999999", headers=auth_headers).status_code == 404


class TestDeleteStatement:
    def test_delete(self, client, auth_headers, db):
        prod, stmt = _make_product_with_statement(db)
        sid = stmt.id
        r = client.delete(f"{API}/{prod.id}/statements/{sid}", headers=auth_headers)
        assert r.status_code == 204, r.text
        db.expire_all()
        assert db.get(CreditCardStatement, sid) is None

    def test_delete_requires_use(self, client, viewer_user_headers, db):
        prod, stmt = _make_product_with_statement(db)
        # viewer (yalnız view, use yok) → 403
        r = client.delete(f"{API}/{prod.id}/statements/{stmt.id}", headers=viewer_user_headers)
        assert r.status_code == 403
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id) is not None  # silinmemiş

    def test_delete_404(self, client, auth_headers, db):
        prod, _ = _make_product_with_statement(db)
        assert client.delete(f"{API}/{prod.id}/statements/99999999", headers=auth_headers).status_code == 404
