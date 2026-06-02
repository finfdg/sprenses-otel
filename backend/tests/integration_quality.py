"""
Kalite Modülü Kapsamlı Test Scripti
====================================
Şablon CRUD, Form iş akışı, yetki kontrolleri ve edge-case senaryoları.

Test kullanıcıları:
- admin (id=1, Admin rolü) — tam kalite yetkisi
- ferit (id=2, Finans Muduru) — tam kalite yetkisi
- mehmet (id=3, Personel) — kalite yetkisi YOK
"""
import requests
import json
import sys
from datetime import date, timedelta

BASE = "https://sprenses.com/api"
PASSED = 0
FAILED = 0
ERRORS = []


def login(username: str, password: str) -> str:
    """Giriş yap, JWT token döndür."""
    r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login failed for {username}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def h(token: str) -> dict:
    """Authorization header oluştur."""
    return {"Authorization": f"Bearer {token}"}


def test(name: str, passed: bool, detail: str = ""):
    global PASSED, FAILED, ERRORS
    if passed:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail}")


# ═══════════════════════════════════════════════════════════════
print("=" * 70)
print("KALITE MODÜLÜ KAPSAMLI TESTLERİ")
print("=" * 70)

# ─── Giriş ────────────────────────────────────────────────────
print("\n📋 1. Kullanıcı Girişleri")
admin_token = login("admin", "admin123")
test("Admin giriş", admin_token is not None)

ferit_token = login("ferit", "ferit123")
test("Ferit giriş", ferit_token is not None)

mehmet_token = login("mehmet", "mehmet123")
test("Mehmet giriş (Personel)", mehmet_token is not None)

# ═══════════════════════════════════════════════════════════════
# ŞABLON TESTLERİ
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ŞABLON TESTLERİ")
print("=" * 70)

# ─── Şablon Listeleme ─────────────────────────────────────────
print("\n📋 2. Şablon Listeleme")
r = requests.get(f"{BASE}/quality/templates/", headers=h(admin_token))
test("Admin şablon listesi 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    data = r.json()
    test("Şablon listesi items içeriyor", "items" in data, str(data.keys()))
    test("En az 1 şablon var", len(data.get("items", [])) >= 1, f"count={len(data.get('items', []))}")

# ─── Personel erişim engeli ────────────────────────────────────
print("\n📋 3. Personel Yetki Kontrolü (Şablonlar)")
r = requests.get(f"{BASE}/quality/templates/", headers=h(mehmet_token))
test("Personel şablon listesi 403", r.status_code == 403, f"status={r.status_code}")

r = requests.post(f"{BASE}/quality/templates/", headers=h(mehmet_token), json={"name": "Test"})
test("Personel şablon oluşturma 403", r.status_code == 403, f"status={r.status_code}")

# ─── Şablon Oluşturma ─────────────────────────────────────────
print("\n📋 4. Şablon Oluşturma (Admin)")
template_payload = {
    "name": "Test Kalite Şablonu",
    "description": "Otomatik test için oluşturuldu",
    "frequency": "daily",
    "is_active": True,
    "sections": [
        {
            "name": "Genel Bilgiler",
            "sort_order": 0,
            "fields": [
                {
                    "label": "Konaklayan Kişi Sayısı",
                    "field_type": "number",
                    "unit": "kişi",
                    "is_required": True,
                    "is_resource": False,
                    "is_guest_count": True,
                    "sort_order": 0
                },
                {
                    "label": "Hava Durumu",
                    "field_type": "text",
                    "is_required": False,
                    "is_resource": False,
                    "is_guest_count": False,
                    "sort_order": 1
                }
            ]
        },
        {
            "name": "Tüketim Verileri",
            "sort_order": 1,
            "fields": [
                {
                    "label": "Elektrik Tüketimi",
                    "field_type": "number",
                    "unit": "kWh",
                    "is_required": True,
                    "is_resource": True,
                    "is_guest_count": False,
                    "sort_order": 0
                },
                {
                    "label": "Su Tüketimi",
                    "field_type": "number",
                    "unit": "m³",
                    "is_required": True,
                    "is_resource": True,
                    "is_guest_count": False,
                    "sort_order": 1
                }
            ]
        },
        {
            "name": "Kontrol Soruları",
            "sort_order": 2,
            "fields": [
                {
                    "label": "Jeneratör çalışıyor mu?",
                    "field_type": "yes_no",
                    "is_required": True,
                    "is_resource": False,
                    "is_guest_count": False,
                    "sort_order": 0
                },
                {
                    "label": "Temizlik Durumu",
                    "field_type": "select",
                    "is_required": True,
                    "is_resource": False,
                    "is_guest_count": False,
                    "options": '["İyi","Orta","Kötü"]',
                    "sort_order": 1
                }
            ]
        }
    ],
    "assignees": [
        {"assignment_type": "filler", "user_id": 1, "role_id": None},
        {"assignment_type": "filler", "user_id": 2, "role_id": None},
        {"assignment_type": "approver", "user_id": 1, "role_id": None}
    ]
}

r = requests.post(f"{BASE}/quality/templates/", headers=h(admin_token), json=template_payload)
test("Şablon oluşturma 201", r.status_code == 201, f"status={r.status_code} body={r.text[:200]}")
test_template_id = None
if r.status_code == 201:
    test_template_id = r.json()["id"]
    test("Şablon ID döndü", test_template_id is not None)

# ─── Şablon Detayı ────────────────────────────────────────────
print("\n📋 5. Şablon Detayı")
if test_template_id:
    r = requests.get(f"{BASE}/quality/templates/{test_template_id}", headers=h(admin_token))
    test("Şablon detayı 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        detail = r.json()
        test("Şablon adı doğru", detail["name"] == "Test Kalite Şablonu", detail.get("name"))
        test("3 bölüm var", len(detail.get("sections", [])) == 3, f"count={len(detail.get('sections', []))}")
        total_fields = sum(len(s.get("fields", [])) for s in detail.get("sections", []))
        test("6 alan var", total_fields == 6, f"count={total_fields}")
        test("3 atama var", len(detail.get("assignees", [])) == 3, f"count={len(detail.get('assignees', []))}")
        # guest_count alanı kontrolü
        guest_fields = [f for s in detail["sections"] for f in s["fields"] if f.get("is_guest_count")]
        test("Bir adet kişi sayısı alanı var", len(guest_fields) == 1, f"count={len(guest_fields)}")
        resource_fields = [f for s in detail["sections"] for f in s["fields"] if f.get("is_resource")]
        test("2 adet kaynak alanı var", len(resource_fields) == 2, f"count={len(resource_fields)}")

# ─── Şablon Güncelleme ────────────────────────────────────────
print("\n📋 6. Şablon Güncelleme")
if test_template_id:
    update_payload = {
        "name": "Test Kalite Şablonu (Güncellenmiş)",
        "description": "Güncellendi"
    }
    r = requests.patch(f"{BASE}/quality/templates/{test_template_id}", headers=h(admin_token), json=update_payload)
    test("Şablon güncelleme 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        test("Ad güncellendi", r.json()["name"] == "Test Kalite Şablonu (Güncellenmiş)")

    # Ferit ile güncelleme
    r = requests.patch(f"{BASE}/quality/templates/{test_template_id}", headers=h(ferit_token), json={"description": "Ferit güncelledi"})
    test("Ferit şablon güncelleyebilir 200", r.status_code == 200, f"status={r.status_code}")

    # Personel ile güncelleme
    r = requests.patch(f"{BASE}/quality/templates/{test_template_id}", headers=h(mehmet_token), json={"description": "Hack"})
    test("Personel güncelleme 403", r.status_code == 403, f"status={r.status_code}")

# ─── Şablon Aynı İsim Kontrolü ────────────────────────────────
print("\n📋 7. Şablon Tekrar Oluşturma (Aynı isim)")
r = requests.post(f"{BASE}/quality/templates/", headers=h(admin_token), json={
    "name": "Test Kalite Şablonu (Güncellenmiş)",
    "frequency": "daily"
})
test("Aynı isimle şablon oluşturma", r.status_code in [201, 409], f"status={r.status_code}")
# Temizlik: eğer oluştuysa sil
if r.status_code == 201:
    dup_id = r.json()["id"]
    requests.delete(f"{BASE}/quality/templates/{dup_id}", headers=h(admin_token))

# ═══════════════════════════════════════════════════════════════
# FORM TESTLERİ
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("FORM TESTLERİ")
print("=" * 70)

# ─── Form Listeleme ────────────────────────────────────────────
print("\n📋 8. Form Listeleme")
r = requests.get(f"{BASE}/quality/forms/", headers=h(admin_token))
test("Admin form listesi 200", r.status_code == 200, f"status={r.status_code}")

r = requests.get(f"{BASE}/quality/forms/", headers=h(mehmet_token))
test("Personel form listesi 403", r.status_code == 403, f"status={r.status_code}")

# ─── Manuel Form Oluşturma ────────────────────────────────────
print("\n📋 9. Manuel Form Oluşturma")
if test_template_id:
    # Yarın için form oluştur (bugün zaten mevcut olabilir)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = requests.post(f"{BASE}/quality/forms/", headers=h(admin_token), json={
        "template_id": test_template_id,
        "period_date": tomorrow
    })
    test("Manuel form oluşturma 201", r.status_code == 201, f"status={r.status_code} body={r.text[:300]}")
    test_form_id = r.json()["id"] if r.status_code == 201 else None

    # Aynı tarih/şablon ile tekrar (duplikat)
    if r.status_code == 201:
        r2 = requests.post(f"{BASE}/quality/forms/", headers=h(admin_token), json={
            "template_id": test_template_id,
            "period_date": tomorrow
        })
        test("Duplikat form 409", r2.status_code == 409, f"status={r2.status_code}")
else:
    test_form_id = None
    test("Manuel form oluşturma (şablon yok)", False, "test_template_id yok")

# ─── Scheduler ile Form Oluşturma ─────────────────────────────
print("\n📋 10. Scheduler ile Form Oluşturma")
r = requests.post(f"{BASE}/quality/scheduler/generate", headers=h(admin_token), json={})
test("Scheduler 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
if r.status_code == 200:
    gen_data = r.json()
    test("Scheduler response 'generated' alanı var", "generated" in gen_data, str(gen_data))

# İkinci çalıştırma — bugünün formları zaten var
r = requests.post(f"{BASE}/quality/scheduler/generate", headers=h(admin_token), json={})
if r.status_code == 200:
    test("Tekrar scheduler → 0 form", r.json().get("generated", -1) == 0, str(r.json()))

# Personel scheduler deneme
r = requests.post(f"{BASE}/quality/scheduler/generate", headers=h(mehmet_token), json={})
test("Personel scheduler 403", r.status_code == 403, f"status={r.status_code}")

# ─── Form Detayı ──────────────────────────────────────────────
print("\n📋 11. Form Detayı")
if test_form_id:
    r = requests.get(f"{BASE}/quality/forms/{test_form_id}", headers=h(admin_token))
    test("Form detayı 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        form_detail = r.json()
        test("Form durumu draft", form_detail["status"] == "draft", f"status={form_detail['status']}")
        test("Bölümler var", len(form_detail.get("sections", [])) > 0, f"sections={len(form_detail.get('sections', []))}")
        test("template_name dolu", form_detail.get("template_name") is not None)

        # Alan ID'lerini topla
        field_ids = {}
        for sec in form_detail.get("sections", []):
            for fld in sec.get("fields", []):
                field_ids[fld["label"]] = fld["id"]

# ─── Form Doldurma ────────────────────────────────────────────
print("\n📋 12. Form Doldurma")
if test_form_id and field_ids:
    fill_payload = {
        "values": [
            {"field_id": field_ids.get("Konaklayan Kişi Sayısı"), "value": "150", "corrective_action": None},
            {"field_id": field_ids.get("Hava Durumu"), "value": "Güneşli", "corrective_action": None},
            {"field_id": field_ids.get("Elektrik Tüketimi"), "value": "4500", "corrective_action": None},
            {"field_id": field_ids.get("Su Tüketimi"), "value": "320", "corrective_action": None},
            {"field_id": field_ids.get("Jeneratör çalışıyor mu?"), "value": "Hayır", "corrective_action": "Jeneratör tamire verildi"},
            {"field_id": field_ids.get("Temizlik Durumu"), "value": "İyi", "corrective_action": None},
        ],
        "notes": "Test açıklaması — otomatik test ile dolduruldu"
    }
    # None field_id'leri filtrele
    fill_payload["values"] = [v for v in fill_payload["values"] if v["field_id"] is not None]

    r = requests.patch(f"{BASE}/quality/forms/{test_form_id}/fill", headers=h(admin_token), json=fill_payload)
    test("Form doldurma 200", r.status_code == 200, f"status={r.status_code} body={r.text[:300]}")

    # Ferit de atanmış — o da doldurabilmeli
    r2 = requests.patch(f"{BASE}/quality/forms/{test_form_id}/fill", headers=h(ferit_token), json=fill_payload)
    test("Ferit form doldurabilir 200", r2.status_code == 200, f"status={r2.status_code} body={r2.text[:200]}")

    # Personel dolduramaz (yetki yok)
    r3 = requests.patch(f"{BASE}/quality/forms/{test_form_id}/fill", headers=h(mehmet_token), json=fill_payload)
    test("Personel form dolduramaz 403", r3.status_code == 403, f"status={r3.status_code}")

# ─── Form Gönderme (Submit) ───────────────────────────────────
print("\n📋 13. Form Gönderme")
if test_form_id:
    r = requests.post(f"{BASE}/quality/forms/{test_form_id}/submit", headers=h(admin_token), json={})
    test("Form gönderme 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    # Durumu kontrol et
    r2 = requests.get(f"{BASE}/quality/forms/{test_form_id}", headers=h(admin_token))
    if r2.status_code == 200:
        test("Form durumu submitted", r2.json()["status"] == "submitted", f"status={r2.json()['status']}")

    # Tekrar gönderme (zaten submitted — başarısız olmalı)
    r3 = requests.post(f"{BASE}/quality/forms/{test_form_id}/submit", headers=h(admin_token), json={})
    test("Tekrar gönderme engeli", r3.status_code in [400, 422], f"status={r3.status_code}")

# ─── Form İnceleme (Reddet) ───────────────────────────────────
print("\n📋 14. Form İnceleme — Reddetme")
if test_form_id:
    r = requests.post(f"{BASE}/quality/forms/{test_form_id}/review", headers=h(admin_token), json={
        "action": "reject",
        "comment": "Test reddi — düzeltme gerekiyor"
    })
    test("Form reddetme 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    # Durumu kontrol et
    r2 = requests.get(f"{BASE}/quality/forms/{test_form_id}", headers=h(admin_token))
    if r2.status_code == 200:
        test("Form durumu rejected", r2.json()["status"] == "rejected", f"status={r2.json()['status']}")
        test("Red yorumu kaydedildi", r2.json().get("review_comment") == "Test reddi — düzeltme gerekiyor",
             f"comment={r2.json().get('review_comment')}")

# ─── Reddedilen Formu Yeniden Açma ────────────────────────────
print("\n📋 15. Reddedilen Form Yeniden Açma")
if test_form_id:
    r = requests.post(f"{BASE}/quality/forms/{test_form_id}/reopen", headers=h(admin_token), json={})
    test("Form yeniden açma 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    r2 = requests.get(f"{BASE}/quality/forms/{test_form_id}", headers=h(admin_token))
    if r2.status_code == 200:
        test("Form durumu draft", r2.json()["status"] == "draft", f"status={r2.json()['status']}")

# ─── Tekrar Gönderme ve Onaylama ──────────────────────────────
print("\n📋 16. Tekrar Gönderme ve Onaylama")
if test_form_id:
    # Tekrar gönder
    r = requests.post(f"{BASE}/quality/forms/{test_form_id}/submit", headers=h(admin_token), json={})
    test("Tekrar gönderme 200", r.status_code == 200, f"status={r.status_code}")

    # Onayla
    r2 = requests.post(f"{BASE}/quality/forms/{test_form_id}/review", headers=h(admin_token), json={
        "action": "approve",
        "comment": "Test onayı"
    })
    test("Form onaylama 200", r2.status_code == 200, f"status={r2.status_code} body={r2.text[:200]}")

    # Durumu kontrol et
    r3 = requests.get(f"{BASE}/quality/forms/{test_form_id}", headers=h(admin_token))
    if r3.status_code == 200:
        test("Form durumu approved", r3.json()["status"] == "approved", f"status={r3.json()['status']}")

# ─── Onaylı Formu İncelemeye Çalışma ──────────────────────────
print("\n📋 17. Onaylı Form Edge Cases")
if test_form_id:
    # Onaylı formu tekrar onaylama
    r = requests.post(f"{BASE}/quality/forms/{test_form_id}/review", headers=h(admin_token), json={
        "action": "approve"
    })
    test("Onaylı formu tekrar onaylama engeli", r.status_code in [400, 422], f"status={r.status_code}")

    # Onaylı formu doldurma
    r2 = requests.patch(f"{BASE}/quality/forms/{test_form_id}/fill", headers=h(admin_token), json={
        "values": [], "notes": "Hack denemesi"
    })
    test("Onaylı formu doldurma engeli", r2.status_code in [400, 422], f"status={r2.status_code}")

    # Onaylı formu yeniden açma
    r3 = requests.post(f"{BASE}/quality/forms/{test_form_id}/reopen", headers=h(admin_token), json={})
    test("Onaylı formu yeniden açma engeli", r3.status_code in [400, 422], f"status={r3.status_code}")

# ═══════════════════════════════════════════════════════════════
# ZORUNLU ALAN TESTİ
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ZORUNLU ALAN TESTİ")
print("=" * 70)

print("\n📋 18. Zorunlu Alan Eksik Gönderme")
if test_template_id:
    # Yeni bir form oluştur (2 gün sonrası)
    day_after = (date.today() + timedelta(days=2)).isoformat()
    r = requests.post(f"{BASE}/quality/forms/", headers=h(admin_token), json={
        "template_id": test_template_id,
        "period_date": day_after
    })
    empty_form_id = r.json()["id"] if r.status_code == 201 else None

    if empty_form_id:
        # Hiçbir alan doldurmadan gönder
        r2 = requests.post(f"{BASE}/quality/forms/{empty_form_id}/submit", headers=h(admin_token), json={})
        test("Boş form gönderme engeli", r2.status_code in [400, 422], f"status={r2.status_code} body={r2.text[:200]}")

        # Kısmen doldur (sadece 1 alan)
        r_detail = requests.get(f"{BASE}/quality/forms/{empty_form_id}", headers=h(admin_token))
        if r_detail.status_code == 200:
            some_field = None
            for sec in r_detail.json().get("sections", []):
                for fld in sec.get("fields", []):
                    if fld.get("is_required"):
                        some_field = fld["id"]
                        break
                if some_field:
                    break
            if some_field:
                requests.patch(f"{BASE}/quality/forms/{empty_form_id}/fill", headers=h(admin_token), json={
                    "values": [{"field_id": some_field, "value": "42"}]
                })
                r3 = requests.post(f"{BASE}/quality/forms/{empty_form_id}/submit", headers=h(admin_token), json={})
                test("Kısmen dolu form gönderme engeli", r3.status_code in [400, 422],
                     f"status={r3.status_code} body={r3.text[:200]}")

        # Temizle — formu sil (veya bırak draft olarak)

# ═══════════════════════════════════════════════════════════════
# FİLTRE TESTLERİ
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("FİLTRE TESTLERİ")
print("=" * 70)

print("\n📋 19. Form Filtreleme")
r = requests.get(f"{BASE}/quality/forms/?status=approved", headers=h(admin_token))
test("Durum filtresi 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    forms = r.json().get("items", [])
    all_approved = all(f["status"] == "approved" for f in forms)
    test("Tüm sonuçlar approved", all_approved, f"statuses={[f['status'] for f in forms[:5]]}")

r = requests.get(f"{BASE}/quality/forms/?status=draft", headers=h(admin_token))
test("Draft filtresi 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    forms = r.json().get("items", [])
    all_draft = all(f["status"] == "draft" for f in forms)
    test("Tüm sonuçlar draft", all_draft, f"statuses={[f['status'] for f in forms[:5]]}")

if test_template_id:
    r = requests.get(f"{BASE}/quality/forms/?template_id={test_template_id}", headers=h(admin_token))
    test("Şablon filtresi 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        forms = r.json().get("items", [])
        all_match = all(f["template_id"] == test_template_id for f in forms)
        test("Tüm sonuçlar doğru şablona ait", all_match)

# Tarih filtreleri
today_str = date.today().isoformat()
r = requests.get(f"{BASE}/quality/forms/?date_from={today_str}&date_to={today_str}", headers=h(admin_token))
test("Tarih filtresi 200", r.status_code == 200, f"status={r.status_code}")

# ═══════════════════════════════════════════════════════════════
# ÖNCEKİ DÖNEM KARŞILAŞTIRMASI
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ÖNCEKİ DÖNEM KARŞILAŞTIRMASI")
print("=" * 70)

print("\n📋 20. Önceki Değerler (previous_values)")
if test_form_id:
    r = requests.get(f"{BASE}/quality/forms/{test_form_id}", headers=h(admin_token))
    if r.status_code == 200:
        pv = r.json().get("previous_values")
        test("previous_values alanı mevcut", pv is not None, f"previous_values={pv}")
        # İlk form olduğu için boş veya None olabilir — bu normal
        if pv is not None:
            test("previous_values liste veya boş", isinstance(pv, list), f"type={type(pv)}")

# ═══════════════════════════════════════════════════════════════
# SCHEDULER STATUS TESTİ
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SCHEDULER TESTLERİ")
print("=" * 70)

print("\n📋 21. Scheduler Status")
r = requests.get(f"{BASE}/quality/scheduler/status", headers=h(admin_token))
test("Scheduler status 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    test("Status response is list", isinstance(r.json(), list), f"type={type(r.json())}")

# ═══════════════════════════════════════════════════════════════
# ŞABLON SİLME TESTLERİ
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ŞABLON SİLME TESTLERİ")
print("=" * 70)

print("\n📋 22. Formu Olan Şablonu Silme Engeli")
if test_template_id:
    r = requests.delete(f"{BASE}/quality/templates/{test_template_id}", headers=h(admin_token))
    test("Formu olan şablon silme 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")

# Boş bir şablon oluştur ve sil
print("\n📋 23. Boş Şablon Oluştur ve Sil")
r = requests.post(f"{BASE}/quality/templates/", headers=h(admin_token), json={
    "name": "Silinecek Şablon",
    "frequency": "weekly"
})
if r.status_code == 201:
    del_id = r.json()["id"]
    r2 = requests.delete(f"{BASE}/quality/templates/{del_id}", headers=h(admin_token))
    test("Formsuz şablon silme 204", r2.status_code == 204, f"status={r2.status_code}")

    # Silinmiş şablona erişim
    r3 = requests.get(f"{BASE}/quality/templates/{del_id}", headers=h(admin_token))
    test("Silinen şablon 404", r3.status_code == 404, f"status={r3.status_code}")

# ═══════════════════════════════════════════════════════════════
# EDGE CASE: GEÇERSİZ VERİLER
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("EDGE CASE TESTLERİ")
print("=" * 70)

print("\n📋 24. Geçersiz Veri Testleri")

# Olmayan şablon ID'si ile form oluşturma
r = requests.post(f"{BASE}/quality/forms/", headers=h(admin_token), json={
    "template_id": 99999,
    "period_date": tomorrow
})
test("Geçersiz şablon ID 404", r.status_code == 404, f"status={r.status_code}")

# Olmayan form ID'sine erişim
r = requests.get(f"{BASE}/quality/forms/99999", headers=h(admin_token))
test("Geçersiz form ID 404", r.status_code == 404, f"status={r.status_code}")

# Olmayan şablon ID'sine erişim
r = requests.get(f"{BASE}/quality/templates/99999", headers=h(admin_token))
test("Geçersiz şablon ID 404", r.status_code == 404, f"status={r.status_code}")

# İsim olmadan şablon oluşturma
r = requests.post(f"{BASE}/quality/templates/", headers=h(admin_token), json={
    "frequency": "daily"
})
test("İsimsiz şablon engeli 422", r.status_code == 422, f"status={r.status_code}")

# Geçersiz review action
if test_form_id:
    r = requests.post(f"{BASE}/quality/forms/{test_form_id}/review", headers=h(admin_token), json={
        "action": "invalid_action"
    })
    test("Geçersiz review action engeli", r.status_code in [400, 422], f"status={r.status_code}")

# ═══════════════════════════════════════════════════════════════
# FERIT İLE FORM İŞ AKIŞI
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("FERİT İLE FORM İŞ AKIŞI")
print("=" * 70)

print("\n📋 25. Ferit Form Oluşturma ve Doldurma")
if test_template_id:
    three_days = (date.today() + timedelta(days=3)).isoformat()
    r = requests.post(f"{BASE}/quality/forms/", headers=h(ferit_token), json={
        "template_id": test_template_id,
        "period_date": three_days
    })
    test("Ferit form oluşturma 201", r.status_code == 201, f"status={r.status_code}")
    ferit_form_id = r.json()["id"] if r.status_code == 201 else None

    if ferit_form_id:
        # Detayı al
        r2 = requests.get(f"{BASE}/quality/forms/{ferit_form_id}", headers=h(ferit_token))
        if r2.status_code == 200:
            ferit_fields = {}
            for sec in r2.json().get("sections", []):
                for fld in sec.get("fields", []):
                    ferit_fields[fld["label"]] = fld["id"]

            # Doldur
            fill = {
                "values": [
                    {"field_id": ferit_fields.get("Konaklayan Kişi Sayısı"), "value": "200"},
                    {"field_id": ferit_fields.get("Hava Durumu"), "value": "Yağmurlu"},
                    {"field_id": ferit_fields.get("Elektrik Tüketimi"), "value": "5200"},
                    {"field_id": ferit_fields.get("Su Tüketimi"), "value": "380"},
                    {"field_id": ferit_fields.get("Jeneratör çalışıyor mu?"), "value": "Evet"},
                    {"field_id": ferit_fields.get("Temizlik Durumu"), "value": "Orta"},
                ],
                "notes": "Ferit tarafından test"
            }
            fill["values"] = [v for v in fill["values"] if v.get("field_id")]
            r3 = requests.patch(f"{BASE}/quality/forms/{ferit_form_id}/fill", headers=h(ferit_token), json=fill)
            test("Ferit form doldurma 200", r3.status_code == 200, f"status={r3.status_code}")

            # Gönder
            r4 = requests.post(f"{BASE}/quality/forms/{ferit_form_id}/submit", headers=h(ferit_token), json={})
            test("Ferit form gönderme 200", r4.status_code == 200, f"status={r4.status_code}")

            # Admin onayla
            r5 = requests.post(f"{BASE}/quality/forms/{ferit_form_id}/review", headers=h(admin_token), json={
                "action": "approve",
                "comment": "Admin tarafından onaylandı"
            })
            test("Admin Ferit formunu onayladı 200", r5.status_code == 200, f"status={r5.status_code}")


# ═══════════════════════════════════════════════════════════════
# TOKEN OLMADAN ERİŞİM
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("YETKİSİZ ERİŞİM TESTLERİ")
print("=" * 70)

print("\n📋 26. Token Olmadan Erişim")
r = requests.get(f"{BASE}/quality/templates/")
test("Token olmadan şablon listesi 401", r.status_code == 401, f"status={r.status_code}")

r = requests.get(f"{BASE}/quality/forms/")
test("Token olmadan form listesi 401", r.status_code == 401, f"status={r.status_code}")

r = requests.post(f"{BASE}/quality/scheduler/generate", json={})
test("Token olmadan scheduler 401", r.status_code == 401, f"status={r.status_code}")


# ═══════════════════════════════════════════════════════════════
# TEMİZLİK
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEMİZLİK")
print("=" * 70)

print("\n📋 27. Test Verilerini Temizle")
# Oluşturulan formları ve şablonu temizle
# Formları silebilmek için DB'den direkt silme gerekir (API'de form delete yok)
# Şablon silinemiyor çünkü formlar var — bu test verisi olarak kalacak
# Ama test_template_id şablonunu pasif yapabiliriz
if test_template_id:
    r = requests.patch(f"{BASE}/quality/templates/{test_template_id}", headers=h(admin_token), json={
        "is_active": False,
        "name": "Test Kalite Şablonu (TEST - PASİF)"
    })
    test("Test şablonu pasifleştirildi", r.status_code == 200, f"status={r.status_code}")


# ═══════════════════════════════════════════════════════════════
# SONUÇ
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"SONUÇ: {PASSED} geçti, {FAILED} başarısız")
print("=" * 70)

if ERRORS:
    print("\n❌ Başarısız Testler:")
    for e in ERRORS:
        print(f"  • {e}")

sys.exit(0 if FAILED == 0 else 1)
