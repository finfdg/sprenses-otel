<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { authState } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import {
		Plus, Pencil, Trash2, X, Check, Clock, ChevronDown, Search,
		RotateCcw, FileText, FileClock, CircleCheck, CircleX, CornerUpLeft
	} from 'lucide-svelte';

	interface Props {
		title: string;
		subtitle: string;
		apiPrefix: string;
		permissionCode: string;
		sourceType: string;
		categories?: string[];
		showCategory?: boolean;
		categoryLabel?: string;
	}

	let {
		title,
		subtitle,
		apiPrefix,
		permissionCode,
		sourceType,
		categories = [],
		showCategory = false,
		categoryLabel = 'Kategori',
	}: Props = $props();

	const FREQ_LABELS: Record<string, string> = {
		monthly: 'Aylık',
		quarterly: '3 Aylık',
		yearly: 'Yıllık',
	};
	const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	let canUse = $derived(hasPermission(permissionCode, 'use'));
	let canApprove = $derived(hasPermission('system.approval', 'use'));

	// State
	let definitions = $state<any[]>([]);
	let summary = $state<any>({});
	let loading = $state(true);
	let total = $state(0);
	let selectedYear = $state(new Date().getFullYear());

	// Arama (debounce 300ms)
	let searchInput = $state('');
	let searchQuery = $state('');
	$effect(() => {
		const v = searchInput;
		const timer = setTimeout(() => { searchQuery = v; }, 300);
		return () => clearTimeout(timer);
	});

	let filteredDefinitions = $derived.by(() => {
		if (!searchQuery.trim()) return definitions;
		const q = searchQuery.toLowerCase().trim();
		return definitions.filter((d: any) =>
			(d.name || '').toLowerCase().includes(q) ||
			(d.category || '').toLowerCase().includes(q) ||
			(d.notes || '').toLowerCase().includes(q)
		);
	});

	// Onayda bekleyen tanım sayısı
	let pendingCreateCount = $derived(
		definitions.filter(d => d.is_active === false && hasPendingApproval(d.id)).length
	);
	// Güncelleme/silme onayı bekleyen aktif kayıt sayısı
	let pendingUpdateCount = $derived(
		definitions.filter(d => d.is_active !== false && hasPendingApproval(d.id)).length
	);
	let totalPendingCount = $derived(pendingCreateCount + pendingUpdateCount);

	// Modal
	let showModal = $state(false);
	let editItem = $state<any>(null);
	let form = $state<{
		name: string;
		category: string;
		amount: number | null;
		currency: string;
		frequency: string;
		payment_day: number;
		start_month: number;
		year: number;
		notes: string;
	}>({
		name: '',
		category: '',
		amount: null,
		currency: 'TRY',
		frequency: 'monthly',
		payment_day: 1,
		start_month: new Date().getMonth() + 1,
		year: new Date().getFullYear(),
		notes: '',
	});
	let saving = $state(false);
	let formError = $state('');

	// Delete confirm
	let deleteItem = $state<any>(null);
	let showDeleteConfirm = $state(false);

	// Expand
	let expandedIds = $state<Set<number>>(new Set());

	// Onay durumu: entry_id → {request_id, action_type, requested_by, requested_by_name}
	let pendingApprovals = $state<Record<string, any>>({});

	// Onay detay modal
	let showApprovalDetail = $state(false);
	let approvalDetail = $state<any>(null);
	let approvalDetailLoading = $state(false);

	// Onay aksiyon modal
	let showActionModal = $state(false);
	let actionType = $state<'approve' | 'reject' | 'return'>('approve');
	let actionNote = $state('');
	let actionProcessing = $state(false);
	let actionRequestId = $state<number>(0);

	async function openApprovalDetail(entityId: number) {
		const info = getPendingInfo(entityId);
		if (!info) return;
		approvalDetailLoading = true;
		showApprovalDetail = true;
		approvalDetail = null;
		try {
			const data = await api.get<any>(`/system/approval/requests/${info.request_id}`);
			approvalDetail = data;
		} catch (err: any) {
			console.error('Onay detayı yüklenemedi:', err);
			showToast('Onay detayı yüklenemedi', 'error');
			showApprovalDetail = false;
		} finally {
			approvalDetailLoading = false;
		}
	}

	function parsePayload(payloadJson: string | null): Record<string, any> | null {
		if (!payloadJson) return null;
		try {
			return JSON.parse(payloadJson);
		} catch (e) {
			console.error('Onay payload JSON parse edilemedi:', e);
			return null;
		}
	}

	const FIELD_LABELS: Record<string, string> = {
		name: 'Ad',
		amount: 'Tutar',
		currency: 'Para Birimi',
		frequency: 'Periyot',
		payment_day: 'Ödeme Günü',
		start_month: 'Başlangıç Ayı',
		year: 'Yıl',
		notes: 'Not',
		category: 'Kategori',
		is_paid: 'Ödendi',
		paid_date: 'Ödeme Tarihi',
		is_active: 'Aktif',
		_target: 'Hedef',
	};

	function getFieldLabel(key: string): string {
		return FIELD_LABELS[key] || key;
	}

	function formatFieldValue(key: string, value: any): string {
		if (value === null || value === undefined) return '-';
		if (typeof value === 'boolean') return value ? 'Evet' : 'Hayır';
		if (key === 'amount' && typeof value === 'number') return fmt(value);
		if (key === 'frequency') return FREQ_LABELS[value] || String(value);
		if (key === 'start_month' && typeof value === 'number' && value >= 1 && value <= 12) return MONTH_NAMES[value - 1];
		return String(value);
	}

	// Entry inline edit
	let editingEntryId = $state<number | null>(null);
	let entryForm = $state<{ amount: number | null; entry_date: string; period_month: number | null; period_year: number | null; is_paid: boolean; paid_date: string; notes: string }>({
		amount: null, entry_date: '', period_month: null, period_year: null, is_paid: false, paid_date: '', notes: '',
	});
	let entryFormSaving = $state(false);

	function openEntryEdit(entry: any) {
		editingEntryId = entry.id;
		entryForm = {
			amount: entry.amount ?? null,
			entry_date: entry.entry_date || '',
			period_month: entry.period_month ?? null,
			period_year: entry.period_year ?? null,
			is_paid: entry.is_paid ?? false,
			// paid_date boşsa etkin ödeme tarihini (entry_date) default göster —
			// Safari boş date input'a bugünün tarihini placeholder olarak basıyor
			paid_date: entry.paid_date || entry.entry_date || '',
			notes: entry.notes || '',
		};
	}

	function cancelEntryEdit() {
		editingEntryId = null;
	}

	async function saveEntryEdit(entry: any) {
		if (entryForm.amount === null || entryForm.amount <= 0) {
			showToast('Tutar sıfırdan büyük olmalıdır', 'error');
			return;
		}
		entryFormSaving = true;
		try {
			const payload: any = {};
			if (entryForm.amount !== entry.amount) payload.amount = entryForm.amount;
			if (entryForm.entry_date !== (entry.entry_date || '')) {
				payload.entry_date = entryForm.entry_date || null;
			}
			if (entryForm.period_month !== (entry.period_month ?? null)) {
				payload.period_month = entryForm.period_month;
			}
			if (entryForm.period_year !== (entry.period_year ?? null)) {
				payload.period_year = entryForm.period_year;
			}
			if (entryForm.notes !== (entry.notes || '')) payload.notes = entryForm.notes || null;
			if (entryForm.is_paid !== (entry.is_paid ?? false)) payload.is_paid = entryForm.is_paid;
			// paid_date karşılaştırma: pre-populated default (entry_date) değişmediyse gönderme
			const effectivePaidOriginal = entry.paid_date || entry.entry_date || '';
			if (entryForm.paid_date !== effectivePaidOriginal) {
				payload.paid_date = entryForm.paid_date || null;
			}
			if (Object.keys(payload).length > 0) {
				const result = await api.patch<any>(`${apiPrefix}/entries/${entry.id}`, payload);
				if (result?.requires_approval) {
					showToast('İşlem onay sürecine alındı', 'info');
				}
				await loadData();
			}
			editingEntryId = null;
		} catch (err: any) {
			console.error('Giriş güncelleme hatası:', err);
			if (err?.message?.includes('bekleyen bir onay talebi')) {
				showToast('Bu giriş için bekleyen bir onay talebi var', 'error');
			} else {
				showToast(err?.message || 'Güncelleme sırasında hata oluştu', 'error');
			}
		} finally {
			entryFormSaving = false;
		}
	}

	function fmt(n: number | null | undefined): string {
		if (n == null) return '-';
		return `₺${n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
	}

	function fmtDate(d: string | null): string {
		if (!d) return '-';
		return new Date(d + 'T00:00:00').toLocaleDateString('tr-TR', { day: '2-digit', month: 'long', year: 'numeric' });
	}

	function fmtMonth(d: string | null): string {
		if (!d) return '-';
		const dt = new Date(d + 'T00:00:00');
		return MONTH_NAMES[dt.getMonth()] + ' ' + dt.getFullYear();
	}

	function fmtPeriod(month: number | null, year: number | null): string {
		if (!month || !year) return '-';
		return MONTH_NAMES[month - 1] + ' ' + year;
	}

	async function loadData() {
		loading = true;
		try {
			const [listData, summaryData] = await Promise.all([
				api.get<any>(`${apiPrefix}/?year=${selectedYear}&page_size=200`),
				api.get<any>(`${apiPrefix}/summary/totals?year=${selectedYear}`),
			]);
			definitions = listData.items;
			total = listData.total;
			summary = summaryData;
			// Girişlerin onay durumunu toplu sorgula
			await loadPendingApprovals();
		} catch (err) {
			console.error('Veri yüklenemedi:', err);
		} finally {
			loading = false;
		}
	}

	async function loadPendingApprovals() {
		try {
			// Tüm giriş ID'lerini ve tanım ID'lerini topla
			const entryIds: number[] = [];
			const defnIds: number[] = [];
			for (const d of definitions) {
				defnIds.push(d.id);
				if (d.entries) {
					for (const e of d.entries) entryIds.push(e.id);
				}
			}
			const allIds = [...entryIds, ...defnIds];
			if (allIds.length === 0) { pendingApprovals = {}; return; }
			const result = await api.post<any>('/system/approval/status/bulk', {
				module_code: permissionCode,
				entity_ids: allIds,
			});
			pendingApprovals = result.pending ?? {};
		} catch (e) {
			console.error('Bekleyen onaylar yüklenemedi:', e);
			pendingApprovals = {};
		}
	}

	function hasPendingApproval(entityId: number): boolean {
		return !!pendingApprovals[String(entityId)];
	}

	function getPendingInfo(entityId: number): any {
		return pendingApprovals[String(entityId)] || null;
	}

	async function cancelApproval(entityId: number) {
		const info = getPendingInfo(entityId);
		if (!info) return;
		try {
			await api.post(`/system/approval/requests/${info.request_id}/cancel`, {});
			showToast('Onay talebi iptal edildi', 'success');
			await loadData();
		} catch (err: any) {
			console.error('Onay iptali hatası:', err);
			showToast(err?.message || 'Onay iptali sırasında hata oluştu', 'error');
		}
	}

	function openApprovalAction(type: 'approve' | 'reject' | 'return', requestId: number) {
		actionType = type;
		actionRequestId = requestId;
		actionNote = '';
		actionProcessing = false;
		showActionModal = true;
	}

	async function executeApprovalAction() {
		if ((actionType === 'reject' || actionType === 'return') && !actionNote.trim()) {
			showToast(actionType === 'reject' ? 'Red gerekçesi zorunludur' : 'İade gerekçesi zorunludur', 'error');
			return;
		}
		actionProcessing = true;
		try {
			const body: Record<string, string> = {};
			if (actionNote.trim()) body.note = actionNote.trim();
			await api.post(`/system/approval/requests/${actionRequestId}/${actionType}`, body);
			const labels = { approve: 'Onaylandı', reject: 'Reddedildi', return: 'İade edildi' };
			showToast(labels[actionType], 'success');
			showActionModal = false;
			showApprovalDetail = false;
			await loadData();
		} catch (err: any) {
			console.error('Onay aksiyon hatası:', err);
			showToast(err?.message || 'İşlem sırasında hata oluştu', 'error');
		} finally {
			actionProcessing = false;
		}
	}

	function openAdd() {
		editItem = null;
		const now = new Date();
		form = {
			name: '', category: '', amount: null, currency: 'TRY',
			frequency: 'monthly', payment_day: 1,
			start_month: now.getMonth() + 1, year: selectedYear, notes: '',
		};
		formError = '';
		showModal = true;
	}

	function openEdit(d: any) {
		editItem = d;
		form = {
			name: d.name, category: d.category || '',
			amount: d.amount, currency: d.currency,
			frequency: d.frequency, payment_day: d.payment_day,
			start_month: d.start_month, year: d.year, notes: d.notes || '',
		};
		formError = '';
		showModal = true;
	}

	async function handleSave() {
		if (!form.name.trim()) { formError = 'Ad zorunludur'; return; }
		if (!form.amount || form.amount <= 0) { formError = 'Tutar sıfırdan büyük olmalıdır'; return; }

		saving = true;
		formError = '';
		try {
			const payload: any = { ...form };
			if (!showCategory) delete payload.category;
			let result: any;
			if (editItem) {
				result = await api.patch(`${apiPrefix}/${editItem.id}`, payload);
			} else {
				result = await api.post(`${apiPrefix}/`, payload);
			}
			if (result?.requires_approval) {
				showToast('İşlem onay sürecine alındı', 'info');
			}
			showModal = false;
			await loadData();
		} catch (err: any) {
			console.error('Kaydetme hatası:', err);
			if (err?.message?.includes('bekleyen bir onay talebi')) {
				formError = 'Bu kayıt için bekleyen bir onay talebi var';
			} else {
				formError = err?.message || 'Kaydetme sırasında hata oluştu';
			}
		} finally {
			saving = false;
		}
	}

	function openDelete(d: any) {
		deleteItem = d;
		showDeleteConfirm = true;
	}

	async function confirmDelete() {
		if (!deleteItem) return;
		try {
			const result = await api.delete<any>(`${apiPrefix}/${deleteItem.id}`);
			if (result?.requires_approval) {
				showToast('Silme işlemi onay sürecine alındı', 'info');
			}
			showDeleteConfirm = false;
			deleteItem = null;
			await loadData();
		} catch (err: any) {
			console.error('Silme hatası:', err);
			showToast(err?.message || 'Silme sırasında hata oluştu', 'error');
		}
	}

	async function togglePaid(entry: any) {
		if (hasPendingApproval(entry.id)) {
			showToast('Bu giriş için bekleyen bir onay talebi var', 'error');
			return;
		}
		try {
			const newPaid = !entry.is_paid;
			const result = await api.patch<any>(`${apiPrefix}/entries/${entry.id}`, {
				is_paid: newPaid,
				paid_date: newPaid ? new Date().toISOString().split('T')[0] : null,
			});
			if (result?.requires_approval) {
				showToast('İşlem onay sürecine alındı', 'info');
			}
			await loadData();
		} catch (err: any) {
			console.error('Durum güncelleme hatası:', err);
			showToast(err?.message || 'Güncelleme sırasında hata oluştu', 'error');
		}
	}

	async function updateEntryAmount(entry: any, newAmount: number) {
		if (newAmount <= 0) return;
		try {
			await api.patch(`${apiPrefix}/entries/${entry.id}`, { amount: newAmount });
			await loadData();
		} catch (err: any) {
			console.error('Tutar güncelleme hatası:', err);
			showToast(err?.message || 'Güncelleme sırasında hata oluştu', 'error');
		}
	}

	function toggleExpand(id: number) {
		const next = new Set(expandedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		expandedIds = next;
	}

	let unsubFinance: (() => void) | null = null;

	onMount(() => {
		loadData();
		unsubFinance = onWsEvent('finance_updated', () => { loadData(); });
	});

	onDestroy(() => { unsubFinance?.(); });
</script>

<div class="space-y-4 sm:space-y-6">
	<!-- Header -->
	<div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
		<div>
			<div class="flex items-center gap-2.5 flex-wrap">
				<h1 class="text-2xl font-semibold text-gray-900">{title}</h1>
				{#if totalPendingCount > 0}
					<StatusBadge type="warning">
						<Clock size={12} />
						{totalPendingCount} onay bekliyor
					</StatusBadge>
				{/if}
			</div>
			<p class="text-xs sm:text-sm text-gray-500 mt-1">{subtitle}</p>
		</div>
	</div>

	<!-- Filtre barı: Arama (sol) + Yıl seçici + Ekle (sağ) -->
	<div class="flex flex-col sm:flex-row sm:items-center gap-3">
		<div class="relative flex-1 max-w-md">
			<Search size={16} class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
			<input
				type="text"
				bind:value={searchInput}
				placeholder="Ad, kategori veya nota göre ara..."
				class="w-full pl-9 pr-9 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
			/>
			{#if searchInput}
				<button
					onclick={() => (searchInput = '')}
					aria-label="Aramayı temizle"
					class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600 rounded cursor-pointer"
				>
					<X size={14} />
				</button>
			{/if}
		</div>
		<div class="flex items-center gap-3 sm:ml-auto">
			<select
				bind:value={selectedYear}
				onchange={() => loadData()}
				aria-label="Yıl seçici"
				class="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer"
			>
				{#each [2025, 2026, 2027] as y (y)}
					<option value={y}>{y}</option>
				{/each}
			</select>
			{#if canUse}
				<button
					onclick={openAdd}
					class="inline-flex items-center gap-2 px-4 py-2.5 bg-teal-600 text-white rounded-xl hover:bg-teal-700 transition-colors text-sm font-medium cursor-pointer"
				>
					<Plus size={16} />
					Ekle
				</button>
			{/if}
		</div>
	</div>

	<!-- Summary Cards -->
	{#if summary.total}
		<div class="flex flex-wrap gap-2 sm:gap-4">
			<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 shadow-sm flex-1 min-w-[140px]">
				<div class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Toplam</div>
				<div class="mt-1 text-base sm:text-xl font-bold text-gray-800">{fmt(summary.total)}</div>
				<div class="text-[10px] sm:text-xs text-gray-400 mt-1">{summary.count || 0} giriş</div>
			</div>
			<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 shadow-sm flex-1 min-w-[140px]">
				<div class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Ödenen</div>
				<div class="mt-1 text-base sm:text-xl font-bold text-emerald-700">{fmt(summary.paid)}</div>
				<div class="text-[10px] sm:text-xs text-gray-400 mt-1">{summary.paid_count || 0} giriş</div>
			</div>
			<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 shadow-sm flex-1 min-w-[140px]">
				<div class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Bekleyen</div>
				<div class="mt-1 text-base sm:text-xl font-bold text-yellow-700">{fmt(summary.pending)}</div>
				<div class="text-[10px] sm:text-xs text-gray-400 mt-1">{(summary.count || 0) - (summary.paid_count || 0)} giriş</div>
			</div>
		</div>
	{/if}

	<!-- Definitions List -->
	<div class="space-y-3">
		{#if loading}
			<TableSkeleton rows={5} columns={4} />
		{:else if definitions.length === 0}
			<EmptyState
				icon={FileText}
				title="Henüz kayıt yok"
				description="İlk kaydı eklemek için sağ üstteki 'Ekle' butonunu kullanın"
				ctaText={canUse ? 'Yeni Ekle' : ''}
				onCta={canUse ? openAdd : null}
			/>
		{:else if filteredDefinitions.length === 0}
			<EmptyState
				title="Aramaya uygun kayıt bulunamadı"
				description="Farklı bir arama terimi deneyin veya aramayı temizleyin"
			/>
		{:else}
			{#each filteredDefinitions as defn (defn.id)}
				{@const isExpanded = expandedIds.has(defn.id)}
				{@const entries = defn.entries || []}
				{@const paidCount = entries.filter((e: any) => e.is_paid).length}
				{@const pendingEntryCount = entries.filter((e: any) => hasPendingApproval(e.id)).length}
				{@const isInactive = defn.is_active === false}
				{@const isPendingCreate = isInactive && hasPendingApproval(defn.id)}
				<div class="rounded-xl border shadow-sm overflow-hidden {isPendingCreate ? 'bg-orange-50/40 border-orange-200' : 'bg-white border-gray-200'}">
					<!-- Definition Header (div role=button — iç action butonları nested olamaz) -->
					<div
						onclick={() => { if (!isInactive) toggleExpand(defn.id); }}
						onkeydown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !isInactive) { e.preventDefault(); toggleExpand(defn.id); } }}
						role="button"
						tabindex={isInactive ? -1 : 0}
						aria-expanded={isExpanded}
						class="w-full flex items-center justify-between px-4 py-3 transition-colors text-left {isInactive ? 'cursor-default' : 'hover:bg-gray-50 cursor-pointer'}"
					>
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2 flex-wrap">
								<span class="font-semibold {isPendingCreate ? 'text-orange-800' : 'text-gray-800'}">{defn.name}</span>
								{#if isPendingCreate}
									<button
										onclick={(e) => { e.stopPropagation(); openApprovalDetail(defn.id); }}
										class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-100 text-orange-700 border border-orange-300 hover:bg-orange-200 transition-colors cursor-pointer"
										title="Onay detayını görüntüle"
									>
										<Clock size={12} />
										Onayda
									</button>
								{/if}
								{#if defn.category}
									<StatusBadge type="info">{defn.category}</StatusBadge>
								{/if}
								<StatusBadge type="neutral">{FREQ_LABELS[defn.frequency] || defn.frequency}</StatusBadge>
							</div>
							<div class="flex items-center gap-3 mt-1 text-xs {isPendingCreate ? 'text-orange-500' : 'text-gray-400'} flex-wrap">
								<span>{fmt(defn.amount)} / dönem</span>
								{#if !isInactive}
									<span>{paidCount}/{entries.length} ödendi</span>
								{/if}
								{#if pendingEntryCount > 0 && !isPendingCreate}
									<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-orange-100 text-orange-700 border border-orange-200">
										<Clock size={12} />
										{pendingEntryCount} giriş onayda
									</span>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-2 shrink-0 ml-3">
							{#if isPendingCreate && canUse}
								<button
									onclick={(e) => { e.stopPropagation(); cancelApproval(defn.id); }}
									class="p-1.5 text-orange-500 hover:text-orange-700 hover:bg-orange-100 rounded-lg cursor-pointer"
									title="Onay talebini iptal et"
								>
									<X size={16} />
								</button>
							{:else if hasPendingApproval(defn.id) && !isInactive}
								<button
									onclick={(e) => { e.stopPropagation(); openApprovalDetail(defn.id); }}
									class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-50 text-orange-700 border border-orange-200 hover:bg-orange-100 transition-colors cursor-pointer"
									title="Onay detayını görüntüle"
								>
									<Clock size={12} />
									Onay Bekliyor
								</button>
								<button
									onclick={(e) => { e.stopPropagation(); cancelApproval(defn.id); }}
									class="p-1.5 text-orange-500 hover:text-orange-700 hover:bg-orange-50 rounded-lg cursor-pointer"
									title="Onay talebini iptal et"
								>
									<X size={16} />
								</button>
							{:else if canUse && !isInactive}
								<button
									onclick={(e) => { e.stopPropagation(); openEdit(defn); }}
									class="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg cursor-pointer"
									title="Düzenle"
								>
									<Pencil size={16} />
								</button>
								<button
									onclick={(e) => { e.stopPropagation(); openDelete(defn); }}
									class="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg cursor-pointer"
									title="Sil"
								>
									<Trash2 size={16} />
								</button>
							{/if}
							{#if !isInactive}
								<ChevronDown size={16} class="text-gray-400 transition-transform {isExpanded ? 'rotate-180' : ''}" />
							{/if}
						</div>
					</div>

					<!-- Entries (expanded) -->
					{#if isExpanded && entries.length > 0}
						<div class="border-t border-gray-100">
							<!-- Desktop: Table view -->
							<table class="w-full text-sm hidden md:table">
								<thead>
									<tr class="bg-gray-50/50 border-b border-gray-100">
										<th class="text-left px-4 py-2 font-medium text-gray-500 text-xs">Dönem</th>
										<th class="text-right px-4 py-2 font-medium text-gray-500 text-xs">Tutar</th>
										<th class="text-center px-4 py-2 font-medium text-gray-500 text-xs">Durum</th>
										<th class="text-left px-4 py-2 font-medium text-gray-500 text-xs">Ödeme Tarihi</th>
										<th class="text-left px-4 py-2 font-medium text-gray-500 text-xs">Not</th>
										{#if canUse}
											<th class="text-center px-4 py-2 font-medium text-gray-500 text-xs w-24">İşlem</th>
										{/if}
									</tr>
								</thead>
								<tbody>
									{#each entries as entry (entry.id)}
										{@const isEditing = editingEntryId === entry.id}
										{#if isEditing && canUse}
											<tr class="border-b border-gray-50 bg-teal-50/30">
												<td class="px-4 py-2.5">
													<select bind:value={entryForm.period_month} class="w-28 px-2 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500">
														{#each MONTH_NAMES as name, i}
															<option value={i + 1}>{name}</option>
														{/each}
													</select>
												</td>
												<td class="px-4 py-2.5 text-right">
													<div class="w-32 ml-auto">
														<MoneyInput bind:value={entryForm.amount} min={0} placeholder="0,00" class="px-2 py-1 rounded-lg" />
													</div>
												</td>
												<td class="px-4 py-2.5 text-center">
													<label class="inline-flex items-center gap-1.5 cursor-pointer">
														<input type="checkbox" bind:checked={entryForm.is_paid} class="w-4 h-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer" />
														<span class="text-xs text-gray-600">{entryForm.is_paid ? 'Ödendi' : 'Bekliyor'}</span>
													</label>
												</td>
												<td class="px-4 py-2.5">
													<input type="date" bind:value={entryForm.paid_date} class="w-36 px-2 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
												</td>
												<td class="px-4 py-2.5">
													<input type="text" bind:value={entryForm.notes} placeholder="Not ekle..." class="w-full px-2 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
												</td>
												<td class="px-4 py-2.5 text-center">
													<div class="flex items-center justify-center gap-1">
														<button onclick={() => saveEntryEdit(entry)} disabled={entryFormSaving} class="p-1.5 text-emerald-600 hover:bg-emerald-50 rounded-lg cursor-pointer disabled:opacity-50" title="Kaydet">
															<Check size={16} />
														</button>
														<button onclick={cancelEntryEdit} class="p-1.5 text-gray-400 hover:bg-gray-100 rounded-lg cursor-pointer" title="İptal">
															<X size={16} />
														</button>
													</div>
												</td>
											</tr>
										{:else}
											{@const pendingInfo = getPendingInfo(entry.id)}
											<tr class="border-b border-gray-50 hover:bg-gray-50/50 transition-colors {entry.is_paid ? 'opacity-60' : ''}">
												<td class="px-4 py-2.5 text-gray-700">{fmtPeriod(entry.period_month, entry.period_year)}</td>
												<td class="px-4 py-2.5 text-right font-medium text-gray-800 whitespace-nowrap">{fmt(entry.amount)}</td>
												<td class="px-4 py-2.5 text-center">
													{#if pendingInfo}
														<button
															onclick={() => openApprovalDetail(entry.id)}
															class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-50 text-orange-700 border border-orange-200 hover:bg-orange-100 transition-colors cursor-pointer"
															title="Onay detayını görüntüle"
														>
															<Clock size={12} />
															Onay Bekliyor
														</button>
													{:else if entry.is_paid}
														<StatusBadge type="success">Ödendi</StatusBadge>
													{:else}
														<StatusBadge type="warning">Bekliyor</StatusBadge>
													{/if}
												</td>
												<td class="px-4 py-2.5 text-gray-500 text-xs">{fmtDate(entry.paid_date || entry.entry_date)}</td>
												<td class="px-4 py-2.5 text-gray-500 text-xs truncate max-w-[200px]" title={entry.notes || ''}>{entry.notes || '-'}</td>
												{#if canUse}
													<td class="px-4 py-2.5 text-center">
														{#if pendingInfo}
															<button
																onclick={() => cancelApproval(entry.id)}
																class="p-1.5 text-orange-500 hover:text-orange-700 hover:bg-orange-50 rounded-lg cursor-pointer"
																title="Onay talebini iptal et"
															>
																<X size={16} />
															</button>
														{:else}
															<div class="flex items-center justify-center gap-1">
																<button onclick={() => openEntryEdit(entry)} class="p-1.5 text-gray-400 hover:text-teal-600 hover:bg-teal-50 rounded-lg cursor-pointer" title="Düzenle">
																	<Pencil size={16} />
																</button>
																<button onclick={() => togglePaid(entry)} class="p-1.5 rounded-lg transition-colors cursor-pointer {entry.is_paid ? 'text-yellow-600 hover:bg-yellow-50' : 'text-emerald-600 hover:bg-emerald-50'}" title={entry.is_paid ? 'Ödenmemiş yap' : 'Ödendi olarak işaretle'}>
																	{#if entry.is_paid}
																		<RotateCcw size={16} />
																	{:else}
																		<Check size={16} />
																	{/if}
																</button>
															</div>
														{/if}
													</td>
												{/if}
											</tr>
										{/if}
									{/each}
								</tbody>
								<tfoot>
									<tr class="border-t-2 border-gray-200 bg-gray-50">
										<td class="px-4 py-2.5 font-semibold text-gray-700 text-xs">Toplam</td>
										<td class="px-4 py-2.5 text-right font-bold text-gray-900">{fmt(entries.reduce((s: number, e: any) => s + e.amount, 0))}</td>
										<td class="px-4 py-2.5"></td>
										<td class="px-4 py-2.5"></td>
										<td class="px-4 py-2.5"></td>
										{#if canUse}
											<td class="px-4 py-2.5"></td>
										{/if}
									</tr>
								</tfoot>
							</table>

							<!-- Mobile: Card view -->
							<div class="md:hidden divide-y divide-gray-100">
								{#each entries as entry (entry.id)}
									{@const isEditing = editingEntryId === entry.id}
									{#if isEditing && canUse}
										<!-- Mobile edit -->
										<div class="p-3 bg-teal-50/30 space-y-3">
											<div class="flex items-center justify-between">
												<span class="font-medium text-gray-800">{fmtPeriod(entry.period_month, entry.period_year)}</span>
												<div class="flex items-center gap-1">
													<button onclick={() => saveEntryEdit(entry)} disabled={entryFormSaving} class="p-1.5 text-emerald-600 hover:bg-emerald-50 rounded-lg cursor-pointer disabled:opacity-50" title="Kaydet">
														<Check size={20} />
													</button>
													<button onclick={cancelEntryEdit} class="p-1.5 text-gray-400 hover:bg-gray-100 rounded-lg cursor-pointer" title="İptal">
														<X size={20} />
													</button>
												</div>
											</div>
											<div class="grid grid-cols-2 gap-2">
												<div>
													<label for="se-amount-{entry.id}" class="text-[10px] text-gray-500 uppercase font-medium">Tutar</label>
													<MoneyInput id="se-amount-{entry.id}" bind:value={entryForm.amount} min={0} placeholder="0,00" class="px-2 py-1.5 rounded-lg" />
												</div>
												<div>
													<label for="se-period-{entry.id}" class="text-[10px] text-gray-500 uppercase font-medium">Dönem</label>
													<select id="se-period-{entry.id}" bind:value={entryForm.period_month} class="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500">
													{#each MONTH_NAMES as name, i}
														<option value={i + 1}>{name}</option>
													{/each}
												</select>
											</div>
											<div>
												<label for="se-entry-{entry.id}" class="text-[10px] text-gray-500 uppercase font-medium">Ödeme Tarihi</label>
												<input id="se-entry-{entry.id}" type="date" bind:value={entryForm.entry_date} class="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
												</div>
												<div>
													<label for="se-paid-{entry.id}" class="text-[10px] text-gray-500 uppercase font-medium">Ödendi Tarihi</label>
													<input id="se-paid-{entry.id}" type="date" bind:value={entryForm.paid_date} class="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
												</div>
											</div>
											<div class="flex items-center gap-4">
												<label class="inline-flex items-center gap-2 cursor-pointer">
													<input type="checkbox" bind:checked={entryForm.is_paid} class="w-4 h-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer" />
													<span class="text-sm text-gray-700">{entryForm.is_paid ? 'Ödendi' : 'Bekliyor'}</span>
												</label>
											</div>
											<div>
												<label for="se-notes-{entry.id}" class="text-[10px] text-gray-500 uppercase font-medium">Not</label>
												<input id="se-notes-{entry.id}" type="text" bind:value={entryForm.notes} placeholder="Not ekle..." class="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
											</div>
										</div>
									{:else}
										<!-- Mobile display -->
										{@const mPendingInfo = getPendingInfo(entry.id)}
										<div class="px-3 py-2.5 flex items-center gap-3 {entry.is_paid ? 'opacity-60' : ''}">
											<div class="flex-1 min-w-0">
												<div class="flex items-center gap-2 flex-wrap">
													<span class="text-sm font-medium text-gray-800">{fmtPeriod(entry.period_month, entry.period_year)}</span>
													{#if mPendingInfo}
														<button
															onclick={() => openApprovalDetail(entry.id)}
															class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-orange-50 text-orange-700 border border-orange-200 hover:bg-orange-100 transition-colors cursor-pointer"
															title="Onay detayını görüntüle"
														>
															<Clock size={10} />
															Onay Bekliyor
														</button>
													{:else if entry.is_paid}
														<StatusBadge type="success">Ödendi</StatusBadge>
													{:else}
														<StatusBadge type="warning">Bekliyor</StatusBadge>
													{/if}
												</div>
												<div class="flex items-center gap-2 mt-0.5">
													<span class="text-sm font-bold text-gray-800">{fmt(entry.amount)}</span>
													<span class="text-[11px] text-gray-400">• {fmtDate(entry.paid_date || entry.entry_date)}</span>
												</div>
												{#if entry.notes}
													<p class="text-[11px] text-gray-400 mt-0.5 truncate">{entry.notes}</p>
												{/if}
											</div>
											{#if canUse}
												<div class="flex items-center gap-0.5 shrink-0">
													{#if mPendingInfo}
														<button onclick={() => cancelApproval(entry.id)} class="p-1.5 text-orange-500 hover:text-orange-700 hover:bg-orange-50 rounded-lg cursor-pointer" title="Onay talebini iptal et">
															<X size={16} />
														</button>
													{:else}
														<button onclick={() => openEntryEdit(entry)} class="p-1.5 text-gray-400 hover:text-teal-600 hover:bg-teal-50 rounded-lg cursor-pointer" title="Düzenle">
															<Pencil size={16} />
														</button>
														<button onclick={() => togglePaid(entry)} class="p-1.5 rounded-lg transition-colors cursor-pointer {entry.is_paid ? 'text-yellow-600 hover:bg-yellow-50' : 'text-emerald-600 hover:bg-emerald-50'}" title={entry.is_paid ? 'Ödenmemiş yap' : 'Ödendi olarak işaretle'}>
															{#if entry.is_paid}
																<RotateCcw size={16} />
															{:else}
																<Check size={16} />
															{/if}
														</button>
													{/if}
												</div>
											{/if}
										</div>
									{/if}
								{/each}
								<!-- Mobile total -->
								<div class="px-3 py-2.5 bg-gray-50 flex items-center justify-between">
									<span class="text-xs font-semibold text-gray-600">Toplam</span>
									<span class="text-sm font-bold text-gray-900">{fmt(entries.reduce((s: number, e: any) => s + e.amount, 0))}</span>
								</div>
							</div>
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</div>

<!-- Create/Edit Modal -->
<Modal bind:show={showModal} title={editItem ? `${title} Düzenle` : `Yeni ${title}`} maxWidth="max-w-lg">
	<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4">
		{#if formError}
			<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{formError}</div>
		{/if}

		<div>
			<label for="name" class="block text-sm font-medium text-gray-700 mb-1">Ad *</label>
			<input
				id="name" type="text" bind:value={form.name}
				placeholder="Adını girin"
				class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
			/>
		</div>

		{#if showCategory}
			<div>
				<label for="category" class="block text-sm font-medium text-gray-700 mb-1">{categoryLabel}</label>
				{#if categories.length > 0}
					<select id="category" bind:value={form.category} class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer">
						<option value="">Seçiniz</option>
						{#each categories as cat}
							<option value={cat}>{cat}</option>
						{/each}
					</select>
				{:else}
					<input id="category" type="text" bind:value={form.category} placeholder="Kategori" class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
				{/if}
			</div>
		{/if}

		<div class="grid grid-cols-2 gap-4">
			<div>
				<label for="amount" class="block text-sm font-medium text-gray-700 mb-1">Tutar *</label>
				<MoneyInput id="amount" bind:value={form.amount} currency={form.currency} min={0} placeholder="0,00" />
			</div>
			<div>
				<label for="frequency" class="block text-sm font-medium text-gray-700 mb-1">Periyot</label>
				<select id="frequency" bind:value={form.frequency} class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer">
					<option value="monthly">Aylık</option>
					<option value="quarterly">3 Aylık</option>
					<option value="yearly">Yıllık</option>
				</select>
			</div>
		</div>

		<div class="grid grid-cols-2 gap-4">
			<div>
				<label for="start_month" class="block text-sm font-medium text-gray-700 mb-1">Başlangıç Ayı</label>
				<select id="start_month" bind:value={form.start_month} class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer">
					{#each MONTH_NAMES as m, i}
						<option value={i + 1}>{m}</option>
					{/each}
				</select>
			</div>
			<div>
				<label for="payment_day" class="block text-sm font-medium text-gray-700 mb-1">Ödeme Günü</label>
				<input id="payment_day" type="number" min="1" max="28" bind:value={form.payment_day} class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
			</div>
		</div>

		<div>
			<label for="notes" class="block text-sm font-medium text-gray-700 mb-1">Notlar</label>
			<textarea id="notes" bind:value={form.notes} rows="2" placeholder="İsteğe bağlı notlar" class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"></textarea>
		</div>

		<div class="flex justify-end gap-3 pt-2">
			<button type="button" onclick={() => showModal = false} class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 cursor-pointer">İptal</button>
			<button type="submit" disabled={saving} class="px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium hover:bg-teal-700 disabled:opacity-50 cursor-pointer">
				{saving ? 'Kaydediliyor...' : (editItem ? 'Güncelle' : 'Kaydet')}
			</button>
		</div>
	</form>
</Modal>

<!-- Onay Detay Modal -->
<Modal bind:show={showApprovalDetail} title="Onay Talebi Detayı" maxWidth="max-w-lg">
	{#if approvalDetailLoading}
		<div class="flex items-center justify-center py-8">
			<div class="animate-spin h-6 w-6 border-4 border-teal-200 border-t-teal-600 rounded-full"></div>
		</div>
	{:else if approvalDetail}
		{@const payload = parsePayload(approvalDetail.payload_json)}
		{@const actionLabels = { create: 'Oluşturma', update: 'Güncelleme', delete: 'Silme' } as Record<string, string>}
		<div class="space-y-4">
			<!-- Genel bilgi -->
			<div class="grid grid-cols-2 gap-3 text-sm">
				<div>
					<span class="text-gray-500">İşlem Türü</span>
					<div class="mt-0.5">
						{#if approvalDetail.action_type === 'create'}
							<StatusBadge type="success">Oluşturma</StatusBadge>
						{:else if approvalDetail.action_type === 'update'}
							<StatusBadge type="info">Güncelleme</StatusBadge>
						{:else if approvalDetail.action_type === 'delete'}
							<StatusBadge type="error">Silme</StatusBadge>
						{:else}
							<span class="text-gray-800">{approvalDetail.action_type || '-'}</span>
						{/if}
					</div>
				</div>
				<div>
					<span class="text-gray-500">Talep Eden</span>
					<div class="mt-0.5 font-medium text-gray-800">{approvalDetail.requested_by_name || '-'}</div>
				</div>
				<div>
					<span class="text-gray-500">Talep Tarihi</span>
					<div class="mt-0.5 text-gray-800">{approvalDetail.requested_at ? new Date(approvalDetail.requested_at).toLocaleString('tr-TR') : '-'}</div>
				</div>
				<div>
					<span class="text-gray-500">İş Akışı</span>
					<div class="mt-0.5 text-gray-800">{approvalDetail.workflow_name || '-'}</div>
				</div>
			</div>

			<!-- Değişiklik detayları -->
			{#if payload && Object.keys(payload).length > 0}
				<div>
					<h4 class="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
						<FileClock size={16} class="text-orange-500" />
						Bekleyen Değişiklikler
					</h4>
					<div class="bg-orange-50/50 border border-orange-200 rounded-lg overflow-hidden">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-orange-200 bg-orange-50">
									<th class="text-left px-3 py-2 font-medium text-orange-800 text-xs">Alan</th>
									<th class="text-left px-3 py-2 font-medium text-orange-800 text-xs">Yeni Değer</th>
								</tr>
							</thead>
							<tbody>
								{#each Object.entries(payload).filter(([k]) => k !== '_target') as [key, value], i}
									<tr class="{i % 2 === 0 ? 'bg-white' : 'bg-orange-50/30'} border-b border-orange-100 last:border-b-0">
										<td class="px-3 py-2 text-gray-600 font-medium">{getFieldLabel(key)}</td>
										<td class="px-3 py-2 text-gray-800">{formatFieldValue(key, value)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{:else if approvalDetail.action_type === 'delete'}
				<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
					Bu kayıt silinmek üzere onay bekliyor.
				</div>
			{/if}

			<!-- Onay aksiyonları (yetkili kullanıcılar) -->
			{#if canApprove && approvalDetail.status === 'pending'}
				<div class="border-t border-gray-200 pt-4">
					<h4 class="text-sm font-semibold text-gray-700 mb-3">Onay İşlemleri</h4>
					<div class="flex flex-wrap gap-2">
						<button
							onclick={() => openApprovalAction('approve', approvalDetail.id)}
							class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 transition-colors cursor-pointer"
						>
							<Check size={16} />
							Onayla
						</button>
						<button
							onclick={() => openApprovalAction('reject', approvalDetail.id)}
							class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors cursor-pointer"
						>
							<X size={16} />
							Reddet
						</button>
						<button
							onclick={() => openApprovalAction('return', approvalDetail.id)}
							class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-amber-700 bg-amber-100 rounded-lg hover:bg-amber-200 transition-colors cursor-pointer border border-amber-300"
						>
							<RotateCcw size={16} />
							İade Et
						</button>
					</div>
				</div>
			{/if}

			<div class="flex justify-end pt-2">
				<button onclick={() => showApprovalDetail = false} class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 cursor-pointer">Kapat</button>
			</div>
		</div>
	{/if}
</Modal>

<!-- Onay Aksiyon Modal -->
<Modal bind:show={showActionModal} title={actionType === 'approve' ? 'Onayla' : actionType === 'reject' ? 'Reddet' : 'İade Et'} maxWidth="max-w-sm">
	<div class="space-y-4">
		{#if actionType === 'approve'}
			<p class="text-sm text-gray-600">Bu talebi onaylamak istediğinize emin misiniz?</p>
			<div>
				<label for="action-note" class="block text-sm font-medium text-gray-700 mb-1">Not <span class="text-gray-400 font-normal">(opsiyonel)</span></label>
				<textarea id="action-note" bind:value={actionNote} rows="2" placeholder="Onay notu ekleyin..." class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"></textarea>
			</div>
		{:else if actionType === 'reject'}
			<p class="text-sm text-gray-600">Bu talebi reddetmek istediğinize emin misiniz?</p>
			<div>
				<label for="action-note" class="block text-sm font-medium text-gray-700 mb-1">Red gerekçesi <span class="text-red-500">*</span></label>
				<textarea id="action-note" bind:value={actionNote} rows="3" placeholder="Red gerekçenizi yazın..." class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-red-500 resize-none"></textarea>
			</div>
		{:else}
			<p class="text-sm text-gray-600">Bu talebi düzeltme için iade etmek istediğinize emin misiniz?</p>
			<div>
				<label for="action-note" class="block text-sm font-medium text-gray-700 mb-1">İade gerekçesi <span class="text-red-500">*</span></label>
				<textarea id="action-note" bind:value={actionNote} rows="3" placeholder="İade gerekçenizi yazın..." class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500 resize-none"></textarea>
			</div>
		{/if}

		<div class="flex justify-end gap-3 pt-1">
			<button onclick={() => showActionModal = false} class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 cursor-pointer">Vazgeç</button>
			{#if actionType === 'approve'}
				<button
					onclick={executeApprovalAction}
					disabled={actionProcessing}
					class="px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 cursor-pointer"
				>
					{actionProcessing ? 'İşleniyor...' : 'Onayla'}
				</button>
			{:else if actionType === 'reject'}
				<button
					onclick={executeApprovalAction}
					disabled={actionProcessing || !actionNote.trim()}
					class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50 cursor-pointer"
				>
					{actionProcessing ? 'İşleniyor...' : 'Reddet'}
				</button>
			{:else}
				<button
					onclick={executeApprovalAction}
					disabled={actionProcessing || !actionNote.trim()}
					class="px-4 py-2 bg-amber-600 text-white rounded-lg text-sm font-medium hover:bg-amber-700 disabled:opacity-50 cursor-pointer"
				>
					{actionProcessing ? 'İşleniyor...' : 'İade Et'}
				</button>
			{/if}
		</div>
	</div>
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Kaydı Sil"
	message="{deleteItem?.name || ''} kaydını ve tüm girişlerini silmek istediğinize emin misiniz?"
	confirmText="Sil"
	cancelText="Vazgeç"
	danger={true}
	onConfirm={confirmDelete}
/>
