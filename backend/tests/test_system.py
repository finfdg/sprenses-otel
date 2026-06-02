"""Sistem yönetimi testleri."""


def test_list_users(client, auth_headers):
    response = client.get("/api/system/users/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] > 0


def test_list_roles(client, auth_headers):
    response = client.get("/api/system/roles/", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_modules(client, auth_headers):
    response = client.get("/api/system/modules/", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_module_tree(client, auth_headers):
    response = client.get("/api/system/modules/tree", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_users_unauthorized(client):
    response = client.get("/api/system/users/")
    assert response.status_code == 401  # Token olmadan erişim reddedilir


def test_rate_limiting(client):
    """Rate limiting testi — 6 ardışık başarısız giriş denemesi."""
    for i in range(5):
        client.post("/api/auth/login", json={
            "username": "ratetest",
            "password": "wrong",
        })
    # 6th request should be rate limited
    response = client.post("/api/auth/login", json={
        "username": "ratetest",
        "password": "wrong",
    })
    assert response.status_code == 429
