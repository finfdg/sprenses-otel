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

	type TItem = { name: string; date: string; amount_eur: number; amount_native: number; currency: string };
	type TGroup = { label: string; total_eur: number; item_count: number; section?: string; items: TItem[] };
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
	// Açılan grubun kalemlerini tarih başlığı altında grupla (kalemler backend'den tarih sıralı gelir).
	// Günlük toplam EUR'da gösterilir (kalemler karışık para birimli olabilir — grup/kolon toplamıyla tutarlı).
	function groupItemsByDate(items: TItem[]): { date: string; label: string; items: TItem[]; totalEur: number }[] {
		const out: { date: string; label: string; items: TItem[]; totalEur: number }[] = [];
		let cur: { date: string; label: string; items: TItem[]; totalEur: number } | null = null;
		for (const it of items) {
			if (!cur || cur.date !== it.date) {
				const [y, m, d] = it.date.split('-').map(Number);
				cur = { date: it.date, label: `${d} ${MONTHS[m - 1]} ${y}`, items: [], totalEur: 0 };
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
		load();
	}
	function nav(delta: number) {
		if (delta > 0 && offsets[period] >= MAX_FUTURE_OFFSET) return; // ileri üst sınır (gelecek dönem)
		if (delta < 0 && offsets[period] <= -120) return; // backend alt sınırı (ge=-120)
		offsets[period] += delta;
		open = {};
		load();
	}
	function toggle(side: string, label: string) {
		open[`${side}:${label}`] = !open[`${side}:${label}`];
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
			<h3 class="text-[17px] text-gray-900">Nakit Akım · T Hesap Cetveli</h3>
			<p class="text-xs text-gray-500 mt-0.5">
				<span class="sm:hidden {expanded ? 'hidden' : ''}">Bugün · dokunarak detaylı cetveli açın</span>
				<span class="{expanded ? '' : 'hidden'} sm:inline">Hesap hareketleri · EUR · grup başlığına tıklayarak detayı açın</span>
			</p>
		</div>
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
		<div class="mt-2 text-xs text-teal-600 font-medium flex items-center gap-1">Detaylı T hesap cetveli için dokun <ChevronRight size={13} /></div>
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
		<!-- T-account gövdesi: üst 2px lacivert çizgi; ortada dikey ayraç (masaüstü) -->
		<div class="border-t-2 border-teal-700 grid grid-cols-1 sm:grid-cols-2 {loading ? 'opacity-60' : ''}">
			{#each [
				{ side: 'giris', title: 'Giriş', groups: data.giris, total: data.total_in_eur, realized: data.realized_in_eur ?? 0, accent: 'bg-teal-600', totalCls: 'text-teal-600' },
				{ side: 'cikis', title: 'Çıkış', groups: data.cikis, total: data.total_out_eur, realized: data.realized_out_eur ?? 0, accent: 'bg-brass', totalCls: 'text-brass-dark' },
			] as col (col.side)}
				<div class="{col.side === 'cikis' ? 'sm:border-l-2 sm:border-teal-700 border-t-2 border-teal-700 sm:border-t-0' : ''} px-0 sm:px-3 py-2 {col.side === 'giris' ? 'sm:pr-3 sm:pl-0' : ''}">
					<!-- Sütun başlığı (Giriş/Çıkış — büyük punto) -->
					<div class="px-2 py-1.5">
						<div class="flex items-center justify-between gap-2">
							<span class="flex items-center gap-2 text-base sm:text-lg font-semibold tracking-wide uppercase text-gray-800">
								<span class="w-3.5 h-3.5 rounded-sm {col.accent}"></span>{col.title}
							</span>
							<span class="tabular-nums text-lg sm:text-xl font-semibold {col.totalCls}">{fmtEur(col.total)}</span>
						</div>
						<!-- Gerçekleşen (banka vb. — zaten oldu) vs bekleyen (planlı) ayrımı -->
						{#if col.realized > 0}
							<div class="flex justify-end items-center gap-2 mt-0.5 text-[11px]">
								<span class="text-emerald-600 tabular-nums">✓ Gerçekleşen {fmtEur(col.realized)}</span>
								<span class="text-gray-400">·</span>
								<span class="text-gray-500 tabular-nums">Bekleyen {fmtEur(col.total - col.realized)}</span>
							</div>
						{/if}
					</div>
					<!-- Gruplar -->
					{#if col.groups.length === 0}
						<p class="px-2 py-3 text-xs text-gray-500">Bu dönemde kayıt yok.</p>
					{/if}
					{#each col.groups as g (g.label)}
						{@const k = `${col.side}:${g.label}`}
						<button type="button" onclick={() => toggle(col.side, g.label)} aria-expanded={!!open[k]}
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
