import type { CashFlowItem, MonthGroup, DayGroup } from '$lib/types/finance';

export const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

export function formatCurrency(amount: number, currency: string = 'TRY'): string {
	return new Intl.NumberFormat('tr-TR', { style: 'currency', currency }).format(amount);
}

export function formatCompact(amount: number, currency: string = 'TRY'): string {
	if (amount >= 1000) {
		return new Intl.NumberFormat('tr-TR', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount);
	}
	return formatCurrency(amount, currency);
}

// Dahili transfer kategorileri — gelir/gider toplamlarından hariç tutulur
const TRANSFER_CATEGORIES = new Set(['Virman', 'Döviz Satım', 'İade']);

export function groupByMonth(items: CashFlowItem[]): MonthGroup[] {
	const groups: Record<string, MonthGroup> = {};
	const dayMap: Record<string, Record<string, DayGroup>> = {};

	for (const item of items) {
		const d = new Date(item.date + 'T00:00:00');
		const monthKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
		const dayKey = item.date;

		if (!groups[monthKey]) {
			groups[monthKey] = {
				key: monthKey,
				label: `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`,
				days: [],
				total_income: 0,
				total_expense: 0,
				balance: 0,
			};
			dayMap[monthKey] = {};
		}

		if (!dayMap[monthKey][dayKey]) {
			dayMap[monthKey][dayKey] = {
				date: dayKey,
				label: d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', weekday: 'short' }),
				expenseItems: [],
				incomeItems: [],
				total_expense: 0,
				total_income: 0,
			};
		}

		const amountForBalance = item.amount;
		const isTransfer = item.category_name && TRANSFER_CATEGORIES.has(item.category_name);

		if (item.type === 'income') {
			dayMap[monthKey][dayKey].incomeItems.push(item);
			if (!isTransfer) {
				dayMap[monthKey][dayKey].total_income += amountForBalance;
				groups[monthKey].total_income += amountForBalance;
			}
		} else {
			dayMap[monthKey][dayKey].expenseItems.push(item);
			if (!isTransfer) {
				dayMap[monthKey][dayKey].total_expense += amountForBalance;
				groups[monthKey].total_expense += amountForBalance;
			}
		}
		groups[monthKey].balance = groups[monthKey].total_income - groups[monthKey].total_expense;
	}

	for (const monthKey of Object.keys(groups)) {
		groups[monthKey].days = Object.values(dayMap[monthKey]).sort((a, b) => a.date.localeCompare(b.date));
	}

	return Object.values(groups).sort((a, b) => a.key.localeCompare(b.key));
}

export function getTodayKeys() {
	const today = new Date();
	const currentMonthKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
	const currentDayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
	return { currentMonthKey, currentDayKey };
}
