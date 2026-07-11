<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Input from '$lib/components/Input.svelte';
	import Button from '$lib/components/Button.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import PdfPreviewModal from '$lib/components/PdfPreviewModal.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { Filter, AlertTriangle, Receipt, Check, FileDown, RefreshCw, Link2, ArrowRight, X, Hourglass, Target } from 'lucide-svelte';
	import {
		cashFlowCache,
		loadAllCashFlow,
		loadCashFlowItems,
		loadCashFlowUntaggedCount,
		loadCashFlowEurBalances,
		refreshCashFlowLight,
		refreshCashFlowFull,
		applyCashFlowFilters,
	} from '$lib/stores/cashflow.svelte';
	import CashFlowSummaryCards from '$lib/components/finance/CashFlowSummaryCards.svelte';
	import CashFlowFilterBar from '$lib/components/finance/CashFlowFilterBar.svelte';
	import MonthAccordion from '$lib/components/finance/MonthAccordion.svelte';
	import type { CashFlowItem as CashFlowItemType, TransactionCategory } from '$lib/types/finance';
	import { groupByMonth, getTodayKeys, monthKeysToDateRange } from '$lib/utils/finance';

	// Eşleşme önerisi hedef türü sözlüğü (backend target_source_type)
	const SUG_TYPE_LABELS: Record<string, string> = {
		check: 'Çek', credit: 'Kredi', advance: 'Avans', vendor_payment: 'Cari',
		tax: 'Vergi', sgk: 'SGK', withholding: 'Stopaj', salary: 'Maaş', rent_expense: 'Kira',
	};
	const CUR_SYMBOL: Record<string, string> = { TRY: '₺', TL: '₺', EUR: '€', USD: '$', GBP: '£' };

	interface MatchSuggestion {
		id: number;
		score: number;
		target_source_type: string;
		target_source_id: number;
		target_description: string | null;
		target_date: string | null;
		amount: number;
		currency: string | null;
		bank_transaction_id: number;
		bank_date: string | null;
		bank_amount: number | null;
		bank_description: string | null;
	}

	// $state — data
	let autoTagging = $state(false);
	let rematching = $state(false);
	let pdfLoading = $state(false);

	// Eşleşme önerileri paneli
	let suggestionsTotal = $state(0);
	let showSuggestions = $state(false);
	let sugItems = $state<MatchSuggestion[]>([]);
	let sugLoading = $state(false);
	let sugPage = $state(1);
	let sugPageSize = $state(25);
	let sugTotal = $state(0);
	let sugConfirm = $state<{ show: boolean; title: string; message: string; confirmText: string; danger: boolean; onConfirm: () => void | Promise<void> }>({
		show: false, title: '', message: '', confirmText: 'Onayla', danger: false, onConfirm: () => {},
	});

	// Yaşlananlar paneli (Faz 3 #21) — vadesi geçmiş açık tahminler + etiketsiz banka hareketleri
	interface AgingData {
		days: number;
		cutoff: string;
		stale_forecasts: {
			by_source: Record<string, { label: string; count: number; total_try: number; oldest_date: string | null }>;
			total_count: number;
			items: { source_type: string; source_id: number; event_date: string; amount: number; currency: string | null; description: string | null; days_overdue: number }[];
		};
		unmatched_bank: {
			count: number;
			total: number;
			items: { id: number; date: string; amount: number; description: string | null; days_old: number }[];
		};
	}
	let agingTotal = $state(0);
	let showAging = $state(false);
	let agingData = $state<AgingData | null>(null);
	let agingLoading = $state(false);
	let agingDays = $state(7);

	// Tahmin doğruluğu paneli (Faz 3 #25) — tahmin ↔ gerçekleşme tarih sapması
	interface AccuracyData {
		months: number;
		total_matches: number;
		by_type: { source_type: string; label: string; count: number; median_delay_days: number; avg_delay_days: number }[];
		by_vendor: { vendor_id: number; vendor_name: string; count: number; median_delay_days: number; current_payment_days: number; suggested_payment_days: number | null }[];
	}
	let showAccuracy = $state(false);
	let accuracyData = $state<AccuracyData | null>(null);
	let accuracyLoading = $state(false);
	let accuracyMonths = $state(6);

	// Cari eşleştirme modu (cariler sayfasından gelince)
	let matchMode = $state(false);
	let matchDate = $state<string | null>(null);
	let matchAmount = $state<number | null>(null);
	let matchVendorName = $state<string | null>(null);
	let matchVtxId = $state<number | null>(null);
	let matchVendorId = $state<number | null>(null);

	// KK/Kredi eşleştirme modu (CC/credit satırından başlar, banka satırı seçilir)
	let ccMatchMode = $state(false);
	let ccMatchStatementId = $state<number | null>(null);
	let ccMatchType = $state<'cc' | 'credit'>('cc');
	let ccMatchDescription = $state('');
	let ccMatchAmount = $state(0);

	// Filtre state
	let tagFilter = $state<'all' | 'untagged' | number>('all');
	let paymentMethodFilter = $state<string | null>(null);
	let showDateFilter = $state(false);
	let filterStartDate = $state(cashFlowCache.filters.startDate);
	let filterEndDate = $state('');
	let filterSearch = $state('');
	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	// Truncation uyarısı
	let isTruncated = $derived(cashFlowCache.totalCount > cashFlowCache.items.length);

	// MonthAccordion referansı — filtre değiştiğinde sıfırlamak için
	let accordionRef: MonthAccordion | undefined = $state();

	// PDF önizleme modalı (iOS Safari uyumlu — blob doğrudan indirilmez, iframe'de gösterilir)
	let pdfModal: PdfPreviewModal | undefined = $state();

	// $derived — Store'dan reactive okuma — optimistic update için doğrudan cache'e yazılır
	let items = $derived(cashFlowCache.items);
	let categories = $derived(cashFlowCache.categories);
	let loading = $derived(cashFlowCache.loading && !cashFlowCache.loaded);
	let untaggedCount = $derived(cashFlowCache.untaggedCount);
	let eurBalances = $derived(cashFlowCache.eurBalances);

	// Filtrelenmiş items
	const filteredItems = $derived(() => {
		let result = items;
		if (tagFilter === 'untagged') result = result.filter(i => !i.category_id);
		else if (tagFilter !== 'all') result = result.filter(i => i.category_id === tagFilter);
		if (paymentMethodFilter) result = result.filter(i => i.payment_method === paymentMethodFilter);

		// Tahmini kredi kartı ekstresi kalemleri (cari ay = limit, ileri aylar = 0) — yalnız
		// daraltıcı filtre yokken göster (etiket 'all', arama boş, ödeme yöntemi yok/kredi_karti);
		// tarih aralığına saygı göster (ileri aylar endDate ile sınırlanabilir).
		const showProjected =
			tagFilter === 'all' &&
			(!paymentMethodFilter || paymentMethodFilter === 'kredi_karti') &&
			!filterSearch.trim();
		if (showProjected && cashFlowCache.projectedItems.length) {
			const start = filterStartDate;
			const end = filterEndDate;
			const inRange = (d: string) => (!start || d >= start) && (!end || d <= end);
			result = [...result, ...cashFlowCache.projectedItems.filter(p => inRange(p.date))];
		}
		return result;
	});

	// Aylık gruplar
	const monthGroups = $derived(groupByMonth(filteredItems()));

	// Constants
	const { currentMonthKey, currentDayKey } = getTodayKeys();
	const canUse = hasPermission('finance.cash_flow', 'use');

	let unsubFinance: (() => void) | null = null;
	// Kendi işlemlerimizden gelen WS event'ini yoksay — scroll koruması
	let skipNextWsReload = false;
	let skipWsTimer: ReturnType<typeof setTimeout> | null = null;

	// UI helper functions
	function markSkipWsReload() {
		skipNextWsReload = true;
		if (skipWsTimer) clearTimeout(skipWsTimer);
		skipWsTimer = setTimeout(() => { skipNextWsReload = false; }, 3000);
	}

	/** Sayfa içi işlemler sonrası veriyi zorla yenile */
	async function forceReload() {
		try {
			await loadCashFlowItems(true);
		} catch (e) {
			console.error('Nakit akım yeniden yüklenemedi:', e);
			showToast('Veriler yüklenemedi', 'error');
		}
	}

	// ─── Eşleşme önerileri ──────────────────────────────────
	function fmtSugDate(d: string | null): string {
		if (!d) return '—';
		const [y, m, day] = d.split('-');
		return `${day}.${m}.${y}`;
	}

	function fmtSugAmount(n: number | null | undefined, currency?: string | null): string {
		if (n == null) return '—';
		const cur = currency || 'TRY';
		const sym = CUR_SYMBOL[cur] ?? cur + ' ';
		return sym + n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	/** Rozet sayısı için yalnız toplamı çek (page_size=1 — hafif istek). */
	async function loadSuggestionCount() {
		try {
			const res = await api.get<{ total: number }>('/finance/cash-flow/match-suggestions?page=1&page_size=1');
			suggestionsTotal = res.total;
		} catch (err) {
			console.error('Eşleşme önerisi sayısı alınamadı:', err);
		}
	}

	async function loadSuggestions() {
		sugLoading = true;
		try {
			const res = await api.get<{ items: MatchSuggestion[]; total: number; pages: number }>(
				`/finance/cash-flow/match-suggestions?page=${sugPage}&page_size=${sugPageSize}`
			);
			// Onay/ret sonrası sayfa aralık dışına düştüyse son sayfaya çekil
			if (res.items.length === 0 && res.total > 0 && sugPage > 1) {
				sugPage = Math.max(1, res.pages);
				sugLoading = false;
				await loadSuggestions();
				return;
			}
			sugItems = res.items;
			sugTotal = res.total;
			suggestionsTotal = res.total;
		} catch (err) {
			console.error('Eşleşme önerileri yüklenemedi:', err);
			showToast('Eşleşme önerileri yüklenemedi', 'error');
		}
		sugLoading = false;
	}

	function openSuggestions() {
		sugPage = 1;
		showSuggestions = true;
		loadSuggestions();
	}

	function askAcceptSuggestion(s: MatchSuggestion) {
		sugConfirm = {
			show: true,
			title: 'Öneriyi Onayla',
			message: `Banka hareketi "${s.target_description || SUG_TYPE_LABELS[s.target_source_type] || s.target_source_type}" kaydıyla eşleştirilecek. Onaylıyor musunuz?`,
			confirmText: 'Onayla',
			danger: false,
			onConfirm: () => acceptSuggestion(s),
		};
	}

	async function acceptSuggestion(s: MatchSuggestion) {
		markSkipWsReload();
		try {
			await api.post(`/finance/cash-flow/match-suggestions/${s.id}/accept`, {});
			showToast('Eşleşme onaylandı', 'success');
			await Promise.all([loadSuggestions(), loadCashFlowItems(true), loadCashFlowEurBalances()]);
		} catch (err: any) {
			console.error('Öneri onaylama hatası:', err);
			const msg = err?.message || 'Öneri onaylanamadı';
			if (msg.includes('kaldırıldı') || msg.includes('bulunamadı')) {
				// 409/404 — hedef bu arada eşleşmiş/kapanmış, öneri düştü → bilgi ver + tazele
				showToast(msg, 'info');
				await loadSuggestions();
			} else {
				showToast(msg, 'error');
			}
		}
	}

	function askRejectSuggestion(s: MatchSuggestion) {
		sugConfirm = {
			show: true,
			title: 'Öneriyi Reddet',
			message: `"${s.target_description || SUG_TYPE_LABELS[s.target_source_type] || s.target_source_type}" önerisi silinecek (bir sonraki eşleştirme koşusunda yeniden önerilebilir). Reddedilsin mi?`,
			confirmText: 'Reddet',
			danger: true,
			onConfirm: () => rejectSuggestion(s),
		};
	}

	async function rejectSuggestion(s: MatchSuggestion) {
		markSkipWsReload();
		try {
			await api.post(`/finance/cash-flow/match-suggestions/${s.id}/reject`, {});
			showToast('Öneri reddedildi', 'success');
			await loadSuggestions();
		} catch (err: any) {
			console.error('Öneri reddetme hatası:', err);
			const msg = err?.message || 'Öneri reddedilemedi';
			if (msg.includes('bulunamadı')) {
				showToast(msg, 'info');
				await loadSuggestions();
			} else {
				showToast(msg, 'error');
			}
		}
	}

	// ─── Yaşlananlar (aging) ────────────────────────────────
	/** Rozet sayısı için sayfa açılışında hafif çek (days=7 — rozet her zaman 7 günlük eşiği gösterir). */
	async function loadAgingCount() {
		try {
			const res = await api.get<AgingData>('/finance/cash-flow/reconciliation/aging?days=7');
			agingTotal = res.stale_forecasts.total_count + res.unmatched_bank.count;
			if (agingDays === 7) agingData = res;
		} catch (err) {
			console.error('Yaşlanan eşleşmemiş sayısı alınamadı:', err);
		}
	}

	async function loadAging() {
		agingLoading = true;
		try {
			agingData = await api.get<AgingData>(`/finance/cash-flow/reconciliation/aging?days=${agingDays}`);
			if (agingDays === 7) agingTotal = agingData.stale_forecasts.total_count + agingData.unmatched_bank.count;
		} catch (err) {
			console.error('Yaşlananlar raporu yüklenemedi:', err);
			showToast('Yaşlananlar raporu yüklenemedi', 'error');
		}
		agingLoading = false;
	}

	function openAging() {
		showAging = true;
		loadAging();
	}

	function setAgingDays(v: string) {
		agingDays = parseInt(v, 10);
		loadAging();
	}

	// ─── Tahmin doğruluğu ───────────────────────────────────
	async function loadAccuracy() {
		accuracyLoading = true;
		try {
			accuracyData = await api.get<AccuracyData>(`/finance/cash-flow/forecast-accuracy?months=${accuracyMonths}`);
		} catch (err) {
			console.error('Tahmin doğruluğu raporu yüklenemedi:', err);
			showToast('Tahmin doğruluğu raporu yüklenemedi', 'error');
		}
		accuracyLoading = false;
	}

	function openAccuracy() {
		showAccuracy = true;
		loadAccuracy();
	}

	function setAccuracyMonths(v: string) {
		accuracyMonths = parseInt(v, 10);
		loadAccuracy();
	}

	/** Gecikme gününü işaretli göster (pozitif = tahminden GEÇ gerçekleşme). */
	function fmtDelay(n: number): string {
		const v = Math.abs(n).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
		return n > 0 ? `+${v}` : n < 0 ? `−${v}` : v;
	}

	function delayCls(n: number): string {
		return n > 0 ? 'text-red-600' : n < 0 ? 'text-emerald-700' : 'text-gray-600';
	}

	// CRUD functions
	function handleCCMatchStart(statementId: number, type: 'cc' | 'credit', description: string, amount: number) {
		ccMatchMode = true;
		ccMatchStatementId = statementId;
		ccMatchType = type;
		ccMatchDescription = description;
		ccMatchAmount = amount;
	}

	async function handleCCMatchSelect(bankTxId: number) {
		if (!ccMatchStatementId) return;
		markSkipWsReload();
		try {
			if (ccMatchType === 'cc') {
				const ccRes = await api.post<any>('/finance/cash-flow/match-cc-payment', {
					bank_transaction_id: bankTxId,
					statement_id: ccMatchStatementId,
				});
				showToast(`KK ödeme eşleştirildi — ${ccRes.card_name} | Kalan: ₺${ccRes.remaining?.toLocaleString('tr-TR') ?? '0'}`, 'success');
				if (ccRes.is_fully_paid) {
					cashFlowCache.items = items.filter(i => !(i.source === 'cc_payment' && i.id === ccMatchStatementId));
				}
			} else {
				const crRes = await api.post<any>('/finance/cash-flow/match-credit-payment', {
					bank_transaction_id: bankTxId,
					payment_id: ccMatchStatementId,
				});
				showToast(`Kredi taksit eşleştirildi — ${crRes.product_name} #${crRes.installment_no}`, 'success');
				cashFlowCache.items = items.filter(i => !(i.source === 'credit' && i.id === ccMatchStatementId));
			}
			loadCashFlowEurBalances();
		} catch (err: any) {
			console.error('Eşleştirme hatası:', err);
			showToast(err?.body?.detail || 'Eşleştirme başarısız', 'error');
		}
		ccMatchMode = false;
		ccMatchStatementId = null;
	}

	function cancelCCMatch() {
		ccMatchMode = false;
		ccMatchStatementId = null;
	}

	async function handleTagAssign(txId: number, categoryId: number | null, note: string | null, vendorId?: number | null, paymentMethod?: string | null, ccStatementId?: number | null) {
		markSkipWsReload();
		try {
			// Kredi taksit ödeme eşleştirmesi
			if (ccStatementId && paymentMethod === 'kredi') {
				const crRes = await api.post<any>('/finance/cash-flow/match-credit-payment', {
					bank_transaction_id: txId,
					payment_id: ccStatementId,
				});
				// Banka işlemini etiketle
				const idx = items.findIndex(i => i.id === txId && i.source === 'bank');
				if (idx !== -1) {
					const cat = categories.find(c => c.id === categoryId);
					cashFlowCache.items[idx] = {
						...items[idx],
						category_id: categoryId,
						category_name: cat?.name ?? null,
						category_color: cat?.color ?? null,
						tag_note: crRes.product_name ?? null,
						tag_source: 'manual',
						payment_method: 'kredi',
					};
				}
				// Eşleşen kredi taksitini listeden kaldır
				cashFlowCache.items = items.filter(i => !(i.source === 'credit' && i.id === ccStatementId));
				showToast(`Kredi taksit eşleştirildi — ${crRes.product_name} #${crRes.installment_no}`, 'success');
				loadCashFlowEurBalances();
				return;
			}

			// Kredi kartı borç ödeme eşleştirmesi
			if (ccStatementId && paymentMethod === 'kredi_karti') {
				const ccRes = await api.post<any>('/finance/cash-flow/match-cc-payment', {
					bank_transaction_id: txId,
					statement_id: ccStatementId,
				});
				// Banka işlemini etiketle
				const idx = items.findIndex(i => i.id === txId && i.source === 'bank');
				if (idx !== -1) {
					const cat = categories.find(c => c.id === categoryId);
					cashFlowCache.items[idx] = {
						...items[idx],
						category_id: categoryId,
						category_name: cat?.name ?? null,
						category_color: cat?.color ?? null,
						tag_note: ccRes.card_name ?? null,
						tag_source: 'manual',
						payment_method: 'kredi_karti',
					};
				}
				// Tamamen ödendiyse CC ödeme kartını kaldır
				if (ccRes.is_fully_paid) {
					cashFlowCache.items = items.filter(i => !(i.source === 'cc_payment' && i.id === ccStatementId));
				}
				showToast(`KK ödeme eşleştirildi — Kalan: ₺${ccRes.remaining?.toLocaleString('tr-TR') ?? '0'}`, 'success');
				loadCashFlowEurBalances();
				return;
			}

			const body: Record<string, any> = {
				category_id: categoryId,
				tag_note: note,
				vendor_id: vendorId ?? null,
			};
			if (paymentMethod !== undefined) {
				body.payment_method = paymentMethod;
			}
			const res = await api.patch<{ ok: boolean; vendor_name: string | null; match_number: number | null; paired_tx_id: number | null }>(`/finance/tags/transactions/${txId}`, body);

			const cat = categories.find(c => c.id === categoryId);
			const idx = items.findIndex(i => i.id === txId && i.source === 'bank');
			if (idx !== -1) {
				cashFlowCache.items[idx] = {
					...items[idx],
					category_id: categoryId,
					category_name: cat?.name ?? null,
					category_color: cat?.color ?? null,
					tag_note: note,
					tag_source: categoryId !== null ? 'manual' : null,
					vendor_id: vendorId ?? null,
					vendor_name: res.vendor_name ?? null,
					payment_method: categoryId === null ? null : (paymentMethod ?? items[idx].payment_method),
					match_number: categoryId === null ? null : (res.match_number ?? items[idx].match_number),
				};
			}

			// Virman/Döviz Satım: karşı taraftaki işlemi de güncelle
			if (res.paired_tx_id) {
				const pIdx = items.findIndex(i => i.id === res.paired_tx_id && i.source === 'bank');
				if (pIdx !== -1) {
					cashFlowCache.items[pIdx] = {
						...items[pIdx],
						category_id: categoryId,
						category_name: cat?.name ?? null,
						category_color: cat?.color ?? null,
						tag_note: note,
						tag_source: categoryId !== null ? 'manual' : null,
						match_number: res.match_number ?? null,
					};
				}
			}

			// Yalnız BANKA işlemleri etiketlenebilir — backend /tags/untagged-count ile aynı evren
			// (çek/cari/kredi satırları kategorisizdir; hepsini saymak rozeti şişirir)
			cashFlowCache.untaggedCount = items.filter(i => i.source === 'bank' && !i.category_id).length;
			showToast(categoryId ? 'Etiket atandı' : 'Etiket kaldırıldı', 'success');

			// EUR bakiyeleri güncelle (gün/ay başlıkları)
			loadCashFlowEurBalances();
		} catch (err) {
			console.error('Etiket atama hatası:', err);
			showToast('Etiket atanamadı', 'error');
		}
	}

	async function handleCreateCategory(name: string, color: string): Promise<TransactionCategory | null> {
		try {
			const newCat = await api.post<TransactionCategory>('/finance/tags/categories', { name, color });
			cashFlowCache.categories = [...categories, newCat];
			showToast(`"${newCat.name}" etiketi oluşturuldu`, 'success');
			return newCat;
		} catch (err: any) {
			console.error('Kategori oluşturma hatası:', err);
			showToast(err?.message || 'Kategori oluşturulamadı', 'error');
			return null;
		}
	}

	async function matchBankToVendorTx(bankTxId: number) {
		if (!matchVtxId || !matchVendorId) return;
		markSkipWsReload();
		try {
			await api.post(`/finance/cash-flow/match-vendor-tx`, {
				bank_transaction_id: bankTxId,
				vendor_transaction_id: matchVtxId,
				vendor_id: matchVendorId,
			});
			showToast('Eşleştirme tamamlandı', 'success');
			matchMode = false;
			// Cariler sayfasına ilgili cariye dön
			goto(`/dashboard/finans/cariler?vendor=${matchVendorId}`);
		} catch (err: any) {
			console.error('Eşleştirme hatası:', err);
			showToast(err?.body?.detail || 'Eşleştirme başarısız', 'error');
		}
	}

	function cancelMatch() {
		matchMode = false;
		if (matchVendorId) {
			goto(`/dashboard/finans/cariler?vendor=${matchVendorId}`);
		} else {
			goto('/dashboard/finans/cariler');
		}
	}

	async function runAutoTag() {
		autoTagging = true;
		markSkipWsReload();
		try {
			const res = await api.post<{ tagged: number; total_untagged: number }>('/finance/tags/auto-tag', {});
			showToast(`${res.tagged} işlem otomatik etiketlendi`, 'success');
			await Promise.all([loadCashFlowItems(true), loadCashFlowUntaggedCount()]);
		} catch (err) {
			console.error('Otomatik etiketleme hatası:', err);
			showToast('Otomatik etiketleme başarısız', 'error');
		}
		autoTagging = false;
	}

	/** Otomatik etiketleme + 4 eşleştiriciyi (çek/kredi/KK/avans) elle tetikle (R1).
	 *  Backend BANKS yayını yapar — açık diğer sekmeler WS ile tazelenir; bu sayfa
	 *  runAutoTag ile aynı desende kendi yankısını atlar ve veriyi zorla yeniler. */
	async function runRematch() {
		rematching = true;
		markSkipWsReload();
		try {
			const res = await api.post<Record<string, number>>('/finance/cash-flow/rematch', {});
			const parts: string[] = [];
			if (res.auto_tagged) parts.push(`${res.auto_tagged} etiket`);
			if (res.payment_methods_detected) parts.push(`${res.payment_methods_detected} ödeme yöntemi`);
			if (res.vendors_auto_matched) parts.push(`${res.vendors_auto_matched} cari`);
			if (res.checks_matched) parts.push(`${res.checks_matched} çek`);
			if (res.credits_matched) parts.push(`${res.credits_matched} kredi`);
			if (res.cc_matched) parts.push(`${res.cc_matched} KK`);
			if (res.advances_matched) parts.push(`${res.advances_matched} avans`);
			if (parts.length) {
				showToast(`Yeniden eşleştirme: ${parts.join(' · ')}`, 'success');
			} else {
				showToast('Yeni eşleşme bulunamadı', 'info');
			}
			await Promise.all([loadCashFlowItems(true), loadCashFlowUntaggedCount(), loadCashFlowEurBalances(), loadSuggestionCount()]);
		} catch (err: any) {
			console.error('Yeniden eşleştirme hatası:', err);
			showToast(err?.body?.detail || 'Yeniden eşleştirme başarısız', 'error');
		}
		rematching = false;
	}

	/** Akordiyonda açık (seçili) ayın nakit akış raporunu PDF göster.
	 *  Birden çok ay açıksa hepsini kapsayan aralık; hiçbir ay açık değilse
	 *  ekrandaki tarih filtresi kullanılır. */
	async function downloadPdf() {
		pdfLoading = true;
		try {
			const expandedMonthKeys = accordionRef?.getExpandedMonthKeys() ?? [];
			const monthRange = monthKeysToDateRange(expandedMonthKeys);

			const params = new URLSearchParams();
			if (monthRange) {
				params.set('start_date', monthRange.start);
				params.set('end_date', monthRange.end);
			} else {
				if (cashFlowCache.filters.startDate) params.set('start_date', cashFlowCache.filters.startDate);
				if (cashFlowCache.filters.endDate) params.set('end_date', cashFlowCache.filters.endDate);
			}
			const qs = params.toString();
			const res = await api.fetchRaw(`/finance/cash-flow/report/pdf${qs ? '?' + qs : ''}`);
			if (!res.ok) throw new Error('İndirme başarısız');
			const blob = await res.blob();

			const fnameLabel = monthRange
				? (expandedMonthKeys.length === 1 ? expandedMonthKeys[0] : `${monthRange.start}_${monthRange.end}`)
				: new Date().toISOString().slice(0, 10);
			// iOS Safari blob'u doğrudan indiremiyor (WebKitBlobResource hatası 1) →
			// paylaşılan önizleme modalında göster (Yazdır/İndir oradan)
			pdfModal?.open(blob, `nakit-akim-raporu-${fnameLabel}.pdf`);
		} catch (err) {
			console.error('PDF rapor indirme hatası:', err);
			showToast('PDF raporu indirilemedi', 'error');
		} finally {
			pdfLoading = false;
		}
	}

	function setFilter(filter: 'all' | 'untagged' | number) {
		tagFilter = filter;
		accordionRef?.resetAccordion();
	}

	async function applyDateFilter() {
		await applyCashFlowFilters({ startDate: filterStartDate, endDate: filterEndDate });
		accordionRef?.resetAccordion();
	}

	async function clearDateFilter() {
		filterStartDate = '';
		filterEndDate = '';
		filterSearch = '';
		showDateFilter = false;
		await applyCashFlowFilters({ startDate: '', endDate: '', search: '' });
		accordionRef?.resetAccordion();
	}

	function handleSearchInput() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(async () => {
			await applyCashFlowFilters({ search: filterSearch });
			accordionRef?.resetAccordion();
		}, 400);
	}

	// Lifecycle — onMount / onDestroy
	onMount(async () => {
		// URL parametrelerinden eşleştirme modunu oku
		const params = $page.url.searchParams;
		if (params.has('vtx_id')) {
			matchMode = true;
			matchDate = params.get('date');
			matchAmount = params.has('amount') ? parseFloat(params.get('amount')!) : null;
			matchVendorName = params.get('vendor') ? decodeURIComponent(params.get('vendor')!) : null;
			matchVtxId = params.has('vtx_id') ? parseInt(params.get('vtx_id')!) : null;
			matchVendorId = params.has('vendor_id') ? parseInt(params.get('vendor_id')!) : null;
		}

		// Eşleştirme modunda her zaman taze veri çek, normal modda cache kullan
		await loadAllCashFlow(matchMode);

		// Öneri + yaşlananlar rozet sayıları (bloklamadan)
		loadSuggestionCount();
		loadAgingCount();

		// Finans güncelleme event'ini dinle — başka kullanıcı değişiklik yapınca otomatik yenile
		unsubFinance = onWsEvent('finance_updated', () => {
			if (skipNextWsReload) {
				// Kendi işlemimizin yankısı — öneriler zaten elle tazelendi
				skipNextWsReload = false;
				refreshCashFlowLight();
				return;
			}
			// Panel açıkken öneri listesini, kapalıyken rozet sayısını tazele
			if (showSuggestions) loadSuggestions();
			else loadSuggestionCount();
			if (showAging) loadAging();
			else loadAgingCount();
			refreshCashFlowFull();
		});
	});

	onDestroy(() => {
		unsubFinance?.();
		if (skipWsTimer) clearTimeout(skipWsTimer);
	});
</script>

<svelte:head>
	<title>Nakit Akım - Sprenses</title>
</svelte:head>

<!-- Başlık -->
<div class="mb-5">
	<PageHeader title="Nakit Akım" description="Banka hareketleri, gelir/gider takibi ve işlem eşleştirme">
		{#snippet actions()}
			{#if canUse}
				<Button
					variant="secondary"
					loading={rematching}
					onclick={runRematch}
					ariaLabel="Yeniden Eşleştir"
					title="Otomatik etiketleme + çek/kredi/KK/avans eşleştiricilerini elle çalıştır"
				>
					<RefreshCw size={16} /> <span class="hidden sm:inline">Yeniden Eşleştir</span>
				</Button>
			{/if}
			<Button
				variant="secondary"
				onclick={openSuggestions}
				disabled={suggestionsTotal === 0}
				ariaLabel="Eşleşme Önerileri"
				title="Otomatik eşiğin altında kalan eşleşme adaylarını incele (onayla/reddet)"
			>
				<Link2 size={16} /> <span class="hidden sm:inline">Eşleşme Önerileri</span>
				<span class="min-w-[1.25rem] h-5 px-1 rounded-full text-[11px] font-semibold tabular-nums flex items-center justify-center {suggestionsTotal > 0 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'}">{suggestionsTotal}</span>
			</Button>
			<Button
				variant="secondary"
				onclick={openAging}
				disabled={agingTotal === 0}
				ariaLabel="Yaşlananlar"
				title="Vadesi geçtiği halde eşleşmemiş tahminler + yaşlanan etiketsiz banka hareketleri"
			>
				<Hourglass size={16} /> <span class="hidden sm:inline">Yaşlananlar</span>
				<span class="min-w-[1.25rem] h-5 px-1 rounded-full text-[11px] font-semibold tabular-nums flex items-center justify-center {agingTotal > 0 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'}">{agingTotal}</span>
			</Button>
			<Button
				variant="secondary"
				onclick={openAccuracy}
				ariaLabel="Tahmin Doğruluğu"
				title="Tahmin ↔ gerçekleşme tarih sapması — tür ve cari bazında gecikme analizi"
			>
				<Target size={16} /> <span class="hidden sm:inline">Tahmin Doğruluğu</span>
			</Button>
			<Button
				variant="secondary"
				loading={pdfLoading}
				onclick={downloadPdf}
				ariaLabel="PDF Rapor"
				title="Açık (seçili) ayın nakit akışını PDF rapor olarak göster — ay kapalıysa görüntülenen aralık"
			>
				<FileDown size={16} /> <span class="hidden sm:inline">PDF Rapor</span>
			</Button>
		{/snippet}
	</PageHeader>
</div>

{#if matchMode}
	<div class="bg-amber-50 border border-amber-300 rounded-2xl p-4 mb-4 flex items-center gap-3 flex-wrap">
		<div class="flex-1 min-w-0">
			<div class="text-sm font-bold text-amber-800">Cari Eşleştirme Modu</div>
			<div class="text-xs text-amber-600 mt-0.5">
				<span class="font-medium">{matchVendorName}</span> — {matchDate} tarihli ₺{matchAmount?.toLocaleString('tr-TR', {minimumFractionDigits: 2})} borç işlemi için banka karşılığını seçin
			</div>
		</div>
		<Button variant="secondary" size="sm" onclick={cancelMatch}>İptal</Button>
	</div>
{/if}

{#if ccMatchMode}
	<div class="bg-pink-50 border border-pink-300 rounded-2xl p-4 mb-4 flex items-center gap-3 flex-wrap">
		<div class="flex-1 min-w-0">
			<div class="text-sm font-bold text-pink-800">{ccMatchType === 'cc' ? 'KK Borç Ödeme' : 'Kredi Taksit'} Eşleştirme</div>
			<div class="text-xs text-pink-600 mt-0.5">
				<span class="font-medium">{ccMatchDescription}</span> — ₺{ccMatchAmount.toLocaleString('tr-TR', {minimumFractionDigits: 2})} için banka işlemini seçin
			</div>
		</div>
		<Button variant="secondary" size="sm" onclick={cancelCCMatch}>İptal</Button>
	</div>
{/if}

{#if !matchMode && !ccMatchMode}
	<CashFlowSummaryCards />
{/if}

<!-- Tarih Aralığı & Arama Filtresi -->
<div class="flex items-center gap-2 mb-3 flex-wrap">
	<button
		onclick={() => { showDateFilter = !showDateFilter; }}
		class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer
			{showDateFilter || filterStartDate || filterEndDate || filterSearch
				? 'bg-cyan-100 text-cyan-700 border border-cyan-300'
				: 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'}"
	>
		<Filter size={14} />
		Filtre
		{#if filterStartDate || filterEndDate || filterSearch}
			<span class="bg-teal-700 text-white rounded-full w-4 h-4 flex items-center justify-center"><Check size={10} /></span>
		{/if}
	</button>

	{#if filterStartDate || filterEndDate}
		<span class="text-xs text-gray-500">
			{filterStartDate || '∞'} → {filterEndDate || '∞'}
		</span>
	{/if}

	{#if filterSearch}
		<span class="text-xs bg-amber-50 text-amber-700 border border-amber-200 rounded px-2 py-0.5">
			"{filterSearch}"
		</span>
	{/if}

	{#if filterStartDate || filterEndDate || filterSearch}
		<button
			onclick={clearDateFilter}
			class="text-xs text-red-600 hover:text-red-700 cursor-pointer"
		>Temizle</button>
	{/if}

	<span class="text-xs text-gray-500 ml-auto">
		{items.length.toLocaleString('tr-TR')} kayıt
		{#if isTruncated}
			<span class="text-amber-600 font-medium">/ {cashFlowCache.totalCount.toLocaleString('tr-TR')} toplam</span>
		{/if}
	</span>
</div>

{#if showDateFilter}
	<div class="bg-gray-50 border border-gray-200 rounded-xl p-3 mb-3 flex items-end gap-3 flex-wrap">
		<div class="flex flex-col gap-1">
			<label class="text-xs text-gray-500 font-medium" for="cf-start">Başlangıç</label>
			<Input
				id="cf-start"
				type="date"
				size="sm"
				bind:value={filterStartDate}
			/>
		</div>
		<div class="flex flex-col gap-1">
			<label class="text-xs text-gray-500 font-medium" for="cf-end">Bitiş</label>
			<Input
				id="cf-end"
				type="date"
				size="sm"
				bind:value={filterEndDate}
			/>
		</div>
		<div class="flex flex-col gap-1 flex-1 min-w-[200px]">
			<label class="text-xs text-gray-500 font-medium" for="cf-search">Arama</label>
			<Input
				id="cf-search"
				type="text"
				size="sm"
				placeholder="Açıklama, banka, cari kodu..."
				bind:value={filterSearch}
				oninput={handleSearchInput}
			/>
		</div>
		<Button size="sm" onclick={applyDateFilter}>Uygula</Button>
	</div>
{/if}

{#if isTruncated}
	<div class="bg-amber-50 border border-amber-200 rounded-xl p-3 mb-3 flex items-center gap-2">
		<AlertTriangle size={16} class="text-amber-600 flex-shrink-0" />
		<span class="text-xs text-amber-700">
			Toplam <strong>{cashFlowCache.totalCount.toLocaleString('tr-TR')}</strong> kayıt mevcut, sadece <strong>{items.length.toLocaleString('tr-TR')}</strong> tanesi gösteriliyor.
			Tarih filtresi kullanarak sonuçları daraltabilirsiniz.
		</span>
	</div>
{/if}

{#if loading}
	<TableSkeleton rows={8} columns={4} />
{:else if filteredItems().length === 0}
	{#if tagFilter === 'untagged'}
		<EmptyState icon={Receipt} title="Tüm işlemler etiketli!" description="Etiketlenmemiş işlem bulunmuyor" />
	{:else if tagFilter !== 'all'}
		<EmptyState icon={Receipt} title="Bu kategoride işlem yok" description="Seçili filtre ile eşleşen işlem bulunamadı" />
	{:else}
		<EmptyState icon={Receipt} title="Henüz işlem yok" description="Banka ekstresi yükleyerek başlayın" />
	{/if}
{:else}
	<MonthAccordion
		bind:this={accordionRef}
		{monthGroups}
		{currentMonthKey}
		{currentDayKey}
		{categories}
		matchMode={matchMode || ccMatchMode}
		{matchDate}
		{eurBalances}
		onTagAssign={handleTagAssign}
		onCreateCategory={handleCreateCategory}
		onMatchSelect={ccMatchMode ? handleCCMatchSelect : matchBankToVendorTx}
		onCCMatchStart={handleCCMatchStart}
	/>
{/if}

<!-- Eşleşme Önerileri paneli -->
<Modal bind:show={showSuggestions} title="Eşleşme Önerileri" maxWidth="max-w-4xl">
	{#if sugLoading}
		<TableSkeleton rows={5} columns={3} showHeader={false} />
	{:else if sugItems.length === 0}
		<EmptyState icon={Link2} title="Bekleyen öneri yok" description="Otomatik eşleşmeyen adaylar burada birikir" />
	{:else}
		<div class="space-y-2">
			{#each sugItems as s (s.id)}
				<div class="border border-gray-200 rounded-xl p-3 flex flex-col lg:flex-row lg:items-center gap-3">
					<!-- SOL: banka hareketi -->
					<div class="flex-1 min-w-0">
						<div class="text-[10px] tracking-wide uppercase text-gray-500 font-semibold mb-0.5">Banka Hareketi</div>
						<div class="flex items-baseline gap-2 flex-wrap">
							<span class="tabular-nums text-xs text-gray-500">{fmtSugDate(s.bank_date)}</span>
							<span class="tabular-nums text-sm font-semibold text-gray-900">{fmtSugAmount(s.bank_amount)}</span>
						</div>
						<div class="text-xs text-gray-500 truncate" title={s.bank_description || ''}>{s.bank_description || '—'}</div>
					</div>

					<div class="hidden lg:flex text-gray-500 shrink-0"><ArrowRight size={16} /></div>

					<!-- SAĞ: hedef kayıt -->
					<div class="flex-1 min-w-0">
						<div class="flex items-center gap-1.5 mb-0.5 flex-wrap">
							<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{SUG_TYPE_LABELS[s.target_source_type] ?? s.target_source_type}</span>
							<StatusBadge type="warning">skor {Math.round(s.score)}</StatusBadge>
						</div>
						<div class="text-sm font-medium text-gray-800 truncate" title={s.target_description || ''}>{s.target_description || '—'}</div>
						<div class="flex items-baseline gap-2">
							<span class="tabular-nums text-xs text-gray-500">{fmtSugDate(s.target_date)}</span>
							<span class="tabular-nums text-sm font-semibold text-gray-900">{fmtSugAmount(s.amount, s.currency)}</span>
						</div>
					</div>

					{#if canUse}
						<div class="flex gap-1.5 shrink-0 justify-end">
							<Button size="sm" onclick={() => askAcceptSuggestion(s)} title="Öneriyi onayla — eşleşme kurulur">
								<Check size={14} /> Onayla
							</Button>
							<Button variant="ghost" size="sm" onclick={() => askRejectSuggestion(s)} title="Öneriyi reddet — öneri silinir">
								<X size={14} class="text-red-600" /> Reddet
							</Button>
						</div>
					{/if}
				</div>
			{/each}
		</div>
		<Pagination
			page={sugPage}
			pageSize={sugPageSize}
			total={sugTotal}
			onPageChange={(p) => { sugPage = p; loadSuggestions(); }}
			onPageSizeChange={(sz) => { sugPageSize = sz; sugPage = 1; loadSuggestions(); }}
		/>
	{/if}
</Modal>

<!-- Yaşlananlar paneli -->
<Modal bind:show={showAging} title="Yaşlananlar — Eşleşmemiş Kayıtlar" maxWidth="max-w-4xl">
	<div class="flex items-center justify-between gap-2 mb-3 flex-wrap">
		<SegmentedControl
			size="sm"
			options={[{ value: '7', label: '7 gün' }, { value: '15', label: '15 gün' }, { value: '30', label: '30 gün' }]}
			value={String(agingDays)}
			onchange={setAgingDays}
			ariaLabel="Yaşlandırma eşiği"
		/>
		{#if agingData && !agingLoading}
			<span class="text-xs text-gray-500">Eşik: {fmtSugDate(agingData.cutoff)} öncesi</span>
		{/if}
	</div>

	{#if agingLoading}
		<TableSkeleton rows={5} columns={3} showHeader={false} />
	{:else if !agingData || (agingData.stale_forecasts.total_count === 0 && agingData.unmatched_bank.count === 0)}
		<EmptyState icon={Hourglass} title="Yaşlanan kayıt yok" description="Seçili eşikten eski açık tahmin veya etiketsiz banka hareketi bulunmuyor" />
	{:else}
		<!-- Kaynak bazlı özet çipleri -->
		{#if Object.keys(agingData.stale_forecasts.by_source).length > 0}
			<div class="flex flex-wrap gap-1.5 mb-4">
				{#each Object.entries(agingData.stale_forecasts.by_source) as [src, g] (src)}
					<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-xs" title={g.oldest_date ? `En eski: ${fmtSugDate(g.oldest_date)}` : ''}>
						<span class="font-medium text-amber-800">{g.label}</span>
						<span class="tabular-nums text-amber-700">{g.count}</span>
						<span class="tabular-nums font-semibold text-amber-800">₺{g.total_try.toLocaleString('tr-TR', { maximumFractionDigits: 0 })}</span>
					</span>
				{/each}
			</div>
		{/if}

		<div class="space-y-5">
			<!-- Açık tahminler -->
			<div>
				<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
					Açık Tahminler ({agingData.stale_forecasts.total_count})
				</h3>
				{#if agingData.stale_forecasts.items.length === 0}
					<p class="text-sm text-gray-500">Vadesi geçmiş açık tahmin yok.</p>
				{:else}
					<div class="divide-y divide-gray-100 border border-gray-200 rounded-xl overflow-hidden">
						{#each agingData.stale_forecasts.items as it (`${it.source_type}-${it.source_id}`)}
							<div class="px-3 py-2 flex items-center gap-2.5 text-sm">
								<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 shrink-0">
									{agingData.stale_forecasts.by_source[it.source_type]?.label ?? it.source_type}
								</span>
								<span class="tabular-nums text-xs text-gray-500 shrink-0">{fmtSugDate(it.event_date)}</span>
								<span class="text-gray-700 truncate flex-1 min-w-0" title={it.description || ''}>{it.description || '—'}</span>
								<span class="tabular-nums font-semibold text-gray-900 shrink-0">{fmtSugAmount(it.amount, it.currency)}</span>
								<span class="tabular-nums text-[11px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 shrink-0">{it.days_overdue} gün</span>
							</div>
						{/each}
					</div>
					{#if agingData.stale_forecasts.total_count > agingData.stale_forecasts.items.length}
						<p class="text-xs text-gray-500 mt-1.5">En eski {agingData.stale_forecasts.items.length} kayıt gösteriliyor.</p>
					{/if}
				{/if}
			</div>

			<!-- Etiketsiz banka hareketleri -->
			<div>
				<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
					Etiketsiz Banka Hareketleri ({agingData.unmatched_bank.count} · ₺{agingData.unmatched_bank.total.toLocaleString('tr-TR', { maximumFractionDigits: 0 })})
				</h3>
				{#if agingData.unmatched_bank.items.length === 0}
					<p class="text-sm text-gray-500">Yaşlanan etiketsiz banka hareketi yok.</p>
				{:else}
					<div class="divide-y divide-gray-100 border border-gray-200 rounded-xl overflow-hidden">
						{#each agingData.unmatched_bank.items as it (it.id)}
							<div class="px-3 py-2 flex items-center gap-2.5 text-sm">
								<span class="tabular-nums text-xs text-gray-500 shrink-0">{fmtSugDate(it.date)}</span>
								<span class="text-gray-700 truncate flex-1 min-w-0" title={it.description || ''}>{it.description || '—'}</span>
								<span class="tabular-nums font-semibold shrink-0 {it.amount < 0 ? 'text-red-600' : 'text-emerald-700'}">{fmtSugAmount(it.amount)}</span>
								<span class="tabular-nums text-[11px] font-semibold px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 shrink-0">{it.days_old} gün</span>
							</div>
						{/each}
					</div>
					{#if agingData.unmatched_bank.count > agingData.unmatched_bank.items.length}
						<p class="text-xs text-gray-500 mt-1.5">En eski {agingData.unmatched_bank.items.length} kayıt gösteriliyor.</p>
					{/if}
				{/if}
			</div>
		</div>
	{/if}
</Modal>

<!-- Tahmin Doğruluğu paneli -->
<Modal bind:show={showAccuracy} title="Tahmin Doğruluğu" maxWidth="max-w-4xl">
	<div class="flex items-center justify-between gap-2 mb-2 flex-wrap">
		<SegmentedControl
			size="sm"
			options={[{ value: '3', label: '3 ay' }, { value: '6', label: '6 ay' }, { value: '12', label: '12 ay' }]}
			value={String(accuracyMonths)}
			onchange={setAccuracyMonths}
			ariaLabel="Analiz dönemi"
		/>
		{#if accuracyData && !accuracyLoading}
			<span class="text-xs text-gray-500 tabular-nums">{accuracyData.total_matches} eşleşme incelendi</span>
		{/if}
	</div>
	<p class="text-xs text-gray-500 mb-3">Pozitif = tahminden geç gerçekleşme. Önerilen vade uygulaması Cariler sayfasından elle yapılır.</p>

	{#if accuracyLoading}
		<TableSkeleton rows={5} columns={4} showHeader={false} />
	{:else if !accuracyData || accuracyData.total_matches === 0}
		<EmptyState icon={Target} title="Yeterli eşleşme verisi yok" description="Seçili dönemde tahmin ↔ gerçekleşme izi bulunamadı" />
	{:else}
		<div class="space-y-5">
			<!-- Tür bazında -->
			<div>
				<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">Tür Bazında</h3>
				<div class="overflow-x-auto border border-gray-200 rounded-xl">
					<table class="w-full text-sm">
						<thead>
							<tr class="text-left text-xs text-gray-600 bg-gray-50 border-b border-gray-200">
								<th class="px-3 py-2 font-medium">Tür</th>
								<th class="px-3 py-2 font-medium text-right">Adet</th>
								<th class="px-3 py-2 font-medium text-right">Medyan Gecikme (gün)</th>
								<th class="px-3 py-2 font-medium text-right">Ortalama (gün)</th>
							</tr>
						</thead>
						<tbody>
							{#each accuracyData.by_type as t (t.source_type)}
								<tr class="border-b border-gray-50">
									<td class="px-3 py-2 text-gray-800">{t.label}</td>
									<td class="px-3 py-2 text-right tabular-nums text-gray-600">{t.count}</td>
									<td class="px-3 py-2 text-right tabular-nums font-semibold {delayCls(t.median_delay_days)}">{fmtDelay(t.median_delay_days)}</td>
									<td class="px-3 py-2 text-right tabular-nums {delayCls(t.avg_delay_days)}">{fmtDelay(t.avg_delay_days)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Cari bazında -->
			<div>
				<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">Cari Bazında</h3>
				{#if accuracyData.by_vendor.length === 0}
					<p class="text-sm text-gray-500">Cari eşleşme izi yok.</p>
				{:else}
					<div class="overflow-x-auto border border-gray-200 rounded-xl">
						<table class="w-full text-sm">
							<thead>
								<tr class="text-left text-xs text-gray-600 bg-gray-50 border-b border-gray-200">
									<th class="px-3 py-2 font-medium">Cari</th>
									<th class="px-3 py-2 font-medium text-right">Adet</th>
									<th class="px-3 py-2 font-medium text-right">Medyan Gecikme (gün)</th>
									<th class="px-3 py-2 font-medium text-right">Mevcut Vade</th>
									<th class="px-3 py-2 font-medium text-right">Önerilen Vade</th>
								</tr>
							</thead>
							<tbody>
								{#each accuracyData.by_vendor as v (v.vendor_id)}
									<tr class="border-b border-gray-50">
										<td class="px-3 py-2 text-gray-800">
											<div class="truncate max-w-[220px]" title={v.vendor_name}>{v.vendor_name}</div>
										</td>
										<td class="px-3 py-2 text-right tabular-nums text-gray-600">{v.count}</td>
										<td class="px-3 py-2 text-right tabular-nums font-semibold {delayCls(v.median_delay_days)}">{fmtDelay(v.median_delay_days)}</td>
										<td class="px-3 py-2 text-right tabular-nums text-gray-600">{v.current_payment_days} gün</td>
										<td class="px-3 py-2 text-right">
											{#if v.suggested_payment_days != null}
												<span class="inline-flex items-center tabular-nums text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">{v.suggested_payment_days} gün</span>
											{:else}
												<span class="text-gray-500">—</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</Modal>

<!-- Öneri onay/ret diyaloğu -->
<ConfirmDialog
	bind:show={sugConfirm.show}
	title={sugConfirm.title}
	message={sugConfirm.message}
	confirmText={sugConfirm.confirmText}
	cancelText="Vazgeç"
	danger={sugConfirm.danger}
	onConfirm={sugConfirm.onConfirm}
/>

<!-- PDF Rapor önizleme (iOS Safari uyumlu) -->
<PdfPreviewModal bind:this={pdfModal} />
