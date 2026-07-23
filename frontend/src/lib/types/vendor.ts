export interface Vendor {
	id: number;
	hesap_kodu: string;
	hesap_adi: string;
	payment_days: number;
	status: string;
	total_borc: number;
	total_alacak: number;
	bakiye: number;
	transaction_count: number;
	unmatched_count: number;
	/** NET vadesi geçmiş (FIFO) — liste çipleri + Gecikmiş sıralaması */
	overdue: number;
	overdue_count: number;
}

export interface VendorDetail {
	id: number;
	hesap_kodu: string;
	hesap_adi: string;
	payment_days: number;
	status: string;
	total_borc: number;
	total_alacak: number;
	bakiye: number;
	contact_person: string | null;
	phone: string | null;
	email: string | null;
	overdue: number;
	overdue_count: number;
	last_payment_amount: number | null;
	last_payment_date: string | null;
}

export interface VendorNote {
	id: number;
	vendor_id: number;
	text: string;
	author_name: string | null;
	done: boolean;
	created_at: string;
	updated_at: string;
}

export interface VendorNoteWithVendor extends VendorNote {
	vendor_name: string;
	vendor_code: string;
}

export interface VendorTransaction {
	id: number;
	vendor_id: number;
	date: string;
	evrak_no: string | null;
	transaction_type: string | null;
	fis_no: string | null;
	description: string | null;
	borc: number;
	alacak: number;
	bakiye: number | null;
	payment_due_date: string | null;
	match_number: number | null;
	payment_method: string | null;
	department_id: number | null;
	department_name: string | null;
	budget_category_id: number | null;
	budget_category_name: string | null;
	dept_status: string | null;
	dept_assigned_by_name: string | null;
	dept_assigned_at: string | null;
	dept_rejection_note: string | null;
	/** Fatura satırında FIFO sonrası kalan (null = ödeme satırı; 0 = kapanmış) */
	fifo_remaining?: number | null;
}

// ─── Analitik görünümler (Aylık Bakiye / Yıllık Ciro) ───

export interface MonthlyFifoRow {
	vendor_id: number;
	hesap_kodu: string;
	hesap_adi: string;
	invoiced: number;
	closed: number;
	remaining: number;
}

export interface MonthlyPeriodRow {
	vendor_id: number;
	hesap_kodu: string;
	hesap_adi: string;
	total_borc: number;
	total_alacak: number;
	balance: number;
}

export interface YearlyTurnoverRow {
	vendor_id: number;
	hesap_kodu: string;
	hesap_adi: string;
	monthly: number[];
	invoice_count: number;
	turnover: number;
}

export interface VendorUpload {
	id: number;
	file_name: string;
	total_vendors: number;
	total_transactions: number;
	new_transactions: number;
	skipped_transactions: number;
	uploaded_by: number | null;
	uploader_name: string | null;
	uploaded_at: string;
}

export interface RemovalCandidate {
	id: number;
	vendor_id: number;
	hesap_kodu: string;
	hesap_adi: string;
	date: string;
	evrak_no: string | null;
	transaction_type: string | null;
	description: string | null;
	borc: number;
	alacak: number;
	bakiye: number | null;
}

export interface VendorUploadResult {
	upload_id: number;
	file_name: string;
	total_vendors: number;
	total_transactions: number;
	new_transactions: number;
	skipped_transactions: number;
	removal_candidates: RemovalCandidate[];
}

export interface BulkDeleteResult {
	deleted: number;
	skipped: number;
	skipped_reasons: string[];
}

export interface PaymentScheduleItem {
	vendor_id: number;
	hesap_kodu: string;
	hesap_adi: string;
	evrak_no: string | null;
	transaction_type: string | null;
	invoice_date: string;
	payment_due_date: string;
	amount: number;
}

export interface WeeklyPaymentGroup {
	friday_date: string;
	total_amount: number;
	items: PaymentScheduleItem[];
}
