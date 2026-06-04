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
	// Finans / satış / onay / kalite — gerçek zamanlı veri akışı
	FINANCE_UPDATED: 'finance_updated',
	SALES_UPDATED: 'sales_updated',
	APPROVAL_UPDATED: 'approval_updated',
	APPROVAL_STATUS_CHANGED: 'approval_status_changed',
	BANK_STATEMENT_UPLOADED: 'bank_statement_uploaded',
	QUALITY_FORM_UPDATE: 'quality_form_update',
	PERMISSION_CHANGED: 'permission_changed',

	// Oturum / bağlantı
	CONNECTED: 'connected',
	FORCE_LOGOUT: 'force_logout',
	SESSION_EXPIRED: 'session_expired',
	USER_STATUS: 'user_status',

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
	// Satış alanı
	HOTEL_RESERVATION: 'hotel_reservation',
	ROOM_TYPES: 'room_types',
	AGENCY_GROUPS: 'agency_groups',
} as const;

export type BroadcastModuleType = (typeof BROADCAST_MODULE)[keyof typeof BROADCAST_MODULE];
