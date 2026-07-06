<!--
	CashFlowTAccount.svelte — Nakit Akım T Hesap Cetveli (Panel yeniden tasarımı, 2026-07-04;
	etkileşim yenilemesi 2026-07-06 — tasarım: "Nakit Akım T-Hesap.dc.html").

	Muhasebedeki T hesap cetveli: solda Nakit Giriş (yeşil), sağda Nakit Çıkış (altın); mobilde
	dikey istif. Dönem sekmeleri (Günlük/Haftalık/Aylık/Yıllık) + tarih gezgini.

	İki bağımsız SÜTUN-İÇİ kontrol (tasarım kararı):
	  1) SEGMENT (Bekleyen | ✓ Gerçekleşen) — aynı liste YERİNDE değişir (ayrı panel açılmaz).
	     Varsayılan "Bekleyen"; dönem/gezinme değişince sıfırlanır. Bölme grup sayaçlarından
	     (realized_eur/realized_count) yapılır — items MAX_ITEMS_PER_GROUP=100 ile kırpık olabilir.
	  2) TARİH GÖRÜNÜMÜ — sütun başlığındaki takvim ikonuna basınca kategori-gruplama ↔ gün-gruplama
	     arası geçiş. Tarih görünümünde tüm kalemler kronolojik gün başlıkları altında (kategori etiketiyle).

	Veri: GET /finance/cash-flow/t-account?period=&offset= (EUR, gerçek finance_events).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import RunwayChart from '$lib/components/RunwayChart.svelte';
	import OverdueList from '$lib/components/OverdueList.svelte';
	import { aggregateRows, AGGREGATE_LABELS, type CashRow } from '$lib/utils/cashflow';
	import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from 'lucide-svelte';

	type TItem = { name: string; date: string; amount_eur: number; amount_native: number; currency: string; is_realized?: boolean };
	type TGroup = { label: string; total_eur: number; item_count: number; section?: string; items: TItem[]; realized_eur?: number; realized_count?: number };
	type TData = {
		period: string; offset: number; start_date: string; end_date: string;
		giris: TGroup[]; cikis: TGroup[];
		total_in_eur: number; total_out_eur: number; net_eur: number;
		realized_in_eur?: number; realized_out_eur?: number;
		faaliyet_net_eur?: number; finansman_net_eur?: number;
		curve?: { date: string; cum: number }[]; skipped_no_rate: number;
	};
	type SideKey = 'giris' | 'cikis';
	type DayBucket = { date: string; label: string; items: TItem[]; totalEur: number };
	// Tarih görünümü: gün → kategori alt-grubu → satır (cari toplu, diğerleri ayrı)
	type DateRow = { name: string; amountLabel: string };
	type DateCat = { label: string; totalEur: number; rows: DateRow[] };
	type DateDay = { date: string; label: string; totalEur: number; cats: DateCat[] };

	// İleri (gelecek dönem) navigasyon üst sınırı — backend le=24 ile aynı
	const MAX_FUTURE_OFFSET = 24;
	// Tarih görünümünde gösterilecek en fazla gün başlığı (fazlası "+N gün daha" ile özetlenir)
	const MAX_DATE_DAYS = 40;

	const PERIODS = [
		{ value: 'daily', label: 'Günlük' },
		{ value: 'weekly', label: 'Haftalık' },
		{ value: 'monthly', label: 'Aylık' },
		{ value: 'yearly', label: 'Yıllık' },
	];
	const PERIOD_TYPE_LABEL: Record<string, string> = {
		daily: 'GÜNLÜK', weekly: 'HAFTALIK', monthly: 'AYLIK', yearly: 'YILLIK',
	};
	const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
	const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const WEEKDAYS = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'];
	// Sütun görsel kimliği: gelir=yeşil (emerald), gider=altın (brass); net bandı lacivert (teal-700 token)
	const COLS: { side: SideKey; title: string; accent: string; totalCls: string }[] = [
		{ side: 'giris', title: 'Nakit Giriş', accent: 'bg-emerald-600', totalCls: 'text-emerald-700' },
		{ side: 'cikis', title: 'Nakit Çıkış', accent: 'bg-brass', totalCls: 'text-brass-dark' },
	];

	// State
	let period = $state<'daily' | 'weekly' | 'monthly' | 'yearly'>('monthly');
	let offsets = $state<Record<string, number>>({ daily: 0, weekly: 0, monthly: 0, yearly: 0 });
	let data = $state<TData | null>(null);
	let loading = $state(false);
	let open = $state<Record<string, boolean>>({});
	// Segment: her sütun bağımsız (bekleyen/gerceklesen); varsayılan bekleyen
	let sideView = $state<Record<SideKey, 'bekleyen' | 'gerceklesen'>>({ giris: 'bekleyen', cikis: 'bekleyen' });
	// Tarih görünümü toggle (kategori↔gün); her sütun bağımsız
	let dateView = $state<Record<SideKey, boolean>>({ giris: false, cikis: false });
	// Mobil (README): kapalıyken "Bugün" özet kartı, dokununca tam T hesap açılır
	let expanded = $state(false);
	let todaySummary = $state<TData | null>(null);
	const cache = new Map<string, TData>();

	function fmtEur(n: number): string {
		return '€' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(n));
	}
	// Kalem kendi para biriminde (detay satırı) — grup/kolon toplamı EUR kalır
	const CUR_SYM: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$', GBP: '£' };
	function fmtNative(n: number, currency: string): string {
		const sym = CUR_SYM[currency] || (currency + ' ');
		return sym + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(n));
	}
	// Toplu/tekil satır tutarı: tek para birimi → native (₺/€…); karışık (currency=null) → EUR toplam
	function rowAmountLabel(row: CashRow): string {
		return row.currency ? fmtNative(row.amount_native, row.currency) : fmtEur(row.amount_eur);
	}

	// ── Segment bölme (kategori görünümü) — sayaç-bazlı (items kırpık olabilir) ──
	function catGroups(groups: TGroup[], realized: boolean): TGroup[] {
		return groups
			.map((g) => {
				const rEur = g.realized_eur ?? 0;
				const rCount = g.realized_count ?? 0;
				return {
					...g,
					items: g.items.filter((it) => !!it.is_realized === realized),
					total_eur: realized ? rEur : g.total_eur - rEur,
					item_count: realized ? rCount : g.item_count - rCount,
				};
			})
			.filter((g) => g.item_count > 0)
			.sort((a, b) => b.total_eur - a.total_eur);
	}

	// Açık kategori grubunun kalemlerini gün başlıkları altında grupla (Map-bazlı → mükerrer
	// anahtar/donma yok; backend items'ı tarih sıralı gönderir). Günlük toplam EUR.
	function groupItemsByDate(items: TItem[]): DayBucket[] {
		const byDate = new Map<string, DayBucket>();
		const out: DayBucket[] = [];
		for (const it of items) {
			let cur = byDate.get(it.date);
			if (!cur) {
				const [y, m, d] = it.date.split('-').map(Number);
				cur = { date: it.date, label: `${d} ${MONTHS[m - 1]} ${y}`, items: [], totalEur: 0 };
				byDate.set(it.date, cur);
				out.push(cur);
			}
			cur.items.push(it);
			cur.totalEur += it.amount_eur;
		}
		return out;
	}

	// ── Tarih görünümü — segment'e göre kalemleri düzleştir; GÜN → KATEGORİ alt-grubu → satır.
	// Kategori "Cari Ödemeleri" ise satırlar firma bazında TOPLU (aggregateRows), diğerlerinde her kalem AYRI.
	function dateBuckets(groups: TGroup[], realized: boolean): { days: DateDay[]; hasMore: boolean; moreText: string } {
		const flat: (TItem & { cat: string })[] = [];
		for (const g of groups) for (const it of g.items) if (!!it.is_realized === realized) flat.push({ ...it, cat: g.label });
		flat.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

		const byDate = new Map<string, { date: string; label: string; totalEur: number; catMap: Map<string, (TItem & { cat: string })[]> }>();
		const dayOrder: string[] = [];
		for (const it of flat) {
			let day = byDate.get(it.date);
			if (!day) {
				const [y, m, d] = it.date.split('-').map(Number);
				day = { date: it.date, label: `${d} ${MONTHS[m - 1]} ${y}`, totalEur: 0, catMap: new Map() };
				byDate.set(it.date, day);
				dayOrder.push(it.date);
			}
			day.totalEur += it.amount_eur;
			let catItems = day.catMap.get(it.cat);
			if (!catItems) { catItems = []; day.catMap.set(it.cat, catItems); }
			catItems.push(it);
		}

		const days: DateDay[] = dayOrder.map((d) => {
			const day = byDate.get(d)!;
			const cats: DateCat[] = [...day.catMap.entries()]
				.map(([label, items]) => ({
					label,
					totalEur: items.reduce((s, it) => s + it.amount_eur, 0),
					rows: aggregateRows(items, AGGREGATE_LABELS.has(label)).map((r) => ({ name: r.name, amountLabel: rowAmountLabel(r) })),
				}))
				.sort((a, b) => b.totalEur - a.totalEur);
			return { date: day.date, label: day.label, totalEur: day.totalEur, cats };
		});

		if (days.length > MAX_DATE_DAYS) {
			const extra = days.length - MAX_DATE_DAYS;
			return { days: days.slice(0, MAX_DATE_DAYS), hasMore: true, moreText: `+${extra} gün daha (Nakit Akım sayfasında tümü)` };
		}
		return { days, hasMore: false, moreText: '' };
	}

	function segTotals(side: SideKey) {
		if (!data) return { realized: 0, pending: 0, hasData: false };
		const total = side === 'giris' ? data.total_in_eur : data.total_out_eur;
		const realized = (side === 'giris' ? data.realized_in_eur : data.realized_out_eur) ?? 0;
		const raw = side === 'giris' ? data.giris : data.cikis;
		return { realized, pending: total - realized, hasData: raw.length > 0 };
	}

	// Dönem etiketi — start/end_date'ten (README biçimleri)
	const periodLabel = $derived.by(() => {
		if (!data) return '';
		const s = new Date(data.start_date + 'T00:00:00');
		if (period === 'daily') return `${WEEKDAYS[s.getDay()]}, ${s.getDate()} ${MONTHS[s.getMonth()]} ${s.getFullYear()}`;
		if (period === 'weekly') {
			const e = new Date(data.end_date + 'T00:00:00');
			return `${s.getDate()} ${MONTHS_SHORT[s.getMonth()]} – ${e.getDate()} ${MONTHS_SHORT[e.getMonth()]} ${e.getFullYear()}`;
		}
		if (period === 'monthly') return `${MONTHS[s.getMonth()]} ${s.getFullYear()}`;
		return String(s.getFullYear());
	});

	async function load() {
		const off = offsets[period];
		const key = `${period}:${off}`;
		const cached = cache.get(key);
		if (cached) { data = cached; return; }
		loading = true;
		try {
			const r = await api.get<TData>(`/finance/cash-flow/t-account?period=${period}&offset=${off}`);
			cache.set(key, r);
			data = r;
		} catch (err) {
			console.error('T hesap verisi yüklenemedi:', err);
			showToast('Nakit akım T hesap verisi yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	// Dönem/gezinme değişince segment + tarih görünümü + açık gruplar sıfırlanır (tasarım kararı)
	function resetViews() {
		open = {};
		sideView = { giris: 'bekleyen', cikis: 'bekleyen' };
		dateView = { giris: false, cikis: false };
	}
	function setPeriod(v: string) {
		period = v as typeof period;
		resetViews();
		load();
	}
	function nav(delta: number) {
		if (delta > 0 && offsets[period] >= MAX_FUTURE_OFFSET) return; // ileri üst sınır (gelecek dönem)
		if (delta < 0 && offsets[period] <= -120) return; // backend alt sınırı (ge=-120)
		offsets[period] += delta;
		resetViews();
		load();
	}
	function setSegment(side: SideKey, v: 'bekleyen' | 'gerceklesen') {
		sideView[side] = v;
		open = {}; // segment değişince açık gruplar kapanır (yerinde swap)
	}
	function toggleDateView(side: SideKey) {
		dateView[side] = !dateView[side];
		open = {};
	}
	function toggle(key: string) {
		open[key] = !open[key];
	}

	onMount(() => {
		load();
		// Mobil özet kartı için bugünün Giriş/Çıkış/Net değerleri
		api.get<TData>('/finance/cash-flow/t-account?period=daily&offset=0')
			.then((r) => { cache.set('daily:0', r); todaySummary = r; })
			.catch((err) => console.error('Günlük özet yüklenemedi:', err));
	});
</script>

<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
	<!-- Başlık -->
	<div class="mb-4 flex items-start justify-between gap-3">
		<div>
			<h3 class="text-[17px] text-gray-900">Nakit Akım</h3>
			<!-- Masaüstü alt-başlık kaldırıldı; yerine aşağıya nakit projeksiyon grafiği (RunwayChart) geldi.
			     Mobil kapalı görünümde "Bugün" etiketi mini özet kartını niteler. -->
			<p class="text-xs text-gray-500 mt-0.5 sm:hidden {expanded ? 'hidden' : ''}">Bugün</p>
		</div>
		<!-- Mobil: kapalıyken "detay için dokun" ipucu (sağ üst köşe) -->
		<button type="button" onclick={() => (expanded = true)} aria-label="Detayı aç"
			class="sm:hidden {expanded ? 'hidden' : ''} shrink-0 -mt-0.5 flex items-center gap-1 text-xs text-teal-700 font-medium cursor-pointer">
			detay için dokun <ChevronRight size={14} />
		</button>
		<!-- Mobil: tam görünümü kapat (yukarı ok) -->
		<button type="button" onclick={() => (expanded = false)} aria-label="Özete dön"
			class="sm:hidden {expanded ? '' : 'hidden'} touch-target w-9 h-9 -mt-1 -mr-1 flex items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 cursor-pointer">
			<ChevronUp size={18} />
		</button>
	</div>

	<!-- Dönem kümülatif nakit akışı grafiği — başlığın hemen altında; dönem/offset ile değişir -->
	<RunwayChart {data} />

	<!-- MOBİL ÖZET KARTI (kapalıyken) — Bugün için Giriş/Çıkış/Net mini kutuları -->
	<button type="button" onclick={() => (expanded = true)}
		class="sm:hidden {expanded ? 'hidden' : ''} w-full text-left cursor-pointer">
		<div class="grid grid-cols-3 gap-2">
			<div class="rounded-xl bg-emerald-50 border border-emerald-100 px-3 py-2.5">
				<div class="text-[10px] uppercase tracking-[0.5px] text-emerald-700">Giriş</div>
				<div class="tabular-nums text-sm font-semibold text-emerald-700 mt-0.5">{todaySummary ? fmtEur(todaySummary.total_in_eur) : '…'}</div>
			</div>
			<div class="rounded-xl bg-brass-soft border border-brass/30 px-3 py-2.5">
				<div class="text-[10px] uppercase tracking-[0.5px] text-brass-dark">Çıkış</div>
				<div class="tabular-nums text-sm font-semibold text-brass-dark mt-0.5">{todaySummary ? fmtEur(todaySummary.total_out_eur) : '…'}</div>
			</div>
			<div class="rounded-xl bg-teal-700 px-3 py-2.5">
				<div class="text-[10px] uppercase tracking-[0.5px] text-teal-200">Net</div>
				<div class="tabular-nums text-sm font-semibold mt-0.5 {(todaySummary?.net_eur ?? 0) >= 0 ? 'text-emerald-300' : 'text-red-300'}">
					{todaySummary ? (todaySummary.net_eur >= 0 ? '+' : '−') + fmtEur(Math.abs(todaySummary.net_eur)) : '…'}
				</div>
			</div>
		</div>
	</button>

	<!-- TAM GÖRÜNÜM (mobilde açıkken / masaüstünde her zaman) -->
	<div class="{expanded ? '' : 'hidden'} sm:block">
	<!-- Sekmeler -->
	<SegmentedControl options={PERIODS} value={period} onchange={setPeriod} fullWidth ariaLabel="Dönem seçimi" class="mb-3" />

	<!-- Tarih gezgini -->
	<div class="flex items-center justify-center gap-3 mb-4">
		<button type="button" onclick={() => nav(-1)} aria-label="Önceki dönem"
			class="touch-target w-9 h-9 flex items-center justify-center rounded-full border border-gray-200 text-gray-600 hover:bg-gray-100 cursor-pointer">
			<ChevronLeft size={16} />
		</button>
		<div class="text-center min-w-[190px]">
			<div class="tabular-nums text-sm font-semibold text-gray-900">{periodLabel || '…'}</div>
			<div class="text-[10px] tracking-[1.5px] text-gray-500">{PERIOD_TYPE_LABEL[period]}</div>
		</div>
		<button type="button" onclick={() => nav(1)} aria-label="Sonraki dönem" disabled={offsets[period] >= MAX_FUTURE_OFFSET}
			class="touch-target w-9 h-9 flex items-center justify-center rounded-full border border-gray-200 text-gray-600 hover:bg-gray-100 cursor-pointer disabled:opacity-40 disabled:cursor-default disabled:hover:bg-transparent">
			<ChevronRight size={16} />
		</button>
	</div>

	{#if loading && !data}
		<div class="space-y-2 animate-pulse" aria-hidden="true">
			{#each Array(4) as _}
				<div class="h-8 bg-gray-100 rounded"></div>
			{/each}
		</div>
	{:else if data}
		<!-- Bir kategori grubunun accordion satırı + gün detayı (kategori görünümü) -->
		{#snippet catRows(side: SideKey, realized: boolean, groups: TGroup[])}
			{#each groups as g (g.label)}
				{@const k = `${side}:${realized ? 'g' : 'b'}:${g.label}`}
				<button type="button" onclick={() => toggle(k)} aria-expanded={!!open[k]}
					class="w-full flex items-center gap-2 px-2 py-2 border-t border-gray-100 hover:bg-gray-50 cursor-pointer text-left touch-target">
					<ChevronDown size={13} class="shrink-0 text-gray-500 transition-transform {open[k] ? '' : '-rotate-90'}" />
					<span class="text-[13px] font-semibold text-gray-900 truncate">{g.label}</span>
					<span class="text-[11px] text-gray-500 shrink-0">{g.item_count} işlem</span>
					<span class="ml-auto tabular-nums text-[13px] text-gray-800 shrink-0">{fmtEur(g.total_eur)}</span>
				</button>
				{#if open[k]}
					<div class="pb-1">
						{#each groupItemsByDate(g.items) as day (day.date)}
							<div class="flex items-center justify-between gap-2 pl-8 pr-2 pt-2 pb-1 border-t border-gray-100">
								<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500">{day.label}</span>
								<span class="tabular-nums text-[10.5px] font-semibold text-gray-500 shrink-0">{fmtEur(day.totalEur)}</span>
							</div>
							<!-- Cari grubunda aynı firma birden çok ödeme → tek toplu satır; diğerlerinde her kalem ayrı -->
							{#each aggregateRows(day.items, AGGREGATE_LABELS.has(g.label)) as row, i (i)}
								<div class="flex items-center gap-2 pl-10 pr-2 py-1 text-[12px]">
									<span class="text-gray-700 truncate">{row.name}</span>
									<span class="ml-auto tabular-nums text-gray-700 shrink-0">{rowAmountLabel(row)}</span>
								</div>
							{/each}
						{/each}
						{#if g.item_count > g.items.length}
							<p class="pl-8 pr-2 py-1 text-[11px] text-gray-500">+{g.item_count - g.items.length} kalem daha (Nakit Akım sayfasında tümü)</p>
						{/if}
					</div>
				{/if}
			{/each}
		{/snippet}

		<!-- Tarih görünümü: GÜN başlığı → KATEGORİ alt-başlığı (etiket + işlem sayısı + alt toplam) → satırlar
		     (cari: firma bazında toplu "N ödeme" rozetli; kredi/çek: her kalem ayrı) -->
		{#snippet dateRows(dv: { days: DateDay[]; hasMore: boolean; moreText: string })}
			{#each dv.days as day (day.date)}
				<div class="flex items-center justify-between gap-2 px-2 py-2 border-t border-gray-100 bg-gray-50">
					<span class="text-[11px] font-bold uppercase tracking-wide text-gray-700">{day.label}</span>
					<span class="tabular-nums text-[11px] font-semibold text-gray-600 shrink-0">{fmtEur(day.totalEur)}</span>
				</div>
				{#each day.cats as cat (cat.label)}
					<div class="flex items-center gap-2 pl-4 pr-2 pt-2 pb-0.5">
						<span class="text-[11px] font-semibold text-gray-700 truncate">{cat.label}</span>
						<span class="ml-auto tabular-nums text-[10.5px] font-semibold text-gray-500 shrink-0">{fmtEur(cat.totalEur)}</span>
					</div>
					{#each cat.rows as row, i (i)}
						<div class="flex items-center gap-2 pl-7 pr-2 py-1">
							<span class="text-[12px] text-gray-700 truncate">{row.name}</span>
							<span class="ml-auto tabular-nums text-[12px] text-gray-700 shrink-0">{row.amountLabel}</span>
						</div>
					{/each}
				{/each}
			{/each}
			{#if dv.hasMore}
				<p class="px-4 py-1.5 text-[11px] text-gray-500">{dv.moreText}</p>
			{/if}
		{/snippet}

		<!-- T-account gövdesi: üst 2px lacivert çizgi; ortada dikey ayraç (masaüstü) -->
		<div class="border-t-2 border-teal-700 grid grid-cols-1 sm:grid-cols-2 {loading ? 'opacity-60' : ''}">
			{#each COLS as col (col.side)}
				{@const st = segTotals(col.side)}
				{@const realized = sideView[col.side] === 'gerceklesen'}
				{@const groups = col.side === 'giris' ? data.giris : data.cikis}
				{@const filtered = catGroups(groups, realized)}
				{@const dv = dateView[col.side] ? dateBuckets(groups, realized) : null}
				<div class="{col.side === 'cikis' ? 'sm:border-l-2 sm:border-teal-700 border-t-2 border-teal-700 sm:border-t-0' : ''} px-0 sm:px-3 py-2 {col.side === 'giris' ? 'sm:pr-3 sm:pl-0' : ''}">
					<!-- Sütun başlığı = tarih görünümü toggle'ı (takvim ikonu) -->
					<button type="button" onclick={() => toggleDateView(col.side)}
						aria-pressed={dateView[col.side]}
						title={dateView[col.side] ? 'Kategoriye göre sırala' : 'Tarihe göre sırala'}
						class="touch-target w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-50 cursor-pointer text-left">
						<span class="flex items-center gap-2 text-base sm:text-lg font-semibold tracking-wide uppercase text-gray-800">
							<span class="w-3.5 h-3.5 rounded-sm {col.accent}"></span>{col.title}
							<CalendarDays size={15} class="{dateView[col.side] ? col.totalCls : 'text-gray-400'} transition-colors" />
						</span>
						<span class="tabular-nums text-lg sm:text-xl font-semibold {col.totalCls}">{fmtEur(col.side === 'giris' ? data.total_in_eur : data.total_out_eur)}</span>
					</button>

					<!-- SEGMENT: ✓ Gerçekleşen | Bekleyen (yerinde swap; ayrı panel yok) -->
					{#if st.hasData}
						<div role="tablist" aria-label="{col.title} durum" class="flex gap-1 bg-gray-100 rounded-lg p-1 mx-2 mt-1 mb-2">
							<button type="button" role="tab" aria-selected={realized} onclick={() => setSegment(col.side, 'gerceklesen')}
								class="touch-target flex-1 flex flex-col items-start gap-0 px-2.5 py-1 rounded-md cursor-pointer transition-colors {realized ? 'bg-white shadow-sm' : 'hover:bg-white/50'}">
								<span class="text-[9.5px] uppercase tracking-wide text-emerald-700">✓ Gerçekleşen</span>
								<span class="tabular-nums text-[12.5px] font-semibold text-emerald-700">{fmtEur(st.realized)}</span>
							</button>
							<button type="button" role="tab" aria-selected={!realized} onclick={() => setSegment(col.side, 'bekleyen')}
								class="touch-target flex-1 flex flex-col items-start gap-0 px-2.5 py-1 rounded-md cursor-pointer transition-colors {!realized ? 'bg-white shadow-sm' : 'hover:bg-white/50'}">
								<span class="text-[9.5px] uppercase tracking-wide {!realized ? 'text-gray-700' : 'text-gray-500'}">Bekleyen</span>
								<span class="tabular-nums text-[12.5px] font-semibold {!realized ? 'text-gray-900' : 'text-gray-500'}">{fmtEur(st.pending)}</span>
							</button>
						</div>
					{/if}

					<!-- İçerik: boş / tarih görünümü / kategori görünümü -->
					{#if filtered.length === 0}
						<p class="px-2 py-3 text-xs text-gray-500">
							{!st.hasData ? 'Bu dönemde kayıt yok.' : realized ? 'Gerçekleşen işlem yok.' : 'Bekleyen işlem yok.'}
						</p>
					{:else if dv}
						{@render dateRows(dv)}
					{:else}
						{@render catRows(col.side, realized, filtered)}
					{/if}
				</div>
			{/each}
		</div>

		<!-- Net bant -->
		<div class="mt-3 rounded-xl bg-teal-700 text-white flex items-center justify-between gap-3 px-4 py-3">
			<span class="text-xs sm:text-sm text-gray-200">Net Nakit Akım · {periodLabel}</span>
			<span class="tabular-nums text-lg font-semibold {data.net_eur >= 0 ? 'text-emerald-300' : 'text-red-300'}">
				{data.net_eur >= 0 ? '+' : '−'}{fmtEur(Math.abs(data.net_eur))}
			</span>
		</div>
		{#if data.skipped_no_rate > 0}
			<p class="mt-2 text-[11px] text-amber-700">{data.skipped_no_rate} kalem kur bilgisi olmadığından hesaba katılamadı.</p>
		{/if}
	{/if}

	</div>

	<!-- Vadesi Geçenler — Nakit Akım kartının EN ALTINDA (kullanıcı isteği 2026-07-06) -->
	<OverdueList />
</div>
