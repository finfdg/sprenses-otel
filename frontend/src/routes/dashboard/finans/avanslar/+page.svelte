<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { Plus, Pencil, Trash2, X, Check, Wallet } from 'lucide-svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';

	const STATUS_LABELS: Record<string, string> = {
		pending: 'Bekliyor',
		received: 'Alındı',
		cancelled: 'İptal',
	};
	const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
		pending: { bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200' },
		received: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
		cancelled: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
	};
	const CURRENCIES = ['EUR', 'USD', 'TRY'];
	const CURRENCY_SYMBOLS: Record<string, string> = { EUR: '€', USD: '$', TRY: '₺' };

	let canUse = $derived(hasPermission('finance.avanslar', 'use'));

	// State
	let advances = $state<any[]>([]);
	let summary = $state<Record<string, { pending: number; received: number; pending_count: number; received_count: number }>>({});
	let loading = $state(true);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	const pageSize = 50;

	// Computed totals
	let totalAmount = $derived(advances.reduce((s, a) => s + (a.amount || 0), 0));
	let totalReceived = $derived(advances.reduce((s, a) => s + (a.received_amount || 0), 0));

	// Filters
	let statusFilter = $state('');
	let currencyFilter = $state('');
	let search = $state('');

	// Modal state
	let showModal = $state(false);
	let editItem = $state<any>(null);
	let form = $state<{
		agency_name: string;
		amount: number | null;
		currency: string;
		advance_date: string;
		notes: string;
	}>({
		agency_name: '',
		amount: null,
		currency: 'EUR',
		advance_date: '',
		notes: '',
	});
	let saving = $state(false);
	let formError = $state('');

	// Match modal
	let showMatchModal = $state(false);
	let matchItem = $state<any>(null);
	let matchForm = $state<{
		received_date: string;
		received_amount: number | null;
		bank_transaction_id: number | null;
	}>({
		received_date: '',
		received_amount: null,
		bank_transaction_id: null,
	});
	let matchSaving = $state(false);

	// Delete confirm
	let deleteItem = $state<any>(null);
	let showDeleteConfirm = $state(false);

	function fmt(n: number | null | undefined, currency = 'EUR'): string {
		if (n == null) return '-';
		const sym = CURRENCY_SYMBOLS[currency] || currency;
		return `${sym}${n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
	}

	function fmtDate(d: string | null): string {
		if (!d) return '-';
		return new Date(d + 'T00:00:00').toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}

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
			pages = listData.pages;
			summary = summaryData;
		} catch (err) {
			console.error('Avans verileri yüklenemedi:', err);
		} finally {
			loading = false;
		}
	}

	function openAdd() {
		editItem = null;
		form = { agency_name: '', amount: null, currency: 'EUR', advance_date: '', notes: '' };
		formError = '';
		showModal = true;
	}

	function openEdit(adv: any) {
		editItem = adv;
		form = {
			agency_name: adv.agency_name,
			amount: adv.amount,
			currency: adv.currency,
			advance_date: adv.advance_date,
			notes: adv.notes || '',
		};
		formError = '';
		showModal = true;
	}

	async function handleSave() {
		if (!form.agency_name.trim()) { formError = 'Acente/Operatör adı zorunludur'; return; }
		if (!form.amount || form.amount <= 0) { formError = 'Tutar sıfırdan büyük olmalıdır'; return; }
		if (!form.advance_date) { formError = 'Avans tarihi zorunludur'; return; }

		saving = true;
		formError = '';
		try {
			if (editItem) {
				await api.patch(`/finance/avanslar/${editItem.id}`, form);
			} else {
				await api.post('/finance/avanslar/', form);
			}
			showModal = false;
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
		try {
			await api.delete(`/finance/avanslar/${deleteItem.id}`);
			showDeleteConfirm = false;
			deleteItem = null;
			await loadData();
		} catch (err: any) {
			console.error('Avans silme hatası:', err);
			showToast(err?.message || 'Silme sırasında hata oluştu', 'error');
		}
	}

	function openMatch(adv: any) {
		matchItem = adv;
		matchForm = {
			received_date: new Date().toISOString().split('T')[0],
			received_amount: adv.amount,
			bank_transaction_id: null,
		};
		showMatchModal = true;
	}

	async function handleMatch() {
		if (!matchItem) return;
		matchSaving = true;
		try {
			await api.post(`/finance/avanslar/${matchItem.id}/match`, matchForm);
			showMatchModal = false;
			matchItem = null;
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

	let filterVersion = $derived(`${statusFilter}|${currencyFilter}|${search}`);
	let prevFilterVersion = '';

	let unsubFinance: (() => void) | null = null;

	onMount(() => {
		loadData();
		unsubFinance = onWsEvent('finance_updated', () => { loadData(); });
	});

	onDestroy(() => { unsubFinance?.(); });

	// Filtre değişikliklerinde yeniden yükle
	$effect(() => {
		const fv = filterVersion;
		if (prevFilterVersion && fv !== prevFilterVersion) {
			page = 1;
			loadData();
		}
		prevFilterVersion = fv;
	});
</script>

<div class="space-y-4 sm:space-y-6">
	<!-- Header -->
	<div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
		<div>
			<h1 class="text-2xl font-semibold text-gray-900">Alınan Avanslar</h1>
			<p class="text-xs sm:text-sm text-gray-500 mt-1">Acente ve operatörlerden alınan avansları yönetin</p>
		</div>
		{#if canUse}
			<button
				onclick={openAdd}
				class="inline-flex items-center gap-2 px-4 py-2.5 bg-teal-600 text-white rounded-xl hover:bg-teal-700 transition-colors text-sm font-medium cursor-pointer"
			>
				<Plus size={16} />
				Yeni Avans
			</button>
		{/if}
	</div>

	<!-- Summary Cards -->
	<div class="flex flex-wrap gap-2 sm:gap-4">
		{#each CURRENCIES as cur}
			{@const s = summary[cur]}
			{#if s}
				<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 shadow-sm flex-1 min-w-[140px]">
					<div class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">{cur} Bekleyen</div>
					<div class="mt-1 text-base sm:text-xl font-bold text-yellow-700">{fmt(s.pending, cur)}</div>
					<div class="text-[10px] sm:text-xs text-gray-400 mt-1">{s.pending_count} kayıt</div>
				</div>
			{/if}
		{/each}
		{#if Object.values(summary).some(s => s.received > 0)}
			<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 shadow-sm flex-1 min-w-[140px]">
				<div class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Toplam Alınan</div>
				<div class="mt-1 text-base sm:text-xl font-bold text-emerald-700">
					{Object.entries(summary).filter(([, s]) => s.received > 0).map(([c, s]) => fmt(s.received, c)).join(' + ')}
				</div>
				<div class="text-[10px] sm:text-xs text-gray-400 mt-1">{Object.values(summary).reduce((a, s) => a + (s?.received_count || 0), 0)} kayıt</div>
			</div>
		{/if}
	</div>

	<!-- Filters -->
	<div class="flex flex-wrap gap-2 sm:gap-3 items-center">
		<input
			type="text"
			placeholder="Acente/Operatör ara..."
			bind:value={search}
			class="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 w-full sm:w-64"
		/>
		<select
			bind:value={statusFilter}
			class="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer flex-1 sm:flex-none"
		>
			<option value="">Tüm Durumlar</option>
			<option value="pending">Bekliyor</option>
			<option value="received">Alındı</option>
			<option value="cancelled">İptal</option>
		</select>
		<select
			bind:value={currencyFilter}
			class="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer flex-1 sm:flex-none"
		>
			<option value="">Tüm Para Birimleri</option>
			{#each CURRENCIES as cur}
				<option value={cur}>{cur}</option>
			{/each}
		</select>
		<span class="text-sm text-gray-500 ml-auto">{total} kayıt</span>
	</div>

	<!-- Table -->
	<div class="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
		{#if loading}
			<TableSkeleton rows={5} columns={5} />
		{:else if advances.length === 0}
			<EmptyState
				icon={Wallet}
				title="Henüz avans kaydı yok"
				description="İlk avansı eklemek için yukarıdaki 'Yeni Avans' butonunu kullanın"
				ctaText={canUse ? 'Yeni Avans' : ''}
				onCta={canUse ? openAdd : null}
			/>
		{:else}
			<!-- Masaüstü tablo -->
			<div class="hidden sm:block overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-gray-100 bg-gray-50/50">
							<th class="text-left px-4 py-3 font-medium text-gray-600">Acente/Operatör</th>
							<th class="text-right px-4 py-3 font-medium text-gray-600">Tutar</th>
							<th class="text-center px-4 py-3 font-medium text-gray-600">Para Birimi</th>
							<th class="text-center px-4 py-3 font-medium text-gray-600 hidden md:table-cell">Avans Tarihi</th>
							<th class="text-center px-4 py-3 font-medium text-gray-600">Durum</th>
							<th class="text-right px-4 py-3 font-medium text-gray-600">Alınan Tutar</th>
							{#if canUse}
								<th class="text-center px-4 py-3 font-medium text-gray-600">İşlemler</th>
							{/if}
						</tr>
					</thead>
					<tbody>
						{#each advances as adv (adv.id)}
							{@const sc = STATUS_COLORS[adv.status] || STATUS_COLORS.pending}
							<tr class="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
								<td class="px-4 py-3">
									<div class="font-medium text-gray-800">{adv.agency_name}</div>
									{#if adv.notes}
										<div class="text-xs text-gray-400 mt-0.5 truncate max-w-[200px]" title={adv.notes}>{adv.notes}</div>
									{/if}
									<div class="text-xs text-gray-400 mt-0.5 md:hidden">{fmtDate(adv.advance_date)}</div>
								</td>
								<td class="px-4 py-3 text-right font-semibold text-gray-800 whitespace-nowrap">{fmt(adv.amount, adv.currency)}</td>
								<td class="px-4 py-3 text-center">
									<span class="text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{adv.currency}</span>
								</td>
								<td class="px-4 py-3 text-center text-gray-600 hidden md:table-cell">{fmtDate(adv.advance_date)}</td>
								<td class="px-4 py-3 text-center">
									<span class="inline-flex px-2.5 py-1 rounded-full text-xs font-medium border {sc.bg} {sc.text} {sc.border}">
										{STATUS_LABELS[adv.status] || adv.status}
									</span>
								</td>
								<td class="px-4 py-3 text-right">
									{#if adv.received_amount != null}
										<span class="font-semibold text-emerald-700">{fmt(adv.received_amount, adv.currency)}</span>
									{:else}
										<span class="text-gray-300">-</span>
									{/if}
								</td>
								{#if canUse}
									<td class="px-4 py-3 text-center">
										<div class="flex items-center justify-center gap-0.5">
											{#if adv.status === 'pending'}
												<button onclick={() => openMatch(adv)} class="p-2 text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors cursor-pointer" title="Alındı olarak işaretle">
													<Check size={16} />
												</button>
												<button onclick={() => handleStatusChange(adv, 'cancelled')} class="p-2 text-red-500 hover:bg-red-50 rounded-lg transition-colors cursor-pointer" title="İptal et">
													<X size={16} />
												</button>
											{/if}
											<button onclick={() => openEdit(adv)} class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer" title="Düzenle">
												<Pencil size={16} />
											</button>
											{#if adv.status !== 'received'}
												<button onclick={() => openDelete(adv)} class="p-2 text-red-400 hover:bg-red-50 rounded-lg transition-colors cursor-pointer" title="Sil">
													<Trash2 size={16} />
												</button>
											{/if}
										</div>
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
					<tfoot>
						<tr class="border-t-2 border-gray-200 bg-gray-50">
							<td class="px-4 py-3 font-semibold text-gray-800">Toplam</td>
							<td class="px-4 py-3 text-right font-bold text-gray-900 whitespace-nowrap">{fmt(totalAmount, 'EUR')}</td>
							<td class="px-4 py-3"></td>
							<td class="px-4 py-3 hidden md:table-cell"></td>
							<td class="px-4 py-3"></td>
							<td class="px-4 py-3 text-right font-bold text-emerald-700 whitespace-nowrap">{fmt(totalReceived, 'EUR')}</td>
							{#if canUse}
								<td class="px-4 py-3"></td>
							{/if}
						</tr>
					</tfoot>
				</table>
			</div>

			<!-- Mobil kart görünümü -->
			<div class="sm:hidden divide-y divide-gray-50">
				{#each advances as adv (adv.id)}
					{@const sc = STATUS_COLORS[adv.status] || STATUS_COLORS.pending}
					<div class="px-3 py-3">
						<div class="flex items-start justify-between gap-2 mb-1.5">
							<div class="min-w-0 flex-1">
								<div class="font-medium text-sm text-gray-800">{adv.agency_name}</div>
								<div class="text-xs text-gray-400 mt-0.5">{fmtDate(adv.advance_date)}</div>
							</div>
							<span class="inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium border shrink-0 {sc.bg} {sc.text} {sc.border}">
								{STATUS_LABELS[adv.status] || adv.status}
							</span>
						</div>
						{#if adv.notes}
							<p class="text-xs text-gray-400 mb-1.5 truncate">{adv.notes}</p>
						{/if}
						<div class="flex items-center justify-between gap-2">
							<div>
								<span class="text-sm font-bold text-gray-800">{fmt(adv.amount, adv.currency)}</span>
								{#if adv.received_amount != null}
									<span class="text-xs text-emerald-600 ml-2">Alınan: {fmt(adv.received_amount, adv.currency)}</span>
								{/if}
							</div>
							{#if canUse}
								<div class="flex items-center gap-1">
									{#if adv.status === 'pending'}
										<button onclick={() => openMatch(adv)} class="px-2.5 py-1.5 text-[10px] font-semibold bg-emerald-50 text-emerald-700 rounded-lg active:scale-95 cursor-pointer">Alındı</button>
										<button onclick={() => handleStatusChange(adv, 'cancelled')} class="px-2.5 py-1.5 text-[10px] font-semibold bg-red-50 text-red-600 rounded-lg active:scale-95 cursor-pointer">İptal</button>
									{/if}
									<button onclick={() => openEdit(adv)} class="px-2.5 py-1.5 text-[10px] font-semibold bg-gray-100 text-gray-600 rounded-lg active:scale-95 cursor-pointer">Düzenle</button>
									{#if adv.status !== 'received'}
										<button onclick={() => openDelete(adv)} class="px-2.5 py-1.5 text-[10px] font-semibold bg-red-50 text-red-500 rounded-lg active:scale-95 cursor-pointer">Sil</button>
									{/if}
								</div>
							{/if}
						</div>
					</div>
				{/each}
				<!-- Mobil toplam -->
				<div class="px-3 py-3 bg-gray-50 border-t-2 border-gray-200">
					<div class="flex items-center justify-between">
						<span class="font-semibold text-sm text-gray-800">Toplam</span>
						<div class="text-right">
							<div class="text-sm font-bold text-gray-900">{fmt(totalAmount, 'EUR')}</div>
							{#if totalReceived > 0}
								<div class="text-xs font-semibold text-emerald-700">Alınan: {fmt(totalReceived, 'EUR')}</div>
							{/if}
						</div>
					</div>
				</div>
			</div>

			<!-- Pagination -->
			{#if pages > 1}
				<div class="flex items-center justify-between px-4 py-3 border-t border-gray-100">
					<span class="text-xs text-gray-500">Sayfa {page} / {pages}</span>
					<div class="flex gap-1">
						<button
							onclick={() => { page = Math.max(1, page - 1); loadData(); }}
							disabled={page <= 1}
							class="px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
						>
							Önceki
						</button>
						<button
							onclick={() => { page = Math.min(pages, page + 1); loadData(); }}
							disabled={page >= pages}
							class="px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
						>
							Sonraki
						</button>
					</div>
				</div>
			{/if}
		{/if}
	</div>
</div>

<!-- Create/Edit Modal -->
<Modal bind:show={showModal} title={editItem ? 'Avansı Düzenle' : 'Yeni Avans'} maxWidth="max-w-lg">
	<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4">
		{#if formError}
			<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{formError}</div>
		{/if}

		<div>
			<label for="agency_name" class="block text-sm font-medium text-gray-700 mb-1">Acente/Operatör Adı *</label>
			<input
				id="agency_name"
				type="text"
				bind:value={form.agency_name}
				placeholder="Acente veya operatör adını girin"
				class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
			/>
		</div>

		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="amount" class="block text-sm font-medium text-gray-700 mb-1">Tutar *</label>
				<MoneyInput
					id="amount"
					bind:value={form.amount}
					currency={form.currency}
					min={0}
					placeholder="0,00"
				/>
			</div>
			<div>
				<label for="currency" class="block text-sm font-medium text-gray-700 mb-1">Para Birimi</label>
				<select
					id="currency"
					bind:value={form.currency}
					class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer"
				>
					{#each CURRENCIES as cur}
						<option value={cur}>{cur} ({CURRENCY_SYMBOLS[cur]})</option>
					{/each}
				</select>
			</div>
		</div>

		<div>
			<label for="advance_date" class="block text-sm font-medium text-gray-700 mb-1">Avans Tarihi *</label>
			<input
				id="advance_date"
				type="date"
				bind:value={form.advance_date}
				class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
			/>
		</div>

		<div>
			<label for="notes" class="block text-sm font-medium text-gray-700 mb-1">Notlar</label>
			<textarea
				id="notes"
				bind:value={form.notes}
				rows="3"
				placeholder="İsteğe bağlı notlar"
				class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"
			></textarea>
		</div>

		<div class="flex justify-end gap-3 pt-2">
			<button
				type="button"
				onclick={() => showModal = false}
				class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 cursor-pointer"
			>
				İptal
			</button>
			<button
				type="submit"
				disabled={saving}
				class="px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium hover:bg-teal-700 disabled:opacity-50 cursor-pointer"
			>
				{saving ? 'Kaydediliyor...' : (editItem ? 'Güncelle' : 'Kaydet')}
			</button>
		</div>
	</form>
</Modal>

<!-- Match Modal -->
<Modal bind:show={showMatchModal} title="Avans Alındı" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); handleMatch(); }} class="space-y-4">
		{#if matchItem}
			<div class="p-3 bg-gray-50 rounded-lg text-sm">
				<div class="font-medium text-gray-800">{matchItem.agency_name}</div>
				<div class="text-gray-500 mt-1">Beklenen: {fmt(matchItem.amount, matchItem.currency)}</div>
			</div>
		{/if}

		<div>
			<label for="received_date" class="block text-sm font-medium text-gray-700 mb-1">Alınma Tarihi *</label>
			<input
				id="received_date"
				type="date"
				bind:value={matchForm.received_date}
				class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
			/>
		</div>

		<div>
			<label for="received_amount" class="block text-sm font-medium text-gray-700 mb-1">Alınan Tutar *</label>
			<MoneyInput
				id="received_amount"
				bind:value={matchForm.received_amount}
				currency={matchItem?.currency}
				min={0}
				placeholder="0,00"
			/>
		</div>

		<div class="flex justify-end gap-3 pt-2">
			<button
				type="button"
				onclick={() => showMatchModal = false}
				class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 cursor-pointer"
			>
				İptal
			</button>
			<button
				type="submit"
				disabled={matchSaving}
				class="px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 cursor-pointer"
			>
				{matchSaving ? 'Kaydediliyor...' : 'Alındı Olarak İşaretle'}
			</button>
		</div>
	</form>
</Modal>

<!-- Delete Confirmation Modal -->
<Modal bind:show={showDeleteConfirm} title="Avans Sil" maxWidth="max-w-sm">
	<div class="space-y-4">
		<p class="text-sm text-gray-600">
			<span class="font-medium text-gray-800">{deleteItem?.agency_name}</span> acentesine ait
			<span class="font-medium">{deleteItem ? fmt(deleteItem.amount, deleteItem.currency) : ''}</span> tutarındaki
			avans kaydını silmek istediğinize emin misiniz?
		</p>
		<div class="flex justify-end gap-3">
			<button
				onclick={() => showDeleteConfirm = false}
				class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 cursor-pointer"
			>
				Vazgeç
			</button>
			<button
				onclick={confirmDelete}
				class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 cursor-pointer"
			>
				Sil
			</button>
		</div>
	</div>
</Modal>
