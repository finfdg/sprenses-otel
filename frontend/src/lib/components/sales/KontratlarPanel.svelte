<!--
	KontratlarPanel.svelte — Kontratlar sekmesi (Acente Mahsup & Nakit Akım birleşik sayfası).

	16 tur operatörünün kontrat arşivi: sezon/dönem, ödeme planı + taksitler, aksiyon/SPO,
	kontenjan, kesinti ve belge arşivi. İzin kodu: sales.kontratlar (view/use);
	mutasyonlar onay akışından geçer (202 → onay kuyruğu). Veri girişi hem elle CRUD
	hem belge yükleme iledir (kullanıcı kararı 2026-07-17).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import {
		AlertTriangle, CalendarClock, CheckCircle2, ChevronDown, ChevronRight,
		Download, FileText, Pencil, Plus, ScrollText, Trash2, Upload, Wallet,
	} from 'lucide-svelte';

	import { api, ApiError } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import Input from '$lib/components/Input.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import Select from '$lib/components/Select.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { useLiveRefetch } from '$lib/utils/liveRefetch.svelte';
	import { BROADCAST_MODULE } from '$lib/constants/realtime';

	// ───── Sabitler ─────────────────────────────────────
	const CONFIDENCE_META: Record<string, { label: string; type: 'success' | 'warning' | 'error' }> = {
		verified: { label: 'Doğrulanmış', type: 'success' },
		scanned_approx: { label: 'Taranmış — yaklaşık', type: 'warning' },
		needs_confirmation: { label: 'Teyit bekliyor', type: 'error' },
	};
	const STATUS_META: Record<string, { label: string; type: 'success' | 'neutral' | 'warning' }> = {
		active: { label: 'Aktif', type: 'success' },
		draft: { label: 'Taslak', type: 'neutral' },
		superseded: { label: 'Revize edildi', type: 'warning' },
	};
	const INST_STATUS_META: Record<string, { label: string; type: 'success' | 'warning' | 'neutral' | 'error' }> = {
		pending: { label: 'Bekliyor', type: 'warning' },
		paid: { label: 'Ödendi', type: 'success' },
		cancelled: { label: 'İptal', type: 'neutral' },
		superseded: { label: 'Revize', type: 'neutral' },
	};
	const PLAN_TYPE_LABELS: Record<string, string> = {
		advance: 'Avans (sabit takvim)',
		eb_prepayment: 'EB ön ödemesi',
		guarantee_check: 'Çek / teminat',
		invoice_terms: 'Fatura vadesi',
	};
	const ACTION_TYPE_LABELS: Record<string, string> = {
		early_booking: 'Erken Rezervasyon (EB)',
		spo: 'SPO / İndirim',
		long_stay: 'Uzun konaklama',
		release_revision: 'Release revizyonu',
		child_policy_revision: 'Çocuk yaşı revizyonu',
		closeout: 'Satışa kapama',
		price_update: 'Fiyat güncellemesi',
		other: 'Diğer',
	};
	const DOC_TYPE_LABELS: Record<string, string> = {
		contract: 'Kontrat', annex: 'Ek / Addendum', protocol: 'Protokol',
		ratelist: 'Fiyat listesi', spo: 'SPO bildirimi', email: 'E-posta', other: 'Diğer',
	};
	const EMPTY_FORM = {
		agency_group_id: 0, code: '', title: '', season_code: 'S26',
		legal_counterparty: '', valid_from: '', valid_to: '', currency: 'EUR',
		pricing_model: '', invoice_due_basis: '', invoice_due_days: null as number | null,
		release_days_default: null as number | null, min_stay_default: null as number | null,
		data_confidence: 'verified', status: 'active', notes: '',
	};

	// ───── Türetilmiş ───────────────────────────────────
	const canUse = $derived(hasPermission('sales.kontratlar', 'use'));

	// ───── State ────────────────────────────────────────
	let loading = $state(true);
	let contracts = $state<any[]>([]);
	let summary = $state<any>(null);
	let groups = $state<{ id: number; name: string }[]>([]);
	let seasonFilter = $state('');
	let groupFilter = $state('');
	let statusFilter = $state('');
	let expandedId = $state<number | null>(null);
	let detail = $state<any>(null);
	let detailLoading = $state(false);

	// Form state
	let showContractModal = $state(false);
	let editingId = $state<number | null>(null);
	let form = $state({ ...EMPTY_FORM });
	let fieldErrors = $state<Record<string, string>>({});
	let saving = $state(false);
	let confirmDelete = $state<{ show: boolean; kind: 'contract' | 'document'; id: number; label: string }>(
		{ show: false, kind: 'contract', id: 0, label: '' });
	let showActionModal = $state(false);
	let actionForm = $state({
		action_type: 'spo', title: '', sales_start: '', sales_end: '', basis: 'booking',
		combinable: '', stay_start: '', stay_end: '', discount_percent: null as number | null,
		notes: '',
	});
	let showInstallmentModal = $state(false);
	let instForm = $state({
		plan_id: 0, due_date: '', amount: null as number | null, currency: 'EUR',
		is_conditional: false, condition_note: '', notes: '',
	});
	let showCalendar = $state(false);
	let showDeductions = $state(false);
	let deductions = $state<any[]>([]);
	let deductionsLoading = $state(false);
	let showAllotments = $state(false);
	let showAudit = $state(false);
	let audit = $state<any>(null);
	let auditLoading = $state(false);
	let allotments = $state<any[]>([]);
	let allotmentsLoading = $state(false);
	let calendarItems = $state<any[]>([]);
	let calendarLoading = $state(false);
	let showUploadModal = $state(false);
	let uploadMeta = $state({ doc_type: 'contract', doc_date: '', notes: '' });
	let uploadFile = $state<File | null>(null);
	let uploading = $state(false);

	// ───── Formatlama ───────────────────────────────────
	function fmtMoney(n: number | null | undefined, cur = 'EUR'): string {
		if (n == null) return '—';
		return new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(n) + ' ' + cur;
	}
	function fmtDate(s: string | null): string {
		if (!s) return '—';
		const [y, m, d] = s.split('-');
		return `${d}.${m}.${y}`;
	}
	function dueLabel(c: any): string {
		if (!c.invoice_due_basis) return '—';
		const basis: Record<string, string> = {
			checkout: 'Çıkış', invoice_date: 'Fatura', invoice_receipt: 'Fatura tebliği',
			self_billing: 'Self-billing', before_checkin: 'Girişten önce',
			first_friday_after_checkin: 'Girişten sonraki ilk Cuma',
		};
		const b = basis[c.invoice_due_basis] ?? c.invoice_due_basis;
		return c.invoice_due_days != null ? `${b} +${c.invoice_due_days}g` : b;
	}

	// ───── Veri ─────────────────────────────────────────
	async function loadAll() {
		loading = true;
		try {
			const params = new URLSearchParams({ page: '1', page_size: '200' });
			if (groupFilter) params.set('group_id', groupFilter);
			if (seasonFilter) params.set('season', seasonFilter);
			if (statusFilter) params.set('status', statusFilter);
			const [list, sum] = await Promise.all([
				api.get<any>(`/sales/kontratlar/?${params}`),
				api.get<any>('/sales/kontratlar/summary'),
			]);
			contracts = list.items;
			summary = sum;
		} catch (e) {
			console.error('Kontrat listesi yüklenemedi:', e);
			showToast('Kontratlar yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	async function toggleCalendar() {
		showCalendar = !showCalendar;
		if (!showCalendar || calendarItems.length) return;
		calendarLoading = true;
		try {
			const start = new Date();
			const end = new Date(Date.now() + 90 * 86400000);
			const iso = (d: Date) => d.toISOString().slice(0, 10);
			const res: any = await api.get(
				`/sales/kontratlar/actions-calendar?start=${iso(start)}&end=${iso(end)}`);
			// Takvimde yalnız tarih-bantlı aksiyonlar çizilir (kontrat-geneli olanlar listede zaten)
			calendarItems = res.items.filter((a: any) => a.sales_start || a.tiers?.some((t: any) => t.stay_start));
		} catch (e) {
			console.error('Aksiyon takvimi yüklenemedi:', e);
			showToast('Aksiyon takvimi yüklenemedi', 'error');
		} finally {
			calendarLoading = false;
		}
	}

	// Bant konumu: bugün..+90g penceresinde yüzde (CSS left/width)
	function bandPos(startS: string | null, endS: string | null): { left: number; width: number } | null {
		const w0 = Date.now();
		const w1 = w0 + 90 * 86400000;
		const s0 = startS ? new Date(startS + 'T00:00:00').getTime() : w0;
		const s1 = endS ? new Date(endS + 'T23:59:59').getTime() : w1;
		if (s1 < w0 || s0 > w1) return null;
		const left = Math.max(0, ((s0 - w0) / (w1 - w0)) * 100);
		const right = Math.min(100, ((s1 - w0) / (w1 - w0)) * 100);
		return { left, width: Math.max(1.5, right - left) };
	}

	async function toggleDeductions() {
		showDeductions = !showDeductions;
		if (!showDeductions || deductions.length) return;
		deductionsLoading = true;
		try {
			const res: any = await api.get(
				`/sales/kontratlar/deductions-forecast?year=${new Date().getFullYear()}`);
			deductions = res.items;
		} catch (e) {
			console.error('Kesinti tahmini yüklenemedi:', e);
			showToast('Kesinti tahmini yüklenemedi', 'error');
		} finally {
			deductionsLoading = false;
		}
	}

	async function toggleAllotments() {
		showAllotments = !showAllotments;
		if (!showAllotments || allotments.length) return;
		allotmentsLoading = true;
		try {
			const iso = (d: Date) => d.toISOString().slice(0, 10);
			const start = new Date();
			const end = new Date(Date.now() + 60 * 86400000);
			const res: any = await api.get(
				`/sales/kontratlar/allotment-usage?start=${iso(start)}&end=${iso(end)}`);
			allotments = res.items;
		} catch (e) {
			console.error('Kontenjan kullanımı yüklenemedi:', e);
			showToast('Kontenjan kullanımı yüklenemedi', 'error');
		} finally {
			allotmentsLoading = false;
		}
	}

	async function toggleAudit() {
		showAudit = !showAudit;
		if (!showAudit || audit) return;
		auditLoading = true;
		try {
			const iso = (d: Date) => d.toISOString().slice(0, 10);
			const start = new Date(Date.now() - 60 * 86400000);
			const end = new Date(Date.now() + 120 * 86400000);
			audit = await api.get(
				`/sales/kontratlar/price-audit?start=${iso(start)}&end=${iso(end)}`);
		} catch (e) {
			console.error('Fiyat denetimi yüklenemedi:', e);
			showToast('Fiyat denetimi yüklenemedi', 'error');
		} finally {
			auditLoading = false;
		}
	}

	const AUDIT_TYPE_LABELS: Record<string, string> = {
		currency_mismatch: 'Para birimi uyumsuz',
		period_gap: 'Dönem boşluğu',
		min_stay_violation: 'Min. konaklama ihlali',
		price_deviation: 'Fiyat sapması',
	};

	async function loadGroups() {
		try {
			const res: any = await api.get('/sales/agency-groups/');
			groups = (res.items ?? res).map((g: any) => ({ id: g.id, name: g.name }));
		} catch (e) {
			console.error('Acente grupları yüklenemedi:', e);
			showToast('Acente grupları yüklenemedi', 'error');
		}
	}

	async function toggleExpand(id: number) {
		if (expandedId === id) { expandedId = null; detail = null; return; }
		expandedId = id;
		detailLoading = true;
		try {
			detail = await api.get<any>(`/sales/kontratlar/${id}`);
		} catch (e) {
			console.error('Kontrat detayı yüklenemedi:', e);
			showToast('Kontrat detayı yüklenemedi', 'error');
			expandedId = null;
		} finally {
			detailLoading = false;
		}
	}

	async function refreshDetail() {
		if (expandedId != null) {
			try {
				detail = await api.get<any>(`/sales/kontratlar/${expandedId}`);
			} catch (e) {
				console.error('Detay tazelenemedi:', e);
			}
		}
	}

	// ───── CRUD ─────────────────────────────────────────
	function openAdd() {
		editingId = null;
		form = { ...EMPTY_FORM, agency_group_id: groups[0]?.id ?? 0 };
		fieldErrors = {};
		showContractModal = true;
	}
	function openEdit(c: any) {
		editingId = c.id;
		form = {
			agency_group_id: c.agency_group_id, code: c.code, title: c.title ?? '',
			season_code: c.season_code, legal_counterparty: c.legal_counterparty ?? '',
			valid_from: c.valid_from ?? '', valid_to: c.valid_to ?? '',
			currency: c.currency, pricing_model: c.pricing_model ?? '',
			invoice_due_basis: c.invoice_due_basis ?? '',
			invoice_due_days: c.invoice_due_days,
			release_days_default: c.release_days_default,
			min_stay_default: c.min_stay_default ?? null,
			data_confidence: c.data_confidence, status: c.status, notes: c.notes ?? '',
		};
		fieldErrors = {};
		showContractModal = true;
	}

	function validateForm(): boolean {
		const errs: Record<string, string> = {};
		if (!form.agency_group_id) errs.agency_group_id = 'Acente grubu seçin';
		if (!form.code.trim()) errs.code = 'Kontrat kodu zorunlu';
		if (!form.season_code.trim()) errs.season_code = 'Sezon zorunlu';
		fieldErrors = errs;
		return Object.keys(errs).length === 0;
	}

	async function handleSave() {
		if (!validateForm()) return;
		saving = true;
		try {
			const payload: any = {
				...form,
				title: form.title || null,
				legal_counterparty: form.legal_counterparty || null,
				valid_from: form.valid_from || null,
				valid_to: form.valid_to || null,
				pricing_model: form.pricing_model || null,
				invoice_due_basis: form.invoice_due_basis || null,
				notes: form.notes || null,
			};
			if (editingId != null) {
				const res: any = await api.patch(`/sales/kontratlar/${editingId}`, payload);
				notifyOutcome(res, 'Kontrat güncellendi');
			} else {
				const res: any = await api.post('/sales/kontratlar/', payload);
				notifyOutcome(res, 'Kontrat oluşturuldu');
			}
			showContractModal = false;
			await loadAll();
			await refreshDetail();
		} catch (e) {
			console.error('Kontrat kaydedilemedi:', e);
			showToast(e instanceof ApiError ? e.message : 'Kontrat kaydedilemedi', 'error');
		} finally {
			saving = false;
		}
	}

	function notifyOutcome(res: any, okMsg: string) {
		if (res?.request_id) {
			showToast('İşlem onay kuyruğuna gönderildi', 'info');
		} else {
			showToast(okMsg, 'success');
		}
	}

	async function handleDelete() {
		const { kind, id } = confirmDelete;
		try {
			if (kind === 'contract') {
				await api.delete(`/sales/kontratlar/${id}`);
				if (expandedId === id) { expandedId = null; detail = null; }
				showToast('Kontrat silindi', 'success');
			} else {
				await api.delete(`/sales/kontratlar/documents/${id}`);
				showToast('Belge silindi', 'success');
			}
			confirmDelete = { ...confirmDelete, show: false };
			await loadAll();
			await refreshDetail();
		} catch (e) {
			console.error('Silme başarısız:', e);
			showToast(e instanceof ApiError ? e.message : 'Silme başarısız', 'error');
		}
	}

	function openAddAction() {
		actionForm = {
			action_type: 'spo', title: '', sales_start: '', sales_end: '', basis: 'booking',
			combinable: '', stay_start: '', stay_end: '', discount_percent: null, notes: '',
		};
		showActionModal = true;
	}

	async function handleSaveAction() {
		if (!detail) return;
		saving = true;
		try {
			const res: any = await api.post(`/sales/kontratlar/${detail.id}/children/actions`, {
				action_type: actionForm.action_type,
				title: actionForm.title || null,
				sales_start: actionForm.sales_start || null,
				sales_end: actionForm.sales_end || null,
				basis: actionForm.basis || null,
				combinable: actionForm.combinable || null,
				notes: actionForm.notes || null,
			});
			// Band (tier) — indirim yüzdesi verildiyse aksiyona bağla (onaysız yol: res.id döner)
			if (res?.id && (actionForm.discount_percent != null || actionForm.stay_start)) {
				await api.post(`/sales/kontratlar/${detail.id}/children/tiers`, {
					action_id: res.id,
					stay_start: actionForm.stay_start || null,
					stay_end: actionForm.stay_end || null,
					discount_percent: actionForm.discount_percent,
				});
			}
			notifyOutcome(res, 'Aksiyon eklendi');
			showActionModal = false;
			await refreshDetail();
			await loadAll();
		} catch (e) {
			console.error('Aksiyon kaydedilemedi:', e);
			showToast(e instanceof ApiError ? e.message : 'Aksiyon kaydedilemedi', 'error');
		} finally {
			saving = false;
		}
	}

	function openAddInstallment(planId: number) {
		instForm = {
			plan_id: planId, due_date: '', amount: null, currency: 'EUR',
			is_conditional: false, condition_note: '', notes: '',
		};
		showInstallmentModal = true;
	}

	async function handleSaveInstallment() {
		if (!detail) return;
		if (!instForm.due_date || instForm.amount == null) {
			showToast('Vade tarihi ve tutar zorunlu', 'error');
			return;
		}
		saving = true;
		try {
			const res: any = await api.post(
				`/sales/kontratlar/${detail.id}/children/installments`, {
					plan_id: instForm.plan_id,
					due_date: instForm.due_date,
					amount: instForm.amount,
					currency: instForm.currency,
					is_conditional: instForm.is_conditional,
					condition_note: instForm.condition_note || null,
					notes: instForm.notes || null,
				});
			notifyOutcome(res, 'Taksit eklendi');
			showInstallmentModal = false;
			await refreshDetail();
			await loadAll();
		} catch (e) {
			console.error('Taksit kaydedilemedi:', e);
			showToast(e instanceof ApiError ? e.message : 'Taksit kaydedilemedi', 'error');
		} finally {
			saving = false;
		}
	}

	async function setInstallmentStatus(inst: any, status: 'paid' | 'cancelled' | 'pending') {
		try {
			const body: any = { status };
			if (status === 'paid') body.paid_date = new Date().toISOString().slice(0, 10);
			const res: any = await api.patch(`/sales/kontratlar/children/installments/${inst.id}`, body);
			notifyOutcome(res, status === 'paid' ? 'Taksit ödendi işaretlendi' : 'Taksit güncellendi');
			await refreshDetail();
			await loadAll();
		} catch (e) {
			console.error('Taksit güncellenemedi:', e);
			showToast(e instanceof ApiError ? e.message : 'Taksit güncellenemedi', 'error');
		}
	}

	function openUpload() {
		uploadMeta = { doc_type: 'contract', doc_date: '', notes: '' };
		uploadFile = null;
		showUploadModal = true;
	}

	async function handleUpload() {
		if (!detail || !uploadFile) {
			showToast('Dosya seçin', 'error');
			return;
		}
		uploading = true;
		try {
			const fd = new FormData();
			fd.append('file', uploadFile);
			fd.append('agency_group_id', String(detail.agency_group_id));
			fd.append('contract_id', String(detail.id));
			fd.append('doc_type', uploadMeta.doc_type);
			if (uploadMeta.doc_date) fd.append('doc_date', uploadMeta.doc_date);
			if (uploadMeta.notes) fd.append('notes', uploadMeta.notes);
			await api.upload('/sales/kontratlar/documents', fd);
			showToast('Belge yüklendi', 'success');
			showUploadModal = false;
			await refreshDetail();
			await loadAll();
		} catch (e) {
			console.error('Belge yüklenemedi:', e);
			showToast(e instanceof ApiError ? e.message : 'Belge yüklenemedi', 'error');
		} finally {
			uploading = false;
		}
	}

	// ───── Lifecycle ────────────────────────────────────
	onMount(() => {
		loadAll();
		loadGroups();
	});
	useLiveRefetch({
		salesModules: [BROADCAST_MODULE.KONTRATLAR],
		reload: () => {
			loadAll();
			refreshDetail();
		},
	});
</script>

<!-- Özet kartları -->
{#if summary}
	<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
		<StatCard icon={ScrollText} label="Aktif Kontrat" value={String(summary.active_contracts)} />
		<StatCard icon={Wallet} label="Bekleyen Taksit"
			value={fmtMoney(summary.pending_installment_total)}
			hint={summary.conditional_pending ? `${fmtMoney(summary.conditional_pending)} koşullu` : ''} />
		<StatCard icon={CalendarClock} label="30 Gün İçinde Vade"
			value={fmtMoney(summary.due_next_30d)} />
		<StatCard icon={AlertTriangle} label="Vadesi Geçen"
			value={fmtMoney(summary.overdue_total)}
			hint={summary.overdue_count ? `${summary.overdue_count} taksit` : ''} />
	</div>
{/if}

<!-- Filtre barı -->
<div class="flex flex-wrap items-center gap-2 mb-4">
	<Select size="sm" fullWidth={false} bind:value={groupFilter} onchange={loadAll}>
		<option value="">Tüm Gruplar</option>
		{#each groups as g}<option value={String(g.id)}>{g.name}</option>{/each}
	</Select>
	<Select size="sm" fullWidth={false} bind:value={seasonFilter} onchange={loadAll}>
		<option value="">Tüm Sezonlar</option>
		<option value="S26">S26</option>
		<option value="W26-27">W26-27</option>
		<option value="S25">S25</option>
		<option value="YEARLY">Yıllık</option>
	</Select>
	<Select size="sm" fullWidth={false} bind:value={statusFilter} onchange={loadAll}>
		<option value="">Tüm Durumlar</option>
		<option value="active">Aktif</option>
		<option value="draft">Taslak</option>
		<option value="superseded">Revize edildi</option>
	</Select>
	<div class="ml-auto flex items-center gap-2">
		<span class="text-sm text-gray-500">{contracts.length} kontrat</span>
		{#if canUse}
			<Button size="sm" onclick={openAdd}><Plus class="w-4 h-4" /> Yeni Kontrat</Button>
		{/if}
	</div>
</div>

<!-- Aksiyon takvimi (90 gün) + Faz 3 araçları -->
<div class="mb-4 flex flex-wrap gap-x-5 gap-y-1">
	<button class="text-sm text-teal-700 hover:underline inline-flex items-center gap-1 cursor-pointer"
		onclick={toggleCalendar}>
		<CalendarClock class="w-4 h-4" />
		{showCalendar ? 'Aksiyon takvimini gizle' : 'Aksiyon takvimi (90 gün)'}
	</button>
	<button class="text-sm text-teal-700 hover:underline inline-flex items-center gap-1 cursor-pointer"
		onclick={toggleDeductions}>
		<Wallet class="w-4 h-4" />
		{showDeductions ? 'Kesinti tahminini gizle' : 'Sezon sonu kesinti tahmini'}
	</button>
	<button class="text-sm text-teal-700 hover:underline inline-flex items-center gap-1 cursor-pointer"
		onclick={toggleAllotments}>
		<ScrollText class="w-4 h-4" />
		{showAllotments ? 'Kontenjan kullanımını gizle' : 'Kontenjan kullanımı (60 gün)'}
	</button>
	<button class="text-sm text-teal-700 hover:underline inline-flex items-center gap-1 cursor-pointer"
		onclick={toggleAudit}>
		<AlertTriangle class="w-4 h-4" />
		{showAudit ? 'Fiyat denetimini gizle' : 'Fiyat/kural denetimi'}
	</button>
</div>
<div class="mb-4">
	{#if showCalendar}
		<div class="mt-2 bg-white border border-gray-200 rounded-xl shadow-sm p-4 overflow-x-auto">
			{#if calendarLoading}
				<TableSkeleton rows={4} columns={2} />
			{:else if calendarItems.length === 0}
				<p class="text-sm text-gray-500">Önümüzdeki 90 günde tarih-bantlı aksiyon yok.</p>
			{:else}
				<div class="min-w-[640px] grid gap-1.5">
					<div class="flex justify-between text-[11px] text-gray-500 pl-[220px]">
						<span>bugün</span><span>+30 gün</span><span>+60 gün</span><span>+90 gün</span>
					</div>
					{#each calendarItems as a (a.action_id)}
						{@const salesPos = bandPos(a.sales_start, a.open_ended ? null : a.sales_end)}
						<div class="flex items-center gap-2">
							<div class="w-[212px] shrink-0 text-xs truncate" title={a.title}>
								<span class="font-medium">{a.group_name}</span>
								<span class="text-gray-500"> · {a.title ?? a.action_type}</span>
							</div>
							<div class="relative h-5 flex-1 bg-gray-50 rounded">
								{#if salesPos}
									<div class="absolute h-2 top-0.5 rounded bg-teal-700/70"
										style={`left:${salesPos.left}%;width:${salesPos.width}%`}
										title={`Satış: ${a.sales_start ?? '—'} – ${a.open_ended ? 'ikinci bildirime kadar' : (a.sales_end ?? '—')}`}></div>
								{/if}
								{#each a.tiers as t, ti (ti)}
									{@const tp = bandPos(t.stay_start, t.stay_end)}
									{#if tp}
										<div class="absolute h-2 bottom-0.5 rounded bg-brass"
											style={`left:${tp.left}%;width:${tp.width}%`}
											title={`Konaklama: ${t.stay_start ?? '—'} – ${t.stay_end ?? '—'}${t.discount_percent != null ? ` · %${t.discount_percent}` : ''}`}></div>
									{/if}
								{/each}
							</div>
						</div>
					{/each}
					<p class="text-[11px] text-gray-500 mt-1">
						<span class="inline-block w-3 h-2 rounded bg-teal-700/70 align-middle"></span> satış penceresi ·
						<span class="inline-block w-3 h-2 rounded bg-brass align-middle"></span> konaklama bandı (indirim)
					</p>
				</div>
			{/if}
		</div>
	{/if}

	{#if showDeductions}
		<div class="mt-2 bg-white border border-gray-200 rounded-xl shadow-sm p-4 overflow-x-auto">
			{#if deductionsLoading}
				<TableSkeleton rows={4} columns={4} />
			{:else if deductions.length === 0}
				<p class="text-sm text-gray-500">Kesinti tanımlı kontrat yok.</p>
			{:else}
				<table class="w-full text-sm min-w-[560px]">
					<thead><tr class="text-left text-xs text-gray-600 uppercase border-b border-gray-200">
						<th class="px-2 py-1.5">Kontrat</th>
						<th class="px-2 py-1.5 text-right">Ciro (EUR)</th>
						<th class="px-2 py-1.5 text-right">Tahmini Kesinti</th>
						<th class="px-2 py-1.5">Kalemler</th>
					</tr></thead>
					<tbody>
						{#each deductions as d (d.contract_code)}
							<tr class="border-b border-gray-100 align-top">
								<td class="px-2 py-1.5 whitespace-nowrap">
									<span class="font-medium">{d.group_name}</span>
									<span class="text-xs text-gray-500"> {d.contract_code}</span>
								</td>
								<td class="px-2 py-1.5 text-right tabular-nums">{fmtMoney(d.ciro_eur)}</td>
								<td class="px-2 py-1.5 text-right tabular-nums font-medium">{fmtMoney(d.total_estimate)}</td>
								<td class="px-2 py-1.5 text-xs text-gray-600">
									{#each d.lines as l, li (li)}
										<div>{l.deduction_type}{l.percent != null ? ` %${l.percent}` : ''}{l.currency !== 'EUR' ? ` (${l.currency})` : ''} — {fmtMoney(l.amount_native, l.currency)}</div>
									{/each}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<p class="text-[11px] text-gray-500 mt-2">Cari yıl çıkış cirosu üzerinden hesaplanır (Sedna Contrack eşlemeli); operatör bildirimiyle karşılaştırma içindir — mutabakat masasına hazırlık.</p>
			{/if}
		</div>
	{/if}

	{#if showAudit}
		<div class="mt-2 bg-white border border-gray-200 rounded-xl shadow-sm p-4 overflow-x-auto">
			{#if auditLoading}
				<TableSkeleton rows={4} columns={4} />
			{:else if audit}
				<div class="flex flex-wrap gap-2 mb-3">
					<StatusBadge type="info">{audit.counts.checked ?? 0} rezervasyon denetlendi</StatusBadge>
					{#if audit.counts.currency_mismatch}<StatusBadge type="warning">{audit.counts.currency_mismatch} para birimi</StatusBadge>{/if}
					{#if audit.counts.min_stay_violation}<StatusBadge type="warning">{audit.counts.min_stay_violation} min-stay</StatusBadge>{/if}
					{#if audit.counts.period_gap}<StatusBadge type="warning">{audit.counts.period_gap} dönem boşluğu</StatusBadge>{/if}
					{#if audit.counts.price_deviation}<StatusBadge type="neutral">{audit.counts.price_deviation} fiyat sapması (EB/SPO etkisi olabilir)</StatusBadge>{/if}
					{#if !audit.counts.rate_rows}<StatusBadge type="neutral">rate matrisi henüz girilmedi (Faz 4b) — kontrat-fiyat kıyası pasif</StatusBadge>{/if}
				</div>
				{#if audit.findings.length === 0}
					<p class="text-sm text-gray-500">Bulgu yok.</p>
				{:else}
					<table class="w-full text-xs min-w-[640px]">
						<thead><tr class="text-left text-gray-600 uppercase border-b border-gray-200">
							<th class="px-2 py-1.5">Tür</th><th class="px-2 py-1.5">Acente</th>
							<th class="px-2 py-1.5">Voucher</th><th class="px-2 py-1.5">Giriş</th>
							<th class="px-2 py-1.5">Detay</th>
						</tr></thead>
						<tbody>
							{#each audit.findings.slice(0, 60) as f, fi (fi)}
								<tr class="border-b border-gray-50">
									<td class="px-2 py-1 whitespace-nowrap">{AUDIT_TYPE_LABELS[f.type] ?? f.type}</td>
									<td class="px-2 py-1 whitespace-nowrap">{f.agency}</td>
									<td class="px-2 py-1 whitespace-nowrap">{f.voucher ?? '—'}</td>
									<td class="px-2 py-1 whitespace-nowrap">{fmtDate(f.checkin)}</td>
									<td class="px-2 py-1 text-gray-600">{f.detail}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			{/if}
		</div>
	{/if}

	{#if showAllotments}
		<div class="mt-2 bg-white border border-gray-200 rounded-xl shadow-sm p-4 overflow-x-auto">
			{#if allotmentsLoading}
				<TableSkeleton rows={4} columns={5} />
			{:else if allotments.length === 0}
				<p class="text-sm text-gray-500">Kontenjan tanımlı kontrat yok.</p>
			{:else}
				<table class="w-full text-sm min-w-[620px]">
					<thead><tr class="text-left text-xs text-gray-600 uppercase border-b border-gray-200">
						<th class="px-2 py-1.5">Kontrat</th>
						<th class="px-2 py-1.5 text-right">Kontenjan</th>
						<th class="px-2 py-1.5 text-right">Ort. Satılan</th>
						<th class="px-2 py-1.5">Kullanım</th>
						<th class="px-2 py-1.5 text-right">Tepe / Aşım</th>
					</tr></thead>
					<tbody>
						{#each allotments as a (a.contract_code)}
							<tr class="border-b border-gray-100">
								<td class="px-2 py-1.5 whitespace-nowrap">
									<span class="font-medium">{a.group_name}</span>
									<span class="text-xs text-gray-500"> {a.contract_code}</span>
									{#if a.guaranteed_share_percent}
										<span class="text-[11px] text-amber-700"> · %{a.guaranteed_share_percent} taahhüt</span>
									{/if}
								</td>
								<td class="px-2 py-1.5 text-right tabular-nums">{a.allotment_rooms} oda</td>
								<td class="px-2 py-1.5 text-right tabular-nums">{a.avg_sold}</td>
								<td class="px-2 py-1.5 w-40">
									<div class="h-2 bg-gray-100 rounded overflow-hidden">
										<div class="h-2 rounded {a.utilization_pct > 100 ? 'bg-red-500' : 'bg-teal-700'}"
											style={`width:${Math.min(100, a.utilization_pct)}%`}></div>
									</div>
									<span class="text-[11px] text-gray-500 tabular-nums">%{a.utilization_pct}</span>
								</td>
								<td class="px-2 py-1.5 text-right tabular-nums">
									{a.max_sold}
									{#if a.days_over_allotment > 0}
										<span class="text-red-600 text-xs"> · {a.days_over_allotment}g aşım</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	{/if}
</div>

<!-- İçerik -->
{#if loading}
	<TableSkeleton rows={6} columns={7} />
{:else if contracts.length === 0}
	<EmptyState
		icon={ScrollText}
		title="Henüz kontrat kaydı yok"
		description="Operatör kontratlarını ekleyerek arşivi başlatın"
		ctaText={canUse ? 'Yeni Kontrat' : ''}
		onCta={canUse ? openAdd : null}
	/>
{:else}
	<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-x-auto">
		<table class="w-full text-sm min-w-[880px]">
			<thead>
				<tr class="text-left text-xs text-gray-600 uppercase border-b border-gray-200">
					<th class="px-3 py-2 w-6"></th>
					<th class="px-3 py-2">Grup / Kod</th>
					<th class="px-3 py-2">Sezon</th>
					<th class="px-3 py-2">Geçerlilik</th>
					<th class="px-3 py-2">Fatura Vadesi</th>
					<th class="px-3 py-2 text-right">Bekleyen Taksit</th>
					<th class="px-3 py-2">Güven</th>
					<th class="px-3 py-2">Durum</th>
					<th class="px-3 py-2 w-20"></th>
				</tr>
			</thead>
			<tbody>
				{#each contracts as c (c.id)}
					<tr class="border-b border-gray-100 hover:bg-gray-50 cursor-pointer group"
						onclick={() => toggleExpand(c.id)}>
						<td class="px-3 py-2 text-gray-400">
							{#if expandedId === c.id}<ChevronDown class="w-4 h-4" />{:else}<ChevronRight class="w-4 h-4" />{/if}
						</td>
						<td class="px-3 py-2">
							<div class="font-medium text-gray-900">{c.agency_group_name}</div>
							<div class="text-xs text-gray-500">{c.code}{c.title ? ` · ${c.title}` : ''}</div>
						</td>
						<td class="px-3 py-2">{c.season_code}</td>
						<td class="px-3 py-2 whitespace-nowrap text-gray-600">
							{fmtDate(c.valid_from)} – {fmtDate(c.valid_to)}
						</td>
						<td class="px-3 py-2 text-gray-600">{dueLabel(c)}</td>
						<td class="px-3 py-2 text-right tabular-nums">
							{#if c.pending_installment_count}
								{fmtMoney(c.pending_installment_total, c.currency)}
								<span class="text-xs text-gray-500">({c.pending_installment_count})</span>
							{:else}—{/if}
						</td>
						<td class="px-3 py-2">
							<StatusBadge type={CONFIDENCE_META[c.data_confidence]?.type ?? 'neutral'}>
								{CONFIDENCE_META[c.data_confidence]?.label ?? c.data_confidence}
							</StatusBadge>
						</td>
						<td class="px-3 py-2">
							<StatusBadge type={STATUS_META[c.status]?.type ?? 'neutral'}>
								{STATUS_META[c.status]?.label ?? c.status}
							</StatusBadge>
						</td>
						<td class="px-3 py-2">
							{#if canUse}
								<div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity"
									role="presentation" onclick={(e) => e.stopPropagation()}>
									<Button variant="secondary" size="sm" onclick={() => openEdit(c)}
										title="Düzenle"><Pencil class="w-3.5 h-3.5" /></Button>
									<Button variant="danger" size="sm" title="Sil"
										onclick={() => confirmDelete = { show: true, kind: 'contract', id: c.id, label: c.code }}>
										<Trash2 class="w-3.5 h-3.5" /></Button>
								</div>
							{/if}
						</td>
					</tr>
					{#if expandedId === c.id}
						<tr class="border-b border-gray-100 bg-gray-50/60">
							<td colspan="9" class="px-6 py-4">
								{#if detailLoading}
									<TableSkeleton rows={3} columns={4} />
								{:else if detail}
									<div class="grid gap-5">
										<!-- Ödeme planları -->
										<section>
											<h4 class="text-sm font-semibold text-gray-800 mb-2">Ödeme Planları</h4>
											{#if detail.payment_plans.length === 0}
												<p class="text-sm text-gray-500">Ödeme planı kaydı yok.</p>
											{/if}
											{#each detail.payment_plans as plan (plan.id)}
												<div class="mb-3 border border-gray-200 rounded-lg bg-white">
													<div class="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-100">
														<span class="font-medium text-sm">{PLAN_TYPE_LABELS[plan.plan_type] ?? plan.plan_type}</span>
														{#if plan.total_amount}
															<span class="text-sm text-gray-600 tabular-nums">· {fmtMoney(plan.total_amount, plan.currency)}</span>
														{/if}
														{#if plan.description}<span class="text-xs text-gray-500">{plan.description}</span>{/if}
														{#if canUse}
															<div class="ml-auto">
																<Button variant="secondary" size="sm" onclick={() => openAddInstallment(plan.id)}>
																	<Plus class="w-3.5 h-3.5" /> Taksit</Button>
															</div>
														{/if}
													</div>
													{#if plan.installments.length}
														<table class="w-full text-xs">
															<tbody>
																{#each plan.installments as inst (inst.id)}
																	<tr class="border-b border-gray-50 last:border-0">
																		<td class="px-3 py-1.5 whitespace-nowrap">{fmtDate(inst.due_date)}</td>
																		<td class="px-3 py-1.5 text-right tabular-nums">
																			{inst.amount != null ? fmtMoney(inst.amount, inst.currency) : (inst.percent != null ? `%${inst.percent}` : '—')}
																		</td>
																		<td class="px-3 py-1.5">
																			<StatusBadge type={INST_STATUS_META[inst.status]?.type ?? 'neutral'}>
																				{INST_STATUS_META[inst.status]?.label ?? inst.status}
																			</StatusBadge>
																			{#if inst.is_conditional}
																				<span class="ml-1 text-amber-700 text-[11px]" title={inst.condition_note}>koşullu</span>
																			{/if}
																		</td>
																		<td class="px-3 py-1.5 text-gray-500">{inst.notes ?? ''}</td>
																		<td class="px-3 py-1.5 text-right whitespace-nowrap">
																			{#if canUse && inst.status === 'pending'}
																				<button class="text-emerald-700 hover:underline text-xs cursor-pointer"
																					onclick={() => setInstallmentStatus(inst, 'paid')}>
																					<CheckCircle2 class="w-3.5 h-3.5 inline" /> Ödendi
																				</button>
																			{:else if canUse && inst.status === 'paid'}
																				<button class="text-gray-500 hover:underline text-xs cursor-pointer"
																					onclick={() => setInstallmentStatus(inst, 'pending')}>Geri al</button>
																			{/if}
																		</td>
																	</tr>
																{/each}
															</tbody>
														</table>
													{/if}
												</div>
											{/each}
										</section>

										<!-- Aksiyonlar -->
										<section>
											<div class="flex items-center gap-2 mb-2">
												<h4 class="text-sm font-semibold text-gray-800">Aksiyonlar / SPO</h4>
												{#if canUse}
													<Button variant="secondary" size="sm" onclick={openAddAction}>
														<Plus class="w-3.5 h-3.5" /> Aksiyon</Button>
												{/if}
											</div>
											{#if detail.actions.length === 0}
												<p class="text-sm text-gray-500">Aksiyon kaydı yok.</p>
											{:else}
												<div class="grid gap-1.5">
													{#each detail.actions as a (a.id)}
														<div class="flex flex-wrap items-center gap-2 text-sm bg-white border border-gray-200 rounded-lg px-3 py-1.5">
															<span class="font-medium">{ACTION_TYPE_LABELS[a.action_type] ?? a.action_type}</span>
															{#if a.title}<span class="text-gray-600">{a.title}</span>{/if}
															{#if a.sales_start || a.sales_end}
																<span class="text-xs text-gray-500">
																	Satış: {fmtDate(a.sales_start)} – {a.open_ended ? 'ikinci bildirime kadar' : fmtDate(a.sales_end)}
																	{a.basis === 'stay' ? '(konaklama bazlı)' : a.basis === 'booking' ? '(satış bazlı)' : ''}
																</span>
															{/if}
															{#each a.tiers as t (t.id)}
																<span class="text-xs bg-gray-100 rounded-full px-2 py-0.5 tabular-nums">
																	{t.stay_start ? `${fmtDate(t.stay_start)}–${fmtDate(t.stay_end)}` : ''}
																	{t.discount_percent != null ? ` %${t.discount_percent}` : ''}
																	{t.fixed_net_price != null ? ` ${fmtMoney(t.fixed_net_price)}` : ''}
																</span>
															{/each}
															{#if a.status === 'superseded'}
																<StatusBadge type="warning">Revize edildi</StatusBadge>
															{/if}
														</div>
													{/each}
												</div>
											{/if}
										</section>

										<!-- Dönemler + Kontenjan + Kesintiler (kompakt) -->
										<div class="grid md:grid-cols-3 gap-4">
											<section>
												<h4 class="text-sm font-semibold text-gray-800 mb-2">Fiyat Dönemleri</h4>
												{#if detail.periods.length === 0}
													<p class="text-sm text-gray-500">Kayıt yok.</p>
												{:else}
													<table class="w-full text-xs bg-white border border-gray-200 rounded-lg overflow-hidden">
														<tbody>
															{#each detail.periods as p (p.id)}
																<tr class="border-b border-gray-50 last:border-0">
																	<td class="px-2 py-1 font-medium">{p.code}</td>
																	<td class="px-2 py-1 whitespace-nowrap">{fmtDate(p.date_start)} – {fmtDate(p.date_end)}</td>
																	<td class="px-2 py-1 text-gray-500">{p.release_days != null ? `R${p.release_days}` : ''}{p.min_stay ? ` · min ${p.min_stay}g` : ''}</td>
																</tr>
															{/each}
														</tbody>
													</table>
												{/if}
											</section>
											<section>
												<h4 class="text-sm font-semibold text-gray-800 mb-2">Kontenjan</h4>
												{#if detail.allotments.length === 0}
													<p class="text-sm text-gray-500">Kayıt yok.</p>
												{:else}
													<ul class="text-xs grid gap-1">
														{#each detail.allotments as al (al.id)}
															<li class="bg-white border border-gray-200 rounded-lg px-2 py-1">
																<span class="font-medium tabular-nums">{al.room_count} oda</span>
																<span class="text-gray-500">
																	{al.allotment_type === 'guaranteed' ? '· garantili' : al.allotment_type === 'free_sale' ? '· free sale' : ''}
																	{al.guaranteed_share_percent ? `· %${al.guaranteed_share_percent} garanti` : ''}
																	{al.notes ? `· ${al.notes}` : ''}
																</span>
															</li>
														{/each}
													</ul>
												{/if}
											</section>
											<section>
												<h4 class="text-sm font-semibold text-gray-800 mb-2">Kesintiler</h4>
												{#if detail.deductions.length === 0}
													<p class="text-sm text-gray-500">Kayıt yok.</p>
												{:else}
													<ul class="text-xs grid gap-1">
														{#each detail.deductions as ded (ded.id)}
															<li class="bg-white border border-gray-200 rounded-lg px-2 py-1">
																<span class="font-medium">{ded.deduction_type}</span>
																<span class="tabular-nums">
																	{ded.percent != null ? ` %${ded.percent}` : ''}
																	{ded.fixed_amount != null ? ` ${fmtMoney(ded.fixed_amount, ded.currency ?? 'EUR')}` : ''}
																</span>
																<span class="text-gray-500">
																	{ded.applies === 'season_end' ? '· sezon sonu' : ded.applies === 'monthly' ? '· aylık' : '· fatura başı'}
																</span>
															</li>
														{/each}
													</ul>
												{/if}
											</section>
										</div>

										<!-- Belgeler -->
										<section>
											<div class="flex items-center gap-2 mb-2">
												<h4 class="text-sm font-semibold text-gray-800">Belgeler</h4>
												{#if canUse}
													<Button variant="secondary" size="sm" onclick={openUpload}>
														<Upload class="w-3.5 h-3.5" /> Belge Yükle</Button>
												{/if}
											</div>
											{#if detail.documents.length === 0}
												<p class="text-sm text-gray-500">Belge yok.</p>
											{:else}
												<ul class="grid gap-1">
													{#each detail.documents as doc (doc.id)}
														<li class="flex items-center gap-2 text-sm bg-white border border-gray-200 rounded-lg px-3 py-1.5">
															<FileText class="w-4 h-4 text-gray-400 shrink-0" />
															<span class="truncate">{doc.original_name}</span>
															<span class="text-xs text-gray-500 whitespace-nowrap">
																{DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
																{doc.doc_date ? ` · ${fmtDate(doc.doc_date)}` : ''}
															</span>
															<span class="ml-auto flex items-center gap-1">
																<a class="text-teal-700 hover:underline inline-flex items-center gap-1 text-xs"
																	href={`/api/sales/kontratlar/documents/${doc.id}/download`}
																	download><Download class="w-3.5 h-3.5" /> İndir</a>
																{#if canUse}
																	<button class="text-red-600 hover:text-red-800 ml-2 cursor-pointer" title="Sil"
																		onclick={() => confirmDelete = { show: true, kind: 'document', id: doc.id, label: doc.original_name }}>
																		<Trash2 class="w-3.5 h-3.5" /></button>
																{/if}
															</span>
														</li>
													{/each}
												</ul>
											{/if}
										</section>

										{#if detail.notes}
											<p class="text-xs text-gray-500 whitespace-pre-wrap border-t border-gray-200 pt-2">{detail.notes}</p>
										{/if}
									</div>
								{/if}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<!-- Kontrat ekle/düzenle modalı -->
<Modal bind:show={showContractModal} title={editingId != null ? 'Kontratı Düzenle' : 'Yeni Kontrat'} maxWidth="max-w-2xl">
	<div class="grid gap-3 sm:grid-cols-2">
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-group">
				Acente Grubu <span class="text-red-600">*</span></label>
			<Select id="kt-group" bind:value={form.agency_group_id} invalid={!!fieldErrors.agency_group_id}>
				{#each groups as g}<option value={g.id}>{g.name}</option>{/each}
			</Select>
			{#if fieldErrors.agency_group_id}<p class="text-xs text-red-600 mt-1">{fieldErrors.agency_group_id}</p>{/if}
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-code">
				Kontrat Kodu <span class="text-red-600">*</span></label>
			<Input id="kt-code" bind:value={form.code} placeholder="ALLTOURS-S26"
				invalid={!!fieldErrors.code} aria-invalid={!!fieldErrors.code} />
			{#if fieldErrors.code}<p class="text-xs text-red-600 mt-1">{fieldErrors.code}</p>{/if}
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-season">
				Sezon <span class="text-red-600">*</span></label>
			<Input id="kt-season" bind:value={form.season_code} placeholder="S26"
				invalid={!!fieldErrors.season_code} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-title">Başlık</label>
			<Input id="kt-title" bind:value={form.title} placeholder="Accommodation Contract 842/26" />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-from">Geçerlilik Başlangıcı</label>
			<Input id="kt-from" type="date" bind:value={form.valid_from} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-to">Geçerlilik Bitişi</label>
			<Input id="kt-to" type="date" bind:value={form.valid_to} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-cur">Para Birimi</label>
			<Select id="kt-cur" bind:value={form.currency}>
				<option value="EUR">EUR</option><option value="TL">TL</option>
				<option value="USD">USD</option><option value="GBP">GBP</option>
			</Select>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-pm">Fiyat Modeli</label>
			<Select id="kt-pm" bind:value={form.pricing_model}>
				<option value="">—</option>
				<option value="pp">Kişi başı (PP)</option>
				<option value="pu">Oda başı (PU)</option>
				<option value="mixed">Karma (PP+PU)</option>
				<option value="pp_multiplier">PP × doluluk çarpanı</option>
				<option value="occupancy_total">Doluluk kombinasyon toplamı</option>
			</Select>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-due-basis">Fatura Vade Bazı</label>
			<Select id="kt-due-basis" bind:value={form.invoice_due_basis}>
				<option value="">—</option>
				<option value="checkout">Çıkış (C-Out)</option>
				<option value="invoice_date">Fatura tarihi</option>
				<option value="invoice_receipt">Fatura tebliği</option>
				<option value="self_billing">Self-billing</option>
				<option value="before_checkin">Girişten önce</option>
				<option value="first_friday_after_checkin">Girişten sonraki ilk Cuma</option>
			</Select>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-due-days">Vade (gün)</label>
			<MoneyInput id="kt-due-days" bind:value={form.invoice_due_days} decimals={0} min={0} placeholder="21" />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-conf">Veri Güveni</label>
			<Select id="kt-conf" bind:value={form.data_confidence}>
				<option value="verified">Doğrulanmış</option>
				<option value="scanned_approx">Taranmış — yaklaşık</option>
				<option value="needs_confirmation">Teyit bekliyor</option>
			</Select>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-status">Durum</label>
			<Select id="kt-status" bind:value={form.status}>
				<option value="active">Aktif</option>
				<option value="draft">Taslak</option>
				<option value="superseded">Revize edildi</option>
			</Select>
		</div>
		<div class="sm:col-span-2">
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-legal">Karşı Taraf (Tüzel)</label>
			<Input id="kt-legal" bind:value={form.legal_counterparty}
				placeholder="alltours flugreisen gmbh, Düsseldorf" />
		</div>
		<div class="sm:col-span-2">
			<label class="block text-sm font-medium text-gray-700 mb-1" for="kt-notes">Notlar</label>
			<Textarea id="kt-notes" bind:value={form.notes} rows={3} />
		</div>
	</div>
	<div class="flex justify-end gap-2 mt-4">
		<Button variant="secondary" onclick={() => showContractModal = false}>İptal</Button>
		<Button loading={saving} onclick={handleSave}>Kaydet</Button>
	</div>
</Modal>

<!-- Aksiyon modalı -->
<Modal bind:show={showActionModal} title="Yeni Aksiyon / SPO" maxWidth="max-w-xl">
	<div class="grid gap-3 sm:grid-cols-2">
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-type">Tür</label>
			<Select id="ac-type" bind:value={actionForm.action_type}>
				{#each Object.entries(ACTION_TYPE_LABELS) as [v, l]}<option value={v}>{l}</option>{/each}
			</Select>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-title">Başlık</label>
			<Input id="ac-title" bind:value={actionForm.title} placeholder="Şubat SPO %10" />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-ss">Satış Başlangıcı</label>
			<Input id="ac-ss" type="date" bind:value={actionForm.sales_start} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-se">Satış Bitişi</label>
			<Input id="ac-se" type="date" bind:value={actionForm.sales_end} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-basis">Baz</label>
			<Select id="ac-basis" bind:value={actionForm.basis}>
				<option value="booking">Satış (booking) bazlı</option>
				<option value="stay">Konaklama (stay) bazlı</option>
			</Select>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-comb">Kombinasyon</label>
			<Select id="ac-comb" bind:value={actionForm.combinable}>
				<option value="">Belirsiz</option>
				<option value="cumulative">Kümüle (yüzdeler toplanır)</option>
				<option value="best_price">Best price (en ucuz kazanır)</option>
				<option value="non_combinable">Birleşmez</option>
				<option value="kb_only">Yalnız KB ile birleşir</option>
			</Select>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-ts">Konaklama Başlangıcı</label>
			<Input id="ac-ts" type="date" bind:value={actionForm.stay_start} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-te">Konaklama Bitişi</label>
			<Input id="ac-te" type="date" bind:value={actionForm.stay_end} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-disc">İndirim %</label>
			<MoneyInput id="ac-disc" bind:value={actionForm.discount_percent} decimals={2} min={0} max={100} placeholder="10,00" />
		</div>
		<div class="sm:col-span-2">
			<label class="block text-sm font-medium text-gray-700 mb-1" for="ac-notes">Notlar</label>
			<Textarea id="ac-notes" bind:value={actionForm.notes} rows={2} />
		</div>
	</div>
	<div class="flex justify-end gap-2 mt-4">
		<Button variant="secondary" onclick={() => showActionModal = false}>İptal</Button>
		<Button loading={saving} onclick={handleSaveAction}>Kaydet</Button>
	</div>
</Modal>

<!-- Taksit modalı -->
<Modal bind:show={showInstallmentModal} title="Yeni Taksit" maxWidth="max-w-md">
	<div class="grid gap-3">
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="in-due">
				Vade Tarihi <span class="text-red-600">*</span></label>
			<Input id="in-due" type="date" bind:value={instForm.due_date} />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="in-amount">
				Tutar <span class="text-red-600">*</span></label>
			<MoneyInput id="in-amount" bind:value={instForm.amount} currency={instForm.currency} min={0} placeholder="0,00" />
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="in-cur">Para Birimi</label>
			<Select id="in-cur" bind:value={instForm.currency}>
				<option value="EUR">EUR</option><option value="TL">TL</option><option value="USD">USD</option>
			</Select>
		</div>
		<label class="flex items-center gap-2 text-sm text-gray-700">
			<input type="checkbox" class="accent-teal-700" bind:checked={instForm.is_conditional} />
			Koşullu taksit (performans şartına bağlı)
		</label>
		{#if instForm.is_conditional}
			<Input bind:value={instForm.condition_note} placeholder="Koşul (ör. %70 ciro/avans şartı)" />
		{/if}
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="in-notes">Not</label>
			<Input id="in-notes" bind:value={instForm.notes} />
		</div>
	</div>
	<div class="flex justify-end gap-2 mt-4">
		<Button variant="secondary" onclick={() => showInstallmentModal = false}>İptal</Button>
		<Button loading={saving} onclick={handleSaveInstallment}>Kaydet</Button>
	</div>
</Modal>

<!-- Belge yükleme modalı -->
<Modal bind:show={showUploadModal} title="Belge Yükle" maxWidth="max-w-xl">
	<div class="grid gap-3">
		<FileDropzone accept=".pdf,.xls,.xlsx" maxSize={20971520}
			label="PDF veya Excel dosyasını buraya sürükleyin"
			hint="PDF en çok 20 MB · Excel (.xls/.xlsx) en çok 10 MB"
			onSelect={(files) => uploadFile = files[0]}
			onError={(errs) => showToast(errs.join(', '), 'error')} />
		{#if uploadFile}
			<p class="text-sm text-gray-600 flex items-center gap-2">
				<FileText class="w-4 h-4" /> {uploadFile.name}</p>
		{/if}
		<div class="grid gap-3 sm:grid-cols-2">
			<div>
				<label class="block text-sm font-medium text-gray-700 mb-1" for="up-type">Belge Türü</label>
				<Select id="up-type" bind:value={uploadMeta.doc_type}>
					{#each Object.entries(DOC_TYPE_LABELS) as [v, l]}<option value={v}>{l}</option>{/each}
				</Select>
			</div>
			<div>
				<label class="block text-sm font-medium text-gray-700 mb-1" for="up-date">Belge Tarihi</label>
				<Input id="up-date" type="date" bind:value={uploadMeta.doc_date} />
			</div>
		</div>
		<div>
			<label class="block text-sm font-medium text-gray-700 mb-1" for="up-notes">Not</label>
			<Input id="up-notes" bind:value={uploadMeta.notes} />
		</div>
	</div>
	<div class="flex justify-end gap-2 mt-4">
		<Button variant="secondary" onclick={() => showUploadModal = false}>İptal</Button>
		<Button loading={uploading} onclick={handleUpload}>Yükle</Button>
	</div>
</Modal>

<ConfirmDialog
	bind:show={confirmDelete.show}
	title={confirmDelete.kind === 'contract' ? 'Kontratı Sil' : 'Belgeyi Sil'}
	message={`"${confirmDelete.label}" silinecek. Bu işlem geri alınamaz. Emin misiniz?`}
	confirmText="Sil"
	danger
	onConfirm={handleDelete}
	onCancel={() => confirmDelete = { ...confirmDelete, show: false }}
/>
