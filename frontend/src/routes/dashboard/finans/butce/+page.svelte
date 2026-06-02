<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { Building2 } from 'lucide-svelte';

	// ── Türkçe ay isimleri ──
	const MONTH_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const MONTH_FULL = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	// ── State ──
	let departments = $state<any[]>([]);
	let categories = $state<any[]>([]);
	let budgets = $state<any[]>([]);
	let summary = $state<any[]>([]);
	let monthlySummary = $state<any[]>([]);
	let selectedYear = $state(new Date().getFullYear());
	let selectedDeptId = $state<number | null>(null);
	let activeTab = $state<'expense' | 'income'>('expense');
	let loading = $state(true);
	let saving = $state(false);

	let canUse = $derived(hasPermission('finance.butce', 'use'));

	// ── Ayarlar Modalları ──
	let showDeptModal = $state(false);
	let showCatModal = $state(false);
	let deptForm = $state({ name: '' });
	let editingDeptId = $state<number | null>(null);
	let catForm = $state({ name: '', type: 'expense' as 'expense' | 'income' });
	let editingCatId = $state<number | null>(null);

	// ── Yıl seçenekleri ──
	const yearOptions = [2025, 2026, 2027, 2028];

	// ── Filtrelenmiş kategoriler ──
	let filteredCategories = $derived(
		categories.filter(c => c.type === activeTab)
	);

	// ── Bütçe grid verisi: category_id -> month -> {planned, actual} ──
	let gridData = $derived(() => {
		const map: Record<number, Record<number, { planned: number; actual: number; id: number | null }>> = {};
		for (const cat of filteredCategories) {
			map[cat.id] = {};
			for (let m = 1; m <= 12; m++) {
				map[cat.id][m] = { planned: 0, actual: 0, id: null };
			}
		}
		for (const b of budgets) {
			const cat = categories.find(c => c.id === b.category_id);
			if (!cat || cat.type !== activeTab) continue;
			if (!map[b.category_id]) continue;
			map[b.category_id][b.month] = {
				planned: b.planned_amount ?? 0,
				actual: b.actual_amount ?? 0,
				id: b.id,
			};
		}
		return map;
	});

	// ── Aylık toplamlar ──
	let monthTotals = $derived(() => {
		const totals: Record<number, { planned: number; actual: number }> = {};
		for (let m = 1; m <= 12; m++) {
			totals[m] = { planned: 0, actual: 0 };
		}
		const data = gridData();
		for (const catId of Object.keys(data)) {
			for (let m = 1; m <= 12; m++) {
				totals[m].planned += data[Number(catId)][m]?.planned ?? 0;
				totals[m].actual += data[Number(catId)][m]?.actual ?? 0;
			}
		}
		return totals;
	});

	// ── Kategori yıllık toplamları ──
	function getCategoryTotal(catId: number): { planned: number; actual: number } {
		const data = gridData();
		let planned = 0, actual = 0;
		if (!data[catId]) return { planned, actual };
		for (let m = 1; m <= 12; m++) {
			planned += data[catId][m]?.planned ?? 0;
			actual += data[catId][m]?.actual ?? 0;
		}
		return { planned, actual };
	}

	// ── Genel toplam ──
	let grandTotal = $derived(() => {
		const totals = monthTotals();
		let planned = 0, actual = 0;
		for (let m = 1; m <= 12; m++) {
			planned += totals[m].planned;
			actual += totals[m].actual;
		}
		return { planned, actual };
	});

	// ── Sayı formatlama ──
	function fmt(n: number | null | undefined): string {
		if (n == null || n === 0) return '0,00';
		return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	function fmtShort(n: number): string {
		if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + 'M';
		if (Math.abs(n) >= 1_000) return (n / 1_000).toLocaleString('tr-TR', { minimumFractionDigits: 0, maximumFractionDigits: 1 }) + 'K';
		return fmt(n);
	}

	// ── Veri yükleme ──
	async function loadDepartments() {
		try {
			const res = await api.get<any>('/finance/departmanlar/');
			departments = Array.isArray(res) ? res : (res.items ?? []);
		} catch (err) {
			console.error('Departman yükleme hatası:', err);
		}
	}

	async function loadCategories() {
		try {
			const res = await api.get<any>('/finance/butce/kategoriler');
			categories = Array.isArray(res) ? res : (res.items ?? []);
		} catch (err) {
			console.error('Kategori yükleme hatası:', err);
		}
	}

	async function loadBudgets() {
		if (!selectedDeptId) return;
		try {
			const res = await api.get<any>(`/finance/butce/?year=${selectedYear}&department_id=${selectedDeptId}`);
			budgets = Array.isArray(res) ? res : (res.items ?? []);
		} catch (err) {
			console.error('Bütçe yükleme hatası:', err);
		}
	}

	async function loadSummary() {
		try {
			const res = await api.get<any>(`/finance/butce/summary?year=${selectedYear}`);
			summary = Array.isArray(res) ? res : (res.items ?? []);
		} catch (err) {
			console.error('Özet yükleme hatası:', err);
		}
	}

	async function loadMonthlySummary() {
		if (!selectedDeptId) return;
		try {
			const res = await api.get<any>(`/finance/butce/monthly-summary?year=${selectedYear}&department_id=${selectedDeptId}`);
			monthlySummary = Array.isArray(res) ? res : (res.items ?? []);
		} catch (err) {
			console.error('Aylık özet yükleme hatası:', err);
		}
	}

	async function loadAllData() {
		loading = true;
		await Promise.all([loadDepartments(), loadCategories(), loadSummary()]);
		if (selectedDeptId) {
			await Promise.all([loadBudgets(), loadMonthlySummary()]);
		}
		loading = false;
	}

	// ── Hücre kaydetme ──
	let pendingSaves = $state<Map<string, ReturnType<typeof setTimeout>>>(new Map());

	function handleCellChange(catId: number, month: number, value: string) {
		const num = parseFloat(value.replace(',', '.')) || 0;
		const data = gridData();
		if (data[catId] && data[catId][month]) {
			data[catId][month].planned = num;
		}

		const key = `${catId}-${month}`;
		const existing = pendingSaves.get(key);
		if (existing) clearTimeout(existing);

		const timer = setTimeout(() => {
			saveBudgetCell(catId, month, num);
			pendingSaves.delete(key);
		}, 800);
		pendingSaves.set(key, timer);
	}

	async function saveBudgetCell(catId: number, month: number, amount: number) {
		if (!selectedDeptId) return;
		saving = true;
		try {
			await api.post('/finance/butce/bulk', {
				items: [{
					department_id: selectedDeptId,
					category_id: catId,
					year: selectedYear,
					month: month,
					planned_amount: amount,
				}],
			});
		} catch (err) {
			console.error('Bütçe kaydetme hatası:', err);
			showToast('Bütçe kaydedilemedi', 'error');
		}
		saving = false;
	}

	function handleCellKeydown(e: KeyboardEvent, catId: number, month: number) {
		if (e.key === 'Enter') {
			(e.target as HTMLInputElement).blur();
		}
		// Tab ile sonraki aya geç (varsayılan davranış yeterli)
	}

	// ── Departman yönetimi ──
	function startEditDept(dept: any) {
		editingDeptId = dept.id;
		deptForm.name = dept.name;
	}

	function cancelEditDept() {
		editingDeptId = null;
		deptForm.name = '';
	}

	async function saveDept() {
		if (!deptForm.name.trim()) return;
		try {
			if (editingDeptId) {
				await api.patch(`/finance/departmanlar/${editingDeptId}`, { name: deptForm.name.trim() });
				showToast('Departman güncellendi', 'success');
			} else {
				await api.post('/finance/departmanlar/', { name: deptForm.name.trim() });
				showToast('Departman eklendi', 'success');
			}
			cancelEditDept();
			await loadDepartments();
			await loadSummary();
		} catch (err: any) {
			console.error('Departman kaydetme hatası:', err);
			showToast(err?.message || 'Departman kaydedilemedi', 'error');
		}
	}

	// ── Kategori yönetimi ──
	function startEditCat(cat: any) {
		editingCatId = cat.id;
		catForm.name = cat.name;
		catForm.type = cat.type;
	}

	function cancelEditCat() {
		editingCatId = null;
		catForm.name = '';
		catForm.type = 'expense';
	}

	async function saveCat() {
		if (!catForm.name.trim()) return;
		try {
			if (editingCatId) {
				await api.patch(`/finance/butce/kategoriler/${editingCatId}`, { name: catForm.name.trim(), type: catForm.type });
				showToast('Kategori güncellendi', 'success');
			} else {
				await api.post('/finance/butce/kategoriler', { name: catForm.name.trim(), type: catForm.type });
				showToast('Kategori eklendi', 'success');
			}
			cancelEditCat();
			await loadCategories();
		} catch (err: any) {
			console.error('Kategori kaydetme hatası:', err);
			showToast(err?.message || 'Kategori kaydedilemedi', 'error');
		}
	}

	async function deleteCat(catId: number) {
		if (!confirm('Bu kategoriyi silmek istediğinizden emin misiniz?')) return;
		try {
			await api.delete(`/finance/butce/kategoriler/${catId}`);
			showToast('Kategori silindi', 'success');
			await loadCategories();
		} catch (err: any) {
			console.error('Kategori silme hatası:', err);
			showToast(err?.message || 'Kategori silinemedi', 'error');
		}
	}

	// ── Departman seçimi değiştiğinde veri yükle ──
	$effect(() => {
		// selectedDeptId veya selectedYear değiştiğinde tetiklenir
		const _dept = selectedDeptId;
		const _year = selectedYear;
		if (_dept) {
			loadBudgets();
			loadMonthlySummary();
		}
		loadSummary();
	});

	// ── WebSocket ──
	let unsubFinance: (() => void) | null = null;

	onMount(async () => {
		await loadAllData();

		unsubFinance = onWsEvent('finance_updated', () => {
			loadAllData();
		});
	});

	onDestroy(() => {
		unsubFinance?.();
		// Bekleyen kayıtları iptal et
		for (const timer of pendingSaves.values()) {
			clearTimeout(timer);
		}
		pendingSaves.clear();
	});

	// ── Seçili departman bilgisi ──
	let selectedDept = $derived(departments.find(d => d.id === selectedDeptId) ?? null);
</script>

<svelte:head>
	<title>Bütçe Yönetimi - Sprenses</title>
</svelte:head>

<!-- Başlık -->
<div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
	<div>
		<h1 class="text-2xl font-semibold text-gray-900">Bütçe Yönetimi</h1>
		<p class="text-sm text-gray-500 mt-0.5">Departman bazlı bütçe planlama ve takip</p>
	</div>

	<div class="flex items-center gap-2 flex-wrap">
		<!-- Kaydetme göstergesi -->
		{#if saving}
			<span class="text-xs text-cyan-600 flex items-center gap-1">
				<svg class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
					<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
					<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
				</svg>
				Kaydediliyor...
			</span>
		{/if}

		<!-- Yıl seçici -->
		<select
			bind:value={selectedYear}
			class="text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 outline-none"
		>
			{#each yearOptions as year}
				<option value={year}>{year}</option>
			{/each}
		</select>

		<!-- Departman seçici -->
		<select
			bind:value={selectedDeptId}
			class="text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 outline-none min-w-[160px]"
		>
			<option value={null}>Tüm Departmanlar</option>
			{#each departments as dept}
				<option value={dept.id}>{dept.name}</option>
			{/each}
		</select>

		<!-- Ayarlar butonu -->
		{#if canUse}
			<div class="relative">
				<button
					onclick={() => showDeptModal = true}
					class="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"
					title="Departman & Kategori Yönetimi"
				>
					<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z" />
						<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
					</svg>
				</button>
			</div>
		{/if}
	</div>
</div>

{#if loading}
	<TableSkeleton rows={6} columns={4} />
{:else if !selectedDeptId}
	<!-- ═══ Departman Özet Kartları ═══ -->
	{#if summary.length === 0}
		<EmptyState icon={Building2} title="Henüz bütçe verisi yok" description="Bir departman seçerek bütçe planlamaya başlayın" />
	{:else}
		<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each summary as dept}
				{@const incomeVariance = (dept.total_actual_income ?? 0) - (dept.total_planned_income ?? 0)}
				{@const expenseVariance = (dept.total_actual_expense ?? 0) - (dept.total_planned_expense ?? 0)}
				{@const netPlanned = (dept.total_planned_income ?? 0) - (dept.total_planned_expense ?? 0)}
				{@const netActual = (dept.total_actual_income ?? 0) - (dept.total_actual_expense ?? 0)}
				<button
					onclick={() => selectedDeptId = dept.department_id}
					class="bg-white rounded-xl border border-gray-200 shadow-sm p-5 text-left hover:border-cyan-300 hover:shadow-md transition-all cursor-pointer"
				>
					<div class="flex items-center justify-between mb-4">
						<h3 class="text-sm font-bold text-gray-800">{dept.department_name}</h3>
						<svg class="w-4 h-4 text-gray-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
						</svg>
					</div>

					<!-- Gelir -->
					<div class="mb-3">
						<div class="flex items-center justify-between text-xs text-gray-500 mb-1">
							<span>Gelir</span>
							<span class={incomeVariance >= 0 ? 'text-green-600' : 'text-red-600'}>
								{incomeVariance >= 0 ? '+' : ''}{fmtShort(incomeVariance)}
							</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-xs text-gray-400">Planlanan</span>
							<span class="text-sm font-medium text-gray-700">{fmtShort(dept.total_planned_income ?? 0)}</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-xs text-gray-400">Gerçekleşen</span>
							<span class="text-sm font-semibold {(dept.total_actual_income ?? 0) >= (dept.total_planned_income ?? 0) ? 'text-green-600' : 'text-amber-600'}">
								{fmtShort(dept.total_actual_income ?? 0)}
							</span>
						</div>
					</div>

					<!-- Gider -->
					<div class="mb-3">
						<div class="flex items-center justify-between text-xs text-gray-500 mb-1">
							<span>Gider</span>
							<span class={expenseVariance <= 0 ? 'text-green-600' : 'text-red-600'}>
								{expenseVariance >= 0 ? '+' : ''}{fmtShort(expenseVariance)}
							</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-xs text-gray-400">Planlanan</span>
							<span class="text-sm font-medium text-gray-700">{fmtShort(dept.total_planned_expense ?? 0)}</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-xs text-gray-400">Gerçekleşen</span>
							<span class="text-sm font-semibold {(dept.total_actual_expense ?? 0) <= (dept.total_planned_expense ?? 0) ? 'text-green-600' : 'text-red-600'}">
								{fmtShort(dept.total_actual_expense ?? 0)}
							</span>
						</div>
					</div>

					<!-- Net -->
					<div class="border-t border-gray-100 pt-2">
						<div class="flex items-center justify-between">
							<span class="text-xs font-medium text-gray-500">Net Durum</span>
							<span class="text-sm font-bold {netActual >= 0 ? 'text-green-600' : 'text-red-600'}">
								{fmtShort(netActual)}
							</span>
						</div>
					</div>
				</button>
			{/each}
		</div>
	{/if}
{:else}
	<!-- ═══ Departman Detay: Bütçe Grid ═══ -->
	<div class="mb-4">
		<button
			onclick={() => selectedDeptId = null}
			class="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors cursor-pointer"
		>
			<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
			</svg>
			Tüm Departmanlar
		</button>
	</div>

	<!-- Departman başlığı + Tab -->
	<div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
		<h2 class="text-lg font-bold text-gray-800">
			{selectedDept?.name ?? 'Departman'} — {selectedYear}
		</h2>
		<div class="flex items-center bg-gray-100 rounded-lg p-0.5">
			<button
				onclick={() => activeTab = 'expense'}
				class="px-4 py-1.5 text-sm font-medium rounded-md transition-colors cursor-pointer {activeTab === 'expense' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}"
			>
				Gider
			</button>
			<button
				onclick={() => activeTab = 'income'}
				class="px-4 py-1.5 text-sm font-medium rounded-md transition-colors cursor-pointer {activeTab === 'income' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}"
			>
				Gelir
			</button>
		</div>
	</div>

	<!-- Aylık özet mini kartları -->
	{#if monthlySummary.length > 0}
		<div class="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-1.5 sm:gap-2 mb-4">
			{#each monthlySummary as ms, i}
				{@const planned = activeTab === 'expense' ? (ms.planned_expense ?? 0) : (ms.planned_income ?? 0)}
				{@const actual = activeTab === 'expense' ? (ms.actual_expense ?? 0) : (ms.actual_income ?? 0)}
				{@const isOver = activeTab === 'expense' ? actual > planned : actual < planned}
				{@const pct = planned > 0 ? Math.round((actual / planned) * 100) : 0}
				<div class="bg-white rounded-lg border {isOver && planned > 0 ? 'border-red-200' : 'border-gray-200'} p-2.5 text-center">
					<div class="text-xs font-medium text-gray-500 mb-1">{MONTH_SHORT[ms.month - 1] ?? MONTH_SHORT[i]}</div>
					<div class="text-xs text-gray-400">Plan: {fmtShort(planned)}</div>
					<div class="text-sm font-semibold {isOver && planned > 0 ? 'text-red-600' : 'text-green-600'}">{fmtShort(actual)}</div>
					{#if planned > 0}
						<div class="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
							<div
								class="h-full rounded-full transition-all {isOver ? 'bg-red-400' : 'bg-green-400'}"
								style="width: {Math.min(pct, 100)}%"
							></div>
						</div>
						<div class="text-[10px] text-gray-400 mt-0.5">%{pct}</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	<!-- Bütçe Grid Tablosu -->
	{#if filteredCategories.length === 0}
		<div class="text-center py-12 text-gray-400">
			<p class="text-base font-medium text-gray-500">
				{activeTab === 'expense' ? 'Gider' : 'Gelir'} kategorisi bulunmuyor
			</p>
			<p class="text-sm mt-1">Ayarlardan kategori ekleyerek başlayın</p>
			{#if canUse}
				<button
					onclick={() => { catForm.type = activeTab; showCatModal = true; }}
					class="mt-3 inline-flex items-center gap-1.5 text-sm text-cyan-600 hover:text-cyan-700 font-medium cursor-pointer"
				>
					<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
					</svg>
					Kategori Ekle
				</button>
			{/if}
		</div>
	{:else}
		<!-- Mobil: Kategori bazlı kart görünümü -->
		<div class="sm:hidden space-y-3 mb-4">
			{#each filteredCategories as cat (cat.id)}
				{@const catTotal = getCategoryTotal(cat.id)}
				<div class="bg-white rounded-xl border border-gray-200 shadow-sm p-3">
					<div class="flex items-center justify-between mb-2">
						<span class="text-sm font-semibold text-gray-800">{cat.name}</span>
						<div class="text-right">
							<span class="text-xs font-bold text-gray-700">{fmtShort(catTotal.planned)}</span>
							{#if catTotal.actual > 0}
								<span class="text-[10px] ml-1 {(activeTab === 'expense' ? catTotal.actual > catTotal.planned : catTotal.actual < catTotal.planned) && catTotal.planned > 0 ? 'text-red-500 font-medium' : 'text-green-600'}">
									({fmtShort(catTotal.actual)})
								</span>
							{/if}
						</div>
					</div>
					<div class="grid grid-cols-4 gap-1">
						{#each { length: 12 } as _, i}
							{@const m = i + 1}
							{@const cell = gridData()[cat.id]?.[m] ?? { planned: 0, actual: 0, id: null }}
							{@const isOverBudget = activeTab === 'expense' ? cell.actual > cell.planned && cell.planned > 0 : cell.actual < cell.planned && cell.planned > 0}
							<div class="text-center rounded p-1 {isOverBudget ? 'bg-red-50' : cell.planned > 0 ? 'bg-green-50' : 'bg-gray-50'}">
								<div class="text-[9px] text-gray-400">{MONTH_SHORT[i]}</div>
								<div class="text-[10px] font-medium text-gray-700">{cell.planned ? fmtShort(cell.planned) : '-'}</div>
								{#if cell.actual > 0}
									<div class="text-[9px] {isOverBudget ? 'text-red-500' : 'text-green-600'}">{fmtShort(cell.actual)}</div>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/each}
			<!-- Mobil toplam -->
			{#if true}
				{@const gt = grandTotal()}
				<div class="bg-gray-50 rounded-xl border border-gray-300 p-3 text-center">
					<span class="text-xs font-bold text-gray-700">TOPLAM</span>
					<span class="text-sm font-bold text-gray-800 ml-2">{fmtShort(gt.planned)}</span>
					{#if gt.actual > 0}
						<span class="text-xs ml-1 {(activeTab === 'expense' ? gt.actual > gt.planned : gt.actual < gt.planned) && gt.planned > 0 ? 'text-red-600 font-bold' : 'text-green-600'}">
							({fmtShort(gt.actual)})
						</span>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Desktop: 12 aylık tablo -->
		<div class="hidden sm:block bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="bg-gray-50 border-b border-gray-200">
							<th class="text-left text-xs font-semibold text-gray-600 px-3 py-2.5 sticky left-0 bg-gray-50 z-10 min-w-[160px]">
								Kategori
							</th>
							{#each MONTH_SHORT as month, i}
								<th class="text-center text-xs font-semibold text-gray-600 px-1.5 py-2.5 min-w-[90px]">
									{month}
								</th>
							{/each}
							<th class="text-center text-xs font-bold text-gray-700 px-2 py-2.5 min-w-[100px] bg-gray-100">
								Toplam
							</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredCategories as cat (cat.id)}
							{@const catTotal = getCategoryTotal(cat.id)}
							<tr class="border-b border-gray-100 hover:bg-gray-50/50">
								<td class="px-3 py-2 sticky left-0 bg-white z-10">
									<span class="text-xs font-medium text-gray-700">{cat.name}</span>
								</td>
								{#each { length: 12 } as _, i}
									{@const m = i + 1}
									{@const cell = gridData()[cat.id]?.[m] ?? { planned: 0, actual: 0, id: null }}
									{@const isOverBudget = activeTab === 'expense' ? cell.actual > cell.planned && cell.planned > 0 : cell.actual < cell.planned && cell.planned > 0}
									{@const isUnderBudget = activeTab === 'expense' ? cell.actual <= cell.planned && cell.planned > 0 : cell.actual >= cell.planned && cell.planned > 0}
									<td class="px-1 py-1.5 text-center {isOverBudget ? 'bg-red-50' : isUnderBudget ? 'bg-green-50' : ''}">
										{#if canUse}
											<input
												type="text"
												value={cell.planned || ''}
												onchange={(e) => handleCellChange(cat.id, m, (e.target as HTMLInputElement).value)}
												onkeydown={(e) => handleCellKeydown(e, cat.id, m)}
												class="w-full text-center text-xs px-1 py-1 border border-transparent rounded focus:border-cyan-400 focus:outline-none focus:bg-white bg-transparent hover:bg-gray-50 transition-colors"
												placeholder="0"
											/>
										{:else}
											<span class="text-xs text-gray-700">{cell.planned ? fmt(cell.planned) : '-'}</span>
										{/if}
										{#if cell.actual > 0}
											<div class="text-[10px] {isOverBudget ? 'text-red-500 font-medium' : 'text-gray-400'} mt-0.5">
												{fmtShort(cell.actual)}
											</div>
										{/if}
									</td>
								{/each}
								<!-- Kategori toplam -->
								<td class="px-2 py-1.5 text-center bg-gray-50">
									<span class="text-xs font-semibold text-gray-700">{fmtShort(catTotal.planned)}</span>
									{#if catTotal.actual > 0}
										<div class="text-[10px] {(activeTab === 'expense' ? catTotal.actual > catTotal.planned : catTotal.actual < catTotal.planned) && catTotal.planned > 0 ? 'text-red-500 font-medium' : 'text-gray-400'} mt-0.5">
											{fmtShort(catTotal.actual)}
										</div>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
					<!-- Alt toplam satırı -->
					<tfoot>
						<tr class="bg-gray-50 border-t-2 border-gray-200">
							<td class="px-3 py-2.5 sticky left-0 bg-gray-50 z-10">
								<span class="text-xs font-bold text-gray-700">TOPLAM</span>
							</td>
							{#each { length: 12 } as _, i}
								{@const m = i + 1}
								{@const t = monthTotals()[m] ?? { planned: 0, actual: 0 }}
								{@const isOver = activeTab === 'expense' ? t.actual > t.planned && t.planned > 0 : t.actual < t.planned && t.planned > 0}
								<td class="px-1 py-2.5 text-center">
									<span class="text-xs font-bold text-gray-700">{fmtShort(t.planned)}</span>
									{#if t.actual > 0}
										<div class="text-[10px] {isOver ? 'text-red-500 font-bold' : 'text-gray-500'} mt-0.5">
											{fmtShort(t.actual)}
										</div>
									{/if}
								</td>
							{/each}
							<!-- Genel toplam -->
							{#if true}
								{@const gt = grandTotal()}
								<td class="px-2 py-2.5 text-center bg-gray-100">
									<span class="text-xs font-bold text-gray-800">{fmtShort(gt.planned)}</span>
									{#if gt.actual > 0}
										<div class="text-[10px] {(activeTab === 'expense' ? gt.actual > gt.planned : gt.actual < gt.planned) && gt.planned > 0 ? 'text-red-600 font-bold' : 'text-gray-500'} mt-0.5">
											{fmtShort(gt.actual)}
										</div>
									{/if}
								</td>
							{/if}
						</tr>
					</tfoot>
				</table>
			</div>
		</div>

		<!-- Açıklama -->
		<div class="flex items-center gap-4 mt-3 text-[10px] text-gray-400">
			<div class="flex items-center gap-1">
				<div class="w-3 h-3 rounded bg-green-50 border border-green-200"></div>
				<span>Bütçe dahilinde</span>
			</div>
			<div class="flex items-center gap-1">
				<div class="w-3 h-3 rounded bg-red-50 border border-red-200"></div>
				<span>Bütçe aşımı</span>
			</div>
			<div class="flex items-center gap-1">
				<span class="text-gray-500">Üst satır:</span> Planlanan
			</div>
			<div class="flex items-center gap-1">
				<span class="text-gray-500">Alt satır:</span> Gerçekleşen
			</div>
		</div>
	{/if}
{/if}

<!-- ═══ Departman Yönetimi Modalı ═══ -->
<Modal bind:show={showDeptModal} title="Departman & Kategori Yönetimi" maxWidth="max-w-2xl">
	<div class="space-y-6">
		<!-- Departmanlar -->
		<div>
			<h3 class="text-sm font-bold text-gray-700 mb-3">Departmanlar</h3>
			<div class="space-y-2 mb-3">
				{#each departments as dept}
					<div class="flex items-center gap-2 p-2 bg-gray-50 rounded-lg">
						{#if editingDeptId === dept.id}
							<input
								type="text"
								bind:value={deptForm.name}
								class="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 outline-none"
								onkeydown={(e) => { if (e.key === 'Enter') saveDept(); if (e.key === 'Escape') cancelEditDept(); }}
							/>
							<button onclick={saveDept} class="text-xs text-cyan-600 hover:text-cyan-700 font-medium cursor-pointer">Kaydet</button>
							<button onclick={cancelEditDept} class="text-xs text-gray-500 hover:text-gray-700 cursor-pointer">İptal</button>
						{:else}
							<span class="flex-1 text-sm text-gray-700">{dept.name}</span>
							{#if canUse}
								<button onclick={() => startEditDept(dept)} class="text-xs text-gray-400 hover:text-cyan-600 cursor-pointer" title="Düzenle">
									<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
										<path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
									</svg>
								</button>
							{/if}
						{/if}
					</div>
				{/each}
			</div>
			{#if canUse}
				<div class="flex items-center gap-2">
					<input
						type="text"
						bind:value={deptForm.name}
						placeholder="Yeni departman adı"
						class="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 outline-none"
						onkeydown={(e) => { if (e.key === 'Enter' && !editingDeptId) saveDept(); }}
						disabled={editingDeptId !== null}
					/>
					<button
						onclick={saveDept}
						disabled={editingDeptId !== null || !deptForm.name.trim()}
						class="text-xs font-medium px-3 py-1.5 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
					>
						Ekle
					</button>
				</div>
			{/if}
		</div>

		<!-- Kategoriler -->
		<div>
			<div class="flex items-center justify-between mb-3">
				<h3 class="text-sm font-bold text-gray-700">Bütçe Kategorileri</h3>
				{#if canUse}
					<button
						onclick={() => showCatModal = true}
						class="text-xs text-cyan-600 hover:text-cyan-700 font-medium cursor-pointer"
					>
						+ Yeni Kategori
					</button>
				{/if}
			</div>

			<!-- Gider kategorileri -->
			<div class="mb-3">
				<span class="text-xs font-medium text-gray-500 mb-1.5 block">Gider Kategorileri</span>
				<div class="space-y-1.5">
					{#each categories.filter(c => c.type === 'expense') as cat}
						<div class="flex items-center gap-2 p-2 bg-red-50/50 rounded-lg">
							{#if editingCatId === cat.id}
								<input
									type="text"
									bind:value={catForm.name}
									class="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 outline-none"
									onkeydown={(e) => { if (e.key === 'Enter') saveCat(); if (e.key === 'Escape') cancelEditCat(); }}
								/>
								<button onclick={saveCat} class="text-xs text-cyan-600 hover:text-cyan-700 font-medium cursor-pointer">Kaydet</button>
								<button onclick={cancelEditCat} class="text-xs text-gray-500 hover:text-gray-700 cursor-pointer">İptal</button>
							{:else}
								<span class="flex-1 text-sm text-gray-700">{cat.name}</span>
								{#if canUse}
									<button onclick={() => startEditCat(cat)} class="text-xs text-gray-400 hover:text-cyan-600 cursor-pointer" title="Düzenle">
										<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
											<path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
										</svg>
									</button>
									<button onclick={() => deleteCat(cat.id)} class="text-xs text-gray-400 hover:text-red-600 cursor-pointer" title="Sil">
										<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
											<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
										</svg>
									</button>
								{/if}
							{/if}
						</div>
					{/each}
				</div>
			</div>

			<!-- Gelir kategorileri -->
			<div>
				<span class="text-xs font-medium text-gray-500 mb-1.5 block">Gelir Kategorileri</span>
				<div class="space-y-1.5">
					{#each categories.filter(c => c.type === 'income') as cat}
						<div class="flex items-center gap-2 p-2 bg-green-50/50 rounded-lg">
							{#if editingCatId === cat.id}
								<input
									type="text"
									bind:value={catForm.name}
									class="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 outline-none"
									onkeydown={(e) => { if (e.key === 'Enter') saveCat(); if (e.key === 'Escape') cancelEditCat(); }}
								/>
								<button onclick={saveCat} class="text-xs text-cyan-600 hover:text-cyan-700 font-medium cursor-pointer">Kaydet</button>
								<button onclick={cancelEditCat} class="text-xs text-gray-500 hover:text-gray-700 cursor-pointer">İptal</button>
							{:else}
								<span class="flex-1 text-sm text-gray-700">{cat.name}</span>
								{#if canUse}
									<button onclick={() => startEditCat(cat)} class="text-xs text-gray-400 hover:text-cyan-600 cursor-pointer" title="Düzenle">
										<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
											<path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
										</svg>
									</button>
									<button onclick={() => deleteCat(cat.id)} class="text-xs text-gray-400 hover:text-red-600 cursor-pointer" title="Sil">
										<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
											<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
										</svg>
									</button>
								{/if}
							{/if}
						</div>
					{/each}
				</div>
			</div>
		</div>
	</div>
</Modal>

<!-- ═══ Kategori Ekleme Modalı ═══ -->
<Modal bind:show={showCatModal} title={editingCatId ? 'Kategori Düzenle' : 'Yeni Kategori'} maxWidth="max-w-sm">
	<form onsubmit={(e) => { e.preventDefault(); saveCat(); }} class="space-y-4">
		<div>
			<label for="cat-name" class="block text-sm font-medium text-gray-700 mb-1">Kategori Adı</label>
			<input
				id="cat-name"
				type="text"
				bind:value={catForm.name}
				placeholder="Kategori adı girin"
				class="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 outline-none"
				required
			/>
		</div>
		<div>
			<span class="block text-sm font-medium text-gray-700 mb-1">Tür</span>
			<div class="flex items-center gap-3">
				<label class="flex items-center gap-1.5 cursor-pointer">
					<input type="radio" bind:group={catForm.type} value="expense" class="text-cyan-600" />
					<span class="text-sm text-gray-700">Gider</span>
				</label>
				<label class="flex items-center gap-1.5 cursor-pointer">
					<input type="radio" bind:group={catForm.type} value="income" class="text-cyan-600" />
					<span class="text-sm text-gray-700">Gelir</span>
				</label>
			</div>
		</div>
		<div class="flex justify-end gap-2 pt-2">
			<button
				type="button"
				onclick={() => { showCatModal = false; cancelEditCat(); }}
				class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 cursor-pointer"
			>
				İptal
			</button>
			<button
				type="submit"
				disabled={!catForm.name.trim()}
				class="px-4 py-2 text-sm font-medium bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
			>
				{editingCatId ? 'Güncelle' : 'Ekle'}
			</button>
		</div>
	</form>
</Modal>
