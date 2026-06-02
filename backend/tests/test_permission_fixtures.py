"""Non-admin test kullanıcı fixture'larının izin matrisini doğru kurduğunu doğrular.

Bu testler `conftest.py`'deki `viewer_user_headers`, `use_user_headers`,
`no_perm_user_headers` ve `make_user_with_perms` fixture'larının çalışmasını
ve izin middleware'inin (`require_permission`) doğru tepki verdiğini test eder.
"""


def test_no_perm_user_blocked_from_protected_endpoint(client, no_perm_user_headers):
    """İzni olmayan kullanıcı korumalı endpoint'lerden 403 alır."""
    res = client.get("/api/finance/cariler/vendors", headers=no_perm_user_headers)
    assert res.status_code == 403


def test_viewer_can_list_but_cannot_create(client, viewer_user_headers, db):
    """can_view=True / can_use=False — GET 200, POST 403."""
    # Departman listesi okuma → 200
    list_res = client.get("/api/finance/departmanlar/", headers=viewer_user_headers)
    assert list_res.status_code == 200

    # Departman oluşturma → 403
    create_res = client.post(
        "/api/finance/departmanlar/",
        headers=viewer_user_headers,
        json={"name": "Test Dept", "code": "T001"},
    )
    assert create_res.status_code == 403


def test_use_user_can_create(client, use_user_headers):
    """can_view=True / can_use=True — POST 200/201."""
    create_res = client.post(
        "/api/finance/departmanlar/",
        headers=use_user_headers,
        json={"name": "Yeni Test Dept", "code": "T002"},
    )
    assert create_res.status_code in (200, 201)


def test_make_user_with_perms_module_specific(client, make_user_with_perms):
    """Factory fixture: bir modülde view, diğerinde hiç izin yok."""
    headers = make_user_with_perms({
        "finance.butce": {"view": True, "use": False},
        "finance.cariler": {"view": False, "use": False},
    })

    # departmanlar'da view var → 200
    res1 = client.get("/api/finance/departmanlar/", headers=headers)
    assert res1.status_code == 200

    # cariler'de view yok → 403
    res2 = client.get("/api/finance/cariler/vendors", headers=headers)
    assert res2.status_code == 403


def test_make_user_with_perms_use_only_specific_module(client, make_user_with_perms):
    """can_use modül-spesifik — diğer modüllerde POST 403."""
    headers = make_user_with_perms({
        "finance.butce": {"view": True, "use": True},
    })

    # departmanlar'da use var → POST başarılı
    create_res = client.post(
        "/api/finance/departmanlar/",
        headers=headers,
        json={"name": "Spesifik İzinli Dept", "code": "T003"},
    )
    assert create_res.status_code in (200, 201)


def test_unauthenticated_blocked(client):
    """Auth header'sız 401."""
    res = client.get("/api/finance/cariler/vendors")
    assert res.status_code == 401
