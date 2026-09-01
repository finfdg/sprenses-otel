"""Acente grubu (sales.acente_mahsup) domain servis katmanı — CRUD + atama (HTTP'siz).

D1-2 deseni (2026-09-01): router (`sales/agency_groups.py`) ve onay executor
(`approval_executor` → `sales.acente_mahsup`, payload `_kind="agency_group"|"agency_assign"`)
AYNI fonksiyonları çağırır → tek kaynak, davranış sapması imkansız. HTTP doğrulama
(404/409/400), response şeması, `check_approval`, audit (`log_action`) ve WS broadcast
ROUTER'da kalır; service yalnız normalizasyon + mutasyon yapar. flush/commit ÇAĞIRMAZ.

Onay payload'ı JSON'dur (`json.dumps default=str`) → alanlar primitif (str/int/float/list);
tarih alanı yok, coercion gerekmez. `kickback_percent` Numeric(5,2) → float kabul edilir.

`payment_alignment` (friday | month_end | day_N | checkin) hem pydantic şemasında hem
burada `is_valid_payment_alignment` ile doğrulanır — executor yolu şemadan geçmediği için
service doğrulaması ZORUNLUDUR (bozuk değer projeksiyonu sessizce Cuma'ya düşürürdü).
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.agency_group import (
    DEFAULT_AGENCY_TERM_DAYS,
    PAYMENT_ALIGN_FRIDAY,
    AgencyGroup,
    is_valid_payment_alignment,
)


def normalize_name(name: Optional[str]) -> str:
    """Grup adı konvansiyonu: kırpılmış + BÜYÜK harf (rezervasyon acente adı eşleşmesi)."""
    return (name or "").strip().upper()


def normalize_members(members: Optional[List[str]]) -> List[str]:
    """Boş ve tekrar eden üyeleri temizle (sıra korunur)."""
    return list(dict.fromkeys(m.strip() for m in (members or []) if m and m.strip()))


def validate_payment_alignment(value: Optional[str]) -> str:
    """Boş → varsayılan (friday); geçersiz → ValueError (router 400 / executor hata)."""
    if value is None or value == "":
        return PAYMENT_ALIGN_FRIDAY
    if not is_valid_payment_alignment(value):
        raise ValueError(
            f"Geçersiz ödeme günü hizalaması: {value!r} "
            "(friday | month_end | checkin | day_1..day_31)"
        )
    return value


def find_name_conflict(db: Session, name: str, exclude_id: Optional[int] = None) -> Optional[AgencyGroup]:
    """Aynı ada sahip başka grup var mı (unique kısıtı öncesi okunaklı 409 için)."""
    q = db.query(AgencyGroup).filter(AgencyGroup.name == name)
    if exclude_id is not None:
        q = q.filter(AgencyGroup.id != exclude_id)
    return q.first()


def create_group(db: Session, data: dict) -> AgencyGroup:
    """Yeni acente grubu oluştur (flush/commit ÇAĞIRMAZ — çağıran yapar)."""
    name = normalize_name(data.get("name"))
    if not name:
        raise ValueError("Grup adı boş olamaz")
    if find_name_conflict(db, name):
        raise ValueError("Bu isimde bir grup zaten mevcut")
    group = AgencyGroup(
        name=name,
        members=normalize_members(data.get("members")),
        term_days=int(data.get("term_days") if data.get("term_days") is not None
                      else DEFAULT_AGENCY_TERM_DAYS),
        kickback_percent=float(data.get("kickback_percent") or 0),
        payment_alignment=validate_payment_alignment(data.get("payment_alignment")),
    )
    db.add(group)
    return group


def apply_group_update(db: Session, group: AgencyGroup, data: dict) -> None:
    """Verilen alanları gruba uygula (yalnız gönderilen/None-olmayan alanlar; `_` önekli
    onay meta anahtarları — `_kind` — yok sayılır)."""
    if data.get("name") is not None:
        new_name = normalize_name(data["name"])
        if not new_name:
            raise ValueError("Grup adı boş olamaz")
        if find_name_conflict(db, new_name, exclude_id=group.id):
            raise ValueError("Bu isimde başka bir grup var")
        group.name = new_name
    if data.get("members") is not None:
        group.members = normalize_members(data["members"])
    if data.get("term_days") is not None:
        group.term_days = int(data["term_days"])
    if data.get("kickback_percent") is not None:
        group.kickback_percent = float(data["kickback_percent"])
    if data.get("payment_alignment") is not None:
        group.payment_alignment = validate_payment_alignment(data["payment_alignment"])


def delete_group(db: Session, group: AgencyGroup) -> None:
    """Grubu sil (üyeler JSON kolonunda — bağlı satır yok, guard gerekmez)."""
    db.delete(group)


def assign_agency(db: Session, agency_name: str, target_group_id: Optional[int]) -> dict:
    """Acenteyi hedef gruba ata / tüm gruplardan çıkar (atomik; flush/commit çağıran yapar).

    Dönüş: {"changed": bool, "target_id", "target_name", "removed_from": [grup adları]}.
    Hedef grup yoksa ValueError (router bunu 404'e çevirmek için önceden kontrol eder;
    executor yolunda talep uygulanamaz → hata görünür).
    """
    agency = (agency_name or "").strip()
    if not agency:
        raise ValueError("Acente adı boş olamaz")

    target: Optional[AgencyGroup] = None
    if target_group_id is not None:
        target = db.query(AgencyGroup).filter(AgencyGroup.id == target_group_id).first()
        if not target:
            raise ValueError(f"Grup bulunamadı: {target_group_id}")

    all_groups = db.query(AgencyGroup).order_by(AgencyGroup.name).all()
    current_groups = [g for g in all_groups if agency in (g.members or [])]

    result = {
        "changed": False,
        "target_id": target.id if target else None,
        "target_name": target.name if target else None,
        "removed_from": [g.name for g in current_groups if not target or g.id != target.id],
    }
    # Zaten yalnız hedef gruptaysa no-op
    if target and len(current_groups) == 1 and current_groups[0].id == target.id:
        return result

    changed = False
    for g in current_groups:
        if target and g.id == target.id:
            continue  # hedef bu grupsa atla; aşağıda zaten eklenecek
        g.members = [m for m in (g.members or []) if m != agency]
        changed = True
    if target and agency not in (target.members or []):
        target.members = [*(target.members or []), agency]
        changed = True

    result["changed"] = changed
    return result
