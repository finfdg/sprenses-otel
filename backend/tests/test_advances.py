"""Alınan Avanslar modülü testleri."""
import pytest
from datetime import date


def test_list_advances_empty(client, auth_headers):
    """Boş avans listesi testi."""
    r = client.get("/api/finance/avanslar/", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 0


def test_create_advance(client, auth_headers):
    """Yeni avans oluşturma testi."""
    payload = {
        "agency_name": "Test Acente",
        "amount": 10000.00,
        "currency": "EUR",
        "advance_date": "2026-04-15",
        "notes": "Test avansı",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()
    assert data["agency_name"] == "Test Acente"
    assert data["amount"] == 10000.00
    assert data["currency"] == "EUR"
    assert data["status"] == "pending"
    return data["id"]


def test_summary(client, auth_headers):
    """Özet testi."""
    r = client.get("/api/finance/avanslar/summary", headers=auth_headers)
    assert r.status_code == 200


def test_update_advance(client, auth_headers):
    """Avans güncelleme testi."""
    # Create first
    payload = {
        "agency_name": "Güncelleme Testi",
        "amount": 5000.00,
        "currency": "USD",
        "advance_date": "2026-05-01",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    # Update
    r = client.patch(f"/api/finance/avanslar/{adv_id}", json={"notes": "Güncellenmiş"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["notes"] == "Güncellenmiş"


def test_match_advance(client, auth_headers):
    """Avans eşleştirme testi."""
    # Create
    payload = {
        "agency_name": "Eşleştirme Testi",
        "amount": 8000.00,
        "currency": "EUR",
        "advance_date": "2026-04-20",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    # Match
    r = client.post(f"/api/finance/avanslar/{adv_id}/match", json={
        "received_date": "2026-04-21",
        "received_amount": 7950.00,
    }, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "received"
    assert data["received_amount"] == 7950.00


def test_delete_advance(client, auth_headers):
    """Avans silme testi."""
    # Create
    payload = {
        "agency_name": "Silinecek",
        "amount": 3000.00,
        "currency": "TRY",
        "advance_date": "2026-06-01",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    # Delete
    r = client.delete(f"/api/finance/avanslar/{adv_id}", headers=auth_headers)
    assert r.status_code == 200


def test_delete_received_advance_fails(client, auth_headers):
    """Alınmış avans silinemez."""
    # Create & match
    payload = {
        "agency_name": "Silinemez",
        "amount": 2000.00,
        "currency": "EUR",
        "advance_date": "2026-04-25",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    r = client.post(f"/api/finance/avanslar/{adv_id}/match", json={
        "received_date": "2026-04-26",
        "received_amount": 2000.00,
    }, headers=auth_headers)
    assert r.status_code == 200

    # Try to delete
    r = client.delete(f"/api/finance/avanslar/{adv_id}", headers=auth_headers)
    assert r.status_code == 400
