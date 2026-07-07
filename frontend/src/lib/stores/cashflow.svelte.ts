// Nakit Akım veri cache'i — sayfa navigasyonlarında tekrar yüklemeyi önler
// WS finance_updated event'i ile otomatik güncellenir

import { api } from '$lib/api';
import { showToast } from '$lib/stores/toast.svelte';
import { onWsEvent } from '$lib/stores/websocket.svelte';
import { WS_EVENT } from '$lib/constants/realtime';
import type { CashFlowItem, TransactionCategory } from '$lib/types/finance';

/** Mevcut yılın 1 Ocak'ı (YYYY-01-01) — varsayılan filtre başlangıcı */
function getDefaultStartDate(): string {
	return `${new Date().getFullYear()}-01-01`;
}

export const cashFlowCache = $state<{
	items: CashFlowItem[];
	/** Tahmini kredi kartı ekstresi kalemleri (yüklenmemiş aylar) — okuma-anında üretilir */
	projectedItems: CashFlowItem[];
	categories: TransactionCategory[];
	untaggedCount: number;
	eurBalances: any;
	loaded: boolean;
	loading: boolean;
	/** Son yükleme zamanı (ms) — stale kontrolü için */
	lastFetchedAt: number;
	/** eurBalances'ın son yükleme zamanı (ms) — items'tan bağımsız tazelik takibi */
	eurBalancesFetchedAt: number;
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
	projectedItems: [],
	categories: [],
	untaggedCount: 0,
	eurBalances: null,
	loaded: false,
	loading: false,
	lastFetchedAt: 0,
	eurBalancesFetchedAt: 0,
	totalCount: 0,
	filters: { startDate: getDefaultStartDate(), endDate: '', search: '' },
});

/** Cache'in geçersiz sayılacağı süre (ms) — 5 dakika */
const STALE_MS = 5 * 60 * 1000;

function isStale(): boolean {
	return Date.now() - cashFlowCache.lastFetchedAt > STALE_MS;
}

/** eurBalances yeniden yüklenmeli mi? (hiç yüklenmemiş, WS ile geçersizlenmiş veya TTL aşılmış) */
export function isEurBalancesStale(): boolean {
	return cashFlowCache.eurBalances === null || Date.now() - cashFlowCache.eurBalancesFetchedAt > STALE_MS;
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
		cashFlowCache.eurBalancesFetchedAt = Date.now();
	} catch (err) {
		// Grafik (RunwayChart) + gün bakiyeleri bu veriden beslenir — sessiz kalırsa
		// kullanıcı bayat eğriye bakar (2026-07-07: rate-limit 429'ları fark edilmedi)
		console.error('EUR bakiye hatası:', err);
		showToast('Nakit projeksiyon bakiyeleri yüklenemedi', 'error');
	}
}

/** Tahmini kredi kartı ekstresi kalemleri (cari ay = limit, ileri aylar = 0) */
export async function loadCashFlowProjections() {
	try {
		const res = await api.get<{ items: CashFlowItem[] }>('/finance/cash-flow/cc-projections');
		cashFlowCache.projectedItems = res.items ?? [];
	} catch (err) {
		console.error('Kredi kartı projeksiyon hatası:', err);
	}
}

/** Tüm verileri yükle (ilk yükleme veya force refresh) */
export async function loadAllCashFlow(force = false) {
	await Promise.all([
		loadCashFlowItems(force),
		loadCashFlowCategories(force),
		loadCashFlowUntaggedCount(),
		loadCashFlowEurBalances(),
		loadCashFlowProjections(),
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
		loadCashFlowProjections(),
	]);
}

/** Cache'i sıfırla (logout vb.) */
export function invalidateCashFlowCache() {
	cashFlowCache.items = [];
	cashFlowCache.projectedItems = [];
	cashFlowCache.categories = [];
	cashFlowCache.untaggedCount = 0;
	cashFlowCache.eurBalances = null;
	cashFlowCache.loaded = false;
	cashFlowCache.loading = false;
	cashFlowCache.lastFetchedAt = 0;
	cashFlowCache.eurBalancesFetchedAt = 0;
	cashFlowCache.totalCount = 0;
	cashFlowCache.filters = { startDate: getDefaultStartDate(), endDate: '', search: '' };
}

// ─── WS ile store-seviyesi geçersizleme (sayfa bağımsız) ───
// finance_updated event'i yalnızca MOUNT edilmiş sayfaların handler'larında tüketilir; kullanıcı
// o sırada başka sayfadaysa (ör. Bankalar'da ekstre yüklerken) event kaybolur ve Panel'e dönüşte
// mount guard'ları dolu-ama-bayat cache'i taze sanırdı (belirti 2026-07-07: ekstre sonrası Panel
// RunwayChart eski bakiyeyi çizdi, F5'e kadar düzelmedi). Burada fetch YAPILMAZ — yalnız tazelik
// damgaları sıfırlanır; bir sonraki mount/isStale kontrolü veriyi kendisi yeniden çeker. Mount'lu
// sayfaların kendi WS handler'ları (refreshCashFlowLight/Full, CashFlowTAccount.refreshData)
// canlı tazelemeyi zaten yapar; bu abonelik onlara istek eklemez.
if (typeof window !== 'undefined') {
	onWsEvent(WS_EVENT.FINANCE_UPDATED, () => {
		cashFlowCache.lastFetchedAt = 0;
		cashFlowCache.eurBalancesFetchedAt = 0;
	});
}
