<script lang="ts">
	// Doluluk sekmesi — basit tasarım (2026-07-19): aylık yatay barlar (gerçekleşen lacivert
	// + ileri rezervasyon çizgili pirinç) ↔ günlük görünüm (masaüstü sütun grafiği / mobil
	// satır listesi). Ay satırına tıklayınca o ayın günlük detayına inilir.
	// Veri: occupancy-overview (sayfadan prop) + /sales/reservations/daily-occupancy (yerel fetch).
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { BedDouble } from 'lucide-svelte';
	import { FUTURE_STRIPE, MONTHS_FULL_TR, MONTHS_TR, WEEKDAYS_TR, trInt } from '$lib/utils/salesDesign';

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

	// ── State ────────────────────────────────────────────────
	let view = $state('aylik');
	let month = $state(new Date().getMonth() + 1);
	let dailyData = $state<any>(null);
	let dailyLoading = $state(false);

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

	// ── UI yardımcıları ──────────────────────────────────────
	function openMonth(m: number) {
		month = m;
		view = 'gunluk';
	}
</script>

<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
	<!-- Başlık + kontroller -->
	<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
		<h2 class="text-base font-semibold text-gray-900">
			{view === 'aylik' ? `${year} Aylık Doluluk` : `Günlük Doluluk — ${MONTHS_FULL_TR[month - 1]} ${year}`}
		</h2>
		<div class="flex flex-wrap items-center gap-2.5">
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
		<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-sm bg-teal-700"></span>Gerçekleşen</span>
		<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-sm" style="background:{FUTURE_STRIPE}"></span>İleri rezervasyon</span>
		<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-white ring-2 ring-red-600"></span>Bugün</span>
	</div>

	{#if loading && !overview}
		<TableSkeleton rows={8} columns={3} />
	{:else if !overview || capacity === 0}
		<EmptyState icon={BedDouble} title="Kapasite tanımsız" description="Doluluk için önce Oda Tipleri sekmesinden aktif oda tipleri ve oda sayıları tanımlanmalıdır." />
	{:else if view === 'aylik'}
		<!-- Aylık yatay barlar -->
		<div class="flex flex-col gap-1.5">
			{#each monthRows as m (m.month)}
				<button
					type="button"
					class="flex w-full items-center gap-3 rounded-xl px-1.5 py-1 text-left hover:bg-gray-50"
					title="{MONTHS_FULL_TR[m.month - 1]} {year} — %{m.pct} doluluk · günlük görünüm için tıklayın"
					onclick={() => openMonth(m.month)}
				>
					<span class="w-9 shrink-0 text-xs font-semibold tabular-nums text-gray-600">{MONTHS_TR[m.month - 1]}</span>
					<span class="relative flex h-6 min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
						<span class="h-full bg-teal-700" style="width:{m.navyW.toFixed(1)}%"></span>
						<span class="h-full" style="width:{m.stripeW.toFixed(1)}%;background:{FUTURE_STRIPE}"></span>
						<span
							class="pointer-events-none absolute inset-0 hidden items-center px-3 text-[11px] font-medium tabular-nums sm:flex {m.navyW >= 20 ? 'text-white' : 'text-gray-600'}"
						>{trInt(m.room_nights)} oda-gece</span>
					</span>
					<span class="w-14 shrink-0 text-right sm:w-28">
						<span class="block text-[13px] font-semibold tabular-nums text-teal-700">%{m.pct}</span>
						<span class="hidden text-[10.5px] tabular-nums text-gray-500 sm:block">{trInt(m.room_nights)}/{trInt(m.capacity_nights)} gece</span>
					</span>
				</button>
			{/each}
		</div>
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
								class="w-full rounded-t-[3px] {d.isToday ? 'ring-2 ring-red-600' : ''} {d.isFuture ? '' : 'bg-teal-700'}"
								style="height:{d.h.toFixed(1)}%;{d.isFuture ? `background:${FUTURE_STRIPE}` : ''}"
								title="{d.day} {MONTHS_FULL_TR[month - 1]} {year} — %{Math.round(d.occupancy_pct)} · {d.room_nights}/{d.capacity} oda"
							></div>
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
					title="{d.day} {MONTHS_FULL_TR[month - 1]} {year} — %{Math.round(d.occupancy_pct)} · {d.room_nights}/{d.capacity} oda"
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
					<span class="w-9 shrink-0 text-right text-[11px] font-semibold tabular-nums text-teal-700">%{Math.round(d.occupancy_pct)}</span>
				</div>
			{/each}
		</div>
		<p class="mt-3 text-right text-xs tabular-nums text-gray-500">
			Ay ortalaması %{Math.round(dailyData.avg_occupancy_pct)} · üstteki sayı boş (kırmızı: fazla) odadır
		</p>
	{/if}
</div>
