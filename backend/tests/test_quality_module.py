"""Kalite modülü detaylı testleri (templates, forms, scheduler)."""

import pytest
from datetime import date, timedelta
from app.models.quality_template import QualityTemplate
from app.models.quality_template_section import QualityTemplateSection
from app.models.quality_template_field import QualityTemplateField
from app.models.quality_form import QualityForm
from app.models.quality_form_value import QualityFormValue


@pytest.fixture
def test_template(db):
    """Test şablonu oluştur."""
    t = QualityTemplate(
        name="Test Şablon",
        description="Test açıklaması",
        frequency="daily",
        is_active=True,
        created_by=1,
    )
    db.add(t)
    db.flush()

    sec = QualityTemplateSection(
        template_id=t.id,
        name="Test Bölüm",
        sort_order=0,
    )
    db.add(sec)
    db.flush()

    field1 = QualityTemplateField(
        section_id=sec.id,
        label="Test Alanı",
        field_type="number",
        is_required=True,
        sort_order=0,
    )
    field2 = QualityTemplateField(
        section_id=sec.id,
        label="Opsiyonel Alan",
        field_type="text",
        is_required=False,
        sort_order=1,
    )
    db.add(field1)
    db.add(field2)
    db.commit()
    db.refresh(t)
    db.refresh(sec)
    db.refresh(field1)
    db.refresh(field2)

    yield t

    # Temizlik
    db.query(QualityFormValue).filter(
        QualityFormValue.form_id.in_(
            db.query(QualityForm.id).filter(QualityForm.template_id == t.id)
        )
    ).delete(synchronize_session=False)
    db.query(QualityForm).filter(QualityForm.template_id == t.id).delete()
    db.query(QualityTemplateField).filter(QualityTemplateField.section_id == sec.id).delete()
    db.query(QualityTemplateSection).filter(QualityTemplateSection.template_id == t.id).delete()
    db.delete(t)
    db.commit()


@pytest.fixture
def test_form(db, test_template):
    """Test formu oluştur."""
    form = QualityForm(
        template_id=test_template.id,
        period_date=date.today(),
        status="draft",
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


# ==================== ŞABLON LİSTE TESTLERİ ====================


class TestTemplateList:
    """Şablon listeleme testleri."""

    def test_list_templates_success(self, client, auth_headers):
        """Şablon listesi döndürmeli."""
        response = client.get("/api/quality/templates/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_list_templates_pagination(self, client, auth_headers):
        """Sayfalama çalışmalı."""
        response = client.get("/api/quality/templates/?page=1&page_size=5", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 5

    def test_list_templates_active_filter(self, client, auth_headers, test_template):
        """Aktif filtresi çalışmalı."""
        response = client.get("/api/quality/templates/?is_active=true", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert all(item["is_active"] for item in data["items"])

    def test_list_templates_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/quality/templates/")
        assert response.status_code == 401


# ==================== ŞABLON DETAY TESTLERİ ====================


class TestTemplateDetail:
    """Şablon detay testleri."""

    def test_get_template_success(self, client, auth_headers, test_template):
        """Şablon detayı görüntülenebilmeli."""
        response = client.get(f"/api/quality/templates/{test_template.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Şablon"
        assert len(data["sections"]) == 1
        assert len(data["sections"][0]["fields"]) == 2

    def test_get_template_not_found(self, client, auth_headers):
        """Olmayan şablon 404 dönmeli."""
        response = client.get("/api/quality/templates/999999", headers=auth_headers)
        assert response.status_code == 404


# ==================== ŞABLON CRUD TESTLERİ ====================


class TestTemplateCRUD:
    """Şablon oluşturma, güncelleme, silme testleri."""

    def test_create_template(self, client, auth_headers, db):
        """Şablon oluşturulabilmeli."""
        response = client.post("/api/quality/templates/", headers=auth_headers, json={
            "name": "Yeni Test Şablon",
            "description": "Test",
            "frequency": "daily",
            "is_active": True,
            "sections": [
                {
                    "name": "Bölüm 1",
                    "sort_order": 0,
                    "fields": [
                        {"label": "Alan 1", "field_type": "number", "is_required": True, "sort_order": 0},
                    ],
                },
            ],
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Yeni Test Şablon"
        assert len(data["sections"]) == 1
        # Temizlik
        t = db.query(QualityTemplate).filter(QualityTemplate.name == "Yeni Test Şablon").first()
        if t:
            db.query(QualityTemplateField).filter(
                QualityTemplateField.section_id.in_(
                    db.query(QualityTemplateSection.id).filter(QualityTemplateSection.template_id == t.id)
                )
            ).delete(synchronize_session=False)
            db.query(QualityTemplateSection).filter(QualityTemplateSection.template_id == t.id).delete()
            db.delete(t)
            db.commit()

    def test_create_template_empty_name(self, client, auth_headers):
        """Boş isimle şablon oluşturma hata vermeli."""
        response = client.post("/api/quality/templates/", headers=auth_headers, json={
            "name": "  ",
            "frequency": "daily",
        })
        assert response.status_code == 400

    def test_create_template_invalid_frequency(self, client, auth_headers):
        """Geçersiz sıklık hata vermeli."""
        response = client.post("/api/quality/templates/", headers=auth_headers, json={
            "name": "Test",
            "frequency": "invalid",
        })
        assert response.status_code == 400

    def test_update_template(self, client, auth_headers, test_template):
        """Şablon güncellenebilmeli."""
        response = client.patch(
            f"/api/quality/templates/{test_template.id}",
            headers=auth_headers,
            json={"name": "Güncellenmiş Şablon"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Güncellenmiş Şablon"

    def test_update_template_not_found(self, client, auth_headers):
        """Olmayan şablon 404 dönmeli."""
        response = client.patch("/api/quality/templates/999999", headers=auth_headers, json={
            "name": "Test",
        })
        assert response.status_code == 404

    def test_delete_template_no_forms(self, client, auth_headers, db):
        """Formu olmayan şablon silinebilmeli."""
        t = QualityTemplate(name="Silinecek", frequency="daily", is_active=True, created_by=1)
        db.add(t)
        db.commit()
        db.refresh(t)

        response = client.delete(f"/api/quality/templates/{t.id}", headers=auth_headers)
        assert response.status_code == 204

    def test_delete_template_with_forms(self, client, auth_headers, test_template, test_form):
        """Formu olan şablon silinemez."""
        response = client.delete(f"/api/quality/templates/{test_template.id}", headers=auth_headers)
        assert response.status_code == 400
        assert "form" in response.json()["detail"].lower()

    def test_delete_template_not_found(self, client, auth_headers):
        """Olmayan şablon 404 dönmeli."""
        response = client.delete("/api/quality/templates/999999", headers=auth_headers)
        assert response.status_code == 404


# ==================== FORM LİSTE TESTLERİ ====================


class TestFormList:
    """Form listeleme testleri."""

    def test_list_forms(self, client, auth_headers):
        """Form listesi döndürmeli."""
        response = client.get("/api/quality/forms/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_list_forms_status_filter(self, client, auth_headers, test_form):
        """Durum filtresi çalışmalı."""
        response = client.get("/api/quality/forms/?status=draft", headers=auth_headers)
        assert response.status_code == 200

    def test_list_forms_template_filter(self, client, auth_headers, test_form, test_template):
        """Şablon filtresi çalışmalı."""
        response = client.get(
            f"/api/quality/forms/?template_id={test_template.id}",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_list_forms_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/quality/forms/")
        assert response.status_code == 401


# ==================== FORM DETAY TESTLERİ ====================


class TestFormDetail:
    """Form detay testleri."""

    def test_get_form_success(self, client, auth_headers, test_form, test_template):
        """Form detayı görüntülenebilmeli."""
        response = client.get(f"/api/quality/forms/{test_form.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["template_id"] == test_template.id
        assert data["status"] == "draft"
        assert "sections" in data

    def test_get_form_not_found(self, client, auth_headers):
        """Olmayan form 404 dönmeli."""
        response = client.get("/api/quality/forms/999999", headers=auth_headers)
        assert response.status_code == 404


# ==================== FORM WORKFLOW TESTLERİ ====================


class TestFormWorkflow:
    """Form iş akışı testleri (fill, submit, review, reopen, delete)."""

    def test_fill_form(self, client, auth_headers, test_form, db):
        """Form doldurulabilmeli."""
        sec = db.query(QualityTemplateSection).filter(
            QualityTemplateSection.template_id == test_form.template_id
        ).first()
        fields = db.query(QualityTemplateField).filter(
            QualityTemplateField.section_id == sec.id
        ).all()

        response = client.patch(
            f"/api/quality/forms/{test_form.id}/fill",
            headers=auth_headers,
            json={
                "values": [
                    {"field_id": fields[0].id, "value": "42"},
                    {"field_id": fields[1].id, "value": "Not"},
                ],
                "notes": "Test notu",
            },
        )
        assert response.status_code == 200

    def test_fill_submitted_form_fails(self, client, auth_headers, test_form, db):
        """Gönderilmiş form düzenlenemez."""
        test_form.status = "submitted"
        db.commit()

        response = client.patch(
            f"/api/quality/forms/{test_form.id}/fill",
            headers=auth_headers,
            json={"values": []},
        )
        assert response.status_code == 400
        # Geri al
        test_form.status = "draft"
        db.commit()

    def test_submit_form_missing_required(self, client, auth_headers, test_form):
        """Zorunlu alanlar doldurulmadan gönderme hata vermeli."""
        response = client.post(
            f"/api/quality/forms/{test_form.id}/submit",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "zorunlu" in response.json()["detail"].lower()

    def test_full_workflow(self, client, auth_headers, test_form, db):
        """Tam iş akışı: fill → submit → review(approve)."""
        sec = db.query(QualityTemplateSection).filter(
            QualityTemplateSection.template_id == test_form.template_id
        ).first()
        required_field = db.query(QualityTemplateField).filter(
            QualityTemplateField.section_id == sec.id,
            QualityTemplateField.is_required == True,
        ).first()

        # 1. Doldur
        fill_resp = client.patch(
            f"/api/quality/forms/{test_form.id}/fill",
            headers=auth_headers,
            json={
                "values": [{"field_id": required_field.id, "value": "100"}],
            },
        )
        assert fill_resp.status_code == 200

        # 2. Gönder
        submit_resp = client.post(
            f"/api/quality/forms/{test_form.id}/submit",
            headers=auth_headers,
        )
        assert submit_resp.status_code == 200
        assert submit_resp.json()["status"] == "submitted"

        # 3. Onayla
        review_resp = client.post(
            f"/api/quality/forms/{test_form.id}/review",
            headers=auth_headers,
            json={"action": "approve", "comment": "Onaylandı"},
        )
        assert review_resp.status_code == 200
        assert review_resp.json()["status"] == "approved"

    def test_reject_and_reopen(self, client, auth_headers, test_form, db):
        """Reddet ve yeniden aç akışı."""
        sec = db.query(QualityTemplateSection).filter(
            QualityTemplateSection.template_id == test_form.template_id
        ).first()
        required_field = db.query(QualityTemplateField).filter(
            QualityTemplateField.section_id == sec.id,
            QualityTemplateField.is_required == True,
        ).first()

        # Doldur ve gönder
        client.patch(
            f"/api/quality/forms/{test_form.id}/fill",
            headers=auth_headers,
            json={"values": [{"field_id": required_field.id, "value": "50"}]},
        )
        client.post(f"/api/quality/forms/{test_form.id}/submit", headers=auth_headers)

        # Reddet
        reject_resp = client.post(
            f"/api/quality/forms/{test_form.id}/review",
            headers=auth_headers,
            json={"action": "reject", "comment": "Düzeltilmeli"},
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"

        # Yeniden aç
        reopen_resp = client.post(
            f"/api/quality/forms/{test_form.id}/reopen",
            headers=auth_headers,
        )
        assert reopen_resp.status_code == 200
        assert reopen_resp.json()["status"] == "draft"

    def test_review_non_submitted_fails(self, client, auth_headers, test_form):
        """Gönderilmemiş form onaylanamaz."""
        response = client.post(
            f"/api/quality/forms/{test_form.id}/review",
            headers=auth_headers,
            json={"action": "approve"},
        )
        assert response.status_code == 400

    def test_reopen_non_rejected_fails(self, client, auth_headers, test_form):
        """Reddedilmemiş form yeniden açılamaz."""
        response = client.post(
            f"/api/quality/forms/{test_form.id}/reopen",
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_delete_draft_form(self, client, auth_headers, db, test_template):
        """Taslak form silinebilmeli."""
        form = QualityForm(
            template_id=test_template.id,
            period_date=date.today() - timedelta(days=100),
            status="draft",
        )
        db.add(form)
        db.commit()
        db.refresh(form)

        response = client.delete(f"/api/quality/forms/{form.id}", headers=auth_headers)
        assert response.status_code == 204

    def test_delete_submitted_form_fails(self, client, auth_headers, db, test_template):
        """Gönderilmiş form silinemez."""
        form = QualityForm(
            template_id=test_template.id,
            period_date=date.today() - timedelta(days=101),
            status="submitted",
        )
        db.add(form)
        db.commit()
        db.refresh(form)

        response = client.delete(f"/api/quality/forms/{form.id}", headers=auth_headers)
        assert response.status_code == 400

        # Temizlik
        db.delete(form)
        db.commit()


# ==================== ZAMANLAYICI TESTLERİ ====================


class TestScheduler:
    """Zamanlayıcı testleri."""

    def test_scheduler_status(self, client, auth_headers):
        """Zamanlayıcı durumu döndürmeli."""
        response = client.get("/api/quality/scheduler/status", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_scheduler_generate(self, client, auth_headers):
        """Form oluşturma çalışmalı."""
        response = client.post("/api/quality/scheduler/generate", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "generated" in data
        assert "skipped" in data
        assert "date" in data

    def test_scheduler_idempotent(self, client, auth_headers):
        """İkinci çalıştırmada mükerrer oluşmamalı."""
        client.post("/api/quality/scheduler/generate", headers=auth_headers)
        response = client.post("/api/quality/scheduler/generate", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["generated"] == 0

    def test_scheduler_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.post("/api/quality/scheduler/generate")
        assert response.status_code == 401


# ==================== FORM OLUŞTURMA TESTLERİ ====================


class TestFormCreate:
    """Form oluşturma testleri."""

    def test_create_form(self, client, auth_headers, test_template, db):
        """Manuel form oluşturulabilmeli."""
        pd = date.today() - timedelta(days=200)
        response = client.post("/api/quality/forms/", headers=auth_headers, json={
            "template_id": test_template.id,
            "period_date": pd.isoformat(),
        })
        assert response.status_code == 201
        assert response.json()["status"] == "draft"
        # Temizlik
        f = db.query(QualityForm).filter(
            QualityForm.template_id == test_template.id,
            QualityForm.period_date == pd,
        ).first()
        if f:
            db.delete(f)
            db.commit()

    def test_create_form_duplicate(self, client, auth_headers, test_form, test_template):
        """Aynı tarih-şablon çifti 409 dönmeli."""
        response = client.post("/api/quality/forms/", headers=auth_headers, json={
            "template_id": test_template.id,
            "period_date": date.today().isoformat(),
        })
        assert response.status_code == 409

    def test_create_form_invalid_template(self, client, auth_headers):
        """Olmayan şablon 404 dönmeli."""
        response = client.post("/api/quality/forms/", headers=auth_headers, json={
            "template_id": 999999,
            "period_date": date.today().isoformat(),
        })
        assert response.status_code == 404
