"""Banka hareketi serbest bırakma servisi (Faz 3 #22c/#24, 2026-07-12).

Bir banka hareketi (veya ekstre/hesap) SİLİNMEDEN önce ona bağlı tüm eşleşmeler
çözülmelidir — aksi halde 'bankasız ödendi' görünen çek/taksit/avans + kaynağı
silinmiş orphan finance_events kalır (2026-07-11 denetim C5). Tek kaynak: hesap
silme (bank_account_service), ekstre silme ve tekil işlem silme AYNI fonksiyonu
kullanır; onay executor'ı da service üzerinden geçer (D1-2).
"""
import logging

from sqlalchemy.orm import Session

from app.models import Advance, BankTransaction, CreditPayment, CreditProduct
from app.models.check import Check
from app.models.credit_card_statement import CreditCardStatement
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.vendor_transaction import VendorTransaction
from app.utils.finance_event_service import finance_event_svc

logger = logging.getLogger(__name__)


def release_bank_transaction(db: Session, tx: BankTransaction) -> dict:
    """Banka hareketine bağlı TÜM eşleşmeleri çöz (silme öncesi zorunlu temizlik).

    Çek → pending; kredi taksiti → unpaid + anapara iadesi (grup üyeleri dahil);
    avans → pending; KK ekstresi → paid_amount geri düşer; cari match_number çifti
    temizlenir. FE unmatch + kaynak upsert; event_matches izleri silinir.

    Dönüş sayaçları: {checks, credits, advances, cc, vendor, needs_vendor_sync}.
    Cari çözüldüyse çağıran işlem sonunda BİR KEZ sync_vendor_finance_events koşmalı.
    """
    counts = {"checks": 0, "credits": 0, "advances": 0, "cc": 0, "vendor": 0,
              "needs_vendor_sync": False}

    # Çekler
    for c in db.query(Check).filter(Check.bank_transaction_id == tx.id).all():
        c.bank_transaction_id = None
        if c.status == "paid":
            c.status = "pending"
        db.flush()
        finance_event_svc.unmatch(db, "check", c.id)
        finance_event_svc.upsert_check(db, c)
        counts["checks"] += 1

    # Kredi taksitleri — doğrudan FK + grup üyeliği (event_matches izinden)
    credit_ids = {p.id for p in db.query(CreditPayment)
                  .filter(CreditPayment.bank_transaction_id == tx.id).all()}
    credit_ids |= {m.target_source_id for m in db.query(EventMatch).filter(
        EventMatch.bank_source_type == "bank", EventMatch.bank_source_id == tx.id,
        EventMatch.target_source_type == "credit",
        EventMatch.method != MATCH_METHOD_SUGGESTION).all()}
    for pid in credit_ids:
        p = db.query(CreditPayment).filter(CreditPayment.id == pid).first()
        if p is None or not p.is_paid:
            continue
        product = db.query(CreditProduct).filter(CreditProduct.id == p.credit_product_id).first()
        # Grup eşleşmesinin diğer banka satırlarındaki ortak match_number izini temizle
        group_ids = [m.bank_source_id for m in db.query(EventMatch).filter(
            EventMatch.target_source_type == "credit", EventMatch.target_source_id == p.id,
            EventMatch.bank_source_type == "bank",
            EventMatch.method != MATCH_METHOD_SUGGESTION).all()]
        for bid in group_ids:
            b = db.query(BankTransaction).filter(BankTransaction.id == bid).first()
            if b is not None and b.match_number is not None and b.vendor_id is None:
                b.match_number = None  # kredi grup izi (cari eşleşme numarasına dokunma)
        p.is_paid = False
        p.paid_date = None
        p.bank_transaction_id = None
        if p.principal and product:
            product.remaining_amount = float(product.remaining_amount) + float(p.principal)
        db.flush()
        finance_event_svc.unmatch(db, "credit", p.id)
        finance_event_svc.upsert_credit_payment(db, p, product)
        counts["credits"] += 1

    # Avanslar
    for a in db.query(Advance).filter(Advance.bank_transaction_id == tx.id).all():
        a.status = "pending"
        a.received_date = None
        a.received_amount = None
        a.bank_transaction_id = None
        db.flush()
        finance_event_svc.unmatch(db, "advance", a.id)
        finance_event_svc.upsert_advance(db, a)
        counts["advances"] += 1

    # KK ekstreleri — bağ event_matches izinde (stmt'de btx FK yok); ödeme geri düşer
    for m in db.query(EventMatch).filter(
            EventMatch.bank_source_type == "bank", EventMatch.bank_source_id == tx.id,
            EventMatch.target_source_type == "cc_payment",
            EventMatch.method != MATCH_METHOD_SUGGESTION).all():
        stmt = db.query(CreditCardStatement).filter(
            CreditCardStatement.id == m.target_source_id).first()
        if stmt is None:
            continue
        stmt.paid_amount = max(0.0, float(stmt.paid_amount or 0) - abs(float(tx.amount)))
        if stmt.is_paid:
            stmt.is_paid = False
            stmt.paid_date = None
        prod = db.query(CreditProduct).filter(CreditProduct.id == stmt.credit_product_id).first()
        db.flush()
        finance_event_svc.unmatch(db, "cc_payment", stmt.id)
        finance_event_svc.upsert_cc_statement(db, stmt, prod)
        counts["cc"] += 1

    # Cari eşleşmesi (match_number çifti) — karşı cari satırı serbest kalır
    if tx.match_number is not None:
        released = (db.query(VendorTransaction)
                    .filter(VendorTransaction.match_number == tx.match_number)
                    .update({VendorTransaction.match_number: None,
                             VendorTransaction.payment_method: None},
                            synchronize_session=False))
        if released:
            counts["vendor"] += released
            counts["needs_vendor_sync"] = True
        db.flush()

    # Kalan event_matches izleri (öneriler dahil) — banka bacağı yok oluyor
    finance_event_svc._delete_event_matches(db, "bank", tx.id)
    return counts


def delete_bank_statement(db: Session, stmt) -> dict:
    """Ekstreyi ve işlemlerini güvenle sil: her işlem için eşleşme çözümü + FE invalidate.

    Hatalı/yanlış hesaba yüklenmiş ekstrenin geri alma yolu (denetim C7 — eskiden
    tek yol hesabı komple silmekti). Çağıran commit + broadcast'ten sorumlu.
    """
    txs = db.query(BankTransaction).filter(BankTransaction.statement_id == stmt.id).all()
    totals = {"transactions": len(txs), "checks": 0, "credits": 0, "advances": 0,
              "cc": 0, "vendor": 0, "needs_vendor_sync": False}
    for tx in txs:
        c = release_bank_transaction(db, tx)
        for k in ("checks", "credits", "advances", "cc", "vendor"):
            totals[k] += c[k]
        totals["needs_vendor_sync"] = totals["needs_vendor_sync"] or c["needs_vendor_sync"]
        finance_event_svc.invalidate(db, "bank", tx.id)
        # bank_transactions.statement_id FK'sı ON DELETE **SET NULL** (CASCADE değil —
        # migration 2b4495d4c8f5) → işlemler AÇIKÇA silinmeli; yoksa ekstre silinince
        # satırlar statement_id=NULL orphan kalır (FE'leri invalidate edildiğinden nakit
        # akımda görünmez ama banka listesinde durur). sedna_bank_recon izleri
        # bank_transaction_id FK CASCADE ile birlikte düşer.
        db.delete(tx)
    db.delete(stmt)
    db.flush()
    return totals


def delete_bank_transaction(db: Session, tx: BankTransaction) -> dict:
    """Tekil banka işlemini sil — YALNIZ eşleşmemiş satır (bilinçli sürtünme:
    eşleşmiş satır banka kanıtıdır; önce eşleşme geri alınmalı)."""
    linked = (
        tx.match_number is not None
        or db.query(Check.id).filter(Check.bank_transaction_id == tx.id).first() is not None
        or db.query(CreditPayment.id).filter(CreditPayment.bank_transaction_id == tx.id).first() is not None
        or db.query(Advance.id).filter(Advance.bank_transaction_id == tx.id).first() is not None
        or db.query(EventMatch.id).filter(
            EventMatch.bank_source_type == "bank", EventMatch.bank_source_id == tx.id,
            EventMatch.method != MATCH_METHOD_SUGGESTION).first() is not None
    )
    if linked:
        raise ValueError("İşlem eşleşmiş — önce eşleşmeyi geri alın (çek/kredi/cari)")
    release_bank_transaction(db, tx)  # öneri izleri temizlenir
    finance_event_svc.invalidate(db, "bank", tx.id)
    db.delete(tx)
    db.flush()
    return {"ok": True}


def delete_account_with_cleanup(db: Session, acc) -> dict:
    """Hesabı, işlemlerinin TÜM eşleşme/FE temizliğiyle birlikte sil (denetim C5).

    Eskiden yalnız db.delete(acc) yapılıyordu: cascade işlemleri silerken kaynak
    kayıtlar 'bankasız ödendi' kalıyor, source_type='bank' FE'leri orphan kalıyordu.
    """
    txs = db.query(BankTransaction).filter(BankTransaction.account_id == acc.id).all()
    totals = {"transactions": len(txs), "needs_vendor_sync": False}
    for tx in txs:
        c = release_bank_transaction(db, tx)
        totals["needs_vendor_sync"] = totals["needs_vendor_sync"] or c["needs_vendor_sync"]
        finance_event_svc.invalidate(db, "bank", tx.id)
    db.delete(acc)
    db.flush()
    return totals
