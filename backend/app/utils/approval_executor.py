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
    from app.utils.entry_generator import _build_description, generate_entries, regenerate_entries
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
        # Dönem değiştiyse açıklamayı yeniden üret (router update_entry ile birebir) — aksi halde
        # nakit akımda (finance_event.description) bayat ay etiketi kalır.
        if "period_month" in payload or "period_year" in payload:
            entry.description = _build_description(
                entry.source_type, entry.definition.name, entry.definition.category,
                entry.period_month, entry.period_year,
            )
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
                if field in ("amount", "frequency", "payment_day", "start_month"):
                    need_regen = True
        if need_regen:
            regenerate_entries(db, defn, direction=direction)
        # Cari-bağlı düzenli ödeme → herhangi bir değişiklikten sonra cari gerçek faturayla senkronla
        if defn.vendor_id:
            from app.utils.recurring_vendor_sync import sync_recurring_from_vendors
            sync_recurring_from_vendors(db)

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

    # Modül kodu→id cache'ini tazele: create/update/delete code veya is_active'i değiştirebilir;
    # bayat cache pasif modüle hâlâ izin verir (bkz. _get_module_id is_active filtresi).
    from app.middleware.auth import invalidate_module_cache
    invalidate_module_cache()


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
    from app.models.bank_transaction import BankTransaction
    from app.models.check import Check
    from app.models.vendor_transaction import VendorTransaction
    from app.utils.finance_event_service import finance_event_svc

    if action_type == "update":
        check = db.query(Check).filter(Check.id == entity_id).first()
        if not check:
            raise ValueError(f"Çek bulunamadı: {entity_id}")
        # Router update_check_status payload'ı {"new_status": ...} taşır (model alanı "status").
        # Eski handler _apply_fields ile "new_status"'u arıyordu → hiç eşleşmiyordu (sessiz no-op).
        new_status = payload.get("new_status", payload.get("status"))
        if new_status:
            # İptal → cari + banka eşleşmesini kaldır (router ile birebir)
            if new_status == "cancelled":
                if check.match_number:
                    mvtx = db.query(VendorTransaction).filter(
                        VendorTransaction.match_number == check.match_number
                    ).first()
                    if mvtx:
                        mvtx.match_number = None
                        mvtx.payment_method = None
                    check.match_number = None
                    check.matched_vendor_id = None
                if check.bank_transaction_id:
                    btx = db.query(BankTransaction).filter(
                        BankTransaction.id == check.bank_transaction_id
                    ).first()
                    if btx:
                        btx.match_number = None
                    check.bank_transaction_id = None
            check.status = new_status
        else:
            _apply_fields(check, payload)  # durum dışı alanlar (savunmacı)
        # finance_events güncelle (router ile birebir)
        bank_tx = None
        if check.bank_transaction_id:
            bank_tx = db.query(BankTransaction).filter(
                BankTransaction.id == check.bank_transaction_id
            ).first()
        finance_event_svc.upsert_check(db, check, bank_tx)


def _handle_finance_cariler(db, action_type, entity_id, payload, actor_id):
    from app.models.vendor import Vendor

    if action_type == "update":
        vendor = db.query(Vendor).filter(Vendor.id == entity_id).first()
        if not vendor:
            raise ValueError(f"Cari bulunamadı: {entity_id}")
        _apply_fields(vendor, payload)
        # Router update_vendor_payment_days/status ile birebir: vade değişince işlem tarihlerini
        # yeniden hesapla + nakit akımı senkronla. Aksi halde onaylı vade/durum değişimi nakit akıma
        # yansımıyordu (bayat vade, yasaklı cari kayıt kalıntısı). sync içinde commit yok → güvenli.
        from app.models.vendor_transaction import VendorTransaction
        from app.utils.finance_event_service import finance_event_svc
        from app.utils.sync_vendor_fifo import sync_vendor_finance_events
        from app.utils.vendor_parser import calculate_payment_friday

        if "payment_days" in payload:
            invoice_txs = (
                db.query(VendorTransaction)
                .filter(
                    VendorTransaction.vendor_id == entity_id,
                    VendorTransaction.alacak > 0,
                    VendorTransaction.date.isnot(None),
                )
                .all()
            )
            for tx in invoice_txs:
                tx.payment_due_date = calculate_payment_friday(tx.date, vendor.payment_days)
                finance_event_svc.upsert_vendor_tx(db, tx, vendor, float(tx.alacak))
        db.flush()
        sync_vendor_finance_events(db)


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
                unit=fld.get("unit"),
                # options payload'da zaten JSON string (şema: Optional[str]) — tekrar dumps ETME
                # (eski handler çift-serileştiriyordu → select seçenekleri parse edilemiyordu).
                options=fld.get("options"),
                is_required=fld.get("is_required", False),
                is_resource=fld.get("is_resource", False),
                is_guest_count=fld.get("is_guest_count", False),
                is_meter=fld.get("is_meter", False),
                is_month_end_only=fld.get("is_month_end_only", False),
                sort_order=fld.get("sort_order", j),
            )
            db.add(field)


def _save_template_assignees(db, template_id, assignees_data):
    """Şablon atananları kaydet."""
    from app.models.quality_template_assignee import QualityTemplateAssignee

    for a in assignees_data:
        # assignment_type ZORUNLU (NOT NULL, default yok) — atlanırsa IntegrityError → onay 500.
        # role_id de taşınmalı (yoksa rol-bazlı atamada user_id+role_id ikisi de NULL → CHECK ihlali).
        assignee = QualityTemplateAssignee(
            template_id=template_id,
            assignment_type=a.get("assignment_type"),
            user_id=a.get("user_id"),
            role_id=a.get("role_id"),
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


def _handle_attendance(db, action_type, entity_id, payload, actor_id):
    """Onaylanan elle giriş/çıkış (hr.attendance) → AttendanceLog oluştur/güncelle/sil.

    punched_at payload'da ISO string olarak talep anında sabitlenir; burada parse edilir.
    create → entity_id=0 (yeni kayıt). update/delete → entity_id=düzenlenen log id.
    """
    from datetime import datetime as _dt

    import pytz

    from app.models.personnel import SOURCE_MANUAL, AttendanceLog
    from app.utils.audit import log_action

    tz = pytz.timezone("Europe/Istanbul")

    def _parse(raw):
        try:
            return _dt.fromisoformat(raw) if raw else None
        except (TypeError, ValueError):
            return None

    if action_type == "create":
        log = AttendanceLog(
            personnel_id=payload.get("personnel_id"),
            type=payload.get("type"),
            source=SOURCE_MANUAL,
            recorded_by=actor_id,
            note=(payload.get("note") or None),
        )
        when = _parse(payload.get("punched_at"))
        if when is not None:
            log.punched_at = when
        db.add(log)
        db.flush()
        log_action(db, actor_id, "manual_punch", "attendance", log.id, f"Onaylı elle {log.type}")

    elif action_type == "update":
        log = db.query(AttendanceLog).filter(AttendanceLog.id == entity_id).first()
        if not log:
            return
        old_type, old_when, old_note = log.type, log.punched_at, log.note
        if payload.get("type"):
            log.type = payload["type"]
        if "note" in payload:
            log.note = (payload.get("note") or "").strip() or None
        when = _parse(payload.get("punched_at"))
        if when is not None:
            log.punched_at = when
        log.edited_at = _dt.now(tz)
        # Eski→yeni farkı (audit detayı + tarihçe)
        def _tt(t):
            return "giriş" if t == "in" else "çıkış"
        ch = []
        if old_type != log.type:
            ch.append(f"hareket: {_tt(old_type)}→{_tt(log.type)}")
        ows, nws = old_when.astimezone(tz).strftime("%d.%m %H:%M"), log.punched_at.astimezone(tz).strftime("%d.%m %H:%M")
        if ows != nws:
            ch.append(f"zaman: {ows}→{nws}")
        if (old_note or "") != (log.note or ""):
            ch.append(f"not: '{old_note or '—'}'→'{log.note or '—'}'")
        detail = "; ".join(ch) if ch else "değişiklik yok"
        log_action(db, actor_id, "update", "attendance", log.id, detail)

    elif action_type == "delete":
        log = db.query(AttendanceLog).filter(AttendanceLog.id == entity_id).first()
        if log and not log.deleted_at:
            log_action(db, actor_id, "delete", "attendance", log.id, "Onaylı silme")
            log.deleted_at = _dt.now(tz)  # soft delete


def _handle_shifts(db, action_type, entity_id, payload, actor_id):
    """Onaylanan vardiya tanımı (hr.shifts) → ShiftDefinition oluştur/güncelle/sil.

    Zaman alanları payload'da ISO string ("HH:MM:SS") olarak gelir; time'a parse edilir.
    """
    from datetime import time as _time

    from app.models.shift import DEFAULT_COLOR, ShiftDefinition

    def _pt(v):
        if not v:
            return None
        try:
            parts = str(v).split(":")
            return _time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None

    if action_type == "create":
        is_active = payload.get("is_active")
        db.add(ShiftDefinition(
            name=(payload.get("name") or "").strip(),
            color=payload.get("color") or DEFAULT_COLOR,
            start_time=_pt(payload.get("start_time")),
            end_time=_pt(payload.get("end_time")),
            start_time2=_pt(payload.get("start_time2")),
            end_time2=_pt(payload.get("end_time2")),
            description=(payload.get("description") or None),
            is_active=True if is_active is None else is_active,
            sort_order=payload.get("sort_order") or 0,
        ))
    elif action_type == "update":
        s = db.query(ShiftDefinition).filter(ShiftDefinition.id == entity_id).first()
        if not s:
            return
        if "name" in payload:
            s.name = payload["name"]
        if "color" in payload:
            s.color = payload["color"]
        for tf in ("start_time", "end_time", "start_time2", "end_time2"):
            if tf in payload:
                setattr(s, tf, _pt(payload[tf]))
        if "description" in payload:
            s.description = payload.get("description") or None
        if "is_active" in payload:
            s.is_active = payload["is_active"]
        if "sort_order" in payload:
            s.sort_order = payload["sort_order"]
    elif action_type == "delete":
        s = db.query(ShiftDefinition).filter(ShiftDefinition.id == entity_id).first()
        if s:
            db.delete(s)


def _handle_shift_schedule(db, action_type, entity_id, payload, actor_id):
    """Onaylanan vardiya çizelgesi (hr.shift_schedule) → ShiftAssignment upsert/sil.

    create → entity_id=0, upsert (personnel_id + work_date benzersiz).
    delete → entity_id=atama id.
    work_date payload'da ISO string ("YYYY-MM-DD") gelir; date'e parse edilir.
    """
    from datetime import date as _date
    from datetime import datetime as _dt

    import pytz

    from app.models.shift_assignment import ShiftAssignment
    from app.utils.audit import log_action

    tz = pytz.timezone("Europe/Istanbul")

    def _pd(v):
        try:
            return _date.fromisoformat(str(v)) if v else None
        except (TypeError, ValueError):
            return None

    if action_type == "create":
        wd = _pd(payload.get("work_date"))
        pid = payload.get("personnel_id")
        sid = payload.get("shift_id")
        if not (wd and pid and sid):
            return
        note = payload.get("note")
        a = (
            db.query(ShiftAssignment)
            .filter(ShiftAssignment.personnel_id == pid, ShiftAssignment.work_date == wd)
            .first()
        )
        if a:
            a.shift_id = sid
            if note is not None:
                a.note = note or None
            a.updated_at = _dt.now(tz)
        else:
            a = ShiftAssignment(
                personnel_id=pid, shift_id=sid, work_date=wd,
                note=(note or None), created_by=actor_id,
            )
            db.add(a)
        db.flush()
        log_action(db, actor_id, "create", "shift_assignment", a.id, "Onaylı rota ataması")

    elif action_type == "delete":
        a = db.query(ShiftAssignment).filter(ShiftAssignment.id == entity_id).first()
        if a:
            log_action(db, actor_id, "delete", "shift_assignment", a.id, "Onaylı rota silme")
            db.delete(a)


def _handle_sales_room_types(db, action_type, entity_id, payload, actor_id):
    """Oda tipi (sales.room_types) onayı — router CRUD'unu birebir yansıtır.

    Delete'te router'daki rezervasyon koruması da uygulanır (rezervasyon varsa silinmez —
    `Reservation.room_type` koda string-bağlı, FK yok; orphan referansı engeller).
    """
    from app.models.room_type import RoomType

    if action_type == "create":
        rt = RoomType(
            code=payload.get("code", ""),
            name=payload.get("name", ""),
            total_rooms=payload.get("total_rooms", 0),
            max_occupancy=payload.get("max_occupancy", 2),
            sort_order=payload.get("sort_order", 0),
            is_active=payload.get("is_active", True),
            description=payload.get("description"),
        )
        db.add(rt)

    elif action_type == "update":
        rt = db.query(RoomType).filter(RoomType.id == entity_id).first()
        if not rt:
            raise ValueError(f"Oda tipi bulunamadı: {entity_id}")
        _apply_fields(rt, payload)

    elif action_type == "delete":
        from sqlalchemy import func
        from app.models.reservation import Reservation
        rt = db.query(RoomType).filter(RoomType.id == entity_id).first()
        if not rt:
            return
        rez_count = (
            db.query(func.count(Reservation.id))
            .filter(Reservation.room_type == rt.code)
            .scalar()
        )
        if rez_count and rez_count > 0:
            raise ValueError(
                f"Bu oda tipine ait {rez_count} rezervasyon olduğu için silinemez (pasif yapın)."
            )
        db.delete(rt)


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
    # İK — Devam Takip (elle giriş/çıkış)
    "hr.attendance": _handle_attendance,
    # İK — Vardiya tanımları
    "hr.shifts": _handle_shifts,
    # İK — Vardiya çizelgesi (rota)
    "hr.shift_schedule": _handle_shift_schedule,
    # Satış
    "sales.room_types": _handle_sales_room_types,
}

# Scheduled modüller (8 adet)
for _code, (_src, _dir) in _SCHEDULED_SOURCE_MAP.items():
    _HANDLERS[_code] = _make_scheduled_handler(_src, _dir)
