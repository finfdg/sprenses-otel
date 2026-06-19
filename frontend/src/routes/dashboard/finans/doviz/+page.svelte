<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { Loader2 } from 'lucide-svelte';
	import type {
		LatestRates, ExchangeRate, ChartDataPoint, ParityDataPoint, CurrencyCode
	} from '$lib/types/exchange-rate';

	// ─── State ──────────────────────────────────────
	let latest = $state<LatestRates | null>(null);
	let loading = $state(true);

	// Grafik
	let chartCurrency = $state<CurrencyCode | 'parity'>('USD');
	let chartDays = $state(90);
	let chartData = $state<ChartDataPoint[]>([]);
	let parityData = $state<ParityDataPoint[]>([]);
	let chartLoading = $state(false);
	let hoverIndex = $state<number | null>(null);

	// Tarihçe tablosu
	let historyCurrency = $state<CurrencyCode>('USD');
	let historyItems = $state<ExchangeRate[]>([]);
	let historyPage = $state(1);
	let historyTotal = $state(0);
	let historyPages = $state(1);
	let historyLoading = $state(false);
	const historyPageSize = 60;

	// ─── Döviz bilgileri ────────────────────────────
	const CURRENCY_INFO: Record<string, { symbol: string; name: string; color: string; bgColor: string }> = {
		USD: { symbol: '$', name: 'ABD Doları', color: 'text-emerald-700', bgColor: 'bg-emerald-50 border-emerald-200' },
		EUR: { symbol: '€', name: 'Euro', color: 'text-blue-700', bgColor: 'bg-blue-50 border-blue-200' },
		GBP: { symbol: '£', name: 'İngiliz Sterlini', color: 'text-violet-700', bgColor: 'bg-violet-50 border-violet-200' },
	};

	const PERIOD_OPTIONS = [
		{ label: '30G', days: 30 },
		{ label: '90G', days: 90 },
		{ label: '6A', days: 180 },
		{ label: '1Y', days: 365 },
		{ label: 'Tümü', days: 1095 },
	];

	// ─── API ────────────────────────────────────────
	async function loadLatest() {
		try {
			latest = await api.get<LatestRates>('/finance/exchange-rates/latest');
		} catch (err: any) {
			console.error('Güncel kurlar yüklenemedi:', err);
			showToast('Güncel kurlar yüklenemedi', 'error');
		}
	}

	async function loadChart() {
		chartLoading = true;
		try {
			if (chartCurrency === 'parity') {
				parityData = await api.get<ParityDataPoint[]>(
					`/finance/exchange-rates/parity/history?days=${chartDays}`
				);
				chartData = [];
			} else {
				chartData = await api.get<ChartDataPoint[]>(
					`/finance/exchange-rates/chart?currency_code=${chartCurrency}&days=${chartDays}`
				);
				parityData = [];
			}
		} catch (err: any) {
			console.error('Grafik verisi yüklenemedi:', err);
		} finally {
			chartLoading = false;
		}
	}

	async function loadHistory() {
		historyLoading = true;
		try {
			const data = await api.get<{ items: ExchangeRate[]; total: number; pages: number }>(
				`/finance/exchange-rates/history?currency_code=${historyCurrency}&page=${historyPage}&page_size=${historyPageSize}`
			);
			historyItems = data.items;
			historyTotal = data.total;
			historyPages = data.pages;
		} catch (err: any) {
			console.error('Tarihçe yüklenemedi:', err);
		} finally {
			historyLoading = false;
		}
	}

	onMount(async () => {
		await Promise.all([loadLatest(), loadChart(), loadHistory()]);
		loading = false;
	});

	// Grafik veya tarihçe değişince yenile
	$effect(() => {
		// chartCurrency veya chartDays değişince
		void chartCurrency;
		void chartDays;
		if (!loading) {
			hoverIndex = null;
			loadChart();
		}
	});

	$effect(() => {
		void historyCurrency;
		void historyPage;
		if (!loading) loadHistory();
	});

	// ─── Yardımcılar ───────────────────────────────
	function formatRate(val: number | null): string {
		if (val === null) return '—';
		return val.toLocaleString('tr-TR', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
	}

	function formatDate(dateStr: string): string {
		const d = new Date(dateStr + 'T00:00:00');
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}

	function formatDateShort(dateStr: string): string {
		const d = new Date(dateStr + 'T00:00:00');
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' });
	}

	function getRateForCurrency(code: string): ExchangeRate | undefined {
		return latest?.rates.find(r => r.currency_code === code);
	}

	// ─── SVG Grafik ─────────────────────────────────
	const CHART_W = 800;
	const CHART_H = 300;
	const PAD = { top: 20, right: 20, bottom: 30, left: 65 };

	let activeChartPoints = $derived.by(() => {
		if (chartCurrency === 'parity') {
			return parityData
				.filter(p => p.parity !== null)
				.map(p => ({ date: p.date, value: p.parity! }));
		}
		return chartData
			.filter(p => p.forex_selling !== null)
			.map(p => ({ date: p.date, value: p.forex_selling! }));
	});

	let chartPath = $derived.by(() => {
		const pts = activeChartPoints;
		if (pts.length < 2) return '';

		const minVal = Math.min(...pts.map(p => p.value));
		const maxVal = Math.max(...pts.map(p => p.value));
		const range = maxVal - minVal || 1;

		const w = CHART_W - PAD.left - PAD.right;
		const h = CHART_H - PAD.top - PAD.bottom;

		return pts.map((p, i) => {
			const x = PAD.left + (i / (pts.length - 1)) * w;
			const y = PAD.top + h - ((p.value - minVal) / range) * h;
			return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
		}).join(' ');
	});

	let chartYLabels = $derived.by(() => {
		const pts = activeChartPoints;
		if (pts.length < 2) return [];

		const minVal = Math.min(...pts.map(p => p.value));
		const maxVal = Math.max(...pts.map(p => p.value));
		const range = maxVal - minVal || 1;
		const h = CHART_H - PAD.top - PAD.bottom;
		const steps = 5;
		const labels: { y: number; text: string }[] = [];

		for (let i = 0; i <= steps; i++) {
			const val = minVal + (range * i) / steps;
			const y = PAD.top + h - (i / steps) * h;
			labels.push({ y, text: val.toFixed(chartCurrency === 'parity' ? 4 : 2) });
		}
		return labels;
	});

	let chartXLabels = $derived.by(() => {
		const pts = activeChartPoints;
		if (pts.length < 2) return [];

		const w = CHART_W - PAD.left - PAD.right;
		const step = Math.max(1, Math.floor(pts.length / 6));
		const labels: { x: number; text: string }[] = [];

		for (let i = 0; i < pts.length; i += step) {
			const x = PAD.left + (i / (pts.length - 1)) * w;
			labels.push({ x, text: formatDateShort(pts[i].date) });
		}
		// Son tarih
		if (pts.length > 1) {
			const lastX = PAD.left + w;
			labels.push({ x: lastX, text: formatDateShort(pts[pts.length - 1].date) });
		}
		return labels;
	});

	function getHoverPoint(idx: number | null) {
		if (idx === null || !activeChartPoints[idx]) return null;
		const pts = activeChartPoints;
		const p = pts[idx];
		const minVal = Math.min(...pts.map(pp => pp.value));
		const maxVal = Math.max(...pts.map(pp => pp.value));
		const range = maxVal - minVal || 1;
		const w = CHART_W - PAD.left - PAD.right;
		const h = CHART_H - PAD.top - PAD.bottom;
		const x = PAD.left + (idx / (pts.length - 1)) * w;
		const y = PAD.top + h - ((p.value - minVal) / range) * h;
		return { x, y, date: p.date, value: p.value };
	}

	function handleChartHover(e: MouseEvent) {
		const svg = (e.currentTarget as SVGSVGElement);
		const rect = svg.getBoundingClientRect();
		const mouseX = (e.clientX - rect.left) / rect.width * CHART_W;
		const pts = activeChartPoints;
		if (pts.length < 2) return;

		const w = CHART_W - PAD.left - PAD.right;
		const relX = mouseX - PAD.left;
		const idx = Math.round((relX / w) * (pts.length - 1));
		hoverIndex = Math.max(0, Math.min(pts.length - 1, idx));
	}
</script>

<svelte:head>
	<title>Döviz Kurları - Sprenses</title>
</svelte:head>

<div class="max-w-7xl mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4 sm:space-y-6">

	<!-- ─── Başlık ─── -->
	<PageHeader title="Döviz Kurları" description="TCMB Merkez Bankası günlük kur verileri" />

	{#if loading}
		<div class="flex items-center justify-center py-24">
			<Loader2 size={32} class="animate-spin text-teal-600" />
		</div>
	{:else}

	<!-- ─── Güncel Kur Kartları ─── -->
	<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
		{#each ['USD', 'EUR', 'GBP'] as code}
			{@const rate = getRateForCurrency(code)}
			{@const info = CURRENCY_INFO[code]}
			<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 hover:shadow-md transition-shadow">
				<div class="flex items-center gap-1.5 sm:gap-2 mb-2 sm:mb-3">
					<span class="text-base sm:text-lg font-bold {info.color}">{info.symbol}</span>
					<span class="text-xs sm:text-sm font-semibold text-gray-700">{code}/TRY</span>
				</div>
				{#if rate}
					<div class="text-lg sm:text-2xl font-bold text-gray-900 mb-1.5 sm:mb-2">
						₺{formatRate(rate.forex_selling)}
					</div>
					<div class="grid grid-cols-2 gap-1.5 sm:gap-2 text-[11px] sm:text-xs">
						<div>
							<span class="text-gray-500">Döviz Alış</span>
							<div class="font-medium text-gray-700">{formatRate(rate.forex_buying)}</div>
						</div>
						<div>
							<span class="text-gray-500">Döviz Satış</span>
							<div class="font-medium text-gray-700">{formatRate(rate.forex_selling)}</div>
						</div>
						</div>
				{:else}
					<div class="text-gray-500 text-sm">Veri yok</div>
				{/if}
			</div>
		{/each}

		<!-- EUR/USD Parite kartı -->
		<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 hover:shadow-md transition-shadow">
			<div class="flex items-center gap-2 mb-3">
				<span class="text-lg font-bold text-amber-600">€/$</span>
				<span class="text-sm font-semibold text-gray-700">EUR/USD</span>
			</div>
			{#if latest?.eur_usd_parity}
				<div class="text-2xl font-bold text-gray-900 mb-2">
					{latest.eur_usd_parity.toFixed(4)}
				</div>
				<div class="text-xs text-gray-500">
					Parite (Satış bazlı)
				</div>
			{:else}
				<div class="text-gray-500 text-sm">Veri yok</div>
			{/if}
			{#if latest?.date}
				<div class="mt-3 text-[11px] text-gray-500">
					Son güncelleme: {formatDate(latest.date)}
				</div>
			{/if}
		</div>
	</div>

	<!-- ─── Grafik ─── -->
	<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-5">
		<!-- Grafik kontrolleri -->
		<div class="flex flex-wrap items-center justify-between gap-2 sm:gap-3 mb-3 sm:mb-4">
			<!-- Döviz sekmeleri -->
			<div class="flex gap-1 bg-gray-100 rounded-lg p-0.5">
				{#each (['USD', 'EUR', 'GBP', 'parity'] as const) as tab}
					<button
						onclick={() => { chartCurrency = tab; hoverIndex = null; }}
						class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer
							{chartCurrency === tab ? 'bg-white text-teal-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}"
					>
						{tab === 'parity' ? 'EUR/USD' : tab}
					</button>
				{/each}
			</div>

			<!-- Süre seçici -->
			<div class="flex gap-1 bg-gray-100 rounded-lg p-0.5">
				{#each PERIOD_OPTIONS as opt}
					<button
						onclick={() => { chartDays = opt.days; hoverIndex = null; }}
						class="px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer
							{chartDays === opt.days ? 'bg-white text-teal-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}"
					>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>

		<!-- SVG Grafik -->
		{#if chartLoading}
			<div class="flex items-center justify-center py-16">
				<Loader2 size={24} class="animate-spin text-teal-600" />
			</div>
		{:else if activeChartPoints.length < 2}
			<div class="flex items-center justify-center py-16 text-gray-500 text-sm">
				Grafik için yeterli veri yok
			</div>
		{:else}
			{@const hp = getHoverPoint(hoverIndex)}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<svg
				viewBox="0 0 {CHART_W} {CHART_H}"
				class="w-full h-auto"
				onmousemove={handleChartHover}
				onmouseleave={() => hoverIndex = null}
				role="img"
				aria-label="Döviz kuru grafiği"
			>
				<!-- Yatay grid çizgileri -->
				{#each chartYLabels as label}
					<line x1={PAD.left} y1={label.y} x2={CHART_W - PAD.right} y2={label.y}
						stroke="#f0f0f0" stroke-width="1" />
					<text x={PAD.left - 8} y={label.y + 4} text-anchor="end"
						fill="#9ca3af" font-size="11">{label.text}</text>
				{/each}

				<!-- X ekseni etiketleri -->
				{#each chartXLabels as label}
					<text x={label.x} y={CHART_H - 5} text-anchor="middle"
						fill="#9ca3af" font-size="10">{label.text}</text>
				{/each}

				<!-- Alış çizgisi (hafif) -->
				{#if chartCurrency !== 'parity' && chartData.length > 1}
					{@const buyPath = chartData.filter(p => p.forex_buying !== null).map((p, i, arr) => {
						const pts = activeChartPoints;
						const minVal = Math.min(...pts.map(pp => pp.value));
						const maxVal = Math.max(...pts.map(pp => pp.value));
						const range = maxVal - minVal || 1;
						const w = CHART_W - PAD.left - PAD.right;
						const h = CHART_H - PAD.top - PAD.bottom;
						const idx = chartData.indexOf(p);
						const x = PAD.left + (idx / (chartData.length - 1)) * w;
						const y = PAD.top + h - ((p.forex_buying! - minVal) / range) * h;
						return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
					}).join(' ')}
					<path d={buyPath} fill="none" stroke="#86efac" stroke-width="1.5" opacity="0.6" />
				{/if}

				<!-- Ana çizgi (satış/parite) -->
				<path d={chartPath} fill="none"
					stroke={chartCurrency === 'parity' ? '#f59e0b' : '#0d9488'}
					stroke-width="2" />

				<!-- Hover göstergesi -->
				{#if hp}
					<line x1={hp.x} y1={PAD.top} x2={hp.x} y2={CHART_H - PAD.bottom}
						stroke="#94a3b8" stroke-width="1" stroke-dasharray="4" />
					<circle cx={hp.x} cy={hp.y} r="4"
						fill={chartCurrency === 'parity' ? '#f59e0b' : '#0d9488'} stroke="white" stroke-width="2" />

					<!-- Tooltip -->
					{@const tooltipX = hp.x > CHART_W / 2 ? hp.x - 130 : hp.x + 10}
					<rect x={tooltipX} y={hp.y - 35} width="120" height="30" rx="6"
						fill="white" stroke="#e5e7eb" stroke-width="1" />
					<text x={tooltipX + 8} y={hp.y - 20} fill="#374151" font-size="11" font-weight="600">
						{chartCurrency === 'parity' ? hp.value.toFixed(4) : '₺' + hp.value.toFixed(4)}
					</text>
					<text x={tooltipX + 112} y={hp.y - 20} text-anchor="end" fill="#9ca3af" font-size="10">
						{formatDateShort(hp.date)}
					</text>
				{/if}
			</svg>

			<!-- Legend -->
			<div class="flex items-center justify-center gap-6 mt-2 text-xs text-gray-500">
				{#if chartCurrency === 'parity'}
					<span class="flex items-center gap-1.5">
						<span class="w-4 h-0.5 bg-amber-500 rounded"></span> EUR/USD Parite
					</span>
				{:else}
					<span class="flex items-center gap-1.5">
						<span class="w-4 h-0.5 bg-teal-600 rounded"></span> Döviz Satış
					</span>
					<span class="flex items-center gap-1.5">
						<span class="w-4 h-0.5 bg-green-300 rounded"></span> Döviz Alış
					</span>
				{/if}
			</div>
		{/if}
	</div>

	<!-- ─── Tarihçe Tablosu ─── -->
	<div class="bg-white rounded-xl border border-gray-200">
		<!-- Tablo başlığı & filtreler -->
		<div class="flex flex-wrap items-center justify-between gap-2 sm:gap-3 p-3 sm:p-4 border-b border-gray-100">
			<h2 class="text-sm font-semibold text-gray-700">Kur Tarihçesi</h2>

			<div class="flex gap-1 bg-gray-100 rounded-lg p-0.5">
				{#each (['USD', 'EUR', 'GBP'] as const) as code}
					<button
						onclick={() => { historyCurrency = code; historyPage = 1; }}
						class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer
							{historyCurrency === code ? 'bg-white text-teal-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}"
					>
						{code}
					</button>
				{/each}
			</div>
		</div>

		{#if historyLoading}
			<div class="flex items-center justify-center py-12">
				<Loader2 size={24} class="animate-spin text-teal-600" />
			</div>
		{:else if historyItems.length === 0}
			<div class="text-center py-12 text-gray-500 text-sm">Veri bulunamadı</div>
		{:else}
			<!-- Desktop tablo -->
			<div class="hidden md:block overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="bg-gray-50 text-gray-500 text-xs">
							<th class="text-left px-4 py-2.5 font-medium">Tarih</th>
							<th class="text-right px-4 py-2.5 font-medium">Döviz Alış</th>
							<th class="text-right px-4 py-2.5 font-medium">Döviz Satış</th>
							<th class="text-right px-4 py-2.5 font-medium">Efektif Alış</th>
							<th class="text-right px-4 py-2.5 font-medium">Efektif Satış</th>
							<th class="text-center px-4 py-2.5 font-medium">Kaynak</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-50">
						{#each historyItems as item}
							<tr class="hover:bg-gray-50/50 transition-colors">
								<td class="px-4 py-2.5 text-gray-700 font-medium">{formatDate(item.date)}</td>
								<td class="px-4 py-2.5 text-right text-gray-600">{formatRate(item.forex_buying)}</td>
								<td class="px-4 py-2.5 text-right font-medium text-gray-800">{formatRate(item.forex_selling)}</td>
								<td class="px-4 py-2.5 text-right text-gray-500">{formatRate(item.banknote_buying)}</td>
								<td class="px-4 py-2.5 text-right text-gray-500">{formatRate(item.banknote_selling)}</td>
								<td class="px-4 py-2.5 text-center">
									{#if item.source === 'tcmb'}
										<span class="inline-flex items-center px-2 py-0.5 text-[10px] font-medium rounded-full bg-emerald-50 text-emerald-700">TCMB</span>
									{:else}
										<span class="inline-flex items-center px-2 py-0.5 text-[10px] font-medium rounded-full bg-gray-100 text-gray-500">Taşıma</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- Mobil kartlar -->
			<div class="md:hidden divide-y divide-gray-50">
				{#each historyItems as item}
					<div class="px-4 py-3">
						<div class="flex items-center justify-between mb-1.5">
							<span class="text-sm font-medium text-gray-700">{formatDate(item.date)}</span>
							{#if item.source === 'tcmb'}
								<span class="inline-flex items-center px-2 py-0.5 text-[10px] font-medium rounded-full bg-emerald-50 text-emerald-700">TCMB</span>
							{:else}
								<span class="inline-flex items-center px-2 py-0.5 text-[10px] font-medium rounded-full bg-gray-100 text-gray-500">Taşıma</span>
							{/if}
						</div>
						<div class="grid grid-cols-2 gap-2 text-xs">
							<div>
								<span class="text-gray-500">Döviz Alış</span>
								<div class="font-medium text-gray-600">{formatRate(item.forex_buying)}</div>
							</div>
							<div>
								<span class="text-gray-500">Döviz Satış</span>
								<div class="font-medium text-gray-800">{formatRate(item.forex_selling)}</div>
							</div>
							<div>
								<span class="text-gray-500">Efektif Alış</span>
								<div class="text-gray-500">{formatRate(item.banknote_buying)}</div>
							</div>
							<div>
								<span class="text-gray-500">Efektif Satış</span>
								<div class="text-gray-500">{formatRate(item.banknote_selling)}</div>
							</div>
						</div>
					</div>
				{/each}
			</div>

			<!-- Pagination -->
			{#if historyPages > 1}
				<div class="flex items-center justify-between px-4 py-3 border-t border-gray-100 text-sm">
					<span class="text-gray-500 text-xs">
						{historyTotal} kayıt, sayfa {historyPage}/{historyPages}
					</span>
					<div class="flex gap-2">
						<button
							onclick={() => historyPage = Math.max(1, historyPage - 1)}
							disabled={historyPage <= 1}
							class="px-3 py-1.5 text-xs rounded-lg border transition-colors cursor-pointer
								{historyPage <= 1 ? 'border-gray-100 text-gray-500 cursor-not-allowed' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}"
						>
							← Önceki
						</button>
						<button
							onclick={() => historyPage = Math.min(historyPages, historyPage + 1)}
							disabled={historyPage >= historyPages}
							class="px-3 py-1.5 text-xs rounded-lg border transition-colors cursor-pointer
								{historyPage >= historyPages ? 'border-gray-100 text-gray-500 cursor-not-allowed' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}"
						>
							Sonraki →
						</button>
					</div>
				</div>
			{/if}
		{/if}
	</div>

	{/if}
</div>
