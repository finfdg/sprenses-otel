<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { FileText } from 'lucide-svelte';

	interface FormItem {
		id: number;
		template_id: number;
		template_name: string;
		period_date: string;
		status: string;
		filled_by_name: string | null;
		submitted_at: string | null;
		reviewed_by_name: string | null;
		reviewed_at: string | null;
		created_at: string;
	}

	interface TemplateOption {
		id: number;
		name: string;
	}

	const canUse = hasPermission('quality.forms', 'use');

	let forms = $state<FormItem[]>([]);
	let templateOptions = $state<TemplateOption[]>([]);
	let loading = $state(true);

	// Pagination
	let currentPage = $state(1);
	let totalItems = $state(0);
	let totalPages = $state(1);
	const pageSize = 25;

	// Filtreler
	let statusFilter = $state('');
	let templateFilter = $state('');
	let dateFrom = $state('');
	let dateTo = $state('');

	const statusLabels: Record<string, string> = {
		draft: 'Taslak',
		submitted: 'Gönderildi',
		approved: 'Onaylandı',
		rejected: 'Reddedildi',
	};

	const statusStyles: Record<string, string> = {
		draft: 'bg-gray-100 text-gray-600 border-gray-200',
		submitted: 'bg-blue-50 text-blue-600 border-blue-200',
		approved: 'bg-green-50 text-green-600 border-green-200',
		rejected: 'bg-red-50 text-red-600 border-red-200',
	};

	let unsubWs: (() => void) | null = null;

	onMount(async () => {
		await loadData();

		// WS: Form durumu değiştiğinde listeyi yenile
		unsubWs = onWsEvent('quality_form_update', (data: any) => {
			const eventLabels: Record<string, string> = {
				submitted: 'gönderildi',
				approved: 'onaylandı',
				rejected: 'reddedildi',
				reopened: 'yeniden açıldı',
			};
			const label = eventLabels[data.event] || 'güncellendi';
			showToast(`${data.template_name} formu ${label} (${data.actor_name})`, 'info');
			loadData();
		});
	});

	onDestroy(() => {
		unsubWs?.();
	});

	async function loadData() {
		loading = true;
		try {
			const params = new URLSearchParams();
			params.set('page', String(currentPage));
			params.set('page_size', String(pageSize));
			if (statusFilter) params.set('status', statusFilter);
			if (templateFilter) params.set('template_id', templateFilter);
			if (dateFrom) params.set('date_from', dateFrom);
			if (dateTo) params.set('date_to', dateTo);

			const [fRes, tRes] = await Promise.all([
				api.get<any>(`/quality/forms/?${params.toString()}`),
				api.get<any>('/quality/templates/?page=1&page_size=200&is_active=true'),
			]);
			forms = fRes.items ?? fRes;
			totalItems = fRes.total ?? forms.length;
			totalPages = fRes.pages ?? 1;
			templateOptions = ((tRes.items ?? tRes) as any[]).map(t => ({ id: t.id, name: t.name }));
		} catch (err) {
			console.error('Formlar yüklenemedi:', err);
			showToast('Formlar yüklenemedi', 'error');
		}
		loading = false;
	}

	function handleFilterChange() {
		currentPage = 1;
		loadData();
	}

	function goToPage(p: number) {
		if (p < 1 || p > totalPages) return;
		currentPage = p;
		loadData();
	}

	// Silme
	let showDeleteConfirm = $state(false);
	let deleteTargetId = $state<number | null>(null);
	let deleteTargetName = $state('');

	function confirmDelete(f: FormItem) {
		deleteTargetId = f.id;
		deleteTargetName = `${f.template_name} (${formatDate(f.period_date)})`;
		showDeleteConfirm = true;
	}

	async function handleDelete() {
		if (!deleteTargetId) return;
		try {
			await api.delete(`/quality/forms/${deleteTargetId}`);
			showToast('Form silindi', 'success');
			showDeleteConfirm = false;
			await loadData();
		} catch (err: any) {
			showToast(err.message || 'Silinemedi', 'error');
			console.error('Form silme hatası:', err);
		}
	}


	// Bugün filtresi
	function filterToday() {
		const today = new Date().toISOString().split('T')[0];
		dateFrom = today;
		dateTo = today;
		statusFilter = '';
		templateFilter = '';
		handleFilterChange();
	}

	function clearFilters() {
		dateFrom = '';
		dateTo = '';
		statusFilter = '';
		templateFilter = '';
		handleFilterChange();
	}

	let hasActiveFilter = $derived(
		statusFilter !== '' || templateFilter !== '' || dateFrom !== '' || dateTo !== ''
	);

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('tr-TR', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
		});
	}
</script>

<div class="max-w-6xl mx-auto">
	<!-- Başlık -->
	<div class="flex justify-end gap-2 mb-6">
		<button
			onclick={filterToday}
			class="text-xs px-3 py-2 sm:py-1.5 bg-blue-50 text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors cursor-pointer"
		>
			Bugün
		</button>
		{#if hasActiveFilter}
			<button
				onclick={clearFilters}
				class="text-xs px-3 py-2 sm:py-1.5 bg-gray-50 text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer"
			>
				Filtreleri Temizle
			</button>
		{/if}
	</div>

	<!-- Filtreler -->
	<div class="bg-white border border-gray-200 rounded-xl p-3 sm:p-4 mb-4">
		<!-- Mobil: 2 satır, Masaüstü: tek satır grid -->
		<div class="space-y-2 sm:space-y-0 sm:grid sm:grid-cols-4 sm:gap-3">
			<!-- Durum + Şablon -->
			<div class="flex gap-2 sm:contents">
				<div class="w-1/2 sm:w-auto">
					<label for="qf-status" class="block text-xs text-gray-500 mb-1">Durum</label>
					<select
						id="qf-status"
						bind:value={statusFilter}
						onchange={handleFilterChange}
						class="w-full px-2 sm:px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-teal-400"
					>
						<option value="">Tümü</option>
						<option value="draft">Taslak</option>
						<option value="submitted">Gönderildi</option>
						<option value="approved">Onaylandı</option>
						<option value="rejected">Reddedildi</option>
					</select>
				</div>
				<div class="w-1/2 sm:w-auto">
					<label for="qf-template" class="block text-xs text-gray-500 mb-1">Şablon</label>
					<select
						id="qf-template"
						bind:value={templateFilter}
						onchange={handleFilterChange}
						class="w-full px-2 sm:px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-teal-400"
					>
						<option value="">Tümü</option>
						{#each templateOptions as t}
							<option value={String(t.id)}>{t.name}</option>
						{/each}
					</select>
				</div>
			</div>
			<!-- Başlangıç + Bitiş -->
			<div class="flex gap-2 sm:contents">
				<div class="w-1/2 sm:w-auto">
					<label for="qf-from" class="block text-xs text-gray-500 mb-1">Başlangıç</label>
					<input
						id="qf-from"
						type="date"
						bind:value={dateFrom}
						onchange={handleFilterChange}
						class="date-filter-input w-full px-2 sm:px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-teal-400"
					/>
				</div>
				<div class="w-1/2 sm:w-auto">
					<label for="qf-to" class="block text-xs text-gray-500 mb-1">Bitiş</label>
					<input
						id="qf-to"
						type="date"
						bind:value={dateTo}
						onchange={handleFilterChange}
						class="date-filter-input w-full px-2 sm:px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-teal-400"
					/>
				</div>
			</div>
		</div>
	</div>

	<!-- Form Listesi -->
	{#if loading}
		<TableSkeleton rows={5} columns={4} />
	{:else if forms.length === 0}
		<EmptyState icon={FileText} title="Henüz form bulunmuyor" />
	{:else}
		<!-- Masaüstü: Tablo görünümü -->
		<div class="hidden md:block bg-white border border-gray-200 rounded-xl overflow-hidden">
			<table class="w-full text-sm">
				<thead class="bg-gray-50 border-b border-gray-200">
					<tr>
						<th class="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Şablon</th>
						<th class="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Tarih</th>
						<th class="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Durum</th>
						<th class="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Dolduran</th>
						<th class="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Onaylayan</th>
						<th class="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase">İşlem</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each forms as f (f.id)}
						<tr class="hover:bg-gray-50 transition-colors">
							<td class="px-4 py-3 font-medium text-gray-900">{f.template_name}</td>
							<td class="px-4 py-3 text-gray-600">{formatDate(f.period_date)}</td>
							<td class="px-4 py-3">
								<span class="text-xs px-2 py-0.5 rounded-full border {statusStyles[f.status] || ''}">
									{statusLabels[f.status] || f.status}
								</span>
							</td>
							<td class="px-4 py-3 text-gray-600">{f.filled_by_name || '—'}</td>
							<td class="px-4 py-3 text-gray-600">{f.reviewed_by_name || '—'}</td>
							<td class="px-4 py-3 text-right">
								<div class="flex items-center justify-end gap-1.5">
									<button
										onclick={() => goto(`/dashboard/kalite/formlar/${f.id}`)}
										class="text-xs px-3 py-1.5 bg-teal-50 text-teal-600 rounded-lg hover:bg-teal-100 transition-colors cursor-pointer"
									>
										{f.status === 'draft' || f.status === 'rejected' ? 'Doldur' : f.status === 'submitted' ? 'İncele' : 'Görüntüle'}
									</button>
									{#if canUse && f.status === 'draft'}
										<button
											onclick={() => confirmDelete(f)}
											class="text-xs px-2 py-1.5 bg-red-50 text-red-600 rounded-lg hover:bg-red-100 transition-colors cursor-pointer"
											title="Sil"
										>
											Sil
										</button>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Mobil: Kart görünümü -->
		<div class="md:hidden space-y-3">
			{#each forms as f (f.id)}
				<button
					onclick={() => goto(`/dashboard/kalite/formlar/${f.id}`)}
					class="w-full bg-white border border-gray-200 rounded-xl p-4 text-left hover:shadow-sm active:bg-gray-50 transition-all cursor-pointer"
				>
					<div class="flex items-start justify-between gap-2">
						<div class="flex-1 min-w-0">
							<h3 class="font-medium text-gray-900 text-sm truncate">{f.template_name}</h3>
							<p class="text-xs text-gray-500 mt-0.5">{formatDate(f.period_date)}</p>
						</div>
						<span class="text-xs px-2 py-0.5 rounded-full border shrink-0 {statusStyles[f.status] || ''}">
							{statusLabels[f.status] || f.status}
						</span>
					</div>
					<div class="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-xs text-gray-500">
						{#if f.filled_by_name}
							<span>Dolduran: <span class="text-gray-600">{f.filled_by_name}</span></span>
						{/if}
						{#if f.reviewed_by_name}
							<span>Onaylayan: <span class="text-gray-600">{f.reviewed_by_name}</span></span>
						{/if}
					</div>
					<div class="mt-3 flex justify-end">
						<span class="text-xs px-3 py-1.5 bg-teal-50 text-teal-600 rounded-lg font-medium">
							{f.status === 'draft' || f.status === 'rejected' ? 'Doldur →' : f.status === 'submitted' ? 'İncele →' : 'Görüntüle →'}
						</span>
					</div>
				</button>
			{/each}
		</div>

		<!-- Sayfalama -->
		{#if totalPages > 1}
			<div class="flex items-center justify-between mt-4 bg-white border border-gray-200 rounded-xl px-4 py-3">
				<span class="text-xs text-gray-500">
					Toplam {totalItems} form
				</span>
				<div class="flex items-center gap-1">
					<button
						onclick={() => goToPage(currentPage - 1)}
						disabled={currentPage <= 1}
						class="px-2.5 py-1.5 text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						←
					</button>
					{#each Array.from({ length: totalPages }, (_, i) => i + 1).filter(p => p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1) as p, idx}
						{@const pages = Array.from({ length: totalPages }, (_, i) => i + 1).filter(pp => pp === 1 || pp === totalPages || Math.abs(pp - currentPage) <= 1)}
						{#if idx > 0 && p - pages[idx - 1] > 1}
							<span class="px-1 text-xs text-gray-500">...</span>
						{/if}
						<button
							onclick={() => goToPage(p)}
							class="px-2.5 py-1.5 text-xs rounded-lg border transition-colors cursor-pointer {
								p === currentPage
									? 'bg-teal-600 text-white border-teal-600'
									: 'text-gray-600 bg-gray-50 border-gray-200 hover:bg-gray-100'
							}"
						>
							{p}
						</button>
					{/each}
					<button
						onclick={() => goToPage(currentPage + 1)}
						disabled={currentPage >= totalPages}
						class="px-2.5 py-1.5 text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						→
					</button>
				</div>
			</div>
		{/if}
	{/if}
</div>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Formu Sil"
	message="{deleteTargetName} formunu silmek istediğinize emin misiniz?"
	confirmText="Sil"
	danger={true}
	onConfirm={handleDelete}
/>
