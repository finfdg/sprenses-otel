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
	import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-svelte';

	type TItem = { name: string; date: string; amount_eur: number };
	type TGroup = { label: string; total_eur: number; item_count: number; items: TItem[] };
	type TData = {
		period: string; offset: number; start_date: string; end_date: string;
		giris: TGroup[]; cikis: TGroup[];
		total_in_eur: number; total_out_eur: number; net_eur: number; skipped_no_rate: number;
	};

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
	const cache = new Map<string, TData>();

	function fmtEur(n: number): string {
		return '€' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(n));
	}
	function fmtDateShort(iso: string): string {
		const [, m, d] = iso.split('-').map(Number);
		return `${d} ${MONTHS_SHORT[m - 1]}`;
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
		if (delta > 0 && offsets[period] >= 0) return; // ileri, şimdiki dönemde durur
		if (delta < 0 && offsets[period] <= -120) return; // backend alt sınırı (ge=-120)
		offsets[period] += delta;
		open = {};
		load();
	}
	function toggle(side: string, label: string) {
		open[`${side}:${label}`] = !open[`${side}:${label}`];
	}

	onMount(load);
</script>

<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
	<!-- Başlık -->
	<div class="mb-4">
		<h3 class="text-[17px] text-gray-900">Nakit Akım · T Hesap Cetveli</h3>
		<p class="text-xs text-gray-500 mt-0.5">Hesap hareketleri · EUR · grup başlığına tıklayarak detayı açın</p>
	</div>

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
		<button type="button" onclick={() => nav(1)} aria-label="Sonraki dönem" disabled={offsets[period] >= 0}
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
				{ side: 'giris', title: 'Giriş', groups: data.giris, total: data.total_in_eur, accent: 'bg-teal-600', totalCls: 'text-teal-600' },
				{ side: 'cikis', title: 'Çıkış', groups: data.cikis, total: data.total_out_eur, accent: 'bg-brass', totalCls: 'text-brass-dark' },
			] as col (col.side)}
				<div class="{col.side === 'cikis' ? 'sm:border-l-2 sm:border-teal-700 border-t-2 border-teal-700 sm:border-t-0' : ''} px-0 sm:px-3 py-2 {col.side === 'giris' ? 'sm:pr-3 sm:pl-0' : ''}">
					<!-- Sütun başlığı -->
					<div class="flex items-center justify-between px-2 py-1.5">
						<span class="flex items-center gap-2 text-xs font-semibold tracking-wide uppercase text-gray-700">
							<span class="w-2.5 h-2.5 rounded-sm {col.accent}"></span>{col.title}
						</span>
						<span class="tabular-nums text-sm font-semibold {col.totalCls}">{fmtEur(col.total)}</span>
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
							<span class="text-[11px] text-gray-500 shrink-0">{g.item_count} işlem</span>
							<span class="ml-auto tabular-nums text-[13px] text-gray-800 shrink-0">{fmtEur(g.total_eur)}</span>
						</button>
						{#if open[k]}
							<div class="pb-1">
								{#each g.items as it, i (i)}
									<div class="flex items-center gap-2 pl-8 pr-2 py-1 text-[12px]">
										<span class="text-gray-700 truncate">{it.name}</span>
										<span class="text-gray-500 shrink-0">· {fmtDateShort(it.date)}</span>
										<span class="ml-auto tabular-nums text-gray-600 shrink-0">{fmtEur(it.amount_eur)}</span>
									</div>
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
</div>
