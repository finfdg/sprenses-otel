<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { formatCurrency, formatCompact } from '$lib/utils/finance';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Button from '$lib/components/Button.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import ReservationsPanel from '$lib/components/sales/ReservationsPanel.svelte';
	import DailyActivityPanel from '$lib/components/sales/DailyActivityPanel.svelte';
	import RoomTypesPanel from '$lib/components/sales/RoomTypesPanel.svelte';
	import {
		Settings2, Target, TrendingUp, LineChart, Wallet, Coins, ArrowRight, Inbox, ChevronRight
	} from 'lucide-svelte';

	// ── Sabitler ─────────────────────────────────────────────
	// Birleşik satış sayfası (2026-07-09): eski Otel Rezervasyon, Günlük Hareketler ve
	// Oda Tipleri modülleri bu sayfanın sekmeleri oldu (izin: sales.acente_mahsup).
	const TABS = [
		{ value: 'ozet', label: 'Genel Bakış' },
		{ value: 'rezervasyon', label: 'Rezervasyonlar' },
		{ value: 'hareket', label: 'Günlük Hareketler' },
		{ value: 'ciro', label: 'Rezervasyon & Ciro' },
		{ value: 'avans', label: 'Alınan Avanslar' },
		{ value: 'fatura', label: 'Satış Faturaları' },
		{ value: 'nakit', label: 'Nakit Akım' },
		{ value: 'oda', label: 'Oda Tipleri' },
	];
	// Projeksiyon gövdesi (senaryo barı + KPI + tablolar) yalnız bu sekmelerde görünür;
	// diğerleri kendi panel bileşenini (keep-alive) render eder.
	const PROJECTION_TABS = ['ozet', 'ciro', 'avans', 'fatura', 'nakit'];
	const STORAGE_KEY = 'acente_mahsup_scenario_v1';
	const NOW_YEAR = new Date().getFullYear();
	const YEARS = [NOW_YEAR - 1, NOW_YEAR, NOW_YEAR + 1];
	const STATUS_META: Record<string, { label: string; cls: string }> = {
		collected: { label: 'Tahsil edildi', cls: 'bg-emerald-50 text-emerald-700' },
		pending: { label: 'Bekliyor', cls: 'bg-amber-50 text-amber-700' },
		planned: { label: 'Planlandı', cls: 'bg-gray-100 text-gray-600' },
		mahsup: { label: 'Mahsup edildi', cls: 'bg-teal-50 text-teal-700' },
	};
	// Acente × Durum kırılımı — granülerlik seçenekleri
	const GRAN_OPTS = [
		{ value: 'day', label: 'Günlük' },
		{ value: 'month', label: 'Aylık' },
		{ value: 'year', label: 'Yıllık' },
	];
	const RANK_OPTS = [
		{ value: 'count', label: 'Rezervasyon' },
		{ value: 'amount', label: 'Ciro' },
	];
	const MONTH_NUMS = Array.from({ length: 12 }, (_, i) => i + 1);

	// ── Türetilmiş ───────────────────────────────────────────
	let canConfig = $derived(hasPermission('sales.acente_mahsup', 'use'));

	// ── State ────────────────────────────────────────────────
	let loading = $state(true);
	let data = $state<any>(null);
	let activeTab = $state('ozet');
	// Panel sekmeleri tembel mount edilir, ziyaret edilince mount kalır (state korunur)
	let visitedTabs = $state(new Set<string>());
	let isProjectionTab = $derived(PROJECTION_TABS.includes(activeTab));

	function selectTab(v: string) {
		activeTab = v;
		if (!PROJECTION_TABS.includes(v) && !visitedTabs.has(v)) {
			visitedTabs = new Set([...visitedTabs, v]);
		}
		// Deep-link: ?tab= parametresini güncelle (sayfa yeniden yüklenmeden)
		try {
			const url = new URL(window.location.href);
			if (v === 'ozet') url.searchParams.delete('tab');
			else url.searchParams.set('tab', v);
			replaceState(url, {});
		} catch (e) {
			console.error('Sekme URL güncellenemedi:', e);
		}
	}
	let year = $state(NOW_YEAR);
	let target = $state<number | null>(null);
	let openingCash = $state<number | null>(0);
	let ready = false;
	let reloadTimer: ReturnType<typeof setTimeout> | undefined;

	// Ayarlar modalı
	let showSettings = $state(false);
	let groups = $state<any[]>([]);
	let groupsLoading = $state(false);
	let savingId = $state<number | null>(null);

	// Acente × Durum kırılımı (Rezervasyon & Ciro sekmesi)
	let stGran = $state('month');
	let stRankBy = $state('count'); // top-N sıralama ölçütü: 'count' (rezervasyon) | 'amount' (ciro)
	let stMonth = $state(new Date().getMonth() + 1);
	let stFilter = $state(''); // '' = tümü · 'g:<id>' = grup (0=Diğer) · 'a:<ad>' = bireysel acente
	let stTrail = $state<{ value: string; label: string }[]>([]); // drill-down breadcrumb yolu
	let statusData = $state<any>(null);
	let statusLoading = $state(false);

	// ── Formatlama ───────────────────────────────────────────
	const eur = (n: number) => formatCurrency(n || 0, 'EUR');
	const eurC = (n: number) => formatCompact(n || 0, 'EUR');
	const pct = (n: number) => (n || 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + '%';
	const monthTr = (m: number) => ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'][m - 1] ?? '';
	const cnt = (n: number) => (n || 0).toLocaleString('tr-TR');

	// ── Veri ─────────────────────────────────────────────────
	async function load() {
		loading = true;
		try {
			let q = `year=${year}&opening_cash=${openingCash || 0}`;
			if (target != null) q += `&year_target=${target}`;
			data = await api.get<any>(`/sales/acente-mahsup/?${q}`);
		} catch (e) {
			console.error('Acente mahsup projeksiyonu yüklenemedi:', e);
			showToast('Projeksiyon yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	async function loadStatus() {
		statusLoading = true;
		try {
			let q = `granularity=${stGran}&year=${year}&rank_by=${stRankBy}`;
			if (stGran === 'day') q += `&month=${stMonth}`;
			if (stFilter.startsWith('g:')) q += `&group_id=${stFilter.slice(2)}`;
			else if (stFilter.startsWith('a:')) q += `&agency=${encodeURIComponent(stFilter.slice(2))}`;
			statusData = await api.get<any>(`/sales/acente-mahsup/agency-status?${q}`);
		} catch (e) {
			console.error('Acente durum kırılımı yüklenemedi:', e);
			showToast('Durum kırılımı yüklenemedi', 'error');
		} finally {
			statusLoading = false;
		}
	}

	// Tabloda satıra tıklayarak filtrele (drill-down): grup/Diğer → üyeleri, üye → tek acente
	function drillRow(row: any) {
		if (row.id != null) {
			stTrail = [{ value: 'g:' + row.id, label: row.name }]; // grup/Diğer → kökten yeni yol
		} else {
			stTrail = [...stTrail, { value: 'a:' + row.name, label: row.name }]; // bireysel → yola ekle
		}
		stFilter = stTrail[stTrail.length - 1].value;
	}
	function gotoCrumb(i: number) {
		if (i < 0) { stTrail = []; stFilter = ''; return; } // "Tüm acenteler" köküne dön
		stTrail = stTrail.slice(0, i + 1);
		stFilter = stTrail[i].value;
	}
	function rowClickable(row: any): boolean {
		return row.id != null || stFilter !== 'a:' + row.name; // grup her zaman, bireysel yalnız aktif değilse
	}

	function persist() {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify({ year, target, openingCash }));
		} catch (e) {
			console.error('Senaryo kaydedilemedi:', e);
		}
	}

	// Senaryo değişince (yıl/hedef/açılış) debounce ile yeniden yükle
	$effect(() => {
		const _y = year, _t = target, _o = openingCash;
		if (!ready) return;
		persist();
		clearTimeout(reloadTimer);
		reloadTimer = setTimeout(load, 400);
	});

	// Rezervasyon & Ciro sekmesi açıkken acente × durum kırılımını yükle
	// (granülerlik / ay / yıl değişince yeniden çeker)
	$effect(() => {
		const _tab = activeTab, _g = stGran, _m = stMonth, _y = year, _f = stFilter, _r = stRankBy;
		if (_tab !== 'ciro') return;
		loadStatus();
	});

	// ── Ayarlar (vade + kickback) ────────────────────────────
	async function openSettings() {
		showSettings = true;
		groupsLoading = true;
		try {
			const rows = await api.get<any[]>('/sales/agency-groups/');
			groups = rows.map((g) => ({ ...g, kickback_percent: Number(g.kickback_percent) || 0 }));
		} catch (e) {
			console.error('Acente grupları yüklenemedi:', e);
			showToast('Acente grupları yüklenemedi', 'error');
		} finally {
			groupsLoading = false;
		}
	}

	async function saveGroup(g: any) {
		savingId = g.id;
		try {
			await api.patch(`/sales/agency-groups/${g.id}`, {
				term_days: Math.round(g.term_days),
				kickback_percent: g.kickback_percent ?? 0,
			});
			showToast(`${g.name} ayarları kaydedildi`, 'success');
			load();
		} catch (e) {
			console.error('Ayar kaydedilemedi:', e);
			showToast('Ayar kaydedilemedi', 'error');
		} finally {
			savingId = null;
		}
	}

	// ── Yaşam döngüsü ────────────────────────────────────────
	onMount(async () => {
		// Deep-link: ?tab=rezervasyon vb. ile doğrudan sekme açılır
		try {
			const wanted = new URL(window.location.href).searchParams.get('tab');
			if (wanted && TABS.some((t) => t.value === wanted)) selectTab(wanted);
		} catch (e) {
			console.error('Sekme parametresi okunamadı:', e);
		}
		try {
			const saved = localStorage.getItem(STORAGE_KEY);
			if (saved) {
				const s = JSON.parse(saved);
				if (YEARS.includes(s.year)) year = s.year;
				if (typeof s.target === 'number') target = s.target;
				if (typeof s.openingCash === 'number') openingCash = s.openingCash;
			}
		} catch (e) {
			console.error('Senaryo okunamadı:', e);
		}
		await load();
		ready = true;
	});

	// ── Görsel yardımcılar ───────────────────────────────────
	let statusMax = $derived(
		statusData ? Math.max(1, ...statusData.periods.map((p: any) => p.total_amount)) : 1
	);
	// Günlük görünümde barlar oda kapasitesi (341) üzerinden doluluk gösterir;
	// diğer görünümlerde tutara (statusMax) göre orantılıdır.
	let stIsDaily = $derived(statusData?.granularity === 'day');
	let roomCap = $derived(Math.max(1, statusData?.room_capacity || 1));
	// Runway grafiği için SVG nokta dizisi
	let chartGeo = $derived.by(() => {
		if (!data) return null;
		const b: number[] = data.cashflow.chart.balances;
		if (b.length < 2) return null;
		const W = 620, H = 96, pad = 12;
		const max = Math.max(...b), min = Math.min(...b), range = max - min || 1;
		const pts = b.map((v, i) => {
			const x = (i / (b.length - 1)) * W;
			const y = H - pad - ((v - min) / range) * (H - 2 * pad);
			return [x, y];
		});
		const line = pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
		const area = `M${pts.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' L')} L${W} ${H} L0 ${H} Z`;
		const mi = data.cashflow.chart.min_index;
		return { line, area, mx: pts[mi]?.[0].toFixed(1), my: pts[mi]?.[1].toFixed(1), labels: data.cashflow.chart.labels };
	});
</script>

<svelte:head><title>Acente Mahsup & Nakit Akım · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader
		title="Acente Mahsup & Nakit Akım"
		description="Satış — rezervasyonlar, günlük hareketler, oda tipleri ve acente mahsup / vadeli tahsilat projeksiyonu (EUR)"
	>
		{#snippet actions()}
			{#if canConfig}
				<Button variant="secondary" onclick={openSettings}>
					<Settings2 class="h-4 w-4" /> Acente Ayarları
				</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<!-- Sekmeler (her zaman görünür; dar ekranda yatay kaydırma) -->
	<div class="overflow-x-auto">
		<SegmentedControl options={TABS} value={activeTab} onchange={selectTab} ariaLabel="Sekmeler" class="min-w-max" />
	</div>

	{#if isProjectionTab}
	<!-- Senaryo barı -->
	<div class="flex flex-wrap items-end gap-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
		<label class="flex flex-col gap-1 text-sm">
			<span class="text-gray-600">Yıl</span>
			<select
				bind:value={year}
				class="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
				aria-label="Projeksiyon yılı"
			>
				{#each YEARS as y}<option value={y}>{y}</option>{/each}
			</select>
		</label>
		<div class="flex flex-col gap-1 text-sm">
			<span class="text-gray-600">Yıl Sonu Ciro Hedefi</span>
			<div class="w-48">
				<MoneyInput bind:value={target} currency="EUR" min={0} placeholder="Gerçekleşen kadar" />
			</div>
		</div>
		<div class="flex flex-col gap-1 text-sm">
			<span class="text-gray-600">Açılış Nakit (avanslar dahil)</span>
			<div class="w-48">
				<MoneyInput bind:value={openingCash} currency="EUR" min={0} placeholder="0,00" />
			</div>
		</div>
		{#if data}
			<div class="ml-auto text-xs text-gray-500">
				Güncel EUR kuru: <span class="tabular-nums">{data.eur_rate?.toLocaleString('tr-TR')} ₺</span>
			</div>
		{/if}
	</div>

	{#if loading && !data}
		<TableSkeleton rows={6} columns={5} />
	{:else if data}
		<!-- KPI kartları -->
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
			<StatCard icon={Target} accent="teal" label="Yıl Sonu Ciro Hedefi" value={eurC(data.kpi.grand_total)} hint="rezervasyon → fatura" />
			<StatCard icon={TrendingUp} accent="emerald" label="Gerçekleşen" value={eurC(data.kpi.realized)} hint="{pct(data.kpi.realized_pct)} · tamamlanan çıkışlar" />
			<StatCard icon={LineChart} accent="blue" label="Tahmini (kalan)" value={eurC(data.kpi.forecast)} hint="{pct(data.kpi.forecast_pct)} · ileri + hedef" />
			<StatCard icon={Wallet} accent="teal" label="Alınan Avans" value={eurC(data.kpi.advance_received)} hint="mahsup: {eurC(data.kpi.advance_applied)}" />
			<StatCard icon={Coins} accent="amber" label="Yıl Sonu Kickback" value={eurC(data.kpi.kickback_total)} hint="acenteye ciro primi" />
		</div>

		<!-- ═══════════ GENEL BAKIŞ ═══════════ -->
		{#if activeTab === 'ozet'}
			<!-- Funnel -->
			<div class="flex flex-wrap items-stretch gap-2">
				{#each [
					{ label: 'Yıllık Ciro', val: data.funnel.revenue, accent: 'text-emerald-700', arrow: true },
					{ label: 'Kesilen Fatura', val: data.funnel.invoiced, accent: 'text-gray-900', arrow: true },
					{ label: 'Avans Mahsubu', val: -data.funnel.advance_offset, accent: 'text-teal-700', arrow: true },
					{ label: 'Net Tahsilat', val: data.funnel.net_collection, accent: 'text-teal-800', arrow: true },
					{ label: 'Yıl Sonu Kickback', val: -data.funnel.kickback, accent: 'text-amber-700', arrow: false },
				] as f}
					<div class="flex min-w-[150px] flex-1 items-center">
						<div class="flex-1 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
							<div class="text-[11px] uppercase tracking-wide text-gray-500">{f.label}</div>
							<div class="mt-1 text-lg font-semibold tabular-nums {f.accent}">{eurC(f.val)}</div>
						</div>
						{#if f.arrow}<ArrowRight class="mx-1 h-4 w-4 shrink-0 text-gray-300" />{/if}
					</div>
				{/each}
			</div>

			<!-- Hedef ilerleme -->
			<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
				<div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
					<h2 class="text-base font-semibold">Yıl Sonu Ciro Hedefine İlerleme</h2>
					<div class="text-sm text-gray-500">
						Gerçekleşen <span class="font-semibold tabular-nums text-emerald-700">{eurC(data.kpi.realized)}</span>
						· Tahmini <span class="font-semibold tabular-nums text-brass-dark">{eurC(data.kpi.forecast)}</span>
					</div>
				</div>
				<div class="flex h-8 overflow-hidden rounded-lg bg-gray-100">
					<div class="flex items-center bg-teal-700 pl-3 text-xs font-semibold text-white" style="width:{data.kpi.realized_pct}%">
						{#if data.kpi.realized_pct > 12}Gerçekleşen{/if}
					</div>
					<div class="flex items-center pl-3 text-xs font-semibold text-teal-900"
						style="width:{data.kpi.forecast_pct}%;background:repeating-linear-gradient(45deg,#bd9a45,#bd9a45 8px,#c9aa5c 8px,#c9aa5c 16px)">
						{#if data.kpi.forecast_pct > 14}Tahmini{/if}
					</div>
				</div>
				<div class="mt-1.5 flex justify-between text-[11px] tabular-nums text-gray-400">
					<span>€0</span><span>Hedef {eurC(data.kpi.grand_total)}</span>
				</div>
			</div>

			<!-- Acente tablosu -->
			<div class="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
				<div class="overflow-x-auto">
					<table class="w-full min-w-[720px] text-sm">
						<thead>
							<tr class="border-b-2 border-teal-700 text-left text-[11px] uppercase tracking-wide text-gray-500">
								<th class="px-4 py-3 font-semibold">Acente</th>
								<th class="px-4 py-3 text-right font-semibold">Pay</th>
								<th class="px-4 py-3 text-right font-semibold">Yıllık Ciro</th>
								<th class="px-4 py-3 text-right font-semibold">Vade</th>
								<th class="px-4 py-3 text-right font-semibold">Alınan Avans</th>
								<th class="px-4 py-3 text-right font-semibold">Kickback</th>
							</tr>
						</thead>
						<tbody>
							{#each data.agencies as a}
								<tr class="border-b border-gray-100">
									<td class="px-4 py-3">
										<span class="flex items-center gap-2 font-medium">
											<span class="h-2.5 w-2.5 shrink-0 rounded-sm" style="background:{a.color}"></span>{a.name}
										</span>
									</td>
									<td class="px-4 py-3 text-right tabular-nums text-gray-600">{pct(a.share_pct)}</td>
									<td class="px-4 py-3 text-right font-semibold tabular-nums">{eurC(a.revenue)}</td>
									<td class="px-4 py-3 text-right tabular-nums text-gray-600">{a.term_days === 0 ? 'Peşin' : a.term_days + ' gün'}</td>
									<td class="px-4 py-3 text-right tabular-nums {a.advance_received > 0 ? 'text-teal-700' : 'text-gray-300'}">{a.advance_received > 0 ? eurC(a.advance_received) : '—'}</td>
									<td class="px-4 py-3 text-right tabular-nums {a.kickback > 0 ? 'text-amber-700' : 'text-gray-300'}">{a.kickback > 0 ? '−' + eurC(a.kickback) : '—'}</td>
								</tr>
							{/each}
							<tr class="bg-gray-50 font-semibold">
								<td class="px-4 py-3">Toplam</td>
								<td></td>
								<td class="px-4 py-3 text-right tabular-nums">{eurC(data.kpi.grand_total)}</td>
								<td></td>
								<td class="px-4 py-3 text-right tabular-nums text-teal-700">{eurC(data.kpi.advance_received)}</td>
								<td class="px-4 py-3 text-right tabular-nums text-amber-700">{data.kpi.kickback_total > 0 ? '−' + eurC(data.kpi.kickback_total) : '—'}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
			{#if data.kpi.kickback_total === 0 && canConfig}
				<p class="text-xs text-gray-500">İpucu: <button class="font-medium text-teal-700 underline" onclick={openSettings}>Acente Ayarları</button>'ndan her acente için kickback oranı ve vade tanımlayabilirsiniz.</p>
			{/if}

		<!-- ═══════════ ALINAN AVANSLAR ═══════════ -->
		{:else if activeTab === 'avans'}
			<div class="grid gap-3 sm:grid-cols-3">
				<StatCard accent="teal" label="Toplam Alınan Avans" value={eur(data.advances.total_received)} hint="bilançoda yükümlülük · nakde alındı" />
				<StatCard accent="emerald" label="Faturayla Mahsup Edilen" value={eur(data.advances.total_applied)} hint="konaklama tamamlandıkça" />
				<StatCard accent="amber" label="Mahsup Bekleyen" value={eur(data.advances.total_remaining)} hint="gelecek konaklamalara mahsup" />
			</div>
			{#if data.advances.rows.length === 0}
				<EmptyState icon={Inbox} title="Alınan avans yok" description="Bu acentelerde kayıtlı avans bulunmuyor." />
			{:else}
				<div class="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
					<div class="overflow-x-auto">
						<table class="w-full min-w-[640px] text-sm">
							<thead>
								<tr class="border-b-2 border-teal-700 text-left text-[11px] uppercase tracking-wide text-gray-500">
									<th class="px-4 py-3 font-semibold">Acente</th>
									<th class="px-4 py-3 text-right font-semibold">Alınan</th>
									<th class="px-4 py-3 text-right font-semibold">Kalan</th>
									<th class="px-4 py-3 font-semibold">Mahsup Durumu</th>
								</tr>
							</thead>
							<tbody>
								{#each data.advances.rows as v}
									<tr class="border-b border-gray-100">
										<td class="px-4 py-3">
											<span class="flex items-center gap-2 font-medium">
												<span class="h-2.5 w-2.5 shrink-0 rounded-sm" style="background:{v.color}"></span>{v.agency}
											</span>
										</td>
										<td class="px-4 py-3 text-right font-semibold tabular-nums text-teal-700">{eur(v.received)}</td>
										<td class="px-4 py-3 text-right tabular-nums {v.remaining > 0 ? 'text-brass-dark' : 'text-emerald-700'}">{v.remaining > 0 ? eur(v.remaining) : 'Tamamlandı'}</td>
										<td class="px-4 py-3">
											<div class="flex items-center gap-2">
												<div class="h-2 flex-1 overflow-hidden rounded-full bg-gray-100">
													<div class="h-full rounded-full bg-emerald-500" style="width:{v.pct}%"></div>
												</div>
												<span class="w-10 shrink-0 text-right text-xs tabular-nums text-gray-600">{pct(v.pct)}</span>
											</div>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
				<p class="text-xs leading-relaxed text-gray-500">
					Avanslar acenteyle görüşmeye istinaden alınan depozitlerdir. Konaklama tamamlanıp fatura kesildikçe ilgili avans mahsup edilir; mahsup edilen tutar tekrar tahsil edilmez.
				</p>
			{/if}

		<!-- ═══════════ REZERVASYON & CİRO ═══════════ -->
		{:else if activeTab === 'ciro'}
			<!-- Acente x Durum kırılımı (gelen / içeride / çıkış) -->
			<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
				<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
					<div>
						<h2 class="text-base font-semibold">Acente × Durum Kırılımı</h2>
						<p class="mt-0.5 text-xs text-gray-500">Gelen, içeride ve çıkış yapan rezervasyonlar — acente bazında tutar (EUR) + adet</p>
					</div>
					<div class="flex flex-wrap items-center gap-2">
						{#if stGran === 'day'}
							<select
								bind:value={stMonth}
								class="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm focus:ring-2 focus:ring-teal-500"
								aria-label="Ay"
							>
								{#each MONTH_NUMS as mm}<option value={mm}>{monthTr(mm)}</option>{/each}
							</select>
						{/if}
						<div class="flex items-center gap-1.5">
							<span class="hidden text-xs font-medium text-gray-500 sm:inline">Sırala:</span>
							<div class="w-44">
								<SegmentedControl options={RANK_OPTS} value={stRankBy} onchange={(v) => (stRankBy = v)} ariaLabel="Sıralama ölçütü" />
							</div>
						</div>
						<div class="w-56">
							<SegmentedControl options={GRAN_OPTS} value={stGran} onchange={(v) => (stGran = v)} ariaLabel="Granülerlik" />
						</div>
					</div>
				</div>

				{#if stTrail.length}
					<nav class="mb-3 flex flex-wrap items-center gap-1.5 text-sm" aria-label="Acente kırılımı yolu">
						<button class="font-medium text-teal-700 hover:underline" onclick={() => gotoCrumb(-1)}>Tüm acenteler</button>
						{#each stTrail as c, i}
							<ChevronRight class="h-3.5 w-3.5 text-gray-400" />
							{#if i < stTrail.length - 1}
								<button class="font-medium text-teal-700 hover:underline" onclick={() => gotoCrumb(i)}>{c.label}</button>
							{:else}
								<span class="font-semibold text-gray-800">{c.label}</span>
							{/if}
						{/each}
					</nav>
				{/if}

				{#if statusData}
					<div class="mb-3 flex flex-wrap gap-4 text-xs text-gray-600">
						{#each statusData.statuses as s}
							<span class="flex items-center gap-1.5"><span class="h-3 w-3 rounded-sm" style="background:{s.color}"></span>{s.label}</span>
						{/each}
					</div>
				{/if}

				{#if statusLoading && !statusData}
					<TableSkeleton rows={6} columns={4} />
				{:else if statusData && statusData.grand_count === 0}
					<EmptyState icon={Inbox} title="Kayıt yok" description="Seçili dönemde bu durumlarda rezervasyon bulunmuyor." />
				{:else if statusData}
					<!-- Grafik: dönem bazında yığılı çubuk. Günlük görünümde bar = dolu oda-gece / oda
					     kapasitesi (doluluk); diğer görünümlerde tutara orantılı. -->
					{#if stIsDaily}
						<p class="mb-2 text-[11px] text-gray-500">Barlar günlük doluluğu <strong>{roomCap} oda</strong> kapasitesi üzerinden gösterir; renkler rezervasyon durumudur.</p>
					{/if}
					<div class="space-y-1">
						{#each statusData.periods as p}
							<div class="flex items-center gap-3 py-0.5">
								<div class="w-9 shrink-0 text-xs font-medium text-gray-600">{p.label}</div>
								<div class="flex h-5 flex-1 overflow-hidden rounded-md bg-gray-100">
									{#each statusData.statuses as s}
										{#if stIsDaily ? p.statuses[s.key].rooms > 0 : p.statuses[s.key].amount > 0}
											<div class="h-full"
												style="width:{stIsDaily ? (p.statuses[s.key].rooms / roomCap) * 100 : (p.statuses[s.key].amount / statusMax) * 100}%;background:{s.color}"
												title="{s.label}: {stIsDaily ? cnt(p.statuses[s.key].rooms) + ' oda' : eurC(p.statuses[s.key].amount)} · {cnt(p.statuses[s.key].count)} rez."></div>
										{/if}
									{/each}
								</div>
								<div class="w-24 shrink-0 text-right text-xs font-semibold tabular-nums text-teal-800">{eurC(p.total_amount)}</div>
								{#if stIsDaily}
									<div class="hidden w-20 shrink-0 text-right text-[11px] text-gray-500 sm:block">{cnt(p.total_rooms)}/{roomCap} oda</div>
								{:else}
									<div class="hidden w-16 shrink-0 text-right text-[11px] text-gray-500 sm:block">{cnt(p.total_count)} rez.</div>
								{/if}
							</div>
						{/each}
					</div>

					<!-- Acente tablosu (durum kolonları) -->
					<div class="mt-5 overflow-hidden rounded-xl border border-gray-200">
						<div class="overflow-x-auto">
							<table class="w-full min-w-[640px] text-sm">
								<thead>
									<tr class="border-b-2 border-teal-700 text-left text-[11px] uppercase tracking-wide text-gray-500">
										<th class="px-4 py-3 font-semibold">Acente</th>
										{#each statusData.statuses as s}
											<th class="px-4 py-3 text-right font-semibold">{s.label}</th>
										{/each}
										<th class="px-4 py-3 text-right font-semibold">Toplam</th>
									</tr>
								</thead>
								<tbody>
									{#each statusData.agencies as a}
										<tr
											class="border-b border-gray-100 {rowClickable(a) ? 'cursor-pointer hover:bg-gray-50' : ''}"
											role={rowClickable(a) ? 'button' : undefined}
											tabindex={rowClickable(a) ? 0 : undefined}
											onclick={() => rowClickable(a) && drillRow(a)}
											onkeydown={(e) => { if (rowClickable(a) && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); drillRow(a); } }}
										>
											<td class="px-4 py-3">
												<span class="flex items-center gap-2 font-medium">
													<span class="h-2.5 w-2.5 shrink-0 rounded-sm" style="background:{a.color}"></span>{a.name}
													{#if a.id != null}<ChevronRight class="h-4 w-4 shrink-0 text-gray-400" />{/if}
												</span>
											</td>
											{#each statusData.statuses as s}
												<td class="px-4 py-3 text-right tabular-nums">
													{#if a[s.key].count > 0}
														<span class="font-semibold">{eurC(a[s.key].amount)}</span>
														<span class="block text-[11px] font-normal text-gray-500">{cnt(a[s.key].count)} rez.</span>
													{:else}<span class="text-gray-300">—</span>{/if}
												</td>
											{/each}
											<td class="px-4 py-3 text-right tabular-nums">
												<span class="font-semibold text-teal-800">{eurC(a.total_amount)}</span>
												<span class="block text-[11px] font-normal text-gray-500">{cnt(a.total_count)} rez.</span>
											</td>
										</tr>
									{/each}
									<tr class="bg-gray-50 font-semibold">
										<td class="px-4 py-3">Toplam</td>
										{#each statusData.statuses as s}
											<td class="px-4 py-3 text-right tabular-nums">
												{eurC(statusData.totals[s.key].amount)}
												<span class="block text-[11px] font-normal text-gray-500">{cnt(statusData.totals[s.key].count)} rez.</span>
											</td>
										{/each}
										<td class="px-4 py-3 text-right tabular-nums text-teal-800">
											{eurC(statusData.grand_amount)}
											<span class="block text-[11px] font-normal text-gray-500">{cnt(statusData.grand_count)} rez.</span>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
				{/if}

				<p class="mt-3 text-xs leading-relaxed text-gray-500">
					<strong>Sırala</strong> seçimine göre (rezervasyon sayısı ya da ciro) en yüksek ilk 7 birim (grup veya tek acente) büyükten küçüğe müstakil gösterilir; kalanların tümü <strong>Diğer</strong> altında toplanır. Gruplanmamış büyük bir acente de kendi hakkıyla listeye girer, "Diğer"e gömülmez. Bir <strong>grup</strong> (veya <strong>Diğer</strong>) satırına tıklayarak içindeki acentelere, oradan tek acenteye inebilirsiniz; üstteki yol (breadcrumb) ile geri dönün. Tutar <strong>gece bazlı</strong> dağıtılır: her konaklama gecesi kendi ayına, ciro gece sayısına bölünerek yazılır (Aylık Doluluk Dağılımı ile aynı yöntem) — birden çok aya yayılan rezervasyon her aya kendi gecesi kadar düşer ve dokunduğu her ayda adet olarak sayılır. Renk, rezervasyonun anlık PMS durumudur (<strong>gelen</strong> / <strong>içeride</strong> / <strong>çıkış yapan</strong>); geçmiş dönemlerde konuklar çıkış yaptığından "içeride" pratikte yalnız güncel dönemde görünür.
				</p>
			</div>

		<!-- ═══════════ SATIŞ FATURALARI ═══════════ -->
		{:else if activeTab === 'fatura'}
			<div class="grid gap-3 sm:grid-cols-3">
				<StatCard accent="gray" label="Kesilen Fatura" value={eurC(data.invoices.total_amount)} hint="çıkışta kesilen (projeksiyon)" />
				<StatCard accent="teal" label="Avans Mahsubu" value={eurC(data.invoices.total_mahsup)} hint="faturadan düşülen" />
				<StatCard accent="emerald" label="Net Tahsil Edilecek" value={eurC(data.invoices.total_net)} hint="vade tarihlerinde" />
			</div>
			{#if data.invoices.rows.length === 0}
				<EmptyState icon={Inbox} title="Fatura yok" description="Bu yıl için projeksiyon faturası bulunmuyor." />
			{:else}
				<div class="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
					<div class="overflow-x-auto">
						<table class="w-full min-w-[720px] text-sm">
							<thead>
								<tr class="border-b-2 border-teal-700 text-left text-[11px] uppercase tracking-wide text-gray-500">
									<th class="px-4 py-3 font-semibold">Çıkış Ayı</th>
									<th class="px-4 py-3 font-semibold">Acente</th>
									<th class="px-4 py-3 text-right font-semibold">Tutar</th>
									<th class="px-4 py-3 text-right font-semibold">Mahsup</th>
									<th class="px-4 py-3 text-right font-semibold">Net</th>
									<th class="px-4 py-3 text-right font-semibold">Vade</th>
									<th class="px-4 py-3 text-right font-semibold">Durum</th>
								</tr>
							</thead>
							<tbody>
								{#each data.invoices.rows as i}
									<tr class="border-b border-gray-100">
										<td class="px-4 py-3 text-gray-600">{i.month_name}</td>
										<td class="px-4 py-3">
											<span class="flex items-center gap-2 font-medium">
												<span class="h-2 w-2 shrink-0 rounded-sm" style="background:{i.color}"></span>{i.agency}
											</span>
										</td>
										<td class="px-4 py-3 text-right tabular-nums">{eurC(i.amount)}</td>
										<td class="px-4 py-3 text-right tabular-nums {i.mahsup > 0 ? 'text-teal-700' : 'text-gray-300'}">{i.mahsup > 0 ? '−' + eurC(i.mahsup) : '—'}</td>
										<td class="px-4 py-3 text-right font-semibold tabular-nums">{eurC(i.net)}</td>
										<td class="px-4 py-3 text-right text-gray-500">{i.due_name}</td>
										<td class="px-4 py-3 text-right">
											<span class="inline-block rounded-md px-2 py-0.5 text-[11px] font-semibold {STATUS_META[i.status]?.cls}">{STATUS_META[i.status]?.label}</span>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
				<p class="text-xs leading-relaxed text-gray-500">
					Faturalar konaklama tamamlandığında (check-out) kesilir. Varsa acente avansı mahsup edilir; kalan net tutar acentenin vadesinde tahsil edilir. Bu sekme rezervasyon cirosundan üretilmiş <strong>projeksiyondur</strong>; gerçek muhasebe faturaları için Hak Ediş Takibi modülüne bakın.
				</p>
			{/if}

		<!-- ═══════════ NAKİT AKIM ═══════════ -->
		{:else if activeTab === 'nakit'}
			<!-- Runway grafiği -->
			<div class="rounded-2xl bg-teal-700 p-5 text-teal-100 shadow-sm">
				<div class="flex flex-wrap items-start justify-between gap-3">
					<div>
						<div class="text-[11px] uppercase tracking-wide text-teal-300">Tahsilat Bakiyesi Projeksiyonu</div>
						<div class="mt-1 text-sm text-teal-200">Açılış <span class="tabular-nums text-white">{eur(data.cashflow.opening)}</span></div>
					</div>
					<div class="text-right">
						<div class="text-[11px] uppercase tracking-wide text-teal-300">Dönem sonu bakiye</div>
						<div class="mt-1 text-xl font-semibold tabular-nums text-emerald-300">{eur(data.cashflow.closing)}</div>
					</div>
				</div>
				{#if chartGeo}
					<div class="mt-3">
						<svg viewBox="0 0 620 96" preserveAspectRatio="none" class="block h-16 w-full">
							<defs>
								<linearGradient id="amcf" x1="0" y1="0" x2="0" y2="1">
									<stop offset="0" stop-color="#7fa8d0" stop-opacity=".34" />
									<stop offset="1" stop-color="#7fa8d0" stop-opacity="0" />
								</linearGradient>
							</defs>
							<path d={chartGeo.area} fill="url(#amcf)" />
							<polyline points={chartGeo.line} fill="none" stroke="#7fa8d0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
							{#if chartGeo.mx}<circle cx={chartGeo.mx} cy={chartGeo.my} r="4.5" fill="#e8c979" />{/if}
						</svg>
						<div class="mt-1 flex justify-between text-[10px] tabular-nums text-teal-300">
							{#each chartGeo.labels as l}<span>{l}</span>{/each}
						</div>
					</div>
					<div class="mt-2 text-xs text-teal-200">
						En düşük bakiye: <span class="font-semibold text-brass-light">{data.cashflow.chart.min_label} · {eurC(data.cashflow.chart.min_value)}</span>
						{#if data.cashflow.kickback_total > 0}· kickback ({eurC(data.cashflow.kickback_total)}) Aralık'ta düşülür{/if}
					</div>
				{/if}
			</div>

			<!-- Aylık tablo -->
			{#if data.cashflow.rows.length === 0}
				<EmptyState icon={Inbox} title="Projeksiyon dönemi yok" description="Seçili yıl için tahsilat projeksiyonu bulunmuyor." />
			{:else}
				<div class="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
					<div class="overflow-x-auto">
						<table class="w-full min-w-[560px] text-sm">
							<thead>
								<tr class="border-b-2 border-teal-700 text-left text-[11px] uppercase tracking-wide text-gray-500">
									<th class="px-4 py-3 font-semibold">Ay</th>
									<th class="px-4 py-3 text-right font-semibold">Tahsilat +</th>
									<th class="px-4 py-3 text-right font-semibold">Kickback −</th>
									<th class="px-4 py-3 text-right font-semibold">Net Ay</th>
									<th class="px-4 py-3 text-right font-semibold">Kümülatif Bakiye</th>
								</tr>
							</thead>
							<tbody>
								{#each data.cashflow.rows as c}
									<tr class="border-b border-gray-100">
										<td class="px-4 py-3 font-medium">{c.name}</td>
										<td class="px-4 py-3 text-right font-semibold tabular-nums text-emerald-700">{eurC(c.collection)}</td>
										<td class="px-4 py-3 text-right tabular-nums {c.kickback > 0 ? 'text-amber-700' : 'text-gray-300'}">{c.kickback > 0 ? '−' + eurC(c.kickback) : '—'}</td>
										<td class="px-4 py-3 text-right font-semibold tabular-nums {c.net >= 0 ? 'text-emerald-700' : 'text-red-600'}">{c.net >= 0 ? '+' : '−'}{eurC(Math.abs(c.net))}</td>
										<td class="px-4 py-3 text-right tabular-nums text-teal-800">{eurC(c.cumulative)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
				<div class="grid gap-3 sm:grid-cols-2">
					<StatCard accent="emerald" label="Dönem Toplam Tahsilat" value={eur(data.cashflow.in_total)} />
					<StatCard accent="amber" label="Ertesi Yıla Devreden" value={eur(data.cashflow.tail)} hint="son ayların vadeli kısmı" />
				</div>
			{/if}
			<p class="text-xs leading-relaxed text-gray-500">
				Her ayın cirosu acente vadesine göre ileri tarihe kaydırılarak tahsilat ayına yazılır. Alınan avanslar açılış bakiyesine dahildir; mahsup edilen tutarlar tekrar tahsilat olarak sayılmaz.
			</p>
		{/if}
	{:else}
		<EmptyState icon={Inbox} title="Veri yok" description="Projeksiyon oluşturulamadı." />
	{/if}
	{/if}

	<!-- ═══════════ PANEL SEKMELERİ (keep-alive: ziyaret edilince mount kalır) ═══════════ -->
	{#if visitedTabs.has('rezervasyon')}
		<div class={activeTab === 'rezervasyon' ? '' : 'hidden'}><ReservationsPanel /></div>
	{/if}
	{#if visitedTabs.has('hareket')}
		<div class={activeTab === 'hareket' ? '' : 'hidden'}><DailyActivityPanel /></div>
	{/if}
	{#if visitedTabs.has('oda')}
		<div class={activeTab === 'oda' ? '' : 'hidden'}><RoomTypesPanel /></div>
	{/if}
</div>

<!-- Acente Ayarları Modalı -->
<Modal bind:show={showSettings} title="Acente Ayarları — Vade & Kickback" maxWidth="max-w-2xl">
	{#if groupsLoading}
		<TableSkeleton rows={4} columns={3} />
	{:else if groups.length === 0}
		<EmptyState icon={Inbox} title="Acente grubu yok" description="Önce Rezervasyonlar sekmesindeki Grupları Yönet ile acente grupları oluşturun." />
	{:else}
		<p class="mb-3 text-sm text-gray-600">Her acente grubunun tahsilat vadesini (gün) ve yıl sonu kickback oranını (%) ayarlayın.</p>
		<div class="space-y-2">
			{#each groups as g (g.id)}
				<div class="flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 p-3">
					<span class="min-w-[120px] flex-1 font-medium">{g.name}</span>
					<label class="flex items-center gap-2 text-sm">
						<span class="text-gray-600">Vade</span>
						<input type="number" min="0" max="365" bind:value={g.term_days}
							class="w-20 rounded-lg border border-gray-300 px-2 py-1.5 text-right tabular-nums focus:ring-2 focus:ring-teal-500" />
						<span class="text-gray-500">gün</span>
					</label>
					<label class="flex items-center gap-2 text-sm">
						<span class="text-gray-600">Kickback</span>
						<div class="w-24"><MoneyInput bind:value={g.kickback_percent} currency="%" min={0} decimals={1} /></div>
					</label>
					<Button size="sm" variant="secondary" loading={savingId === g.id} onclick={() => saveGroup(g)}>Kaydet</Button>
				</div>
			{/each}
		</div>
	{/if}
</Modal>
