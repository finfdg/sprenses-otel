<script lang="ts">
	// Asistan yanıtlarında gösterilen hafif SVG grafik (harici kütüphane yok).
	// Veri yapısaldır (etiket:string + değer:number); Svelte ile escape'li render → XSS yok.
	interface Point {
		etiket: string;
		deger: number;
	}
	let {
		tip = 'bar',
		baslik = '',
		para_birimi = '',
		seri = []
	}: { tip?: string; baslik?: string; para_birimi?: string; seri?: Point[] } = $props();

	// Bar etiketleri kısa kalsın diye kompakt biçim (ör. 7,6 Mn); tam değer title'da.
	const nfCompact = new Intl.NumberFormat('tr-TR', { notation: 'compact', maximumFractionDigits: 1 });
	const nfFull = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 });
	function fmt(n: number): string {
		return nfCompact.format(n) + (para_birimi ? ' ' + para_birimi : '');
	}
	function fmtFull(n: number): string {
		return nfFull.format(n) + (para_birimi ? ' ' + para_birimi : '');
	}

	// ── Bar (yatay çubuk) ──
	let maxAbs = $derived(Math.max(1, ...seri.map((p) => Math.abs(p.deger))));
	function barWidth(v: number): number {
		return Math.max(2, (Math.abs(v) / maxAbs) * 100); // yüzde
	}

	// ── Line (trend) geometri ──
	const W = 640,
		H = 200,
		padL = 6,
		padR = 12,
		padT = 12,
		padB = 26;
	let vals = $derived(seri.map((p) => p.deger));
	let vmin = $derived(Math.min(0, ...vals));
	let vmax = $derived(Math.max(1, ...vals));
	function px(i: number): number {
		return seri.length <= 1 ? padL : padL + (i * (W - padL - padR)) / (seri.length - 1);
	}
	function py(v: number): number {
		return padT + ((vmax - v) * (H - padT - padB)) / (vmax - vmin || 1);
	}
	let linePts = $derived(seri.map((p, i) => `${px(i)},${py(p.deger)}`).join(' '));
	let areaPts = $derived(
		seri.length
			? `${px(0)},${py(0)} ` + seri.map((p, i) => `${px(i)},${py(p.deger)}`).join(' ') + ` ${px(seri.length - 1)},${py(0)}`
			: ''
	);
	let zeroY = $derived(py(0));
	// Çok nokta varsa etiketleri seyrelt
	let labelEvery = $derived(Math.max(1, Math.ceil(seri.length / 8)));
</script>

<figure class="my-2 rounded-xl border border-gray-200 bg-white p-3">
	{#if baslik}
		<figcaption class="text-xs font-semibold text-gray-600 mb-2">{baslik}</figcaption>
	{/if}

	{#if tip === 'line'}
		<svg viewBox="0 0 {W} {H}" class="w-full h-auto" role="img" aria-label={baslik || 'grafik'}>
			<!-- sıfır çizgisi -->
			<line x1={padL} y1={zeroY} x2={W - padR} y2={zeroY} stroke="#e5e7eb" stroke-width="1" />
			{#if areaPts}
				<polygon points={areaPts} fill="#0d9488" fill-opacity="0.08" />
			{/if}
			<polyline points={linePts} fill="none" stroke="#0f766e" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
			{#each seri as p, i}
				<circle cx={px(i)} cy={py(p.deger)} r="2.5" fill="#0f766e" />
				{#if i % labelEvery === 0}
					<text x={px(i)} y={H - 8} text-anchor="middle" font-size="10" fill="#6b7280">{p.etiket}</text>
				{/if}
			{/each}
		</svg>
	{:else}
		<!-- bar: yatay çubuklar -->
		<div class="space-y-1.5">
			{#each seri as p}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-28 shrink-0 truncate text-gray-600" title={p.etiket}>{p.etiket}</span>
					<span class="flex-1 h-4 bg-gray-100 rounded overflow-hidden">
						<span
							class="block h-full rounded {p.deger < 0 ? 'bg-red-500' : 'bg-teal-600'}"
							style="width: {barWidth(p.deger)}%"
						></span>
					</span>
					<span class="w-20 shrink-0 text-right tabular-nums text-gray-700 whitespace-nowrap" title={fmtFull(p.deger)}>{fmt(p.deger)}</span>
				</div>
			{/each}
		</div>
	{/if}
</figure>
