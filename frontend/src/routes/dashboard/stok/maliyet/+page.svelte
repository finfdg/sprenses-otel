<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { formatCompact, formatCurrency } from '$lib/utils/finance';
	import { Flame, BedDouble, Repeat, Trash2, Package, Truck, TrendingUp, Info, TriangleAlert } from 'lucide-svelte';

	const AY = ['', 'Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const periodLabel = (p: string) => { const [y, m] = (p || '').split('-'); return `${AY[Number(m)] || m} ${y}`; };
	const GROUP_COLOR: Record<string, string> = {
		fb: 'bg-amber-400', rooms: 'bg-teal-400', staff: 'bg-violet-400', technical: 'bg-blue-400',
		waste: 'bg-red-400', capex: 'bg-gray-300', overhead: 'bg-gray-400', main: 'bg-gray-300',
	};

	let loading = $state(true);
	let op = $state<any>({});
	let summary = $state<any>({});
	let suppliers = $state<any[]>([]);
	let variance = $state<any[]>([]);
	let anomalies = $state<any[]>([]);

	let kpi = $derived(op.kpi || {});
	let occ = $derived(op.occupancy || {});
	let byGroup = $derived(op.by_group || []);
	let monthly = $derived(op.monthly || []);
	let maxGroup = $derived(Math.max(1, ...byGroup.map((g: any) => g.total)));
	let maxMonthCons = $derived(Math.max(1, ...monthly.map((m: any) => m.fb_consumption)));
	let maxSup = $derived(Math.max(1, ...suppliers.map((s: any) => s.total)));

	async function load() {
		loading = true;
		try {
			const [o, s, sup, v] = await Promise.all([
				api.get<any>('/stok/operational-kpi'),
				api.get<any>('/stok/summary'),
				api.get<any>('/stok/by-supplier?limit=10'),
				api.get<any>('/stok/price-variance?limit=8'),
			]);
			op = o; summary = s; suppliers = sup.items || []; variance = v.items || []; anomalies = v.anomalies || [];
		} catch (e) {
			console.error('Maliyet kontrol yüklenemedi:', e);
		} finally {
			loading = false;
		}
	}
	onMount(load);
</script>

<svelte:head><title>Maliyet Kontrol · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader title="Maliyet Kontrol" description="Operasyonel maliyet ↔ doluluk füzyonu: kişi başı F&B maliyeti, CPOR, fiyat sapması, departman tüketimi (Sedna stok + rezervasyon)." />

	{#if loading}
		<div class="py-12 text-center text-gray-500 text-sm">Yükleniyor…</div>
	{:else}
		<!-- Operasyonel KPI kartları -->
		<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
			<StatCard label="Kişi Başı F&B Maliyeti" value={`${(kpi.cost_per_guest_night_try ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺`} accent="amber" icon={Flame} hint={`/gece · ${kpi.cost_per_guest_night_eur ?? '–'} €`} />
			<StatCard label="CPOR" value={`${(kpi.cpor_try ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺`} accent="teal" icon={BedDouble} hint="Oda-gece başı" />
			<StatCard label="Stok Devir Hızı" value={`${kpi.inventory_turnover ?? 0}x`} accent="blue" icon={Repeat} hint="Tüketim / stok değeri" />
			<StatCard label="Zayiat %" value={`%${kpi.waste_pct ?? 0}`} accent={kpi.waste_pct ? 'red' : 'gray'} icon={Trash2} hint={kpi.waste_pct ? 'Zayi deposu' : 'Ayrı izlenmiyor'} />
			<StatCard label="Doluluk" value={`%${occ.occupancy_pct ?? 0}`} accent="blue" icon={BedDouble} hint={`${(occ.guest_nights || 0).toLocaleString('tr-TR')} geceleme`} />
			<StatCard label="Anlık Stok Değeri" value={formatCompact(summary.stock_value)} accent="emerald" icon={Package} hint={`${summary.in_stock_count || 0} üründe stok`} />
		</div>

		{#if kpi.matched_periods?.length}
			<p class="text-[11px] text-gray-500 -mt-2">Kişi başı maliyet yalnız tüketimi işlenmiş aylar üzerinden: {kpi.matched_periods.map(periodLabel).join(', ')} (tüketim ay-sonu sayımla post edilir).</p>
		{/if}

		<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
			<!-- Maliyet grubu kırılımı -->
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-4">Maliyet Grubu Bazında Tüketim</h3>
				{#if byGroup.length === 0}
					<EmptyState icon={Flame} title="Tüketim verisi yok" description="Üst bardaki 'Sedna' butonuyla içe aktarın." />
				{:else}
					<div class="space-y-2.5">
						{#each byGroup as g (g.group)}
							<div class="flex items-center gap-3">
								<span class="w-32 shrink-0 text-xs text-gray-700">{g.label}</span>
								<div class="flex-1 h-5 bg-gray-100 rounded-md overflow-hidden">
									<div class="h-full {GROUP_COLOR[g.group] || 'bg-gray-400'} rounded-md" style="width: {(g.total / maxGroup) * 100}%"></div>
								</div>
								<span class="w-24 shrink-0 text-right text-xs font-semibold text-gray-800 tabular-nums">{formatCompact(g.total)}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Maliyet vs Doluluk (aylık) -->
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-1">Aylık F&B Tüketim vs Doluluk</h3>
				<div class="flex items-center gap-3 text-[11px] text-gray-500 mb-3">
					<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-amber-400"></span> Tüketim</span>
					<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span> Doluluk %</span>
				</div>
				<div class="space-y-2">
					{#each monthly as m (m.period)}
						<div class="{m.matched ? '' : 'opacity-50'}">
							<div class="flex justify-between text-[11px] text-gray-500 mb-0.5">
								<span>{periodLabel(m.period)} {#if m.matched}<span class="text-amber-700 font-medium">· {(m.cost_per_guest_night).toLocaleString('tr-TR', { maximumFractionDigits: 0 })}₺/kişi</span>{/if}</span>
								<span class="tabular-nums">{formatCompact(m.fb_consumption)} · %{m.occupancy_pct}</span>
							</div>
							<div class="relative h-3 bg-gray-100 rounded-sm">
								<div class="absolute inset-y-0 left-0 bg-amber-400 rounded-sm" style="width: {(m.fb_consumption / maxMonthCons) * 100}%"></div>
								<div class="absolute top-1/2 -translate-y-1/2 w-1.5 h-3 bg-blue-500 rounded-full" style="left: {Math.min(m.occupancy_pct, 100)}%"></div>
							</div>
						</div>
					{/each}
				</div>
			</div>

			<!-- Satın alma fiyat sapması (medyan bazlı) + birim/miktar anomalileri -->
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
				<div class="flex items-center gap-2 mb-1"><TrendingUp size={18} class="text-red-500" /><h3 class="text-sm font-semibold text-gray-800">Satın Alma Fiyat Hareketi</h3></div>
				<p class="text-[11px] text-gray-500 mb-3">Son alış ↔ <span class="font-medium text-gray-600">medyan</span> (aykırı girişe dayanıklı) — gerçek fiyat hareketi</p>
				{#if variance.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-1.5">
						{#each variance as v (v.product_id)}
							<div class="flex items-center justify-between gap-2 text-sm">
								<span class="text-gray-700 truncate flex-1" title={v.name}>{v.name}</span>
								<span class="tabular-nums text-xs text-gray-500 whitespace-nowrap">{v.median_cost ?? v.avg_cost} → {v.last_cost} <span class="font-semibold {v.variance_pct > 0 ? 'text-red-600' : 'text-emerald-600'}">%{v.variance_pct}</span></span>
							</div>
						{/each}
					</div>
				{/if}

				{#if anomalies.length}
					<div class="mt-4 pt-3 border-t border-gray-100">
						<div class="flex items-center gap-1.5 mb-2">
							<TriangleAlert size={14} class="text-amber-500" />
							<span class="text-xs font-semibold text-gray-600">Olası birim/miktar tutarsızlığı ({anomalies.length})</span>
						</div>
						<div class="space-y-1">
							{#each anomalies as v (v.product_id)}
								<div class="flex items-center justify-between gap-2 text-xs">
									<span class="text-gray-500 truncate flex-1" title={v.name}>{v.name}</span>
									<span class="tabular-nums text-gray-500 whitespace-nowrap">medyan {v.median_cost ?? v.avg_cost} → son <span class="font-semibold text-amber-600">{v.last_cost}</span></span>
								</div>
							{/each}
						</div>
						<p class="text-[11px] text-gray-500 mt-2">Net tutar doğru, <span class="font-medium">miktar paydası</span> Sedna'da tutarsız (kg yerine çuval/koli adedi) — fiyat artışı değil, giriş kalitesi.</p>
					</div>
				{/if}
			</div>

			<!-- Tedarikçi sıralaması -->
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
				<div class="flex items-center gap-2 mb-4"><Truck size={18} class="text-blue-600" /><h3 class="text-sm font-semibold text-gray-800">Tedarikçi Bazında Alım</h3></div>
				{#if suppliers.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-2">
						{#each suppliers as s (s.code)}
							<div class="flex items-center gap-3">
								<span class="w-32 sm:w-40 shrink-0 text-xs text-gray-700 truncate" title={s.name}>{s.name}</span>
								<div class="flex-1 h-4 bg-gray-100 rounded-md overflow-hidden">
									<div class="h-full bg-blue-400 rounded-md" style="width: {(s.total / maxSup) * 100}%"></div>
								</div>
								<span class="w-20 shrink-0 text-right text-xs font-semibold text-gray-800 tabular-nums">{formatCompact(s.total)}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<!-- All-inclusive maliyet yaklaşımı (bilgi) -->
		<div class="bg-blue-50/50 border border-blue-100 rounded-xl p-4 flex items-start gap-3">
			<Info size={18} class="text-blue-400 mt-0.5 shrink-0" />
			<div class="text-sm text-gray-600">
				<span class="font-medium text-gray-800">All-inclusive maliyet yaklaşımı:</span>
				Bu resort all-inclusive olduğundan F&B geliri oda/paket fiyatına gömülüdür — ayrı bir F&B geliri yoktur.
				Bu nedenle klasik <span class="font-medium">Food Cost %</span> (F&B maliyeti ÷ F&B geliri) uygulanmaz; doğru metrik
				yukarıdaki <span class="font-medium text-amber-700">kişi başı F&B maliyetidir</span>.
				Reçete sapması / teorik maliyet ise POS ürün-satış kaydı gerektirir — Sedna önbüroda (DailyProductSaleTrans) tutulmuyor.
			</div>
		</div>
	{/if}
</div>
