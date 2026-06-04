"""Onaylanan taleplerin payload'larını uygulayan executor.

Onay talebi onaylandığında bu modül çağrılır. Saklanan payload_json
verisi parse edilir ve ilgili modülün iş mantığı çalıştırılır.

Her modül için ayrı handler fonksiyonu tanımlıdır. Handler'lar kayıt
oluşturma/güncelleme/silme işlemlerini ve gerekli yan etkileri
(finance_events, giriş üretimi vb.) gerçekleştirir.
"""

import json
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.constants import SourceType
from app.models.approval import ApprovalRequest

logger = logging.getLogger(__name__)


# ── Ana fonksiyon ─────────────────────────────────────────────

def execute_approved_payload(db: Session, request: ApprovalRequest) -> bool:
    """Onaylanan talebin payload_json'ını çalıştır.

    Returns:
        True — başarılı veya payload yok
        False — hata oluştu
    """
    if not request.payload_json:
        logger.info("Onay talebi %d: payload yok, atlanıyor", request.id)
        return True

    try:
        payload = json.loads(request.payload_json)
    except (json.JSONDecodeError, TypeError):
        logger.error("Onay talebi %d: payload JSON parse hatası", request.id)
        return False

    module_code = request.module_code or request.entity_type
    action_type = request.action_type
    entity_id = request.entity_id
    actor_id = request.requested_by

    handler = _HANDLERS.get(module_code)
    if not handler:
        logger.error("Onay talebi %d: '%s' modülü için handler bulunamadı", request.id, module_code)
        return False

    try:
        handler(db, action_type, entity_id, payload, actor_id)
        db.flush()
        logger.info("Onay talebi %d: payload başarıyla uygulandı [%s/%s]",
                     request.id, module_code, action_type)
        return True
    except Exception as e:
        logger.error("Onay talebi %d: executor hatası [%s]: %s",
                     request.id, module_code, e, exc_info=True)
        return False


# ── Temizlik (iptal/ret) ──────────────────────────────────────

def cleanup_rejected_or_cancelled(db: Session, request: ApprovalRequest) -> bool:
    """Onay reddedildiğinde veya iptal edildiğinde pasif oluşturulan kaydı sil.

    Sadece "create" action için geçerli — update/delete zaten mevcut kayda dokunmaz.
    Returns True eğer temizlik yapıldıysa.
    """
    if request.action_type != "create" or not request.entity_id:
        return False

    module_code = request.module_code or request.entity_type
    if module_code not in _SCHEDULED_SOURCE_MAP:
        return False

    source_type, _ = _SCHEDULED_SOURCE_MAP[module_code]

    from app.models.scheduled import ScheduledDefinition
    defn = db.query(ScheduledDefinition).filter(
        ScheduledDefinition.id == request.entity_id,
        ScheduledDefinition.source_type == source_type,
        ScheduledDefinition.is_active == False,  # noqa: E712
    ).first()
    if defn:
        db.delete(defn)
        logger.info("Pasif tanım silindi (onay %d iptal/ret): defn_id=%d",
                     request.id, defn.id)
        return True
    return False


# ── Yardımcı ──────────────────────────────────────────────────

def _apply_fields(obj, payload: dict, exclude: Optional[set] = None):
    """Payload'daki alanları objeye uygula."""
    skip = exclude or set()
    for key, val in payload.items():
        if key in skip:
            continue
        if hasattr(obj, key):
            setattr(obj, key, val)


# ── Scheduled modüller (8 modül) ──────────────────────────────

_SCHEDULED_SOURCE_MAP = {
    "accounting.taxes": (SourceType.TAX, -1),
    "accounting.recurring": (SourceType.RECURRING, -1),
    "accounting.rent_income": (SourceType.RENT_INCOME, 1),
    "accounting.rent_expense": (SourceType.RENT_EXPENSE, -1),
    "accounting.dividend": (SourceType.DIVIDEND, -1),
    "hr.salary": (SourceType.SALARY, -1),
    "hr.withholding": (SourceType.WITHHOLDING, -1),
    "hr.sgk": (SourceType.SGK, -1),
}


def _handle_scheduled(db, action_type, entity_id, payload, actor_id, source_type, direction):
    """Planlı gider/gelir modülleri handler'ı."""
    from app.models.scheduled import ScheduledDefinition, ScheduledEntry
    from app.utils.entry_generator import generate_entries, regenerate_entries
    from app.utils.finance_event_service import finance_event_svc

    target = payload.pop("_target", "definition")

    if target == "entry":
        # Giriş güncelleme
        entry = db.query(ScheduledEntry).filter(ScheduledEntry.id == entity_id).first()
        if not entry:
            raise ValueError(f"Giriş bulunamadı: {entity_id}")
        _apply_fields(entry, payload, exclude={"_target"})
        if payload.get("is_paid") and not entry.paid_date:
            entry.paid_date = date.today()
        finance_event_svc.upsert_scheduled_entry(db, entry, direction=direction)
        return

    if action_type == "create":
        # Pasif oluşturulmuş kaydı aktifleştir (entity_id > 0 ise)
        defn = None
        if entity_id > 0:
            defn = db.query(ScheduledDefinition).filter(
                ScheduledDefinition.id == entity_id,
                ScheduledDefinition.source_type == source_type,
                ScheduledDefinition.is_active == False,  # noqa: E712
            ).first()
        if defn:
            # Mevcut pasif kaydı aktifleştir ve payload ile güncelle
            defn.is_active = True
            _apply_fields(defn, payload, exclude={"_target"})
        else:
            # Pasif kayıt yoksa yeni oluştur (geriye uyumluluk)
            defn = ScheduledDefinition(
                source_type=source_type,
                name=payload.get("name", ""),
                category=payload.get("category"),
                amount=payload.get("amount", 0),
                currency=payload.get("currency", "TRY"),
                frequency=payload.get("frequency", "monthly"),
                payment_day=payload.get("payment_day", 1),
                start_month=payload.get("start_month", 1),
                year=payload.get("year") or date.today().year,
                notes=payload.get("notes"),
                is_active=True,
                created_by=actor_id,
            )
            db.add(defn)
        db.flush()
        generate_entries(db, defn, direction=direction)

    elif action_type == "update":
        defn = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.id == entity_id,
            ScheduledDefinition.source_type == source_type,
        ).first()
        if not defn:
            raise ValueError(f"Tanım bulunamadı: {entity_id}")
        need_regen = False
        for field, value in payload.items():
            if field.startswith("_"):
                continue
            if hasattr(defn, field):
                setattr(defn, field, value)
                if field in ("amount", "frequency", "payment_day"):
                    need_regen = True
        if need_regen:
            regenerate_entries(db, defn, direction=direction)

    elif action_type == "delete":
        defn = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.id == entity_id,
            ScheduledDefinition.source_type == source_type,
        ).first()
        if not defn:
            raise ValueError(f"Tanım bulunamadı: {entity_id}")
        entries = defn.entries.all()
        for entry in entries:
            finance_event_svc.invalidate(db, entry.source_type, entry.id)
        db.delete(defn)


def _make_scheduled_handler(source_type, direction):
    """Scheduled modül için closure handler oluştur."""
    def handler(db, action_type, entity_id, payload, actor_id):
        _handle_scheduled(db, action_type, entity_id, payload, actor_id, source_type, direction)
    return handler


# ── Sistem modülleri ──────────────────────────────────────────

def _handle_system_users(db, action_type, entity_id, payload, actor_id):
    from app.models.user import User
    from app.utils.security import hash_password

    if action_type == "create":
        password = payload.pop("password", None)
        user = User(
            username=payload.get("username", ""),
            email=payload.get("email", ""),
            first_name=payload.get("first_name", ""),
            last_name=payload.get("last_name", ""),
            role_id=payload.get("role_id"),
            is_active=payload.get("is_active", True),
            hashed_password=hash_password(password) if password else "",
        )
        db.add(user)

    elif action_type == "update":
        user = db.query(User).filter(User.id == entity_id).first()
        if not user:
            raise ValueError(f"Kullanıcı bulunamadı: {entity_id}")
        for key, val in payload.items():
            if key == "password" and val:
                user.hashed_password = hash_password(val)
            elif key == "email" and val is None:
                user.email = ""
            elif hasattr(user, key):
                setattr(user, key, val)

    elif action_type == "delete":
        user = db.query(User).filter(User.id == entity_id).first()
        if user:
            db.delete(user)


def _handle_system_roles(db, action_type, entity_id, payload, actor_id):
    from app.models.role import Role
    from app.models.role_module_permission import RoleModulePermission

    if action_type == "create":
        permissions = payload.pop("permissions", [])
        role = Role(
            name=payload.get("name", ""),
            description=payload.get("description"),
            is_active=payload.get("is_active", True),
        )
        db.add(role)
        db.flush()
        for perm in permissions:
            db.add(RoleModulePermission(
                role_id=role.id,
                module_id=perm.get("module_id"),
                can_view=perm.get("can_view", False),
                can_use=perm.get("can_use", False),
            ))

    elif action_type == "update":
        role = db.query(Role).filter(Role.id == entity_id).first()
        if not role:
            raise ValueError(f"Rol bulunamadı: {entity_id}")
        permissions = payload.pop("permissions", None)
        _apply_fields(role, payload)
        if permissions is not None:
            db.query(RoleModulePermission).filter(
                RoleModulePermission.role_id == entity_id
            ).delete()
            db.flush()
            for perm in permissions:
                db.add(RoleModulePermission(
                    role_id=entity_id,
                    module_id=perm.get("module_id"),
                    can_view=perm.get("can_view", False),
                    can_use=perm.get("can_use", False),
                ))

    elif action_type == "delete":
        role = db.query(Role).filter(Role.id == entity_id).first()
        if role:
            role.is_active = False


def _handle_system_modules(db, action_type, entity_id, payload, actor_id):
    from app.models.module import Module

    if action_type == "create":
        module = Module(
            name=payload.get("name", ""),
            code=payload.get("code", ""),
            description=payload.get("description"),
            parent_id=payload.get("parent_id"),
            sort_order=payload.get("sort_order", 0),
            icon=payload.get("icon"),
            is_active=payload.get("is_active", True),
        )
        db.add(module)

    elif action_type == "update":
        module = db.query(Module).filter(Module.id == entity_id).first()
        if not module:
            raise ValueError(f"Modül bulunamadı: {entity_id}")
        _apply_fields(module, payload)

    elif action_type == "delete":
        module = db.query(Module).filter(Module.id == entity_id).first()
        if module:
            module.is_active = False


# ── Finans modülleri ──────────────────────────────────────────

def _handle_finance_banks(db, action_type, entity_id, payload, actor_id):
    from app.models.bank_account import BankAccount

    if action_type == "create":
        acc = BankAccount(
            bank_name=payload.get("bank_name", ""),
            branch_name=payload.get("branch_name"),
            account_no=payload.get("account_no"),
            iban=payload.get("iban"),
            currency=payload.get("currency", "TRY"),
            holder_name=payload.get("holder_name"),
            blocked_amount=payload.get("blocked_amount", 0),
            created_by=actor_id,
        )
        db.add(acc)

    elif action_type == "update":
        acc = db.query(BankAccount).filter(BankAccount.id == entity_id).first()
        if not acc:
            raise ValueError(f"Banka hesabı bulunamadı: {entity_id}")
        _apply_fields(acc, payload)

    elif action_type == "delete":
        acc = db.query(BankAccount).filter(BankAccount.id == entity_id).first()
        if acc:
            db.delete(acc)


def _handle_finance_krediler(db, action_type, entity_id, payload, actor_id):
    from app.models.credit_product import CreditPayment, CreditProduct
    from app.utils.finance_event_service import finance_event_svc

    target = payload.pop("_target", "product")

    if target == "payment":
        # Ödeme güncelleme/silme
        if action_type == "update":
            payment = db.query(CreditPayment).filter(CreditPayment.id == entity_id).first()
            if not payment:
                raise ValueError(f"Ödeme bulunamadı: {entity_id}")
            old_is_paid = payment.is_paid
            _apply_fields(payment, payload, exclude={"_target"})
            db.flush()
            product = db.query(CreditProduct).filter(CreditProduct.id == payment.product_id).first()
            if product:
                finance_event_svc.upsert_credit_payment(db, payment, product)
                # remaining_amount güncelle
                if old_is_paid != payment.is_paid and payment.principal:
                    if payment.is_paid:
                        product.remaining_amount = float(product.remaining_amount or 0) - float(payment.principal or 0)
                    else:
                        product.remaining_amount = float(product.remaining_amount or 0) + float(payment.principal or 0)
        elif action_type == "delete":
            payment = db.query(CreditPayment).filter(CreditPayment.id == entity_id).first()
            if payment:
                finance_event_svc.invalidate(db, "credit", payment.id)
                db.delete(payment)
        return

    # Ürün CRUD
    if action_type == "create":
        details = payload.get("details")
        product = CreditProduct(
            type=payload.get("type", ""),
            name=payload.get("name", ""),
            bank_name=payload.get("bank_name"),
            company=payload.get("company"),
            currency=payload.get("currency", "TRY"),
            total_amount=payload.get("total_amount", 0),
            remaining_amount=payload.get("remaining_amount", 0),
            interest_rate=payload.get("interest_rate"),
            bsmv_rate=payload.get("bsmv_rate"),
            commission_rate=payload.get("commission_rate"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            details=json.dumps(details, ensure_ascii=False) if details else None,
            notes=payload.get("notes"),
            created_by=actor_id,
        )
        db.add(product)

    elif action_type == "update":
        product = db.query(CreditProduct).filter(CreditProduct.id == entity_id).first()
        if not product:
            raise ValueError(f"Kredi ürünü bulunamadı: {entity_id}")
        details = payload.pop("details", None)
        _apply_fields(product, payload, exclude={"_target"})
        if details is not None:
            product.details = json.dumps(details, ensure_ascii=False)

    elif action_type == "delete":
        product = db.query(CreditProduct).filter(CreditProduct.id == entity_id).first()
        if product:
            # Ödemelerin finance_event'lerini temizle
            payments = db.query(CreditPayment).filter(CreditPayment.product_id == entity_id).all()
            for p in payments:
                finance_event_svc.invalidate(db, "credit", p.id)
            db.delete(product)


def _handle_finance_avanslar(db, action_type, entity_id, payload, actor_id):
    from app.models.advance import Advance
    from app.utils.finance_event_service import finance_event_svc

    if action_type == "create":
        adv = Advance(
            agency_name=payload.get("agency_name", ""),
            amount=payload.get("amount", 0),
            currency=payload.get("currency", "TRY"),
            advance_date=payload.get("advance_date"),
            notes=payload.get("notes"),
            status="pending",
            created_by=actor_id,
        )
        db.add(adv)
        db.flush()
        finance_event_svc.upsert_advance(db, adv)

    elif action_type == "update":
        adv = db.query(Advance).filter(Advance.id == entity_id).first()
        if not adv:
            raise ValueError(f"Avans bulunamadı: {entity_id}")
        _apply_fields(adv, payload)
        db.flush()
        finance_event_svc.upsert_advance(db, adv)

    elif action_type == "delete":
        adv = db.query(Advance).filter(Advance.id == entity_id).first()
        if adv:
            finance_event_svc.invalidate(db, "advance", adv.id)
            db.delete(adv)


def _handle_finance_departmanlar(db, action_type, entity_id, payload, actor_id):
    from app.models.department import Department

    if action_type == "create":
        dept = Department(
            name=payload.get("name", ""),
            code=payload.get("code", ""),
            manager_id=payload.get("manager_id"),
            is_active=payload.get("is_active", True),
            sort_order=payload.get("sort_order", 0),
        )
        db.add(dept)

    elif action_type == "update":
        dept = db.query(Department).filter(Department.id == entity_id).first()
        if not dept:
            raise ValueError(f"Departman bulunamadı: {entity_id}")
        _apply_fields(dept, payload)

    elif action_type == "delete":
        dept = db.query(Department).filter(Department.id == entity_id).first()
        if dept:
            dept.is_active = False


def _handle_finance_butce(db, action_type, entity_id, payload, actor_id):
    from app.models.budget import Budget, BudgetCategory

    target = payload.pop("_target", "budget")

    if target == "department":
        return _handle_finance_departmanlar(db, action_type, entity_id, payload, actor_id)

    if target == "category":
        if action_type == "create":
            cat = BudgetCategory(
                name=payload.get("name", ""),
                type=payload.get("type", "expense"),
                sort_order=payload.get("sort_order", 0),
            )
            db.add(cat)
        elif action_type == "update":
            cat = db.query(BudgetCategory).filter(BudgetCategory.id == entity_id).first()
            if cat:
                _apply_fields(cat, payload, exclude={"_target"})
        elif action_type == "delete":
            cat = db.query(BudgetCategory).filter(BudgetCategory.id == entity_id).first()
            if cat:
                db.delete(cat)
        return

    # Budget CRUD
    if action_type in ("create", "update"):
        # Upsert mantığı
        existing = None
        if action_type == "update":
            existing = db.query(Budget).filter(Budget.id == entity_id).first()
        if existing:
            _apply_fields(existing, payload, exclude={"_target"})
        else:
            budget = Budget(
                category_id=payload.get("category_id"),
                department_id=payload.get("department_id"),
                year=payload.get("year"),
                month=payload.get("month"),
                planned_amount=payload.get("planned_amount", payload.get("amount", 0)),
                currency=payload.get("currency", "TRY"),
                notes=payload.get("notes"),
            )
            db.add(budget)

    elif action_type == "delete":
        budget = db.query(Budget).filter(Budget.id == entity_id).first()
        if budget:
            db.delete(budget)


def _handle_finance_checks(db, action_type, entity_id, payload, actor_id):
    from app.models.check import Check

    if action_type == "update":
        check = db.query(Check).filter(Check.id == entity_id).first()
        if not check:
            raise ValueError(f"Çek bulunamadı: {entity_id}")
        _apply_fields(check, payload)


def _handle_finance_cariler(db, action_type, entity_id, payload, actor_id):
    from app.models.vendor import Vendor

    if action_type == "update":
        vendor = db.query(Vendor).filter(Vendor.id == entity_id).first()
        if not vendor:
            raise ValueError(f"Cari bulunamadı: {entity_id}")
        _apply_fields(vendor, payload)


# ── Kalite modülleri ──────────────────────────────────────────

def _handle_quality_templates(db, action_type, entity_id, payload, actor_id):
    from app.models.quality_template import QualityTemplate
    from app.models.quality_template_assignee import QualityTemplateAssignee
    from app.models.quality_template_section import QualityTemplateSection

    if action_type == "create":
        sections_data = payload.pop("sections", [])
        assignees_data = payload.pop("assignees", [])
        tpl = QualityTemplate(
            name=payload.get("name", ""),
            description=payload.get("description"),
            frequency=payload.get("frequency", "daily"),
            footer_text=payload.get("footer_text"),
            increase_threshold=payload.get("increase_threshold", 10.0),
            decrease_threshold=payload.get("decrease_threshold", 10.0),
            is_active=payload.get("is_active", True),
            created_by=actor_id,
        )
        db.add(tpl)
        db.flush()
        _save_template_sections(db, tpl.id, sections_data)
        _save_template_assignees(db, tpl.id, assignees_data)

    elif action_type == "update":
        tpl = db.query(QualityTemplate).filter(QualityTemplate.id == entity_id).first()
        if not tpl:
            raise ValueError(f"Şablon bulunamadı: {entity_id}")
        sections_data = payload.pop("sections", None)
        assignees_data = payload.pop("assignees", None)
        _apply_fields(tpl, payload)
        if sections_data is not None:
            db.query(QualityTemplateSection).filter(
                QualityTemplateSection.template_id == entity_id
            ).delete()
            db.flush()
            _save_template_sections(db, entity_id, sections_data)
        if assignees_data is not None:
            db.query(QualityTemplateAssignee).filter(
                QualityTemplateAssignee.template_id == entity_id
            ).delete()
            db.flush()
            _save_template_assignees(db, entity_id, assignees_data)

    elif action_type == "delete":
        tpl = db.query(QualityTemplate).filter(QualityTemplate.id == entity_id).first()
        if tpl:
            db.delete(tpl)


def _save_template_sections(db, template_id, sections_data):
    """Şablon bölümlerini ve alanlarını kaydet."""
    from app.models.quality_template_field import QualityTemplateField
    from app.models.quality_template_section import QualityTemplateSection

    for i, sec in enumerate(sections_data):
        section = QualityTemplateSection(
            template_id=template_id,
            name=sec.get("name", sec.get("title", "")),
            sort_order=sec.get("sort_order", i),
        )
        db.add(section)
        db.flush()
        for j, fld in enumerate(sec.get("fields", [])):
            field = QualityTemplateField(
                section_id=section.id,
                label=fld.get("label", ""),
                field_type=fld.get("field_type", "text"),
                options=json.dumps(fld.get("options")) if fld.get("options") else None,
                is_required=fld.get("is_required", False),
                sort_order=fld.get("sort_order", j),
            )
            db.add(field)


def _save_template_assignees(db, template_id, assignees_data):
    """Şablon atananları kaydet."""
    from app.models.quality_template_assignee import QualityTemplateAssignee

    for a in assignees_data:
        assignee = QualityTemplateAssignee(
            template_id=template_id,
            user_id=a.get("user_id"),
        )
        db.add(assignee)


def _handle_quality_forms(db, action_type, entity_id, payload, actor_id):
    from app.models.quality_form import QualityForm

    if action_type == "create":
        form = QualityForm(
            template_id=payload.get("template_id"),
            period_date=payload.get("period_date"),
            notes=payload.get("notes"),
            status="draft",
        )
        db.add(form)

    elif action_type == "delete":
        form = db.query(QualityForm).filter(QualityForm.id == entity_id).first()
        if form:
            db.delete(form)


# ── Handler kayıt tablosu ────────────────────────────────────

_HANDLERS = {
    # Sistem
    "system.users": _handle_system_users,
    "system.roles": _handle_system_roles,
    "system.modules": _handle_system_modules,
    # Finans
    "finance.banks": _handle_finance_banks,
    "finance.krediler": _handle_finance_krediler,
    "finance.avanslar": _handle_finance_avanslar,
    "finance.departmanlar": _handle_finance_departmanlar,
    "finance.butce": _handle_finance_butce,
    "finance.checks": _handle_finance_checks,
    "finance.cariler": _handle_finance_cariler,
    # Kalite
    "quality.templates": _handle_quality_templates,
    "quality.forms": _handle_quality_forms,
}

# Scheduled modüller (8 adet)
for _code, (_src, _dir) in _SCHEDULED_SOURCE_MAP.items():
    _HANDLERS[_code] = _make_scheduled_handler(_src, _dir)
