<!--
	DailyActivityPanel.svelte — Günlük Hareketler sekmesi (Acente Mahsup & Nakit Akım birleşik sayfası).

	Eski /dashboard/satis/gunluk-hareketler sayfasının içeriği (2026-07-09 birleştirme):
	gün gün gelen yeni rezervasyonlar ve iptaller — Sedna önbüro verisinden canlı,
	drill-down modal + aylık doluluk etkisi grafiği. İzin kodu: sales.acente_mahsup (view).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import StatCard from '$lib/components/StatCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import MonthlyOccupancyChart from '$lib/components/MonthlyOccupancyChart.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { CalendarDays, CalendarPlus, CalendarX, Sigma, TrendingUp, RefreshCw, Loader2 } from 'lucide-svelte';

	// Sabitler
	const GUN = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
	const QUICK_RANGES = [
		{ key: 'd7', label: 'Son 7 Gün' },
		{ key: 'd14', label: 'Son 14 Gün' },
		{ key: 'd30', label: 'Son 30 Gün' },
		{ key: 'month', label: 'Bu Ay' },
	] as const;
	const eur0 = new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
	const eur2 = new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });

	// State — filtreler
	let quick = $state<string>('d14');
	let startDate = $state('');
	let endDate = $state('');

	// State — veri
	let loading = $state(true);
	let configured = $state(true);
	let data = $state<any>({ days: [], totals: null });

	// State — drill-down modal
	let detailOpen = $state(false);
	let detailDate = $state('');
	let detailTab = $state<'new' | 'cancelled'>('new');
	let detailLoading = $state(false);
	let detailItems = $state<any[]>([]);
	let detailCounts = $state({ new: 0, cancelled: 0 });

	// State — doluluk taban verisi (Aylık Doluluk Etkisi grafiği için, tek sefer çekilir)
	let occMonthly = $state<any[]>([]);
	let occCapacity = $state(0);
	let occLoaded = $state(false);

	// Türetilmiş
	let totals = $derived(data.totals);
	let hasActivity = $derived(data.days.some((d: any) => d.new.count || d.cancelled.count));
	let todayIso = $derived(toISO(new Date()));

	// Formatlama
	function toISO(d: Date): string {
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	}
	function fmtD(s: string | null): string {
		if (!s) return '—';
		const [y, m, d] = s.split('-');
		return `${d}.${m}.${y}`;
	}
	function dayLabel(s: string): string {
		const [y, m, d] = s.split('-').map(Number);
		return `${String(d).padStart(2, '0')}.${String(m).padStart(2, '0')} ${GUN[new Date(y, m - 1, d).getDay()]}`;
	}
	function daysBetween(a: string, b: string): number {
		return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
	}

	// Veri fonksiyonları
	function rangeFor(key: string): { start: string; end: string } {
		const today = new Date();
		if (key === 'month') return { start: toISO(new Date(today.getFullYear(), today.getMonth(), 1)), end: toISO(today) };
		const days = key === 'd7' ? 6 : key === 'd30' ? 29 : 13;
		const s = new Date(today);
		s.setDate(s.getDate() - days);
		return { start: toISO(s), end: toISO(today) };
	}

	async function load() {
		loading = true;
		try {
			data = await api.get<any>(`/sales/daily-activity/summary?start_date=${startDate}&end_date=${endDate}`);
			configured = true;
		} catch (e: any) {
			console.error('Günlük hareketler yüklenemedi:', e);
			if (e?.status === 503) configured = false;
			else showToast('Günlük hareketler yüklenemedi', 'error');
			data = { days: [], totals: null };
		} finally {
			loading = false;
		}
	}

	function setQuick(key: string) {
		quick = key;
		const r = rangeFor(key);
		startDate = r.start;
		endDate = r.end;
		load();
	}

	function customDateChanged() {
		if (!startDate || !endDate) return;
		quick = 'custom';
		load();
	}

	// Drill-down
	async function loadDetail() {
		detailLoading = true;
		detailItems = [];
		try {
			const r = await api.get<any>(`/sales/daily-activity/details?activity_date=${detailDate}&type=${detailTab}`);
			detailItems = r.items || [];
		} catch (e) {
			console.error('Hareket detayları yüklenemedi:', e);
			showToast('Hareket detayları yüklenemedi', 'error');
		} finally {
			detailLoading = false;
		}
	}

	// Doluluk taban verisi — otelin aylık mevcut doluluğu (grafik çubuklarının tabanı).
	// Tıklanan güne bağlı değil → tek sefer çekilip yeniden kullanılır.
	async function loadOccupancy() {
		try {
			const r = await api.get<any>('/sales/reservations/summary');
			occMonthly = r.monthly || [];
			occCapacity = r.kpi?.total_capacity || 0;
			occLoaded = true;
		} catch (e: any) {
			// Kritik değil: taban yüklenemezse (ör. 403 — otel rezervasyon görme izni yok)
			// grafik yalnız bugünün katkısını gösterir + kart içinde görünür uyarı satırı
			// belirir. Bu yüzden toast yerine yalnız console.error (gürültü engellenir).
			console.error('Doluluk taban verisi yüklenemedi:', e);
			occLoaded = true;
		}
	}

	function openDetail(day: any, tab: 'new' | 'cancelled') {
		detailDate = day.date;
		detailCounts = { new: day.new.count, cancelled: day.cancelled.count };
		detailTab = tab;
		detailOpen = true;
		loadDetail();
		if (!occLoaded) loadOccupancy();
	}

	function setTab(t: 'new' | 'cancelled') {
		if (detailTab !== t) {
			detailTab = t;
			loadDetail();
		}
	}

	onMount(() => {
		const r = rangeFor('d14');
		startDate = r.start;
		endDate = r.end;
		load();
	});
</script>

<div class="space-y-5">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h2 class="text-base font-semibold text-gray-900">Günlük Rezervasyon Hareketleri</h2>
			<p class="mt-0.5 text-xs text-gray-500">Gün gün gelen yeni rezervasyonlar ve iptaller — Sedna önbüro verisinden canlı.</p>
		</div>
		<Button variant="secondary" onclick={load} loading={loading}>
			<RefreshCw size={16} /> Yenile
		</Button>
	</div>

	{#if !configured}
		<EmptyState
			icon={CalendarDays}
			title="Sedna bağlantısı yok"
			description="Günlük hareketler canlı Sedna önbüro verisinden gelir; bağlantı (SEDNA_PASSWORD) yapılandırılmamış veya tünel kapalı."
		/>
	{:else}
		<!-- Özet kartlar -->
		{#if totals}
			<div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
				<StatCard
					label="Gelen Rezervasyon"
					value={totals.new.count.toLocaleString('tr-TR')}
					accent="teal"
					icon={CalendarPlus}
					hint={`${totals.new.nights.toLocaleString('tr-TR')} gece · ${totals.new.pax.toLocaleString('tr-TR')} misafir`}
				/>
				<StatCard
					label="İptal"
					value={totals.cancelled.count.toLocaleString('tr-TR')}
					accent="red"
					icon={CalendarX}
					hint={`${eur0.format(totals.cancelled.eur)} · oran %${totals.cancel_rate.toLocaleString('tr-TR')}`}
				/>
				<StatCard
					label="Net Rezervasyon"
					value={totals.net_count.toLocaleString('tr-TR')}
					accent="blue"
					icon={Sigma}
					hint="Gelen − iptal"
				/>
				<StatCard
					label="Net Ciro Etkisi"
					value={eur0.format(totals.net_eur)}
					accent={totals.net_eur >= 0 ? 'emerald' : 'red'}
					icon={TrendingUp}
					hint={`Gelen ${eur0.format(totals.new.eur)}`}
				/>
			</div>
		{/if}

		<!-- Filtre barı -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3 sm:p-4 flex flex-wrap items-center gap-3">
			<div class="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm">
				{#each QUICK_RANGES as r, i (r.key)}
					<button
						onclick={() => setQuick(r.key)}
						class="px-3 py-1.5 font-medium {i > 0 ? 'border-l border-gray-200' : ''} {quick === r.key
							? 'bg-teal-700 text-white'
							: 'bg-white text-gray-600 hover:bg-gray-50'}"
					>{r.label}</button>
				{/each}
			</div>
			<div class="inline-flex items-center gap-1.5 text-sm text-gray-600">
				<Input
					type="date"
					size="sm"
					fullWidth={false}
					bind:value={startDate}
					onchange={customDateChanged}
				/>
				<span class="text-gray-500">→</span>
				<Input
					type="date"
					size="sm"
					fullWidth={false}
					bind:value={endDate}
					onchange={customDateChanged}
				/>
			</div>
			{#if totals}
				<span class="ml-auto text-sm text-gray-500">
					{data.days.length} gün · {totals.new.count + totals.cancelled.count} hareket
				</span>
			{/if}
		</div>

		<!-- Günlük tablo / kartlar -->
		{#if loading}
			<TableSkeleton rows={8} columns={6} />
		{:else if !hasActivity}
			<EmptyState
				icon={CalendarDays}
				title="Hareket yok"
				description="Seçilen dönemde gelen rezervasyon veya iptal kaydı bulunmuyor."
			/>
		{:else}
			<!-- Desktop tablo -->
			<div class="hidden md:block bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
				<div class="overflow-x-auto">
					<table class="w-full text-sm border-collapse">
						<thead>
							<tr class="bg-gray-50 border-b border-gray-200">
								<th rowspan="2" class="text-left font-semibold text-gray-700 px-3 py-2 align-bottom">Tarih</th>
								<th colspan="4" class="text-center font-semibold text-teal-800 bg-teal-50/70 px-2 py-1.5 border-l border-gray-200">Gelen Rezervasyonlar</th>
								<th colspan="4" class="text-center font-semibold text-red-700 bg-red-50/70 px-2 py-1.5 border-l border-gray-200">İptaller</th>
								<th colspan="2" class="text-center font-semibold text-gray-700 px-2 py-1.5 border-l border-gray-200">Net</th>
							</tr>
							<tr class="bg-gray-50 border-b border-gray-200 text-gray-600">
								<th class="text-right font-medium px-2 py-1.5 border-l border-gray-200">Adet</th>
								<th class="text-right font-medium px-2 py-1.5">Gece</th>
								<th class="text-right font-medium px-2 py-1.5">Misafir</th>
								<th class="text-right font-medium px-2 py-1.5">Ciro (€)</th>
								<th class="text-right font-medium px-2 py-1.5 border-l border-gray-200">Adet</th>
								<th class="text-right font-medium px-2 py-1.5">Gece</th>
								<th class="text-right font-medium px-2 py-1.5">Misafir</th>
								<th class="text-right font-medium px-2 py-1.5">Ciro (€)</th>
								<th class="text-right font-medium px-2 py-1.5 border-l border-gray-200">Adet</th>
								<th class="text-right font-medium px-2 py-1.5">Ciro (€)</th>
							</tr>
						</thead>
						<tbody>
							{#each data.days as day (day.date)}
								<tr class="border-b border-gray-100 hover:bg-gray-50/60 {day.date === todayIso ? 'bg-teal-50/40' : ''}">
									<td class="px-3 py-2 whitespace-nowrap font-medium text-gray-800 tabular-nums">
										{dayLabel(day.date)}
										{#if day.date === todayIso}
											<span class="ml-1.5 text-[10px] font-semibold text-teal-700 bg-teal-100 rounded-full px-1.5 py-0.5">Bugün</span>
										{/if}
									</td>
									<!-- Gelen -->
									<td class="p-0 text-right border-l border-gray-100">
										{#if day.new.count}
											<button
												onclick={() => openDetail(day, 'new')}
												title="Gelen rezervasyonları gör"
												class="w-full px-2 py-2 text-right font-semibold text-teal-700 tabular-nums hover:bg-teal-50 hover:underline"
											>{day.new.count}</button>
										{:else}
											<span class="block px-2 py-2 text-gray-400">—</span>
										{/if}
									</td>
									<td class="px-2 py-2 text-right tabular-nums {day.new.nights ? 'text-gray-700' : 'text-gray-400'}">{day.new.nights || '—'}</td>
									<td class="px-2 py-2 text-right tabular-nums {day.new.pax ? 'text-gray-700' : 'text-gray-400'}">{day.new.pax || '—'}</td>
									<td class="px-2 py-2 text-right tabular-nums {day.new.eur ? 'text-gray-800' : 'text-gray-400'}">{day.new.eur ? eur0.format(day.new.eur) : '—'}</td>
									<!-- İptal -->
									<td class="p-0 text-right border-l border-gray-100">
										{#if day.cancelled.count}
											<button
												onclick={() => openDetail(day, 'cancelled')}
												title="İptalleri gör"
												class="w-full px-2 py-2 text-right font-semibold text-red-600 tabular-nums hover:bg-red-50 hover:underline"
											>{day.cancelled.count}</button>
										{:else}
											<span class="block px-2 py-2 text-gray-400">—</span>
										{/if}
									</td>
									<td class="px-2 py-2 text-right tabular-nums {day.cancelled.nights ? 'text-gray-700' : 'text-gray-400'}">{day.cancelled.nights || '—'}</td>
									<td class="px-2 py-2 text-right tabular-nums {day.cancelled.pax ? 'text-gray-700' : 'text-gray-400'}">{day.cancelled.pax || '—'}</td>
									<td class="px-2 py-2 text-right tabular-nums {day.cancelled.eur ? 'text-red-600' : 'text-gray-400'}">{day.cancelled.eur ? eur0.format(day.cancelled.eur) : '—'}</td>
									<!-- Net -->
									<td class="px-2 py-2 text-right font-semibold tabular-nums border-l border-gray-100 {day.net_count > 0 ? 'text-teal-700' : day.net_count < 0 ? 'text-red-600' : 'text-gray-500'}">
										{day.net_count > 0 ? '+' : ''}{day.net_count}
									</td>
									<td class="px-2 py-2 text-right font-semibold tabular-nums {day.net_eur > 0 ? 'text-teal-700' : day.net_eur < 0 ? 'text-red-600' : 'text-gray-500'}">
										{day.net_eur ? eur0.format(day.net_eur) : '—'}
									</td>
								</tr>
							{/each}
						</tbody>
						{#if totals}
							<tfoot>
								<tr class="bg-gray-50 border-t-2 border-gray-200 font-semibold text-gray-800">
									<td class="px-3 py-2.5">TOPLAM</td>
									<td class="px-2 py-2.5 text-right tabular-nums text-teal-800 border-l border-gray-200">{totals.new.count}</td>
									<td class="px-2 py-2.5 text-right tabular-nums">{totals.new.nights.toLocaleString('tr-TR')}</td>
									<td class="px-2 py-2.5 text-right tabular-nums">{totals.new.pax.toLocaleString('tr-TR')}</td>
									<td class="px-2 py-2.5 text-right tabular-nums">{eur0.format(totals.new.eur)}</td>
									<td class="px-2 py-2.5 text-right tabular-nums text-red-700 border-l border-gray-200">{totals.cancelled.count}</td>
									<td class="px-2 py-2.5 text-right tabular-nums">{totals.cancelled.nights.toLocaleString('tr-TR')}</td>
									<td class="px-2 py-2.5 text-right tabular-nums">{totals.cancelled.pax.toLocaleString('tr-TR')}</td>
									<td class="px-2 py-2.5 text-right tabular-nums text-red-700">{eur0.format(totals.cancelled.eur)}</td>
									<td class="px-2 py-2.5 text-right tabular-nums border-l border-gray-200 {totals.net_count >= 0 ? 'text-teal-800' : 'text-red-700'}">{totals.net_count > 0 ? '+' : ''}{totals.net_count}</td>
									<td class="px-2 py-2.5 text-right tabular-nums {totals.net_eur >= 0 ? 'text-teal-800' : 'text-red-700'}">{eur0.format(totals.net_eur)}</td>
								</tr>
							</tfoot>
						{/if}
					</table>
				</div>
			</div>

			<!-- Mobil kartlar -->
			<div class="md:hidden space-y-2">
				{#each data.days as day (day.date)}
					{#if day.new.count || day.cancelled.count}
						<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3 {day.date === todayIso ? 'ring-1 ring-teal-300' : ''}">
							<div class="flex items-center justify-between mb-2">
								<span class="font-semibold text-gray-800 tabular-nums">{dayLabel(day.date)}</span>
								<span class="text-sm font-semibold tabular-nums {day.net_eur > 0 ? 'text-teal-700' : day.net_eur < 0 ? 'text-red-600' : 'text-gray-500'}">
									{eur0.format(day.net_eur)}
								</span>
							</div>
							<div class="grid grid-cols-2 gap-2 text-sm">
								<button
									onclick={() => openDetail(day, 'new')}
									disabled={!day.new.count}
									class="rounded-lg border border-teal-100 bg-teal-50/60 px-2.5 py-2 text-left disabled:opacity-40"
								>
									<span class="block text-xs text-teal-800 font-medium">Gelen</span>
									<span class="font-semibold text-teal-700 tabular-nums">{day.new.count} rez · {eur0.format(day.new.eur)}</span>
								</button>
								<button
									onclick={() => openDetail(day, 'cancelled')}
									disabled={!day.cancelled.count}
									class="rounded-lg border border-red-100 bg-red-50/60 px-2.5 py-2 text-left disabled:opacity-40"
								>
									<span class="block text-xs text-red-700 font-medium">İptal</span>
									<span class="font-semibold text-red-600 tabular-nums">{day.cancelled.count} rez · {eur0.format(day.cancelled.eur)}</span>
								</button>
							</div>
						</div>
					{/if}
				{/each}
			</div>

			<p class="text-[11px] text-gray-500">
				Kaynak: Sedna önbüro (canlı) · Gelen = rezervasyonun kayıt tarihi, İptal = iptal tarihi ·
				tutarlar EUR karşılığıdır. <span class="font-medium">Adet hücresine tıkla → rezervasyon detaylarını gör.</span>
			</p>
		{/if}
	{/if}
</div>

<!-- Drill-down: günün gelen/iptal rezervasyonları -->
<Modal bind:show={detailOpen} title={`${fmtD(detailDate)} — Günlük Hareketler`} maxWidth="max-w-4xl">
	<div class="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm mb-3">
		<button
			onclick={() => setTab('new')}
			class="px-3 py-1.5 font-medium {detailTab === 'new' ? 'bg-teal-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
		>Gelenler ({detailCounts.new})</button>
		<button
			onclick={() => setTab('cancelled')}
			class="px-3 py-1.5 font-medium border-l border-gray-200 {detailTab === 'cancelled' ? 'bg-red-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
		>İptaller ({detailCounts.cancelled})</button>
	</div>

	{#if detailLoading}
		<div class="py-10 text-center text-gray-500 text-sm"><Loader2 class="animate-spin inline" size={20} /></div>
	{:else if detailItems.length === 0}
		<p class="py-8 text-center text-gray-500 text-sm">
			{detailTab === 'new' ? 'Bu gün gelen rezervasyon yok.' : 'Bu gün iptal edilen rezervasyon yok.'}
		</p>
	{:else}
		<div class="text-xs text-gray-500 mb-2">
			{detailItems.length} rezervasyon · toplam {eur2.format(detailItems.reduce((s, i) => s + (i.eur || 0), 0))}
		</div>
		<div class="mb-3">
			<MonthlyOccupancyChart items={detailItems} mode={detailTab} monthly={occMonthly} capacity={occCapacity} />
		</div>
		<div class="max-h-[60vh] overflow-y-auto overflow-x-auto -mx-1">
			<table class="w-full text-xs sm:text-sm">
				<!-- sticky HÜCRELERDE (tr'de değil): iOS Safari tr-sticky'de arka planı boyamıyordu →
				     kayan satırlar başlığın üzerinden görünüyordu (vardiya-çizelgesi ile aynı desen) -->
				<thead>
					<tr class="text-gray-600">
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-right font-medium px-2 py-2 w-8">#</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-left font-medium px-2 py-2">Voucher</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-left font-medium px-2 py-2">Acente</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-left font-medium px-2 py-2">Ülke</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-left font-medium px-2 py-2">Oda</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-left font-medium px-2 py-2">Pansiyon</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-left font-medium px-2 py-2 whitespace-nowrap">Konaklama</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-right font-medium px-2 py-2">Pax</th>
						<th class="sticky top-0 z-10 bg-gray-50 border-b border-gray-200 text-right font-medium px-2 py-2">Tutar (€)</th>
					</tr>
				</thead>
				<tbody>
					{#each detailItems as it, i (it.rec_id)}
						<tr class="border-b border-gray-100 align-top {detailTab === 'new' && it.is_cancelled ? 'opacity-60' : ''}">
							<td class="px-2 py-2 tabular-nums text-right text-gray-500">{i + 1}</td>
							<td class="px-2 py-2 tabular-nums text-gray-600 whitespace-nowrap">{it.voucher || '—'}</td>
							<td class="px-2 py-2 text-gray-800 font-medium max-w-[180px]">
								<span class="block truncate" title={it.agency}>{it.agency || '—'}</span>
								{#if detailTab === 'new' && it.is_cancelled}
									<span class="block mt-0.5"><span class="text-[10px] font-semibold text-red-700 bg-red-50 border border-red-200 rounded-full px-1.5 py-0.5">Sonradan iptal</span></span>
								{/if}
							</td>
							<td class="px-2 py-2 text-gray-600">{it.nation || '—'}</td>
							<td class="px-2 py-2 text-gray-600 whitespace-nowrap">{it.room_type || '—'}</td>
							<td class="px-2 py-2 text-gray-600">{it.board || '—'}</td>
							<td class="px-2 py-2 text-gray-700 whitespace-nowrap tabular-nums">
								{fmtD(it.checkin_date)} → {fmtD(it.checkout_date)}
								<span class="text-gray-500">({it.nights} gece)</span>
								{#if detailTab === 'cancelled'}
									<span class="block text-[10px] text-gray-500">
										Kayıt: {fmtD(it.record_date)}{#if it.checkin_date && it.cancel_date && daysBetween(it.cancel_date, it.checkin_date) >= 0}
											· girişe {daysBetween(it.cancel_date, it.checkin_date)} gün kala iptal{/if}
									</span>
								{/if}
							</td>
							<td class="px-2 py-2 text-right tabular-nums text-gray-700">{it.pax}</td>
							<td class="px-2 py-2 text-right tabular-nums font-medium {detailTab === 'cancelled' ? 'text-red-600' : 'text-gray-800'}">
								{eur2.format(it.eur || 0)}
								{#if it.currency && it.currency !== 'EUR'}
									<span class="block text-[10px] text-gray-500 font-normal">{it.amount.toLocaleString('tr-TR')} {it.currency}</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</Modal>
