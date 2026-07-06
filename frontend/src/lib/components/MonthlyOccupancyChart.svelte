<script lang="ts">
	// Aylık Doluluk Etkisi — Otel Rezervasyon'daki "Aylık Doluluk Dağılımı" tarzı yatay
	// bar. Her ay için otelin MEVCUT doluluğu lacivert çubukla çizilir; tıklanan günün
	// gelen/iptal rezervasyonlarının o aya kattığı oda-gece, çubuğun UCUNDA farklı renkle
	// (gelen = pirinç/altın, iptal = kırmızı) gösterilir. Doluluk taban verisi
	// `/sales/reservations/summary` (monthly + kapasite) ile gelir; bugünün katkısı
	// modaldeki `items`'tan istemci tarafında hesaplanır (ek endpoint yok).
	import { BarChart3 } from 'lucide-svelte';

	// Sabitler
	const MONTHS_TR = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];

	// Props
	let {
		items = [],
		mode = 'new',
		monthly = [],
		capacity = 0,
	}: {
		items: any[];
		mode: 'new' | 'cancelled';
		monthly: any[];
		capacity: number;
	} = $props();

	// Türetilmiş
	let buckets = $derived(computeBuckets(items));
	let rows = $derived(buildRows(buckets, monthly, capacity, mode));
	let totalNights = $derived(buckets.reduce((s, b) => s + b.nights, 0));
	let totalPax = $derived(buckets.reduce((s, b) => s + b.pax, 0));

	// Yardımcı fonksiyonlar
	function keyOf(d: Date): string {
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
	}
	function labelFromKey(key: string): string {
		const [y, m] = key.split('-').map(Number);
		return `${MONTHS_TR[m - 1]} ${String(y).slice(2)}`;
	}
	function fmtInt(n: number): string {
		return Math.round(n).toLocaleString('tr-TR');
	}
	function computeBuckets(list: any[]) {
		const map = new Map<string, { key: string; nights: number; pax: number; count: number }>();
		for (const it of list) {
			if (!it.checkin_date || !it.checkout_date) continue;
			const ci = new Date(it.checkin_date + 'T00:00:00');
			const co = new Date(it.checkout_date + 'T00:00:00');
			if (isNaN(ci.getTime()) || isNaN(co.getTime()) || co <= ci) continue;
			const pax = it.pax || 0;
			const startKey = keyOf(ci);
			const d = new Date(ci);
			while (d < co) {
				const k = keyOf(d);
				let b = map.get(k);
				if (!b) {
					b = { key: k, nights: 0, pax: 0, count: 0 };
					map.set(k, b);
				}
				b.nights += 1;
				b.pax += pax;
				d.setDate(d.getDate() + 1);
			}
			const sb = map.get(startKey);
			if (sb) sb.count += 1;
		}
		return [...map.values()].sort((a, b) => a.key.localeCompare(b.key));
	}
	function buildRows(bkts: any[], base: any[], cap: number, m: 'new' | 'cancelled') {
		const baseMap = new Map((base || []).map((row: any) => [row.month, row]));
		return bkts.map((b) => {
			const [y, mo] = b.key.split('-').map(Number);
			const daysInMonth = new Date(y, mo, 0).getDate();
			const bm = baseMap.get(b.key);
			const capacityNights = bm?.capacity_nights ?? cap * daysInMonth;
			const occRoomNights = bm?.room_nights ?? 0;
			const occPct = capacityNights > 0 ? (occRoomNights / capacityNights) * 100 : 0;
			const todayPct = capacityNights > 0 ? (b.nights / capacityNights) * 100 : 0;
			let navyW: number;
			let tipW: number;
			if (m === 'new') {
				// Bugünün katkısı mevcut doluluğun UCUNDA (içinde) vurgulanır
				tipW = Math.min(todayPct, Math.max(occPct, todayPct));
				navyW = Math.max(occPct - todayPct, 0);
			} else {
				// İptaller mevcut dolulukta değil → çubuğun ardına (kayıp) eklenir
				navyW = occPct;
				tipW = Math.min(todayPct, Math.max(100 - occPct, 0));
			}
			return {
				key: b.key,
				label: labelFromKey(b.key),
				occPct,
				occRoomNights,
				capacityNights,
				todayNights: b.nights,
				todayPax: b.pax,
				count: b.count,
				navyW: Math.min(navyW, 100),
				tipW: Math.min(tipW, 100),
			};
		});
	}
</script>

<div class="rounded-xl border border-gray-200 bg-gray-50/60 p-3">
	<div class="flex items-center justify-between mb-1">
		<div class="flex items-center gap-1.5 text-sm font-semibold text-gray-700">
			<BarChart3 size={16} class={mode === 'new' ? 'text-teal-700' : 'text-red-600'} />
			Aylık Doluluk Etkisi
		</div>
		<span class="text-xs text-gray-500 tabular-nums">
			{fmtInt(totalNights)} oda-gece · {rows.length} ay
		</span>
	</div>

	{#if rows.length === 0}
		<p class="py-6 text-center text-gray-500 text-xs">Konaklama tarihi olan rezervasyon bulunmuyor.</p>
	{:else}
		<!-- Lejant -->
		<div class="flex items-center gap-4 text-[11px] text-gray-500 mb-2.5">
			<span class="inline-flex items-center gap-1.5">
				<span class="w-2.5 h-2.5 rounded-sm bg-teal-700"></span> Mevcut doluluk
			</span>
			<span class="inline-flex items-center gap-1.5">
				<span class="w-2.5 h-2.5 rounded-sm {mode === 'new' ? 'bg-brass' : 'bg-red-500'}"></span>
				{mode === 'new' ? 'Bu günün katkısı' : 'Bu gün iptal (kayıp)'}
			</span>
		</div>

		<!-- Bar'lar -->
		<div class="space-y-2">
			{#each rows as r (r.key)}
				<div class="flex items-center gap-2 sm:gap-3">
					<div class="w-12 sm:w-14 shrink-0 text-xs text-gray-600 font-medium tabular-nums">{r.label}</div>
					<div
						class="flex-1 min-w-0 bg-gray-100 rounded-full h-7 relative overflow-hidden flex"
						title="{r.label}: mevcut %{r.occPct.toFixed(0)} ({fmtInt(r.occRoomNights)}/{fmtInt(r.capacityNights)} oda-gece) · bu gün {mode === 'new' ? '+' : '−'}{fmtInt(r.todayNights)} oda-gece ({r.count} rez)"
					>
						<div class="h-full bg-teal-700" style="width: {r.navyW.toFixed(1)}%"></div>
						<div class="h-full {mode === 'new' ? 'bg-brass' : 'bg-red-500'}" style="width: {r.tipW.toFixed(1)}%"></div>
						<div class="absolute inset-0 flex items-center px-2.5 text-[11px]">
							<span
								class="font-medium truncate"
								class:text-white={r.occPct >= 25}
								class:text-gray-700={r.occPct < 25}
							>{fmtInt(r.occRoomNights)} dolu</span>
						</div>
					</div>
					<div class="w-20 sm:w-24 shrink-0 text-right leading-tight">
						<div class="text-xs font-semibold text-gray-700 tabular-nums">%{r.occPct.toFixed(0)}</div>
						<div class="text-[11px] font-semibold tabular-nums {mode === 'new' ? 'text-brass-dark' : 'text-red-600'}">
							{mode === 'new' ? '+' : '−'}{fmtInt(r.todayNights)} gece
						</div>
					</div>
				</div>
			{/each}
		</div>

		<p class="text-[11px] text-gray-500 mt-2.5">
			Lacivert çubuk otelin o ayki mevcut doluluğu; uçtaki
			<span class="font-medium {mode === 'new' ? 'text-brass-dark' : 'text-red-600'}">
				{mode === 'new' ? 'pirinç' : 'kırmızı'}
			</span>
			kısım bu günkü {mode === 'new' ? 'gelen' : 'iptal edilen'} rezervasyonların oda-gece etkisidir
			({totalPax.toLocaleString('tr-TR')} misafir-gece).
			{#if capacity === 0}
				<span class="block mt-0.5 text-amber-600">Doluluk taban verisi yüklenemedi — yalnızca bu günün katkısı gösteriliyor.</span>
			{/if}
		</p>
	{/if}
</div>
