<!--
	CashFlowTAccount.svelte — Nakit Akım T Hesap Cetveli (Panel yeniden tasarımı, 2026-07-04).

	Muhasebedeki T hesap cetveli mantığı: solda Giriş, sağda Çıkış sütunu (mobilde dikey
	istif), açılır hesap grupları, altta net bant. Dönem sekmeleri (Günlük/Haftalık/Aylık/
	Yıllık) + tarih gezgini (‹ ›; ileri ok şimdiki dönemde devre dışı). Veri:
	GET /finance/cash-flow/t-account?period=&offset= (EUR, gerçek finance_events).
	Tasarım referansı: design_handoff_panel_redesign (lacivert/altın).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import NakitKoruma from '$lib/components/NakitKoruma.svelte';
	import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from 'lucide-svelte';

	type TItem = { name: string; date: string; amount_eur: number; amount_native: number; currency: string; is_realized?: boolean };
	type TGroup = { label: string; total_eur: number; item_count: number; section?: string; items: TItem[]; realized_eur?: number; realized_count?: number };
	type TData = {
		period: string; offset: number; start_date: string; end_date: string;
		giris: TGroup[]; cikis: TGroup[];
		total_in_eur: number; total_out_eur: number; net_eur: number;
		realized_in_eur?: number; realized_out_eur?: number;
		faaliyet_net_eur?: number; finansman_net_eur?: number; skipped_no_rate: number;
	};

	// İleri (gelecek dönem) navigasyon üst sınırı — backend le=24 ile aynı
	const MAX_FUTURE_OFFSET = 24;

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

	// State
	let period = $state<'daily' | 'weekly' | 'monthly' | 'yearly'>('monthly');
	let offsets = $state<Record<string, number>>({ daily: 0, weekly: 0, monthly: 0, yearly: 0 });
	let data = $state<TData | null>(null);
	let loading = $state(false);
	let open = $state<Record<string, boolean>>({});
	// "✓ Gerçekleşen" tıklanınca ödenmiş kalemler kolon başına AYRI listede açılır;
	// ana grup listesi yalnız bekleyenleri gösterir (kullanıcı isteği 2026-07-06)
	let showRealized = $state<Record<string, boolean>>({});
	// Mobil (README): kapalıyken "Bugün" özet kartı (Giriş/Çıkış/Net mini kutular),
	// dokununca tam T hesap açılır; masaüstünde her zaman tam görünüm
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
	// Grupları gerçekleşen/bekleyen olarak böl. Tutar/sayı GRUP SAYAÇLARINDAN türetilir
	// (realized_eur/realized_count) — items listesi MAX_ITEMS_PER_GROUP ile kırpık olabilir.
	// Eski backend yanıtında (realized_eur yok) bekleyen listesi tam grubu gösterir (zarif düşüş).
	function splitGroups(groups: TGroup[], realized: boolean): TGroup[] {
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

	// Açılan grubun kalemlerini tarih başlığı altında grupla. Map-bazlı birleştirme:
	// aynı tarih items içinde BİTİŞİK olmasa da tek bucket'a gider → keyed {#each} (day.date)
	// asla mükerrer anahtar üretmez (svelte-each-dupkey donma sınıfına karşı savunma;
	// backend ayrıca items'ı tarihe sıralar → bucket'lar kronolojik kalır).
	// Günlük toplam EUR'da gösterilir (kalemler karışık para birimli olabilir — grup/kolon toplamıyla tutarlı).
	function groupItemsByDate(items: TItem[]): { date: string; label: string; items: TItem[]; totalEur: number }[] {
		const byDate = new Map<string, { date: string; label: string; items: TItem[]; totalEur: number }>();
		const out: { date: string; label: string; items: TItem[]; totalEur: number }[] = [];
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

	function setPeriod(v: string) {
		period = v as typeof period;
		open = {}; // sekme değişince gruplar kapanır
		showRealized = {};
		load();
	}
	function nav(delta: number) {
		if (delta > 0 && offsets[period] >= MAX_FUTURE_OFFSET) return; // ileri üst sınır (gelecek dönem)
		if (delta < 0 && offsets[period] <= -120) return; // backend alt sınırı (ge=-120)
		offsets[period] += delta;
		open = {};
		showRealized = {};
		load();
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
			<p class="text-xs text-gray-500 mt-0.5">
				<span class="sm:hidden {expanded ? 'hidden' : ''}">Bugün</span>
				<span class="{expanded ? '' : 'hidden'} sm:inline">Hesap hareketleri · EUR · grup başlığına tıklayarak detayı açın</span>
			</p>
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

	<!-- MOBİL ÖZET KARTI (kapalıyken) — Bugün için Giriş/Çıkış/Net mini kutuları -->
	<button type="button" onclick={() => (expanded = true)}
		class="sm:hidden {expanded ? 'hidden' : ''} w-full text-left cursor-pointer">
		<div class="grid grid-cols-3 gap-2">
			<div class="rounded-xl bg-teal-50 border border-teal-100 px-3 py-2.5">
				<div class="text-[10px] uppercase tracking-[0.5px] text-teal-600">Giriş</div>
				<div class="tabular-nums text-sm font-semibold text-teal-700 mt-0.5">{todaySummary ? fmtEur(todaySummary.total_in_eur) : '…'}</div>
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
		<!-- Grup satırları — bekleyen ana listede ve "Gerçekleşen" panelinde ortak kullanılır.
		     variant open-state anahtarına girer ki iki listedeki aynı etiket çakışmasın. -->
		{#snippet groupRows(side: string, variant: string, groups: TGroup[])}
			{#each groups as g (g.label)}
				{@const k = `${side}:${variant}:${g.label}`}
				<button type="button" onclick={() => toggle(k)} aria-expanded={!!open[k]}
					class="w-full flex items-center gap-2 px-2 py-2 border-t border-gray-100 hover:bg-gray-50 cursor-pointer text-left touch-target">
					<ChevronDown size={13} class="shrink-0 text-gray-500 transition-transform {open[k] ? '' : '-rotate-90'}" />
					<span class="text-[13px] font-semibold text-gray-900 truncate">{g.label}</span>
					{#if g.section === 'finansman'}
						<span class="shrink-0 text-[9px] font-medium uppercase tracking-wide text-blue-600 bg-blue-50 border border-blue-100 rounded px-1 py-0.5">Finansman</span>
					{/if}
					<span class="text-[11px] text-gray-500 shrink-0">{g.item_count} işlem</span>
					<span class="ml-auto tabular-nums text-[13px] text-gray-800 shrink-0">{fmtEur(g.total_eur)}</span>
				</button>
				{#if open[k]}
					<div class="pb-1">
						{#each groupItemsByDate(g.items) as day (day.date)}
							<!-- Tarih başlığı — o günün kalemleri altında gruplanır + günlük toplam (EUR) -->
							<div class="flex items-center justify-between gap-2 pl-8 pr-2 pt-2 pb-1 border-t border-gray-100">
								<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500">{day.label}</span>
								<span class="tabular-nums text-[10.5px] font-semibold text-gray-500 shrink-0">{fmtEur(day.totalEur)}</span>
							</div>
							{#each day.items as it, i (i)}
								<div class="flex items-center gap-2 pl-10 pr-2 py-1 text-[12px]">
									<span class="text-gray-700 truncate">{it.name}</span>
									<!-- Kalem kendi para biriminde (₺/€…); kolon/grup toplamı EUR konsolide -->
									<span class="ml-auto tabular-nums text-gray-700 shrink-0">{fmtNative(it.amount_native, it.currency)}</span>
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

		<!-- T-account gövdesi: üst 2px lacivert çizgi; ortada dikey ayraç (masaüstü) -->
		<div class="border-t-2 border-teal-700 grid grid-cols-1 sm:grid-cols-2 {loading ? 'opacity-60' : ''}">
			{#each [
				{ side: 'giris', title: 'Giriş', groups: data.giris, total: data.total_in_eur, realized: data.realized_in_eur ?? 0, accent: 'bg-teal-600', totalCls: 'text-teal-600' },
				{ side: 'cikis', title: 'Çıkış', groups: data.cikis, total: data.total_out_eur, realized: data.realized_out_eur ?? 0, accent: 'bg-brass', totalCls: 'text-brass-dark' },
			] as col (col.side)}
				{@const pendingGroups = splitGroups(col.groups, false)}
				{@const realizedGroups = splitGroups(col.groups, true)}
				<div class="{col.side === 'cikis' ? 'sm:border-l-2 sm:border-teal-700 border-t-2 border-teal-700 sm:border-t-0' : ''} px-0 sm:px-3 py-2 {col.side === 'giris' ? 'sm:pr-3 sm:pl-0' : ''}">
					<!-- Sütun başlığı (Giriş/Çıkış — büyük punto) -->
					<div class="px-2 py-1.5">
						<div class="flex items-center justify-between gap-2">
							<span class="flex items-center gap-2 text-base sm:text-lg font-semibold tracking-wide uppercase text-gray-800">
								<span class="w-3.5 h-3.5 rounded-sm {col.accent}"></span>{col.title}
							</span>
							<span class="tabular-nums text-lg sm:text-xl font-semibold {col.totalCls}">{fmtEur(col.total)}</span>
						</div>
						<!-- Gerçekleşen (ödenmiş — tıklayınca ayrı listede) vs bekleyen (planlı, ana liste) -->
						{#if col.realized > 0}
							<div class="flex justify-end items-center gap-2 mt-0.5 text-[11px]">
								<!-- touch-target: ≥44px dokunma alanı (iPad); emerald-700: etkileşimli kontrolde AA kontrast -->
								<button type="button" onclick={() => (showRealized[col.side] = !showRealized[col.side])}
									aria-expanded={!!showRealized[col.side]}
									class="touch-target flex items-center gap-0.5 text-emerald-700 tabular-nums cursor-pointer hover:underline py-1">
									✓ Gerçekleşen {fmtEur(col.realized)}
									<ChevronDown size={11} class="transition-transform {showRealized[col.side] ? '' : '-rotate-90'}" />
								</button>
								<span class="text-gray-400">·</span>
								<span class="text-gray-500 tabular-nums">Bekleyen {fmtEur(col.total - col.realized)}</span>
							</div>
						{/if}
					</div>
					<!-- Gerçekleşen paneli — ödenmiş kalemler ayrı listede (ana listeyi sadeleştirir) -->
					{#if showRealized[col.side] && realizedGroups.length > 0}
						<div class="mx-1 sm:mx-0 mb-2 rounded-xl border border-emerald-200 bg-emerald-50/60 overflow-hidden">
							<div class="flex items-center justify-between gap-2 px-3 pt-2 pb-1">
								<span class="text-[10px] font-semibold uppercase tracking-wide text-emerald-700">✓ Gerçekleşen İşlemler</span>
								<span class="tabular-nums text-[11px] font-semibold text-emerald-700">{fmtEur(col.realized)}</span>
							</div>
							<div class="bg-white/70">
								{@render groupRows(col.side, 'gerceklesen', realizedGroups)}
							</div>
						</div>
					{/if}
					<!-- Bekleyen gruplar (ana liste) -->
					{#if pendingGroups.length === 0}
						<p class="px-2 py-3 text-xs text-gray-500">
							{col.realized > 0 ? 'Bekleyen kayıt yok — tümü gerçekleşti (✓ Gerçekleşen ile görüntüleyin).' : 'Bu dönemde kayıt yok.'}
						</p>
					{/if}
					{@render groupRows(col.side, 'bekleyen', pendingGroups)}
				</div>
			{/each}
		</div>

		<!-- Net bant -->
		<div class="mt-3 rounded-xl bg-teal-700 text-white flex items-center justify-between px-4 py-3">
			<span class="text-xs sm:text-sm">Net Nakit Akım · {periodLabel}</span>
			<span class="tabular-nums text-lg font-semibold {data.net_eur >= 0 ? 'text-emerald-300' : 'text-red-300'}">
				{data.net_eur >= 0 ? '+' : '−'}{fmtEur(Math.abs(data.net_eur))}
			</span>
		</div>
		{#if data.skipped_no_rate > 0}
			<p class="mt-2 text-[11px] text-amber-700">{data.skipped_no_rate} kalem kur bilgisi olmadığından hesaba katılamadı.</p>
		{/if}
	{/if}

		<!-- Nakit Koruma · Ödeme Erteleme — Nakit Akım kartının içinde, en altta -->
		<NakitKoruma embedded />
	</div>
</div>
