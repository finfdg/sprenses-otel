<script lang="ts">
	import { api } from '$lib/api';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { BROADCAST_MODULE } from '$lib/constants/realtime';
	import { showToast } from '$lib/stores/toast.svelte';
	import { useLiveRefetch } from '$lib/utils/liveRefetch.svelte';
	import {
		AlarmClock,
		Building2,
		CalendarRange,
		FileText,
		Hotel,
		Inbox,
		Landmark,
		WalletCards,
	} from 'lucide-svelte';

	// ── Type / interface tanımları ───────────────────────────
	type Metrics = {
		advance_received: number;
		advance_applied: number;
		collections: number;
		reservation_amount: number;
		invoiced_amount: number;
		reservation_count: number;
		overdue: number;
		open_due: number;
		projected_gross: number;
		projected_advance: number;
		projected_due: number;
		month_end_receivable: number;
	};

	type AgencyRow = {
		agency_id: number;
		agency: string;
		color: string;
		term_days: number;
		totals: Metrics;
	};
	type Report = {
		year: number;
		today: string;
		currency: string;
		eur_rate: number;
		last_advance_sync_at: string | null;
		totals: Metrics;
		agencies: AgencyRow[];
		source_counts: Record<string, number>;
	};

	// ── Sabitler ─────────────────────────────────────────────
	const NOW = new Date();
	const NOW_YEAR = NOW.getFullYear();
	const YEARS = [NOW_YEAR - 2, NOW_YEAR - 1, NOW_YEAR, NOW_YEAR + 1];
	const EMPTY_METRICS: Metrics = {
		advance_received: 0,
		advance_applied: 0,
		collections: 0,
		reservation_amount: 0,
		invoiced_amount: 0,
		reservation_count: 0,
		overdue: 0,
		open_due: 0,
		projected_gross: 0,
		projected_advance: 0,
		projected_due: 0,
		month_end_receivable: 0,
	};

	// ── State ────────────────────────────────────────────────
	let year = $state(NOW_YEAR);
	let selectedAgency = $state('all');
	let loading = $state(true);
	let data = $state<Report | null>(null);

	// ── Türetilmiş ───────────────────────────────────────────
	let rows = $derived.by(() => {
		const agencies = data?.agencies ?? [];
		return agencies
			.filter((agency) => selectedAgency === 'all' || String(agency.agency_id) === selectedAgency)
			.map((agency) => ({
				...agency,
				metrics: agency.totals,
			}));
	});

	let activeTotals = $derived.by(() => {
		const totals = { ...EMPTY_METRICS };
		for (const row of rows) {
			for (const key of Object.keys(EMPTY_METRICS) as (keyof Metrics)[]) {
				totals[key] += row.metrics[key];
			}
		}
		return totals;
	});

	let periodLabel = $derived(`${year} yılı`);

	// ── Formatlama ───────────────────────────────────────────
	function euro(value: number): string {
		return new Intl.NumberFormat('tr-TR', {
			style: 'currency',
			currency: 'EUR',
			maximumFractionDigits: 0,
		}).format(value || 0);
	}

	function syncLabel(value: string | null): string {
		if (!value) return 'Avans detayı henüz senkronlanmadı';
		const d = new Date(value);
		if (Number.isNaN(d.getTime())) return 'Sedna senkron zamanı bilinmiyor';
		return `Sedna avans hareketleri: ${d.toLocaleString('tr-TR')}`;
	}

	// ── Veri fonksiyonları ───────────────────────────────────
	async function load() {
		loading = true;
		try {
			data = await api.get<Report>(`/sales/acente-finans/?year=${year}`);
			if (selectedAgency !== 'all' && !data.agencies.some((a) => String(a.agency_id) === selectedAgency)) {
				selectedAgency = 'all';
			}
		} catch (error) {
			console.error('Acente finansal takip raporu yüklenemedi:', error);
			showToast('Acente finansal takip raporu yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	// ── Canlı yenileme ───────────────────────────────────────
	useLiveRefetch({
		modules: [
			BROADCAST_MODULE.SALES_INVOICES,
			BROADCAST_MODULE.EXCHANGE_RATES,
			BROADCAST_MODULE.HAKEDIS,
		],
		salesModules: [BROADCAST_MODULE.HOTEL_RESERVATION, BROADCAST_MODULE.AGENCY_GROUPS],
		reload: load,
	});

	// Yıl değişince raporu yenile.
	$effect(() => {
		const _year = year;
		void load();
	});
</script>

<svelte:head><title>Acente Finansal Takip · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader
		title="Acente Finansal Takip"
		description="Sedna avans ve tahsilatları, PMS rezervasyonları ve hak ediş vadeleri yıllık acente görünümünde."
	>
		{#snippet actions()}
			<select
				value={year}
				onchange={(event) => (year = Number((event.currentTarget as HTMLSelectElement).value))}
				aria-label="Rapor yılı"
				class="rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm font-medium focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20"
			>
				{#each YEARS as option}<option value={option}>{option}</option>{/each}
			</select>
		{/snippet}
	</PageHeader>

	{#if loading && !data}
		<div class="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
			{#each Array(6) as _}<div class="h-32 animate-pulse rounded-2xl bg-gray-100"></div>{/each}
		</div>
		<TableSkeleton rows={7} columns={7} />
	{:else if !data}
		<EmptyState icon={Inbox} title="Rapor oluşturulamadı" description="Sedna ve PMS verileri okunamadı." />
	{:else}
		<!-- Yıllık rapor ve acente filtresi -->
		<div class="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<label class="flex min-w-[240px] items-center gap-2 text-sm text-gray-600">
						<Building2 size={17} class="text-teal-700" />
						<span class="shrink-0">Acente</span>
						<select
							bind:value={selectedAgency}
							class="min-w-0 flex-1 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm focus:ring-2 focus:ring-teal-500/20"
						>
							<option value="all">Tüm acenteler</option>
							{#each data.agencies as agency (agency.agency_id)}
								<option value={String(agency.agency_id)}>{agency.agency}</option>
							{/each}
						</select>
				</label>
				<span class="text-xs text-gray-500">{periodLabel} · EUR/TL kuru {data.eur_rate.toLocaleString('tr-TR')}</span>
			</div>
		</div>

		<!-- Yıllık KPI'lar -->
		<div class="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
			<StatCard icon={WalletCards} accent="teal" label="Alınan Avans" value={euro(activeTotals.advance_received)} hint={`Mahsup: ${euro(activeTotals.advance_applied)}`} />
			<StatCard icon={Landmark} accent="emerald" label="Haricen Tahsilat" value={euro(activeTotals.collections)} hint="340 virmanları hariç" />
			<StatCard icon={Hotel} accent="blue" label="Rezervasyon Cirosu" value={euro(activeTotals.reservation_amount)} hint={`${activeTotals.reservation_count.toLocaleString('tr-TR')} rezervasyon`} />
			<StatCard icon={FileText} accent="gray" label="Kesilen Fatura" value={euro(activeTotals.invoiced_amount)} hint="Seçili yıldaki brüt tutar" />
			<StatCard icon={AlarmClock} accent={activeTotals.overdue > 0 ? 'red' : 'gray'} label="Vadesi Geçen Hak Ediş" value={activeTotals.overdue > 0 ? euro(activeTotals.overdue) : '—'} hint="Bekleyen avans mahsubu sonrası" />
			<StatCard icon={CalendarRange} accent="amber" label="Yıllık Alınacak Hak Ediş" value={euro(activeTotals.month_end_receivable)} hint={`Gerçek ${euro(activeTotals.open_due)} · tahmini ${euro(activeTotals.projected_due)}`} />
		</div>

		<!-- Yıllık acente tablosu -->
		<div class="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
			<div class="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 px-4 py-3 sm:px-5">
				<div>
					<h2 class="text-sm font-semibold text-gray-900">{periodLabel} · Acente Kırılımı</h2>
					<p class="mt-0.5 text-xs text-gray-500">Kullanılmamış avans önce açık faturalara, kalanı ileri rezervasyonlara FIFO mahsup edilir.</p>
				</div>
				<span class="text-xs text-gray-500">{syncLabel(data.last_advance_sync_at)}</span>
			</div>

			{#if data.source_counts.advance_transactions === 0}
				<div class="border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-800">
					Sedna 340 hareket detayı ilk senkronu bekliyor. Yıllık alınan ve mahsup edilen avans toplamları senkrondan sonra dolacaktır.
				</div>
			{/if}

			{#if loading}
				<div class="p-4"><TableSkeleton rows={6} columns={7} /></div>
			{:else if rows.length === 0}
				<div class="p-8"><EmptyState icon={Inbox} title="Bu yılda kayıt yok" description="Seçili yıl veya acente için finansal hareket bulunamadı." /></div>
			{:else}
				<div class="hidden overflow-x-auto md:block">
					<table class="min-w-[1160px] w-full text-sm">
						<thead class="bg-gray-50 text-left text-[11px] uppercase tracking-wide text-gray-500">
							<tr>
								<th class="px-5 py-3 font-semibold">Acente</th>
								<th class="px-4 py-3 text-right font-semibold">Alınan Avans</th>
								<th class="px-4 py-3 text-right font-semibold">Tahsilat</th>
								<th class="px-4 py-3 text-right font-semibold">Rezervasyon</th>
								<th class="px-4 py-3 text-right font-semibold">Kesilen Fatura</th>
								<th class="px-4 py-3 text-right font-semibold">Vadesi Geçen</th>
								<th class="px-5 py-3 text-right font-semibold">Yıllık Hak Ediş</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-100">
							{#each rows as row (row.agency_id)}
								<tr class="hover:bg-gray-50/80">
									<td class="px-5 py-3">
										<div class="flex items-center gap-2.5">
											<span class="h-2.5 w-2.5 shrink-0 rounded-full" style={`background:${row.color}`}></span>
											<span><span class="block font-semibold text-gray-800">{row.agency}</span><span class="text-[11px] text-gray-500">{row.term_days === 0 ? 'Peşin' : `${row.term_days} gün vade`}</span></span>
										</div>
									</td>
									<td class="px-4 py-3 text-right tabular-nums">
										<span class="font-semibold text-teal-700">{euro(row.metrics.advance_received)}</span>
										{#if row.metrics.advance_applied > 0}<span class="block text-[11px] text-gray-500">mahsup {euro(row.metrics.advance_applied)}</span>{/if}
									</td>
									<td class="px-4 py-3 text-right font-semibold tabular-nums text-emerald-700">{euro(row.metrics.collections)}</td>
									<td class="px-4 py-3 text-right tabular-nums"><span class="font-semibold text-gray-800">{euro(row.metrics.reservation_amount)}</span><span class="block text-[11px] text-gray-500">{row.metrics.reservation_count} rezervasyon</span></td>
									<td class="px-4 py-3 text-right font-semibold tabular-nums text-indigo-700">{euro(row.metrics.invoiced_amount)}</td>
									<td class="px-4 py-3 text-right font-semibold tabular-nums {row.metrics.overdue > 0 ? 'text-red-700' : 'text-gray-400'}">{row.metrics.overdue > 0 ? euro(row.metrics.overdue) : '—'}</td>
									<td class="px-5 py-3 text-right tabular-nums"><span class="font-bold text-amber-700">{euro(row.metrics.month_end_receivable)}</span><span class="block text-[11px] text-gray-500">gerçek {euro(row.metrics.open_due)} · tahmini {euro(row.metrics.projected_due)}</span></td>
								</tr>
							{/each}
						</tbody>
						<tfoot class="border-t-2 border-gray-200 bg-gray-50 font-semibold">
							<tr>
								<td class="px-5 py-3 text-gray-800">Toplam</td>
								<td class="px-4 py-3 text-right tabular-nums text-teal-700">{euro(activeTotals.advance_received)}</td>
								<td class="px-4 py-3 text-right tabular-nums text-emerald-700">{euro(activeTotals.collections)}</td>
								<td class="px-4 py-3 text-right tabular-nums">{euro(activeTotals.reservation_amount)}</td>
								<td class="px-4 py-3 text-right tabular-nums text-indigo-700">{euro(activeTotals.invoiced_amount)}</td>
								<td class="px-4 py-3 text-right tabular-nums text-red-700">{euro(activeTotals.overdue)}</td>
								<td class="px-5 py-3 text-right tabular-nums text-amber-700">{euro(activeTotals.month_end_receivable)}</td>
							</tr>
						</tfoot>
					</table>
				</div>

				<div class="divide-y divide-gray-100 md:hidden">
					{#each rows as row (row.agency_id)}
						<article class="p-4">
							<div class="mb-3 flex items-center justify-between gap-3">
								<div class="flex min-w-0 items-center gap-2"><span class="h-2.5 w-2.5 shrink-0 rounded-full" style={`background:${row.color}`}></span><h3 class="truncate text-sm font-semibold text-gray-900">{row.agency}</h3></div>
								<span class="shrink-0 text-[11px] text-gray-500">{row.term_days === 0 ? 'Peşin' : `${row.term_days} gün`}</span>
							</div>
							<div class="grid grid-cols-2 gap-x-5 gap-y-2 text-xs">
								<div><span class="block text-gray-500">Alınan avans</span><strong class="text-teal-700">{euro(row.metrics.advance_received)}</strong></div>
								<div class="text-right"><span class="block text-gray-500">Tahsilat</span><strong class="text-emerald-700">{euro(row.metrics.collections)}</strong></div>
								<div><span class="block text-gray-500">Rezervasyon</span><strong>{euro(row.metrics.reservation_amount)}</strong><span class="ml-1 text-gray-500">· {row.metrics.reservation_count}</span></div>
								<div class="text-right"><span class="block text-gray-500">Kesilen fatura</span><strong class="text-indigo-700">{euro(row.metrics.invoiced_amount)}</strong></div>
								<div><span class="block text-gray-500">Vadesi geçen</span><strong class={row.metrics.overdue > 0 ? 'text-red-700' : 'text-gray-400'}>{row.metrics.overdue > 0 ? euro(row.metrics.overdue) : '—'}</strong></div>
							</div>
							<div class="mt-3 flex items-end justify-between rounded-xl bg-amber-50 px-3 py-2">
								<span class="text-xs text-amber-900">Yıllık alınacak hak ediş<br /><small class="text-amber-700">Gerçek {euro(row.metrics.open_due)} · tahmini {euro(row.metrics.projected_due)}</small></span>
								<strong class="text-sm tabular-nums text-amber-800">{euro(row.metrics.month_end_receivable)}</strong>
							</div>
						</article>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
