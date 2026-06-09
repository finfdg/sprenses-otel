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
	import { Filter, AlertTriangle, Receipt } from 'lucide-svelte';
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
	import { groupByMonth, getTodayKeys } from '$lib/utils/finance';

	// $state — data
	let autoTagging = $state(false);

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

			cashFlowCache.untaggedCount = items.filter(i => !i.category_id).length;
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

		// Finans güncelleme event'ini dinle — başka kullanıcı değişiklik yapınca otomatik yenile
		unsubFinance = onWsEvent('finance_updated', () => {
			if (skipNextWsReload) {
				skipNextWsReload = false;
				refreshCashFlowLight();
				return;
			}
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
	<PageHeader title="Nakit Akım" description="Banka hareketleri, gelir/gider takibi ve işlem eşleştirme" />
</div>

{#if matchMode}
	<div class="bg-amber-50 border border-amber-300 rounded-2xl p-4 mb-4 flex items-center gap-3 flex-wrap">
		<div class="flex-1 min-w-0">
			<div class="text-sm font-bold text-amber-800">Cari Eşleştirme Modu</div>
			<div class="text-xs text-amber-600 mt-0.5">
				<span class="font-medium">{matchVendorName}</span> — {matchDate} tarihli ₺{matchAmount?.toLocaleString('tr-TR', {minimumFractionDigits: 2})} borç işlemi için banka karşılığını seçin
			</div>
		</div>
		<button
			onclick={cancelMatch}
			class="text-xs font-medium px-3 py-1.5 rounded-lg bg-gray-200 text-gray-700 hover:bg-gray-300 transition-colors cursor-pointer"
		>
			İptal
		</button>
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
		<button
			onclick={cancelCCMatch}
			class="text-xs font-medium px-3 py-1.5 rounded-lg bg-gray-200 text-gray-700 hover:bg-gray-300 transition-colors cursor-pointer"
		>
			İptal
		</button>
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
			<span class="bg-teal-700 text-white rounded-full w-4 h-4 text-[10px] flex items-center justify-center">✓</span>
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
			<input
				id="cf-start"
				type="date"
				bind:value={filterStartDate}
				class="text-sm border border-gray-300 rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-teal-500 focus:border-teal-500 outline-none"
			/>
		</div>
		<div class="flex flex-col gap-1">
			<label class="text-xs text-gray-500 font-medium" for="cf-end">Bitiş</label>
			<input
				id="cf-end"
				type="date"
				bind:value={filterEndDate}
				class="text-sm border border-gray-300 rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-teal-500 focus:border-teal-500 outline-none"
			/>
		</div>
		<div class="flex flex-col gap-1 flex-1 min-w-[200px]">
			<label class="text-xs text-gray-500 font-medium" for="cf-search">Arama</label>
			<input
				id="cf-search"
				type="text"
				placeholder="Açıklama, banka, cari kodu..."
				bind:value={filterSearch}
				oninput={handleSearchInput}
				class="text-sm border border-gray-300 rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-teal-500 focus:border-teal-500 outline-none"
			/>
		</div>
		<button
			onclick={applyDateFilter}
			class="px-4 py-1.5 bg-teal-700 text-white text-sm font-medium rounded-lg hover:bg-teal-800 transition-colors cursor-pointer"
		>Uygula</button>
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
