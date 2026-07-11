<!--
	ReservationsPanel.svelte — Rezervasyonlar sekmesi (Acente Mahsup & Nakit Akım birleşik sayfası).

	Eski /dashboard/satis/otel-rezervasyon sayfasının içeriği (2026-07-09 birleştirme):
	XLS yükleme, KPI kartları, aylık doluluk + günlük drill-down, ADR/konaklama trendi,
	pazar/acente/oda tipi/pansiyon dağılımları, pickup, acente gruplama (drag-drop + modal).
	İzin kodu: sales.acente_mahsup (view/use).
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import {
		ArrowUpDown,
		BedDouble,
		Building2,
		Calendar,
		ChevronRight,
		Coins,
		FileSpreadsheet,
		Globe2,
		Loader2,
		PieChart,
		GripVertical,
		RefreshCw,
		Settings2,
		TrendingUp,
		Undo2,
		Upload,
		Users,
		X,
	} from 'lucide-svelte';

	import { api, ApiError } from '$lib/api';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import Select from '$lib/components/Select.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import Button from '$lib/components/Button.svelte';
	import ResultModal from '$lib/components/sales/otel-rezervasyon/ResultModal.svelte';
	import RemovalReviewModal from '$lib/components/sales/otel-rezervasyon/RemovalReviewModal.svelte';
	import UploadsHistoryModal from '$lib/components/sales/otel-rezervasyon/UploadsHistoryModal.svelte';
	import AgencyGroupModal from '$lib/components/sales/otel-rezervasyon/AgencyGroupModal.svelte';
	import type { UploadHistory, RemovalCandidate, UploadResult, ApiGroup } from '$lib/types/reservation';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';

	// ───── Const ──────────────────────────────────────────
	const TR_AY: Record<string, string> = {
		'01': 'Oca', '02': 'Şub', '03': 'Mar', '04': 'Nis', '05': 'May', '06': 'Haz',
		'07': 'Tem', '08': 'Ağu', '09': 'Eyl', '10': 'Eki', '11': 'Kas', '12': 'Ara',
	};

	type SummaryData = {
		kpi: {
			total_rez: number; total_eur: number; total_room_nights: number;
			total_guest_nights: number; total_pax: number;
			total_adult: number; total_child_paid: number; total_child_free: number; total_baby: number;
			adr: number; avg_los: number; definite_count: number; option_count: number;
			// Doluluk metrikleri
			total_capacity: number; date_range_days: number; occupancy_pct: number;
		};
		monthly: Array<{ month: string; rez: number; room_nights: number; pax: number; eur: number; capacity_nights: number; empty_nights: number; occupancy_pct: number }>;
		by_agency: Array<{ name: string; rez: number; room_nights: number; pax: number; eur: number; pct: number }>;
		by_nation: Array<{ code: string; rez: number; room_nights: number; eur: number; pct: number }>;
		by_room_type: Array<{ name: string; rez: number; room_nights: number; eur: number; pct: number; total_rooms: number; occupancy_pct: number }>;
		by_board: Array<{ name: string; rez: number; eur: number; pct: number }>;
		pickup: Array<{ month: string; rez: number; eur: number; pct: number }>;
		los_buckets: Array<{ bucket: string; count: number }>;
		lead_time: { avg: number; median: number; min: number; max: number };
	};

	// UploadHistory, RemovalCandidate, UploadResult, ApiGroup → $lib/types/reservation (modal bileşenleriyle ortak)

	type BulkDeleteResult = {
		deleted: number;
		skipped: number;
		skipped_reasons: string[];
	};

	type DailyOccupancy = {
		month: string;
		days: Array<{
			date: string;            // YYYY-MM-DD
			weekday: number;          // 0=Pzt ... 6=Pazar
			room_nights: number;
			capacity: number;
			empty: number;
			occupancy_pct: number;
			pax: number;
			eur: number;
			checkin_count: number;
			checkout_count: number;
		}>;
		total_capacity: number;
		avg_occupancy_pct: number;
		peak_date: string | null;
		peak_occupancy_pct: number;
		low_date: string | null;
		low_occupancy_pct: number;
	};

	// ───── Derived ────────────────────────────────────────
	const canView = $derived(hasPermission('sales.acente_mahsup', 'view'));
	const canUse = $derived(hasPermission('sales.acente_mahsup', 'use'));

	// ───── State ──────────────────────────────────────────
	let summary = $state<SummaryData | null>(null);
	let uploads = $state<UploadHistory[]>([]);
	let loading = $state<boolean>(true);
	let uploading = $state<boolean>(false);

	let filters = $state<{ year: number | 'all' }>({ year: new Date().getFullYear() });
	let availableYears = $state<number[]>([]);

	let uploadResult = $state<UploadResult | null>(null);
	let showResultModal = $state<boolean>(false);
	let showUploadsModal = $state<boolean>(false);

	let confirmDelete = $state<{ show: boolean; id: number | null; fileName: string }>({
		show: false, id: null, fileName: '',
	});

	// Silme adayları (yükleme sonrası tespit edilen olası iptaller)
	let showRemovalModal = $state<boolean>(false);
	let removalCandidates = $state<RemovalCandidate[]>([]);
	let selectedRemovalIds = $state<Set<number>>(new Set());
	let bulkDeleting = $state<boolean>(false);
	let confirmBulkDelete = $state<boolean>(false);

	// Aylık drill-down state
	let expandedMonth = $state<string | null>(null);
	let dailyData = $state<DailyOccupancy | null>(null);
	let dailyDataPrev = $state<DailyOccupancy | null>(null);  // Karşılaştırma için önceki yıl aynı ay
	let dailyLoading = $state<boolean>(false);

	// Yıl karşılaştırma state
	let compareMode = $state<boolean>(false);
	let previousYearSummary = $state<SummaryData | null>(null);
	let previousYearLabel = $derived(
		typeof filters.year === 'number' ? filters.year - 1 : null
	);
	let canCompare = $derived(
		typeof filters.year === 'number' && availableYears.includes(filters.year - 1)
	);

	// ───── Acente Gruplama ─────────────────────────────────
	// ApiGroup → $lib/types/reservation

	type AgencyGroupItem = {
		type: 'group'; id: number; name: string;
		members: Array<{ name: string; rez: number; room_nights: number; pax: number; eur: number; pct: number }>;
		rez: number; room_nights: number; pax: number; eur: number; pct: number;
	};
	type AgencyIndividualItem = {
		type: 'individual';
		name: string; rez: number; room_nights: number; pax: number; eur: number; pct: number;
	};
	type AgencyListItem = AgencyGroupItem | AgencyIndividualItem;

	// API'den yüklenen grup tanımları
	let agencyGroups = $state<ApiGroup[]>([]);

	// Hangi acente hangi gruba ait → hızlı arama (reactive)
	let agencyToGroup = $derived(
		Object.fromEntries(
			agencyGroups.flatMap(g => g.members.map(m => [m, g.name]))
		) as Record<string, string>
	);
	let agencyToGroupId = $derived(
		Object.fromEntries(
			agencyGroups.flatMap(g => g.members.map(m => [m, g.id]))
		) as Record<string, number>
	);

	let agencyViewMode = $state<'individual' | 'grouped'>('individual');
	let expandedGroups = $state<Set<string>>(new Set());

	let groupedAgencies = $derived((): AgencyListItem[] => {
		if (!summary) return [];
		const agencies = summary.by_agency;
		const totalEur = agencies.reduce((s, a) => s + a.eur, 0);

		const groupMap = new Map<string, { apiGroup: ApiGroup; rows: typeof agencies }>();
		const ungrouped: typeof agencies = [];

		for (const a of agencies) {
			const gName = agencyToGroup[a.name];
			if (gName) {
				if (!groupMap.has(gName)) {
					const apiGroup = agencyGroups.find(g => g.name === gName)!;
					groupMap.set(gName, { apiGroup, rows: [] });
				}
				groupMap.get(gName)!.rows.push(a);
			} else {
				ungrouped.push(a);
			}
		}

		const result: AgencyListItem[] = [];
		for (const [, { apiGroup, rows }] of groupMap.entries()) {
			const grpEur = rows.reduce((s, m) => s + m.eur, 0);
			result.push({
				type: 'group', id: apiGroup.id, name: apiGroup.name,
				members: [...rows].sort((a, b) => b.eur - a.eur),
				rez: rows.reduce((s, m) => s + m.rez, 0),
				room_nights: rows.reduce((s, m) => s + m.room_nights, 0),
				pax: rows.reduce((s, m) => s + m.pax, 0),
				eur: grpEur,
				pct: totalEur > 0 ? (grpEur / totalEur) * 100 : 0,
			});
		}
		for (const a of ungrouped) result.push({ type: 'individual', ...a });
		return result.sort((a, b) => b.eur - a.eur);
	});

	function toggleGroup(name: string) {
		const next = new Set(expandedGroups);
		if (next.has(name)) next.delete(name);
		else next.add(name);
		expandedGroups = next;
	}

	// ───── Drag & Drop — Acente ↔ Grup ──────────────────────
	// HTML5 DnD; mouse/trackpad'de çalışır. Touch için modal alternatifi var.
	let draggingAgency = $state<string | null>(null);
	let dragOverGroupId = $state<number | null>(null);
	let dragOverUngroup = $state<boolean>(false);
	let assigningAgency = $state<boolean>(false);

	function onAgencyDragStart(e: DragEvent, agencyName: string) {
		if (!e.dataTransfer) return;
		draggingAgency = agencyName;
		e.dataTransfer.effectAllowed = 'move';
		e.dataTransfer.setData('text/plain', agencyName);
	}

	function onAgencyDragEnd() {
		draggingAgency = null;
		dragOverGroupId = null;
		dragOverUngroup = false;
	}

	function onGroupDragOver(e: DragEvent, groupId: number) {
		if (!draggingAgency) return;
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
		dragOverGroupId = groupId;
		dragOverUngroup = false;
	}

	function onGroupDragLeave(groupId: number) {
		if (dragOverGroupId === groupId) dragOverGroupId = null;
	}

	function onUngroupDragOver(e: DragEvent) {
		if (!draggingAgency) return;
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
		dragOverUngroup = true;
		dragOverGroupId = null;
	}

	function onUngroupDragLeave() {
		dragOverUngroup = false;
	}

	async function onGroupDrop(e: DragEvent, targetGroupId: number) {
		e.preventDefault();
		const agency = draggingAgency || e.dataTransfer?.getData('text/plain') || '';
		dragOverGroupId = null;
		dragOverUngroup = false;
		draggingAgency = null;
		if (!agency) return;
		// Aynı gruba bırakma → no-op
		if (agencyToGroupId[agency] === targetGroupId) return;
		await assignAgencyToGroup(agency, targetGroupId);
	}

	async function onUngroupDrop(e: DragEvent) {
		e.preventDefault();
		const agency = draggingAgency || e.dataTransfer?.getData('text/plain') || '';
		dragOverGroupId = null;
		dragOverUngroup = false;
		draggingAgency = null;
		if (!agency) return;
		// Zaten gruba ait değilse → no-op
		if (!agencyToGroupId[agency]) return;
		await assignAgencyToGroup(agency, null);
	}

	async function assignAgencyToGroup(agencyName: string, targetGroupId: number | null) {
		assigningAgency = true;
		try {
			const updated = await api.post<ApiGroup[]>('/sales/agency-groups/assign', {
				agency_name: agencyName,
				target_group_id: targetGroupId,
			});
			agencyGroups = updated;
			const targetName = targetGroupId
				? updated.find(g => g.id === targetGroupId)?.name ?? ''
				: '';
			showToast(
				targetGroupId
					? `${agencyName} → ${targetName} grubuna eklendi`
					: `${agencyName} gruptan çıkarıldı`,
				'success'
			);
		} catch (e) {
			console.error('Acente atama hatası:', e);
			showToast(e instanceof ApiError ? e.message : 'Atama hatası', 'error');
		} finally {
			assigningAgency = false;
		}
	}

	// ───── Grup Yönetim Modalı ─────────────────────────────
	// showGroupMgmtModal: true olduğunda
	//   gmView === 'list'  → Grup listesi gösterilir
	//   gmView === 'form'  → Oluştur/Düzenle formu gösterilir
	let showGroupMgmtModal = $state(false);
	let gmView = $state<'list' | 'form'>('list');
	let gmSaving = $state(false);
	// null = yeni grup, ApiGroup = mevcut
	let gmEditTarget = $state<ApiGroup | null>(null);
	let gmNewName = $state('');
	let gmMembers = $state<string[]>([]);
	let gmSearch = $state('');

	let knownAgencies = $derived(
		summary ? [...summary.by_agency.map(a => a.name)].sort() : []
	);
	let gmSuggestions = $derived(
		knownAgencies.filter(n => {
			if (!gmSearch.trim()) return false;
			if (!n.toLowerCase().includes(gmSearch.toLowerCase())) return false;
			if (gmMembers.includes(n)) return false;
			const gid = agencyToGroupId[n];
			if (gid && (!gmEditTarget || gid !== gmEditTarget.id)) return false;
			return true;
		})
	);

	/**
	 * Tüm grup yönetim modal state'ini sıfırla.
	 */
	function resetGmState() {
		gmView = 'list';
		gmEditTarget = null;
		gmNewName = '';
		gmMembers = [];
		gmSearch = '';
		gmSaving = false;
	}

	function openGroupMgmt() {
		// Önce state'i temizle, sonra modal'ı aç — sıralama önemli
		resetGmState();
		showGroupMgmtModal = true;
	}

	function closeGroupMgmt() {
		showGroupMgmtModal = false;
		// State sıfırlama $effect ile garanti altında
	}

	function openNewGroup() {
		gmEditTarget = null;
		gmNewName = '';
		gmMembers = [];
		gmSearch = '';
		gmView = 'form';
	}

	function openEditGroup(g: ApiGroup) {
		gmEditTarget = g;
		gmNewName = g.name;
		gmMembers = [...g.members];
		gmSearch = '';
		gmView = 'form';
	}

	// Modal kapandığında state'i otomatik sıfırla — onclose callback'ine
	// güvenmek yerine reactive olarak garanti et. Backdrop/X/Esc/Kapat
	// hepsi showGroupMgmtModal=false yapar, bu effect tetiklenir.
	$effect(() => {
		if (!showGroupMgmtModal) {
			// gmView, gmSearch vb. sıfırlansın
			gmView = 'list';
			gmEditTarget = null;
			gmNewName = '';
			gmMembers = [];
			gmSearch = '';
			gmSaving = false;
		}
	});

	function gmAddMember(name: string) {
		if (!gmMembers.includes(name)) gmMembers = [...gmMembers, name];
		gmSearch = '';
	}

	function gmRemoveMember(name: string) {
		gmMembers = gmMembers.filter(m => m !== name);
	}

	async function gmSave() {
		const nm = gmNewName.trim().toUpperCase();
		if (!nm) { showToast('Grup adı boş olamaz', 'error'); return; }
		gmSaving = true;
		try {
			if (gmEditTarget) {
				await api.patch(`/sales/agency-groups/${gmEditTarget.id}`,
					{ name: nm, members: gmMembers });
				showToast('Grup güncellendi', 'success');
			} else {
				await api.post('/sales/agency-groups/', { name: nm, members: gmMembers });
				showToast('Grup oluşturuldu', 'success');
			}
			agencyGroups = await api.get('/sales/agency-groups/');
			gmView = 'list';
		} catch (e) {
			console.error('Grup kayıt hatası:', e);
			showToast(e instanceof ApiError ? e.message : 'Kayıt hatası', 'error');
		} finally {
			gmSaving = false;
		}
	}

	// Grup silme onayı (ConfirmDialog — native confirm() kullanılmaz)
	let gmDeleteTarget = $state<ApiGroup | null>(null);
	let showGmDeleteConfirm = $state(false);

	function askGmDelete(g: ApiGroup) {
		gmDeleteTarget = g;
		showGmDeleteConfirm = true;
	}

	async function gmDeleteConfirmed() {
		const g = gmDeleteTarget;
		if (!g) return;
		try {
			await api.delete(`/sales/agency-groups/${g.id}`);
			agencyGroups = await api.get('/sales/agency-groups/');
			showToast('Grup silindi', 'success');
		} catch (e) {
			console.error('Grup silme hatası:', e);
			showToast('Silme hatası', 'error');
		} finally {
			gmDeleteTarget = null;
		}
	}

	async function loadAgencyGroups() {
		try {
			agencyGroups = await api.get('/sales/agency-groups/');
		} catch (e) {
			console.error('Acente grupları yüklenemedi:', e);
		}
	}

	const WEEKDAY_LABELS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
	const TR_AY_FULL: Record<string, string> = {
		'01': 'Ocak', '02': 'Şubat', '03': 'Mart', '04': 'Nisan',
		'05': 'Mayıs', '06': 'Haziran', '07': 'Temmuz', '08': 'Ağustos',
		'09': 'Eylül', '10': 'Ekim', '11': 'Kasım', '12': 'Aralık',
	};

	// ───── Formatlama ─────────────────────────────────────
	function formatEur(n: number, withCurrency = true): string {
		if (n == null || isNaN(n)) return '-';
		const formatted = new Intl.NumberFormat('tr-TR', {
			minimumFractionDigits: 0,
			maximumFractionDigits: 0,
		}).format(Math.round(n));
		return withCurrency ? `${formatted} €` : formatted;
	}
	function formatEurCompact(n: number): string {
		if (n == null || isNaN(n)) return '-';
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} M €`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)} K €`;
		return `${Math.round(n)} €`;
	}
	function formatInt(n: number): string {
		if (n == null || isNaN(n)) return '-';
		return new Intl.NumberFormat('tr-TR').format(n);
	}
	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		const d = new Date(iso);
		return new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(d);
	}
	function monthLabel(ym: string): string {
		const [y, m] = ym.split('-');
		return `${TR_AY[m] ?? m} ${y}`;
	}

	// ───── Veri yükleme ───────────────────────────────────
	function buildQuery(year: number | 'all'): string {
		const p = new URLSearchParams();
		if (year !== 'all') {
			p.set('start_date', `${year}-01-01`);
			p.set('end_date', `${year}-12-31`);
		}
		return p.toString();
	}

	async function loadSummary() {
		try {
			const qs = buildQuery(filters.year);
			const tasks: Promise<any>[] = [
				api.get<SummaryData>(`/sales/reservations/summary${qs ? `?${qs}` : ''}`),
			];
			// Karşılaştırma açıksa ve önceki yıl mevcutsa paralel çek
			if (compareMode && canCompare && previousYearLabel !== null) {
				const prevQs = buildQuery(previousYearLabel);
				tasks.push(api.get<SummaryData>(`/sales/reservations/summary?${prevQs}`));
			}
			const results = await Promise.all(tasks);
			summary = results[0];
			previousYearSummary = results[1] ?? null;
		} catch (e) {
			console.error('Özet yüklenemedi:', e);
			if (!(e instanceof Error && e.message === 'Unauthorized')) {
				showToast('Özet yüklenemedi', 'error');
			}
		}
	}

	// ───── Karşılaştırma helper'ları ──────────────────────
	/** Yıllık % değişim — geçerli vs önceki. previous=0 ise current>0 → 100 (yeni), aksi → 0. */
	function yoyPct(current: number, previous: number): number {
		if (!previous || previous === 0) return current > 0 ? 100 : 0;
		return ((current - previous) / previous) * 100;
	}

	/** Yüzde puanı farkı (örn. doluluk %78 vs %66 → +12pt) */
	function yoyPoints(current: number, previous: number): number {
		return current - previous;
	}

	function changeColorClass(delta: number): string {
		if (delta > 0.5) return 'text-emerald-600 bg-emerald-50';
		if (delta < -0.5) return 'text-rose-600 bg-rose-50';
		return 'text-gray-500 bg-gray-50';
	}

	function changeArrow(delta: number): string {
		if (delta > 0.5) return '↑';
		if (delta < -0.5) return '↓';
		return '→';
	}

	/** Yıllık ortalama ADR — toplam ciro / toplam oda-gece. */
	function yearAdr(s: SummaryData): number {
		return s.kpi.total_room_nights > 0 ? s.kpi.total_eur / s.kpi.total_room_nights : 0;
	}

	/**
	 * Karşılaştırma açıkken her iki yılın aylarını birleştir.
	 * Geçerli yılda olmayıp önceki yılda olan ay (örn. 2025 Ocak var, 2026 Ocak yok)
	 * için "boş ay" placeholder satırı üretir — bar 0 görünür ama 2025 overlay'i çizilir.
	 */
	type MonthlyRowType = SummaryData['monthly'][number];

	function buildEmptyMonth(monthKey: string, year: number, totalCapacity: number): MonthlyRowType {
		const yr = year;
		const m = Number(monthKey);
		const daysInMonth = new Date(yr, m, 0).getDate();
		const capacity = totalCapacity * daysInMonth;
		return {
			month: `${yr}-${monthKey}`,
			rez: 0,
			room_nights: 0,
			pax: 0,
			eur: 0,
			capacity_nights: capacity,
			empty_nights: capacity,
			occupancy_pct: 0,
		};
	}

	let displayedMonthly = $derived.by<MonthlyRowType[]>(() => {
		if (!summary) return [];

		// Belirli bir yıl filtresi seçiliyse → 12 ayın tamamını garanti et.
		// Veri olmayan aylar placeholder ile çizilir (0 dolu, tam kapasite boş, %0).
		// Karşılaştırma açıkken karşı yıldaki aylar da otomatik kapsanmış olur.
		if (typeof filters.year === 'number') {
			const year = filters.year;
			const cap = summary.kpi.total_capacity
				|| (previousYearSummary?.kpi.total_capacity ?? 0);
			const currentMap = new Map(summary.monthly.map((m) => [m.month.slice(-2), m]));
			const result: MonthlyRowType[] = [];
			for (let m = 1; m <= 12; m++) {
				const key = String(m).padStart(2, '0');
				result.push(currentMap.get(key) ?? buildEmptyMonth(key, year, cap));
			}
			return result;
		}

		// "Tüm Yıllar" modu — backend'in döndürdüğü aylara güven
		if (!compareMode || !previousYearSummary) {
			return summary.monthly;
		}
		const year = new Date().getFullYear();
		const cap = summary.kpi.total_capacity || previousYearSummary.kpi.total_capacity || 0;
		const map = new Map<string, MonthlyRowType>();
		for (const m of summary.monthly) {
			map.set(m.month.slice(-2), m);
		}
		for (const pm of previousYearSummary.monthly) {
			const key = pm.month.slice(-2);
			if (!map.has(key)) {
				map.set(key, buildEmptyMonth(key, year, cap));
			}
		}
		return [...map.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([, v]) => v);
	});

	function toggleCompareMode() {
		if (!canCompare) {
			showToast('Karşılaştırma için en az 2 farklı yılda veri olmalı', 'info', 3000);
			return;
		}
		compareMode = !compareMode;
		if (!compareMode) {
			previousYearSummary = null;
		}
		loadSummary();
	}

	async function loadUploads() {
		try {
			// Mevcut yıllar — rezervasyon VERİSİNDE geçen yıllar (backend distinct).
			// Yükleme periyodunun start/end yılını kullanmak aradaki yılları atlıyordu
			// (periyot 2026→2030 → 2027/2028/2029 seçilemiyordu); artık her yıl gelir.
			const [uploadList, yearsResp] = await Promise.all([
				api.get<UploadHistory[]>('/sales/reservations/uploads'),
				api.get<{ years: number[] }>('/sales/reservations/years'),
			]);
			uploads = uploadList;
			availableYears = yearsResp.years || [];
		} catch (e) {
			console.error('Yükleme geçmişi alınamadı:', e);
		}
	}

	async function refreshAll() {
		loading = true;
		try {
			await Promise.all([loadSummary(), loadUploads()]);
		} finally {
			loading = false;
		}
	}

	// ───── Aksiyon ────────────────────────────────────────
	async function handleUpload(files: File[]) {
		if (!files.length) return;
		const file = files[0];
		uploading = true;
		try {
			const fd = new FormData();
			fd.append('file', file);
			const res = await api.upload<UploadResult>('/sales/reservations/upload', fd);
			uploadResult = res;
			showResultModal = true;
			showToast(
				`${res.new_rows} yeni · ${res.updated_rows} güncellenen rezervasyon`,
				'success',
			);
			await refreshAll();
		} catch (e) {
			if (e instanceof ApiError) {
				showToast(e.message, 'error', 5000);
			} else {
				console.error('Yükleme hatası:', e);
				showToast('Dosya yüklenemedi', 'error');
			}
		} finally {
			uploading = false;
		}
	}

	function openRemovalReview() {
		if (!uploadResult || uploadResult.removal_candidates.length === 0) return;
		removalCandidates = uploadResult.removal_candidates;
		// Varsayılan: hepsi seçili — kullanıcı istemediklerini çıkarır
		selectedRemovalIds = new Set(removalCandidates.map((c) => c.id));
		showResultModal = false;
		showRemovalModal = true;
	}

	const selectedRemovalTotalEur = $derived(
		removalCandidates
			.filter((c) => selectedRemovalIds.has(c.id))
			.reduce((sum, c) => sum + (c.eur_total || 0), 0),
	);

	async function executeBulkDelete() {
		const ids = Array.from(selectedRemovalIds);
		if (ids.length === 0) {
			showToast('Silinecek kayıt seçilmedi', 'warning');
			return;
		}
		bulkDeleting = true;
		try {
			const res = await api.post<BulkDeleteResult>('/sales/reservations/bulk-delete', { ids });
			let msg = `${res.deleted} kayıt silindi`;
			if (res.skipped > 0) {
				msg += ` · ${res.skipped} atlandı`;
			}
			showToast(msg, 'success');
			confirmBulkDelete = false;
			showRemovalModal = false;
			removalCandidates = [];
			selectedRemovalIds = new Set();
			await refreshAll();
		} catch (e) {
			if (e instanceof ApiError) {
				showToast(e.message, 'error', 5000);
			} else {
				console.error('Toplu silme hatası:', e);
				showToast('Kayıtlar silinemedi', 'error');
			}
		} finally {
			bulkDeleting = false;
		}
	}

	function formatRangeDate(iso: string): string {
		// 2026-05-16 → 16.05
		const [, m, d] = iso.split('-');
		return `${d}.${m}`;
	}

	function handleDropError(errors: string[]) {
		for (const err of errors) showToast(err, 'error', 4000);
	}

	function askDelete(u: UploadHistory) {
		confirmDelete = { show: true, id: u.id, fileName: u.file_name };
	}

	async function doDelete() {
		if (confirmDelete.id == null) return;
		try {
			await api.delete(`/sales/reservations/uploads/${confirmDelete.id}`);
			showToast('Yükleme silindi', 'success');
			await refreshAll();
		} catch (e) {
			console.error('Silme hatası:', e);
			showToast('Yükleme silinemedi', 'error');
		} finally {
			confirmDelete = { show: false, id: null, fileName: '' };
		}
	}

	function applyYearFilter(y: number | 'all') {
		filters.year = y;
		expandedMonth = null;  // Yıl değişince expand'i kapat
		dailyData = null;
		loadSummary();
	}

	// ───── Aylık Drill-Down ─────────────────────────────────
	async function toggleMonthDetail(month: string) {
		if (expandedMonth === month) {
			// Aynı aya tekrar tıklandı — kapat
			expandedMonth = null;
			dailyData = null;
			dailyDataPrev = null;
			return;
		}
		expandedMonth = month;
		dailyData = null;
		dailyDataPrev = null;
		dailyLoading = true;
		try {
			// Karşılaştırma açıksa önceki yıl aynı ay da paralel çekilir
			const [y, m] = month.split('-');
			const prevMonth = `${Number(y) - 1}-${m}`;
			const tasks: Promise<any>[] = [
				api.get<DailyOccupancy>(`/sales/reservations/daily-occupancy?month=${month}`),
			];
			if (compareMode && canCompare) {
				tasks.push(
					api.get<DailyOccupancy>(`/sales/reservations/daily-occupancy?month=${prevMonth}`)
						.catch(() => null),  // önceki yılda veri yoksa null
				);
			}
			const results = await Promise.all(tasks);
			// Hala aynı ay açıksa veri ata (hızlı tıklamada eski cevap atılır)
			if (expandedMonth === month) {
				dailyData = results[0];
				dailyDataPrev = results[1] ?? null;
			}
		} catch (e) {
			console.error('Günlük detay yüklenemedi:', e);
			showToast('Günlük detay yüklenemedi', 'error');
			expandedMonth = null;
		} finally {
			dailyLoading = false;
		}
	}

	function formatDayShort(iso: string): string {
		const d = new Date(iso);
		return new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: 'short' }).format(d);
	}

	function formatFullMonth(ym: string): string {
		const [y, m] = ym.split('-');
		return `${TR_AY_FULL[m] ?? m} ${y}`;
	}

	// ───── Lifecycle ──────────────────────────────────────
	let unsubscribe: (() => void) | null = null;

	onMount(() => {
		refreshAll();
		loadAgencyGroups();
		unsubscribe = onWsEvent('sales_updated', (data) => {
			// synthetic: WS reconnect'te store'un yerel yeniden yayını (modül bilgisi yok) —
			// toast/otomatik-açma yan etkisi olmadan yalnız sessiz reload yapılır
			// (refreshAll zaten sessizdir).
			if (data?.synthetic === true || data?.module === 'hotel_reservation') {
				refreshAll();
			}
		});
	});

	onDestroy(() => {
		if (unsubscribe) unsubscribe();
	});
</script>

<div class="space-y-6">
		<!-- ── Bölüm başlığı + Yıl Filtresi ── -->
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div>
				<h2 class="text-base font-semibold text-gray-900">Rezervasyonlar</h2>
				<p class="mt-0.5 text-xs text-gray-500">XLS yükle veya Sedna senkronu → KPI ve dağılımları gör</p>
			</div>
			<div class="flex flex-wrap items-center gap-2">
				{#if availableYears.length > 0}
					<Select
						bind:value={filters.year}
						onchange={() => applyYearFilter(filters.year)}
						aria-label="Yıl filtresi"
						size="sm"
						fullWidth={false}
					>
						<option value="all">Tüm Yıllar</option>
						{#each availableYears as y}
							<option value={y}>{y}</option>
						{/each}
					</Select>
				{/if}

				<!-- Karşılaştır toggle (önceki yıl verisi varsa aktif) -->
				<Button
					variant="secondary"
					onclick={toggleCompareMode}
					disabled={!canCompare}
					title={canCompare
						? (compareMode ? `Karşılaştırma kapalı (${previousYearLabel} ile)` : `${previousYearLabel} ile karşılaştır`)
						: 'Karşılaştırma için bir önceki yılın verisi yüklü olmalı'}
				>
					<ArrowUpDown size={16} />
					<span class="hidden sm:inline">
						{#if compareMode && canCompare && previousYearLabel !== null}
							{filters.year} ↔ {previousYearLabel}
						{:else}
							Karşılaştır
						{/if}
					</span>
				</Button>

				<Button variant="secondary" onclick={refreshAll} disabled={loading} title="Yenile" ariaLabel="Yenile">
					<RefreshCw size={16} class={loading ? 'animate-spin' : ''} />
				</Button>

				{#if uploads.length > 0}
					<Button variant="secondary" onclick={() => (showUploadsModal = true)}>
						<FileSpreadsheet size={16} />
						<span class="hidden sm:inline">Yüklemeler ({uploads.length})</span>
					</Button>
				{/if}
			</div>
		</div>

		<!-- ── Dropzone ── -->
		{#if canUse}
			<div class="relative">
				{#if uploading}
					<div class="absolute inset-0 z-10 bg-white/80 rounded-xl flex items-center justify-center">
						<div class="flex items-center gap-2 text-teal-600">
							<Loader2 size={20} class="animate-spin" />
							<span class="text-sm font-medium">XLS işleniyor...</span>
						</div>
					</div>
				{/if}
				<FileDropzone
					accept=".xls,.xlsx"
					maxSize={10 * 1024 * 1024}
					disabled={uploading}
					label="Crystal Reports XLS dosyasını sürükleyin veya tıklayın"
					hint="Sadece .xls / .xlsx · maks. 10 MB"
					onSelect={handleUpload}
					onError={handleDropError}
				/>
			</div>
		{/if}

		<!-- ── İçerik ── -->
		{#if loading && !summary}
			<TableSkeleton rows={8} columns={5} />
		{:else if summary && summary.kpi.total_rez === 0}
			<EmptyState
				icon={Upload}
				title={filters.year !== 'all' ? 'Bu dönemde rezervasyon bulunamadı' : 'Henüz veri yüklenmedi'}
				description={filters.year !== 'all'
					? `${filters.year} yılı için rezervasyon kaydı yok — farklı bir yıl seçin veya XLS yükleyin.`
					: 'XLS dosyasını sürükleyerek başlayın.'}
			/>
		{:else if summary}
			<!-- KPI Kartları -->
			{@const prev = compareMode ? previousYearSummary : null}
			{@const rezPct = prev ? yoyPct(summary.kpi.total_rez, prev.kpi.total_rez) : null}
			{@const eurPct = prev ? yoyPct(summary.kpi.total_eur, prev.kpi.total_eur) : null}
			{@const adrPct = prev ? yoyPct(summary.kpi.adr, prev.kpi.adr) : null}
			{@const rnPct = prev ? yoyPct(summary.kpi.total_room_nights, prev.kpi.total_room_nights) : null}
			{@const occDp = prev ? yoyPoints(summary.kpi.occupancy_pct, prev.kpi.occupancy_pct) : null}
			{@const paxPct = prev ? yoyPct(summary.kpi.total_pax, prev.kpi.total_pax) : null}
			{@const ltDelta = prev ? summary.lead_time.avg - prev.lead_time.avg : null}
			<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2 sm:gap-3">
				<!-- Rezervasyon -->
				<StatCard
					label="Rezervasyon"
					value={formatInt(summary.kpi.total_rez)}
					icon={FileSpreadsheet}
					accent="teal"
					hint={`Definite: ${summary.kpi.definite_count} · Option: ${summary.kpi.option_count}`}
					delta={rezPct}
					deltaText={rezPct !== null ? `${rezPct >= 0 ? '+' : ''}${rezPct.toFixed(0)}%` : undefined}
					deltaLabel={prev ? `vs ${formatInt(prev.kpi.total_rez)}` : undefined}
				/>
				<!-- Net Ciro -->
				<StatCard
					label="Net Ciro"
					value={formatEurCompact(summary.kpi.total_eur)}
					icon={Coins}
					accent="teal"
					hint={formatEur(summary.kpi.total_eur)}
					delta={eurPct}
					deltaText={eurPct !== null ? `${eurPct >= 0 ? '+' : ''}${eurPct.toFixed(0)}%` : undefined}
					deltaLabel={prev ? `vs ${formatEurCompact(prev.kpi.total_eur)}` : undefined}
				/>
				<!-- ADR -->
				<StatCard
					label="ADR"
					value={formatEur(summary.kpi.adr)}
					icon={TrendingUp}
					accent="teal"
					hint="Oda-gece başı ciro"
					delta={adrPct}
					deltaText={adrPct !== null ? `${adrPct >= 0 ? '+' : ''}${adrPct.toFixed(1)}%` : undefined}
					deltaLabel={prev ? `vs ${formatEur(prev.kpi.adr)}` : undefined}
				/>
				<!-- Oda-Gece -->
				<StatCard
					label="Oda-Gece"
					value={formatInt(summary.kpi.total_room_nights)}
					icon={Calendar}
					accent="teal"
					hint={`Ort. ${summary.kpi.avg_los.toFixed(1)} gece`}
					delta={rnPct}
					deltaText={rnPct !== null ? `${rnPct >= 0 ? '+' : ''}${rnPct.toFixed(0)}%` : undefined}
					deltaLabel={prev ? `vs ${formatInt(prev.kpi.total_room_nights)}` : undefined}
				/>
				<!-- Doluluk — pt fark (yüzde puanı) -->
				<StatCard
					label="Doluluk"
					value={`%${summary.kpi.occupancy_pct.toFixed(1)}`}
					icon={PieChart}
					accent="teal"
					hint={`${summary.kpi.total_capacity} oda × ${summary.kpi.date_range_days} gün`}
					delta={occDp}
					deltaText={occDp !== null ? `${occDp >= 0 ? '+' : ''}${occDp.toFixed(1)}pt` : undefined}
					deltaLabel={prev ? `vs %${prev.kpi.occupancy_pct.toFixed(1)}` : undefined}
				/>
				<!-- Pax -->
				<StatCard
					label="Pax"
					value={formatInt(summary.kpi.total_pax)}
					icon={Users}
					accent="gray"
					hint={`Yet ${summary.kpi.total_adult} · Çoc ${summary.kpi.total_child_paid + summary.kpi.total_child_free}`}
					delta={paxPct}
					deltaText={paxPct !== null ? `${paxPct >= 0 ? '+' : ''}${paxPct.toFixed(0)}%` : undefined}
					deltaLabel={prev ? `vs ${formatInt(prev.kpi.total_pax)}` : undefined}
				/>
				<!-- Lead Time -->
				<StatCard
					label="Rez.-Giriş Arası"
					value={`${summary.lead_time.avg.toFixed(0)} gün`}
					icon={Calendar}
					accent="gray"
					hint={`Medyan ${summary.lead_time.median} gün`}
					delta={ltDelta}
					deltaText={ltDelta !== null ? `${ltDelta >= 0 ? '+' : ''}${ltDelta.toFixed(0)} gün` : undefined}
					deltaLabel={prev ? `vs ${prev.lead_time.avg.toFixed(0)}g` : undefined}
				/>
			</div>

			<!-- ── Aylık Gece Dağılımı (stay-night attribution) ── -->
			<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
				<div class="flex items-center gap-2 mb-1">
					<Calendar size={18} class="text-teal-500" />
					<h2 class="font-semibold text-gray-900">Aylık Doluluk Dağılımı</h2>
					<span class="text-xs text-gray-500 ml-auto">Stay-night bazlı</span>
				</div>
				<p class="text-xs text-gray-500 mb-4">
					Bar genişliği doluluk yüzdesini gösterir (100% = tam kapasite). Dolu kısım teal, boş kısım gri.
					{#if compareMode && previousYearSummary && previousYearLabel !== null}
						<span class="ml-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-semibold">
							<span class="inline-block w-2.5 h-1 bg-gray-400 rounded-sm"></span>
							{previousYearLabel} ince çubuk
						</span>
					{/if}
				</p>
				{#if displayedMonthly.length === 0}
					<p class="text-sm text-gray-500 text-center py-6">Veri yok</p>
				{:else}
					{@const prevMonthMap = compareMode && previousYearSummary
						? new Map(previousYearSummary.monthly.map((pm) => [pm.month.split('-')[1], pm]))
						: null}
					<div class="space-y-2.5">
						{#each displayedMonthly as m}
							{@const monthKey = m.month.split('-')[1]}
							{@const prevM = prevMonthMap ? prevMonthMap.get(monthKey) : null}
							<div>
								<!-- Tıklanabilir bar — drill-down aç/kapat -->
								<button
									type="button"
									onclick={() => toggleMonthDetail(m.month)}
									class="w-full flex items-center gap-3 text-sm group cursor-pointer text-left hover:opacity-90 transition-opacity"
									aria-expanded={expandedMonth === m.month}
									aria-label="{monthLabel(m.month)} günlük detayı"
								>
									<div class="w-20 sm:w-24 shrink-0 text-gray-600 font-medium flex items-center gap-1">
										<span>{monthLabel(m.month)}</span>
										<ChevronRight class="w-3 h-3 text-gray-500 transition-transform {expandedMonth === m.month ? 'rotate-90' : ''}" />
									</div>
									<div class="flex-1 flex flex-col gap-0.5 min-w-0">
										<!-- Geçerli yıl bar -->
										<div class="bg-gray-100 rounded-full h-8 relative overflow-hidden ring-1 ring-transparent group-hover:ring-teal-300 transition">
											<!-- Dolu kısım: doluluk % bazlı -->
											<div
												class="h-full bg-gradient-to-r from-teal-500 to-cyan-500 rounded-full transition-all"
												style="width: {Math.min(Math.max(m.occupancy_pct, 0), 100).toFixed(1)}%"
											></div>
											<!-- Etiket: sol "X dolu" (mobilde "boş" gizli), sağ "%X" (mobilde EUR alt satıra düşer) -->
											<div class="absolute inset-0 flex items-center justify-between px-2 sm:px-3 text-xs gap-2">
												<span class="font-medium truncate min-w-0" class:text-white={m.occupancy_pct >= 25} class:text-gray-700={m.occupancy_pct < 25}>
													<span class:drop-shadow-sm={m.occupancy_pct >= 25}>
														{formatInt(m.room_nights)}<span class="opacity-75 hidden sm:inline">/{formatInt(m.capacity_nights)}</span> dolu
													</span>
													<span class="opacity-75 ml-1 hidden sm:inline">· {formatInt(m.empty_nights)} boş</span>
												</span>
												<span class="font-semibold text-gray-700 whitespace-nowrap flex items-center gap-1 sm:gap-1.5 shrink-0">
													{#if prevM}
														{@const dp = yoyPoints(m.occupancy_pct, prevM.occupancy_pct)}
														<span class="text-[10px] font-semibold px-1 rounded {changeColorClass(dp)}" title="Doluluk değişimi (yüzde puanı)">
															{changeArrow(dp)}{dp >= 0 ? '+' : ''}{dp.toFixed(0)}pt
														</span>
													{/if}
													<span class="text-teal-700 font-bold">%{m.occupancy_pct.toFixed(0)}</span>
													<span class="hidden sm:inline text-gray-500">·</span>
													{#if prevM}
														{@const ePct = yoyPct(m.eur, prevM.eur)}
														<span class="hidden sm:inline-flex text-[10px] font-semibold px-1 rounded {changeColorClass(ePct)}" title="Ciro değişimi ({previousYearLabel} aynı ay: {formatEurCompact(prevM.eur)})">
															{changeArrow(ePct)}{ePct >= 0 ? '+' : ''}{ePct.toFixed(0)}%
														</span>
													{/if}
													<span class="hidden sm:inline">{formatEurCompact(m.eur)}</span>
												</span>
											</div>
										</div>
										<!-- Mobilde bar dışında "X boş · ciro" özet satırı (sm+ desktop'ta gizli — bilgi bar içinde) -->
										<div class="flex sm:hidden items-center justify-between px-2 mt-0.5 text-[11px] text-gray-500">
											<span>{formatInt(m.empty_nights)} boş</span>
											<span class="font-semibold text-gray-700 flex items-center gap-1">
												{#if prevM}
													{@const ePctM = yoyPct(m.eur, prevM.eur)}
													<span class="text-[10px] font-semibold px-1 rounded {changeColorClass(ePctM)}">
														{changeArrow(ePctM)}{ePctM >= 0 ? '+' : ''}{ePctM.toFixed(0)}%
													</span>
												{/if}
												{formatEurCompact(m.eur)}
											</span>
										</div>
										<!-- Önceki yıl ince overlay bar + sayısal etiket satırı -->
										{#if prevM}
											<div class="bg-gray-100 rounded-full h-2 relative overflow-hidden">
												<div
													class="h-full bg-gray-400 rounded-full"
													style="width: {Math.min(Math.max(prevM.occupancy_pct, 0), 100).toFixed(1)}%"
												></div>
											</div>
											<div class="flex items-center justify-between px-2 text-[10px] text-gray-500 mt-0.5">
												<span>
													<span class="font-semibold text-gray-600">{previousYearLabel}:</span>
													{formatInt(prevM.room_nights)} dolu · %{prevM.occupancy_pct.toFixed(0)}
												</span>
												<span class="font-semibold text-gray-600">{formatEurCompact(prevM.eur)}</span>
											</div>
										{/if}
									</div>
								</button>

								<!-- Drill-down: günlük takvim heatmap -->
								{#if expandedMonth === m.month}
									<div class="mt-2 mb-3 ml-0 sm:ml-24 bg-gradient-to-br from-gray-50 to-white border border-gray-200 rounded-xl p-3 sm:p-4">
										{#if dailyLoading}
											<div class="flex items-center gap-2 text-sm text-gray-500 py-6 justify-center">
												<Loader2 size={18} class="animate-spin text-teal-500" />
												Günlük veriler yükleniyor...
											</div>
										{:else if dailyData}
											<!-- Üst özet -->
											<div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs mb-3 pb-3 border-b border-gray-200">
												<span class="font-semibold text-gray-700">
													{formatFullMonth(dailyData.month)} — Günlük Doluluk
												</span>
												<!-- Kapasite badge'i: Oda Tipleri sayfasından gelen toplam oda sayısı -->
												<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-teal-50 border border-teal-200 text-teal-800 font-semibold">
													<BedDouble class="w-3 h-3" />
													Kapasite: {dailyData.total_capacity} oda
												</span>
												<span class="text-gray-500">
													Ortalama:
													<span class="font-semibold text-teal-700">%{dailyData.avg_occupancy_pct.toFixed(1)}</span>
												</span>
												{#if dailyData.peak_date}
													<span class="text-gray-500">
														Zirve:
														<span class="font-semibold text-emerald-600">
															{formatDayShort(dailyData.peak_date)} · %{dailyData.peak_occupancy_pct.toFixed(0)}
														</span>
													</span>
												{/if}
												{#if dailyData.low_date}
													<span class="text-gray-500">
														Dip:
														<span class="font-semibold text-rose-500">
															{formatDayShort(dailyData.low_date)} · %{dailyData.low_occupancy_pct.toFixed(0)}
														</span>
													</span>
												{/if}
												{#if dailyDataPrev}
													{@const dpAvg = yoyPoints(dailyData.avg_occupancy_pct, dailyDataPrev.avg_occupancy_pct)}
													<span class="ml-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold {changeColorClass(dpAvg)}">
														{changeArrow(dpAvg)}{dpAvg >= 0 ? '+' : ''}{dpAvg.toFixed(1)}pt
														<span class="opacity-70 font-normal">vs {dailyDataPrev.month} ort %{dailyDataPrev.avg_occupancy_pct.toFixed(1)}</span>
													</span>
												{/if}
											</div>

											<!-- Günlük yatay bar listesi — aylık ile aynı stil -->
											{@const prevDayMap = compareMode && dailyDataPrev
												? new Map(dailyDataPrev.days.map((pd) => [pd.date.slice(-2), pd]))
												: null}
											<div class="space-y-1.5">
												{#each dailyData.days as day}
													{@const dateNum = Number(day.date.slice(-2))}
													{@const isWeekend = day.weekday >= 5}
													{@const prevDay = prevDayMap ? prevDayMap.get(day.date.slice(-2)) : null}
													<div class="flex items-start gap-3 text-xs">
														<!-- Sol etiket: gün + hafta günü -->
														<div class="w-16 sm:w-20 shrink-0 flex items-center gap-1.5 pt-0.5">
															<span class="font-mono font-semibold text-gray-700">{String(dateNum).padStart(2, '0')}</span>
															<span class="text-[10px] {isWeekend ? 'text-rose-500 font-semibold' : 'text-gray-500'}">
																{WEEKDAY_LABELS[day.weekday]}
															</span>
														</div>
														<!-- Bar (+ varsa karşılaştırma alt satırı) -->
														<div class="flex-1 flex flex-col gap-0.5">
															<div class="bg-gray-100 rounded-full h-6 relative overflow-hidden"
																title="{day.checkin_count > 0 ? day.checkin_count + ' giriş · ' : ''}{day.checkout_count > 0 ? day.checkout_count + ' çıkış' : ''}">
																<div
																	class="h-full rounded-full transition-all {day.occupancy_pct >= 100 ? 'bg-gradient-to-r from-rose-500 to-rose-400' : 'bg-gradient-to-r from-teal-500 to-cyan-500'}"
																	style="width: {Math.min(Math.max(day.occupancy_pct, 0), 100).toFixed(1)}%"
																></div>
																<div class="absolute inset-0 flex items-center justify-between px-2.5 gap-2">
																	<span class="font-medium whitespace-nowrap" class:text-white={day.occupancy_pct >= 25} class:text-gray-700={day.occupancy_pct < 25}>
																		<span class:drop-shadow-sm={day.occupancy_pct >= 25}>
																			{formatInt(day.room_nights)}<span class="opacity-75">/{day.capacity}</span> dolu
																		</span>
																		<span class="opacity-75 ml-1 hidden sm:inline">· {formatInt(day.empty)} boş</span>
																	</span>
																	<span class="font-semibold text-gray-700 whitespace-nowrap flex items-center gap-1.5">
																		{#if prevDay}
																			{@const dp = yoyPoints(day.occupancy_pct, prevDay.occupancy_pct)}
																			<span class="text-[10px] font-semibold px-1 rounded {changeColorClass(dp)}" title="Doluluk farkı ({prevDay.date}: %{prevDay.occupancy_pct.toFixed(1)})">
																				{changeArrow(dp)}{dp >= 0 ? '+' : ''}{dp.toFixed(0)}pt
																			</span>
																		{/if}
																		<span class="{day.occupancy_pct >= 100 ? 'text-rose-600' : 'text-teal-700'} font-bold">%{day.occupancy_pct.toFixed(0)}</span>
																		<span class="hidden md:inline text-gray-500">·</span>
																		<span class="hidden md:inline">{formatEurCompact(day.eur)}</span>
																	</span>
																</div>
															</div>
															<!-- Karşılaştırma açıkken: 2025'in aynı günü için ince bar + sayısal satır -->
															{#if prevDay}
																<div class="bg-gray-100 rounded-full h-1.5 relative overflow-hidden">
																	<div
																		class="h-full bg-gray-400 rounded-full"
																		style="width: {Math.min(Math.max(prevDay.occupancy_pct, 0), 100).toFixed(1)}%"
																	></div>
																</div>
																<div class="flex items-center justify-between px-2 text-[10px] text-gray-500 -mt-0.5">
																	<span>
																		<span class="font-semibold text-gray-600">{prevDay.date.slice(0, 7)}:</span>
																		{formatInt(prevDay.room_nights)} dolu · %{prevDay.occupancy_pct.toFixed(0)} · <Users size={11} class="inline align-text-bottom" /> {formatInt(prevDay.pax)}
																	</span>
																	<span class="font-semibold text-gray-600">{formatEurCompact(prevDay.eur)}</span>
																</div>
															{/if}
														</div>
														<!-- Sağ: O gün otelde bulunan kişi sayısı (pax) + YoY rozeti -->
														<div class="hidden md:flex w-20 shrink-0 items-center gap-1.5 text-[11px] justify-end pt-0.5">
															<span class="text-gray-700 font-semibold" title="O gün otelde konaklayan kişi sayısı">
																<Users size={12} class="inline align-text-bottom" /> {formatInt(day.pax)}
															</span>
															{#if prevDay && prevDay.pax > 0}
																{@const pct = yoyPct(day.pax, prevDay.pax)}
																<span class="text-[10px] font-semibold px-1 rounded {changeColorClass(pct)}" title="Kişi sayısı değişimi ({prevDay.date}: {formatInt(prevDay.pax)})">
																	{changeArrow(pct)}{pct >= 0 ? '+' : ''}{pct.toFixed(0)}%
																</span>
															{/if}
														</div>
													</div>
												{/each}
											</div>

											<!-- Alt özet: hafta sonu vs hafta içi karşılaştırması -->
											{@const weekdays = dailyData.days.filter(d => d.weekday < 5)}
											{@const weekends = dailyData.days.filter(d => d.weekday >= 5)}
											{@const weekdayAvg = weekdays.length ? weekdays.reduce((s, d) => s + d.occupancy_pct, 0) / weekdays.length : 0}
											{@const weekendAvg = weekends.length ? weekends.reduce((s, d) => s + d.occupancy_pct, 0) / weekends.length : 0}
											<div class="mt-3 pt-3 border-t border-gray-200 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-500">
												<span>
													Hafta içi ort:
													<span class="font-semibold text-teal-700">%{weekdayAvg.toFixed(1)}</span>
												</span>
												<span>
													Hafta sonu ort:
													<span class="font-semibold {weekendAvg > weekdayAvg ? 'text-emerald-600' : 'text-rose-500'}">%{weekendAvg.toFixed(1)}</span>
												</span>
												<span class="hidden sm:inline ml-auto">
													<span class="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-1"></span>giriş
													<span class="inline-block w-2 h-2 rounded-full bg-orange-500 ml-2 mr-1"></span>çıkış
												</span>
											</div>
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
					<!-- Aylık toplam özet -->
					<div class="mt-4 pt-3 border-t border-gray-100 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
						<span>
							Toplam kapasite:
							<span class="font-semibold text-gray-700">
								{formatInt(displayedMonthly.reduce((s, m) => s + m.capacity_nights, 0))} oda-gece
							</span>
						</span>
						<span>
							Boş:
							<span class="font-semibold text-gray-700">
								{formatInt(displayedMonthly.reduce((s, m) => s + m.empty_nights, 0))} oda-gece
							</span>
						</span>
						<span>
							Ortalama doluluk:
							<span class="font-bold text-teal-700">
								%{summary.kpi.occupancy_pct.toFixed(1)}
							</span>
						</span>
					</div>
				{/if}
			</section>

			<!-- ── Aylık ADR & Konaklama Trendi (iki grafik yan yana) ── -->
			{#if displayedMonthly.length > 0}
				{@const calcAdr = (m: { eur: number; room_nights: number }) => m.room_nights > 0 ? m.eur / m.room_nights : 0}
				{@const adrPrevMap = compareMode && previousYearSummary
					? new Map(previousYearSummary.monthly.map((pm) => [pm.month.split('-')[1], pm]))
					: null}
				{@const allAdr = [
					...displayedMonthly.map(m => calcAdr(m)),
					...(adrPrevMap ? Array.from(adrPrevMap.values()).map(pm => calcAdr(pm)) : []),
				]}
				{@const maxAdr = Math.max(...allAdr, 1)}
				{@const allPax = [
					...displayedMonthly.map(m => m.pax),
					...(adrPrevMap ? Array.from(adrPrevMap.values()).map(pm => pm.pax) : []),
				]}
				{@const maxPax = Math.max(...allPax, 1)}

				<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
					<!-- ADR (Ortalama Oda Fiyatı) -->
					<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
						<div class="flex items-center gap-2 mb-1">
							<Coins size={18} class="text-emerald-500" />
							<h2 class="font-semibold text-gray-900">Aylık ADR Trendi</h2>
							<span class="text-xs text-gray-500 ml-auto">Oda-gece başı ciro</span>
						</div>
						<p class="text-xs text-gray-500 mb-4">
							Bar genişliği o ayın ortalama oda fiyatını gösterir.
							{#if compareMode && previousYearSummary && previousYearLabel !== null}
								<span class="ml-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-semibold">
									<span class="inline-block w-2.5 h-1 bg-gray-400 rounded-sm"></span>
									{previousYearLabel} ince çubuk
								</span>
							{/if}
						</p>
						<div class="space-y-2">
							{#each displayedMonthly as m}
								{@const adr = calcAdr(m)}
								{@const monthKey = m.month.split('-')[1]}
								{@const prevM = adrPrevMap ? adrPrevMap.get(monthKey) : null}
								{@const prevAdr = prevM ? calcAdr(prevM) : null}
								<div>
									<div class="flex items-center gap-3 text-xs">
										<div class="w-16 sm:w-20 shrink-0 text-gray-600 font-medium">{monthLabel(m.month)}</div>
										<div class="flex-1 flex flex-col gap-0.5">
											<div class="bg-gray-100 rounded-full h-7 relative overflow-hidden">
												<div
													class="h-full bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full transition-all"
													style="width: {Math.max((adr / maxAdr) * 100, 2).toFixed(1)}%"
												></div>
												<div class="absolute inset-0 flex items-center justify-between px-2.5 text-xs gap-2">
													<span class="font-medium" class:text-white={adr / maxAdr >= 0.25} class:text-gray-700={adr / maxAdr < 0.25}>
														<span class:drop-shadow-sm={adr / maxAdr >= 0.25}>{formatEur(adr)}</span>
													</span>
													{#if prevAdr !== null}
														{@const pct = yoyPct(adr, prevAdr)}
														<span class="text-[10px] font-semibold px-1 rounded {changeColorClass(pct)}" title="ADR değişimi ({previousYearLabel} aynı ay: {formatEur(prevAdr)})">
															{changeArrow(pct)}{pct >= 0 ? '+' : ''}{pct.toFixed(0)}%
														</span>
													{/if}
												</div>
											</div>
											{#if prevAdr !== null && prevM}
												<div class="bg-gray-100 rounded-full h-2 relative overflow-hidden">
													<div
														class="h-full bg-gray-400 rounded-full"
														style="width: {Math.max((prevAdr / maxAdr) * 100, 1).toFixed(1)}%"
													></div>
												</div>
												<div class="text-[10px] text-gray-500 px-2 -mt-0.5">
													<span class="font-semibold text-gray-600">{previousYearLabel}:</span> {formatEur(prevAdr)}
												</div>
											{/if}
										</div>
									</div>
								</div>
							{/each}
						</div>
						<!-- Alt özet -->
						<div class="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-500 flex flex-wrap items-center justify-between gap-2">
							<span>Yıl ortalama ADR: <span class="font-bold text-emerald-700">{formatEur(yearAdr(summary))}</span></span>
							{#if compareMode && previousYearSummary}
								{@const pct = yoyPct(yearAdr(summary), yearAdr(previousYearSummary))}
								<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold {changeColorClass(pct)}">
									{changeArrow(pct)}{pct >= 0 ? '+' : ''}{pct.toFixed(1)}% vs {formatEur(yearAdr(previousYearSummary))}
								</span>
							{/if}
						</div>
					</section>

					<!-- Pax (Konaklama — kişi-gece) -->
					<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
						<div class="flex items-center gap-2 mb-1">
							<Users size={18} class="text-indigo-500" />
							<h2 class="font-semibold text-gray-900">Aylık Konaklama</h2>
							<span class="text-xs text-gray-500 ml-auto">Kişi-gece</span>
						</div>
						<p class="text-xs text-gray-500 mb-4">
							Her ay konaklayan toplam kişi sayısı (yetişkin + çocuk × gece).
							{#if compareMode && previousYearSummary && previousYearLabel !== null}
								<span class="ml-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-semibold">
									<span class="inline-block w-2.5 h-1 bg-gray-400 rounded-sm"></span>
									{previousYearLabel} ince çubuk
								</span>
							{/if}
						</p>
						<div class="space-y-2">
							{#each displayedMonthly as m}
								{@const monthKey = m.month.split('-')[1]}
								{@const prevM = adrPrevMap ? adrPrevMap.get(monthKey) : null}
								<div>
									<div class="flex items-center gap-3 text-xs">
										<div class="w-16 sm:w-20 shrink-0 text-gray-600 font-medium">{monthLabel(m.month)}</div>
										<div class="flex-1 flex flex-col gap-0.5">
											<div class="bg-gray-100 rounded-full h-7 relative overflow-hidden">
												<div
													class="h-full bg-gradient-to-r from-indigo-500 to-blue-400 rounded-full transition-all"
													style="width: {Math.max((m.pax / maxPax) * 100, 2).toFixed(1)}%"
												></div>
												<div class="absolute inset-0 flex items-center justify-between px-2.5 text-xs gap-2">
													<span class="font-medium" class:text-white={m.pax / maxPax >= 0.25} class:text-gray-700={m.pax / maxPax < 0.25}>
														<span class:drop-shadow-sm={m.pax / maxPax >= 0.25}>{formatInt(m.pax)} kişi-gece</span>
													</span>
													{#if prevM}
														{@const pct = yoyPct(m.pax, prevM.pax)}
														<span class="text-[10px] font-semibold px-1 rounded {changeColorClass(pct)}" title="Konaklama değişimi ({previousYearLabel} aynı ay: {formatInt(prevM.pax)})">
															{changeArrow(pct)}{pct >= 0 ? '+' : ''}{pct.toFixed(0)}%
														</span>
													{/if}
												</div>
											</div>
											{#if prevM}
												<div class="bg-gray-100 rounded-full h-2 relative overflow-hidden">
													<div
														class="h-full bg-gray-400 rounded-full"
														style="width: {Math.max((prevM.pax / maxPax) * 100, 1).toFixed(1)}%"
													></div>
												</div>
												<div class="text-[10px] text-gray-500 px-2 -mt-0.5">
													<span class="font-semibold text-gray-600">{previousYearLabel}:</span> {formatInt(prevM.pax)} kişi-gece
												</div>
											{/if}
										</div>
									</div>
								</div>
							{/each}
						</div>
						<!-- Alt özet -->
						<div class="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-500 flex flex-wrap items-center justify-between gap-2">
							<span>Yıl toplam: <span class="font-bold text-indigo-700">{formatInt(summary.kpi.total_guest_nights)} kişi-gece</span></span>
							{#if compareMode && previousYearSummary}
								{@const pct = yoyPct(summary.kpi.total_guest_nights, previousYearSummary.kpi.total_guest_nights)}
								<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold {changeColorClass(pct)}">
									{changeArrow(pct)}{pct >= 0 ? '+' : ''}{pct.toFixed(1)}% vs {formatInt(previousYearSummary.kpi.total_guest_nights)}
								</span>
							{/if}
						</div>
					</section>
				</div>
			{/if}

			<!-- ── Pazar & Acente (yan yana) ── -->
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
				<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
					<div class="flex items-center gap-2 mb-4">
						<Globe2 size={18} class="text-teal-500" />
						<h2 class="font-semibold text-gray-900">Pazar Dağılımı</h2>
						<span class="text-xs text-gray-500 ml-auto">Top 8</span>
					</div>
					{#if summary.by_nation.length === 0}
						<p class="text-sm text-gray-500 text-center py-6">Veri yok</p>
					{:else}
						<div class="space-y-2.5">
							{#each summary.by_nation.slice(0, 8) as n}
								<div class="flex items-center gap-3 text-sm">
									<div class="w-12 shrink-0 font-mono text-xs font-semibold text-gray-600">{n.code}</div>
									<div class="flex-1 bg-gray-100 rounded-full h-6 relative overflow-hidden">
										<div class="h-full bg-cyan-500 rounded-full" style="width: {Math.max(n.pct, 1).toFixed(1)}%"></div>
										<span class="absolute inset-0 flex items-center justify-end pr-2 text-xs font-medium text-gray-800">
											{formatEurCompact(n.eur)} ({n.pct.toFixed(1)}%)
										</span>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</section>

				<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
					<!-- Başlık + Görünüm Toggleı -->
					<div class="flex items-center gap-2 mb-4 flex-wrap">
						<Building2 size={18} class="text-teal-500 shrink-0" />
						<h2 class="font-semibold text-gray-900">Acente Dağılımı</h2>
						<span class="text-xs text-gray-500">
							{agencyViewMode === 'grouped'
								? `${groupedAgencies().length} satır (${summary.by_agency.length} acente)`
								: `Tümü (${summary.by_agency.length})`}
						</span>
						<div class="ml-auto flex items-center gap-2">
						<!-- Grup yönet butonu (can_use) -->
						{#if hasPermission('sales.acente_mahsup', 'use')}
							<button
								onclick={openGroupMgmt}
								class="flex items-center gap-1 text-xs text-gray-500 hover:text-teal-600 border border-gray-200 rounded-lg px-2 py-1.5 hover:border-teal-300 transition-colors"
								title="Grupları yönet"
							>
								<Settings2 size={13} />
								<span class="hidden sm:inline">Grupları Yönet</span>
							</button>
						{/if}
						<!-- Toggle butonu -->
						<div class="flex rounded-lg border border-gray-200 overflow-hidden text-xs font-medium">
							<button
								onclick={() => agencyViewMode = 'individual'}
								class="px-3 py-1.5 transition-colors {agencyViewMode === 'individual'
									? 'bg-teal-700 text-white'
									: 'bg-white text-gray-500 hover:bg-gray-50'}"
							>Bireysel</button>
							<button
								onclick={() => agencyViewMode = 'grouped'}
								class="px-3 py-1.5 transition-colors border-l border-gray-200 {agencyViewMode === 'grouped'
									? 'bg-teal-700 text-white'
									: 'bg-white text-gray-500 hover:bg-gray-50'}"
							>Gruplu</button>
						</div>
						</div><!-- /ml-auto wrapper -->
					</div>

					{#if summary.by_agency.length === 0}
						<p class="text-sm text-gray-500 text-center py-6">Veri yok</p>

					{:else if agencyViewMode === 'individual'}
						<!-- ── Bireysel görünüm (mevcut) ── -->
						<div class="space-y-2.5 {summary.by_agency.length > 12 ? 'max-h-[520px] overflow-y-auto pr-1' : ''}">
							{#each summary.by_agency as a}
								<div class="flex items-center gap-3 text-sm">
									<div class="w-28 sm:w-32 shrink-0 text-xs text-gray-600 truncate" title={a.name}>{a.name}</div>
									<div class="flex-1 bg-gray-100 rounded-full h-6 relative overflow-hidden">
										<div class="h-full bg-teal-500 rounded-full" style="width: {Math.max(a.pct, 1).toFixed(1)}%"></div>
										<span class="absolute inset-0 flex items-center justify-end pr-2 text-xs font-medium text-gray-800">
											{formatEurCompact(a.eur)} ({a.pct.toFixed(1)}%)
										</span>
									</div>
								</div>
							{/each}
						</div>
						<div class="mt-4 pt-3 border-t border-gray-200 flex items-center justify-between text-sm">
							<span class="font-semibold text-gray-700">Toplam ({summary.by_agency.length} acente)</span>
							<span class="font-bold text-teal-700">{formatEur(summary.by_agency.reduce((s, a) => s + a.eur, 0))}</span>
						</div>

					{:else}
						<!-- ── Gruplu görünüm ── -->
						{#if canUse}
							<p class="text-[11px] text-gray-500 mb-2 flex items-center gap-1">
								<GripVertical size={11} class="text-gray-500" />
								Acenteyi sürükleyip grup başlığına bırakarak ekleyin · gruptan çıkarmak için aşağıdaki alana bırakın
							</p>
						{/if}
						<div class="space-y-1.5 {groupedAgencies().length > 12 ? 'max-h-[520px] overflow-y-auto pr-1' : ''}">
							{#each groupedAgencies() as item}
								{#if item.type === 'group'}
									<!-- Grup satırı -->
									<div
										class="rounded-lg border overflow-hidden transition-all {dragOverGroupId === item.id ? 'border-teal-500 ring-2 ring-teal-300 bg-teal-50/60' : 'border-teal-100'}"
										ondragover={canUse ? (e) => onGroupDragOver(e, item.id) : undefined}
										ondragleave={canUse ? () => onGroupDragLeave(item.id) : undefined}
										ondrop={canUse ? (e) => onGroupDrop(e, item.id) : undefined}
										role={canUse ? 'button' : undefined}
										tabindex={canUse ? -1 : undefined}
									>
										<button
											onclick={() => toggleGroup(item.name)}
											class="w-full flex items-center gap-3 text-sm px-2 py-1.5 bg-teal-50 hover:bg-teal-100 transition-colors"
										>
											<!-- Açma/kapama oku -->
											<ChevronRight class="w-3 h-3 text-teal-600 shrink-0 transition-transform {expandedGroups.has(item.name) ? 'rotate-90' : ''}" />

											<div class="w-24 sm:w-28 shrink-0 text-xs font-semibold text-teal-800 truncate text-left" title={item.name}>
												{item.name}
												<span class="font-normal text-teal-500 ml-1">({item.members.length})</span>
											</div>
											<div class="flex-1 bg-teal-100 rounded-full h-6 relative overflow-hidden">
												<div class="h-full bg-teal-500 rounded-full" style="width: {Math.max(item.pct, 1).toFixed(1)}%"></div>
												<span class="absolute inset-0 flex items-center justify-end pr-2 text-xs font-semibold text-teal-900">
													{formatEurCompact(item.eur)} ({item.pct.toFixed(1)}%)
												</span>
											</div>
										</button>
										<!-- Üyeler (açıkken) -->
										{#if expandedGroups.has(item.name)}
											<div class="divide-y divide-gray-100 bg-white">
												{#each item.members as m}
													<div
														class="flex items-center gap-3 text-sm px-2 py-1.5 transition-opacity {draggingAgency === m.name ? 'opacity-40' : ''}"
														draggable={canUse}
														ondragstart={canUse ? (e) => onAgencyDragStart(e, m.name) : undefined}
														ondragend={canUse ? onAgencyDragEnd : undefined}
													>
														{#if canUse}
															<GripVertical size={12} class="text-gray-500 hover:text-gray-500 cursor-grab shrink-0" />
														{:else}
															<span class="w-3 shrink-0"></span>
														{/if}
														<div class="w-24 sm:w-28 shrink-0 text-xs text-gray-500 truncate pl-2" title={m.name}>{m.name}</div>
														<div class="flex-1 bg-gray-100 rounded-full h-5 relative overflow-hidden">
															<div class="h-full bg-teal-300 rounded-full" style="width: {Math.max(m.pct, 0.5).toFixed(1)}%"></div>
															<span class="absolute inset-0 flex items-center justify-end pr-2 text-xs text-gray-700">
																{formatEurCompact(m.eur)} ({m.pct.toFixed(1)}%)
															</span>
														</div>
													</div>
												{/each}
											</div>
										{/if}
									</div>
								{:else}
									<!-- Tekil acente satırı -->
									<div
										class="flex items-center gap-3 text-sm px-2 transition-opacity {draggingAgency === item.name ? 'opacity-40' : ''}"
										draggable={canUse}
										ondragstart={canUse ? (e) => onAgencyDragStart(e, item.name) : undefined}
										ondragend={canUse ? onAgencyDragEnd : undefined}
									>
										{#if canUse}
											<GripVertical size={12} class="text-gray-500 hover:text-gray-500 cursor-grab shrink-0" />
										{:else}
											<span class="w-3 shrink-0"></span>
										{/if}
										<div class="w-24 sm:w-28 shrink-0 text-xs text-gray-600 truncate" title={item.name}>{item.name}</div>
										<div class="flex-1 bg-gray-100 rounded-full h-6 relative overflow-hidden">
											<div class="h-full bg-teal-500 rounded-full" style="width: {Math.max(item.pct, 1).toFixed(1)}%"></div>
											<span class="absolute inset-0 flex items-center justify-end pr-2 text-xs font-medium text-gray-800">
												{formatEurCompact(item.eur)} ({item.pct.toFixed(1)}%)
											</span>
										</div>
									</div>
								{/if}
							{/each}
						</div>
						<!-- Gruptan çıkar drop zone — yalnızca sürükleme sırasında ve gruba ait acenteler için -->
						{#if canUse && draggingAgency && agencyToGroupId[draggingAgency]}
							<div
								ondragover={onUngroupDragOver}
								ondragleave={onUngroupDragLeave}
								ondrop={onUngroupDrop}
								class="mt-3 border-2 border-dashed rounded-lg p-3 text-center text-xs transition-colors {dragOverUngroup ? 'border-rose-400 bg-rose-50 text-rose-700' : 'border-gray-300 bg-gray-50 text-gray-500'}"
								role="button"
								tabindex="-1"
							>
								<Undo2 size={14} class="inline-block mr-1 -mt-0.5" />
								Buraya bırakırsanız <strong>{draggingAgency}</strong> gruptan çıkarılır (bireysel olur)
							</div>
						{/if}
						<!-- Toplam satırı -->
						<div class="mt-4 pt-3 border-t border-gray-200 flex items-center justify-between text-sm">
							<span class="font-semibold text-gray-700">
								Toplam ({summary.by_agency.length} acente · {agencyGroups.length} grup)
							</span>
							<span class="font-bold text-teal-700">{formatEur(summary.by_agency.reduce((s, a) => s + a.eur, 0))}</span>
						</div>
					{/if}
				</section>
			</div>

			<!-- ── Oda Tipi & Pansiyon ── -->
			<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
				<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm lg:col-span-2">
					<div class="flex items-center gap-2 mb-4">
						<PieChart size={18} class="text-teal-500" />
						<h2 class="font-semibold text-gray-900">Oda Tipi Dağılımı</h2>
					</div>
					{#if summary.by_room_type.length === 0}
						<p class="text-sm text-gray-500 text-center py-6">Veri yok</p>
					{:else}
						<div class="space-y-2.5">
							{#each summary.by_room_type as t}
								<div class="flex items-center gap-3 text-sm">
									<div class="w-24 sm:w-32 shrink-0 text-xs font-medium text-gray-700 truncate" title={t.name}>
										{t.name}
										{#if t.total_rooms > 0}
											<span class="block text-[10px] text-gray-500">{t.total_rooms} oda</span>
										{/if}
									</div>
									<div class="flex-1 bg-gray-100 rounded-full h-6 relative overflow-hidden">
										<div class="h-full bg-amber-500 rounded-full" style="width: {Math.max(t.pct, 1).toFixed(1)}%"></div>
										<span class="absolute inset-0 flex items-center justify-between px-2 text-xs">
											<span class="text-gray-600">
												{t.rez} rez
												{#if t.occupancy_pct > 0}
													<span class="ml-1 text-teal-700 font-medium">· %{t.occupancy_pct.toFixed(0)}</span>
												{/if}
											</span>
											<span class="font-semibold text-gray-800">{formatEurCompact(t.eur)} ({t.pct.toFixed(1)}%)</span>
										</span>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</section>

				<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
					<div class="flex items-center gap-2 mb-4">
						<Coins size={18} class="text-teal-500" />
						<h2 class="font-semibold text-gray-900">Pansiyon</h2>
					</div>
					{#if summary.by_board.length === 0}
						<p class="text-sm text-gray-500 text-center py-6">Veri yok</p>
					{:else}
						<div class="space-y-3">
							{#each summary.by_board as b}
								<div>
									<div class="flex items-center justify-between text-xs mb-1">
										<span class="font-medium text-gray-700">{b.name}</span>
										<span class="text-gray-500">{b.rez} rez · {b.pct.toFixed(1)}%</span>
									</div>
									<div class="bg-gray-100 rounded-full h-3 overflow-hidden">
										<div class="h-full bg-emerald-500 rounded-full" style="width: {Math.max(b.pct, 1).toFixed(1)}%"></div>
									</div>
									<div class="text-right text-xs text-gray-500 mt-0.5">{formatEur(b.eur)}</div>
								</div>
							{/each}
						</div>
					{/if}
				</section>
			</div>

			<!-- ── Pickup & LOS ── -->
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
				<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
					<div class="flex items-center gap-2 mb-4">
						<TrendingUp size={18} class="text-teal-500" />
						<h2 class="font-semibold text-gray-900">Pickup Temposu</h2>
						<span class="text-xs text-gray-500 ml-auto">Aylık rezervasyon alımı</span>
					</div>
					{#if summary.pickup.length === 0}
						<p class="text-sm text-gray-500 text-center py-6">Veri yok</p>
					{:else}
						{@const prevPickupMap = compareMode && previousYearSummary
							? new Map(previousYearSummary.pickup.map((pp) => [pp.month.split('-')[1], pp]))
							: null}
						{@const allPickupValues = [
							...summary.pickup.map(p => p.eur),
							...(prevPickupMap ? Array.from(prevPickupMap.values()).map(pp => pp.eur) : []),
						]}
						{@const maxPickup = Math.max(...allPickupValues, 1)}
						<div class="mt-3">
							<!-- Bar alanı: sabit yükseklik, bar'lar alttan büyür -->
							<div class="flex items-end gap-1 h-40">
								{#each summary.pickup as p}
									{@const monthKey = p.month.split('-')[1]}
									{@const prevP = prevPickupMap ? prevPickupMap.get(monthKey) : null}
									<div
										class="flex-1 flex items-end justify-center gap-0.5 h-full group relative"
										title="{monthLabel(p.month)}: {p.rez} rez · {formatEur(p.eur)}{prevP ? ` · önceki yıl: ${prevP.rez} rez · ${formatEur(prevP.eur)}` : ''}"
									>
										<!-- Tutar etiketi: hover'da görünür -->
										<span class="absolute -top-0.5 text-[10px] font-medium text-gray-700 opacity-0 group-hover:opacity-100 transition whitespace-nowrap pointer-events-none z-10">
											{formatEurCompact(p.eur)}{prevP ? ` / ${formatEurCompact(prevP.eur)}` : ''}
										</span>
										<!-- Mevcut yıl bar -->
										<div class="{prevP ? 'w-1/2' : 'w-full'} flex flex-col justify-end h-full">
											<div
												class="w-full bg-gradient-to-t from-cyan-500 to-teal-400 rounded-t hover:from-cyan-600 transition-all min-h-[3px]"
												style="height: {Math.max((p.eur / maxPickup) * 100, 1).toFixed(1)}%"
											></div>
										</div>
										<!-- Önceki yıl bar (karşılaştırma açıkken) -->
										{#if prevP}
											<div class="w-1/2 flex flex-col justify-end h-full">
												<div
													class="w-full bg-gray-300 rounded-t min-h-[3px]"
													style="height: {Math.max((prevP.eur / maxPickup) * 100, 1).toFixed(1)}%"
												></div>
											</div>
										{/if}
									</div>
								{/each}
							</div>
							<!-- Ay etiketleri: bar alanının dışında, ayrı satır -->
							<div class="flex gap-1 mt-2 border-t border-gray-100 pt-2">
								{#each summary.pickup as p}
									<div class="flex-1 text-[10px] sm:text-[10px] text-gray-500 truncate text-center">
										{monthLabel(p.month).slice(0, 6)}
									</div>
								{/each}
							</div>
							<!-- Toplam özeti -->
							<div class="flex items-center justify-between text-xs text-gray-500 mt-3 pt-3 border-t border-gray-100">
								<span>
									Toplam:
									<span class="font-semibold text-gray-700">
										{formatInt(summary.pickup.reduce((s, p) => s + p.rez, 0))} rez
									</span>
								</span>
								<span>
									En yüksek ay:
									<span class="font-semibold text-teal-700">
										{summary.pickup.length > 0 ? monthLabel(summary.pickup.reduce((max, p) => p.eur > max.eur ? p : max).month) : '-'}
									</span>
								</span>
							</div>
						</div>
					{/if}
				</section>

				<section class="bg-white border border-gray-200 rounded-xl p-4 sm:p-6 shadow-sm">
					<div class="flex items-center gap-2 mb-4">
						<Calendar size={18} class="text-teal-500" />
						<h2 class="font-semibold text-gray-900">Konaklama Uzunluğu</h2>
						<span class="text-xs text-gray-500 ml-auto">Gece dağılımı</span>
					</div>
					{#if summary.los_buckets.length === 0}
						<p class="text-sm text-gray-500 text-center py-6">Veri yok</p>
					{:else}
						{@const maxLos = Math.max(...summary.los_buckets.map(b => b.count))}
						<div class="space-y-1.5">
							{#each summary.los_buckets as b}
								<div class="flex items-center gap-3 text-xs">
									<div class="w-10 shrink-0 text-right font-mono text-gray-500">{b.bucket}</div>
									<div class="flex-1 bg-gray-100 rounded h-5 overflow-hidden relative">
										<div class="h-full bg-indigo-400 rounded" style="width: {(b.count / maxLos * 100).toFixed(1)}%"></div>
										<span class="absolute inset-0 flex items-center pl-2 text-[10px] font-medium text-gray-800">
											{formatInt(b.count)}
										</span>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</section>
			</div>
		{/if}
</div>

<!-- ── Yükleme Sonuç Modalı ── -->
<ResultModal
	bind:show={showResultModal}
	result={uploadResult}
	{canUse}
	onReviewRemovals={openRemovalReview}
/>

<!-- ── Silme Adayları İnceleme Modalı ── -->
<RemovalReviewModal
	bind:show={showRemovalModal}
	candidates={removalCandidates}
	bind:selectedIds={selectedRemovalIds}
	selectedTotalEur={selectedRemovalTotalEur}
	{bulkDeleting}
	onRequestDelete={() => (confirmBulkDelete = true)}
/>

<ConfirmDialog
	bind:show={confirmBulkDelete}
	title="Toplu Silme Onayı"
	message={`${selectedRemovalIds.size} rezervasyon kalıcı olarak silinecek (toplam ${formatEur(selectedRemovalTotalEur)}). Bu işlem geri alınamaz. Devam edilsin mi?`}
	confirmText="Evet, Sil"
	cancelText="Vazgeç"
	danger
	onConfirm={executeBulkDelete}
/>

<!-- ── Yüklemeler Geçmişi Modal ── -->
<UploadsHistoryModal
	bind:show={showUploadsModal}
	{uploads}
	{canUse}
	onDelete={askDelete}
/>

<!-- ── Silme Onayı ── -->
<ConfirmDialog
	bind:show={confirmDelete.show}
	title="Yüklemeyi sil"
	message={`"${confirmDelete.fileName}" yüklemesi silinecek. Rezervasyon kayıtları korunur (başka bir yükleme tarafından üzerine yazılmamışsa). Onaylıyor musunuz?`}
	confirmText="Sil"
	danger={true}
	onConfirm={doDelete}
	onCancel={() => (confirmDelete = { show: false, id: null, fileName: '' })}
/>

<!-- ══════════════════════════════════════════════════════
     Acente Grup Yönetim Modalı (Liste + Form tek modal)
     ══════════════════════════════════════════════════════ -->
<AgencyGroupModal
	bind:show={showGroupMgmtModal}
	bind:view={gmView}
	groups={agencyGroups}
	editTarget={gmEditTarget}
	bind:name={gmNewName}
	members={gmMembers}
	bind:search={gmSearch}
	suggestions={gmSuggestions}
	saving={gmSaving}
	onEditGroup={openEditGroup}
	onAskDelete={askGmDelete}
	onClose={closeGroupMgmt}
	onNewGroup={openNewGroup}
	onRemoveMember={gmRemoveMember}
	onAddMember={gmAddMember}
	onSave={gmSave}
/>

<!-- ── Grup Silme Onayı ── -->
<ConfirmDialog
	bind:show={showGmDeleteConfirm}
	title="Grubu Sil"
	message={gmDeleteTarget ? `"${gmDeleteTarget.name}" grubunu silmek istediğinize emin misiniz? Üye acenteler bireysel görünüme döner.` : ''}
	confirmText="Sil"
	cancelText="Vazgeç"
	danger
	onConfirm={gmDeleteConfirmed}
	onCancel={() => (gmDeleteTarget = null)}
/>
