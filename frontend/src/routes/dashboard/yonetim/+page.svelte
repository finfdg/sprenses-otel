<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import { formatCompact, formatCurrency } from '$lib/utils/finance';
	import {
		Landmark, BedDouble, TrendingUp, Flame, PiggyBank, Repeat, Receipt, Truck,
		FileWarning, CreditCard, TriangleAlert, ArrowUpRight, Wallet, Percent
	} from 'lucide-svelte';

	let loading = $state(true);
	let dash = $state<any>({});
	let alerts = $state<any>({});
	let classification = $state<any>({});
	let bank = $state<any>({});
	let checks = $state<any>({});
	let credits = $state<any[]>([]);

	function fmtEur(n: number): string { return formatCompact(n || 0, 'EUR'); }
	function fmtTry(n: number): string { return formatCompact(n || 0, 'TRY'); }

	let advanceEur = $derived(dash.finance?.agency_advance_by_currency?.EUR || 0);
	let advanceTl = $derived(dash.finance?.agency_advance_by_currency?.TL || 0);
	let creditDue = $derived(credits.filter((c) => !c.is_paid).reduce((s, c) => s + (c.amount || 0), 0));
	let maxClass = $derived(Math.max(1, ...(classification.items || []).map((x: any) => x.total)));

	async function load() {
		loading = true;
		try {
			const [d, a, c, mob, up] = await Promise.all([
				api.get<any>('/yonetim/dashboard'),
				api.get<any>('/yonetim/alerts'),
				api.get<any>('/yonetim/cost-classification'),
				api.get<any>('/finance/cash-flow/mobile-dashboard').catch(() => ({})),
				api.get<any[]>('/finance/krediler/upcoming-payments?days=30&include_paid=false').catch(() => []),
			]);
			dash = d; alerts = a; classification = c;
			bank = mob?.bank || {}; checks = mob?.checks || {};
			credits = up || [];
		} catch (e) {
			console.error('Yönetim paneli yüklenemedi:', e);
		} finally {
			loading = false;
		}
	}
	onMount(load);
</script>

<svelte:head><title>Yönetim Paneli · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader title="Yönetim Paneli" description="GM / Finans üst düzey göstergeler — doluluk, operasyonel maliyet, nakit ve uyarılar tek bakışta." />

	{#if loading}
		<div class="py-12 text-center text-gray-400 text-sm">Yükleniyor…</div>
	{:else}
		<!-- 10 KPI hero -->
		<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
			<StatCard label="Banka Bakiyesi" value={fmtTry(bank.total_try_balance || 0)} accent="teal" icon={Landmark} hint="Güncel TRY" />
			<StatCard label="Doluluk" value={`%${dash.occupancy?.occupancy_pct ?? 0}`} accent="blue" icon={BedDouble} hint={`${(dash.occupancy?.guest_nights || 0).toLocaleString('tr-TR')} geceleme`} />
			<StatCard label="ADR" value={`${dash.occupancy?.adr_eur ?? 0} €`} accent="blue" icon={TrendingUp} hint="Ort. oda fiyatı" />
			<StatCard label="RevPAR" value={`${dash.occupancy?.revpar_eur ?? 0} €`} accent="blue" icon={TrendingUp} hint="Mevcut oda başına" />
			<StatCard label="Kişi Başı Maliyet" value={`${(dash.cost?.cost_per_guest_night_try ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺`} accent="amber" icon={Flame} hint={`F&B / gece · ${dash.cost?.cost_per_guest_night_eur ?? '–'} €`} />
			<StatCard label="GOP (yaklaşık)" value={fmtTry(dash.gop_approx_try || 0)} accent="emerald" icon={PiggyBank} hint="Oda geliri − tüketim" />
			<StatCard label="Stok Devir Hızı" value={`${dash.cost?.inventory_turnover ?? 0}x`} accent="gray" icon={Repeat} hint="Tüketim / stok değeri" />
			<StatCard label="Oda Geliri" value={fmtTry(dash.revenue?.room_invoiced_try || 0)} accent="emerald" icon={Receipt} hint={`Tahsil ${fmtTry(dash.revenue?.room_collected_try || 0)}`} />
			<StatCard label="Tedarikçi Borcu" value={fmtTry(dash.finance?.supplier_debt_try || 0)} accent="red" icon={Truck} hint="Net cari borç" />
			<StatCard label="Food Cost %" value="—" accent="gray" icon={Percent} hint="PMS reçete erişimi bekleniyor" />
		</div>

		<!-- Uyarılar + Sınıflama -->
		<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
			<!-- Uyarılar -->
			<div class="lg:col-span-2 bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5 space-y-4">
				<h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2"><TriangleAlert size={16} class="text-amber-600" /> Uyarılar & Aksiyonlar</h3>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
					<a href="/dashboard/finans/cekler" class="flex items-center justify-between gap-2 p-3 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
						<span class="flex items-center gap-2 text-sm text-gray-700"><FileWarning size={16} class="text-amber-600" /> Vadesi yakın çek</span>
						<span class="text-sm font-semibold text-gray-800 tabular-nums">{checks.pending_count || 0} · {fmtTry(checks.pending_amount || 0)}</span>
					</a>
					<a href="/dashboard/finans/krediler" class="flex items-center justify-between gap-2 p-3 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
						<span class="flex items-center gap-2 text-sm text-gray-700"><CreditCard size={16} class="text-blue-600" /> 30 gün kredi taksiti</span>
						<span class="text-sm font-semibold text-gray-800 tabular-nums">{credits.filter((c) => !c.is_paid).length} · {fmtTry(creditDue)}</span>
					</a>
					<a href="/dashboard/finans/cariler" class="flex items-center justify-between gap-2 p-3 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
						<span class="flex items-center gap-2 text-sm text-gray-700"><Truck size={16} class="text-red-500" /> Tedarikçi borcu</span>
						<span class="text-sm font-semibold text-gray-800 tabular-nums">{fmtTry(alerts.supplier_debt_total_try || 0)}</span>
					</a>
					<a href="/dashboard/finans/satis-faturalari" class="flex items-center justify-between gap-2 p-3 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
						<span class="flex items-center gap-2 text-sm text-gray-700"><Wallet size={16} class="text-teal-600" /> Acente avansı</span>
						<span class="text-sm font-semibold text-gray-800 tabular-nums">{fmtEur(advanceEur)} · {fmtTry(advanceTl)}</span>
					</a>
				</div>

				<!-- Fiyat sapması -->
				{#if alerts.price_variance?.length}
					<div>
						<div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Satın Alma Fiyat Sapması (en yüksek)</div>
						<div class="space-y-1.5">
							{#each alerts.price_variance.slice(0, 5) as v (v.product_id)}
								<div class="flex items-center justify-between gap-2 text-sm">
									<span class="text-gray-700 truncate">{v.name}</span>
									<span class="tabular-nums text-gray-500">{v.avg_cost} → {v.last_cost} <span class="font-semibold {v.variance_pct > 0 ? 'text-red-600' : 'text-emerald-600'}">%{v.variance_pct}</span></span>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<a href="/dashboard/stok/maliyet" class="inline-flex items-center gap-1 text-sm text-teal-700 hover:text-teal-800 font-medium">
					Maliyet Kontrol detayı <ArrowUpRight size={15} />
				</a>
			</div>

			<!-- Sabit / Değişken -->
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4 sm:p-5">
				<h3 class="text-sm font-semibold text-gray-800 mb-1">Maliyet Yapısı ({classification.year})</h3>
				<p class="text-[11px] text-gray-400 mb-3">Sabit / değişken / yarı-değişken gösterge (yıllık TRY)</p>
				<div class="space-y-3">
					{#each classification.items || [] as it (it.key)}
						<div>
							<div class="flex justify-between text-xs mb-1">
								<span class="text-gray-600">{it.label}</span>
								<span class="font-semibold text-gray-800 tabular-nums">{fmtTry(it.total)}</span>
							</div>
							<div class="h-2 bg-gray-100 rounded-full overflow-hidden">
								<div class="h-full rounded-full {it.key === 'variable' ? 'bg-amber-400' : it.key === 'semi' ? 'bg-blue-400' : 'bg-gray-400'}" style="width: {(it.total / maxClass) * 100}%"></div>
							</div>
						</div>
					{/each}
				</div>
				{#if alerts.critical_stock_count}
					<div class="mt-4 pt-3 border-t border-gray-100 text-xs text-gray-500">
						<span class="font-semibold text-amber-600">{alerts.critical_stock_count}</span> ürün stokta tükendi (yeniden sipariş adayı)
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
