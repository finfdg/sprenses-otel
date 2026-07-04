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
		// Toplam-dışı: dahili transferler + karşı kayıtla eşleşmiş bilgi satırları
		// (ör. ödenen çek "Ödendi" rozetiyle listede kalır ama para banka bacağında sayılır)
		const isTransfer = item.category_name && TRANSFER_CATEGORIES.has(item.category_name);
		const excludeFromTotals = isTransfer || item.is_matched === true;

		if (item.type === 'income') {
			dayMap[monthKey][dayKey].incomeItems.push(item);
			if (!excludeFromTotals) {
				dayMap[monthKey][dayKey].total_income += amountForBalance;
				groups[monthKey].total_income += amountForBalance;
			}
		} else {
			dayMap[monthKey][dayKey].expenseItems.push(item);
			if (!excludeFromTotals) {
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
			/** true → eşleşmiş bilgi grubu (ör. "Ödenen Çekler") — toplamı gün toplamına girmez */
			matched: boolean;
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
	const groups: Partial<Record<string, Extract<DayRenderUnit, { kind: 'group' }>>> = {};

	for (const item of items) {
		// Tahmini (projeksiyon) kalemler gruplanmaz — her kart kendi "Tahmini" satırında
		// görünür (kesim/son-ödeme tarihleri ve tahmini etiketi kalem üstünde okunur kalsın)
		if (item.is_projected || !GROUPABLE_SOURCES.has(item.source)) {
			units.push({ kind: 'item', item });
			continue;
		}
		const src = item.source as GroupableSource;
		// Eşleşmiş bilgi satırları (ör. ödenen çekler) AYRI bir grupta toplanır
		// ("Ödenen Çekler") — bekleyenlerin grubuna ve gün toplamına karışmaz
		const matched = item.is_matched === true;
		const key = matched ? `${src}:matched` : src;
		let g = groups[key];
		if (!g) {
			g = groups[key] = {
				kind: 'group', source: src, matched, items: [], count: 0,
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

/** Ay anahtarlarını ('YYYY-MM') tarih aralığına çevirir: ilk ayın 1'i → son ayın son günü.
 *  Nakit akım PDF raporu, akordiyonda açık ay(lar)ın kapsamını bununla üretir. */
export function monthKeysToDateRange(keys: string[]): { start: string; end: string } | null {
	if (keys.length === 0) return null;
	const sorted = [...keys].sort();
	const first = sorted[0];
	const last = sorted[sorted.length - 1];
	const [y, m] = last.split('-').map(Number);
	const lastDay = new Date(y, m, 0).getDate(); // ayın son günü (m 1-bazlı → bir sonraki ayın 0. günü)
	return { start: `${first}-01`, end: `${last}-${String(lastDay).padStart(2, '0')}` };
}

// ── Nakit Koruma (runway) projeksiyonu ──────────────────────
export type RunwayFlow = { id: string; date: string; amount_eur: number };
export type RunwayResult = {
	byDay: { day: number; bal: number }[];
	firstNeg: number | null; // bakiyenin ilk negatif olduğu gün-numarası (yoksa null)
	lowVal: number;
	lowDay: number;
	endBal: number;
};

/** Bankadaki nakitten başlayıp [today..monthEnd] arası günlük bakiye projeksiyonu.
 *  `dates` = erteleme override'ı (flowId → 'YYYY-MM-DD'); ay dışına ertelenen ödeme
 *  projeksiyona GİRMEZ (borç gelecek aya taşınır). Saf fonksiyon — component'ten ayrı test edilir. */
export function projectRunway(
	startEur: number,
	inflows: RunwayFlow[],
	outs: RunwayFlow[],
	todayISO: string,
	monthEndISO: string,
	dates: Record<string, string> = {},
): RunwayResult {
	const ym = todayISO.slice(0, 7);
	const startDay = Number(todayISO.slice(8, 10));
	const endDay = Number(monthEndISO.slice(8, 10));
	const dayOf = (iso: string) => Number(iso.slice(8, 10));

	const byDay: { day: number; bal: number }[] = [];
	let bal = startEur;
	for (let d = startDay; d <= endDay; d++) {
		for (const i of inflows) if (i.date.slice(0, 7) === ym && dayOf(i.date) === d) bal += i.amount_eur;
		for (const o of outs) {
			const iso = dates[o.id] || o.date;
			if (iso.slice(0, 7) === ym && dayOf(iso) === d) bal -= o.amount_eur; // ay dışına ertelenen atlanır
		}
		byDay.push({ day: d, bal: Math.round(bal * 100) / 100 });
	}

	let lowVal = Infinity, lowDay = startDay, firstNeg: number | null = null;
	for (const p of byDay) {
		if (p.bal < lowVal) { lowVal = p.bal; lowDay = p.day; }
		if (firstNeg === null && p.bal < 0) firstNeg = p.day;
	}
	if (!byDay.length) lowVal = startEur;
	return { byDay, firstNeg, lowVal, lowDay, endBal: byDay.length ? byDay[byDay.length - 1].bal : startEur };
}

export function getTodayKeys() {
	const today = new Date();
	const currentMonthKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
	const currentDayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
	return { currentMonthKey, currentDayKey };
}
