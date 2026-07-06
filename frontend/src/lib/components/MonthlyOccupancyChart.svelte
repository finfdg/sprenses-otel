<script lang="ts">
	// Aylık Doluluk Etkisi grafiği — tıklanan günün rezervasyonlarını konaklama
	// tarihlerine göre ay ay "oda-gece" (room-nights) olarak dağıtıp bar grafiğinde gösterir.
	import { BarChart3 } from 'lucide-svelte';

	// Sabitler
	const MONTHS_TR = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const CHART_W = 760;
	const CHART_H = 220;
	const PAD = { top: 20, right: 16, bottom: 44, left: 46 };
	const PLOT_W = CHART_W - PAD.left - PAD.right;
	const PLOT_H = CHART_H - PAD.top - PAD.bottom;
	const BASE_Y = PAD.top + PLOT_H;

	// Props
	let { items = [], mode = 'new' }: { items: any[]; mode: 'new' | 'cancelled' } = $props();

	// Türetilmiş — ay kovaları (oda-gece + misafir-gece + giriş adedi)
	let buckets = $derived(computeBuckets(items));
	let maxNights = $derived(Math.max(1, ...buckets.map((b) => b.nights)));
	let totalNights = $derived(buckets.reduce((s, b) => s + b.nights, 0));
	let totalPax = $derived(buckets.reduce((s, b) => s + b.pax, 0));
	let slot = $derived(buckets.length ? PLOT_W / buckets.length : PLOT_W);
	let barW = $derived(Math.min(slot * 0.6, 56));
	let yTicks = $derived([0, 0.5, 1].map((f) => ({ v: Math.round(maxNights * f), y: BASE_Y - f * PLOT_H })));
	let barFill = $derived(mode === 'new' ? 'var(--color-teal-700)' : 'var(--color-red-500)');
	let valFill = $derived(mode === 'new' ? 'var(--color-teal-800)' : 'var(--color-red-600)');

	// Yardımcı fonksiyonlar
	function keyOf(d: Date): string {
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
	}
	function labelOf(d: Date): string {
		return `${MONTHS_TR[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
	}
	function computeBuckets(list: any[]) {
		const map = new Map<string, { key: string; label: string; nights: number; pax: number; count: number }>();
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
					b = { key: k, label: labelOf(d), nights: 0, pax: 0, count: 0 };
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
	function barX(i: number): number {
		return PAD.left + slot * i + (slot - barW) / 2;
	}
	function barH(v: number): number {
		return (v / maxNights) * PLOT_H;
	}
</script>

<div class="rounded-xl border border-gray-200 bg-gray-50/60 p-3">
	<div class="flex items-center justify-between mb-1.5">
		<div class="flex items-center gap-1.5 text-sm font-semibold text-gray-700">
			<BarChart3 size={16} class={mode === 'new' ? 'text-teal-700' : 'text-red-600'} />
			Aylık Doluluk Etkisi
		</div>
		<span class="text-xs text-gray-500 tabular-nums">
			{totalNights.toLocaleString('tr-TR')} oda-gece · {buckets.length} ay
		</span>
	</div>

	{#if buckets.length === 0}
		<p class="py-6 text-center text-gray-500 text-xs">Konaklama tarihi olan rezervasyon bulunmuyor.</p>
	{:else}
		<svg viewBox="0 0 {CHART_W} {CHART_H}" width="100%" class="block" role="img"
			aria-label="Aylık oda-gece dağılımı grafiği">
			<!-- Y ekseni ızgara + etiket -->
			{#each yTicks as t}
				<line x1={PAD.left} y1={t.y} x2={CHART_W - PAD.right} y2={t.y}
					stroke="var(--color-gray-200)" stroke-width="1" />
				<text x={PAD.left - 8} y={t.y + 4} text-anchor="end"
					font-size="10" fill="var(--color-gray-500)">{t.v}</text>
			{/each}

			<!-- Bar'lar -->
			{#each buckets as b, i (b.key)}
				<g>
					<title>{b.label}: {b.nights} oda-gece · {b.pax} misafir-gece · {b.count} giriş</title>
					<rect x={barX(i)} y={BASE_Y - barH(b.nights)} width={barW} height={barH(b.nights)}
						rx="3" fill={barFill} />
					<text x={barX(i) + barW / 2} y={BASE_Y - barH(b.nights) - 5} text-anchor="middle"
						font-size="10" font-weight="600" fill={valFill}>{b.nights}</text>
					<text x={barX(i) + barW / 2} y={BASE_Y + 15} text-anchor="middle"
						font-size="10" fill="var(--color-gray-500)">{b.label}</text>
				</g>
			{/each}

			<!-- Taban çizgisi -->
			<line x1={PAD.left} y1={BASE_Y} x2={CHART_W - PAD.right} y2={BASE_Y}
				stroke="var(--color-gray-300)" stroke-width="1" />
		</svg>

		<p class="text-[11px] text-gray-500 mt-1">
			Bu günkü {mode === 'new' ? 'gelen' : 'iptal edilen'} rezervasyonların konaklama tarihlerine göre
			ay ay oda-gece dağılımı ({totalPax.toLocaleString('tr-TR')} misafir-gece).
		</p>
	{/if}
</div>
