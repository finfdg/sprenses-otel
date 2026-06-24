<script lang="ts">
	// Svelte
	import { onMount, onDestroy } from 'svelte';
	// Proje store/api
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { BROADCAST_MODULE } from '$lib/constants/realtime';
	// Bileşenler
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import Select from '$lib/components/Select.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { formatCurrency } from '$lib/utils/finance';
	import {
		BarChart3, Euro, BedDouble, CalendarCheck, Clock, Building2, Globe, UtensilsCrossed,
		TrendingUp, TrendingDown
	} from 'lucide-svelte';

	// Sabitler
	const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
	// Dönem seçenekleri: "Tüm dönem" + son birkaç yıl (özet endpoint'i start_date/end_date ile filtreler)
	const CURRENT_YEAR = new Date().getFullYear();
	const PERIOD_OPTIONS: { value: string; label: string }[] = [
		{ value: '', label: 'Tüm Dönem' },
		...[0, 1, 2].map((offset) => {
			const y = CURRENT_YEAR + 1 - offset; // gelecek yıl rezervasyonları da kapsasın
			return { value: String(y), label: `${y}` };
		}),
	];

	// SVG grafik boyutları (döviz panelinden uyarlandı)
	const CHART_W = 800;
	const CHART_H = 280;
	const PAD = { top: 20, right: 20, bottom: 30, left: 55 };

	// Türetilmiş — izin geçidi (salt-okunur panel)
	let canView = $derived(hasPermission('sales.hotel_reservation', 'view'));
	let canViewDaily = $derived(hasPermission('sales.daily_reservations', 'view'));

	// Veri state
	let summary = $state<any>(null);
	let daily = $state<any>(null);

	// UI state
	let loading = $state(true);
	let period = $state(''); // '' = tüm dönem, yoksa yıl (YYYY)
	let hoverIndex = $state<number | null>(null);

	// Türetilmiş veri kısayolları
	let kpi = $derived(summary?.kpi ?? null);
	let byAgency = $derived<any[]>(summary?.by_agency ?? []);
	let byRoomType = $derived<any[]>(summary?.by_room_type ?? []);
	let byBoard = $derived<any[]>(summary?.by_board ?? []);
	let byNation = $derived<any[]>((summary?.by_nation ?? []).slice(0, 10));

	// Aylık doluluk noktaları (grafik için)
	let monthlyPoints = $derived<{ label: string; value: number; month: string }[]>(
		(summary?.monthly ?? []).map((m: any) => ({
			label: monthLabel(m.month),
			value: m.occupancy_pct ?? 0,
			month: m.month,
		}))
	);

	// Acente geceleme bar'ları için maksimum (görece genişlik)
	let agencyMaxNights = $derived(Math.max(1, ...byAgency.map((a) => a.room_nights || 0)));
	let nationMaxEur = $derived(Math.max(1, ...byNation.map((n) => n.eur || 0)));
	let boardMaxEur = $derived(Math.max(1, ...byBoard.map((b) => b.eur || 0)));

	// ── SVG aylık doluluk çizgisi (döviz pattern) ──
	let chartPath = $derived.by(() => {
		const pts = monthlyPoints;
		if (pts.length < 2) return '';
		const maxVal = Math.max(100, ...pts.map((p) => p.value));
		const w = CHART_W - PAD.left - PAD.right;
		const h = CHART_H - PAD.top - PAD.bottom;
		return pts
			.map((p, i) => {
				const x = PAD.left + (i / (pts.length - 1)) * w;
				const y = PAD.top + h - (p.value / maxVal) * h;
				return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(' ');
	});

	let chartYLabels = $derived.by(() => {
		const pts = monthlyPoints;
		if (pts.length < 2) return [];
		const maxVal = Math.max(100, ...pts.map((p) => p.value));
		const h = CHART_H - PAD.top - PAD.bottom;
		const steps = 4;
		const labels: { y: number; text: string }[] = [];
		for (let i = 0; i <= steps; i++) {
			const val = (maxVal * i) / steps;
			const y = PAD.top + h - (i / steps) * h;
			labels.push({ y, text: `%${Math.round(val)}` });
		}
		return labels;
	});

	let chartXLabels = $derived.by(() => {
		const pts = monthlyPoints;
		if (pts.length < 2) return [];
		const w = CHART_W - PAD.left - PAD.right;
		const step = Math.max(1, Math.floor(pts.length / 8));
		const labels: { x: number; text: string }[] = [];
		for (let i = 0; i < pts.length; i += step) {
			const x = PAD.left + (i / (pts.length - 1)) * w;
			labels.push({ x, text: pts[i].label });
		}
		return labels;
	});

	function getHoverPoint(idx: number | null) {
		const pts = monthlyPoints;
		if (idx === null || !pts[idx] || pts.length < 2) return null;
		const maxVal = Math.max(100, ...pts.map((p) => p.value));
		const w = CHART_W - PAD.left - PAD.right;
		const h = CHART_H - PAD.top - PAD.bottom;
		const x = PAD.left + (idx / (pts.length - 1)) * w;
		const y = PAD.top + h - (pts[idx].value / maxVal) * h;
		return { x, y, label: pts[idx].label, value: pts[idx].value };
	}

	function handleChartHover(e: MouseEvent) {
		const svg = e.currentTarget as SVGSVGElement;
		const rect = svg.getBoundingClientRect();
		const mouseX = ((e.clientX - rect.left) / rect.width) * CHART_W;
		const pts = monthlyPoints;
		if (pts.length < 2) return;
		const w = CHART_W - PAD.left - PAD.right;
		const relX = mouseX - PAD.left;
		const idx = Math.round((relX / w) * (pts.length - 1));
		hoverIndex = Math.max(0, Math.min(pts.length - 1, idx));
	}

	// Formatlama
	function fmtEur(n: number): string {
		return formatCurrency(n || 0, 'EUR');
	}
	function fmtNum(n: number): string {
		return new Intl.NumberFormat('tr-TR').format(n || 0);
	}
	function monthLabel(ym: string): string {
		// "2026-05" → "May 26"
		const [y, m] = (ym || '').split('-');
		const mi = parseInt(m, 10) - 1;
		if (mi < 0 || mi > 11) return ym;
		return `${MONTH_NAMES[mi].slice(0, 3)} ${y.slice(2)}`;
	}

	// Veri fonksiyonları
	async function loadSummary() {
		const params = period ? `?start_date=${period}-01-01&end_date=${period}-12-31` : '';
		try {
			summary = await api.get<any>(`/sales/reservations/summary${params}`);
		} catch (err) {
			console.error('Satış özeti yüklenemedi:', err);
			showToast('Satış özeti yüklenemedi', 'error');
		}
	}

	async function loadDaily() {
		if (!canViewDaily) return;
		// Günlük hareket = Sedna canlı; dönem yoksa son 30 gün, yıl seçiliyse o yılın ilk yarısı yerine
		// güncel aya yakın bir pencere kullan (geniş aralık Sedna sorgusunu yavaşlatır).
		const today = new Date();
		const end = today.toISOString().slice(0, 10);
		const startDate = new Date(today.getTime() - 29 * 86400000).toISOString().slice(0, 10);
		try {
			daily = await api.get<any>(`/daily-activity/summary?start_date=${startDate}&end_date=${end}`);
		} catch (err) {
			// Sedna kapalı olabilir — opsiyonel kart, sessizce gizle ama logla
			console.error('Günlük hareket özeti yüklenemedi:', err);
			daily = null;
		}
	}

	async function load() {
		loading = true;
		hoverIndex = null;
		try {
			await Promise.all([loadSummary(), loadDaily()]);
		} finally {
			loading = false;
		}
	}

	function onPeriodChange() {
		load();
	}

	// Lifecycle
	let unsubSales: (() => void) | undefined;
	onMount(() => {
		load();
		unsubSales = onWsEvent('sales_updated', (data: any) => {
			if (data?.module === BROADCAST_MODULE.HOTEL_RESERVATION) {
				loadSummary();
			}
		});
	});
	onDestroy(() => {
		unsubSales?.();
	});
</script>

<svelte:head><title>Satış & Doluluk Paneli · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader title="Satış & Doluluk Paneli" description="Otel doluluğu, ortalama oda fiyatı ve satış dağılımları tek bakışta.">
		{#snippet actions()}
			<Select size="sm" fullWidth={false} bind:value={period} onchange={onPeriodChange} aria-label="Dönem seçimi" class="min-w-[8rem]">
				{#each PERIOD_OPTIONS as opt}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</Select>
		{/snippet}
	</PageHeader>

	{#if !canView}
		<EmptyState icon={BarChart3} title="Erişim yetkiniz yok" description="Bu paneli görüntülemek için Otel Rezervasyon görme izni gereklidir." />
	{:else if loading}
		<TableSkeleton rows={8} columns={5} />
	{:else if !summary || !kpi}
		<EmptyState icon={BarChart3} title="Veri bulunamadı" description="Seçilen dönem için rezervasyon özeti bulunamadı." />
	{:else}
		<!-- KPI kartları -->
		<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3 sm:gap-4">
			<StatCard
				label="Doluluk"
				value={`%${(kpi.occupancy_pct ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 })}`}
				accent="teal"
				icon={BarChart3}
				hint={`${fmtNum(kpi.total_capacity)} oda · ${fmtNum(kpi.date_range_days)} gün`}
			/>
			<StatCard
				label="ADR"
				value={`${(kpi.adr ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 2 })} €`}
				accent="blue"
				icon={Euro}
				hint="Ortalama oda fiyatı"
			/>
			<StatCard
				label="Oda Gecesi"
				value={fmtNum(kpi.total_room_nights)}
				accent="gray"
				icon={BedDouble}
				hint={`${fmtNum(kpi.total_guest_nights)} kişi-gece`}
			/>
			<StatCard
				label="Toplam Rezervasyon"
				value={fmtNum(kpi.total_rez)}
				accent="emerald"
				icon={CalendarCheck}
				hint={`${fmtNum(kpi.definite_count)} kesin · ${fmtNum(kpi.option_count)} opsiyon`}
			/>
			<StatCard
				label="Ort. Konaklama"
				value={`${(kpi.avg_los ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} gece`}
				accent="gray"
				icon={Clock}
				hint={`Toplam ciro ${fmtEur(kpi.total_eur)}`}
			/>
		</div>

		<!-- Aylık doluluk trendi -->
		<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
			<h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
				<BarChart3 size={16} class="text-teal-600" /> Aylık Doluluk Trendi
			</h3>
			{#if monthlyPoints.length < 2}
				<div class="flex items-center justify-center py-12 text-gray-500 text-sm">Grafik için yeterli veri yok</div>
			{:else}
				{@const hp = getHoverPoint(hoverIndex)}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<svg
					viewBox="0 0 {CHART_W} {CHART_H}"
					class="w-full h-auto"
					role="img"
					aria-label="Aylık doluluk trendi grafiği"
					onmousemove={handleChartHover}
					onmouseleave={() => (hoverIndex = null)}
				>
					<!-- Yatay grid çizgileri + Y etiketleri -->
					{#each chartYLabels as label}
						<line x1={PAD.left} y1={label.y} x2={CHART_W - PAD.right} y2={label.y} stroke="#f0f0f0" stroke-width="1" />
						<text x={PAD.left - 8} y={label.y + 4} text-anchor="end" fill="#9ca3af" font-size="11">{label.text}</text>
					{/each}

					<!-- X etiketleri -->
					{#each chartXLabels as label}
						<text x={label.x} y={CHART_H - 8} text-anchor="middle" fill="#9ca3af" font-size="10">{label.text}</text>
					{/each}

					<!-- Doluluk çizgisi -->
					<path d={chartPath} fill="none" stroke="#0d9488" stroke-width="2" />

					<!-- Hover göstergesi -->
					{#if hp}
						<line x1={hp.x} y1={PAD.top} x2={hp.x} y2={CHART_H - PAD.bottom} stroke="#94a3b8" stroke-width="1" stroke-dasharray="4" />
						<circle cx={hp.x} cy={hp.y} r="4" fill="#0d9488" stroke="white" stroke-width="2" />
						{@const tooltipX = hp.x > CHART_W / 2 ? hp.x - 110 : hp.x + 10}
						<rect x={tooltipX} y={hp.y - 34} width="100" height="28" rx="6" fill="white" stroke="#e5e7eb" stroke-width="1" />
						<text x={tooltipX + 8} y={hp.y - 21} fill="#374151" font-size="11" font-weight="600">%{hp.value.toLocaleString('tr-TR', { maximumFractionDigits: 1 })}</text>
						<text x={tooltipX + 92} y={hp.y - 21} text-anchor="end" fill="#9ca3af" font-size="10">{hp.label}</text>
					{/if}
				</svg>
			{/if}
		</div>

		<!-- Dağılım kartları -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
			<!-- Acente bazında geceleme -->
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
					<Building2 size={16} class="text-teal-600" /> Acente Bazında Geceleme
				</h3>
				{#if byAgency.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-3">
						{#each byAgency.slice(0, 8) as a (a.name)}
							<div>
								<div class="flex justify-between text-xs mb-1 gap-2">
									<span class="text-gray-700 truncate">{a.name}</span>
									<span class="font-semibold text-gray-800 tabular-nums shrink-0">{fmtNum(a.room_nights)} gece · {fmtEur(a.eur)}</span>
								</div>
								<div class="h-2 bg-gray-100 rounded-full">
									<div class="h-2 bg-teal-600 rounded-full" style="width:{(a.room_nights / agencyMaxNights) * 100}%"></div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Oda tipi doluluğu -->
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
					<BedDouble size={16} class="text-teal-600" /> Oda Tipi Doluluğu
				</h3>
				{#if byRoomType.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-3">
						{#each byRoomType.slice(0, 8) as t (t.name)}
							<div>
								<div class="flex justify-between text-xs mb-1 gap-2">
									<span class="text-gray-700 truncate">{t.name}</span>
									<span class="font-semibold text-gray-800 tabular-nums shrink-0">%{(t.occupancy_pct ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} · {fmtNum(t.room_nights)} gece</span>
								</div>
								<div class="h-2 bg-gray-100 rounded-full">
									<div class="h-2 bg-teal-600 rounded-full" style="width:{Math.min(t.occupancy_pct ?? 0, 100)}%"></div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Pansiyon tipi -->
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
					<UtensilsCrossed size={16} class="text-teal-600" /> Pansiyon Tipi
				</h3>
				{#if byBoard.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-3">
						{#each byBoard as b (b.name)}
							<div>
								<div class="flex justify-between text-xs mb-1 gap-2">
									<span class="text-gray-700 truncate">{b.name}</span>
									<span class="font-semibold text-gray-800 tabular-nums shrink-0">%{(b.pct ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} · {fmtEur(b.eur)}</span>
								</div>
								<div class="h-2 bg-gray-100 rounded-full">
									<div class="h-2 bg-teal-600 rounded-full" style="width:{(b.eur / boardMaxEur) * 100}%"></div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Uyruk (Top 10) -->
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
					<Globe size={16} class="text-teal-600" /> Uyruk (İlk 10)
				</h3>
				{#if byNation.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-3">
						{#each byNation as n (n.code)}
							<div>
								<div class="flex justify-between text-xs mb-1 gap-2">
									<span class="text-gray-700 truncate">{n.code}</span>
									<span class="font-semibold text-gray-800 tabular-nums shrink-0">%{(n.pct ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} · {fmtEur(n.eur)}</span>
								</div>
								<div class="h-2 bg-gray-100 rounded-full">
									<div class="h-2 bg-teal-600 rounded-full" style="width:{(n.eur / nationMaxEur) * 100}%"></div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<!-- Günlük hareket (opsiyonel — sales.daily_reservations izni) -->
		{#if canViewDaily && daily?.totals}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
				<div class="flex items-center justify-between gap-2 mb-4">
					<h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2">
						<CalendarCheck size={16} class="text-teal-600" /> Son 30 Gün Hareket
					</h3>
					<StatusBadge type={daily.totals.cancel_rate > 25 ? 'warning' : 'info'}>
						İptal oranı %{(daily.totals.cancel_rate ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 })}
					</StatusBadge>
				</div>
				<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
					<div class="rounded-xl border border-gray-200 p-3">
						<div class="text-xs font-medium text-gray-500 uppercase tracking-wider flex items-center gap-1">
							<TrendingUp size={14} class="text-emerald-600" /> Yeni Rezervasyon
						</div>
						<div class="mt-1 text-lg font-bold text-emerald-700 tabular-nums">{fmtNum(daily.totals.new?.count ?? 0)}</div>
						<div class="text-xs text-gray-500 mt-0.5">{fmtEur(daily.totals.new?.eur ?? 0)}</div>
					</div>
					<div class="rounded-xl border border-gray-200 p-3">
						<div class="text-xs font-medium text-gray-500 uppercase tracking-wider flex items-center gap-1">
							<TrendingDown size={14} class="text-red-600" /> İptal
						</div>
						<div class="mt-1 text-lg font-bold text-red-600 tabular-nums">{fmtNum(daily.totals.cancelled?.count ?? 0)}</div>
						<div class="text-xs text-gray-500 mt-0.5">{fmtEur(daily.totals.cancelled?.eur ?? 0)}</div>
					</div>
					<div class="rounded-xl border border-gray-200 p-3">
						<div class="text-xs font-medium text-gray-500 uppercase tracking-wider">Net</div>
						<div class="mt-1 text-lg font-bold tabular-nums {(daily.totals.net_count ?? 0) >= 0 ? 'text-emerald-700' : 'text-red-600'}">{fmtNum(daily.totals.net_count ?? 0)}</div>
						<div class="text-xs text-gray-500 mt-0.5">{fmtEur(daily.totals.net_eur ?? 0)}</div>
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>
