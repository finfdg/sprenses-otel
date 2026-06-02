// Nakit Akım veri cache'i — sayfa navigasyonlarında tekrar yüklemeyi önler
// WS finance_updated event'i ile otomatik güncellenir

import { api } from '$lib/api';
import type { CashFlowItem, TransactionCategory } from '$lib/types/finance';

/** Mevcut yılın 1 Ocak'ı (YYYY-01-01) — varsayılan filtre başlangıcı */
function getDefaultStartDate(): string {
	return `${new Date().getFullYear()}-01-01`;
}

export const cashFlowCache = $state<{
	items: CashFlowItem[];
	categories: TransactionCategory[];
	untaggedCount: number;
	eurBalances: any;
	loaded: boolean;
	loading: boolean;
	/** Son yükleme zamanı (ms) — stale kontrolü için */
	lastFetchedAt: number;
	/** Backend'deki toplam kayıt sayısı (truncation uyarısı için) */
	totalCount: number;
	/** Aktif filtre parametreleri */
	filters: {
		startDate: string;
		endDate: string;
		search: string;
	};
}>({
	items: [],
	categories: [],
	untaggedCount: 0,
	eurBalances: null,
	loaded: false,
	loading: false,
	lastFetchedAt: 0,
	totalCount: 0,
	filters: { startDate: getDefaultStartDate(), endDate: '', search: '' },
});

/** Cache'in geçersiz sayılacağı süre (ms) — 5 dakika */
const STALE_MS = 5 * 60 * 1000;

function isStale(): boolean {
	return Date.now() - cashFlowCache.lastFetchedAt > STALE_MS;
}

export async function loadCashFlowItems(force = false) {
	if (!force && cashFlowCache.loaded && !isStale()) return;
	cashFlowCache.loading = true;
	try {
		const params = new URLSearchParams({ page_size: '2000' });
		const { startDate, endDate, search } = cashFlowCache.filters;
		if (startDate) params.set('start_date', startDate);
		if (endDate) params.set('end_date', endDate);
		if (search) params.set('search', search);

		const res = await api.get<any>(`/finance/cash-flow/?${params}`);
		cashFlowCache.items = res.items ?? res;
		cashFlowCache.totalCount = res.total ?? cashFlowCache.items.length;
		cashFlowCache.loaded = true;
		cashFlowCache.lastFetchedAt = Date.now();
	} catch (err) {
		console.error('Veri yükleme hatası:', err);
		throw err;
	} finally {
		cashFlowCache.loading = false;
	}
}

/** Filtreleri güncelle ve verileri yeniden yükle */
export async function applyCashFlowFilters(filters: { startDate?: string; endDate?: string; search?: string }) {
	if (filters.startDate !== undefined) cashFlowCache.filters.startDate = filters.startDate;
	if (filters.endDate !== undefined) cashFlowCache.filters.endDate = filters.endDate;
	if (filters.search !== undefined) cashFlowCache.filters.search = filters.search;
	await loadCashFlowItems(true);
}

export async function loadCashFlowCategories(force = false) {
	if (!force && cashFlowCache.categories.length > 0 && !isStale()) return;
	try {
		cashFlowCache.categories = await api.get<TransactionCategory[]>('/finance/tags/categories');
	} catch (err) {
		console.error('Kategori yükleme hatası:', err);
	}
}

export async function loadCashFlowUntaggedCount() {
	try {
		const res = await api.get<{ count: number }>('/finance/tags/untagged-count');
		cashFlowCache.untaggedCount = res.count;
	} catch (err) {
		console.error('Etiketsiz sayısı hatası:', err);
	}
}

export async function loadCashFlowEurBalances() {
	try {
		cashFlowCache.eurBalances = await api.get('/finance/cash-flow/eur-balances');
	} catch (err) {
		console.error('EUR bakiye hatası:', err);
	}
}

/** Tüm verileri yükle (ilk yükleme veya force refresh) */
export async function loadAllCashFlow(force = false) {
	await Promise.all([
		loadCashFlowItems(force),
		loadCashFlowCategories(force),
		loadCashFlowUntaggedCount(),
		loadCashFlowEurBalances(),
	]);
}

/** WS event sonrası hafif güncelleme (items'a dokunma — scroll koruması) */
export async function refreshCashFlowLight() {
	await Promise.all([
		loadCashFlowUntaggedCount(),
		loadCashFlowEurBalances(),
	]);
}

/** WS event sonrası tam güncelleme */
export async function refreshCashFlowFull() {
	await Promise.all([
		loadCashFlowItems(true),
		loadCashFlowUntaggedCount(),
		loadCashFlowEurBalances(),
	]);
}

/** Cache'i sıfırla (logout vb.) */
export function invalidateCashFlowCache() {
	cashFlowCache.items = [];
	cashFlowCache.categories = [];
	cashFlowCache.untaggedCount = 0;
	cashFlowCache.eurBalances = null;
	cashFlowCache.loaded = false;
	cashFlowCache.loading = false;
	cashFlowCache.lastFetchedAt = 0;
	cashFlowCache.totalCount = 0;
	cashFlowCache.filters = { startDate: getDefaultStartDate(), endDate: '', search: '' };
}
