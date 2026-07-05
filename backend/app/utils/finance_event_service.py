"""FinanceEventService — Nakit akım olay deposu yönetimi.

Her kaynak modülün write endpoint'i (create/update/delete/match) bu servisi çağırarak
finance_events tablosunu güncel tutar. Nakit akım listesi buradan okur.

Kullanım:
    from app.utils.finance_event_service import finance_event_svc

    # Kayıt ekle / güncelle
    finance_event_svc.upsert_bank_tx(db, tx, acc, cat, vendor)
    finance_event_svc.upsert_check(db, check, bank_tx)
    finance_event_svc.upsert_credit_payment(db, payment, product)
    finance_event_svc.upsert_cc_statement(db, stmt, product)
    finance_event_svc.upsert_advance(db, adv)
    finance_event_svc.upsert_vendor_tx(db, vtx, vendor, amount)

    # Kayıt sil
    finance_event_svc.invalidate(db, "check", check_id)

    # Eşleştir (çift sayım engeli)
    finance_event_svc.match(db, "bank", btx_id, "check", check_id)
    finance_event_svc.unmatch(db, "credit", payment_id)
"""

import logging
from datetime import datetime
from typing import Optional

import pytz
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

TZ_ISTANBUL = pytz.timezone("Europe/Istanbul")

from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    SOURCE_ADVANCE,
    SOURCE_BANK,
    SOURCE_CC_PAYMENT,
    SOURCE_CHECK,
    SOURCE_CREDIT,
    SOURCE_DIVIDEND,
    SOURCE_DIVIDEND_STOPAJ,
    SOURCE_VENDOR,
    FinanceEvent,
)

logger = logging.getLogger(__name__)


def _dec(val) -> Optional[float]:
    """Decimal/None → float."""
    if val is None:
        return None
    return float(val)


class FinanceEventService:
    """Nakit akım olay deposu yönetimi."""

    # ─── Tek Merkezi Upsert ──────────────────────────────────────────────────

    def _upsert(self, db: Session, source_type: str, source_id: int, fields: dict) -> Optional[FinanceEvent]:
        """INSERT ON CONFLICT UPDATE — finance_events tablosuna atomik upsert.

        PostgreSQL INSERT ON CONFLICT ile tek sorguda yazar; ORM identity map
        üzerinden nesneyi döndürür — çift sorgu yok.
        """
        # ─── KALICI ÖTELEME (deferral) — merkezî override ────────────────────
        # Bir kalem ileri bir tarihe ötelenmişse event_date ertelenmiş tarihe çekilir.
        # TÜM türler tek yerden geçer → Sedna sync / FIFO yeniden yazımı ötelemeyi korur.
        # "bank" HARİÇ: banka hareketi gerçekleşmiş nakittir, en kalabalık FE türüdür
        # → gereksiz lookup olmasın. (lazy import: circular import'u kır.)
        if source_type != SOURCE_BANK and "event_date" in fields:
            from app.services.deferral_service import get_deferral_map
            deferred_to = get_deferral_map(db).get((source_type, source_id))
            if deferred_to is not None:
                fields["event_date"] = deferred_to

        now = datetime.now(TZ_ISTANBUL)
        fields["source_type"] = source_type
        fields["source_id"]   = source_id
        fields.setdefault("created_at", now)
        fields["updated_at"] = now

        update_fields = {k: v for k, v in fields.items()
                         if k not in ("source_type", "source_id", "created_at")}

        stmt = (
            pg_insert(FinanceEvent)
            .values(**fields)
            .on_conflict_do_update(
                constraint="uq_finance_events_source",
                set_=update_fields,
            )
            .returning(FinanceEvent.id)
        )
        row = db.execute(stmt).fetchone()
        db.flush()

        if row is None:
            return None

        # SQLAlchemy identity map — flush sonrası get() cache'den döner, ekstra sorgu yok
        event = db.get(FinanceEvent, row[0])
        if event is None:
            # Nadir durum: session cache'de yoksa tek nokta sorgusu
            event = db.query(FinanceEvent).filter(FinanceEvent.id == row[0]).first()
        elif event in db:
            # ON CONFLICT DO UPDATE SQL düzeyinde yazar; kayıt identity map'te zaten
            # varsa (yeniden upsert) python nesnesi BAYAT kalır (ör. event_date deferral
            # sonrası eski değeri gösterir). expire → sonraki erişimde tazelenir (lazy;
            # dönüş değeri okunmayan hot-path'te ekstra sorgu yok).
            db.expire(event)
        return event

    # ─── Kaynak Bazlı Upsert'ler ────────────────────────────────────────────

    def upsert_bank_tx(self, db: Session, tx, acc, cat=None, vendor=None) -> Optional[FinanceEvent]:
        """BankTransaction → FinanceEvent."""
        try:
            return self._upsert(db, SOURCE_BANK, tx.id, {
                "event_date":     tx.date,
                "amount":         abs(_dec(tx.amount)),
                "direction":      DIRECTION_INCOME if tx.type == "income" else DIRECTION_EXPENSE,
                "currency":       acc.currency if acc else "TRY",
                "description":    tx.description,
                "bank_name":      acc.bank_name if acc else None,
                "account_id":     tx.account_id,
                "iban":           acc.iban if acc else None,
                "receipt_no":     tx.receipt_no,
                "balance":        _dec(tx.balance),
                "payment_method": tx.payment_method,
                "match_number":   tx.match_number,
                "tag_note":       tx.tag_note,
                "tag_source":     tx.tag_source,
                "bank_account_id": tx.account_id,
                "vendor_id":      tx.vendor_id,
                "category_id":    cat.id if cat else tx.category_id,
                "category_name":  cat.name if cat else None,
                "category_color": cat.color if cat else None,
                "is_realized":    True,
            })
        except Exception as e:
            # Sessiz yutma YOK: çağıranın transaction'ı rollback olsun, finance_events
            # tutarsız (eksik kayıt) commit edilmesin. Çağıranlar _safe_commit/try-except içinde.
            logger.error("upsert_bank_tx hatası tx_id=%s: %s", tx.id, e)
            raise

    def upsert_check(self, db: Session, check, bank_tx=None) -> Optional[FinanceEvent]:
        """Check → FinanceEvent. Banka eşleşmesi varsa is_matched=True.

        İptal (cancelled) çek gerçek bir yükümlülük değildir → FE **invalidate** edilir
        (nakit akım listesinde hayalet bekleyen gider olarak görünmesin). Tüm yolları
        kapsar: Excel yükleme, PATCH durum, Sedna içe aktarma.
        """
        try:
            if getattr(check, "status", None) == "cancelled":
                self.invalidate(db, SOURCE_CHECK, check.id)
                return None
            # Çek nakit akımda HER ZAMAN vadesinde gösterilir (2026-07-03): ödenip
            # bankayla eşleşince de vadesindeki yerinde "Ödendi" rozetiyle kalır
            # (banka bacağı gerçek ödeme tarihinde ayrıca görünür; gün/ay toplamlarına
            # yalnız o katılır — is_matched bayrağı frontend'de toplam-dışı bırakır).
            display_date = check.due_date
            # bank_tx parametresiz çağrılar (cari eşleştirme, banka tahmini) daha önce
            # BANKAYLA eşleşmiş çekin is_matched'ını yanlışlıkla False'a düşürüyordu
            # → çift sayım (2026-07-04 denetim bulgusu: prod'da 12 çek). Çekin kendi
            # bank_transaction_id'si de eşleşmişlik kanıtıdır.
            is_matched   = bank_tx is not None or getattr(check, "bank_transaction_id", None) is not None

            return self._upsert(db, SOURCE_CHECK, check.id, {
                "event_date":      display_date,
                "amount":          abs(_dec(check.amount_currency)),
                "direction":       DIRECTION_EXPENSE,
                "currency":        "TRY" if check.currency == "TL" else check.currency,
                "description":     check.vendor_name,
                # Eşleşmişse gerçek banka hareketinin bankası; eşleşmemiş verilen çekte çekin
                # ödeneceği banka (Sedna AccCheck.Bank → checks.bank_name) → nakit akımda gösterilir.
                "bank_name":       (bank_tx.account.bank_name if bank_tx and bank_tx.account
                                    else getattr(check, "bank_name", None)),
                # Eşleşmiş banka kesin; eşleşmemişte çekin bank_name'i tahmin olabilir → bayrağı taşı
                "bank_name_inferred": (False if (bank_tx and bank_tx.account)
                                       else bool(getattr(check, "bank_name_inferred", False))),
                "payment_method":  "cek",
                "check_no":        check.check_no,
                "event_status":    check.status,
                "vendor_code":     check.vendor_code,
                "tag_note":        check.description,
                "is_matched":      is_matched,
                "is_realized":     check.status == "paid",
            })
        except Exception as e:
            logger.error("upsert_check hatası check_id=%s: %s", check.id, e)
            raise

    def upsert_credit_payment(self, db: Session, payment, product) -> Optional[FinanceEvent]:
        """CreditPayment → FinanceEvent. Banka eşleşmesi varsa is_matched=True."""
        try:
            from app.models.credit_product import CREDIT_TYPE_LABELS
            type_label = CREDIT_TYPE_LABELS.get(product.type, product.type)
            desc = f"[{type_label}] {product.name}"
            if payment.installment_no:
                desc += f" — Taksit #{payment.installment_no}"

            return self._upsert(db, SOURCE_CREDIT, payment.id, {
                "event_date":      payment.due_date,
                "amount":          abs(_dec(payment.amount)),
                "direction":       DIRECTION_EXPENSE,
                "currency":        product.currency or "TRY",
                "description":     desc,
                "bank_name":       product.bank_name,
                "payment_method":  product.type,
                "event_status":    "paid" if payment.is_paid else "pending",
                "tag_note":        f"Anapara: {_dec(payment.principal):,.2f}" if payment.principal else None,
                "is_matched":      payment.bank_transaction_id is not None,
                "is_realized":     payment.is_paid,
            })
        except Exception as e:
            logger.error("upsert_credit_payment hatası payment_id=%s: %s", payment.id, e)
            raise

    def upsert_cc_statement(self, db: Session, stmt, product) -> Optional[FinanceEvent]:
        """CreditCardStatement → FinanceEvent.

        Tutar olarak kalan borç (toplam - ödenen) kullanılır.
        Banka üzerinden yapılan kısmi ödemeler zaten banka işlemi olarak
        nakit akımda görünür; CC finance event yalnızca henüz ödenmemiş
        kısmı temsil eder — çift sayım engellenir.

        Vadesi geçmiş (son_odeme_tarihi < bugün) ekstreler nakit akımdan
        gizlenir (is_matched=True). Gerçek ödeme zaten banka kaydında.
        """
        try:
            from datetime import date as date_cls
            today = date_cls.today()

            kalan = _dec(stmt.toplam_borc) - _dec(stmt.paid_amount or 0)
            desc  = f"[Kredi Kartı] {product.name} — {stmt.kesim_tarihi.strftime('%d.%m.%Y')} Ekstresi"
            if kalan < _dec(stmt.toplam_borc):
                desc += f" (Kalan: ₺{kalan:,.2f})"

            # Vadesi geçmiş veya tamamen ödenmişse nakit akımdan gizle
            is_past_due = stmt.son_odeme_tarihi < today
            should_hide = stmt.is_paid or is_past_due

            return self._upsert(db, SOURCE_CC_PAYMENT, stmt.id, {
                "event_date":      stmt.son_odeme_tarihi,
                "amount":          abs(kalan) if kalan > 0 else abs(_dec(stmt.toplam_borc)),
                "direction":       DIRECTION_EXPENSE,
                "currency":        "TRY",
                "description":     desc,
                "bank_name":       product.bank_name,
                "payment_method":  "kredi_karti",
                "event_status":    "paid" if should_hide else "pending",
                "tag_note":        f"Asgari: ₺{_dec(stmt.asgari_odeme):,.2f}",
                "is_matched":      should_hide,
                "is_realized":     should_hide,
            })
        except Exception as e:
            logger.error("upsert_cc_statement hatası stmt_id=%s: %s", stmt.id, e)
            raise

    def upsert_advance(self, db: Session, adv) -> Optional[FinanceEvent]:
        """Advance → FinanceEvent. Banka eşleşmesi varsa is_matched=True."""
        try:
            if adv.status == "cancelled":
                self.invalidate(db, SOURCE_ADVANCE, adv.id)
                return None

            # Avans "received" olduğunda is_matched=True yapılır ki
            # nakit akımda çift görünmesin — banka ekstresi tarafı yeterli.
            is_received = adv.status == "received"
            return self._upsert(db, SOURCE_ADVANCE, adv.id, {
                "event_date":   adv.advance_date,
                "amount":       abs(_dec(adv.received_amount or adv.amount)),
                "direction":    DIRECTION_INCOME,
                "currency":     adv.currency,
                "description":  f"[Avans] {adv.agency_name}",
                "event_status": adv.status,
                "tag_note":     adv.notes,
                "is_matched":   is_received,
                "is_realized":  is_received,
            })
        except Exception as e:
            logger.error("upsert_advance hatası adv_id=%s: %s", adv.id, e)
            raise

    def upsert_vendor_tx(self, db: Session, vtx, vendor, amount: float) -> Optional[FinanceEvent]:
        """VendorTransaction (ödeme planı) → FinanceEvent."""
        try:
            if vtx.payment_due_date is None:
                self.invalidate(db, SOURCE_VENDOR, vtx.id)
                return None

            return self._upsert(db, SOURCE_VENDOR, vtx.id, {
                "event_date":      vtx.payment_due_date,
                "amount":          abs(amount),
                "direction":       DIRECTION_EXPENSE,
                "currency":        "TRY",
                "description":     vendor.hesap_adi,
                "payment_method":  "cari",
                "vendor_id":       vtx.vendor_id,
                "vendor_code":     vendor.hesap_kodu,
                "tag_note":        vtx.evrak_no,
                "is_matched":      vtx.match_number is not None,
                "is_realized":     vtx.match_number is not None,
            })
        except Exception as e:
            logger.error("upsert_vendor_tx hatası vtx_id=%s: %s", vtx.id, e)
            raise

    # ─── Planlı Giderler (Vergi, Düzenli Ödeme, Maaş, Stopaj) ─────────────

    def upsert_scheduled_entry(self, db: Session, entry, direction: int = DIRECTION_EXPENSE) -> Optional[FinanceEvent]:
        """ScheduledEntry → FinanceEvent. source_type giriş kaydından alınır."""
        try:
            desc_map = {
                "tax": "Vergi",
                "recurring": "Düzenli Ödeme",
                "salary": "Maaş",
                "withholding": "Stopaj",
                "rent_income": "Alınan Kira",
                "rent_expense": "Verilen Kira",
                "sgk": "SGK",
                "dividend": "Temettü",
            }
            prefix = desc_map.get(entry.source_type, "Gider")
            desc = entry.description or f"[{prefix}]"

            event_date = entry.paid_date if entry.paid_date else entry.entry_date

            return self._upsert(db, entry.source_type, entry.id, {
                "event_date":   event_date,
                "amount":       abs(float(entry.amount)),
                "direction":    direction,
                "currency":     entry.currency or "TRY",
                "description":  desc,
                "event_status": "paid" if entry.is_paid else "pending",
                "is_realized":  entry.is_paid,
                "is_matched":   False,
            })
        except Exception as e:
            logger.error("upsert_scheduled_entry hatası id=%s: %s", entry.id, e)
            raise

    # ─── Kâr Payı Dağıtımı (Temettü) — ÖDEME (pay sahibi × taksit) bazlı net + stopaj ──────────
    # Kişi-kişi görünürlük + kısmi ödeme ayrımı için finance_event TAKSİT değil ÖDEME satırı
    # (dividend_payments) anahtarıdır. source_id = payment.id. Tarih/açıklama servis tarafından
    # hesaplanır (net = gerçek/planlı ödeme tarihi; stopaj = muhtasar veya gerçek ödeme tarihi).

    def upsert_dividend_net(self, db: Session, payment, description: str, event_date) -> Optional[FinanceEvent]:
        """DividendPayment net bacağı → FinanceEvent (source_type 'dividend').

        Banka eşleşmesi varsa (payment.bank_transaction_id) is_matched=True → nakit akımda gizlenir
        (banka bacağı gerçek çıkışı temsil eder; çift sayım engellenir)."""
        try:
            return self._upsert(db, SOURCE_DIVIDEND, payment.id, {
                "event_date":   event_date,
                "amount":       abs(float(payment.net_amount)),
                "direction":    DIRECTION_EXPENSE,
                "currency":     "TRY",
                "description":  description,
                "payment_method": "temettu",
                "event_status": "paid" if payment.is_paid else "pending",
                "is_realized":  payment.is_paid,
                "is_matched":   payment.bank_transaction_id is not None,
            })
        except Exception as e:
            logger.error("upsert_dividend_net hatası payment_id=%s: %s", payment.id, e)
            raise

    def upsert_dividend_stopaj(self, db: Session, payment, description: str, event_date) -> Optional[FinanceEvent]:
        """DividendPayment stopaj bacağı → FinanceEvent (source_type 'dividend_stopaj')."""
        try:
            return self._upsert(db, SOURCE_DIVIDEND_STOPAJ, payment.id, {
                "event_date":   event_date,
                "amount":       abs(float(payment.stopaj_amount)),
                "direction":    DIRECTION_EXPENSE,
                "currency":     "TRY",
                "description":  description,
                "payment_method": "stopaj",
                "event_status": "paid" if payment.stopaj_paid else "pending",
                "is_realized":  payment.stopaj_paid,
                "is_matched":   False,
            })
        except Exception as e:
            logger.error("upsert_dividend_stopaj hatası payment_id=%s: %s", payment.id, e)
            raise

    # ─── Silme & Eşleştirme ─────────────────────────────────────────────────

    def invalidate(self, db: Session, source_type: str, source_id: int) -> None:
        """Kaynağı finance_events'ten kaldır (kaynak silindiğinde).

        Silinen kaydın matched_event_id ile eşleştiği karşı taraf varsa
        o kaydın is_matched flag'i de temizlenir — aksi halde karşı taraf
        sonsuza dek gizli kalır (orphan match).
        """
        try:
            # Silinecek event'i bul — eşleşme bilgisini temizlemek için
            event = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == source_type,
                FinanceEvent.source_id   == source_id,
            ).first()

            if event:
                # Bu event'e matched_event_id ile bağlı karşı tarafı temizle
                db.query(FinanceEvent).filter(
                    FinanceEvent.matched_event_id == event.id,
                ).update(
                    {"is_matched": False, "matched_event_id": None},
                    synchronize_session=False,
                )

                # Bu event başka bir event'e bağlıysa onu da temizle
                if event.matched_event_id:
                    db.query(FinanceEvent).filter(
                        FinanceEvent.id == event.matched_event_id,
                    ).update(
                        {"is_matched": False, "matched_event_id": None},
                        synchronize_session=False,
                    )

                db.delete(event)
            else:
                # Event yoksa direkt sil (eski davranış)
                db.query(FinanceEvent).filter(
                    FinanceEvent.source_type == source_type,
                    FinanceEvent.source_id   == source_id,
                ).delete(synchronize_session=False)

            db.flush()
        except Exception as e:
            logger.error("invalidate hatası %s/%s: %s", source_type, source_id, e)
            raise

    def match(
        self,
        db: Session,
        source_type_a: str,
        source_id_a: int,
        source_type_b: str,
        source_id_b: int,
    ) -> None:
        """İki kaynağı eşleştir — ikincisi is_matched=True, ilki is_realized=True olur.

        Kural:
        - bank + check      → check is_matched=True (banka tarafı görünür)
        - bank + credit     → credit is_matched=True
        - bank + advance    → advance is_matched=True
        - bank + cc_payment → cc_payment is_matched=True
        """
        try:
            # A kaynağını is_realized yap
            db.query(FinanceEvent).filter(
                FinanceEvent.source_type == source_type_a,
                FinanceEvent.source_id   == source_id_a,
            ).update({"is_realized": True}, synchronize_session=False)

            # B kaynağını gizle (is_matched=True)
            db.query(FinanceEvent).filter(
                FinanceEvent.source_type == source_type_b,
                FinanceEvent.source_id   == source_id_b,
            ).update({"is_matched": True, "is_realized": True}, synchronize_session=False)

            db.flush()
        except Exception as e:
            logger.error("match hatası %s/%s ↔ %s/%s: %s",
                         source_type_a, source_id_a, source_type_b, source_id_b, e)
            raise

    def unmatch(self, db: Session, source_type: str, source_id: int) -> None:
        """Eşleştirmeyi geri al — is_matched=False, matched_event_id=None."""
        try:
            db.query(FinanceEvent).filter(
                FinanceEvent.source_type == source_type,
                FinanceEvent.source_id   == source_id,
            ).update(
                {"is_matched": False, "is_realized": False, "matched_event_id": None},
                synchronize_session=False,
            )
            db.flush()
        except Exception as e:
            logger.error("unmatch hatası %s/%s: %s", source_type, source_id, e)
            raise

    def sync_tag(self, db: Session, tx_id: int, category_id, category_name, category_color,
                 tag_note, tag_source, payment_method, match_number, vendor_id) -> None:
        """BankTransaction etiket değişikliğini finance_events'e yansıt.
        NOT: is_matched burada DEĞİŞTİRİLMEZ — sadece match()/unmatch() fonksiyonları değiştirir.
        Cari eşleştirmesi banka hareketini nakit akımdan gizlememeli.
        """
        try:
            # vendor_code'u da çek
            vendor_code = None
            if vendor_id:
                from app.models.vendor import Vendor
                v = db.query(Vendor).filter(Vendor.id == vendor_id).first()
                if v:
                    vendor_code = v.hesap_kodu

            update_fields = {
                "category_id":    category_id,
                "category_name":  category_name,
                "category_color": category_color,
                "tag_note":       tag_note,
                "tag_source":     tag_source,
                "payment_method": payment_method,
                "match_number":   match_number,
                "vendor_id":      vendor_id,
                "vendor_code":    vendor_code,
            }

            rows = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == SOURCE_BANK,
                FinanceEvent.source_id   == tx_id,
            ).update(update_fields, synchronize_session=False)
            logger.info("sync_tag tx_id=%s: %d satır güncellendi (match=%s)", tx_id, rows, match_number)

            if rows == 0:
                # finance_events'te kayıt yok — oluştur
                from app.models.bank_account import BankAccount
                from app.models.bank_transaction import BankTransaction
                btx = db.query(BankTransaction).filter(BankTransaction.id == tx_id).first()
                if btx:
                    acc = db.query(BankAccount).filter(BankAccount.id == btx.account_id).first()
                    self.upsert_bank_tx(db, btx, acc)
                    db.query(FinanceEvent).filter(
                        FinanceEvent.source_type == SOURCE_BANK,
                        FinanceEvent.source_id   == tx_id,
                    ).update(update_fields, synchronize_session=False)
                    logger.info("sync_tag: FE oluşturuldu tx_id=%s", tx_id)
            db.flush()
        except Exception as e:
            logger.error("sync_tag hatası tx_id=%s: %s", tx_id, e)
            raise

    def update_amount_try(self, db: Session, event_date, rate_try_per_eur: float) -> int:
        """Belirli tarih için EUR/USD cinsindeki eventlerin amount_try'ını güncelle.

        rate_try_per_eur: 1 EUR = X TRY
        """
        try:
            updated = (
                db.query(FinanceEvent)
                .filter(
                    FinanceEvent.event_date == event_date,
                    FinanceEvent.currency   == "EUR",
                )
                .update(
                    {"amount_try": FinanceEvent.amount * rate_try_per_eur},
                    synchronize_session=False,
                )
            )
            db.flush()
            return updated
        except Exception as e:
            logger.error("update_amount_try hatası date=%s: %s", event_date, e)
            return 0


# Singleton instance
finance_event_svc = FinanceEventService()
