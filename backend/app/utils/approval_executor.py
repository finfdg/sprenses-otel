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


def _make_crud_handler(load, create_fn, update_fn, delete_fn, not_found_msg,
                       create_takes_actor=True):
    """Standart create/update/delete onay handler'ı üretir (uniform CRUD modülleri).

    Yalnız basit-CRUD modülleri için (banks/avanslar/departmanlar/room_types) — özel
    mantıklı handler'lar (krediler `_target`, butce upsert, checks iptal kademesi,
    quality, scheduled) açık yazılır. `create_takes_actor`, `create_fn`'in `actor_id`
    alıp almadığını AÇIKÇA kodlar (departmanlar/room_types almaz; banks/avanslar alır) —
    bu imza farkı eski drift bug'larının (D2-4) kaynağıydı, gizlenmez. `load(db, id)`
    güncelleme/silmede varlığı çeker (lazy model import'u burada kalır).
    """
    def handler(db, action_type, entity_id, payload, actor_id):
        if action_type == "create":
            if create_takes_actor:
                create_fn(db, payload, actor_id)
            else:
                create_fn(db, payload)
        elif action_type == "update":
            obj = load(db, entity_id)
            if not obj:
                raise ValueError(not_found_msg.format(id=entity_id))
            update_fn(db, obj, payload)
        elif action_type == "delete":
            obj = load(db, entity_id)
            if obj:
                delete_fn(db, obj)
    return handler


# ── Scheduled modüller (7 modül) ──────────────────────────────
# NOT: accounting.dividend fabrika DIŞIdır (bespoke — _handle_accounting_dividend).

_SCHEDULED_SOURCE_MAP = {
    "accounting.taxes": (SourceType.TAX, -1),
    "accounting.recurring": (SourceType.RECURRING, -1),
    "accounting.rent_income": (SourceType.RENT_INCOME, 1),
    "accounting.rent_expense": (SourceType.RENT_EXPENSE, -1),
    "hr.salary": (SourceType.SALARY, -1),
    "hr.withholding": (SourceType.WITHHOLDING, -1),
    "hr.sgk": (SourceType.SGK, -1),
}


def _handle_scheduled(db, action_type, entity_id, payload, actor_id, source_type, direction):
    """Planlı gider/gelir modülleri handler'ı — router (create_scheduled_router) ile ORTAK tek
    kaynak: app/services/scheduled_service (girişleri üret + cari sync + FE + açıklama)."""
    from app.models.scheduled import ScheduledDefinition, ScheduledEntry
    from app.services import scheduled_service

    target = payload.pop("_target", "definition")

    if target == "entry":
        entry = db.query(ScheduledEntry).filter(ScheduledEntry.id == entity_id).first()
        if not entry:
            raise ValueError(f"Giriş bulunamadı: {entity_id}")
        scheduled_service.apply_entry_update(db, entry, payload, direction)
        return

    if action_type == "create":
        # Pasif oluşturulmuş kaydı aktifleştir (entity_id > 0) veya yeni oluştur
        defn = None
        if entity_id > 0:
            defn = db.query(ScheduledDefinition).filter(
                ScheduledDefinition.id == entity_id,
                ScheduledDefinition.source_type == source_type,
                ScheduledDefinition.is_active == False,  # noqa: E712
            ).first()
        if defn:
            defn.is_active = True
            _apply_fields(defn, payload, exclude={"_target"})
        else:
            # Geriye uyum fallback — vendor_id dahil (eskiden atlanıyordu → cari sync tetiklenmiyordu)
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
                vendor_id=payload.get("vendor_id"),
                is_active=True,
                created_by=actor_id,
            )
            db.add(defn)
        db.flush()
        scheduled_service.post_create(db, defn, direction)

    elif action_type == "update":
        defn = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.id == entity_id,
            ScheduledDefinition.source_type == source_type,
        ).first()
        if not defn:
            raise ValueError(f"Tanım bulunamadı: {entity_id}")
        scheduled_service.apply_definition_update(db, defn, payload, direction)

    elif action_type == "delete":
        defn = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.id == entity_id,
            ScheduledDefinition.source_type == source_type,
        ).first()
        if not defn:
            raise ValueError(f"Tanım bulunamadı: {entity_id}")
        scheduled_service.delete_definition(db, defn)


def _make_scheduled_handler(source_type, direction):
    """Scheduled modül için closure handler oluştur."""
    def handler(db, action_type, entity_id, payload, actor_id):
        _handle_scheduled(db, action_type, entity_id, payload, actor_id, source_type, direction)
    return handler


# ── Sistem modülleri ──────────────────────────────────────────

def _handle_system_users(db, action_type, entity_id, payload, actor_id):
    # Router (system_users.py) ile ORTAK tek kaynak: app/services/system_service.
    # Devre-dışı→oturum kapatma artık executor yolunda da uygulanır (eskiden eksikti).
    from app.models.user import User
    from app.services import system_service

    if action_type == "create":
        system_service.create_user(db, payload)
    elif action_type == "update":
        user = db.query(User).filter(User.id == entity_id).first()
        if not user:
            raise ValueError(f"Kullanıcı bulunamadı: {entity_id}")
        system_service.apply_user_update(db, user, payload)
    elif action_type == "delete":
        user = db.query(User).filter(User.id == entity_id).first()
        if user:
            system_service.delete_user(db, user)


def _handle_system_roles(db, action_type, entity_id, payload, actor_id):
    # Router (system_roles.py) ile ORTAK tek kaynak: app/services/system_service.
    # İzin değişince cache invalidate (eskiden eksikti); delete HARD + user-guard (eskiden SOFT'tu).
    from app.models.role import Role
    from app.services import system_service

    if action_type == "create":
        system_service.create_role(db, payload)
    elif action_type == "update":
        role = db.query(Role).filter(Role.id == entity_id).first()
        if not role:
            raise ValueError(f"Rol bulunamadı: {entity_id}")
        system_service.apply_role_update(db, role, payload)
    elif action_type == "delete":
        role = db.query(Role).filter(Role.id == entity_id).first()
        if role:
            system_service.delete_role(db, role)


def _handle_system_modules(db, action_type, entity_id, payload, actor_id):
    # Router (system_modules.py) ile ORTAK tek kaynak: app/services/system_service.
    # delete HARD + alt-modül guard (eskiden SOFT'tu); cache invalidate service içinde.
    from app.models.module import Module
    from app.services import system_service

    if action_type == "create":
        system_service.create_module(db, payload)
    elif action_type == "update":
        module = db.query(Module).filter(Module.id == entity_id).first()
        if not module:
            raise ValueError(f"Modül bulunamadı: {entity_id}")
        system_service.apply_module_update(db, module, payload)
    elif action_type == "delete":
        module = db.query(Module).filter(Module.id == entity_id).first()
        if module:
            system_service.delete_module(db, module)


# ── Finans modülleri ──────────────────────────────────────────

def _handle_finance_krediler(db, action_type, entity_id, payload, actor_id):
    # Router endpoint'iyle BİREBİR aynı mantık (tek kaynak: app/services/credit_service).
    # Böylece onaylanan create/update'te de BCH/KMH ödeme planı + finance_events üretilir,
    # remaining_amount doğru ayarlanır ve doğru kolon (credit_product_id) kullanılır
    # (eski elle-yazım `payment.product_id` ile AttributeError veriyor + planı atlıyordu — D2-4).
    from app.models.credit_product import CreditPayment, CreditProduct
    from app.services import credit_service

    target = payload.pop("_target", "product")

    if target == "payment":
        payment = db.query(CreditPayment).filter(CreditPayment.id == entity_id).first()
        if action_type == "update":
            if not payment:
                raise ValueError(f"Ödeme bulunamadı: {entity_id}")
            credit_service.apply_payment_update(db, payment, payload)
        elif action_type == "delete":
            if payment:
                credit_service.delete_payment(db, payment)
        return

    # Ürün CRUD
    if action_type == "create":
        credit_service.create_product(db, payload, actor_id)
    elif action_type == "update":
        product = db.query(CreditProduct).filter(CreditProduct.id == entity_id).first()
        if not product:
            raise ValueError(f"Kredi ürünü bulunamadı: {entity_id}")
        # Router close/reopen özel `action` payload'ı gönderir (alan güncellemesi DEĞİL) →
        # ortak service'in close_product/reopen_product'ını çağır (status + FE yan etkileri).
        action = payload.get("action")
        if action == "close":
            credit_service.close_product(db, product, payload.get("closed_date"))
        elif action == "reopen":
            credit_service.reopen_product(db, product)
        else:
            credit_service.apply_product_update(db, product, payload)
    elif action_type == "delete":
        product = db.query(CreditProduct).filter(CreditProduct.id == entity_id).first()
        if product:
            credit_service.delete_product(db, product)


def _handle_accounting_dividend(db, action_type, entity_id, payload, actor_id):
    # Router endpoint'iyle BİREBİR aynı mantık (tek kaynak: app/services/dividend_service).
    # Böylece onaylanan create'te de taksitler + 72 ödeme + net/stopaj finance_events üretilir.
    from app.models.dividend import DividendDistribution, DividendPayment
    from app.services import dividend_service

    target = payload.pop("_target", "distribution")

    if target == "payment":
        payment = db.query(DividendPayment).filter(DividendPayment.id == entity_id).first()
        if action_type == "update":
            if not payment:
                raise ValueError(f"Temettü ödemesi bulunamadı: {entity_id}")
            dividend_service.apply_payment_update(db, payment, payload)
        return

    # Dağıtım CRUD
    if action_type == "create":
        dividend_service.create_distribution(db, payload, actor_id)
    elif action_type == "update":
        dist = db.query(DividendDistribution).filter(DividendDistribution.id == entity_id).first()
        if not dist:
            raise ValueError(f"Temettü dağıtımı bulunamadı: {entity_id}")
        dividend_service.apply_distribution_update(db, dist, payload)
    elif action_type == "delete":
        dist = db.query(DividendDistribution).filter(DividendDistribution.id == entity_id).first()
        if dist:
            dividend_service.delete_distribution(db, dist)


def _handle_finance_hakedis(db, action_type, entity_id, payload, actor_id):
    # Router (hakedis.py update_term) ile ORTAK: receivable_service.upsert_term.
    # Doğal anahtar customer_code (payload'da) — entity_id'ye bakılmaz (kompozit upsert,
    # budget deseni). create/update aynı upsert; delete kullanılmaz (vade tanımı silinmez,
    # 30 güne çekilir).
    from app.services import receivable_service

    if action_type in ("create", "update"):
        receivable_service.upsert_term(
            db,
            payload.get("customer_code", ""),
            int(payload.get("term_days", 30)),
            payload.get("notes"),
        )


def _handle_finance_departmanlar(db, action_type, entity_id, payload, actor_id):
    # Router (departmanlar.py) ile ORTAK: app/services/department_service.
    # delete guard'lı HARD (rezervasyon/kayıt varsa ValueError). Bu handler `butce`
    # tarafından da yeniden kullanıldığından (target=department) açık fonksiyon tutulur.
    from app.models.department import Department
    from app.services import department_service

    if action_type == "create":
        department_service.create_department(db, payload)
    elif action_type == "update":
        dept = db.query(Department).filter(Department.id == entity_id).first()
        if not dept:
            raise ValueError(f"Departman bulunamadı: {entity_id}")
        department_service.apply_department_update(db, dept, payload)
    elif action_type == "delete":
        dept = db.query(Department).filter(Department.id == entity_id).first()
        if dept:
            department_service.delete_department(db, dept)


def _handle_finance_butce(db, action_type, entity_id, payload, actor_id):
    # Router (butce.py) ile ORTAK: app/services/budget_service.
    # DRIFT kapatıldı: budget create artık KOMPOZİT ANAHTAR upsert (dept+cat+yıl+ay) —
    # eskiden entity_id bazlıydı (create'te entity_id=0 → her zaman INSERT) → aynı dönem
    # için ÇİFT bütçe / uq_budget_dept_cat_year_month ihlali.
    from app.models.budget import Budget, BudgetCategory
    from app.services import budget_service

    target = payload.pop("_target", "budget")

    if target == "department":
        return _handle_finance_departmanlar(db, action_type, entity_id, payload, actor_id)

    if target == "category":
        if action_type == "create":
            budget_service.create_category(db, payload)
        elif action_type == "update":
            cat = db.query(BudgetCategory).filter(BudgetCategory.id == entity_id).first()
            if cat:
                budget_service.apply_category_update(db, cat, payload)
        elif action_type == "delete":
            cat = db.query(BudgetCategory).filter(BudgetCategory.id == entity_id).first()
            if cat:
                budget_service.delete_category(db, cat)
        return

    if target == "bulk":
        # Router bulk_upsert_budgets ile birebir — her kalem kompozit-anahtar upsert.
        for item in payload.get("items", []):
            budget_service.upsert_budget(
                db,
                department_id=item.get("department_id"),
                category_id=item.get("category_id"),
                year=item.get("year"),
                month=item.get("month"),
                planned_amount=item.get("planned_amount", 0),
                currency=item.get("currency", "TRY"),
                notes=item.get("notes"),
                created_by=actor_id,
            )
        return

    # Budget CRUD — kompozit anahtar upsert (router upsert_budget ile birebir)
    if action_type in ("create", "update"):
        budget_service.upsert_budget(
            db,
            department_id=payload.get("department_id"),
            category_id=payload.get("category_id"),
            year=payload.get("year"),
            month=payload.get("month"),
            planned_amount=payload.get("planned_amount", payload.get("amount", 0)),
            currency=payload.get("currency", "TRY"),
            notes=payload.get("notes"),
            created_by=actor_id,
        )

    elif action_type == "delete":
        budget = db.query(Budget).filter(Budget.id == entity_id).first()
        if budget:
            budget_service.delete_budget(db, budget)


def _handle_finance_checks(db, action_type, entity_id, payload, actor_id):
    # Router (update_check_status) ile BİREBİR aynı mantık — tek kaynak:
    # app/services/check_service.apply_check_status (iptal kademesi + finance_event tazeleme).
    from app.models.check import Check
    from app.services import check_service

    if action_type == "update":
        check = db.query(Check).filter(Check.id == entity_id).first()
        if not check:
            raise ValueError(f"Çek bulunamadı: {entity_id}")
        # Router payload'ı {"new_status": ...} taşır (model alanı "status").
        new_status = payload.get("new_status", payload.get("status"))
        if new_status:
            check_service.apply_check_status(db, check, new_status)
        else:
            # Savunmacı: durum dışı alan güncellemesi (endpoint her zaman new_status gönderir)
            from app.models.bank_transaction import BankTransaction
            from app.utils.finance_event_service import finance_event_svc
            _apply_fields(check, payload)
            bank_tx = (db.query(BankTransaction).filter(
                BankTransaction.id == check.bank_transaction_id).first()
                if check.bank_transaction_id else None)
            finance_event_svc.upsert_check(db, check, bank_tx)


def _handle_finance_cariler(db, action_type, entity_id, payload, actor_id):
    # Router (payment-days + status endpoint'leri) ile BİREBİR aynı mantık —
    # tek kaynak: app/services/vendor_service.apply_vendor_update (vade recalc + FE sync).
    from app.models.vendor import Vendor
    from app.services import vendor_service

    if action_type == "update":
        vendor = db.query(Vendor).filter(Vendor.id == entity_id).first()
        if not vendor:
            raise ValueError(f"Cari bulunamadı: {entity_id}")
        vendor_service.apply_vendor_update(db, vendor, payload)


# ── Kalite modülleri ──────────────────────────────────────────

def _handle_quality_templates(db, action_type, entity_id, payload, actor_id):
    from app.models.quality_template import QualityTemplate
    from app.models.quality_template_assignee import QualityTemplateAssignee
    from app.models.quality_template_section import QualityTemplateSection
    from app.services import quality_service

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
        quality_service.save_sections(db, tpl.id, sections_data)
        quality_service.save_assignees(db, tpl.id, assignees_data)

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
            quality_service.save_sections(db, entity_id, sections_data)
        if assignees_data is not None:
            db.query(QualityTemplateAssignee).filter(
                QualityTemplateAssignee.template_id == entity_id
            ).delete()
            db.flush()
            quality_service.save_assignees(db, entity_id, assignees_data)

    elif action_type == "delete":
        tpl = db.query(QualityTemplate).filter(QualityTemplate.id == entity_id).first()
        if tpl:
            db.delete(tpl)


def _handle_quality_forms(db, action_type, entity_id, payload, actor_id):
    from app.models.quality_form import QualityForm
    from app.services import quality_service

    if action_type == "create":
        quality_service.create_form(
            db,
            template_id=payload.get("template_id"),
            period_date=payload.get("period_date"),
            notes=payload.get("notes"),
        )

    elif action_type == "delete":
        form = db.query(QualityForm).filter(QualityForm.id == entity_id).first()
        if form:
            quality_service.delete_form(db, form)


def _handle_attendance(db, action_type, entity_id, payload, actor_id):
    """Onaylanan elle giriş/çıkış (hr.attendance) → AttendanceLog oluştur/güncelle/sil.

    Mutasyon TEK kaynakta: app/services/hr_service (router + executor ORTAK çağırır).
    punched_at payload'da ISO string olarak talep anında sabitlenir; service coerce eder.
    create → entity_id=0 (yeni kayıt). update/delete → entity_id=düzenlenen log id.
    Audit (log_action) + eski→yeni diff burada (onay yolu generic detay) kalır.
    """
    import pytz

    from app.models.personnel import AttendanceLog
    from app.services import hr_service
    from app.utils.audit import log_action

    tz = pytz.timezone("Europe/Istanbul")

    if action_type == "create":
        log = hr_service.create_attendance(db, payload, actor_id)
        log_action(db, actor_id, "manual_punch", "attendance", log.id, f"Onaylı elle {log.type}")

    elif action_type == "update":
        log = db.query(AttendanceLog).filter(AttendanceLog.id == entity_id).first()
        if not log:
            return
        old_type, old_when, old_note = hr_service.apply_attendance_update(db, log, payload)
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
            hr_service.delete_attendance(db, log)  # soft delete


def _handle_shifts(db, action_type, entity_id, payload, actor_id):
    """Onaylanan vardiya tanımı (hr.shifts) → ShiftDefinition oluştur/güncelle/sil.

    Mutasyon TEK kaynakta: app/services/hr_service (router + executor ORTAK çağırır).
    Zaman alanları payload'da ISO string ("HH:MM:SS") gelir; service time'a coerce eder.
    """
    from app.models.shift import ShiftDefinition
    from app.services import hr_service

    if action_type == "create":
        hr_service.create_shift(db, payload, actor_id)
    elif action_type == "update":
        s = db.query(ShiftDefinition).filter(ShiftDefinition.id == entity_id).first()
        if not s:
            return
        hr_service.apply_shift_update(db, s, payload)
    elif action_type == "delete":
        s = db.query(ShiftDefinition).filter(ShiftDefinition.id == entity_id).first()
        if s:
            hr_service.delete_shift(db, s)


def _handle_shift_schedule(db, action_type, entity_id, payload, actor_id):
    """Onaylanan vardiya çizelgesi (hr.shift_schedule) → ShiftAssignment upsert/sil.

    Mutasyon TEK kaynakta: app/services/hr_service (router + executor ORTAK çağırır).
    create → entity_id=0, upsert (personnel_id + work_date benzersiz).
    delete → entity_id=atama id. work_date payload'da ISO string; service date'e coerce eder.
    Audit (log_action) onay yolunda burada kalır.
    """
    from app.models.shift_assignment import ShiftAssignment
    from app.services import hr_service
    from app.utils.audit import log_action

    if action_type == "create":
        pid = payload.get("personnel_id")
        sid = payload.get("shift_id")
        wd = payload.get("work_date")
        if not (wd and pid and sid):
            return
        a = hr_service.upsert_assignment(db, pid, sid, wd, payload.get("note"), actor_id)
        log_action(db, actor_id, "create", "shift_assignment", a.id, "Onaylı rota ataması")

    elif action_type == "delete":
        a = db.query(ShiftAssignment).filter(ShiftAssignment.id == entity_id).first()
        if a:
            log_action(db, actor_id, "delete", "shift_assignment", a.id, "Onaylı rota silme")
            hr_service.delete_assignment(db, a)


# ── Uniform basit-CRUD handler'ları (factory ile) ────────────
# Bu 4 modül create/update/delete'te tek service çağrısı yapar (özel mantık yok) →
# _make_crud_handler ile üretilir. Router'larla ORTAK service (D1-2 deseni); davranış
# birebir. Önemli notlar:
#   - departmanlar: delete guard'lı HARD (rezervasyon/kayıt varsa ValueError).
#   - room_types: delete rezervasyon koruması (rezervasyon varsa ValueError).
#   - create_takes_actor: banks/avanslar actor_id alır; departmanlar/room_types almaz.

def _make_simple_crud_handlers():
    from app.models.advance import Advance
    from app.models.bank_account import BankAccount
    from app.models.room_type import RoomType
    from app.services import (
        advance_service,
        bank_account_service,
        room_type_service,
    )

    def _loader(model):
        return lambda db, eid: db.query(model).filter(model.id == eid).first()

    return {
        "finance.banks": _make_crud_handler(
            _loader(BankAccount), bank_account_service.create_account,
            bank_account_service.apply_account_update, bank_account_service.delete_account,
            "Banka hesabı bulunamadı: {id}", create_takes_actor=True),
        "finance.avanslar": _make_crud_handler(
            _loader(Advance), advance_service.create_advance,
            advance_service.apply_advance_update, advance_service.delete_advance,
            "Avans bulunamadı: {id}", create_takes_actor=True),
        "sales.room_types": _make_crud_handler(
            _loader(RoomType), room_type_service.create_room_type,
            room_type_service.apply_room_type_update, room_type_service.delete_room_type,
            "Oda tipi bulunamadı: {id}", create_takes_actor=False),
    }


# ── Handler kayıt tablosu ────────────────────────────────────

_HANDLERS = {
    # Sistem
    "system.users": _handle_system_users,
    "system.roles": _handle_system_roles,
    "system.modules": _handle_system_modules,
    # Finans — özel mantıklı handler'lar (açık)
    "finance.krediler": _handle_finance_krediler,
    "finance.departmanlar": _handle_finance_departmanlar,  # butce target=department yeniden kullanır
    "finance.butce": _handle_finance_butce,
    "finance.checks": _handle_finance_checks,
    "finance.cariler": _handle_finance_cariler,
    "finance.hakedis": _handle_finance_hakedis,
    # Muhasebe — Temettü (kâr payı dağıtımı, bespoke — fabrika DIŞI)
    "accounting.dividend": _handle_accounting_dividend,
    # Kalite
    "quality.templates": _handle_quality_templates,
    "quality.forms": _handle_quality_forms,
    # İK — Devam Takip (elle giriş/çıkış)
    "hr.attendance": _handle_attendance,
    # İK — Vardiya tanımları
    "hr.shifts": _handle_shifts,
    # İK — Vardiya çizelgesi (rota)
    "hr.shift_schedule": _handle_shift_schedule,
}

# Uniform basit-CRUD modülleri (finance.banks/avanslar/departmanlar, sales.room_types)
_HANDLERS.update(_make_simple_crud_handlers())

# Scheduled modüller (7 adet — temettü bespoke, yukarıda açık kayıtlı)
for _code, (_src, _dir) in _SCHEDULED_SOURCE_MAP.items():
    _HANDLERS[_code] = _make_scheduled_handler(_src, _dir)
