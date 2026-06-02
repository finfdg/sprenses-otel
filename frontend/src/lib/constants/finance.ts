/**
 * Finans modülü sabitleri — backend ile senkronize tutulmalıdır.
 * Backend karşılığı: app/utils/finance_event_service.py (source_type'lar)
 */

// ─── Kaynak Tipleri (finance_events.source_type) ─────────────────────────

export const SOURCE_BANK = 'bank' as const;
export const SOURCE_CHECK = 'check' as const;
export const SOURCE_CREDIT = 'credit' as const;
export const SOURCE_CC_PAYMENT = 'cc_payment' as const;
export const SOURCE_ADVANCE = 'advance' as const;
export const SOURCE_VENDOR_PAYMENT = 'vendor_payment' as const;
export const SOURCE_CASH_FLOW = 'cash_flow' as const;

export type SourceType =
	| typeof SOURCE_BANK
	| typeof SOURCE_CHECK
	| typeof SOURCE_CREDIT
	| typeof SOURCE_CC_PAYMENT
	| typeof SOURCE_ADVANCE
	| typeof SOURCE_VENDOR_PAYMENT
	| typeof SOURCE_CASH_FLOW;

// ─── İşlem Yönü ─────────────────────────────────────────────────────────

export const TYPE_INCOME = 'income' as const;
export const TYPE_EXPENSE = 'expense' as const;

export type TransactionDirection = typeof TYPE_INCOME | typeof TYPE_EXPENSE;

// ─── Transfer Kategorileri (gelir/gider toplamlarından hariç tutulan) ────

export const TRANSFER_CATEGORIES = new Set(['Virman', 'Döviz Satım', 'İade']);

// ─── Ödeme Yöntemleri ───────────────────────────────────────────────────

export const PM_HAVALE_EFT = 'havale_eft' as const;
export const PM_FAST = 'fast' as const;
export const PM_VIRMAN = 'virman' as const;
export const PM_CEK = 'cek' as const;
export const PM_KREDI_KARTI = 'kredi_karti' as const;
export const PM_OTOMATIK_ODEME = 'otomatik_odeme' as const;
export const PM_NAKIT = 'nakit' as const;
export const PM_KREDI = 'kredi' as const;
export const PM_CARI = 'cari' as const;
export const PM_SENET = 'senet' as const;
export const PM_DIGER = 'diger' as const;
export const PM_DEVIR = 'devir' as const;

export type PaymentMethod =
	| typeof PM_HAVALE_EFT
	| typeof PM_FAST
	| typeof PM_VIRMAN
	| typeof PM_CEK
	| typeof PM_KREDI_KARTI
	| typeof PM_OTOMATIK_ODEME
	| typeof PM_NAKIT
	| typeof PM_KREDI
	| typeof PM_CARI
	| typeof PM_SENET
	| typeof PM_DIGER
	| typeof PM_DEVIR;

/** Ödeme yöntemi etiketleri (UI'da gösterilen Türkçe adlar) */
export const PAYMENT_METHOD_LABELS: Record<string, string> = {
	[PM_HAVALE_EFT]: 'Havale / EFT',
	[PM_FAST]: 'FAST',
	[PM_VIRMAN]: 'Virman',
	[PM_CEK]: 'Çek',
	[PM_KREDI_KARTI]: 'Kredi Kartı',
	[PM_OTOMATIK_ODEME]: 'Otomatik Ödeme',
	[PM_NAKIT]: 'Nakit',
	[PM_KREDI]: 'Kredi',
	[PM_CARI]: 'Cari',
	[PM_SENET]: 'Senet',
	[PM_DIGER]: 'Diğer',
	[PM_DEVIR]: 'Devir',
};

// ─── Etiket Kaynağı ─────────────────────────────────────────────────────

export const TAG_AUTO = 'auto' as const;
export const TAG_MANUAL = 'manual' as const;

export type TagSource = typeof TAG_AUTO | typeof TAG_MANUAL | null;

// ─── Avans Durumları ────────────────────────────────────────────────────

export const STATUS_PENDING = 'pending' as const;
export const STATUS_RECEIVED = 'received' as const;
export const STATUS_CANCELLED = 'cancelled' as const;
export const STATUS_PAID = 'paid' as const;
export const STATUS_ACTIVE = 'active' as const;
export const STATUS_CLOSED = 'closed' as const;

// ─── Kredi Ürün Tipleri ─────────────────────────────────────────────────

export const CREDIT_KREDI_KARTI = 'kredi_karti' as const;
export const CREDIT_KMH = 'kmh' as const;
export const CREDIT_BCH = 'bch' as const;
export const CREDIT_SPOT = 'spot_kredi' as const;
export const CREDIT_TAKSITLI = 'taksitli_kredi' as const;
export const CREDIT_LEASING = 'leasing' as const;

export type CreditProductType =
	| typeof CREDIT_KREDI_KARTI
	| typeof CREDIT_KMH
	| typeof CREDIT_BCH
	| typeof CREDIT_SPOT
	| typeof CREDIT_TAKSITLI
	| typeof CREDIT_LEASING;

/** Kredi ürün tipi etiketleri */
export const CREDIT_TYPE_LABELS: Record<string, string> = {
	[CREDIT_KREDI_KARTI]: 'Kredi Kartı',
	[CREDIT_KMH]: 'KMH',
	[CREDIT_BCH]: 'BCH',
	[CREDIT_SPOT]: 'Spot Kredi',
	[CREDIT_TAKSITLI]: 'Taksitli Kredi',
	[CREDIT_LEASING]: 'Leasing',
};

// ─── Para Birimleri ─────────────────────────────────────────────────────

export const CURRENCY_TRY = 'TRY' as const;
export const CURRENCY_EUR = 'EUR' as const;
export const CURRENCY_USD = 'USD' as const;
export const CURRENCY_GBP = 'GBP' as const;

export type CurrencyCode = typeof CURRENCY_EUR | typeof CURRENCY_USD | typeof CURRENCY_GBP;
