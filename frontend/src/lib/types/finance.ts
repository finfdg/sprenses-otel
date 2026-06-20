export interface TransactionCategory {
	id: number;
	name: string;
	color: string;
	sort_order: number;
	is_active: boolean;
}

export interface CashFlowItem {
	id: number;
	date: string;
	description: string;
	amount: number;
	type: 'income' | 'expense';
	source: 'bank' | 'check' | 'credit' | 'cc_payment' | 'advance' | 'vendor_payment';
	balance: number | null;
	receipt_no: string | null;
	bank_name: string | null;
	bank_name_inferred?: boolean;
	currency: string;
	iban: string | null;
	account_id: number | null;
	check_no: string | null;
	check_status: string | null;
	vendor_code: string | null;
	category_id: number | null;
	category_name: string | null;
	category_color: string | null;
	tag_note: string | null;
	tag_source: 'auto' | 'manual' | null;
	vendor_id: number | null;
	vendor_name: string | null;
	payment_method: string | null;
	match_number: number | null;
	amount_try: number | null;
	invoice_count: number | null;
}

export interface Summary {
	total_income: number;
	total_expense: number;
	balance: number;
}

export interface DayGroup {
	date: string;
	label: string;
	expenseItems: CashFlowItem[];
	incomeItems: CashFlowItem[];
	total_expense: number;
	total_income: number;
}

export interface MonthGroup {
	key: string;
	label: string;
	days: DayGroup[];
	total_income: number;
	total_expense: number;
	balance: number;
}
