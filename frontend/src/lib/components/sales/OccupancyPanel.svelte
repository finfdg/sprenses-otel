<script lang="ts">
	// Doluluk sekmesi — basit tasarım (2026-07-19): aylık yatay barlar (gerçekleşen lacivert
	// + ileri rezervasyon çizgili pirinç) ↔ günlük görünüm (masaüstü sütun grafiği / mobil
	// satır listesi). Ay satırına tıklayınca o ayın günlük detayına inilir.
	// Veri: occupancy-overview (sayfadan prop) + /sales/reservations/daily-occupancy (yerel fetch).
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import Button from '$lib/components/Button.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { BedDouble } from 'lucide-svelte';
	import { eurCompact, FUTURE_STRIPE, MONTHS_FULL_TR, MONTHS_TR, WEEKDAYS_TR, trInt } from '$lib/utils/salesDesign';

	// ── Props ────────────────────────────────────────────────
	let {
		overview = null,
		loading = false,
		year,
		yearOpts,
		onYear,
	}: {
		overview: any;
		loading: boolean;
		year: number;
		yearOpts: number[];
		onYear: (y: number) => void;
	} = $props();

	// ── Sabitler ─────────────────────────────────────────────
	const VIEW_OPTS = [
		{ value: 'gunluk', label: 'Günlük' },
		{ value: 'aylik', label: 'Aylık' },
	];
	const MONTH_NUMS = Array.from({ length: 12 }, (_, i) => i + 1);

	// Karşılaştırma modunda önceki yıl barlarının renkleri (1. önceki yıl pirinç, 2. gri)
	const COMPARE_COLORS = ['bg-brass', 'bg-gray-400'];

	// ── State ────────────────────────────────────────────────
	let view = $state('aylik');
	let month = $state(new Date().getMonth() + 1);
	let dailyData = $state<any>(null);
	let dailyLoading = $state(false);
	// Yıl karşılaştırma (aylık görünüm): önceki 2 yılın occupancy-overview verisi
	let compare = $state(false);
	let compareLoading = $state(false);
	let compareYears = $state<any[]>([]); // verisi olan önceki yıllar (yeni→eski)
	const compareCache = new Map<number, any>(); // yıl → overview (geçmiş yıl verisi değişmez)

	// ── Türetilmiş ───────────────────────────────────────────
	let todayIso = $derived(overview?.today ?? '');
	let capacity = $derived(overview?.capacity ?? 0);
	let monthRows = $derived.by(() => {
		if (!overview) return [];
		return overview.months.map((m: any) => {
			const cap = Math.max(1, m.capacity_nights);
			return {
				...m,
				navyW: Math.min((m.past_nights / cap) * 100, 100),
				stripeW: Math.min((m.future_nights / cap) * 100, 100),
				pct: Math.round(m.occupancy_pct),
			};
		});
	});
	let dailyRows = $derived.by(() => {
		if (!dailyData) return [];
		return dailyData.days.map((d: any) => {
			const isToday = d.date === todayIso;
			const isFuture = todayIso && d.date > todayIso;
			const dow = new Date(d.date + 'T00:00:00').getDay();
			return {
				...d,
				day: Number(d.date.slice(8, 10)),
				dow,
				weekend: dow === 0 || dow === 6,
				isToday,
				isFuture,
				h: Math.min(100, Math.max(2, d.occupancy_pct)),
				over: d.room_nights > d.capacity ? d.room_nights - d.capacity : 0,
			};
		});
	});

	// ── Veri fonksiyonları ───────────────────────────────────
	// Karşılaştırma: önceki 2 yılın overview'u (verisi olmayan yıl gösterilmez)
	async function loadCompare() {
		compareLoading = true;
		try {
			const wanted = [year - 1, year - 2];
			const results = await Promise.all(
				wanted.map(async (y) => {
					if (compareCache.has(y)) return compareCache.get(y);
					const d = await api.get<any>(`/sales/reservations/occupancy-overview?year=${y}`);
					compareCache.set(y, d);
					return d;
				}),
			);
			compareYears = results.filter((d) => d && d.year_room_nights > 0);
		} catch (e) {
			console.error('Karşılaştırma verisi yüklenemedi:', e);
			showToast('Karşılaştırma verisi yüklenemedi', 'error');
		} finally {
			compareLoading = false;
		}
	}

	async function loadDaily() {
		dailyLoading = true;
		try {
			const mk = `${year}-${String(month).padStart(2, '0')}`;
			dailyData = await api.get<any>(`/sales/reservations/daily-occupancy?month=${mk}`);
		} catch (e) {
			console.error('Günlük doluluk yüklenemedi:', e);
			showToast('Günlük doluluk yüklenemedi', 'error');
		} finally {
			dailyLoading = false;
		}
	}

	// Günlük görünümdeyken ay/yıl değişince yeniden çek
	$effect(() => {
		const _v = view, _m = month, _y = year;
		if (_v !== 'gunluk') return;
		loadDaily();
	});

	// Karşılaştırma açıkken yıl değişince önceki yılları yeniden çek
	$effect(() => {
		const _y = year;
		if (!compare) return;
		loadCompare();
	});

	// ── UI yardımcıları ──────────────────────────────────────
	function openMonth(m: number) {
		month = m;
		view = 'gunluk';
	}

	/** Karşılaştırma satırı: önceki yılın aynı ayı için bar verisi. */
	function compMonth(cy: any, mNum: number) {
		const cm = cy.months[mNum - 1] ?? { room_nights: 0, capacity_nights: 1, occupancy_pct: 0, eur: 0 };
		return {
			...cm,
			w: Math.min((cm.room_nights / Math.max(1, cm.capacity_nights)) * 100, 100),
			pct: Math.round(cm.occupancy_pct),
		};
	}
</script>

<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
	<!-- Başlık + kontroller -->
	<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
		<h2 class="text-base font-semibold text-gray-900">
			{view === 'aylik' ? `${year} Aylık Doluluk` : `Günlük Doluluk — ${MONTHS_FULL_TR[month - 1]} ${year}`}
		</h2>
		<div class="flex flex-wrap items-center gap-2.5">
			{#if view === 'aylik'}
				<Button
					size="sm"
					variant={compare ? 'primary' : 'secondary'}
					onclick={() => (compare = !compare)}
					title="Önceki iki yılın doluluk ve cirosunu aynı grafikte göster"
				>Karşılaştır</Button>
			{/if}
			{#if view === 'gunluk'}
				<select
					value={month}
					onchange={(e) => (month = Number((e.currentTarget as HTMLSelectElement).value))}
					aria-label="Ay"
					class="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm focus:ring-2 focus:ring-teal-500"
				>
					{#each MONTH_NUMS as m}<option value={m}>{MONTHS_FULL_TR[m - 1]}</option>{/each}
				</select>
			{/if}
			<select
				value={year}
				onchange={(e) => onYear(Number((e.currentTarget as HTMLSelectElement).value))}
				aria-label="Yıl"
				class="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm focus:ring-2 focus:ring-teal-500"
			>
				{#each yearOpts as y}<option value={y}>{y}</option>{/each}
			</select>
			<SegmentedControl options={VIEW_OPTS} value={view} onchange={(v) => (view = v)} ariaLabel="Görünüm" size="sm" />
		</div>
	</div>

	<!-- Lejant -->
	<div class="mb-4 flex flex-wrap gap-x-4 gap-y-2 text-xs text-gray-600">
		<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-sm bg-teal-700"></span>{compare && view === 'aylik' ? `${year} Gerçekleşen` : 'Gerçekleşen'}</span>
		<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-sm" style="background:{FUTURE_STRIPE}"></span>{compare && view === 'aylik' ? `${year} İleri rezervasyon` : 'İleri rezervasyon'}</span>
		{#if compare && view === 'aylik'}
			{#each compareYears as cy, i (cy.year)}
				<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-sm {COMPARE_COLORS[i] ?? 'bg-gray-400'}"></span>{cy.year}</span>
			{/each}
		{/if}
		<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-white ring-2 ring-red-600"></span>Bugün</span>
	</div>

	{#if loading && !overview}
		<TableSkeleton rows={8} columns={3} />
	{:else if !overview || capacity === 0}
		<EmptyState icon={BedDouble} title="Kapasite tanımsız" description="Doluluk için önce Oda Tipleri sekmesinden aktif oda tipleri ve oda sayıları tanımlanmalıdır." />
	{:else if view === 'aylik'}
		<!-- Aylık yatay barlar (karşılaştırma açıkken her ayın altında önceki yılların barları) -->
		<div class="flex flex-col {compare ? 'gap-3' : 'gap-1.5'}">
			{#each monthRows as m (m.month)}
				<div class="flex flex-col gap-0.5">
					<button
						type="button"
						class="flex w-full items-center gap-3 rounded-xl px-1.5 py-1 text-left hover:bg-gray-50"
						title="{MONTHS_FULL_TR[m.month - 1]} {year} — %{m.pct} doluluk · {eurCompact(m.eur)} ciro · günlük görünüm için tıklayın"
						onclick={() => openMonth(m.month)}
					>
						<span class="w-9 shrink-0 text-xs font-semibold tabular-nums text-gray-600">{MONTHS_TR[m.month - 1]}</span>
						<span class="relative flex h-6 min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
							<span class="h-full bg-teal-700" style="width:{m.navyW.toFixed(1)}%"></span>
							<span class="h-full" style="width:{m.stripeW.toFixed(1)}%;background:{FUTURE_STRIPE}"></span>
							<span
								class="pointer-events-none absolute inset-0 hidden items-center px-3 text-[11px] font-medium tabular-nums sm:flex {m.navyW >= 30 ? 'text-white' : 'text-gray-600'}"
							>{trInt(m.room_nights)} oda-gece{m.eur > 0 ? ` · ${eurCompact(m.eur)}` : ''}</span>
						</span>
						<span class="w-14 shrink-0 text-right sm:w-28">
							<span class="block text-[13px] font-semibold tabular-nums text-teal-700">%{m.pct}</span>
							<span class="hidden text-[10.5px] tabular-nums text-gray-500 sm:block">{trInt(m.room_nights)}/{trInt(m.capacity_nights)} gece</span>
							{#if m.eur > 0}
								<span class="block text-[9.5px] tabular-nums text-gray-500 sm:hidden">{eurCompact(m.eur)}</span>
							{/if}
						</span>
					</button>
					{#if compare}
						{#each compareYears as cy, i (cy.year)}
							{@const cm = compMonth(cy, m.month)}
							<div
								class="flex w-full items-center gap-3 px-1.5"
								title="{MONTHS_FULL_TR[m.month - 1]} {cy.year} — %{cm.pct} doluluk · {eurCompact(cm.eur)} ciro"
							>
								<span class="w-9 shrink-0 text-right text-[10px] font-medium tabular-nums text-gray-500">{cy.year}</span>
								<span class="relative flex h-4 min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
									<span class="h-full {COMPARE_COLORS[i] ?? 'bg-gray-400'}" style="width:{cm.w.toFixed(1)}%"></span>
									<span class="pointer-events-none absolute inset-0 hidden items-center px-3 text-[10px] font-medium tabular-nums text-gray-900 sm:flex">
										{trInt(cm.room_nights)} oda-gece{cm.eur > 0 ? ` · ${eurCompact(cm.eur)}` : ''}
									</span>
								</span>
								<span class="w-14 shrink-0 text-right sm:w-28">
									<span class="block text-[11px] font-semibold tabular-nums text-gray-600">%{cm.pct}</span>
									{#if cm.eur > 0}
										<span class="block text-[9.5px] tabular-nums text-gray-500 sm:hidden">{eurCompact(cm.eur)}</span>
									{/if}
								</span>
							</div>
						{/each}
					{/if}
				</div>
			{/each}
		</div>
		{#if compare && compareLoading && compareYears.length === 0}
			<p class="mt-3 text-xs text-gray-500">Karşılaştırma verisi yükleniyor…</p>
		{:else if compare && !compareLoading && compareYears.length === 0}
			<p class="mt-3 text-xs text-gray-500">{year - 2}–{year - 1} yıllarına ait rezervasyon verisi bulunamadı.</p>
		{/if}
		<p class="mt-3 text-xs text-gray-500">Bir ayın satırına tıklayarak günlük detayına inebilirsiniz.</p>
	{:else if dailyLoading && !dailyData}
		<TableSkeleton rows={8} columns={3} />
	{:else if dailyData}
		<!-- Günlük: masaüstü sütun grafiği -->
		<div class="hidden sm:block">
			<div class="relative">
				<div class="pointer-events-none absolute inset-x-0 top-0 border-t border-dashed border-gray-300"></div>
				<div class="pointer-events-none absolute inset-x-0 top-[85px] border-t border-dashed border-gray-200"></div>
				<div class="pointer-events-none absolute inset-x-0 top-[170px] border-t border-gray-300"></div>
				<div class="relative flex h-[170px] items-end gap-[3px]">
					{#each dailyRows as d (d.date)}
						<div class="relative flex h-full min-w-0 flex-1 items-end">
							<span
								class="pointer-events-none absolute -left-1.5 -right-1.5 text-center text-[8.5px] font-semibold tabular-nums whitespace-nowrap {d.over > 0 ? 'text-red-700' : 'text-gray-500'}"
								style="bottom:calc({d.h.toFixed(1)}% + 3px)"
							>{d.over > 0 ? '+' + trInt(d.over) : trInt(d.empty)}</span>
							<div
								class="relative w-full overflow-hidden rounded-t-[3px] {d.isToday ? 'ring-2 ring-red-600' : ''} {d.isFuture ? '' : 'bg-teal-700'}"
								style="height:{d.h.toFixed(1)}%;{d.isFuture ? `background:${FUTURE_STRIPE}` : ''}"
								title="{d.day} {MONTHS_FULL_TR[month - 1]} {year} — %{Math.round(d.occupancy_pct)} · {d.room_nights}/{d.capacity} oda · {eurCompact(d.eur)} ciro"
							>
								{#if d.eur > 0 && d.h >= 40}
									<span
										class="pointer-events-none absolute bottom-1 left-1/2 text-[8.5px] font-medium tabular-nums whitespace-nowrap {d.isFuture ? 'text-[#43350a]' : 'text-white/90'}"
										style="writing-mode: vertical-rl; transform: translateX(-50%) rotate(180deg);"
									>{eurCompact(d.eur)}</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
				<div class="mt-1.5 flex gap-[3px]">
					{#each dailyRows as d (d.date)}
						<div class="min-w-0 flex-1 overflow-hidden text-center">
							<span class="text-[10px] tabular-nums {d.isToday ? 'font-bold text-brass-dark' : 'font-medium text-gray-500'}">{d.day}</span>
						</div>
					{/each}
				</div>
			</div>
		</div>
		<!-- Günlük: mobil satır listesi -->
		<div class="flex flex-col gap-1 sm:hidden">
			{#each dailyRows as d (d.date)}
				<div
					class="flex items-center gap-2 rounded-lg px-1 py-0.5 {d.isToday ? 'bg-brass-soft' : ''}"
					title="{d.day} {MONTHS_FULL_TR[month - 1]} {year} — %{Math.round(d.occupancy_pct)} · {d.room_nights}/{d.capacity} oda · {eurCompact(d.eur)} ciro"
				>
					<span class="w-[52px] shrink-0 text-[10.5px] tabular-nums {d.isToday ? 'font-bold text-brass-dark' : d.weekend ? 'font-medium text-gray-600' : 'font-medium text-gray-500'}">{d.day} {WEEKDAYS_TR[d.dow]}</span>
					<span class="relative h-4 min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
						<span class="block h-full rounded-full {d.isFuture ? '' : 'bg-teal-700'}" style="width:{Math.max(2, d.occupancy_pct).toFixed(1)}%;{d.isFuture ? `background:${FUTURE_STRIPE}` : ''}"></span>
						{#if d.over > 0}
							<span class="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-red-600 px-1.5 py-px text-[9.5px] font-semibold tabular-nums whitespace-nowrap text-white">{trInt(d.over)} fazla</span>
						{:else}
							<span class="absolute right-2 top-1/2 -translate-y-1/2 text-[9.5px] font-semibold tabular-nums whitespace-nowrap {d.occupancy_pct > 88 ? 'text-white' : 'text-gray-600'}">{trInt(d.empty)} boş</span>
						{/if}
					</span>
					<span class="w-12 shrink-0 text-right">
						<span class="block text-[11px] font-semibold tabular-nums text-teal-700">%{Math.round(d.occupancy_pct)}</span>
						{#if d.eur > 0}
							<span class="block text-[8.5px] tabular-nums text-gray-500">{eurCompact(d.eur)}</span>
						{/if}
					</span>
				</div>
			{/each}
		</div>
		<p class="mt-3 text-right text-xs tabular-nums text-gray-500">
			Ay ortalaması %{Math.round(dailyData.avg_occupancy_pct)} · üstteki sayı boş (kırmızı: fazla) odadır
		</p>
	{/if}
</div>
