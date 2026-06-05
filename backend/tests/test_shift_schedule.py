"""Vardiya çizelgesi (hr.shift_schedule) — rota endpoint testleri.

GET aralık + atama/upsert + silme + toplu (bulk) + hafta kopyalama + izin + doğrulama.
"""
import uuid
from datetime import time

import pytest

from app.models.personnel import Personnel
from app.models.shift import ShiftDefinition

PREFIX = "/api/hr/shift-schedule"


@pytest.fixture
def two_shifts(db):
    s1 = ShiftDefinition(name="Sabah T", color="#3b82f6", start_time=time(7, 0), end_time=time(15, 0))
    s2 = ShiftDefinition(name="Akşam T", color="#f59e0b", start_time=time(15, 0), end_time=time(23, 0))
    db.add_all([s1, s2])
    db.flush()
    return s1.id, s2.id


@pytest.fixture
def two_people(db):
    p1 = Personnel(full_name="Ali Test", employee_code=f"T-{uuid.uuid4().hex[:6]}",
                   department="Mutfak", title="Aşçı", access_token=uuid.uuid4().hex, is_active=True)
    p2 = Personnel(full_name="Ayşe Test", employee_code=f"T-{uuid.uuid4().hex[:6]}",
                   department="Resepsiyon", title="Görevli", access_token=uuid.uuid4().hex, is_active=True)
    db.add_all([p1, p2])
    db.flush()
    return p1.id, p2.id


# ── İzin geçitleri ───────────────────────────────────────

def test_get_requires_view(client, no_perm_user_headers):
    r = client.get(f"{PREFIX}?start=2026-06-01&end=2026-06-07", headers=no_perm_user_headers)
    assert r.status_code == 403


def test_assign_requires_use(client, viewer_user_headers, two_shifts, two_people):
    s1, _ = two_shifts
    p1, _ = two_people
    r = client.post(PREFIX, json={"personnel_id": p1, "shift_id": s1, "work_date": "2026-06-02"},
                    headers=viewer_user_headers)
    assert r.status_code == 403


# ── GET yapısı ───────────────────────────────────────────

def test_get_structure(client, auth_headers, two_shifts, two_people):
    p1, p2 = two_people
    r = client.get(f"{PREFIX}?start=2026-06-01&end=2026-06-07", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert {"start", "end", "departments", "shifts", "personnel", "assignments"} <= set(d.keys())
    pids = {p["id"] for p in d["personnel"]}
    assert p1 in pids and p2 in pids
    assert "Mutfak" in d["departments"]


# ── Atama / upsert / silme ───────────────────────────────

def test_assign_upsert_get_delete(client, auth_headers, two_shifts, two_people):
    s1, s2 = two_shifts
    p1, _ = two_people
    # atama
    r = client.post(PREFIX, json={"personnel_id": p1, "shift_id": s1, "work_date": "2026-06-02"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["shift_id"] == s1
    # upsert (aynı hücre) → id sabit, vardiya değişir
    r = client.post(PREFIX, json={"personnel_id": p1, "shift_id": s2, "work_date": "2026-06-02"}, headers=auth_headers)
    assert r.status_code in (200, 201)
    assert r.json()["id"] == aid and r.json()["shift_id"] == s2
    # GET yansıtıyor
    r = client.get(f"{PREFIX}?start=2026-06-01&end=2026-06-07", headers=auth_headers)
    cell = [a for a in r.json()["assignments"] if a["personnel_id"] == p1 and a["work_date"] == "2026-06-02"]
    assert len(cell) == 1 and cell[0]["shift_id"] == s2
    # silme
    r = client.delete(f"{PREFIX}/{aid}", headers=auth_headers)
    assert r.status_code == 200
    r = client.get(f"{PREFIX}?start=2026-06-01&end=2026-06-07", headers=auth_headers)
    assert not [a for a in r.json()["assignments"] if a["id"] == aid]


def test_assign_404(client, auth_headers, two_shifts, two_people):
    s1, _ = two_shifts
    p1, _ = two_people
    r = client.post(PREFIX, json={"personnel_id": 999999, "shift_id": s1, "work_date": "2026-06-02"}, headers=auth_headers)
    assert r.status_code == 404
    r = client.post(PREFIX, json={"personnel_id": p1, "shift_id": 999999, "work_date": "2026-06-02"}, headers=auth_headers)
    assert r.status_code == 404


# ── Toplu işlemler ───────────────────────────────────────

def test_bulk_assign_and_clear(client, auth_headers, two_shifts, two_people):
    s1, _ = two_shifts
    p1, p2 = two_people
    r = client.post(f"{PREFIX}/bulk", json={"personnel_ids": [p1, p2], "shift_id": s1, "dates": ["2026-06-03", "2026-06-04"]}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["count"] == 4
    # temizle
    r = client.post(f"{PREFIX}/bulk", json={"personnel_ids": [p1, p2], "shift_id": None, "dates": ["2026-06-03", "2026-06-04"]}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["count"] == 4
    r = client.get(f"{PREFIX}?start=2026-06-01&end=2026-06-07", headers=auth_headers)
    assert not [a for a in r.json()["assignments"] if a["personnel_id"] in (p1, p2)]


def test_copy_week(client, auth_headers, two_shifts, two_people):
    s1, _ = two_shifts
    p1, _ = two_people
    client.post(PREFIX, json={"personnel_id": p1, "shift_id": s1, "work_date": "2026-06-02"}, headers=auth_headers)
    r = client.post(f"{PREFIX}/copy-week", json={"source_start": "2026-06-01", "target_start": "2026-06-08"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["count"] >= 1
    # 2026-06-02 + 7 gün = 2026-06-09
    r = client.get(f"{PREFIX}?start=2026-06-08&end=2026-06-14", headers=auth_headers)
    assert [a for a in r.json()["assignments"] if a["personnel_id"] == p1 and a["work_date"] == "2026-06-09"]


# ── Doğrulama ────────────────────────────────────────────

def test_range_validation(client, auth_headers):
    assert client.get(f"{PREFIX}?start=2026-06-07&end=2026-06-01", headers=auth_headers).status_code == 400
    assert client.get(f"{PREFIX}?start=2026-01-01&end=2026-12-31", headers=auth_headers).status_code == 400


def test_bulk_empty_validation(client, auth_headers, two_shifts):
    s1, _ = two_shifts
    r = client.post(f"{PREFIX}/bulk", json={"personnel_ids": [], "shift_id": s1, "dates": ["2026-06-03"]}, headers=auth_headers)
    assert r.status_code == 400
