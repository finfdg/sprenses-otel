/**
 * Gerçek zamanlı (WebSocket) sözleşme sabitleri — sihirli string'lerin tek kaynağı.
 *
 * WS event tipleri ve broadcast modül adları backend ile **birebir aynı** olmalıdır.
 * Backend karşılığı: `backend/app/constants.py` (WSEvent, BroadcastModule).
 * Python ↔ TS arası otomatik senkron yoktur; bir değer değişirse iki dosya birlikte
 * güncellenir.
 *
 * `onWsEvent` / `emitLocal` parametreleri `WsEventType` union'ı ile tiplenmiştir;
 * böylece kataloğda olmayan bir event adı yazmak **derleme hatası** verir (typo
 * kaynaklı sessiz kırılma önlenir).
 */

// WebSocket event `type` değerleri (backend yayını ↔ frontend onWsEvent)
export const WS_EVENT = {
	// Finans / satış / onay — gerçek zamanlı veri akışı
	FINANCE_UPDATED: 'finance_updated',
	SALES_UPDATED: 'sales_updated',
	APPROVAL_UPDATED: 'approval_updated',
	APPROVAL_STATUS_CHANGED: 'approval_status_changed',
	BANK_STATEMENT_UPLOADED: 'bank_statement_uploaded',
	ATTENDANCE_UPDATED: 'attendance_updated',
	SHIFT_SCHEDULE_UPDATED: 'shift_schedule_updated',
	PERMISSION_CHANGED: 'permission_changed',

	// Oturum / bağlantı
	CONNECTED: 'connected',
	FORCE_LOGOUT: 'force_logout',
	SESSION_EXPIRED: 'session_expired',
	USER_STATUS: 'user_status',
	USER_EMAIL_VERIFIED: 'user_email_verified',

	// Bildirim
	NOTIFICATION: 'notification',

	// Mesajlaşma
	NEW_MESSAGE: 'new_message',
	NEW_CONVERSATION: 'new_conversation',
	MESSAGE_EDITED: 'message_edited',
	MESSAGE_DELETED: 'message_deleted',
	READ_STATUS: 'read_status',
	TYPING: 'typing',
	UNREAD_INCREMENTED: 'unread_incremented',
	UNREAD_UPDATED: 'unread_updated',
	GROUP_NAME_CHANGED: 'group_name_changed',
	GROUP_ADMIN_CHANGED: 'group_admin_changed',
	GROUP_MEMBER_ADDED: 'group_member_added',
	GROUP_MEMBER_REMOVED: 'group_member_removed',
} as const;

export type WsEventType = (typeof WS_EVENT)[keyof typeof WS_EVENT];

// finance_updated / sales_updated event'lerindeki `module` alanı
export const BROADCAST_MODULE = {
	// Finans alanı
	BANKS: 'banks',
	CARILER: 'cariler',
	CASH_FLOW: 'cash_flow',
	CHECKS: 'checks',
	CREDITS: 'credits',
	ADVANCES: 'advances',
	ACCOUNTING: 'accounting',
	HR: 'hr',
	APPROVAL: 'approval',
	SCHEDULED: 'scheduled',
	RECON: 'recon', // Sedna mutabakat (accounting.mutabakat)
	SALES_INVOICES: 'sales_invoices', // satış faturaları/tahsilatlar (Sedna aynalama sonrası yayın)
	// Satış alanı
	HOTEL_RESERVATION: 'hotel_reservation',
	ROOM_TYPES: 'room_types',
	AGENCY_GROUPS: 'agency_groups',
} as const;

export type BroadcastModuleType = (typeof BROADCAST_MODULE)[keyof typeof BROADCAST_MODULE];

// Sedna mutabakat kayıt durumları (`sedna_bank_recon.status` — DB-saklı, DEĞİŞTİRİLEMEZ).
// Backend karşılığı: `backend/app/constants.py` ReconStatus (iki taraf birebir aynı tutulur).
export const RECON_STATUS = {
	MATCHED: 'matched', // birebir/grup eşleşti (kapalı)
	SEDNA_PENDING: 'sedna_pending', // bankada var, Sedna henüz girmemiş (gecikme)
	SEDNA_MISSING: 'sedna_missing', // bankada var, Sedna dönem içinde girmemiş (gerçek eksik)
	SEDNA_EXTRA: 'sedna_extra', // Sedna'da var, bankada yok (muhtemel hatalı giriş)
	DIRECTION_FLIP: 'direction_flip', // aynı gün + aynı mutlak tutar + TERS yön
	DUPLICATE_SUSPECT: 'duplicate_suspect', // Sedna adedi > banka adedi (mükerrer fiş şüphesi)
	SEDNA_DIFF: 'sedna_diff', // eşleşmiş/korunan yerel kayıtta (çek/cari) Sedna sapması — entity_type'lı
	BALANCE_DIFF: 'balance_diff', // cari net bakiyesi ↔ Sedna 320 hesap bakiyesi farkı (Faz C, entity_type='vendor_balance')
} as const;

export type ReconStatusType = (typeof RECON_STATUS)[keyof typeof RECON_STATUS];
