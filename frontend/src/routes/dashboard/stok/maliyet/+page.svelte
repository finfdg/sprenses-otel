<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { formatCompact, formatCurrency } from '$lib/utils/finance';
	import { Package, ArrowDownToLine, Flame, Boxes, Building2, Truck } from 'lucide-svelte';

	const AY = ['', 'Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	function periodLabel(p: string): string {
		const [y, m] = (p || '').split('-');
		return `${AY[Number(m)] || m} ${y}`;
	}

	let loading = $state(true);
	let summary = $state<any>({});
	let departments = $state<any[]>([]);
	let trend = $state<any[]>([]);
	let suppliers = $state<any[]>([]);

	let maxDept = $derived(Math.max(1, ...departments.map((d) => d.total)));
	let maxTrend = $derived(Math.max(1, ...trend.flatMap((t) => [t.purchases, t.consumption])));
	let maxSup = $derived(Math.max(1, ...suppliers.map((s) => s.total)));

	async function load() {
		loading = true;
		try {
			const [s, d, t, sup] = await Promise.all([
				api.get<any>('/stok/summary'),
				api.get<any>('/stok/cost-by-department'),
				api.get<any>('/stok/monthly-trend'),
				api.get<any>('/stok/by-supplier?limit=12'),
			]);
			summary = s;
			departments = d.items || [];
			trend = t.items || [];
			suppliers = sup.items || [];
		} catch (e) {
			console.error('Stok maliyet yüklenemedi:', e);
		} finally {
			loading = false;
		}
	}
	onMount(load);
</script>

<svelte:head><title>Stok Maliyet · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader title="Stok Maliyet" description="Departman tüketimi, alım/tüketim trendi ve tedarikçi maliyetleri (Sedna muhasebeden). Üst bardaki 'Sedna' butonuyla güncellenir." />

	<!-- Özet kartları -->
	<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
		<StatCard label="Anlık Stok Değeri" value={formatCompact(summary.stock_value || 0, 'TRY')} accent="teal" icon={Package} hint={`${summary.in_stock_count || 0} / ${summary.product_count || 0} üründe stok`} />
		<StatCard label="Toplam Alım" value={formatCompact(summary.purchases_total || 0, 'TRY')} accent="blue" icon={ArrowDownToLine} hint="Tedarikçiden giriş" />
		<StatCard label="Toplam Tüketim" value={formatCompact(summary.consumption_total || 0, 'TRY')} accent="amber" icon={Flame} hint="Departman çıkışı" />
		<StatCard label="Depo / Departman" value={String(summary.depot_count || 0)} accent="gray" icon={Building2} hint={summary.last_period ? `Son dönem: ${periodLabel(summary.last_period)}` : ''} />
	</div>

	{#if loading}
		<div class="text-sm text-gray-400 py-10 text-center">Yükleniyor…</div>
	{:else}
		<!-- Departman tüketim maliyeti (hero) -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
			<div class="flex items-center gap-2 mb-4">
				<Flame size={18} class="text-amber-600" />
				<h3 class="text-sm font-semibold text-gray-800">Departman Bazında Tüketim Maliyeti</h3>
			</div>
			{#if departments.length === 0}
				<EmptyState icon={Flame} title="Tüketim verisi yok" message="Üst bardaki 'Sedna' butonuyla içe aktarın." />
			{:else}
				<div class="space-y-2.5">
					{#each departments as d (d.code)}
						<div class="flex items-center gap-3">
							<span class="w-40 sm:w-48 shrink-0 text-xs text-gray-700 truncate" title={d.name}>{d.name}</span>
							<div class="flex-1 h-5 bg-gray-100 rounded-md overflow-hidden">
								<div class="h-full bg-amber-400 rounded-md transition-all" style="width: {(d.total / maxDept) * 100}%"></div>
							</div>
							<span class="w-28 shrink-0 text-right text-xs font-semibold text-gray-800 tabular-nums">{formatCompact(d.total, 'TRY')}</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
			<!-- Aylık trend: alım vs tüketim -->
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-1">Aylık Alım vs Tüketim</h3>
				<div class="flex items-center gap-3 text-[11px] text-gray-500 mb-3">
					<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-blue-500"></span> Alım</span>
					<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-amber-400"></span> Tüketim</span>
				</div>
				<div class="space-y-2.5">
					{#each trend as t (t.period)}
						<div>
							<div class="flex justify-between text-[11px] text-gray-500 mb-0.5">
								<span>{periodLabel(t.period)}</span>
								<span class="tabular-nums">{formatCompact(t.purchases, 'TRY')} · <span class="text-amber-700">{formatCompact(t.consumption, 'TRY')}</span></span>
							</div>
							<div class="flex gap-1 h-3">
								<div class="bg-blue-500 rounded-sm" style="width: {(t.purchases / maxTrend) * 50}%"></div>
								<div class="bg-amber-400 rounded-sm" style="width: {(t.consumption / maxTrend) * 50}%"></div>
							</div>
						</div>
					{/each}
				</div>
			</div>

			<!-- Tedarikçi bazında alım -->
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
				<div class="flex items-center gap-2 mb-4">
					<Truck size={18} class="text-blue-600" />
					<h3 class="text-sm font-semibold text-gray-800">Tedarikçi Bazında Alım</h3>
				</div>
				{#if suppliers.length === 0}
					<p class="text-sm text-gray-400">Veri yok</p>
				{:else}
					<div class="space-y-2">
						{#each suppliers as s (s.code)}
							<div class="flex items-center gap-3">
								<span class="w-36 sm:w-44 shrink-0 text-xs text-gray-700 truncate" title={s.name}>{s.name}</span>
								<div class="flex-1 h-4 bg-gray-100 rounded-md overflow-hidden">
									<div class="h-full bg-blue-400 rounded-md" style="width: {(s.total / maxSup) * 100}%"></div>
								</div>
								<span class="w-24 shrink-0 text-right text-xs font-semibold text-gray-800 tabular-nums">{formatCompact(s.total, 'TRY')}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
