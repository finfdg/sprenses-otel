<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import ListPage from '$lib/components/ListPage.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import Button from '$lib/components/Button.svelte';
	import { CheckCircle2, Check, X } from 'lucide-svelte';

	interface PendingItem {
		id: number;
		vendor_id: number;
		vendor_name: string;
		date: string;
		evrak_no: string | null;
		description: string | null;
		borc: number;
		alacak: number;
		department_id: number;
		department_name: string;
		budget_category_id: number | null;
		budget_category_name: string | null;
		dept_status: string;
		dept_assigned_by_name: string | null;
		dept_assigned_at: string | null;
		dept_rejection_note: string | null;
	}

	let pendingInvoices = $state<PendingItem[]>([]);
	let loading = $state(true);
	let showApproveModal = $state(false);
	let showRejectModal = $state(false);
	let selectedInvoice = $state<PendingItem | null>(null);
	let approvalNote = $state('');
	let rejectionNote = $state('');
	let processing = $state(false);
	let fadingIds = $state<Set<number>>(new Set());

	let pendingCount = $derived(pendingInvoices.length);

	function formatAmount(n: number): string {
		return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	function formatDate(d: string): string {
		return new Date(d).toLocaleDateString('tr-TR');
	}

	function formatRelativeDate(d: string): string {
		const now = new Date();
		const date = new Date(d);
		const diffMs = now.getTime() - date.getTime();
		const diffMins = Math.floor(diffMs / 60000);
		const diffHours = Math.floor(diffMs / 3600000);
		const diffDays = Math.floor(diffMs / 86400000);

		if (diffMins < 1) return 'Az önce';
		if (diffMins < 60) return `${diffMins} dakika önce`;
		if (diffHours < 24) return `${diffHours} saat önce`;
		if (diffDays < 7) return `${diffDays} gün önce`;
		return formatDate(d);
	}

	function getAmount(inv: PendingItem): number {
		return inv.alacak || inv.borc;
	}

	async function loadPending() {
		try {
			const data = await api.get<PendingItem[]>('/finance/onay/my-approvals');
			pendingInvoices = data;
		} catch (err) {
			console.error('Onay bekleyen faturalar yüklenemedi:', err);
		} finally {
			loading = false;
		}
	}

	function openApproveModal(invoice: PendingItem) {
		selectedInvoice = invoice;
		approvalNote = '';
		showApproveModal = true;
	}

	function openRejectModal(invoice: PendingItem) {
		selectedInvoice = invoice;
		rejectionNote = '';
		showRejectModal = true;
	}

	async function approveInvoice() {
		if (!selectedInvoice || processing) return;
		processing = true;
		try {
			const body: Record<string, string> = {};
			if (approvalNote.trim()) {
				body.note = approvalNote.trim();
			}
			await api.post(`/finance/onay/approve/${selectedInvoice.id}`, body);
			const approvedId = selectedInvoice.id;
			showApproveModal = false;
			selectedInvoice = null;
			approvalNote = '';
			// Fade out then remove
			fadingIds = new Set([...fadingIds, approvedId]);
			setTimeout(() => {
				pendingInvoices = pendingInvoices.filter((inv) => inv.id !== approvedId);
				const newFading = new Set(fadingIds);
				newFading.delete(approvedId);
				fadingIds = newFading;
			}, 400);
		} catch (err) {
			console.error('Fatura onaylanamadı:', err);
		} finally {
			processing = false;
		}
	}

	async function rejectInvoice() {
		if (!selectedInvoice || processing) return;
		if (!rejectionNote.trim()) return;
		processing = true;
		try {
			await api.post(`/finance/onay/reject/${selectedInvoice.id}`, { note: rejectionNote.trim() });
			const rejectedId = selectedInvoice.id;
			showRejectModal = false;
			selectedInvoice = null;
			rejectionNote = '';
			// Fade out then remove
			fadingIds = new Set([...fadingIds, rejectedId]);
			setTimeout(() => {
				pendingInvoices = pendingInvoices.filter((inv) => inv.id !== rejectedId);
				const newFading = new Set(fadingIds);
				newFading.delete(rejectedId);
				fadingIds = newFading;
			}, 400);
		} catch (err) {
			console.error('Fatura reddedilemedi:', err);
		} finally {
			processing = false;
		}
	}

	let unsubFinance: (() => void) | null = null;
	let unsubNotification: (() => void) | null = null;

	onMount(() => {
		loadPending();
		unsubFinance = onWsEvent('finance_updated', () => {
			loadPending();
		});
		unsubNotification = onWsEvent('notification', () => {
			loadPending();
		});
	});

	onDestroy(() => {
		unsubFinance?.();
		unsubNotification?.();
	});
</script>

<ListPage
	title="Onay Kutusu"
	description={pendingCount > 0 ? `${pendingCount} onay bekliyor` : ''}
	{loading}
	isEmpty={pendingInvoices.length === 0}
	emptyIcon={CheckCircle2}
	emptyTitle="Onay bekleyen fatura bulunmuyor"
	emptyMessage="Tüm faturalar incelendi"
	card={false}
	maxWidth="max-w-4xl"
>
	{#snippet skeleton()}
		<TableSkeleton rows={4} columns={3} showHeader={false} />
	{/snippet}

	<div class="space-y-4">
		{#each pendingInvoices as invoice (invoice.id)}
				<div
					class="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sm:p-5 transition-all duration-400"
					class:opacity-0={fadingIds.has(invoice.id)}
					class:scale-95={fadingIds.has(invoice.id)}
				>
					<!-- Top Row: Vendor + Amount -->
					<div class="flex items-start justify-between gap-3 mb-3">
						<h3 class="text-base sm:text-lg font-bold text-gray-800 truncate">{invoice.vendor_name}</h3>
						<div class="text-right shrink-0">
							<span class="text-lg sm:text-xl font-bold text-teal-600">
								{formatAmount(getAmount(invoice))} ₺
							</span>
						</div>
					</div>

					<!-- Second Row: Badges + Date -->
					<div class="flex flex-wrap items-center gap-2 mb-3">
						<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-teal-50 text-teal-700 border border-teal-200">
							{invoice.department_name}
						</span>
						{#if invoice.budget_category_name}
							<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-200">
								{invoice.budget_category_name}
							</span>
						{/if}
						<span class="text-sm text-gray-500">{formatDate(invoice.date)}</span>
					</div>

					<!-- Third Row: Evrak No + Description -->
					<div class="flex flex-wrap items-center gap-3 mb-2 text-sm">
						{#if invoice.evrak_no}
							<span class="font-mono text-gray-500 text-xs bg-gray-50 px-2 py-0.5 rounded">{invoice.evrak_no}</span>
						{/if}
						{#if invoice.description}
							<p class="text-gray-600 truncate max-w-md">{invoice.description}</p>
						{/if}
					</div>

					<!-- Fourth Row: Assigned by + Date -->
					<div class="flex flex-wrap items-center gap-2 text-sm text-gray-500 mb-3">
						{#if invoice.dept_assigned_by_name}
							<span>Gönderen: <span class="font-medium text-gray-700">{invoice.dept_assigned_by_name}</span></span>
						{/if}
						{#if invoice.dept_assigned_at}
							<span class="text-gray-500">·</span>
							<span>{formatRelativeDate(invoice.dept_assigned_at)}</span>
						{/if}
					</div>

					<!-- Action Buttons -->
					<div class="flex items-center gap-3 pt-3 border-t border-gray-100">
						<Button onclick={() => openApproveModal(invoice)}>
							<Check size={16} /> Onayla
						</Button>
						<Button variant="danger" onclick={() => openRejectModal(invoice)}>
							<X size={16} /> Reddet
						</Button>
					</div>
				</div>
			{/each}
		</div>
</ListPage>

<!-- Approval Modal -->
<Modal bind:show={showApproveModal} title="Faturayı Onayla" maxWidth="max-w-md">
	{#if selectedInvoice}
		<div class="space-y-4">
			<div class="bg-gray-50 rounded-lg p-3 text-sm">
				<p class="font-medium text-gray-800">{selectedInvoice.vendor_name}</p>
				<p class="text-gray-600 mt-1">
					<span class="font-semibold text-teal-600">{formatAmount(getAmount(selectedInvoice))} ₺</span>
				</p>
			</div>
			<div>
				<label for="approval-note" class="block text-sm font-medium text-gray-700 mb-1">Not (opsiyonel)</label>
				<textarea
					id="approval-note"
					bind:value={approvalNote}
					rows="3"
					class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 outline-none resize-none"
					placeholder="Onay notu ekleyin..."
				></textarea>
			</div>
			<div class="flex items-center justify-end gap-3 pt-2">
				<button
					onclick={() => { showApproveModal = false; }}
					class="px-4 py-2.5 rounded-lg font-medium text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors cursor-pointer"
				>
					İptal
				</button>
				<button
					onclick={approveInvoice}
					disabled={processing}
					class="px-4 py-2.5 rounded-lg font-medium text-sm bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
				>
					{#if processing}
						<span class="inline-flex items-center gap-2">
							<span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
							Onaylanıyor...
						</span>
					{:else}
						Onayla
					{/if}
				</button>
			</div>
		</div>
	{/if}
</Modal>

<!-- Rejection Modal -->
<Modal bind:show={showRejectModal} title="Faturayı Reddet" maxWidth="max-w-md">
	{#if selectedInvoice}
		<div class="space-y-4">
			<div class="bg-gray-50 rounded-lg p-3 text-sm">
				<p class="font-medium text-gray-800">{selectedInvoice.vendor_name}</p>
				<p class="text-gray-600 mt-1">
					<span class="font-semibold text-teal-600">{formatAmount(getAmount(selectedInvoice))} ₺</span>
				</p>
			</div>
			<div>
				<label for="rejection-note" class="block text-sm font-medium text-gray-700 mb-1">Red gerekçesi (zorunlu)</label>
				<textarea
					id="rejection-note"
					bind:value={rejectionNote}
					rows="3"
					class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-red-500 focus:ring-1 focus:ring-red-500 outline-none resize-none"
					placeholder="Red gerekçesini yazın..."
				></textarea>
				{#if rejectionNote !== '' && !rejectionNote.trim()}
					<p class="text-xs text-red-600 mt-1">Red gerekçesi boş bırakılamaz</p>
				{/if}
			</div>
			<div class="flex items-center justify-end gap-3 pt-2">
				<button
					onclick={() => { showRejectModal = false; }}
					class="px-4 py-2.5 rounded-lg font-medium text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors cursor-pointer"
				>
					İptal
				</button>
				<button
					onclick={rejectInvoice}
					disabled={processing || !rejectionNote.trim()}
					class="px-4 py-2.5 rounded-lg font-medium text-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
				>
					{#if processing}
						<span class="inline-flex items-center gap-2">
							<span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
							Reddediliyor...
						</span>
					{:else}
						Reddet
					{/if}
				</button>
			</div>
		</div>
	{/if}
</Modal>
