<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { formatCompact, formatCurrency } from '$lib/utils/finance';
	import { Flame, BedDouble, Repeat, Trash2, Package, Truck, TrendingUp, Info, TriangleAlert, Printer, Eye, EyeOff } from 'lucide-svelte';

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
	let showZero = $state(false); // %0 (değişmeyen) fiyatları göster/gizle
	// Varsayılan: %0 gizli → liste artan→azalan okunaklı kalır. Toggle ile %0'lar da görünür.
	let shownVariance = $derived(showZero ? variance : variance.filter((v: any) => v.variance_pct !== 0));
	let zeroCount = $derived(variance.filter((v: any) => v.variance_pct === 0).length);

	let kpi = $derived(op.kpi || {});
	let occ = $derived(op.occupancy || {});
	let byGroup = $derived(op.by_group || []);
	let monthly = $derived(op.monthly || []);
	let maxGroup = $derived(Math.max(1, ...byGroup.map((g: any) => g.total)));
	let maxMonthCons = $derived(Math.max(1, ...monthly.map((m: any) => m.fb_consumption)));
	let maxSup = $derived(Math.max(1, ...suppliers.map((s: any) => s.total)));

	// Ürün alış hareketleri detayı (fiyat/anomali satırına tıklanınca)
	let showMovements = $state(false);
	let movementsLoading = $state(false);
	let detail = $state<any>({ name: '', items: [], count: 0, median_cost: 0 });

	const fmtQty = (n: number) => (n ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 2 });
	const fmtDate = (s: string | null) => (s ? s.split('-').reverse().join('.') : '–');
	// Efektif birim fiyat = net ÷ miktar (Sedna'nın Cost alanı bazen hatalı/0)
	const effUnit = (it: any) => (it.quantity ? it.net_amount / it.quantity : it.unit_cost);

	// Hareket türü → renkli rozet + sol kenar aksanı (giriş yeşil, devir gri, transfer turuncu,
	// tüketim kırmızı, bedelsiz mavi). Depo akışı: giriş→hedef, çıkış kaynak→hedef, tüketim depo.
	function movMeta(it: any): { label: string; badge: string; accent: string } {
		const t = it.type_label || '';
		if (it.direction === 'in') {
			if (t.includes('Alış')) return { label: t, badge: 'bg-emerald-50 text-emerald-700', accent: 'border-l-emerald-500' };
			if (t.includes('Bedelsiz')) return { label: t, badge: 'bg-blue-50 text-blue-700', accent: 'border-l-blue-500' };
			return { label: t || 'Giriş', badge: 'bg-gray-100 text-gray-600', accent: 'border-l-gray-300' };
		}
		if (it.direction === 'out') return { label: t || 'Çıkış', badge: 'bg-amber-50 text-amber-700', accent: 'border-l-amber-500' };
		if (it.direction === 'consume') return { label: t || 'Tüketim', badge: 'bg-red-50 text-red-600', accent: 'border-l-red-500' };
		return { label: t || it.direction || '–', badge: 'bg-gray-100 text-gray-600', accent: 'border-l-gray-300' };
	}
	function flowText(it: any): string {
		if (it.direction === 'out') return `${it.from_depot ?? '?'} → ${it.to_depot ?? '?'}`;
		if (it.direction === 'consume') return it.cons_depot ?? '–';
		return it.to_depot ?? '–';
	}

	// Hareketlerden depo akış grafiği türet: transfer rotaları (oklar) + depo başına özet.
	let flow = $derived.by(() => {
		const items: any[] = detail.items || [];
		const map = new Map<string, any>();
		const routes = new Map<string, any>();
		const ens = (n: string) => {
			if (!map.has(n)) map.set(n, { name: n, alis: 0, acilis: 0, tIn: 0, tOut: 0, tuketim: 0 });
			return map.get(n);
		};
		for (const it of items) {
			const t = it.type_label || '';
			if (it.direction === 'in') {
				const d = ens(it.to_depot || '(belirsiz)');
				if (t.includes('Devir') || t.includes('Açılış')) d.acilis += it.quantity;
				else d.alis += it.quantity;
			} else if (it.direction === 'out') {
				const from = it.from_depot || '?', to = it.to_depot || '?';
				ens(from).tOut += it.quantity;
				ens(to).tIn += it.quantity;
				const k = `${from}|${to}`;
				const r = routes.get(k) || { from, to, qty: 0 };
				r.qty += it.quantity;
				routes.set(k, r);
			} else if (it.direction === 'consume') {
				ens(it.cons_depot || '?').tuketim += it.quantity;
			}
		}
		const act = (d: any) => d.alis + d.tIn + d.tOut + d.tuketim;
		return {
			routes: [...routes.values()].sort((a, b) => b.qty - a.qty),
			depots: [...map.values()].filter((d) => act(d) > 0).sort((a, b) => act(b) - act(a)),
		};
	});

	// PDF'i blob olarak çek → gizli iframe ile yazdırma diyaloğunu TETİKLE (masaüstünde direkt
	// yazıcıya gider). iOS Safari iframe print'i çoğu zaman yoksaydığından fallback: PDF'i yeni
	// sekmede aç → kullanıcı Paylaş → Yazdır kullanır. (banka talimatları deseniyle aynı.)
	let printing = $state(false);
	async function printMovements() {
		if (!detail.product_id || printing) return;
		printing = true;
		try {
			const res = await api.fetchRaw(`/stok/product-purchases/${detail.product_id}/pdf`);
			if (!res.ok) throw new Error(`PDF alınamadı (${res.status})`);
			const url = URL.createObjectURL(await res.blob());
			const iframe = document.createElement('iframe');
			iframe.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0';
			iframe.src = url;
			iframe.onload = () => {
				try {
					iframe.contentWindow?.focus();
					iframe.contentWindow?.print();
				} catch (err) {
					console.error('iframe yazdırma hatası:', err);
					window.open(url, '_blank'); // iOS fallback → Paylaş → Yazdır
				}
				setTimeout(() => { iframe.remove(); URL.revokeObjectURL(url); }, 60000);
			};
			document.body.appendChild(iframe);
		} catch (e) {
			console.error('Yazdırma başlatılamadı:', e);
			showToast('Yazdırma başlatılamadı', 'error');
		} finally {
			printing = false;
		}
	}

	let movementsError = $state(false);
	let lastProduct = $state<any>(null);
	async function openMovements(p: any) {
		lastProduct = p;
		showMovements = true;
		movementsLoading = true;
		movementsError = false;
		detail = { name: p.name, items: [], count: 0, median_cost: p.median_cost ?? p.avg_cost };
		// Zaman aşımı: yanıt 5sn'de gelmezse iptal et → sonsuz skeleton yerine hata göster
		const ctrl = new AbortController();
		const timer = setTimeout(() => ctrl.abort(), 5000);
		try {
			detail = await api.get<any>(`/stok/product-purchases/${p.product_id}`, ctrl.signal);
		} catch (e) {
			console.error('Ürün alış hareketleri yüklenemedi:', e);
			movementsError = true;
		} finally {
			clearTimeout(timer);
			movementsLoading = false;
		}
	}

	async function load() {
		loading = true;
		try {
			const [o, s, sup, v] = await Promise.all([
				api.get<any>('/stok/operational-kpi'),
				api.get<any>('/stok/summary'),
				api.get<any>('/stok/by-supplier?limit=10'),
				api.get<any>('/stok/price-variance?limit=0&include_zero=true'),
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
		<TableSkeleton rows={6} columns={6} />
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
				<div class="flex items-start justify-between gap-2 mb-1">
					<div class="flex items-center gap-2"><TrendingUp size={18} class="text-red-500" /><h3 class="text-sm font-semibold text-gray-800">Satın Alma Fiyat Hareketi</h3></div>
					{#if zeroCount > 0}
						<Button variant="ghost" size="sm" onclick={() => (showZero = !showZero)} class="shrink-0 -mt-1" title={showZero ? 'Değişmeyenleri gizle' : 'Değişmeyenleri göster'}>
							{#if showZero}<EyeOff size={14} /> %0 gizle{:else}<Eye size={14} /> %0 göster ({zeroCount}){/if}
						</Button>
					{/if}
				</div>
				<p class="text-[11px] text-gray-500 mb-3">Son alış ↔ <span class="font-medium text-gray-600">medyan</span> (aykırı girişe dayanıklı) — fiyatı artanlar üstte, azalanlar altta</p>
				{#if shownVariance.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-0.5 max-h-72 overflow-y-auto pr-1">
						{#each shownVariance as v (v.product_id)}
							<button type="button" onclick={() => openMovements(v)} class="w-full flex items-center justify-between gap-2 text-sm text-left px-2 py-1 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer" title="Alış hareketlerini gör">
								<span class="text-gray-700 truncate flex-1">{v.name}</span>
								<span class="tabular-nums text-xs text-gray-500 whitespace-nowrap">{v.median_cost ?? v.avg_cost} → {v.last_cost} <span class="font-semibold {v.variance_pct > 0 ? 'text-red-600' : v.variance_pct < 0 ? 'text-emerald-600' : 'text-gray-400'}">%{v.variance_pct}</span></span>
							</button>
						{/each}
					</div>
				{/if}

				{#if anomalies.length}
					<div class="mt-4 pt-3 border-t border-gray-100">
						<div class="flex items-center gap-1.5 mb-2">
							<TriangleAlert size={14} class="text-amber-500" />
							<span class="text-xs font-semibold text-gray-600">Olası birim/miktar tutarsızlığı ({anomalies.length})</span>
						</div>
						<div class="space-y-0.5 max-h-72 overflow-y-auto pr-1">
							{#each anomalies as v (v.product_id)}
								<button type="button" onclick={() => openMovements(v)} class="w-full flex items-center justify-between gap-2 text-xs text-left px-2 py-1 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer" title="Alış hareketlerini gör">
									<span class="text-gray-500 truncate flex-1">{v.name}</span>
									<span class="tabular-nums text-gray-500 whitespace-nowrap">medyan {v.median_cost ?? v.avg_cost} → son <span class="font-semibold text-amber-600">{v.last_cost}</span></span>
								</button>
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

<!-- Ürün stok hareketleri detayı (giriş + transfer + tüketim, tür bazlı renkli) -->
<Modal bind:show={showMovements} title={detail.name || 'Stok hareketleri'} maxWidth="max-w-4xl">
	{#if movementsLoading}
		<TableSkeleton rows={6} columns={6} />
	{:else if movementsError}
		<div class="text-center py-8">
			<EmptyState icon={TriangleAlert} title="Yüklenemedi" description="Stok hareketleri getirilemedi. Bağlantınızı kontrol edip tekrar deneyin." />
			<Button variant="secondary" size="sm" onclick={() => lastProduct && openMovements(lastProduct)} class="mt-3">Tekrar dene</Button>
		</div>
	{:else if !detail.items?.length}
		<EmptyState icon={Package} title="Stok hareketi yok" description="Bu ürün için kayıtlı hareket bulunamadı." />
	{:else}
		<div class="flex items-start justify-between gap-3 mb-2">
			<p class="text-xs text-gray-500">
				{detail.count} hareket · {detail.purchase_count} alış · medyan alış <span class="font-medium text-gray-700 tabular-nums">{formatCurrency(detail.median_cost)}</span>
				· <span class="font-medium">Birim = net ÷ miktar</span>
			</p>
			<Button variant="secondary" size="sm" onclick={printMovements} loading={printing} class="shrink-0">
				<Printer size={16} /> Yazdır
			</Button>
		</div>
		<!-- Görsel depo akış şeması: transfer okları + depo özet kartları -->
		{#if flow.routes.length || flow.depots.length}
			<div class="bg-gray-50/70 border border-gray-200 rounded-xl p-3 sm:p-4 mb-4">
				<div class="text-xs font-semibold text-gray-700 mb-2.5">Depo Akış Şeması</div>
				{#if flow.routes.length}
					<div class="space-y-2 mb-3">
						{#each flow.routes as r (r.from + r.to)}
							<div class="flex items-center gap-2">
								<span class="shrink-0 px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 text-xs font-medium whitespace-nowrap max-w-[38%] truncate" title={r.from}>{r.from}</span>
								<div class="flex-1 flex flex-col items-center min-w-[54px]">
									<span class="text-[11px] font-semibold text-amber-700 tabular-nums leading-none mb-0.5">{fmtQty(r.qty)}</span>
									<div class="w-full flex items-center text-amber-400">
										<div class="flex-1 border-t-2 border-dashed border-amber-300"></div>
										<span class="text-amber-500 text-sm leading-none -ml-0.5">▶</span>
									</div>
								</div>
								<span class="shrink-0 px-2.5 py-1 rounded-lg bg-amber-50 text-amber-700 text-xs font-medium whitespace-nowrap max-w-[38%] truncate" title={r.to}>{r.to}</span>
							</div>
						{/each}
					</div>
				{/if}
				<div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
					{#each flow.depots as d (d.name)}
						<div class="bg-white border border-gray-200 rounded-lg p-2">
							<div class="text-[11px] font-semibold text-gray-800 truncate" title={d.name}>{d.name}</div>
							<div class="mt-1 space-y-0.5 text-[11px] tabular-nums">
								{#if d.alis}<div class="flex justify-between gap-2"><span class="text-emerald-600">Alış</span><span>+{fmtQty(d.alis)}</span></div>{/if}
								{#if d.tIn}<div class="flex justify-between gap-2"><span class="text-amber-600">Transfer giriş</span><span>+{fmtQty(d.tIn)}</span></div>{/if}
								{#if d.tOut}<div class="flex justify-between gap-2"><span class="text-amber-600">Transfer çıkış</span><span>−{fmtQty(d.tOut)}</span></div>{/if}
								{#if d.tuketim}<div class="flex justify-between gap-2"><span class="text-red-600">Tüketim</span><span>−{fmtQty(d.tuketim)}</span></div>{/if}
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Renk lejantı -->
		<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500 mb-2">
			<span class="font-medium text-gray-600">Tüm hareketler:</span>
			<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-emerald-500"></span> Alış</span>
			<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-gray-300"></span> Devir/Açılış</span>
			<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-amber-500"></span> Çıkış/Transfer</span>
			<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-red-500"></span> Tüketim</span>
			<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-blue-500"></span> Bedelsiz</span>
		</div>
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="text-left text-xs text-gray-600 border-b border-gray-200">
						<th class="py-2 pr-2 font-medium text-right w-8">#</th>
						<th class="py-2 px-2 font-medium">Tarih</th>
						<th class="py-2 px-2 font-medium">Hareket</th>
						<th class="py-2 px-2 font-medium">Depo / Akış</th>
						<th class="py-2 px-2 font-medium text-right">Miktar</th>
						<th class="py-2 px-2 font-medium text-right">Birim</th>
						<th class="py-2 pl-2 font-medium text-right">Net Tutar</th>
					</tr>
				</thead>
				<tbody>
					{#each detail.items as it, i (it.id)}
						{@const m = movMeta(it)}
						<tr class="border-b border-gray-100 last:border-0 border-l-4 {m.accent}">
							<td class="py-2 pr-2 pl-2 text-right tabular-nums text-gray-400">{i + 1}</td>
							<td class="py-2 px-2 whitespace-nowrap tabular-nums text-gray-700">{fmtDate(it.date)}</td>
							<td class="py-2 px-2">
								<span class="inline-block px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap {m.badge}">{m.label}</span>
								{#if it.supplier_name}<div class="text-[11px] text-gray-500 truncate max-w-[180px] mt-0.5" title={it.supplier_name}>{it.supplier_name}</div>{/if}
							</td>
							<td class="py-2 px-2 text-gray-600 whitespace-nowrap">
								{#if it.direction === 'out'}
									<span class="text-gray-700">{it.from_depot ?? '?'}</span> <span class="text-amber-600">→</span> <span class="text-gray-700">{it.to_depot ?? '?'}</span>
								{:else}
									{flowText(it)}
								{/if}
							</td>
							<td class="py-2 px-2 text-right tabular-nums text-gray-700">{fmtQty(it.quantity)}</td>
							<td class="py-2 px-2 text-right tabular-nums font-medium text-gray-800">{it.net_amount ? formatCurrency(effUnit(it)) : '–'}</td>
							<td class="py-2 pl-2 text-right tabular-nums text-gray-700">{formatCurrency(it.net_amount)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</Modal>
