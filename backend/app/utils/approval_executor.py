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

def _handle_finance_banks(db, action_type, entity_id, payload, actor_id):
    from app.models.bank_account import BankAccount
    from app.services import bank_account_service

    if action_type == "create":
        bank_account_service.create_account(db, payload, actor_id)
    elif action_type == "update":
        acc = db.query(BankAccount).filter(BankAccount.id == entity_id).first()
        if not acc:
            raise ValueError(f"Banka hesabı bulunamadı: {entity_id}")
        bank_account_service.apply_account_update(db, acc, payload)
    elif action_type == "delete":
        acc = db.query(BankAccount).filter(BankAccount.id == entity_id).first()
        if acc:
            bank_account_service.delete_account(db, acc)


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
        credit_service.apply_product_update(db, product, payload)
    elif action_type == "delete":
        product = db.query(CreditProduct).filter(CreditProduct.id == entity_id).first()
        if product:
            credit_service.delete_product(db, product)


def _handle_finance_avanslar(db, action_type, entity_id, payload, actor_id):
    from app.models.advance import Advance
    from app.services import advance_service

    if action_type == "create":
        advance_service.create_advance(db, payload, actor_id)
    elif action_type == "update":
        adv = db.query(Advance).filter(Advance.id == entity_id).first()
        if not adv:
            raise ValueError(f"Avans bulunamadı: {entity_id}")
        advance_service.apply_advance_update(db, adv, payload)
    elif action_type == "delete":
        adv = db.query(Advance).filter(Advance.id == entity_id).first()
        if adv:
            advance_service.delete_advance(db, adv)


def _handle_finance_departmanlar(db, action_type, entity_id, payload, actor_id):
    # Router (departmanlar.py) ile ORTAK: app/services/department_service.
    # delete artık guard'lı HARD (eskiden guard'sız SOFT idi → router'dan sapıyordu).
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
