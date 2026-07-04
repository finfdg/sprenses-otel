"""Planlı gider/gelir CRUD testleri — scheduled_base fabrikası.

Bu tek test dosyası, scheduled_base.create_scheduled_router() tarafından
üretilen generic endpoint'leri test eder. Aynı CRUD pattern'ını kullanan
7 modül (vergiler, düzenli ödemeler, alınan/verilen kiralar, maaş, stopaj,
SGK) burada parametrik olarak kapsanır. (Temettü artık bespoke — bkz.
tests/test_dividend.py.)
"""

import pytest
from datetime import date


# ─── Modül parametreleri ────────────────────────────────────

MODULES = [
    # (api_prefix, source_type, entity_label, direction)
    ("/api/accounting/taxes", "tax", "Vergi", -1),
    ("/api/accounting/recurring", "recurring", "Düzenli Ödeme", -1),
    ("/api/accounting/rent-income", "rent_income", "Alınan Kira", 1),
    ("/api/accounting/rent-expense", "rent_expense", "Verilen Kira", -1),
    ("/api/hr/salary", "salary", "Maaş", -1),
    ("/api/hr/withholding", "withholding", "Stopaj", -1),
    ("/api/hr/sgk", "sgk", "SGK", -1),
]

MODULE_IDS = [m[1] for m in MODULES]


# ─── Yardımcı fonksiyonlar ──────────────────────────────────

def _create_definition(client, auth_headers, prefix, **overrides):
    """Yeni bir tanım oluştur ve yanıtı döndür."""
    payload = {
        "name": "Test Tanım",
        "amount": 5000.0,
        "currency": "TRY",
        "frequency": "monthly",
        "payment_day": 15,
        "start_month": 1,
        "year": 2026,
    }
    payload.update(overrides)
    resp = client.post(prefix + "/", json=payload, headers=auth_headers)
    return resp


# ─── CREATE testleri ────────────────────────────────────────


class TestCreate:
    """Tanım oluşturma testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES, ids=MODULE_IDS)
    def test_create_monthly(self, client, auth_headers, prefix, source_type, label, direction):
        """Aylık tanım oluşturma — 12 giriş üretilmeli (start_month=1)."""
        resp = _create_definition(client, auth_headers, prefix, frequency="monthly", start_month=1)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["source_type"] == source_type
        assert data["name"] == "Test Tanım"
        assert data["amount"] == 5000.0
        assert data["frequency"] == "monthly"
        assert data["is_active"] is True
        # Aylık, Ocak'tan başlayınca 12 giriş olmalı
        assert len(data["entries"]) == 12
        # Tüm girişlerin source_type'ı doğru olmalı
        for entry in data["entries"]:
            assert entry["source_type"] == source_type
            assert entry["is_paid"] is False
            assert entry["amount"] == 5000.0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_quarterly(self, client, auth_headers, prefix, source_type, label, direction):
        """Üç aylık tanım — 4 giriş üretilmeli (start_month=1)."""
        resp = _create_definition(client, auth_headers, prefix, frequency="quarterly", start_month=1)
        assert resp.status_code == 201
        entries = resp.json()["entries"]
        assert len(entries) == 4
        # Üç aylık: Ocak, Nisan, Temmuz, Ekim
        months = [e["entry_date"].split("-")[1] for e in entries]
        assert months == ["01", "04", "07", "10"]

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_yearly(self, client, auth_headers, prefix, source_type, label, direction):
        """Yıllık tanım — 1 giriş üretilmeli."""
        resp = _create_definition(client, auth_headers, prefix, frequency="yearly", start_month=6)
        assert resp.status_code == 201
        entries = resp.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["entry_date"] == "2026-06-15"

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_with_category(self, client, auth_headers, prefix, source_type, label, direction):
        """Kategori ile oluşturma — açıklama kategoriden oluşturulmalı."""
        resp = _create_definition(
            client, auth_headers, prefix,
            name="Gelir Vergisi", category="İnsan Kaynakları",
        )
        assert resp.status_code == 201
        entries = resp.json()["entries"]
        assert entries[0]["description"].endswith("- İnsan Kaynakları")

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_start_month_mid_year(self, client, auth_headers, prefix, source_type, label, direction):
        """Yıl ortasından başlayan aylık tanım — kalan ay kadar giriş."""
        resp = _create_definition(client, auth_headers, prefix, start_month=7)
        assert resp.status_code == 201
        entries = resp.json()["entries"]
        # Temmuz'dan Aralık'a = 6 giriş
        assert len(entries) == 6

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_payment_day_28(self, client, auth_headers, prefix, source_type, label, direction):
        """payment_day=28 — Şubat dahil sorunsuz çalışmalı."""
        resp = _create_definition(client, auth_headers, prefix, payment_day=28)
        assert resp.status_code == 201
        entries = resp.json()["entries"]
        # Şubat girişi 28. gün olmalı
        feb_entry = [e for e in entries if e["entry_date"].startswith("2026-02")]
        assert len(feb_entry) == 1
        assert feb_entry[0]["entry_date"] == "2026-02-28"


class TestCreateValidation:
    """Oluşturma doğrulama testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_empty_name(self, client, auth_headers, prefix, source_type, label, direction):
        """Boş isim — 422 hatası."""
        resp = _create_definition(client, auth_headers, prefix, name="")
        assert resp.status_code == 422

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_negative_amount(self, client, auth_headers, prefix, source_type, label, direction):
        """Negatif tutar — 422 hatası."""
        resp = _create_definition(client, auth_headers, prefix, amount=-100)
        assert resp.status_code == 422

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_zero_amount(self, client, auth_headers, prefix, source_type, label, direction):
        """Sıfır tutar — 422 hatası."""
        resp = _create_definition(client, auth_headers, prefix, amount=0)
        assert resp.status_code == 422

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_invalid_frequency(self, client, auth_headers, prefix, source_type, label, direction):
        """Geçersiz frekans — 422 hatası."""
        resp = _create_definition(client, auth_headers, prefix, frequency="weekly")
        assert resp.status_code == 422

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_payment_day_out_of_range(self, client, auth_headers, prefix, source_type, label, direction):
        """payment_day > 28 — 422 hatası."""
        resp = _create_definition(client, auth_headers, prefix, payment_day=29)
        assert resp.status_code == 422

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_create_start_month_out_of_range(self, client, auth_headers, prefix, source_type, label, direction):
        """start_month > 12 — 422 hatası."""
        resp = _create_definition(client, auth_headers, prefix, start_month=13)
        assert resp.status_code == 422


# ─── LIST testleri ──────────────────────────────────────────


class TestList:
    """Listeleme testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES, ids=MODULE_IDS)
    def test_list_empty(self, client, auth_headers, prefix, source_type, label, direction):
        """Boş liste — sayfalama yapısını döndürmeli."""
        resp = client.get(prefix + "/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_list_with_data(self, client, auth_headers, prefix, source_type, label, direction):
        """Veri ile listeleme — oluşturulan tanım listede olmalı."""
        _create_definition(client, auth_headers, prefix)
        resp = client.get(prefix + "/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1
        # Girişler dahil gelir
        assert "entries" in data["items"][0]

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_list_year_filter(self, client, auth_headers, prefix, source_type, label, direction):
        """Yıl filtresi — sadece o yılın tanımları gelir."""
        _create_definition(client, auth_headers, prefix, year=2026)
        _create_definition(client, auth_headers, prefix, year=2025, name="Eski Tanım")

        resp2026 = client.get(prefix + "/?year=2026", headers=auth_headers)
        resp2025 = client.get(prefix + "/?year=2025", headers=auth_headers)
        respAll = client.get(prefix + "/", headers=auth_headers)

        assert resp2026.json()["total"] >= 1
        assert resp2025.json()["total"] >= 1
        assert respAll.json()["total"] >= 2

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_list_pagination(self, client, auth_headers, prefix, source_type, label, direction):
        """Sayfalama — page_size=1 ile ilk sayfada 1 kayıt."""
        _create_definition(client, auth_headers, prefix, name="Tanım A")
        _create_definition(client, auth_headers, prefix, name="Tanım B")

        resp = client.get(prefix + "/?page=1&page_size=1", headers=auth_headers)
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] >= 2
        assert data["pages"] >= 2

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_list_source_type_isolation(self, client, auth_headers, prefix, source_type, label, direction):
        """Farklı modüllerin tanımları birbirini görmemeli."""
        # Vergi oluştur
        _create_definition(client, auth_headers, "/api/accounting/taxes", name="Vergi Tanım")
        # Maaş oluştur
        _create_definition(client, auth_headers, "/api/hr/salary", name="Maaş Tanım")

        # Vergi listesinde maaş olmamalı
        resp_tax = client.get("/api/accounting/taxes/", headers=auth_headers)
        tax_names = [d["name"] for d in resp_tax.json()["items"]]
        assert "Maaş Tanım" not in tax_names

        # Maaş listesinde vergi olmamalı
        resp_salary = client.get("/api/hr/salary/", headers=auth_headers)
        salary_names = [d["name"] for d in resp_salary.json()["items"]]
        assert "Vergi Tanım" not in salary_names


# ─── GET (detail) testleri ──────────────────────────────────


class TestGetDetail:
    """Tekil tanım getirme testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_get_detail(self, client, auth_headers, prefix, source_type, label, direction):
        """ID ile tanım getirme — girişler dahil."""
        create_resp = _create_definition(client, auth_headers, prefix)
        defn_id = create_resp.json()["id"]

        resp = client.get(f"{prefix}/{defn_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == defn_id
        assert "entries" in data
        assert len(data["entries"]) > 0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_get_detail_not_found(self, client, auth_headers, prefix, source_type, label, direction):
        """Var olmayan ID — 404."""
        resp = client.get(f"{prefix}/999999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_get_detail_wrong_source_type(self, client, auth_headers, prefix, source_type, label, direction):
        """Farklı modülün ID'si — 404 (source_type uyumsuz)."""
        # Vergi oluştur
        create_resp = _create_definition(client, auth_headers, "/api/accounting/taxes")
        defn_id = create_resp.json()["id"]

        # Maaş endpoint'inden o ID'yi sorgula — 404 olmalı
        resp = client.get(f"/api/hr/salary/{defn_id}", headers=auth_headers)
        assert resp.status_code == 404


# ─── UPDATE testleri ────────────────────────────────────────


class TestUpdate:
    """Tanım güncelleme testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_name(self, client, auth_headers, prefix, source_type, label, direction):
        """İsim güncelleme — girişler değişmemeli."""
        create_resp = _create_definition(client, auth_headers, prefix)
        defn_id = create_resp.json()["id"]
        orig_entries_count = len(create_resp.json()["entries"])

        resp = client.patch(
            f"{prefix}/{defn_id}",
            json={"name": "Güncellenmiş İsim"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Güncellenmiş İsim"
        # İsim değişikliği regeneration tetiklemez
        assert len(data["entries"]) == orig_entries_count

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_amount_triggers_regeneration(self, client, auth_headers, prefix, source_type, label, direction):
        """Tutar değişikliği — girişler yeniden üretilmeli."""
        create_resp = _create_definition(client, auth_headers, prefix, amount=1000)
        defn_id = create_resp.json()["id"]

        resp = client.patch(
            f"{prefix}/{defn_id}",
            json={"amount": 2000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 2000.0
        # Yeni girişlerin tutarı güncellenmeli
        for entry in data["entries"]:
            assert entry["amount"] == 2000.0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_frequency_triggers_regeneration(self, client, auth_headers, prefix, source_type, label, direction):
        """Frekans değişikliği — giriş sayısı değişmeli."""
        create_resp = _create_definition(
            client, auth_headers, prefix, frequency="monthly", start_month=1,
        )
        defn_id = create_resp.json()["id"]
        assert len(create_resp.json()["entries"]) == 12

        resp = client.patch(
            f"{prefix}/{defn_id}",
            json={"frequency": "quarterly"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # Aylıktan 3 aylığa → 12'den 4'e
        assert len(resp.json()["entries"]) == 4

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_no_change(self, client, auth_headers, prefix, source_type, label, direction):
        """Aynı değerle güncelleme — 200 ama değişiklik yok."""
        create_resp = _create_definition(client, auth_headers, prefix)
        defn_id = create_resp.json()["id"]

        resp = client.patch(
            f"{prefix}/{defn_id}",
            json={"name": "Test Tanım"},  # Aynı isim
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_not_found(self, client, auth_headers, prefix, source_type, label, direction):
        """Var olmayan ID — 404."""
        resp = client.patch(
            f"{prefix}/999999",
            json={"name": "Yeni İsim"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_preserves_paid_entries(self, client, auth_headers, prefix, source_type, label, direction):
        """Tutar değişince ödenmiş girişler korunmalı."""
        create_resp = _create_definition(client, auth_headers, prefix, amount=1000)
        defn_id = create_resp.json()["id"]
        first_entry_id = create_resp.json()["entries"][0]["id"]

        # İlk girişi ödenmiş olarak işaretle
        client.patch(
            f"{prefix}/entries/{first_entry_id}",
            json={"is_paid": True},
            headers=auth_headers,
        )

        # Tutarı değiştir → regeneration tetiklenir
        resp = client.patch(
            f"{prefix}/{defn_id}",
            json={"amount": 2000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        entries = resp.json()["entries"]

        # Ödenmiş giriş korunmalı (eski tutar ile)
        paid_entries = [e for e in entries if e["is_paid"]]
        assert len(paid_entries) >= 1
        assert paid_entries[0]["amount"] == 1000.0

        # Ödenmemiş girişler yeni tutarla üretilmeli
        unpaid_entries = [e for e in entries if not e["is_paid"]]
        for entry in unpaid_entries:
            assert entry["amount"] == 2000.0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_is_active(self, client, auth_headers, prefix, source_type, label, direction):
        """is_active değişikliği — regeneration tetiklemez."""
        create_resp = _create_definition(client, auth_headers, prefix)
        defn_id = create_resp.json()["id"]
        orig_count = len(create_resp.json()["entries"])

        resp = client.patch(
            f"{prefix}/{defn_id}",
            json={"is_active": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        assert len(resp.json()["entries"]) == orig_count


# ─── DELETE testleri ────────────────────────────────────────


class TestDelete:
    """Tanım silme testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_delete(self, client, auth_headers, prefix, source_type, label, direction):
        """Tanım silme — başarılı."""
        create_resp = _create_definition(client, auth_headers, prefix)
        defn_id = create_resp.json()["id"]

        resp = client.delete(f"{prefix}/{defn_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert "silindi" in resp.json()["detail"]

        # Silinen tanım artık gelmiyor
        get_resp = client.get(f"{prefix}/{defn_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_delete_not_found(self, client, auth_headers, prefix, source_type, label, direction):
        """Var olmayan ID — 404."""
        resp = client.delete(f"{prefix}/999999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_delete_cascades_entries(self, client, auth_headers, prefix, source_type, label, direction):
        """Silme girişleri de kaldırır — listede görünmez."""
        create_resp = _create_definition(client, auth_headers, prefix)
        defn_id = create_resp.json()["id"]

        # Sil
        client.delete(f"{prefix}/{defn_id}", headers=auth_headers)

        # Listede artık yok
        list_resp = client.get(prefix + "/", headers=auth_headers)
        ids = [d["id"] for d in list_resp.json()["items"]]
        assert defn_id not in ids


# ─── ENTRY UPDATE testleri ──────────────────────────────────


class TestEntryUpdate:
    """Giriş güncelleme testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_mark_as_paid(self, client, auth_headers, prefix, source_type, label, direction):
        """Girişi ödenmiş olarak işaretle — paid_date otomatik set edilir."""
        create_resp = _create_definition(client, auth_headers, prefix)
        entry_id = create_resp.json()["entries"][0]["id"]

        resp = client.patch(
            f"{prefix}/entries/{entry_id}",
            json={"is_paid": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_paid"] is True
        assert data["paid_date"] is not None
        # REGRESYON: varsayılan ödeme tarihi PLANLI gün (entry_date) olmalı, bugün DEĞİL —
        # geçmiş ödemeleri toplu işaretlerken hepsi "bugüne" yığılmasın.
        assert data["paid_date"] == data["entry_date"]

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_entry_amount(self, client, auth_headers, prefix, source_type, label, direction):
        """Giriş tutarını güncelle."""
        create_resp = _create_definition(client, auth_headers, prefix, amount=1000)
        entry_id = create_resp.json()["entries"][0]["id"]

        resp = client.patch(
            f"{prefix}/entries/{entry_id}",
            json={"amount": 1500},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["amount"] == 1500.0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_entry_notes(self, client, auth_headers, prefix, source_type, label, direction):
        """Giriş notu güncelle."""
        create_resp = _create_definition(client, auth_headers, prefix)
        entry_id = create_resp.json()["entries"][0]["id"]

        resp = client.patch(
            f"{prefix}/entries/{entry_id}",
            json={"notes": "Ödeme yapıldı"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["notes"] == "Ödeme yapıldı"

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_entry_not_found(self, client, auth_headers, prefix, source_type, label, direction):
        """Var olmayan giriş — 404."""
        resp = client.patch(
            f"{prefix}/entries/999999",
            json={"is_paid": True},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_update_entry_no_change(self, client, auth_headers, prefix, source_type, label, direction):
        """Aynı değerle güncelleme — 200 döner."""
        create_resp = _create_definition(client, auth_headers, prefix, amount=5000)
        entry_id = create_resp.json()["entries"][0]["id"]

        resp = client.patch(
            f"{prefix}/entries/{entry_id}",
            json={"amount": 5000.0},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_mark_paid_with_explicit_date(self, client, auth_headers, prefix, source_type, label, direction):
        """Ödenme tarihi açıkça verilirse o tarih kullanılmalı."""
        create_resp = _create_definition(client, auth_headers, prefix)
        entry_id = create_resp.json()["entries"][0]["id"]

        resp = client.patch(
            f"{prefix}/entries/{entry_id}",
            json={"is_paid": True, "paid_date": "2026-03-20"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["paid_date"] == "2026-03-20"

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_entry_wrong_source_type(self, client, auth_headers, prefix, source_type, label, direction):
        """Farklı modülün girişini güncelleyemez — 404."""
        # Vergi oluştur
        create_resp = _create_definition(client, auth_headers, "/api/accounting/taxes")
        entry_id = create_resp.json()["entries"][0]["id"]

        # Maaş endpoint'inden aynı entry_id ile güncelleme dene
        resp = client.patch(
            f"/api/hr/salary/entries/{entry_id}",
            json={"is_paid": True},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ─── SUMMARY testleri ───────────────────────────────────────


class TestSummary:
    """Özet endpoint testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES, ids=MODULE_IDS)
    def test_summary_structure(self, client, auth_headers, prefix, source_type, label, direction):
        """Özet — yanıt yapısı doğru olmalı."""
        # Uzak gelecek yılı kullan — production verisinin olmadığı yıl
        resp = client.get(f"{prefix}/summary/totals?year=2099", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["year"] == 2099
        assert "total" in data
        assert "paid" in data
        assert "pending" in data
        assert "count" in data
        assert "paid_count" in data
        # 2099'da veri olmayacağı için sıfır olmalı
        assert data["total"] == 0
        assert data["paid"] == 0
        assert data["count"] == 0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_summary_with_data(self, client, auth_headers, prefix, source_type, label, direction):
        """Veri ile özet — doğru toplamlar."""
        create_resp = _create_definition(
            client, auth_headers, prefix, amount=1000, year=2026,
        )
        entries = create_resp.json()["entries"]
        entry_count = len(entries)

        resp = client.get(f"{prefix}/summary/totals?year=2026", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1000.0 * entry_count
        assert data["paid"] == 0
        assert data["pending"] == 1000.0 * entry_count
        assert data["count"] >= entry_count
        assert data["paid_count"] == 0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_summary_with_paid_entries(self, client, auth_headers, prefix, source_type, label, direction):
        """Ödenmiş girişler — paid toplamı artmalı."""
        create_resp = _create_definition(
            client, auth_headers, prefix, amount=1000, year=2026,
        )
        entries = create_resp.json()["entries"]

        # İlk 3 girişi öde
        for entry in entries[:3]:
            client.patch(
                f"{prefix}/entries/{entry['id']}",
                json={"is_paid": True},
                headers=auth_headers,
            )

        resp = client.get(f"{prefix}/summary/totals?year=2026", headers=auth_headers)
        data = resp.json()
        assert data["paid"] == 3000.0
        assert data["paid_count"] == 3
        assert data["pending"] == data["total"] - 3000.0

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_summary_year_filter(self, client, auth_headers, prefix, source_type, label, direction):
        """Farklı yıl filtresi — sadece o yılın verileri."""
        _create_definition(client, auth_headers, prefix, amount=1000, year=2026)
        _create_definition(client, auth_headers, prefix, amount=2000, year=2025, name="Eski")

        resp2026 = client.get(f"{prefix}/summary/totals?year=2026", headers=auth_headers)
        resp2025 = client.get(f"{prefix}/summary/totals?year=2025", headers=auth_headers)

        # 2026 toplamı 1000*12=12000 olmalı (sadece o yılın tanımı)
        assert resp2026.json()["total"] == 12000.0
        assert resp2025.json()["total"] == 24000.0  # 2025 = 2000*12

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_summary_inactive_excluded(self, client, auth_headers, prefix, source_type, label, direction):
        """Pasif tanımlar özete dahil edilmez."""
        create_resp = _create_definition(
            client, auth_headers, prefix, amount=1000, year=2026,
        )
        defn_id = create_resp.json()["id"]

        # Pasif yap
        client.patch(
            f"{prefix}/{defn_id}",
            json={"is_active": False},
            headers=auth_headers,
        )

        resp = client.get(f"{prefix}/summary/totals?year=2026", headers=auth_headers)
        # Pasif tanımın girişleri özete dahil edilmemeli
        assert resp.json()["total"] == 0


# ─── Tam CRUD döngüsü testleri ─────────────────────────────


class TestFullCycle:
    """Uçtan uca CRUD döngüsü testleri."""

    @pytest.mark.parametrize("prefix,source_type,label,direction", MODULES[:1], ids=MODULE_IDS[:1])
    def test_full_lifecycle(self, client, auth_headers, prefix, source_type, label, direction):
        """Oluştur → Listele → Güncelle → Girişi öde → Sil tam döngüsü."""
        # 1. Oluştur
        create_resp = _create_definition(client, auth_headers, prefix, amount=3000)
        assert create_resp.status_code == 201
        defn_id = create_resp.json()["id"]
        entries = create_resp.json()["entries"]
        assert len(entries) > 0

        # 2. Listele
        list_resp = client.get(prefix + "/", headers=auth_headers)
        assert list_resp.status_code == 200
        assert any(d["id"] == defn_id for d in list_resp.json()["items"])

        # 3. Güncelle (isim)
        update_resp = client.patch(
            f"{prefix}/{defn_id}",
            json={"name": "Güncel Tanım"},
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Güncel Tanım"

        # 4. Girişi öde
        entry_id = entries[0]["id"]
        pay_resp = client.patch(
            f"{prefix}/entries/{entry_id}",
            json={"is_paid": True},
            headers=auth_headers,
        )
        assert pay_resp.status_code == 200
        assert pay_resp.json()["is_paid"] is True

        # 5. Özet kontrolü
        summary_resp = client.get(f"{prefix}/summary/totals?year=2026", headers=auth_headers)
        assert summary_resp.status_code == 200
        assert summary_resp.json()["paid"] >= 3000.0

        # 6. Sil
        del_resp = client.delete(f"{prefix}/{defn_id}", headers=auth_headers)
        assert del_resp.status_code == 200

        # 7. Silindiğini doğrula
        get_resp = client.get(f"{prefix}/{defn_id}", headers=auth_headers)
        assert get_resp.status_code == 404


# ─── İzin testleri ──────────────────────────────────────────


class TestPermissions:
    """İzin kontrolü testleri."""

    def test_unauthenticated_access(self, client):
        """Kimlik doğrulaması olmadan erişim — 401/403."""
        resp = client.get("/api/accounting/taxes/")
        assert resp.status_code in (401, 403)

    def test_unauthenticated_create(self, client):
        """Kimlik doğrulaması olmadan oluşturma — 401/403."""
        resp = client.post("/api/accounting/taxes/", json={
            "name": "Test", "amount": 1000,
        })
        assert resp.status_code in (401, 403)

    def test_unauthenticated_summary(self, client):
        """Kimlik doğrulaması olmadan özet — 401/403."""
        resp = client.get("/api/accounting/taxes/summary/totals")
        assert resp.status_code in (401, 403)


class TestPayNextMonth:
    """pay_next_month: dönemin ödemesi bir sonraki ayın payment_day'inde yapılır (ör. Ocak → 10 Şubat)."""

    PREFIX = "/api/accounting/recurring"

    def test_payment_date_unit_shift_and_rollover(self):
        from app.utils.entry_generator import _payment_date
        assert _payment_date("recurring", 2026, 1, 10, pay_next_month=True) == date(2026, 2, 10)
        assert _payment_date("recurring", 2026, 12, 10, pay_next_month=True) == date(2027, 1, 10)  # yıl geçişi
        assert _payment_date("recurring", 2026, 1, 10, pay_next_month=False) == date(2026, 1, 10)  # aynı ay
        # salary zaten kaynak-bazlı kayar (pay_next_month=False olsa da)
        assert _payment_date("salary", 2026, 1, 10, pay_next_month=False) == date(2026, 2, 10)

    def test_create_pay_next_month_shifts_dates(self, client, auth_headers):
        resp = _create_definition(client, auth_headers, self.PREFIX,
                                  payment_day=10, start_month=1, pay_next_month=True)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["pay_next_month"] is True
        entries = sorted(data["entries"], key=lambda e: e["period_month"])
        assert entries[0]["period_month"] == 1 and entries[0]["entry_date"] == "2026-02-10"  # Ocak → 10 Şubat
        assert entries[1]["entry_date"] == "2026-03-10"
        dec = [e for e in entries if e["period_month"] == 12][0]
        assert dec["entry_date"] == "2027-01-10"  # Aralık → 10 Ocak 2027

    def test_create_default_same_month(self, client, auth_headers):
        resp = _create_definition(client, auth_headers, self.PREFIX, payment_day=10, start_month=1)
        data = resp.json()
        assert data["pay_next_month"] is False
        jan = [e for e in data["entries"] if e["period_month"] == 1][0]
        assert jan["entry_date"] == "2026-01-10"  # varsayılan aynı ay

    def test_update_pay_next_month_regenerates(self, client, auth_headers):
        create = _create_definition(client, auth_headers, self.PREFIX, payment_day=10, start_month=1)
        defn_id = create.json()["id"]
        upd = client.patch(f"{self.PREFIX}/{defn_id}", json={"pay_next_month": True}, headers=auth_headers)
        assert upd.status_code == 200, upd.text
        detail = client.get(f"{self.PREFIX}/{defn_id}", headers=auth_headers).json()
        assert detail["pay_next_month"] is True
        jan = [e for e in detail["entries"] if e["period_month"] == 1][0]
        assert jan["entry_date"] == "2026-02-10"  # güncellemede yeniden üretilip sonraki aya kaydı
