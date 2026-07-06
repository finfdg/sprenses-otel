<!--
	RunwayChart.svelte — Seçili dönemin KÜMÜLATİF nakit akışı eğrisi (EUR).

	Panel Nakit Akım kartının ÜSTÜNDE (başlık altında). Veri T-Hesap yanıtından (`data.curve`)
	gelir → dönem sekmesi (günlük/haftalık/aylık/yıllık) ve ileri/geri ay gezinmesiyle BİRLİKTE
	değişir. Eğri dönem başında 0'dan başlar, gün gün net (gelir−gider) birikir, dönem sonunda
	net'e ulaşır (net bandıyla tutarlı). En düşük nokta = dönem içi en kötü nakit pozisyonu.
	(2026-07-06: eski runway endpoint sabit "bu ay" idi → dönem-duyarlı T-Hesap eğrisine geçildi.)
-->
<script lang="ts">
	type CurvePoint = { date: string; cum: number };
	type ChartData = {
		start_date: string; end_date: string;
		net_eur: number; curve?: CurvePoint[];
	};
	let { data }: { data: ChartData | null } = $props();

	const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	function fmtEur(n: number): string {
		return '€' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(Math.abs(n)));
	}
	function signed(n: number): string {
		return (n >= 0 ? '+' : '−') + fmtEur(n);
	}
	function labelIso(iso: string): string {
		const [, m, d] = iso.split('-').map(Number);
		return `${d} ${MONTHS_SHORT[m - 1]}`;
	}

	let hoverIdx = $state<number | null>(null);

	const proj = $derived.by(() => {
		if (!data || !data.curve || data.curve.length === 0) return null;
		const startT = new Date(data.start_date + 'T00:00:00').getTime();
		const endT = new Date(data.end_date + 'T00:00:00').getTime();
		const spanMs = Math.max(1, endT - startT);
		// Dönem başında 0 çapası + hareketli günlerin kümülatifi
		const pts0 = [
			{ t: startT, cum: 0, date: data.start_date },
			...data.curve.map((p) => ({ t: new Date(p.date + 'T00:00:00').getTime(), cum: p.cum, date: p.date })),
		];
		const vals = pts0.map((p) => p.cum);
		const hi = Math.max(0, ...vals);
		const lo = Math.min(0, ...vals);
		const pad = (hi - lo) * 0.14 || 1;
		const top = 12, bottom = 108;
		const mapX = (t: number) => ((t - startT) / spanMs) * 620;
		const mapY = (v: number) => bottom - ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (bottom - top);
		const pts = pts0.map((p) => `${mapX(p.t).toFixed(1)},${mapY(p.cum).toFixed(1)}`).join(' ');

		let low = pts0[0];
		for (const p of pts0) if (p.cum < low.cum) low = p;

		return {
			pts,
			net: data.net_eur,
			negative: data.net_eur < 0,
			zeroY: mapY(0).toFixed(1),
			lowX: mapX(low.t).toFixed(1),
			lowY: mapY(low.cum).toFixed(1),
			lowLabel: `${labelIso(low.date)} · ${signed(low.cum)}`,
			byDay: pts0.map((p) => ({
				date: p.date, cum: p.cum,
				xPct: (mapX(p.t) / 620) * 100, yPct: (mapY(p.cum) / 120) * 100,
			})),
			firstLabel: labelIso(data.start_date),
			lastLabel: labelIso(data.end_date),
		};
	});

	function onChartMove(ev: PointerEvent) {
		const bd = proj?.byDay;
		if (!bd || !bd.length) return;
		const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
		if (!rect.width) return;
		const fracPct = ((ev.clientX - rect.left) / rect.width) * 100;
		let best = 0, bestD = Infinity;
		for (let i = 0; i < bd.length; i++) {
			const d = Math.abs(bd[i].xPct - fracPct);
			if (d < bestD) { bestD = d; best = i; }
		}
		if (best !== hoverIdx) hoverIdx = best;
	}
	function onChartLeave() {
		if (hoverIdx !== null) hoverIdx = null;
	}
</script>

{#if !data}
	<div class="h-[150px] bg-gray-100 rounded-2xl animate-pulse mb-4" aria-hidden="true"></div>
{:else if proj}
	<!-- Kümülatif nakit akışı eğrisi (seçili dönem) -->
	<div class="rounded-2xl bg-teal-700 px-5 py-4 text-teal-100 mb-4">
		<div class="flex items-start justify-between gap-4">
			<div>
				<div class="text-[10px] uppercase tracking-[0.6px] text-teal-300">Dönem Nakit Akışı (kümülatif)</div>
				<div class="tabular-nums text-[22px] font-semibold mt-0.5 {proj.negative ? 'text-red-300' : 'text-emerald-300'}">{signed(proj.net)}</div>
			</div>
			<div class="text-right">
				<div class="text-[10px] uppercase tracking-[0.6px] text-teal-300">En Düşük</div>
				<div class="tabular-nums text-[12.5px] font-semibold text-brass-light mt-0.5">{proj.lowLabel}</div>
			</div>
		</div>
		<div class="mt-3">
			<div class="relative" style="touch-action:none" role="img" aria-label="Dönem kümülatif nakit akışı eğrisi — üzerinde gezinerek gün ve tutar görün"
				onpointermove={onChartMove} onpointerdown={onChartMove} onpointerleave={onChartLeave}>
				<svg viewBox="0 0 620 120" preserveAspectRatio="none" class="w-full h-[88px] block" aria-hidden="true">
					<line x1="0" y1={proj.zeroY} x2="620" y2={proj.zeroY} stroke="#e07a6a" stroke-width="1" stroke-dasharray="4 4" opacity="0.7" />
					<polyline points={proj.pts} fill="none" stroke={proj.negative ? '#e8a06a' : '#8fd0a8'} stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
					<circle cx={proj.lowX} cy={proj.lowY} r="4.5" fill="#e8c979" />
				</svg>
				{#if hoverIdx !== null && proj.byDay[hoverIdx]}
					{@const h = proj.byDay[hoverIdx]}
					{@const tipLeft = Math.max(14, Math.min(86, h.xPct))}
					<div class="absolute inset-y-0 w-px bg-teal-100/40 pointer-events-none" style="left:{h.xPct}%"></div>
					<div class="absolute w-[9px] h-[9px] rounded-full bg-white border-2 border-teal-700 pointer-events-none"
						style="left:{h.xPct}%;top:{h.yPct}%;transform:translate(-50%,-50%);box-shadow:0 0 0 3px rgba(232,236,243,.18)"></div>
					<div class="absolute pointer-events-none rounded-lg border px-2 py-1 whitespace-nowrap"
						style="left:{tipLeft}%;top:{h.yPct}%;transform:translate(-50%,calc(-100% - 12px));background:#0f1b30;border-color:#2c405f;box-shadow:0 6px 18px -6px rgba(0,0,0,.6)">
						<div class="tabular-nums text-[9.5px] text-teal-300 tracking-[0.4px]">{labelIso(h.date)}</div>
						<div class="tabular-nums text-[13px] font-semibold" style="color:{h.cum >= 0 ? '#8fd0a8' : '#f0a58f'}">{signed(h.cum)}</div>
					</div>
				{/if}
			</div>
			<div class="flex justify-between tabular-nums text-[9.5px] text-teal-300 mt-1">
				<span>{proj.firstLabel}</span><span>{proj.lastLabel}</span>
			</div>
		</div>
	</div>
{/if}
