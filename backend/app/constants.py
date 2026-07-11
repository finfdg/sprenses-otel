"""Merkezi sabitler — sihirli string'lerin tek doğruluk kaynağı.

WebSocket event tipleri, finance/sales broadcast modül adları ve planlı (scheduled)
`source_type` değerleri burada tanımlıdır. Backend genelinde literal string yerine
bu sabitler kullanılır — böylece yazım hatası (typo) kaynaklı sessiz kırılmalar
(ör. frontend'in dinlemediği bir event tipi yayınlamak, sorguda eşleşmeyen bir
source_type) önlenir.

Tek doğruluk kaynağı ilkesi:
- Finans hareketi `source_type` değerleri zaten `app/models/finance_event.py` içinde
  (`SOURCE_BANK` vb.) tanımlıdır. Burada **yeniden tanımlanmaz**, oradan re-export
  edilir — böylece değer iki yerde tutulmaz.
- Planlı (scheduled) `source_type` değerleri ile WS event tipleri ve broadcast modül
  adlarının başka bir evi yoktu; bunların kanonik evi bu dosyadır.

Frontend karşılığı: `frontend/src/lib/constants/realtime.ts`. WS event tipleri ve
broadcast modül adları iki taraf arasında **birebir aynı** olmalıdır (Python ↔ TS
arası otomatik senkron yoktur; değer değişirse her iki dosya birlikte güncellenir).

DİKKAT — `source_type` değerleri veritabanında saklanır (`finance_events.source_type`,
`scheduled_definitions.source_type`). Bu string'ler **DEĞİŞTİRİLEMEZ**; yalnızca
literal yerine isimli sabitle referanslanır. Yeni değer eklemek migration gerektirir.
"""

from app.models.finance_event import (
    SOURCE_ADVANCE,
    SOURCE_BANK,
    SOURCE_CC_PAYMENT,
    SOURCE_CHECK,
    SOURCE_CREDIT,
    SOURCE_VENDOR,
)


class WSEvent:
    """WebSocket event `type` değerleri — backend yayını ↔ frontend `onWsEvent`.

    Bu değerler diller-arası sözleşmedir: backend `manager.send_to_*({"type": ...})`
    ile yayınlar, frontend `onWsEvent(type, handler)` ile dinler. Değer uyuşmazlığı
    sessizce çalışmaz; bu yüzden tek kaynaktan referanslanır.
    """

    # Finans / satış / onay — gerçek zamanlı veri akışı
    FINANCE_UPDATED = "finance_updated"
    SALES_UPDATED = "sales_updated"
    APPROVAL_UPDATED = "approval_updated"
    APPROVAL_STATUS_CHANGED = "approval_status_changed"
    BANK_STATEMENT_UPLOADED = "bank_statement_uploaded"
    ATTENDANCE_UPDATED = "attendance_updated"  # PDKS giriş/çıkış — canlı pano tazeleme
    SHIFT_SCHEDULE_UPDATED = "shift_schedule_updated"  # vardiya çizelgesi (rota) — canlı tazeleme
    PERMISSION_CHANGED = "permission_changed"
    SEDNA_SYNC_PROGRESS = "sedna_sync_progress"  # merkezi Sedna senkronu adım-adım ilerleme (Faz 2 #18)

    # Oturum / bağlantı
    CONNECTED = "connected"
    FORCE_LOGOUT = "force_logout"
    SESSION_EXPIRED = "session_expired"
    USER_STATUS = "user_status"
    USER_EMAIL_VERIFIED = "user_email_verified"  # e-posta teyidi → kullanıcı listesi canlı tazeleme

    # Bildirim
    NOTIFICATION = "notification"

    # Mesajlaşma
    NEW_MESSAGE = "new_message"
    NEW_CONVERSATION = "new_conversation"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_DELETED = "message_deleted"
    READ_STATUS = "read_status"
    TYPING = "typing"
    UNREAD_INCREMENTED = "unread_incremented"
    UNREAD_UPDATED = "unread_updated"
    GROUP_NAME_CHANGED = "group_name_changed"
    GROUP_ADMIN_CHANGED = "group_admin_changed"
    GROUP_MEMBER_ADDED = "group_member_added"
    GROUP_MEMBER_REMOVED = "group_member_removed"


class BroadcastModule:
    """`finance_updated` / `sales_updated` event'lerindeki `module` alanı.

    Frontend bu alanı hangi panonun tazeleneceğini belirlemek için kullanabilir.
    (Çoğu dinleyici modülden bağımsız tazelediği için yanlış değer bugün
    işlevsel kırılma yaratmaz, ancak tutarlılık ve gelecekteki modül-bazlı
    filtreleme için merkezileştirilmiştir.)
    """

    # Finans alanı
    BANKS = "banks"
    CARILER = "cariler"
    CASH_FLOW = "cash_flow"
    CHECKS = "checks"
    CREDITS = "credits"
    ADVANCES = "advances"
    ACCOUNTING = "accounting"
    HR = "hr"
    APPROVAL = "approval"
    SCHEDULED = "scheduled"  # create_scheduled_router varsayılanı
    RECON = "recon"  # Sedna mutabakat (accounting.mutabakat — Uyuşmayan Veriler)
    BUTCE = "butce"  # bütçe + departman fatura onayı (bütçe actual'ları)
    HAKEDIS = "hakedis"  # hak ediş vade tanımları
    STOK = "stok"  # stok/depo (Sedna stok senkronu)
    EXCHANGE_RATES = "exchange_rates"  # döviz kurları (fx cron → internal yayın; mevcut literal sabitlendi)
    SALES_INVOICES = "sales_invoices"  # satış faturaları/tahsilatlar (Sedna aynalama sonrası yayın)

    # Satış alanı
    HOTEL_RESERVATION = "hotel_reservation"
    ROOM_TYPES = "room_types"
    AGENCY_GROUPS = "agency_groups"


class ReconStatus:
    """`sedna_bank_recon.status` değerleri (DB-saklı — DEĞİŞTİRİLEMEZ).

    Banka↔Sedna mutabakat sınıflandırması. Kural: banka verisi HER ZAMAN otorite —
    motor banka satırını değiştirmez, yalnız sınıflar. Frontend karşılığı
    `lib/constants/realtime.ts` RECON_STATUS (iki taraf birebir aynı tutulur).
    """

    MATCHED = "matched"                    # birebir/grup eşleşti (kapalı)
    SEDNA_PENDING = "sedna_pending"        # bankada var, Sedna henüz girmemiş (gecikme — uyuşmazlık DEĞİL)
    SEDNA_MISSING = "sedna_missing"        # bankada var, Sedna dönem içinde girmemiş (gerçek eksik)
    SEDNA_EXTRA = "sedna_extra"            # Sedna'da var, bankada yok (muhtemel hatalı giriş)
    DIRECTION_FLIP = "direction_flip"      # aynı gün + aynı mutlak tutar + TERS yön (borç/alacak ters)
    DUPLICATE_SUSPECT = "duplicate_suspect"  # Sedna adedi > banka adedi (mükerrer fiş şüphesi)
    SEDNA_DIFF = "sedna_diff"              # eşleşmiş/korunan yerel kayıtta Sedna sapması (entity_type'lı)
    BALANCE_DIFF = "balance_diff"          # cari net bakiyesi ↔ Sedna 320 hesap bakiyesi farkı (Faz C)

    OPEN = frozenset({SEDNA_PENDING, SEDNA_MISSING, SEDNA_EXTRA, DIRECTION_FLIP,
                      DUPLICATE_SUSPECT, SEDNA_DIFF, BALANCE_DIFF})


class SourceType:
    """`finance_events.source_type` ve `scheduled_definitions.source_type` değerleri.

    Finans hareketi kaynakları `app/models/finance_event.py`'den re-export edilir
    (değer orada tek kaynak). Planlı kaynaklar burada tanımlıdır.

    DİKKAT: DB'de saklanır — değerler DEĞİŞTİRİLEMEZ. Yalnızca literal yerine
    isimli sabitle referanslanır (sorgu eşleşmesi aynı kalmalı).
    """

    # Finans hareketi kaynakları (re-export — tek kaynak: models/finance_event.py)
    BANK = SOURCE_BANK
    CHECK = SOURCE_CHECK
    CREDIT = SOURCE_CREDIT
    CC_PAYMENT = SOURCE_CC_PAYMENT
    ADVANCE = SOURCE_ADVANCE
    VENDOR_PAYMENT = SOURCE_VENDOR

    # Planlı tanım kaynakları (scheduled_definitions) — create_scheduled_router
    TAX = "tax"
    RECURRING = "recurring"
    RENT_INCOME = "rent_income"
    RENT_EXPENSE = "rent_expense"
    SALARY = "salary"
    WITHHOLDING = "withholding"
    SGK = "sgk"

    # Kâr payı dağıtımı (bespoke modül — create_scheduled_router DEĞİL).
    # DIVIDEND = net kalem (ortaklara), DIVIDEND_STOPAJ = stopaj kalemi (vergi dairesine).
    DIVIDEND = "dividend"
    DIVIDEND_STOPAJ = "dividend_stopaj"

    # create_scheduled_router fabrikasıyla üretilen tüm planlı source_type'lar
    # (temettü artık fabrika DIŞI — bespoke; bu yüzden burada YOK)
    SCHEDULED = frozenset({
        TAX, RECURRING, RENT_INCOME, RENT_EXPENSE,
        SALARY, WITHHOLDING, SGK,
    })
