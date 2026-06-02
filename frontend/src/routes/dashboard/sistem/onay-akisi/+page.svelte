<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Button from '$lib/components/Button.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { ClipboardCheck, Inbox, Plus } from 'lucide-svelte';

	// ── Sabitler ──────────────────────────────────────────────
	const STATUS_MAP: Record<string, { label: string; bg: string; text: string; border: string }> = {
		pending: { label: 'Bekliyor', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
		approved: { label: 'Onaylandı', bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
		rejected: { label: 'Reddedildi', bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200' },
		returned: { label: 'İade Edildi', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
		cancelled: { label: 'İptal Edildi', bg: 'bg-gray-100', text: 'text-gray-500', border: 'border-gray-200' },
	};

	const ACTION_TYPE_LABELS: Record<string, string> = {
		create: 'Oluşturma',
		update: 'Güncelleme',
		delete: 'Silme',
	};

	const TABS = ['definitions', 'pending', 'submissions', 'history'] as const;
	type TabKey = typeof TABS[number];

	// ── Arayüzler ─────────────────────────────────────────────
	interface RoleSummary {
		id: number;
		name: string;
	}

	interface ModuleWithRoles {
		id: number;
		name: string;
		code: string;
		parent_id: number | null;
		roles: RoleSummary[];
	}

	interface ModuleGroup {
		parent: ModuleWithRoles | null;
		parentName: string;
		children: ModuleWithRoles[];
	}

	interface Workflow {
		id: number;
		name: string;
		module_id: number | null;
		module_code: string | null;
		module_name: string | null;
		description: string | null;
		is_active: boolean;
		conditions_json: string | null;
		requestor_roles: RoleSummary[];
		approver_roles: RoleSummary[];
		created_by_name: string | null;
		created_at: string;
		updated_at: string | null;
	}

	interface RequestLog {
		id: number;
		step_number: number;
		action: string;
		actor_id: number;
		actor_name: string;
		note: string | null;
		created_at: string;
	}

	interface ApprovalRequest {
		id: number;
		workflow_id: number;
		workflow_name: string;
		entity_type: string;
		entity_id: number;
		entity_summary: string;
		module_code: string | null;
		action_type: string | null;
		payload_json: string | null;
		status: string;
		current_step: number;
		total_steps: number;
		requested_by: number;
		requested_by_name: string;
		requested_at: string;
		completed_at: string | null;
		completed_by_name: string | null;
		current_step_approver_name: string | null;
		logs: RequestLog[];
	}

	// ── Türetilmiş ────────────────────────────────────────────
	let canUse = hasPermission('system', 'use');

	// ── State ─────────────────────────────────────────────────
	// Tab
	let activeTab = $state<TabKey>('pending');

	// Modül listesi (modules-with-roles)
	let modules = $state<ModuleWithRoles[]>([]);

	// Tanımlar
	let workflows = $state<Workflow[]>([]);
	let workflowsLoading = $state(true);
	let showWorkflowModal = $state(false);
	let editingWorkflow = $state<Workflow | null>(null);
	let wfName = $state('');
	let wfModuleId = $state<number | null>(null);
	let wfDescription = $state('');
	let wfConditions = $state('');
	let wfRequestorRoleIds = $state<number[]>([]);
	let wfApproverRoleIds = $state<number[]>([]);
	let wfSaving = $state(false);
	let showDeleteConfirm = $state(false);
	let deletingWorkflow = $state<Workflow | null>(null);
	let deleting = $state(false);

	// Bekleyen Onaylar
	let pendingRequests = $state<ApprovalRequest[]>([]);
	let pendingLoading = $state(true);
	let pendingCount = $state(0);
	let pendingPage = $state(1);
	let pendingPages = $state(1);

	// Onay/Red/İade modal
	let showActionModal = $state(false);
	let actionType = $state<'approve' | 'reject' | 'return'>('approve');
	let actionRequest = $state<ApprovalRequest | null>(null);
	let actionNote = $state('');
	let actionProcessing = $state(false);

	// Gönderdiklerim
	let mySubmissions = $state<ApprovalRequest[]>([]);
	let submissionsLoading = $state(true);
	let submissionsPage = $state(1);
	let submissionsPages = $state(1);
	let cancellingId = $state<number | null>(null);
	let resubmittingId = $state<number | null>(null);

	// Geçmiş
	let historyRequests = $state<ApprovalRequest[]>([]);
	let historyLoading = $state(true);
	let historyPage = $state(1);
	let historyPages = $state(1);
	let historyStatusFilter = $state<string>('');

	// Detay modal
	let showDetailModal = $state(false);
	let detailRequest = $state<ApprovalRequest | null>(null);

	// ── Türetilmiş state ──────────────────────────────────────
	let groupedModules = $derived.by(() => {
		const groups: ModuleGroup[] = [];
		// Üst modüller (parent_id null olanlar)
		const parents = modules.filter(m => m.parent_id === null);
		// Alt modüller (parent_id olanlar)
		const children = modules.filter(m => m.parent_id !== null);

		// Her üst modülün altındaki alt modülleri grupla
		const parentMap = new Map<number, ModuleWithRoles[]>();
		for (const c of children) {
			if (!parentMap.has(c.parent_id!)) parentMap.set(c.parent_id!, []);
			parentMap.get(c.parent_id!)!.push(c);
		}

		// Üst modülleri sırayla ekle
		for (const p of parents) {
			const kids = parentMap.get(p.id) ?? [];
			if (kids.length > 0 || p.roles.length > 0) {
				groups.push({ parent: p, parentName: p.name, children: kids });
			}
		}

		// Üst modülü olmayan (orphan) alt modüller
		const knownParentIds = new Set(parents.map(p => p.id));
		const orphans = children.filter(c => !knownParentIds.has(c.parent_id!));
		if (orphans.length > 0) {
			groups.push({ parent: null, parentName: 'Diğer', children: orphans });
		}

		return groups;
	});

	let availableRoles = $derived.by(() => {
		if (!wfModuleId) return [];
		const m = modules.find(mod => mod.id === wfModuleId);
		return m ? m.roles : [];
	});

	// ── Formatlama fonksiyonları ───────────────────────────────
	function formatDate(d: string): string {
		return new Date(d).toLocaleDateString('tr-TR', {
			day: '2-digit', month: '2-digit', year: 'numeric',
		});
	}

	function formatDateTime(d: string): string {
		return new Date(d).toLocaleDateString('tr-TR', {
			day: '2-digit', month: '2-digit', year: 'numeric',
			hour: '2-digit', minute: '2-digit',
		});
	}

	function formatRelative(d: string): string {
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

	function statusInfo(status: string) {
		return STATUS_MAP[status] ?? STATUS_MAP.pending;
	}

	// ── Veri fonksiyonları ─────────────────────────────────────
	async function loadModulesWithRoles() {
		try {
			modules = await api.get<ModuleWithRoles[]>('/system/approval/modules-with-roles');
		} catch (err) {
			console.error('Modüller yüklenemedi:', err);
		}
	}

	async function loadWorkflows() {
		workflowsLoading = true;
		try {
			const data = await api.get<any>('/system/approval/workflows?page=1&page_size=100');
			workflows = data.items ?? [];
		} catch (err) {
			console.error('İş akışları yüklenemedi:', err);
			showToast('İş akışları yüklenemedi', 'error');
		} finally {
			workflowsLoading = false;
		}
	}

	async function loadPending() {
		pendingLoading = true;
		try {
			const [data, countData] = await Promise.all([
				api.get<any>(`/system/approval/requests/pending?page=${pendingPage}&page_size=20`),
				api.get<any>('/system/approval/requests/pending/count'),
			]);
			pendingRequests = data.items ?? [];
			pendingPages = data.pages ?? 1;
			pendingCount = countData.count ?? 0;
		} catch (err) {
			console.error('Bekleyen onaylar yüklenemedi:', err);
			showToast('Bekleyen onaylar yüklenemedi', 'error');
		} finally {
			pendingLoading = false;
		}
	}

	async function loadSubmissions() {
		submissionsLoading = true;
		try {
			const data = await api.get<any>(`/system/approval/requests/my-submissions?page=${submissionsPage}&page_size=20`);
			mySubmissions = data.items ?? [];
			submissionsPages = data.pages ?? 1;
		} catch (err) {
			console.error('Gönderilen talepler yüklenemedi:', err);
			showToast('Gönderilen talepler yüklenemedi', 'error');
		} finally {
			submissionsLoading = false;
		}
	}

	async function loadHistory() {
		historyLoading = true;
		try {
			let url = `/system/approval/requests/history?page=${historyPage}&page_size=20`;
			if (historyStatusFilter) url += `&status_filter=${historyStatusFilter}`;
			const data = await api.get<any>(url);
			historyRequests = data.items ?? [];
			historyPages = data.pages ?? 1;
		} catch (err) {
			console.error('Onay geçmişi yüklenemedi:', err);
			showToast('Onay geçmişi yüklenemedi', 'error');
		} finally {
			historyLoading = false;
		}
	}

	async function loadTabData(tab: TabKey) {
		if (tab === 'definitions') await loadWorkflows();
		else if (tab === 'pending') await loadPending();
		else if (tab === 'submissions') await loadSubmissions();
		else if (tab === 'history') await loadHistory();
	}

	// ── CRUD: Tanımlar ────────────────────────────────────────
	function openCreateWorkflow() {
		editingWorkflow = null;
		wfName = '';
		wfModuleId = null;
		wfDescription = '';
		wfConditions = '';
		wfRequestorRoleIds = [];
		wfApproverRoleIds = [];
		showWorkflowModal = true;
	}

	function openEditWorkflow(wf: Workflow) {
		editingWorkflow = wf;
		wfName = wf.name;
		wfModuleId = wf.module_id;
		wfDescription = wf.description ?? '';
		wfConditions = wf.conditions_json ?? '';
		wfRequestorRoleIds = wf.requestor_roles.map(r => r.id);
		wfApproverRoleIds = wf.approver_roles.map(r => r.id);
		showWorkflowModal = true;
	}

	function toggleRoleId(list: number[], roleId: number): number[] {
		return list.includes(roleId)
			? list.filter(id => id !== roleId)
			: [...list, roleId];
	}

	async function saveWorkflow() {
		if (!wfName.trim()) {
			showToast('Onay adı zorunludur', 'error');
			return;
		}
		if (!wfModuleId) {
			showToast('Modül seçimi zorunludur', 'error');
			return;
		}
		if (wfRequestorRoleIds.length === 0) {
			showToast('En az bir talep eden rol seçmelisiniz', 'error');
			return;
		}
		if (wfApproverRoleIds.length === 0) {
			showToast('En az bir onay veren rol seçmelisiniz', 'error');
			return;
		}
		wfSaving = true;
		try {
			const body: Record<string, any> = {
				name: wfName.trim(),
				module_id: wfModuleId,
				description: wfDescription.trim() || null,
				conditions_json: wfConditions.trim() || null,
				requestor_role_ids: wfRequestorRoleIds,
				approver_role_ids: wfApproverRoleIds,
			};

			if (editingWorkflow) {
				await api.patch(`/system/approval/workflows/${editingWorkflow.id}`, body);
				showToast('Onay tanımı güncellendi', 'success');
			} else {
				await api.post('/system/approval/workflows', body);
				showToast('Onay tanımı oluşturuldu', 'success');
			}
			showWorkflowModal = false;
			await loadWorkflows();
		} catch (err) {
			console.error('Onay tanımı kaydedilemedi:', err);
			showToast('Onay tanımı kaydedilemedi', 'error');
		} finally {
			wfSaving = false;
		}
	}

	function confirmDeleteWorkflow(wf: Workflow) {
		deletingWorkflow = wf;
		showDeleteConfirm = true;
	}

	async function deleteWorkflow() {
		if (!deletingWorkflow) return;
		deleting = true;
		try {
			await api.delete(`/system/approval/workflows/${deletingWorkflow.id}`);
			showToast('Onay tanımı silindi', 'success');
			showDeleteConfirm = false;
			deletingWorkflow = null;
			await loadWorkflows();
		} catch (err) {
			console.error('Onay tanımı silinemedi:', err);
			showToast('Onay tanımı silinemedi', 'error');
		} finally {
			deleting = false;
		}
	}

	// ── Onay/Red/İade işlemleri ───────────────────────────────
	function openAction(type: 'approve' | 'reject' | 'return', req: ApprovalRequest) {
		actionType = type;
		actionRequest = req;
		actionNote = '';
		showActionModal = true;
	}

	function actionTitle(): string {
		if (actionType === 'approve') return 'Onayla';
		if (actionType === 'reject') return 'Reddet';
		return 'İade Et';
	}

	async function executeAction() {
		if (!actionRequest || actionProcessing) return;
		if ((actionType === 'reject' || actionType === 'return') && !actionNote.trim()) {
			showToast(`${actionType === 'reject' ? 'Red' : 'İade'} gerekçesi zorunludur`, 'error');
			return;
		}
		actionProcessing = true;
		try {
			const body: Record<string, string> = {};
			if (actionNote.trim()) body.note = actionNote.trim();

			await api.post(`/system/approval/requests/${actionRequest.id}/${actionType}`, body);

			const labels: Record<string, string> = { approve: 'onaylandı', reject: 'reddedildi', return: 'iade edildi' };
			showToast(`Talep ${labels[actionType]}`, 'success');
			showActionModal = false;
			actionRequest = null;
			await loadPending();
		} catch (err) {
			console.error('İşlem başarısız:', err);
			showToast('İşlem gerçekleştirilemedi', 'error');
		} finally {
			actionProcessing = false;
		}
	}

	// ── Gönderdiklerim işlemleri ──────────────────────────────
	async function cancelRequest(req: ApprovalRequest) {
		cancellingId = req.id;
		try {
			await api.post(`/system/approval/requests/${req.id}/cancel`, {});
			showToast('Talep iptal edildi', 'success');
			await loadSubmissions();
		} catch (err) {
			console.error('Talep iptal edilemedi:', err);
			showToast('Talep iptal edilemedi', 'error');
		} finally {
			cancellingId = null;
		}
	}

	async function resubmitRequest(req: ApprovalRequest) {
		resubmittingId = req.id;
		try {
			await api.post(`/system/approval/requests/${req.id}/resubmit`, {});
			showToast('Talep yeniden gönderildi', 'success');
			await loadSubmissions();
		} catch (err) {
			console.error('Talep yeniden gönderilemedi:', err);
			showToast('Talep yeniden gönderilemedi', 'error');
		} finally {
			resubmittingId = null;
		}
	}

	// ── Detay ─────────────────────────────────────────────────
	function openDetail(req: ApprovalRequest) {
		detailRequest = req;
		showDetailModal = true;
	}

	function parsePayload(json: string | null): Record<string, any> | null {
		if (!json) return null;
		try { return JSON.parse(json); } catch (e) { console.error('Onay payload JSON parse edilemedi:', e); return null; }
	}

	const FIELD_LABELS: Record<string, string> = {
		name: 'Ad', amount: 'Tutar', currency: 'Para Birimi',
		frequency: 'Periyot', payment_day: 'Ödeme Günü',
		start_month: 'Başlangıç Ayı', year: 'Yıl', notes: 'Not',
		category: 'Kategori', is_paid: 'Ödendi', paid_date: 'Ödeme Tarihi',
		is_active: 'Aktif', description: 'Açıklama', bank_name: 'Banka Adı',
		branch_name: 'Şube Adı', account_number: 'Hesap No', iban: 'IBAN',
		account_type: 'Hesap Türü', balance: 'Bakiye', first_name: 'Ad',
		last_name: 'Soyad', email: 'E-posta', role_id: 'Rol',
		title: 'Başlık', code: 'Kod', parent_id: 'Üst Modül',
		check_number: 'Çek No', status: 'Durum', due_date: 'Vade Tarihi',
		vendor_name: 'Cari Adı', payment_days: 'Ödeme Vadesi (gün)',
		product_name: 'Ürün Adı', credit_type: 'Kredi Türü',
		interest_rate: 'Faiz Oranı', total_amount: 'Toplam Tutar',
		principal: 'Anapara', interest: 'Faiz', installment: 'Taksit',
	};

	const FREQ_LABELS_MAP: Record<string, string> = {
		monthly: 'Aylık', quarterly: '3 Aylık', yearly: 'Yıllık',
	};
	const MONTH_NAMES_MAP = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	function getFieldLabel(key: string): string {
		return FIELD_LABELS[key] || key;
	}

	function formatFieldValue(key: string, value: any): string {
		if (value === null || value === undefined) return '-';
		if (typeof value === 'boolean') return value ? 'Evet' : 'Hayır';
		if ((key === 'amount' || key === 'balance' || key === 'total_amount' || key === 'principal' || key === 'interest' || key === 'installment') && typeof value === 'number') {
			return `₺${value.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
		}
		if (key === 'frequency') return FREQ_LABELS_MAP[value] || String(value);
		if (key === 'start_month' && typeof value === 'number' && value >= 1 && value <= 12) return MONTH_NAMES_MAP[value - 1];
		return String(value);
	}

	// ── UI yardımcıları ───────────────────────────────────────
	function switchTab(tab: TabKey) {
		activeTab = tab;
		loadTabData(tab);
	}

	// ── Lifecycle ─────────────────────────────────────────────
	let unsubApproval: (() => void) | null = null;
	let unsubNotification: (() => void) | null = null;

	onMount(() => {
		loadModulesWithRoles();
		loadPending();
		loadWorkflows();
		loadSubmissions();

		unsubApproval = onWsEvent('approval_updated', () => {
			loadPending();
			loadSubmissions();
		});
		unsubNotification = onWsEvent('notification', () => {
			loadPending();
		});
	});

	onDestroy(() => {
		unsubApproval?.();
		unsubNotification?.();
	});
</script>

<svelte:head>
	<title>Onay Akışı | Sprenses</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 py-6">
	<!-- Sayfa Başlığı -->
	<div class="mb-6">
		<h1 class="text-2xl font-semibold text-gray-900">Onay Akışı</h1>
		<p class="text-sm text-gray-500 mt-1">Onay tanımları, bekleyen onaylar ve gönderilen talepler</p>
	</div>

	<!-- Tab Bar -->
	<div class="flex items-center gap-1 border-b border-gray-200 mb-6 overflow-x-auto">
		<button
			onclick={() => switchTab('definitions')}
			class="px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors cursor-pointer
				{activeTab === 'definitions'
					? 'text-teal-700 border-b-2 border-teal-600'
					: 'text-gray-500 hover:text-gray-700'}"
		>
			Tanımlar
		</button>
		<button
			onclick={() => switchTab('pending')}
			class="px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors cursor-pointer inline-flex items-center gap-2
				{activeTab === 'pending'
					? 'text-teal-700 border-b-2 border-teal-600'
					: 'text-gray-500 hover:text-gray-700'}"
		>
			Bekleyen Onaylar
			{#if pendingCount > 0}
				<span class="inline-flex items-center justify-center px-2 py-0.5 rounded-full text-xs font-semibold bg-teal-100 text-teal-700 min-w-[20px]">
					{pendingCount}
				</span>
			{/if}
		</button>
		<button
			onclick={() => switchTab('submissions')}
			class="px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors cursor-pointer
				{activeTab === 'submissions'
					? 'text-teal-700 border-b-2 border-teal-600'
					: 'text-gray-500 hover:text-gray-700'}"
		>
			Gönderdiklerim
		</button>
		<button
			onclick={() => switchTab('history')}
			class="px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors cursor-pointer
				{activeTab === 'history'
					? 'text-teal-700 border-b-2 border-teal-600'
					: 'text-gray-500 hover:text-gray-700'}"
		>
			Geçmiş
		</button>
	</div>

	<!-- ═══════════════════ TAB 1: TANIMLAR ═══════════════════ -->
	{#if activeTab === 'definitions'}
		<!-- Üst Bar -->
		{#if canUse}
			<div class="flex justify-end mb-4">
				<Button onclick={openCreateWorkflow}><Plus size={16} /> Yeni Tanım</Button>
			</div>
		{/if}

		{#if workflowsLoading}
			<TableSkeleton rows={4} columns={3} />
		{:else if workflows.length === 0}
			<EmptyState
				icon={ClipboardCheck}
				title="Henüz onay tanımı oluşturulmadı"
				description="Yeni bir onay tanımı oluşturarak başlayın"
			/>
		{:else}
			<div class="space-y-3">
				{#each workflows as wf (wf.id)}
					<div class="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sm:p-5">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2 mb-1">
									<h3 class="text-base font-bold text-gray-800 truncate">{wf.name}</h3>
									{#if wf.is_active}
										<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">Aktif</span>
									{:else}
										<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500 border border-gray-200">Pasif</span>
									{/if}
								</div>
								<div class="flex flex-wrap items-center gap-2 text-sm text-gray-500 mb-2">
									<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-teal-50 text-teal-700 border border-teal-200">
										{wf.module_name ?? wf.module_code ?? '—'}
									</span>
									{#if wf.description}
										<span class="text-gray-500">|</span>
										<span class="truncate max-w-xs">{wf.description}</span>
									{/if}
								</div>
								<!-- Rol bilgileri -->
								<div class="flex flex-col sm:flex-row gap-2 text-xs text-gray-500">
									<div class="flex items-center gap-1.5">
										<span class="text-gray-500">Talep:</span>
										<div class="flex flex-wrap gap-1">
											{#each wf.requestor_roles as role}
												<span class="inline-flex items-center px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-100">
													{role.name}
												</span>
											{/each}
										</div>
									</div>
									<svg class="w-4 h-4 text-gray-500 hidden sm:block shrink-0 self-center" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
										<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
									</svg>
									<div class="flex items-center gap-1.5">
										<span class="text-gray-500">Onay:</span>
										<div class="flex flex-wrap gap-1">
											{#each wf.approver_roles as role}
												<span class="inline-flex items-center px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-100">
													{role.name}
												</span>
											{/each}
										</div>
									</div>
								</div>
							</div>
							{#if canUse}
								<div class="flex items-center gap-2 shrink-0">
									<button
										onclick={() => openEditWorkflow(wf)}
										class="p-2 rounded-lg text-gray-500 hover:text-teal-600 hover:bg-teal-50 transition-colors cursor-pointer"
										title="Düzenle"
									>
										<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
											<path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
										</svg>
									</button>
									<button
										onclick={() => confirmDeleteWorkflow(wf)}
										class="p-2 rounded-lg text-gray-500 hover:text-red-600 hover:bg-red-50 transition-colors cursor-pointer"
										title="Sil"
									>
										<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
											<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
										</svg>
									</button>
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}

	<!-- ═══════════════════ TAB 2: BEKLEYEN ONAYLAR ═══════════════════ -->
	{:else if activeTab === 'pending'}
		{#if pendingLoading}
			<TableSkeleton rows={4} columns={3} />
		{:else if pendingRequests.length === 0}
			<EmptyState
				icon={Inbox}
				title="Onay bekleyen talep bulunmuyor"
				description="Tüm talepler incelendi"
			/>
		{:else}
			<div class="space-y-4">
				{#each pendingRequests as req (req.id)}
					<div class="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sm:p-5">
						<!-- Üst: Özet + İş Akışı -->
						<div class="flex items-start justify-between gap-3 mb-3">
							<div class="min-w-0 flex-1">
								<h3 class="text-base font-bold text-gray-800 truncate">{req.entity_summary}</h3>
								<div class="flex flex-wrap items-center gap-2 mt-1 text-sm text-gray-500">
									{#if req.action_type}
										<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium
											{req.action_type === 'create' ? 'bg-blue-50 text-blue-700 border border-blue-200' : ''}
											{req.action_type === 'update' ? 'bg-amber-50 text-amber-700 border border-amber-200' : ''}
											{req.action_type === 'delete' ? 'bg-red-50 text-red-600 border border-red-200' : ''}
										">
											{ACTION_TYPE_LABELS[req.action_type] ?? req.action_type}
										</span>
									{/if}
									<span>{req.workflow_name}</span>
								</div>
							</div>
							<button
								onclick={() => openDetail(req)}
								class="p-2 rounded-lg text-gray-500 hover:text-teal-600 hover:bg-teal-50 transition-colors cursor-pointer shrink-0"
								title="Detay"
							>
								<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
									<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
								</svg>
							</button>
						</div>

						<!-- Gönderen + Tarih -->
						<div class="flex flex-wrap items-center gap-2 text-sm text-gray-500 mb-3">
							<span>Gönderen: <span class="font-medium text-gray-700">{req.requested_by_name}</span></span>
							<span class="text-gray-500">·</span>
							<span>{formatRelative(req.requested_at)}</span>
						</div>

						<!-- Eylem Butonları -->
						<div class="flex items-center gap-3 pt-3 border-t border-gray-100">
							<button
								onclick={() => openAction('approve', req)}
								class="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm bg-green-600 text-white hover:bg-green-700 active:scale-95 transition-all cursor-pointer"
							>
								<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
									<path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
								</svg>
								Onayla
							</button>
							<button
								onclick={() => openAction('reject', req)}
								class="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 active:scale-95 transition-all cursor-pointer"
							>
								<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
									<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
								</svg>
								Reddet
							</button>
							<button
								onclick={() => openAction('return', req)}
								class="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm bg-amber-50 text-amber-600 border border-amber-200 hover:bg-amber-100 active:scale-95 transition-all cursor-pointer"
							>
								<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
									<path stroke-linecap="round" stroke-linejoin="round" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
								</svg>
								İade Et
							</button>
						</div>
					</div>
				{/each}
			</div>

			<!-- Sayfalama -->
			{#if pendingPages > 1}
				<div class="flex items-center justify-center gap-2 mt-6">
					<button
						onclick={() => { pendingPage = Math.max(1, pendingPage - 1); loadPending(); }}
						disabled={pendingPage <= 1}
						class="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						Önceki
					</button>
					<span class="text-sm text-gray-500">{pendingPage} / {pendingPages}</span>
					<button
						onclick={() => { pendingPage = Math.min(pendingPages, pendingPage + 1); loadPending(); }}
						disabled={pendingPage >= pendingPages}
						class="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						Sonraki
					</button>
				</div>
			{/if}
		{/if}

	<!-- ═══════════════════ TAB 3: GÖNDERDİKLERİM ═══════════════════ -->
	{:else if activeTab === 'submissions'}
		{#if submissionsLoading}
			<div class="flex justify-center py-16">
				<div class="w-8 h-8 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin"></div>
			</div>
		{:else if mySubmissions.length === 0}
			<div class="flex flex-col items-center justify-center py-16 text-gray-500">
				<svg class="w-16 h-16 mb-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
				</svg>
				<p class="text-lg font-medium text-gray-500">Henüz talep göndermediniz</p>
				<p class="text-sm text-gray-500 mt-1">Gönderdiğiniz onay talepleri burada listelenir</p>
			</div>
		{:else}
			<!-- Mobil: Kart görünümü -->
			<div class="sm:hidden space-y-3">
				{#each mySubmissions as req (req.id)}
					{@const si = statusInfo(req.status)}
					<div class="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
						<div class="flex items-start justify-between gap-2 mb-2">
							<button onclick={() => openDetail(req)} class="text-left min-w-0 flex-1 cursor-pointer">
								<h3 class="text-sm font-bold text-gray-800 truncate">{req.entity_summary}</h3>
								<p class="text-xs text-gray-500 mt-0.5">{req.workflow_name}</p>
							</button>
							<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border shrink-0 {si.bg} {si.text} {si.border}">
								{si.label}
							</span>
						</div>
						<div class="flex items-center gap-2 text-xs text-gray-500 mb-2">
							<span>{formatRelative(req.requested_at)}</span>
						</div>
						{#if req.current_step_approver_name && req.status === 'pending'}
							<p class="text-xs text-gray-500 mb-2">Onaylayan: <span class="font-medium text-gray-700">{req.current_step_approver_name}</span></p>
						{/if}
						<div class="flex items-center gap-2 pt-2 border-t border-gray-100">
							{#if req.status === 'returned'}
								<button
									onclick={() => resubmitRequest(req)}
									disabled={resubmittingId === req.id}
									class="px-3 py-1.5 rounded-lg text-xs font-medium bg-teal-50 text-teal-700 border border-teal-200 hover:bg-teal-100 disabled:opacity-50 transition-colors cursor-pointer"
								>
									Yeniden Gönder
								</button>
							{/if}
							{#if req.status === 'pending' || req.status === 'returned'}
								<button
									onclick={() => cancelRequest(req)}
									disabled={cancellingId === req.id}
									class="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 disabled:opacity-50 transition-colors cursor-pointer"
								>
									İptal
								</button>
							{/if}
						</div>
					</div>
				{/each}
			</div>

			<!-- Masaüstü: Tablo görünümü -->
			<div class="hidden sm:block overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-200">
							<th class="pb-3 pr-4 font-medium">Varlık</th>
							<th class="pb-3 pr-4 font-medium">İş Akışı</th>
							<th class="pb-3 pr-4 font-medium">Durum</th>
							<th class="pb-3 pr-4 font-medium">Tarih</th>
							<th class="pb-3 font-medium text-right">İşlem</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-100">
						{#each mySubmissions as req (req.id)}
							{@const si = statusInfo(req.status)}
							<tr class="hover:bg-gray-50">
								<td class="py-3 pr-4">
									<button onclick={() => openDetail(req)} class="text-left cursor-pointer">
										<p class="font-medium text-gray-800 truncate max-w-xs">{req.entity_summary}</p>
									</button>
								</td>
								<td class="py-3 pr-4 text-gray-500">{req.workflow_name}</td>
								<td class="py-3 pr-4">
									<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border {si.bg} {si.text} {si.border}">
										{si.label}
									</span>
								</td>
								<td class="py-3 pr-4 text-gray-500">{formatRelative(req.requested_at)}</td>
								<td class="py-3 text-right">
									<div class="flex items-center justify-end gap-2">
										{#if req.status === 'returned'}
											<button
												onclick={() => resubmitRequest(req)}
												disabled={resubmittingId === req.id}
												class="px-3 py-1.5 rounded-lg text-xs font-medium bg-teal-50 text-teal-700 border border-teal-200 hover:bg-teal-100 disabled:opacity-50 transition-colors cursor-pointer"
											>
												Yeniden Gönder
											</button>
										{/if}
										{#if req.status === 'pending' || req.status === 'returned'}
											<button
												onclick={() => cancelRequest(req)}
												disabled={cancellingId === req.id}
												class="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 disabled:opacity-50 transition-colors cursor-pointer"
											>
												İptal
											</button>
										{/if}
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- Sayfalama -->
			{#if submissionsPages > 1}
				<div class="flex items-center justify-center gap-2 mt-6">
					<button
						onclick={() => { submissionsPage = Math.max(1, submissionsPage - 1); loadSubmissions(); }}
						disabled={submissionsPage <= 1}
						class="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						Önceki
					</button>
					<span class="text-sm text-gray-500">{submissionsPage} / {submissionsPages}</span>
					<button
						onclick={() => { submissionsPage = Math.min(submissionsPages, submissionsPage + 1); loadSubmissions(); }}
						disabled={submissionsPage >= submissionsPages}
						class="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						Sonraki
					</button>
				</div>
			{/if}
		{/if}

	<!-- ═══════════════════ TAB 4: GEÇMİŞ ═══════════════════ -->
	{:else if activeTab === 'history'}
		<!-- Filtreler -->
		<div class="flex items-center gap-3 mb-4">
			<select
				bind:value={historyStatusFilter}
				onchange={() => { historyPage = 1; loadHistory(); }}
				class="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white cursor-pointer focus:border-teal-500 focus:ring-1 focus:ring-teal-500 outline-none"
			>
				<option value="">Tüm durumlar</option>
				<option value="approved">Onaylanan</option>
				<option value="rejected">Reddedilen</option>
				<option value="cancelled">İptal edilen</option>
			</select>
		</div>

		{#if historyLoading}
			<div class="flex justify-center py-16">
				<div class="w-8 h-8 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin"></div>
			</div>
		{:else if historyRequests.length === 0}
			<div class="flex flex-col items-center justify-center py-16 text-gray-500">
				<svg class="w-16 h-16 mb-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
				</svg>
				<p class="text-lg font-medium text-gray-500">Geçmiş kayıt bulunamadı</p>
			</div>
		{:else}
			<!-- Tablo -->
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-200">
							<th class="pb-3 pr-4 font-medium">Varlık</th>
							<th class="pb-3 pr-4 font-medium">İş Akışı</th>
							<th class="pb-3 pr-4 font-medium">İşlem</th>
							<th class="pb-3 pr-4 font-medium">Durum</th>
							<th class="pb-3 pr-4 font-medium">Talep Eden</th>
							<th class="pb-3 pr-4 font-medium">Onaylayan</th>
							<th class="pb-3 font-medium">Tarih</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-100">
						{#each historyRequests as req (req.id)}
							{@const si = statusInfo(req.status)}
							<tr class="hover:bg-gray-50 cursor-pointer" onclick={() => openDetail(req)}>
								<td class="py-3 pr-4">
									<p class="font-medium text-gray-800 truncate max-w-xs">{req.entity_summary}</p>
								</td>
								<td class="py-3 pr-4 text-gray-500">{req.workflow_name}</td>
								<td class="py-3 pr-4">
									{#if req.action_type === 'create'}
										<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700">Oluşturma</span>
									{:else if req.action_type === 'update'}
										<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-amber-50 text-amber-700">Güncelleme</span>
									{:else if req.action_type === 'delete'}
										<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-50 text-red-700">Silme</span>
									{/if}
								</td>
								<td class="py-3 pr-4">
									<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border {si.bg} {si.text} {si.border}">
										{si.label}
									</span>
								</td>
								<td class="py-3 pr-4 text-gray-500">{req.requested_by_name}</td>
								<td class="py-3 pr-4 text-gray-500">{req.completed_by_name ?? '—'}</td>
								<td class="py-3 text-gray-500">{formatRelative(req.completed_at ?? req.requested_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- Sayfalama -->
			{#if historyPages > 1}
				<div class="flex items-center justify-center gap-2 mt-6">
					<button
						onclick={() => { historyPage = Math.max(1, historyPage - 1); loadHistory(); }}
						disabled={historyPage <= 1}
						class="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						Önceki
					</button>
					<span class="text-sm text-gray-500">{historyPage} / {historyPages}</span>
					<button
						onclick={() => { historyPage = Math.min(historyPages, historyPage + 1); loadHistory(); }}
						disabled={historyPage >= historyPages}
						class="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						Sonraki
					</button>
				</div>
			{/if}
		{/if}
	{/if}
</div>

<!-- ═══════════════════ MODALLER ═══════════════════ -->

<!-- Onay Tanımı Oluştur/Düzenle Modal -->
<Modal bind:show={showWorkflowModal} title={editingWorkflow ? 'Onay Tanımını Düzenle' : 'Yeni Onay Tanımı'} maxWidth="max-w-2xl">
	<div class="space-y-5">
		<!-- Onay Adı -->
		<div>
			<label for="wf-name" class="block text-sm font-medium text-gray-700 mb-1">Onay Adı <span class="text-red-600">*</span></label>
			<input
				id="wf-name"
				type="text"
				bind:value={wfName}
				class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 outline-none"
				placeholder="Örn: Cari ödeme onayı"
			/>
		</div>

		<!-- Modül Seçimi -->
		<div>
			<label for="wf-module" class="block text-sm font-medium text-gray-700 mb-1">Modül <span class="text-red-600">*</span></label>
			<select
				id="wf-module"
				bind:value={wfModuleId}
				onchange={() => { wfRequestorRoleIds = []; wfApproverRoleIds = []; }}
				class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 outline-none bg-white cursor-pointer"
			>
				<option value={null}>Modül seçin...</option>
				{#each groupedModules as group}
					<optgroup label={group.parentName}>
						{#if group.parent && group.parent.roles.length > 0}
							<option value={group.parent.id}>{group.parent.name}</option>
						{/if}
						{#each group.children as child}
							<option value={child.id}>{child.name}</option>
						{/each}
					</optgroup>
				{/each}
			</select>
		</div>

		<!-- Talep Eden Roller -->
		{#if wfModuleId && availableRoles.length > 0}
			<div>
				<span class="block text-sm font-medium text-gray-700 mb-2">
					Talep Eden Roller <span class="text-red-600">*</span>
					<span class="text-xs text-gray-500 font-normal ml-1">(Bu rollerdeki kullanıcıların işlemleri onaya tabi olacak)</span>
				</span>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
					{#each availableRoles as role}
						<label class="flex items-center gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors
							{wfRequestorRoleIds.includes(role.id)
								? 'border-blue-300 bg-blue-50'
								: 'border-gray-200 bg-white hover:bg-gray-50'}">
							<input
								type="checkbox"
								checked={wfRequestorRoleIds.includes(role.id)}
								onchange={() => { wfRequestorRoleIds = toggleRoleId(wfRequestorRoleIds, role.id); }}
								class="rounded text-blue-600 focus:ring-blue-500 cursor-pointer"
							/>
							<span class="text-sm text-gray-700 font-medium">{role.name}</span>
						</label>
					{/each}
				</div>
			</div>

			<!-- Onay Veren Roller -->
			<div>
				<span class="block text-sm font-medium text-gray-700 mb-2">
					Onay Veren Roller <span class="text-red-600">*</span>
					<span class="text-xs text-gray-500 font-normal ml-1">(Bu rollerdeki kullanıcılar onay/red verebilir)</span>
				</span>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
					{#each availableRoles as role}
						<label class="flex items-center gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors
							{wfApproverRoleIds.includes(role.id)
								? 'border-emerald-300 bg-emerald-50'
								: 'border-gray-200 bg-white hover:bg-gray-50'}">
							<input
								type="checkbox"
								checked={wfApproverRoleIds.includes(role.id)}
								onchange={() => { wfApproverRoleIds = toggleRoleId(wfApproverRoleIds, role.id); }}
								class="rounded text-emerald-600 focus:ring-emerald-500 cursor-pointer"
							/>
							<span class="text-sm text-gray-700 font-medium">{role.name}</span>
						</label>
					{/each}
				</div>
			</div>
		{:else if wfModuleId && availableRoles.length === 0}
			<div class="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-700">
				Bu modüle kullanım yetkisi olan rol bulunamadı. Önce roller sayfasından ilgili izinleri tanımlayın.
			</div>
		{/if}

		<!-- Açıklama -->
		<div>
			<label for="wf-desc" class="block text-sm font-medium text-gray-700 mb-1">Açıklama</label>
			<textarea
				id="wf-desc"
				bind:value={wfDescription}
				rows="2"
				class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 outline-none resize-none"
				placeholder="Onay tanımı hakkında kısa açıklama..."
			></textarea>
		</div>

		<!-- Koşullar JSON -->
		<div>
			<label for="wf-conditions" class="block text-sm font-medium text-gray-700 mb-1">Koşullar (JSON, opsiyonel)</label>
			<textarea
				id="wf-conditions"
				bind:value={wfConditions}
				rows="2"
				class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-teal-500 focus:ring-1 focus:ring-teal-500 outline-none resize-none"
				placeholder={`{"min_amount": 10000}`}
			></textarea>
		</div>

		<!-- Butonlar -->
		<div class="flex items-center justify-end gap-3 pt-2">
			<Button variant="secondary" onclick={() => { showWorkflowModal = false; }}>İptal</Button>
			<Button onclick={saveWorkflow} loading={wfSaving}>{editingWorkflow ? 'Güncelle' : 'Oluştur'}</Button>
		</div>
	</div>
</Modal>

<!-- Silme Onay Modal -->
<Modal bind:show={showDeleteConfirm} title="Onay Tanımını Sil" maxWidth="max-w-md">
	{#if deletingWorkflow}
		<div class="space-y-4">
			<p class="text-sm text-gray-600">
				<span class="font-semibold text-gray-800">"{deletingWorkflow.name}"</span> onay tanımını silmek istediğinize emin misiniz? Bu işlem geri alınamaz.
			</p>
			<div class="flex items-center justify-end gap-3 pt-2">
				<button
					onclick={() => { showDeleteConfirm = false; deletingWorkflow = null; }}
					class="px-4 py-2.5 rounded-lg font-medium text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors cursor-pointer"
				>
					Vazgeç
				</button>
				<button
					onclick={deleteWorkflow}
					disabled={deleting}
					class="px-4 py-2.5 rounded-lg font-medium text-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
				>
					{#if deleting}
						<span class="inline-flex items-center gap-2">
							<span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
							Siliniyor...
						</span>
					{:else}
						Sil
					{/if}
				</button>
			</div>
		</div>
	{/if}
</Modal>

<!-- Onay/Red/İade Modal -->
<Modal bind:show={showActionModal} title={actionTitle()} maxWidth="max-w-md">
	{#if actionRequest}
		<div class="space-y-4">
			<div class="bg-gray-50 rounded-lg p-3 text-sm">
				<p class="font-medium text-gray-800">{actionRequest.entity_summary}</p>
				<p class="text-gray-500 mt-1">{actionRequest.workflow_name}</p>
			</div>
			<div>
				<label for="action-note" class="block text-sm font-medium text-gray-700 mb-1">
					{#if actionType === 'approve'}
						Not (opsiyonel)
					{:else if actionType === 'reject'}
						Red gerekçesi (zorunlu)
					{:else}
						İade gerekçesi (zorunlu)
					{/if}
				</label>
				<textarea
					id="action-note"
					bind:value={actionNote}
					rows="3"
					class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none resize-none
						{actionType === 'approve' ? 'focus:border-green-500 focus:ring-1 focus:ring-green-500' : ''}
						{actionType === 'reject' ? 'focus:border-red-500 focus:ring-1 focus:ring-red-500' : ''}
						{actionType === 'return' ? 'focus:border-amber-500 focus:ring-1 focus:ring-amber-500' : ''}"
					placeholder="{actionType === 'approve' ? 'Onay notu ekleyin...' : actionType === 'reject' ? 'Red gerekçesini yazın...' : 'İade gerekçesini yazın...'}"
				></textarea>
				{#if (actionType === 'reject' || actionType === 'return') && actionNote !== '' && !actionNote.trim()}
					<p class="text-xs text-red-600 mt-1">Gerekçe boş bırakılamaz</p>
				{/if}
			</div>
			<div class="flex items-center justify-end gap-3 pt-2">
				<button
					onclick={() => { showActionModal = false; actionRequest = null; }}
					class="px-4 py-2.5 rounded-lg font-medium text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors cursor-pointer"
				>
					Vazgeç
				</button>
				<button
					onclick={executeAction}
					disabled={actionProcessing || ((actionType === 'reject' || actionType === 'return') && !actionNote.trim())}
					class="px-4 py-2.5 rounded-lg font-medium text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer
						{actionType === 'approve' ? 'bg-green-600 hover:bg-green-700' : ''}
						{actionType === 'reject' ? 'bg-red-600 hover:bg-red-700' : ''}
						{actionType === 'return' ? 'bg-amber-600 hover:bg-amber-700' : ''}"
				>
					{#if actionProcessing}
						<span class="inline-flex items-center gap-2">
							<span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
							İşleniyor...
						</span>
					{:else}
						{actionTitle()}
					{/if}
				</button>
			</div>
		</div>
	{/if}
</Modal>

<!-- Detay Modal -->
<Modal bind:show={showDetailModal} title="Talep Detayı" maxWidth="max-w-lg">
	{#if detailRequest}
		{@const si = statusInfo(detailRequest.status)}
		<div class="space-y-4">
			<!-- Özet -->
			<div class="bg-gray-50 rounded-lg p-4">
				<div class="flex items-start justify-between gap-2 mb-2">
					<h3 class="text-base font-bold text-gray-800">{detailRequest.entity_summary}</h3>
					<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border shrink-0 {si.bg} {si.text} {si.border}">
						{si.label}
					</span>
				</div>
				<div class="grid grid-cols-2 gap-2 text-sm">
					{#if detailRequest.action_type}
						<div>
							<span class="text-gray-500">İşlem:</span>
							<span class="font-medium text-gray-700 ml-1">{ACTION_TYPE_LABELS[detailRequest.action_type] ?? detailRequest.action_type}</span>
						</div>
					{/if}
					<div>
						<span class="text-gray-500">İş Akışı:</span>
						<span class="font-medium text-gray-700 ml-1">{detailRequest.workflow_name}</span>
					</div>
					<div>
						<span class="text-gray-500">Gönderen:</span>
						<span class="font-medium text-gray-700 ml-1">{detailRequest.requested_by_name}</span>
					</div>
					<div>
						<span class="text-gray-500">Tarih:</span>
						<span class="font-medium text-gray-700 ml-1">{formatDateTime(detailRequest.requested_at)}</span>
					</div>
					{#if detailRequest.current_step_approver_name && detailRequest.status === 'pending'}
						<div>
							<span class="text-gray-500">Onaylayan:</span>
							<span class="font-medium text-gray-700 ml-1">{detailRequest.current_step_approver_name}</span>
						</div>
					{/if}
					{#if detailRequest.completed_at}
						<div>
							<span class="text-gray-500">Tamamlanma:</span>
							<span class="font-medium text-gray-700 ml-1">{formatDateTime(detailRequest.completed_at)}</span>
						</div>
					{/if}
					{#if detailRequest.completed_by_name}
						<div>
							<span class="text-gray-500">Tamamlayan:</span>
							<span class="font-medium text-gray-700 ml-1">{detailRequest.completed_by_name}</span>
						</div>
					{/if}
				</div>
			</div>

			<!-- Değişiklik Detayları -->
			{#if detailRequest.payload_json}
				{@const payload = parsePayload(detailRequest.payload_json)}
				{#if payload && Object.keys(payload).filter(k => k !== '_target').length > 0}
					<div>
						<h4 class="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
							<svg class="w-4 h-4 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15a2.25 2.25 0 012.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25z" /></svg>
							{detailRequest.action_type === 'delete' ? 'Silme Talebi' : 'İstenen Değişiklikler'}
						</h4>
						<div class="bg-orange-50/50 border border-orange-200 rounded-lg overflow-hidden">
							<table class="w-full text-sm">
								<thead>
									<tr class="border-b border-orange-200 bg-orange-50">
										<th class="text-left px-3 py-2 font-medium text-orange-800 text-xs">Alan</th>
										<th class="text-left px-3 py-2 font-medium text-orange-800 text-xs">Değer</th>
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
				{/if}
			{:else if detailRequest.action_type === 'delete'}
				<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center gap-2">
					<svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" /></svg>
					Bu kayıt silinmek üzere onay bekliyor.
				</div>
			{/if}

			<!-- İşlem Geçmişi -->
			{#if detailRequest.logs && detailRequest.logs.length > 0}
				<div>
					<h4 class="text-sm font-medium text-gray-700 mb-2">İşlem Geçmişi</h4>
					<div class="space-y-2">
						{#each detailRequest.logs as log}
							{@const logStatus = log.action === 'approve' ? 'approved' : log.action === 'reject' ? 'rejected' : log.action === 'return' ? 'returned' : log.action === 'cancel' ? 'cancelled' : 'pending'}
							{@const logSi = statusInfo(logStatus)}
							<div class="flex items-start gap-3 text-sm bg-gray-50 rounded-lg p-2.5">
								<div class="shrink-0 mt-0.5">
									<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border {logSi.bg} {logSi.text} {logSi.border}">
										{logSi.label}
									</span>
								</div>
								<div class="min-w-0 flex-1">
									<p class="text-gray-800">
										<span class="font-medium">{log.actor_name}</span>
										<span class="text-gray-500 ml-1">
											{#if log.action === 'approve'}onayladı{:else if log.action === 'reject'}reddetti{:else if log.action === 'return'}iade etti{:else if log.action === 'cancel'}iptal etti{:else if log.action === 'submit'}gönderdi{:else if log.action === 'resubmit'}yeniden gönderdi{:else}{log.action}{/if}
										</span>
									</p>
									{#if log.note}
										<p class="text-gray-500 text-xs mt-0.5 italic">"{log.note}"</p>
									{/if}
									<p class="text-gray-500 text-xs mt-0.5">{formatDateTime(log.created_at)}</p>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Kapat -->
			<div class="flex justify-end pt-2">
				<button
					onclick={() => { showDetailModal = false; detailRequest = null; }}
					class="px-4 py-2.5 rounded-lg font-medium text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors cursor-pointer"
				>
					Kapat
				</button>
			</div>
		</div>
	{/if}
</Modal>
