<!--
	RunwayChart.svelte — Nakit projeksiyon eğrisi (bankadaki nakitten ay sonuna gün gün).

	Panel Nakit Akım kartının ÜSTÜNDE (başlık altında) gösterilir. Veri paylaşımlı
	`runway.svelte` deposundan gelir (tek fetch; vadesi geçenlerle ortak). Grafiğin üzerine
	dokununca gün + bakiye ipucu çıkar. Eski NakitKoruma'dan ayrılan grafik parçası (2026-07-06).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { projectRunway } from '$lib/utils/finance';
	import { runwayStore, subscribeRunway, fmtEur, signed, labelDate, dayNum, MONTHS_SHORT } from '$lib/stores/runway.svelte';

	const data = $derived(runwayStore.data);
	const loading = $derived(runwayStore.loading);
	// Runway grafiği hover — dokunulan günün izdüşümü + bakiye ipucu
	let hoverIdx = $state<number | null>(null);

	const proj = $derived.by(() => {
		if (!data) return null;
		const today = data.today;
		const projOuts = data.outs.map((o) => ({ id: o.id, date: o.date, amount_eur: o.amount_eur }));
		const r = projectRunway(data.start_eur, data.inflows, projOuts, today, data.month_end, {});

		const vals = r.byDay.map((p) => p.bal);
		const hi = Math.max(data.start_eur, ...vals);
		const lo = Math.min(0, ...vals);
		const pad = (hi - lo) * 0.14 || 1;
		const top = 12, bottom = 108;
		const startDay = dayNum(today), endDay = dayNum(data.month_end);
		const span = endDay - startDay || 1;
		const mapX = (d: number) => ((d - startDay) / span) * 620;
		const mapY = (v: number) => bottom - ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (bottom - top);
		const pts = r.byDay.map((p) => `${mapX(p.day).toFixed(1)},${mapY(p.bal).toFixed(1)}`).join(' ');

		const ym = today.slice(0, 7);
		const negative = r.firstNeg !== null;
		return {
			negative,
			statusText: negative
				? `${r.firstNeg} ${MONTHS_SHORT[Number(ym.slice(5, 7)) - 1]}'de bakiye negatife düşüyor`
				: 'Ay boyunca nakit pozitif kalıyor',
			pts, ym,
			byDay: r.byDay.map((p) => ({
				day: p.day, bal: p.bal,
				xPct: (mapX(p.day) / 620) * 100, yPct: (mapY(p.bal) / 120) * 100,
			})),
			zeroY: mapY(0).toFixed(1),
			lowX: mapX(r.lowDay).toFixed(1),
			lowY: mapY(r.lowVal).toFixed(1),
			lowLabel: `${labelDate(`${ym}-${String(r.lowDay).padStart(2, '0')}`)} · ${signed(r.lowVal)}`,
			firstLabel: labelDate(today),
			lastLabel: labelDate(data.month_end),
		};
	});

	function onChartMove(ev: PointerEvent) {
		const bd = proj?.byDay;
		if (!bd || !bd.length) return;
		const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
		if (!rect.width) return;
		const frac = (ev.clientX - rect.left) / rect.width;
		let idx = Math.round(frac * (bd.length - 1));
		idx = Math.max(0, Math.min(bd.length - 1, idx));
		if (idx !== hoverIdx) hoverIdx = idx;
	}
	function onChartLeave() {
		if (hoverIdx !== null) hoverIdx = null;
	}

	onMount(() => subscribeRunway());
</script>

{#if loading}
	<div class="h-[172px] bg-gray-100 rounded-2xl animate-pulse mb-4" aria-hidden="true"></div>
{:else if data && proj}
	<!-- RUNWAY DURUM KARTI (bankadaki nakit + durum + eğri + en düşük bakiye) -->
	<div class="rounded-2xl bg-teal-700 px-5 py-4 text-teal-100 mb-4">
		<div class="flex items-start justify-between gap-4">
			<div>
				<div class="text-[10px] uppercase tracking-[0.6px] text-teal-300">Bankadaki Nakit</div>
				<div class="tabular-nums text-[22px] font-semibold text-white mt-0.5">{fmtEur(data.start_eur)}</div>
			</div>
			<div class="text-right max-w-[60%]">
				<div class="text-[10px] uppercase tracking-[0.6px] text-teal-300">Durum</div>
				<div class="text-[13px] font-semibold mt-0.5 {proj.negative ? 'text-red-300' : 'text-emerald-300'}">
					{proj.negative ? '⚠ ' : '✓ '}{proj.statusText}
				</div>
			</div>
		</div>
		<div class="mt-3">
			<div class="relative" style="touch-action:none" role="img" aria-label="Nakit projeksiyon eğrisi — üzerinde gezinerek gün ve bakiye görün"
				onpointermove={onChartMove} onpointerdown={onChartMove} onpointerleave={onChartLeave}>
				<svg viewBox="0 0 620 120" preserveAspectRatio="none" class="w-full h-[88px] block" aria-hidden="true">
					<line x1="0" y1={proj.zeroY} x2="620" y2={proj.zeroY} stroke="#e07a6a" stroke-width="1" stroke-dasharray="4 4" opacity="0.7" />
					<polyline points={proj.pts} fill="none" stroke={proj.negative ? '#e8a06a' : '#8fd0a8'} stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
					<circle cx={proj.lowX} cy={proj.lowY} r="4.5" fill="#e8c979" />
				</svg>
				{#if hoverIdx !== null && proj.byDay[hoverIdx]}
					{@const h = proj.byDay[hoverIdx]}
					{@const tipLeft = Math.max(14, Math.min(86, h.xPct))}
					{@const hIso = `${proj.ym}-${String(h.day).padStart(2, '0')}`}
					<div class="absolute inset-y-0 w-px bg-teal-100/40 pointer-events-none" style="left:{h.xPct}%"></div>
					<div class="absolute w-[9px] h-[9px] rounded-full bg-white border-2 border-teal-700 pointer-events-none"
						style="left:{h.xPct}%;top:{h.yPct}%;transform:translate(-50%,-50%);box-shadow:0 0 0 3px rgba(232,236,243,.18)"></div>
					<div class="absolute pointer-events-none rounded-lg border px-2 py-1 whitespace-nowrap"
						style="left:{tipLeft}%;top:{h.yPct}%;transform:translate(-50%,calc(-100% - 12px));background:#0f1b30;border-color:#2c405f;box-shadow:0 6px 18px -6px rgba(0,0,0,.6)">
						<div class="tabular-nums text-[9.5px] text-teal-300 tracking-[0.4px]">{labelDate(hIso)}</div>
						<div class="tabular-nums text-[13px] font-semibold" style="color:{h.bal >= 0 ? '#8fd0a8' : '#f0a58f'}">{signed(h.bal)}</div>
					</div>
				{/if}
			</div>
			<div class="flex justify-between tabular-nums text-[9.5px] text-teal-300 mt-1">
				<span>{proj.firstLabel}</span><span>{proj.lastLabel}</span>
			</div>
		</div>
		<div class="text-[11.5px] text-teal-200 mt-2">En düşük bakiye: <span class="text-brass-light font-semibold">{proj.lowLabel}</span></div>
	</div>
{/if}
