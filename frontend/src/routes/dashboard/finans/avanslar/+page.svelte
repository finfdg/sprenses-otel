<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge, { type BadgeType } from '$lib/components/StatusBadge.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { Plus, Pencil, Trash2, X, Check, Wallet, Hourglass, CircleCheck, Search } from 'lucide-svelte';

	// Sabitler
	const STATUS_LABELS: Record<string, string> = { pending: 'Bekliyor', received: 'Alındı', cancelled: 'İptal' };
	const STATUS_BADGE: Record<string, BadgeType> = { pending: 'warning', received: 'success', cancelled: 'neutral' };
	const CURRENCIES = ['EUR', 'USD', 'TRY'];
	const CURRENCY_SYMBOLS: Record<string, string> = { EUR: '€', USD: '$', TRY: '₺' };

	// Türetilmiş
	let canUse = $derived(hasPermission('finance.avanslar', 'use'));

	// Veri state
	let advances = $state<any[]>([]);
	let summary = $state<Record<string, { pending: number; received: number; pending_count: number; received_count: number }>>({});
	let loading = $state(true);
	let total = $state(0);
	let page = $state(1);
	let pageSize = $state(50);

	// Filtre state
	let statusFilter = $state('');
	let currencyFilter = $state('');
	let searchInput = $state(''); // input'a bağlı ham değer
	let search = $state(''); // 300ms debounce sonrası sorguya giden değer

	// Form modal state
	let showModal = $state(false);
	let editItem = $state<any>(null);
	let form = $state<{ agency_name: string; amount: number | null; currency: string; advance_date: string; notes: string }>({
		agency_name: '', amount: null, currency: 'EUR', advance_date: '', notes: '',
	});
	let saving = $state(false);
	let formError = $state('');
	let fieldErrors = $state<{ agency_name?: string; amount?: string; advance_date?: string }>({});

	// Eşleştirme modal state
	let showMatchModal = $state(false);
	let matchItem = $state<any>(null);
	let matchForm = $state<{ received_date: string; received_amount: number | null; bank_transaction_id: number | null }>({
		received_date: '', received_amount: null, bank_transaction_id: null,
	});
	let matchSaving = $state(false);

	// Silme onayı
	let deleteItem = $state<any>(null);
	let showDeleteConfirm = $state(false);

	// Sayfa toplamı — para birimi bazında ayrıştırır (karışık para birimlerini TOPLAMAZ)
	let pageTotals = $derived.by(() => {
		const m: Record<string, { amount: number; received: number }> = {};
		for (const a of advances) {
			const c = a.currency || 'EUR';
			if (!m[c]) m[c] = { amount: 0, received: 0 };
			m[c].amount += a.amount || 0;
			m[c].received += a.received_amount || 0;
		}
		return m;
	});
	let receivedCards = $derived(Object.entries(summary).filter(([, s]) => s && s.received > 0));

	// Formatlama
	function fmt(n: number | null | undefined, currency = 'EUR'): string {
		if (n == null) return '—';
		const sym = CURRENCY_SYMBOLS[currency] || currency;
		return `${sym}${n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
	}
	function fmtDate(d: string | null): string {
		if (!d) return '—';
		return new Date(d + 'T00:00:00').toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}

	// Veri yükleme
	async function loadData() {
		loading = true;
		try {
			const params = new URLSearchParams();
			params.set('page', String(page));
			params.set('page_size', String(pageSize));
			if (statusFilter) params.set('status', statusFilter);
			if (currencyFilter) params.set('currency', currencyFilter);
			if (search.trim()) params.set('search', search.trim());

			const [listData, summaryData] = await Promise.all([
				api.get<any>(`/finance/avanslar/?${params}`),
				api.get<any>('/finance/avanslar/summary'),
			]);
			advances = listData.items;
			total = listData.total;
			summary = summaryData;
		} catch (err) {
			console.error('Avans verileri yüklenemedi:', err);
			showToast('Avans verileri yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	// CRUD
	function openAdd() {
		editItem = null;
		form = { agency_name: '', amount: null, currency: 'EUR', advance_date: '', notes: '' };
		formError = '';
		fieldErrors = {};
		showModal = true;
	}

	function openEdit(adv: any) {
		editItem = adv;
		form = { agency_name: adv.agency_name, amount: adv.amount, currency: adv.currency, advance_date: adv.advance_date, notes: adv.notes || '' };
		formError = '';
		fieldErrors = {};
		showModal = true;
	}

	function validate(): boolean {
		const e: { agency_name?: string; amount?: string; advance_date?: string } = {};
		if (!form.agency_name.trim()) e.agency_name = 'Acente/Operatör adı zorunludur';
		if (!form.amount || form.amount <= 0) e.amount = 'Tutar sıfırdan büyük olmalıdır';
		if (!form.advance_date) e.advance_date = 'Avans tarihi zorunludur';
		fieldErrors = e;
		return Object.keys(e).length === 0;
	}

	async function handleSave() {
		if (!validate()) return;
		saving = true;
		formError = '';
		try {
			if (editItem) {
				await api.patch(`/finance/avanslar/${editItem.id}`, form);
			} else {
				await api.post('/finance/avanslar/', form);
			}
			showModal = false;
			showToast(editItem ? 'Avans güncellendi' : 'Avans eklendi', 'success');
			await loadData();
		} catch (err: any) {
			console.error('Avans kaydetme hatası:', err);
			formError = err?.message || 'Kaydetme sırasında hata oluştu';
		} finally {
			saving = false;
		}
	}

	function openDelete(adv: any) {
		deleteItem = adv;
		showDeleteConfirm = true;
	}

	async function confirmDelete() {
		if (!deleteItem) return;
		const item = deleteItem;
		try {
			await api.delete(`/finance/avanslar/${item.id}`);
			showToast('Avans silindi', 'success');
			await loadData();
		} catch (err: any) {
			console.error('Avans silme hatası:', err);
			showToast(err?.message || 'Silme sırasında hata oluştu', 'error');
		} finally {
			deleteItem = null;
		}
	}

	function openMatch(adv: any) {
		matchItem = adv;
		matchForm = { received_date: new Date().toISOString().split('T')[0], received_amount: adv.amount, bank_transaction_id: null };
		showMatchModal = true;
	}

	async function handleMatch() {
		if (!matchItem) return;
		matchSaving = true;
		try {
			await api.post(`/finance/avanslar/${matchItem.id}/match`, matchForm);
			showMatchModal = false;
			matchItem = null;
			showToast('Avans alındı olarak işaretlendi', 'success');
			await loadData();
		} catch (err: any) {
			console.error('Avans eşleştirme hatası:', err);
			showToast(err?.message || 'Eşleştirme sırasında hata oluştu', 'error');
		} finally {
			matchSaving = false;
		}
	}

	async function handleStatusChange(adv: any, newStatus: string) {
		try {
			await api.patch(`/finance/avanslar/${adv.id}`, { status: newStatus });
			await loadData();
		} catch (err: any) {
			console.error('Durum güncelleme hatası:', err);
			showToast(err?.message || 'Durum güncellenirken hata oluştu', 'error');
		}
	}

	// Arama debounce (300ms): searchInput → search
	let searchTimer: ReturnType<typeof setTimeout>;
	$effect(() => {
		const v = searchInput;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { search = v.trim(); }, 300);
		return () => clearTimeout(searchTimer);
	});

	// Filtre değişiminde sayfayı 1'e al ve yeniden yükle (ilk yüklemede tetiklenmez)
	let filterKey = $derived(`${statusFilter}|${currencyFilter}|${search}`);
	let prevFilterKey = '';
	$effect(() => {
		const fk = filterKey;
		if (prevFilterKey && fk !== prevFilterKey) { page = 1; loadData(); }
		prevFilterKey = fk;
	});

	function changePage(p: number) { page = p; loadData(); }
	function changePageSize(s: number) { pageSize = s; page = 1; loadData(); }

	// Lifecycle
	let unsubFinance: (() => void) | null = null;
	onMount(() => {
		loadData();
		unsubFinance = onWsEvent('finance_updated', () => { loadData(); });
	});
	onDestroy(() => { unsubFinance?.(); });
</script>

<svelte:head><title>Alınan Avanslar · Sprenses</title></svelte:head>

<div class="space-y-5 sm:space-y-6">
	<!-- Başlık -->
	<PageHeader title="Alınan Avanslar" description="Acente ve operatörlerden alınan avansları takip edin ve banka tahsilatıyla eşleştirin">
		{#snippet actions()}
			{#if canUse}
				<Button onclick={openAdd}><Plus size={16} /> Yeni Avans</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<!-- Özet kartları (para birimi bazında, doğru) -->
	{#if !loading && (Object.keys(summary).length > 0)}
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
			{#each CURRENCIES as cur (cur)}
				{@const s = summary[cur]}
				{#if s && s.pending_count > 0}
					<StatCard label={`${cur} Bekleyen`} value={fmt(s.pending, cur)} accent="amber" icon={Hourglass} hint={`${s.pending_count} kayıt`} />
				{/if}
			{/each}
			{#each receivedCards as [cur, s] (cur)}
				<StatCard label={`${cur} Alınan`} value={fmt(s.received, cur)} accent="emerald" icon={CircleCheck} hint={`${s.received_count} kayıt`} />
			{/each}
		</div>
	{/if}

	<!-- Filtreler -->
	<div class="flex flex-col sm:flex-row gap-2 sm:gap-3 sm:items-center">
		<div class="relative w-full sm:w-72">
			<Search size={16} class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" aria-hidden="true" />
			<input
				type="search"
				placeholder="Acente/Operatör ara…"
				bind:value={searchInput}
				aria-label="Acente veya operatör ara"
				class="w-full pl-9 pr-9 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
			/>
			{#if searchInput}
				<button onclick={() => searchInput = ''} aria-label="Aramayı temizle" class="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 cursor-pointer">
					<X size={16} />
				</button>
			{/if}
		</div>
		<select bind:value={statusFilter} aria-label="Duruma göre filtrele" class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer flex-1 sm:flex-none">
			<option value="">Tüm Durumlar</option>
			<option value="pending">Bekliyor</option>
			<option value="received">Alındı</option>
			<option value="cancelled">İptal</option>
		</select>
		<select bind:value={currencyFilter} aria-label="Para birimine göre filtrele" class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer flex-1 sm:flex-none">
			<option value="">Tüm Para Birimleri</option>
			{#each CURRENCIES as cur (cur)}<option value={cur}>{cur}</option>{/each}
		</select>
		<span class="text-sm text-gray-500 sm:ml-auto">{total} kayıt</span>
	</div>

	<!-- Liste -->
	<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
		{#if loading}
			<TableSkeleton rows={6} columns={5} />
		{:else if advances.length === 0}
			<EmptyState
				icon={Wallet}
				title="Henüz avans kaydı yok"
				description={search || statusFilter || currencyFilter ? 'Filtrelere uygun avans bulunamadı.' : "İlk avansı eklemek için 'Yeni Avans' butonunu kullanın."}
				ctaText={canUse && !(search || statusFilter || currencyFilter) ? 'Yeni Avans' : ''}
				onCta={canUse && !(search || statusFilter || currencyFilter) ? openAdd : null}
			/>
		{:else}
			<!-- Masaüstü tablo -->
			<div class="hidden sm:block overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-gray-200 bg-gray-50 text-left">
							<th class="px-4 py-3 font-medium text-gray-600">Acente/Operatör</th>
							<th class="px-4 py-3 font-medium text-gray-600 text-right">Tutar</th>
							<th class="px-4 py-3 font-medium text-gray-600 text-center hidden md:table-cell">Avans Tarihi</th>
							<th class="px-4 py-3 font-medium text-gray-600 text-center">Durum</th>
							<th class="px-4 py-3 font-medium text-gray-600 text-right">Alınan Tutar</th>
							{#if canUse}<th class="px-4 py-3 font-medium text-gray-600 text-right">İşlemler</th>{/if}
						</tr>
					</thead>
					<tbody>
						{#each advances as adv (adv.id)}
							<tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors">
								<td class="px-4 py-3">
									<div class="font-medium text-gray-900">{adv.agency_name}</div>
									{#if adv.notes}<div class="text-xs text-gray-500 mt-0.5 truncate max-w-[220px]" title={adv.notes}>{adv.notes}</div>{/if}
									<div class="text-xs text-gray-500 mt-0.5 md:hidden">{fmtDate(adv.advance_date)}</div>
								</td>
								<td class="px-4 py-3 text-right font-semibold text-gray-900 whitespace-nowrap">{fmt(adv.amount, adv.currency)}</td>
								<td class="px-4 py-3 text-center text-gray-600 hidden md:table-cell whitespace-nowrap">{fmtDate(adv.advance_date)}</td>
								<td class="px-4 py-3 text-center">
									<StatusBadge type={STATUS_BADGE[adv.status] ?? 'neutral'}>{STATUS_LABELS[adv.status] ?? adv.status}</StatusBadge>
								</td>
								<td class="px-4 py-3 text-right whitespace-nowrap">
									{#if adv.received_amount != null}
										<span class="font-semibold text-emerald-700">{fmt(adv.received_amount, adv.currency)}</span>
									{:else}
										<span class="text-gray-400">—</span>
									{/if}
								</td>
								{#if canUse}
									<td class="px-4 py-3">
										<div class="flex items-center justify-end gap-1">
											{#if adv.status === 'pending'}
												<button onclick={() => openMatch(adv)} aria-label="Alındı olarak işaretle" title="Alındı olarak işaretle" class="p-2 text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors cursor-pointer"><Check size={16} /></button>
												<button onclick={() => handleStatusChange(adv, 'cancelled')} aria-label="İptal et" title="İptal et" class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"><X size={16} /></button>
											{/if}
											<button onclick={() => openEdit(adv)} aria-label="Düzenle" title="Düzenle" class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"><Pencil size={16} /></button>
											{#if adv.status !== 'received'}
												<button onclick={() => openDelete(adv)} aria-label="Sil" title="Sil" class="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors cursor-pointer"><Trash2 size={16} /></button>
											{/if}
										</div>
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
					{#if Object.keys(pageTotals).length > 0}
						<tfoot>
							<tr class="border-t-2 border-gray-200 bg-gray-50">
								<td class="px-4 py-3 font-semibold text-gray-700 align-top">Bu sayfa</td>
								<td class="px-4 py-3 text-right font-bold text-gray-900 whitespace-nowrap align-top">
									{#each Object.entries(pageTotals) as [cur, t] (cur)}<div>{fmt(t.amount, cur)}</div>{/each}
								</td>
								<td class="px-4 py-3 hidden md:table-cell"></td>
								<td class="px-4 py-3"></td>
								<td class="px-4 py-3 text-right font-bold text-emerald-700 whitespace-nowrap align-top">
									{#each Object.entries(pageTotals) as [cur, t] (cur)}<div>{t.received > 0 ? fmt(t.received, cur) : ''}</div>{/each}
								</td>
								{#if canUse}<td class="px-4 py-3"></td>{/if}
							</tr>
						</tfoot>
					{/if}
				</table>
			</div>

			<!-- Mobil kart görünümü -->
			<div class="sm:hidden divide-y divide-gray-100">
				{#each advances as adv (adv.id)}
					<div class="p-3">
						<div class="flex items-start justify-between gap-2 mb-2">
							<div class="min-w-0 flex-1">
								<div class="font-medium text-gray-900">{adv.agency_name}</div>
								<div class="text-xs text-gray-500 mt-0.5">{fmtDate(adv.advance_date)}</div>
							</div>
							<StatusBadge type={STATUS_BADGE[adv.status] ?? 'neutral'}>{STATUS_LABELS[adv.status] ?? adv.status}</StatusBadge>
						</div>
						{#if adv.notes}<p class="text-xs text-gray-500 mb-2 line-clamp-2">{adv.notes}</p>{/if}
						<div class="flex items-end justify-between gap-2">
							<div>
								<div class="text-base font-bold text-gray-900">{fmt(adv.amount, adv.currency)}</div>
								{#if adv.received_amount != null}<div class="text-xs text-emerald-700 mt-0.5">Alınan: {fmt(adv.received_amount, adv.currency)}</div>{/if}
							</div>
							{#if canUse}
								<div class="flex items-center gap-1.5 shrink-0">
									{#if adv.status === 'pending'}
										<button onclick={() => openMatch(adv)} aria-label="Alındı olarak işaretle" class="p-2.5 text-emerald-700 bg-emerald-50 rounded-lg active:scale-95 cursor-pointer"><Check size={16} /></button>
										<button onclick={() => handleStatusChange(adv, 'cancelled')} aria-label="İptal et" class="p-2.5 text-gray-600 bg-gray-100 rounded-lg active:scale-95 cursor-pointer"><X size={16} /></button>
									{/if}
									<button onclick={() => openEdit(adv)} aria-label="Düzenle" class="p-2.5 text-gray-600 bg-gray-100 rounded-lg active:scale-95 cursor-pointer"><Pencil size={16} /></button>
									{#if adv.status !== 'received'}
										<button onclick={() => openDelete(adv)} aria-label="Sil" class="p-2.5 text-red-600 bg-red-50 rounded-lg active:scale-95 cursor-pointer"><Trash2 size={16} /></button>
									{/if}
								</div>
							{/if}
						</div>
					</div>
				{/each}
				<!-- Mobil sayfa toplamı -->
				<div class="p-3 bg-gray-50 border-t-2 border-gray-200 flex items-start justify-between gap-2">
					<span class="font-semibold text-sm text-gray-700">Bu sayfa</span>
					<div class="text-right">
						{#each Object.entries(pageTotals) as [cur, t] (cur)}
							<div class="text-sm font-bold text-gray-900">{fmt(t.amount, cur)}{#if t.received > 0}<span class="text-emerald-700 font-semibold ml-2">↓ {fmt(t.received, cur)}</span>{/if}</div>
						{/each}
					</div>
				</div>
			</div>

			<!-- Sayfalama -->
			{#if total > pageSize || page > 1}
				<div class="px-4 border-t border-gray-100">
					<Pagination {page} {pageSize} {total} onPageChange={changePage} onPageSizeChange={changePageSize} />
				</div>
			{/if}
		{/if}
	</div>
</div>

<!-- Oluştur / Düzenle Modal -->
<Modal bind:show={showModal} title={editItem ? 'Avansı Düzenle' : 'Yeni Avans'} maxWidth="max-w-lg">
	<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4" novalidate>
		{#if formError}
			<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700" role="alert">{formError}</div>
		{/if}

		<div>
			<label for="agency_name" class="block text-sm font-medium text-gray-700 mb-1">Acente/Operatör Adı <span class="text-red-600">*</span></label>
			<input
				id="agency_name"
				type="text"
				bind:value={form.agency_name}
				aria-invalid={!!fieldErrors.agency_name}
				aria-describedby={fieldErrors.agency_name ? 'agency_name-error' : undefined}
				placeholder="Acente veya operatör adını girin"
				class="w-full px-3 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 {fieldErrors.agency_name ? 'border-red-400' : 'border-gray-300'}"
			/>
			{#if fieldErrors.agency_name}<p id="agency_name-error" class="text-xs text-red-600 mt-1">{fieldErrors.agency_name}</p>{/if}
		</div>

		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="amount" class="block text-sm font-medium text-gray-700 mb-1">Tutar <span class="text-red-600">*</span></label>
				<MoneyInput id="amount" bind:value={form.amount} currency={form.currency} min={0} placeholder="0,00" ariaInvalid={!!fieldErrors.amount} ariaDescribedby={fieldErrors.amount ? 'amount-error' : undefined} />
				{#if fieldErrors.amount}<p id="amount-error" class="text-xs text-red-600 mt-1">{fieldErrors.amount}</p>{/if}
			</div>
			<div>
				<label for="currency" class="block text-sm font-medium text-gray-700 mb-1">Para Birimi</label>
				<select id="currency" bind:value={form.currency} class="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer">
					{#each CURRENCIES as cur (cur)}<option value={cur}>{cur} ({CURRENCY_SYMBOLS[cur]})</option>{/each}
				</select>
			</div>
		</div>

		<div>
			<label for="advance_date" class="block text-sm font-medium text-gray-700 mb-1">Avans Tarihi <span class="text-red-600">*</span></label>
			<input
				id="advance_date"
				type="date"
				bind:value={form.advance_date}
				aria-invalid={!!fieldErrors.advance_date}
				aria-describedby={fieldErrors.advance_date ? 'advance_date-error' : undefined}
				class="w-full px-3 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 {fieldErrors.advance_date ? 'border-red-400' : 'border-gray-300'}"
			/>
			{#if fieldErrors.advance_date}<p id="advance_date-error" class="text-xs text-red-600 mt-1">{fieldErrors.advance_date}</p>{/if}
		</div>

		<div>
			<label for="notes" class="block text-sm font-medium text-gray-700 mb-1">Notlar</label>
			<textarea id="notes" bind:value={form.notes} rows="3" placeholder="İsteğe bağlı notlar" class="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"></textarea>
		</div>

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="secondary" onclick={() => showModal = false}>İptal</Button>
			<Button type="submit" loading={saving}>{editItem ? 'Güncelle' : 'Kaydet'}</Button>
		</div>
	</form>
</Modal>

<!-- Eşleştirme (Alındı) Modal -->
<Modal bind:show={showMatchModal} title="Avans Alındı" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); handleMatch(); }} class="space-y-4">
		{#if matchItem}
			<div class="p-3 bg-gray-50 rounded-lg text-sm">
				<div class="font-medium text-gray-900">{matchItem.agency_name}</div>
				<div class="text-gray-500 mt-1">Beklenen: {fmt(matchItem.amount, matchItem.currency)}</div>
			</div>
		{/if}
		<div>
			<label for="received_date" class="block text-sm font-medium text-gray-700 mb-1">Alınma Tarihi <span class="text-red-600">*</span></label>
			<input id="received_date" type="date" bind:value={matchForm.received_date} class="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
		</div>
		<div>
			<label for="received_amount" class="block text-sm font-medium text-gray-700 mb-1">Alınan Tutar <span class="text-red-600">*</span></label>
			<MoneyInput id="received_amount" bind:value={matchForm.received_amount} currency={matchItem?.currency} min={0} placeholder="0,00" />
		</div>
		<div class="flex justify-end gap-2 pt-2">
			<Button variant="secondary" onclick={() => showMatchModal = false}>İptal</Button>
			<Button type="submit" loading={matchSaving}><Check size={16} /> Alındı İşaretle</Button>
		</div>
	</form>
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Avansı Sil"
	message={deleteItem ? `${deleteItem.agency_name} acentesine ait ${fmt(deleteItem.amount, deleteItem.currency)} tutarındaki avans kaydını silmek istediğinize emin misiniz?` : ''}
	confirmText="Sil"
	cancelText="Vazgeç"
	danger
	onConfirm={confirmDelete}
/>
