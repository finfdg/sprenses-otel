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
	import { Flame, BedDouble, Repeat, Trash2, Package, Truck, TrendingUp, Info, TriangleAlert, Printer, Eye, EyeOff, ArrowUp } from 'lucide-svelte';

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
	const fmtTRYint = (n: number) => '₺' + Math.round(n ?? 0).toLocaleString('tr-TR');
	const fmtDate = (s: string | null) => (s ? s.split('-').reverse().join('.') : '–');
	// Efektif birim fiyat = net ÷ miktar (Sedna'nın Cost alanı bazen hatalı/0)
	const effUnit = (it: any) => (it.quantity ? it.net_amount / it.quantity : it.unit_cost);

	// Hareket türü → renkli rozet + sol kenar aksanı (giriş yeşil, devir gri, transfer turuncu,
	// tüketim kırmızı, bedelsiz mavi). Depo akışı: giriş→hedef, çıkış kaynak→hedef, tüketim depo.
	function movMeta(it: any): { label: string; badge: string; accent: string; dot: string } {
		const t = it.type_label || '';
		if (it.direction === 'in') {
			if (t.includes('Alış')) return { label: t, badge: 'bg-emerald-50 text-emerald-700', accent: 'border-l-emerald-500', dot: 'bg-emerald-500' };
			if (t.includes('Bedelsiz')) return { label: t, badge: 'bg-blue-50 text-blue-700', accent: 'border-l-blue-500', dot: 'bg-blue-500' };
			return { label: t || 'Giriş', badge: 'bg-gray-100 text-gray-600', accent: 'border-l-gray-300', dot: 'bg-gray-300' };
		}
		if (it.direction === 'out') return { label: t || 'Çıkış', badge: 'bg-amber-50 text-amber-700', accent: 'border-l-amber-500', dot: 'bg-amber-500' };
		if (it.direction === 'consume') return { label: t || 'Tüketim', badge: 'bg-red-50 text-red-600', accent: 'border-l-red-500', dot: 'bg-red-500' };
		return { label: t || it.direction || '–', badge: 'bg-gray-100 text-gray-600', accent: 'border-l-gray-300', dot: 'bg-gray-300' };
	}
	const MONTHS_TR = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
	const monthLabel = (k: string) => { const [y, m] = k.split('-'); return `${MONTHS_TR[Number(m) - 1] || m} ${y}`; };
	let detailView = $state<'trunk' | 'table'>('trunk'); // modal görünümü: gövde / liste
	function flowText(it: any, hub: string | null = null): string {
		if (it.direction === 'out') return `${it.from_depot ?? '?'} → ${it.to_depot ?? '?'}`;
		if (it.direction === 'consume') return it.cons_depot ?? '–';
		return it.to_depot || hub || '–'; // giriş: depo etiketi boşsa merkez (hub) depoya
	}

	// HUB = en çok transfer çıkışı yapan kaynak depo (= ANA DEPO). Sedna'da bazı Alış'lar depo
	// etiketsiz gelir; o mal fiziksel olarak merkez depoya girer (mutabakat doğrular). Hem gövde,
	// hem yürüyen bakiye, hem liste bu hub'ı kullanır → "alış nereye girdi" tutarlı görünür.
	let hubDepot = $derived.by(() => {
		const outBy: Record<string, number> = {};
		for (const it of (detail.items || [])) if (it.direction === 'out') outBy[it.from_depot || '?'] = (outBy[it.from_depot || '?'] || 0) + (it.quantity || 0);
		return Object.keys(outBy).sort((a, b) => outBy[b] - outBy[a])[0] || null;
	});

	// STOK HAREKET GÖVDESİ (ağaç): kök = ilk dönem devir/açılışı (en alt), gövde yukarı doğru
	// kronolojik büyür. Sol dal = giriş (yeşil), sağ dal = çıkış/transfer (amber). Her dönem
	// sonunda HALKA: o depodaki SAYIMDA KALAN (yürüyen bakiye) + TÜKETİM (ay-sonu tüketim postingi,
	// = sayım farkı: önceki sayım + giren − çıkan − bu sayım). Önemli: Tüketim "kaydedilen" değil,
	// her halkada sayım farkından okunan değerdir. Veri bunu doğruluyor (ör. PERSONEL MUTFAĞI Oca:
	// 0 + 16 transfer − 4 kalan = 12 = kayıtlı tüketim). Alış (depo etiketi boş) merkez depoya
	// (en çok transfer çıkışı yapan = hub) yazılır — çünkü 8 + 36 alış − 12 transfer = 32 = sonraki
	// ay devri (Sedna mutabakatı). Çıktı: alttan üste sıralı satırlar (root / node / ring), render
	// için ters çevrilir (en güncel üstte).
	let trunk = $derived.by(() => {
		const seq = [...(detail.items || [])].reverse(); // backend date DESC → eski→yeni
		if (!seq.length) return { rows: [] as any[], hub: null as string | null };
		const hub = hubDepot; // alış'ların (depo etiketsiz) indiği merkez depo
		const per = (s: string | null) => (s ? s.slice(0, 7) : '');

		const bal: Record<string, number> = {};
		const rows: any[] = [];               // alttan üste: hareketler + dönem halkaları
		const rootOpen: any[] = [];           // ilk dönem açılış kartları
		let curPeriod = '';
		let consume: Record<string, number> = {}; // mevcut dönem tüketim (depo → qty)
		let rootDone = false;

		const closeRing = (p: string) => {
			const counts = Object.entries(bal)
				.filter(([, q]) => Math.round((q as number) * 100) / 100 > 0)
				.map(([depot, q]) => ({ depot, qty: q as number }))
				.sort((a, b) => b.qty - a.qty);
			const cons = Object.entries(consume)
				.filter(([, q]) => (q as number) > 0)
				.map(([depot, q]) => ({ depot, qty: q as number }))
				.sort((a, b) => b.qty - a.qty);
			rows.push({ kind: 'ring', period: p, counts, cons });
			consume = {};
		};

		for (const it of seq) {
			const p = per(it.date);
			const t = it.type_label || '';
			const qty = it.quantity || 0;
			const opening = it.direction === 'in' && /Devir|Açılış/.test(t);
			// Dönem değişince önceki dönemi kapat (devir reset'inden ÖNCE) + kök artık tamamdır.
			// KÖK = YALNIZ ilk dönemin açılışı; sonraki ayların devirleri devreden sayımı tekrar eder.
			// (Boş postingler API'de elenince ardışık "yalnız-devir" aylar oluşabiliyor; rootDone'u
			// yalnız non-opening'e bağlamak kökte mükerrer depo → {#each} dup-key crash'i yaratıyordu.)
			if (curPeriod && p !== curPeriod) { closeRing(curPeriod); rootDone = true; }
			curPeriod = p;

			if (it.direction === 'in') {
				const depot = it.to_depot || hub || '(belirsiz)';
				if (opening) {
					bal[depot] = qty; // sayım reset (fiziksel devir değeri)
					if (!rootDone && !rootOpen.some((o: any) => o.depot === depot)) rootOpen.push({ depot, qty, net: it.net_amount });
				} else {
					bal[depot] = (bal[depot] || 0) + qty;
					rows.push({ kind: 'node', side: 'in', date: it.date, label: t || 'Giriş', depot, qty, net: it.net_amount });
					rootDone = true;
				}
			} else if (it.direction === 'out') {
				const from = it.from_depot || '?', to = it.to_depot || '?';
				bal[from] = (bal[from] || 0) - qty;
				bal[to] = (bal[to] || 0) + qty;
				rows.push({ kind: 'node', side: 'out', date: it.date, label: t || 'Çıkış', from, to, qty });
				rootDone = true;
			} else if (it.direction === 'consume') {
				const d = it.cons_depot || '?';
				bal[d] = (bal[d] || 0) - qty;
				consume[d] = (consume[d] || 0) + qty;
				rootDone = true;
			}
		}
		if (curPeriod) closeRing(curPeriod);

		if (rootOpen.length) rows.unshift({ kind: 'root', date: seq[0]?.date, openings: rootOpen });
		rows.reverse(); // üstten alta: en güncel üstte, kök altta
		return { rows, hub };
	});

	// Depo bazında YÜRÜYEN BAKİYE: hareketleri kronolojik (eskiden yeniye) işle.
	// Devir/Açılış = sayım anlık değeri (RESET); alış/bedelsiz/transfer-giriş = ekle;
	// transfer-çıkış/tüketim = çıkar. Her hareketin id'sine, ilgili depo(lar)daki kalan yazılır.
	let runBal = $derived.by(() => {
		const seq = [...(detail.items || [])].reverse();
		const bal: Record<string, number> = {};
		const res: Record<number, any> = {};
		for (const it of seq) {
			const t = it.type_label || '';
			if (it.direction === 'in') {
				const d = it.to_depot || hubDepot || '?'; // alış depo etiketsizse merkez (hub) depoya gir
				const opening = /Devir|Açılış/.test(t);
				bal[d] = opening ? it.quantity : (bal[d] || 0) + it.quantity;
				res[it.id] = { kind: 'in', depot: d, val: bal[d], opening };
			} else if (it.direction === 'out') {
				const f = it.from_depot || '?', to = it.to_depot || '?';
				bal[f] = (bal[f] || 0) - it.quantity;
				bal[to] = (bal[to] || 0) + it.quantity;
				res[it.id] = { kind: 'out', from: f, fromVal: bal[f], to, toVal: bal[to] };
			} else if (it.direction === 'consume') {
				const d = it.cons_depot || '?';
				bal[d] = (bal[d] || 0) - it.quantity;
				res[it.id] = { kind: 'consume', depot: d, val: bal[d] };
			}
		}
		return res;
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
				api.get<any>('/stok/by-supplier?limit=0'),
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
				<div class="flex items-center gap-2 mb-4"><Truck size={18} class="text-blue-600" /><h3 class="text-sm font-semibold text-gray-800">Tedarikçi Bazında Alım</h3>{#if suppliers.length}<span class="text-xs text-gray-500">({suppliers.length})</span>{/if}</div>
				{#if suppliers.length === 0}
					<p class="text-sm text-gray-500">Veri yok</p>
				{:else}
					<div class="space-y-2 max-h-96 overflow-y-auto pr-1">
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
	<svelte:boundary>
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
		<!-- Görünüm geçişi + renk lejantı -->
		<div class="flex flex-wrap items-center justify-between gap-2 mb-3">
			<div class="inline-flex rounded-lg border border-gray-200 p-0.5 text-xs">
				<button type="button" onclick={() => (detailView = 'trunk')} class="px-3 py-1 rounded-md font-medium transition-colors {detailView === 'trunk' ? 'bg-teal-700 text-white' : 'text-gray-600 hover:bg-gray-50'}">Gövde</button>
				<button type="button" onclick={() => (detailView = 'table')} class="px-3 py-1 rounded-md font-medium transition-colors {detailView === 'table' ? 'bg-teal-700 text-white' : 'text-gray-600 hover:bg-gray-50'}">Liste</button>
			</div>
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500">
				<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-emerald-500"></span> Giriş</span>
				<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-amber-500"></span> Çıkış / Transfer</span>
				<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-blue-500"></span> Sayımda kalan</span>
				<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm bg-red-500"></span> Tüketim</span>
			</div>
		</div>

		{#if detailView === 'trunk'}
			<!-- Stok Hareket Gövdesi: kök (devir) en altta, gövde yukarı doğru kronolojik büyür.
			     Sol = giriş (yeşil), sağ = çıkış/transfer (amber). Dönem sonu halkası: sayımda kalan +
			     sayımdan hesaplanan tüketim. Üstte ürün + depo özeti. -->
			<div class="bg-gray-50/60 border border-gray-200 rounded-xl p-2 sm:p-4">
				<div class="flex items-start justify-between gap-2 mb-2 px-1">
					<div>
						<div class="text-sm font-bold text-gray-800">Stok Hareket Gövdesi</div>
						<div class="text-[11px] font-medium"><span class="text-emerald-600">← Giriş</span></div>
					</div>
					<div class="text-right">
						<div class="text-[11px] text-gray-400">{detail.name}</div>
						<div class="text-[11px] font-medium text-amber-700">Çıkış / Transfer →</div>
					</div>
				</div>

				<!-- üst ok: en güncel -->
				<div class="flex flex-col items-center">
					<ArrowUp size={26} class="text-amber-700" strokeWidth={2.5} />
				</div>
				<div class="text-center text-[11px] text-gray-400 mb-1">en güncel · gövde yukarı büyür</div>

				{#each trunk.rows as r, ri (r.kind + (r.date || '') + (r.period || '') + (r.side || '') + (r.label || '') + ri)}
					{#if r.kind === 'ring'}
						<!-- dönem sonu halkası (sayımda kalan + tüketim) -->
						<div class="relative py-1.5">
							<div class="absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2 bg-amber-700/40"></div>
							<div class="relative mx-auto max-w-md bg-white border border-gray-200 rounded-2xl shadow-sm px-4 py-3">
								<div class="flex items-center justify-center gap-2 mb-2">
									<span class="text-sm font-bold text-gray-800">{monthLabel(r.period)}</span>
									<span class="text-[10px] font-semibold tracking-wide text-gray-400">DÖNEM SONU</span>
								</div>
								{#if r.counts.length}
									<div class="flex flex-wrap items-center justify-center gap-1.5 text-xs">
										<span class="inline-flex items-center gap-1 text-gray-500"><span class="w-2.5 h-2.5 rounded-sm bg-blue-500"></span>sayımda kalan</span>
										{#each r.counts as c (c.depot)}
											<span class="px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 font-medium whitespace-nowrap">{c.depot} {fmtQty(c.qty)}</span>
										{/each}
									</div>
								{/if}
								{#if r.cons.length}
									<div class="text-center text-[10px] text-gray-400 mt-2 mb-1.5">↓ SAYIMDAN HESAPLANIR</div>
									<div class="flex flex-wrap items-center justify-center gap-1.5">
										{#each r.cons as c (c.depot)}
											<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-red-50">
												<span class="w-2 h-2 rounded-sm bg-red-500"></span>
												<span class="text-xs font-bold text-red-600 whitespace-nowrap">TÜKETİM {c.depot} {fmtQty(c.qty)} adet</span>
											</span>
										{/each}
									</div>
								{/if}
							</div>
						</div>
					{:else if r.kind === 'root'}
						<!-- kök: ilk dönem devir / açılış -->
						<div class="relative pt-1">
							<div class="absolute top-0 h-6 left-1/2 w-[3px] -translate-x-1/2 bg-amber-700/40"></div>
							<div class="relative flex justify-center mb-1"><div class="w-4 h-4 rounded-full bg-teal-500 ring-4 ring-teal-100"></div></div>
							<div class="text-center mb-2"><span class="px-2.5 py-0.5 rounded-md bg-amber-50 text-amber-800 text-[11px] font-semibold whitespace-nowrap">{fmtDate(r.date)} · KÖK · DEVİR / AÇILIŞ</span></div>
							<div class="flex flex-wrap justify-center gap-2">
								{#each r.openings as o (o.depot)}
									<div class="bg-white border border-gray-200 rounded-xl px-3 py-2 text-center min-w-[120px]">
										<div class="text-[11px] text-gray-500">{o.depot}</div>
										<div class="text-sm font-bold text-gray-800 tabular-nums">{fmtQty(o.qty)} adet</div>
										{#if o.net}<div class="text-[11px] text-gray-400 tabular-nums">{fmtTRYint(o.net)}</div>{/if}
									</div>
								{/each}
							</div>
						</div>
					{:else}
						<!-- hareket düğümü: giriş (sol/yeşil) | çıkış-transfer (sağ/amber) -->
						{@const isIn = r.side === 'in'}
						<div class="grid grid-cols-[1fr_2.25rem_1fr] items-center">
							<!-- sol: giriş -->
							<div class="flex justify-end">
								{#if isIn}
									<div class="bg-white border border-gray-200 border-l-4 border-l-emerald-500 rounded-lg shadow-sm px-3 py-2 max-w-[15rem]">
										<div class="flex items-center justify-end gap-2 mb-0.5">
											<span class="text-[11px] tabular-nums text-gray-400">{fmtDate(r.date)}</span>
											<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-50 text-emerald-700 whitespace-nowrap">{r.label}</span>
										</div>
										<div class="text-xs text-gray-700 text-right truncate" title={r.depot}>{r.depot}</div>
										<div class="flex items-baseline justify-end gap-2">
											<span class="text-sm font-bold text-emerald-700 tabular-nums">+{fmtQty(r.qty)} adet</span>
											{#if r.net}<span class="text-[11px] text-gray-400 tabular-nums">{fmtTRYint(r.net)}</span>{/if}
										</div>
									</div>
								{/if}
							</div>
							<!-- merkez: gövde çizgisi + nokta -->
							<div class="relative flex justify-center self-stretch min-h-[3.5rem]">
								<div class="absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2 bg-amber-700/40"></div>
								<div class="relative z-10 self-center w-3.5 h-3.5 rounded-full ring-2 ring-white {isIn ? 'bg-emerald-500' : 'bg-amber-500'}"></div>
							</div>
							<!-- sağ: çıkış / transfer -->
							<div class="flex justify-start">
								{#if !isIn}
									<div class="bg-white border border-gray-200 border-l-4 border-l-amber-500 rounded-lg shadow-sm px-3 py-2 max-w-[15rem]">
										<div class="flex items-center gap-2 mb-0.5">
											<span class="text-[11px] tabular-nums text-gray-400">{fmtDate(r.date)}</span>
											<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 whitespace-nowrap">{r.label}</span>
										</div>
										<div class="text-xs text-gray-700 truncate" title={`${r.from} → ${r.to}`}>{r.from} <span class="text-amber-600">→</span> {r.to}</div>
										<div class="flex items-baseline gap-2">
											<span class="text-sm font-bold text-amber-700 tabular-nums">−{fmtQty(r.qty)} adet</span>
											<span class="text-[11px] text-gray-300">—</span>
										</div>
									</div>
								{/if}
							</div>
						</div>
					{/if}
				{/each}
			</div>
		{:else}
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
									{:else if it.direction === 'in'}
										<span class="text-gray-700">{it.to_depot || hubDepot || '–'}</span>{#if !it.to_depot && hubDepot}<span class="text-gray-400 ml-0.5" title="Sedna'da depo etiketi yok — mal merkez depoya (hub) girer">*</span>{/if}
									{:else}
										{flowText(it)}
									{/if}
									{#if runBal[it.id] && !(runBal[it.id].kind === 'in' && runBal[it.id].opening)}
										{@const b = runBal[it.id]}
										<div class="text-[11px] text-gray-400">
											{#if b.kind === 'out'}kalan {b.from}: <span class={b.fromVal < 0 ? 'text-amber-600' : ''}>{fmtQty(b.fromVal)}</span> · {b.to}: {fmtQty(b.toVal)}
											{:else}kalan {b.depot}: <span class={b.val < 0 ? 'text-amber-600' : ''}>{fmtQty(b.val)}</span>{/if}
										</div>
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
	{/if}
	<!-- Güvenlik ağı: herhangi bir render hatası modalı dondurmasın → hata + Liste'ye geç -->
	{#snippet failed(error, reset)}
		<div class="text-center py-8">
			<EmptyState icon={TriangleAlert} title="Görünüm oluşturulamadı" description="Bu ürünün hareket görünümü çizilirken bir sorun oluştu. Liste görünümünü deneyebilirsiniz." />
			<Button variant="secondary" size="sm" onclick={() => { detailView = 'table'; reset(); }} class="mt-3">Liste görünümüne geç</Button>
		</div>
	{/snippet}
	</svelte:boundary>
</Modal>
