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

// Gün içi kaynak gruplaması: çekler, cari ödemeleri, kredi taksitleri (leasing dahil —
// leasing bir kredi ürün tipidir, source='credit' gelir) ve KK borç ödemeleri tek katlanabilir
// kartta toplanır (2+ kayıt varsa). Diğer kaynaklar birebir geçer; grup ilk üyesinin konumunda
// görünür (sıra korunur).
export type GroupableSource = 'check' | 'vendor_payment' | 'credit' | 'cc_payment';

export type DayRenderUnit =
	| { kind: 'item'; item: CashFlowItem }
	| {
			kind: 'group';
			source: GroupableSource;
			items: CashFlowItem[];
			count: number;
			totalTry: number;
			/** Tüm üyeler aynı (TRY-dışı) para birimindeyse native toplam; karışıksa null */
			nativeTotal: number | null;
			currency: string | null;
	  };

const GROUPABLE_SOURCES = new Set(['check', 'vendor_payment', 'credit', 'cc_payment']);

export function groupDaySourceItems(items: CashFlowItem[]): DayRenderUnit[] {
	const units: DayRenderUnit[] = [];
	const groups: Partial<Record<GroupableSource, Extract<DayRenderUnit, { kind: 'group' }>>> = {};

	for (const item of items) {
		if (!GROUPABLE_SOURCES.has(item.source)) {
			units.push({ kind: 'item', item });
			continue;
		}
		const src = item.source as GroupableSource;
		let g = groups[src];
		if (!g) {
			g = groups[src] = {
				kind: 'group', source: src, items: [], count: 0,
				totalTry: 0, nativeTotal: 0, currency: null,
			};
			units.push(g); // grup, ilk üyesinin konumuna yerleşir
		}
		g.items.push(item);
		g.count++;
		g.totalTry += item.currency === 'TRY' ? item.amount : (item.amount_try ?? 0);
		if (g.nativeTotal !== null) {
			if (g.currency === null) g.currency = item.currency;
			if (g.currency === item.currency) g.nativeTotal += item.amount;
			else { g.nativeTotal = null; g.currency = null; } // karışık para birimi → TL göster
		}
	}

	// Tek kayıtlı "grup"ları düz item'a indir (gruplamaya değmez) + toplamları yuvarla
	return units.map((u) =>
		u.kind === 'group' && u.count === 1 ? ({ kind: 'item', item: u.items[0] } as DayRenderUnit) : u
	).map((u) => {
		if (u.kind === 'group') {
			u.totalTry = Math.round(u.totalTry * 100) / 100;
			if (u.nativeTotal !== null) u.nativeTotal = Math.round(u.nativeTotal * 100) / 100;
			if (u.currency === 'TRY') { u.nativeTotal = null; u.currency = null; } // TRY'de native ayrıca gösterilmez
		}
		return u;
	});
}

export function getTodayKeys() {
	const today = new Date();
	const currentMonthKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
	const currentDayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
	return { currentMonthKey, currentDayKey };
}
