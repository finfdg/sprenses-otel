export interface BankAccount {
	id: number;
	bank_name: string;
	branch_name: string | null;
	account_no: string | null;
	iban: string;
	currency: string;
	holder_name: string | null;
	blocked_amount: number | null;
	is_active: boolean;
	created_at: string;
	transaction_count: number;
	last_balance: number | null;
	last_statement_date: string | null;
}

export interface BankStatement {
	id: number;
	account_id: number;
	file_name: string;
	file_type: string;
	period_start: string | null;
	period_end: string | null;
	total_transactions: number;
	new_transactions: number;
	skipped_transactions: number;
	uploaded_at: string;
}

export interface BankTransaction {
	id: number;
	account_id: number;
	date: string;
	receipt_no: string | null;
	description: string;
	amount: number;
	balance: number | null;
	type: 'income' | 'expense';
	source?: 'statement' | 'manual';
}

export interface UploadResult {
	statement_id: number;
	file_name: string;
	total_transactions: number;
	new_transactions: number;
	skipped_transactions: number;
	account_iban: string | null;
	account_currency: string | null;
}
