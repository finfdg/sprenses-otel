import { describe, it, expect } from 'vitest';
import { formatCurrency, formatCompact, groupByMonth, getTodayKeys, MONTH_NAMES } from './finance';
import type { CashFlowItem } from '$lib/types/finance';

// ─── Yardımcı: minimal CashFlowItem oluştur ─────────────────
function makeItem(overrides: Partial<CashFlowItem> & { date: string; amount: number; type: 'income' | 'expense' }): CashFlowItem {
	return {
		id: 1,
		description: 'Test',
		balance: null,
		receipt_no: null,
		bank_name: null,
		currency: 'TRY',
		iban: null,
		account_id: null,
		check_no: null,
		check_status: null,
		vendor_code: null,
		category_id: null,
		category_name: null,
		category_color: null,
		tag_note: null,
		tag_source: null,
		vendor_id: null,
		vendor_name: null,
		payment_method: null,
		match_number: null,
		amount_try: null,
		invoice_count: null,
		source: 'bank',
		...overrides,
	};
}

// ─── MONTH_NAMES ─────────────────────────────────────────────

describe('MONTH_NAMES', () => {
	it('12 ay içerir', () => {
		expect(MONTH_NAMES).toHaveLength(12);
	});

	it('Ocak ile başlar, Aralık ile biter', () => {
		expect(MONTH_NAMES[0]).toBe('Ocak');
		expect(MONTH_NAMES[11]).toBe('Aralık');
	});
});

// ─── formatCurrency ──────────────────────────────────────────

describe('formatCurrency', () => {
	it('TRY formatlar (varsayılan)', () => {
		const result = formatCurrency(1234.56);
		// Türkçe TRY formatı: ₺1.234,56
		expect(result).toContain('1.234,56');
	});

	it('sıfır değeri formatlar', () => {
		const result = formatCurrency(0);
		expect(result).toContain('0');
	});

	it('negatif değer formatlar', () => {
		const result = formatCurrency(-500);
		expect(result).toContain('500');
	});

	it('USD para birimi ile formatlar', () => {
		const result = formatCurrency(100, 'USD');
		expect(result).toContain('100');
		expect(result).toContain('$');
	});

	it('EUR para birimi ile formatlar', () => {
		const result = formatCurrency(100, 'EUR');
		expect(result).toContain('100');
		expect(result).toContain('€');
	});
});

// ─── formatCompact ───────────────────────────────────────────

describe('formatCompact', () => {
	it('1000 altı için ondalıklı gösterir', () => {
		const result = formatCompact(999.50);
		expect(result).toContain('999,50');
	});

	it('1000 ve üstü için ondalık göstermez', () => {
		const result = formatCompact(1500.75);
		// maximumFractionDigits: 0 → ondalık yok (locale farklılığı için iki seçenek)
		expect(result).toMatch(/1\.50[01]/);
	});

	it('tam 1000 için ondalık göstermez', () => {
		const result = formatCompact(1000);
		expect(result).toContain('1.000');
		// Ondalık olmamalı
		expect(result).not.toContain(',00');
	});

	it('büyük sayılar için çalışır', () => {
		const result = formatCompact(1250000);
		expect(result).toContain('1.250.000');
	});
});

// ─── groupByMonth ────────────────────────────────────────────

describe('groupByMonth', () => {
	it('boş dizi için boş döner', () => {
		expect(groupByMonth([])).toEqual([]);
	});

	it('tek gelir kaydını doğru gruplar', () => {
		const items = [makeItem({ date: '2025-03-15', amount: 1000, type: 'income' })];
		const result = groupByMonth(items);

		expect(result).toHaveLength(1);
		expect(result[0].key).toBe('2025-03');
		expect(result[0].label).toBe('Mart 2025');
		expect(result[0].total_income).toBe(1000);
		expect(result[0].total_expense).toBe(0);
		expect(result[0].balance).toBe(1000);
	});

	it('tek gider kaydını doğru gruplar', () => {
		const items = [makeItem({ date: '2025-06-10', amount: 500, type: 'expense' })];
		const result = groupByMonth(items);

		expect(result).toHaveLength(1);
		expect(result[0].total_expense).toBe(500);
		expect(result[0].total_income).toBe(0);
		expect(result[0].balance).toBe(-500);
	});

	it('aynı ayda gelir ve gideri toplar', () => {
		const items = [
			makeItem({ id: 1, date: '2025-01-05', amount: 3000, type: 'income' }),
			makeItem({ id: 2, date: '2025-01-20', amount: 1200, type: 'expense' }),
		];
		const result = groupByMonth(items);

		expect(result).toHaveLength(1);
		expect(result[0].total_income).toBe(3000);
		expect(result[0].total_expense).toBe(1200);
		expect(result[0].balance).toBe(1800);
	});

	it('farklı ayları ayrı gruplar ve sıralar', () => {
		const items = [
			makeItem({ id: 1, date: '2025-03-01', amount: 100, type: 'income' }),
			makeItem({ id: 2, date: '2025-01-15', amount: 200, type: 'expense' }),
		];
		const result = groupByMonth(items);

		expect(result).toHaveLength(2);
		expect(result[0].key).toBe('2025-01');
		expect(result[1].key).toBe('2025-03');
	});

	it('aynı gündeki kayıtları aynı DayGroup altında toplar', () => {
		const items = [
			makeItem({ id: 1, date: '2025-05-10', amount: 100, type: 'income' }),
			makeItem({ id: 2, date: '2025-05-10', amount: 50, type: 'expense' }),
		];
		const result = groupByMonth(items);

		expect(result).toHaveLength(1);
		expect(result[0].days).toHaveLength(1);
		expect(result[0].days[0].incomeItems).toHaveLength(1);
		expect(result[0].days[0].expenseItems).toHaveLength(1);
	});

	it('günleri tarih sırasına göre sıralar', () => {
		const items = [
			makeItem({ id: 1, date: '2025-02-20', amount: 100, type: 'income' }),
			makeItem({ id: 2, date: '2025-02-05', amount: 200, type: 'expense' }),
			makeItem({ id: 3, date: '2025-02-12', amount: 50, type: 'income' }),
		];
		const result = groupByMonth(items);

		expect(result[0].days).toHaveLength(3);
		expect(result[0].days[0].date).toBe('2025-02-05');
		expect(result[0].days[1].date).toBe('2025-02-12');
		expect(result[0].days[2].date).toBe('2025-02-20');
	});

	it('transfer kategorilerini (Virman, Döviz Satım, İade) toplamdan hariç tutar', () => {
		const items = [
			makeItem({ id: 1, date: '2025-04-01', amount: 5000, type: 'income', category_name: 'Virman' }),
			makeItem({ id: 2, date: '2025-04-01', amount: 2000, type: 'income', category_name: null }),
			makeItem({ id: 3, date: '2025-04-05', amount: 1000, type: 'expense', category_name: 'Döviz Satım' }),
			makeItem({ id: 4, date: '2025-04-05', amount: 300, type: 'expense', category_name: 'İade' }),
		];
		const result = groupByMonth(items);

		expect(result[0].total_income).toBe(2000);  // Virman hariç
		expect(result[0].total_expense).toBe(0);     // Döviz Satım ve İade hariç
		expect(result[0].balance).toBe(2000);
	});

	it('transfer kaydı DayGroup items içinde yer alır ama toplama dahil olmaz', () => {
		const items = [
			makeItem({ id: 1, date: '2025-07-01', amount: 10000, type: 'income', category_name: 'Virman' }),
		];
		const result = groupByMonth(items);

		expect(result[0].days[0].incomeItems).toHaveLength(1);
		expect(result[0].days[0].total_income).toBe(0);
	});
});

// ─── getTodayKeys ────────────────────────────────────────────

describe('getTodayKeys', () => {
	it('bugünün ay ve gün anahtarlarını döndürür', () => {
		const { currentMonthKey, currentDayKey } = getTodayKeys();
		const today = new Date();
		const expectedMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
		const expectedDay = `${expectedMonth}-${String(today.getDate()).padStart(2, '0')}`;

		expect(currentMonthKey).toBe(expectedMonth);
		expect(currentDayKey).toBe(expectedDay);
	});

	it('YYYY-MM formatında ay anahtarı döndürür', () => {
		const { currentMonthKey } = getTodayKeys();
		expect(currentMonthKey).toMatch(/^\d{4}-\d{2}$/);
	});

	it('YYYY-MM-DD formatında gün anahtarı döndürür', () => {
		const { currentDayKey } = getTodayKeys();
		expect(currentDayKey).toMatch(/^\d{4}-\d{2}-\d{2}$/);
	});
});
