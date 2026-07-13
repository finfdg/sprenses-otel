<!--
	RunwayChart.svelte — Bankadaki nakit "runway" bakiye eğrisi (EUR), DÖNEM-DUYARLI.

	Panel Nakit Akım kartının ÜSTÜNDE. Veri `eur_balances.daily`'den gelir (Nakit Akım sayfasıyla
	AYNI kaynak → iki görünüm tutarlı; GERÇEK günlük banka bakiyesi: geçmiş=fiili, gelecek=projeksiyon).
	Seçili dönemin (`startDate..endDate`) günlük bakiyeleri dilimlenip çizilir → dönem sekmesi ve
	ileri/geri gezinmeyle değişir. Bakiye 0 çizgisinin altına düşerse "negatife düşüyor" uyarısı.
	Çizgi rengi 0 çizgisinde bölünür (üstü yeşil / altı turuncu — negatife düşene kadar yeşil,
	2026-07-13) ve dönem başında hareket yoksa önceki dönemin kapanış bakiyesi 1'inci güne
	"Devir" noktası olarak eklenir → çizgi her zaman dönem başından başlar (aynı gün).
	(2026-07-06: önce T-Hesap akışından geriye-hesaplanıyordu → geçmiş bakiyeler yanlış çıkıyordu
	[1 Tem gerçek €6.822 iken −€14.916 gösteriyordu]; eur_balances gerçek bakiyeye geçildi.)
-->
<script lang="ts">
	type DayBal = { balance_eur: number };
	type Balances = { daily?: Record<string, DayBal>; total_balance_eur?: number } | null;
	let { balances, startDate, endDate }: { balances: Balances; startDate?: string; endDate?: string } = $props();

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
		const daily = balances?.daily;
		if (!daily || !startDate || !endDate) return null;
		const mkPt = (d: string, bal: number, carry = false) => ({
			t: new Date(d + 'T00:00:00').getTime(), bal, date: d, carry,
		});
		const allDates = Object.keys(daily).sort();
		// Seçili dönem içindeki hareketli günlerin GERÇEK banka bakiyeleri (tarih sıralı)
		const pts0 = allDates
			.filter((d) => d >= startDate && d <= endDate)
			.map((d) => mkPt(d, daily[d].balance_eur));
		// DEVREDEN BAKİYE (2026-07-13, kullanıcı isteği): dönem başında hareket yoksa çizgi ay
		// ortasından başlıyordu (ilk hareketli gün). Dönemden ÖNCEKİ son bilinen bakiye 1'inci
		// güne "Devir" noktası olarak eklenir → çizgi her zaman dönem başından başlar. Son
		// hareket dönem sonundan önce bitiyorsa bakiye dönem sonuna düz uzatılır (hareketsiz
		// günlerde bakiye değişmez). Dönemde hiç hareket yoksa düz devir çizgisi çizilir.
		const prevDate = allDates.filter((d) => d < startDate).pop();
		const carryBal = prevDate !== undefined ? daily[prevDate].balance_eur : null;

		const startT = new Date(startDate + 'T00:00:00').getTime();
		// Günlük görünümde (start==end) eksen 0 uzunlukta kalır → 1 günlük eksen kullanılır;
		// böylece düz devir/uzatma çizgisi görünmez nokta değil tam-genişlik çizgi olur.
		const endT0 = new Date(endDate + 'T00:00:00').getTime();
		const endT = endT0 > startT ? endT0 : startT + 86400000;

		if (pts0.length === 0) {
			if (carryBal === null) return null;
			pts0.push(mkPt(startDate, carryBal, true), { ...mkPt(endDate, carryBal), t: endT });
		} else {
			if (pts0[0].date > startDate && carryBal !== null) pts0.unshift(mkPt(startDate, carryBal, true));
			const lastPt = pts0[pts0.length - 1];
			if (lastPt.t < endT) pts0.push({ ...mkPt(endDate, lastPt.bal), t: endT });
		}

		const spanMs = Math.max(1, endT - startT);
		const vals = pts0.map((p) => p.bal);
		const hi = Math.max(0, ...vals);
		const lo = Math.min(0, ...vals);
		const pad = (hi - lo) * 0.14 || 1;
		const top = 12, bottom = 108;
		const mapX = (t: number) => ((t - startT) / spanMs) * 620;
		const mapY = (v: number) => bottom - ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (bottom - top);
		const pts = pts0.map((p) => `${mapX(p.t).toFixed(1)},${mapY(p.bal).toFixed(1)}`).join(' ');

		let low = pts0[0];
		for (const p of pts0) if (p.bal < low.bal) low = p;
		// "Negatife düşüyor" uyarısı bakiyenin İLK KEZ 0'ın altına düştüğü günü gösterir (en düşük
		// gün DEĞİL) — kullanıcı bulgusu 2026-07-07: minimum 31 Tem'deydi ama açık daha erken başlıyor.
		// `low` (en düşük bakiye) ayrı kalır: grafik noktası + "En düşük bakiye" etiketi.
		const firstNeg = pts0.find((p) => p.bal < 0) ?? null;
		const negative = firstNeg !== null;
		const endBal = pts0[pts0.length - 1].bal;
		const startEur = balances?.total_balance_eur ?? pts0[pts0.length - 1].bal;

		return {
			pts, negative, startEur,
			statusText: firstNeg
				? (firstNeg.carry
					? 'Dönem negatif devir bakiyesiyle başlıyor'
					: `Bakiye ${labelIso(firstNeg.date)} tarihinde negatife düşüyor`)
				: 'Dönem boyunca nakit pozitif kalıyor',
			zeroY: mapY(0).toFixed(1),
			// Çizgi rengini 0 çizgisinde böl: üstü (pozitif) yeşil, altı (negatif) turuncu.
			// Gradyan stop'u 0'ın viewBox içindeki dikey oranına (0..1) konur → tek polyline
			// hem yeşil hem turuncu görünür (negatife düşene kadar yeşil devam eder).
			zeroOffset: Math.min(1, Math.max(0, mapY(0) / 120)).toFixed(4),
			// Kenar kırpılmasına karşı clamp — 1'inci gün (devir) / son gün minimumsa daire (r=4.5)
			// viewBox kenarında yarım çizilmesin
			lowX: Math.min(615.5, Math.max(4.5, mapX(low.t))).toFixed(1),
			lowY: mapY(low.bal).toFixed(1),
			lowLabel: `${labelIso(low.date)} · ${signed(low.bal)}`,
			endBal,
			byDay: pts0.map((p) => ({
				date: p.date, bal: p.bal, carry: p.carry,
				xPct: (mapX(p.t) / 620) * 100, yPct: (mapY(p.bal) / 120) * 100,
			})),
			firstLabel: labelIso(startDate),
			lastLabel: labelIso(endDate),
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

{#if !balances}
	<div class="h-[168px] bg-gray-100 rounded-2xl animate-pulse mb-4" aria-hidden="true"></div>
{:else if proj}
	<!-- Bankadaki nakit runway — gerçek günlük banka bakiyesi (seçili dönem) -->
	<div class="rounded-2xl bg-teal-700 px-5 py-4 text-teal-100 mb-4">
		<div class="flex items-start justify-between gap-4">
			<div>
				<div class="text-[10px] uppercase tracking-[0.6px] text-teal-300">Bankadaki Nakit</div>
				<div class="tabular-nums text-[22px] font-semibold text-white mt-0.5">{fmtEur(proj.startEur)}</div>
			</div>
			<div class="text-right max-w-[60%]">
				<div class="text-[10px] uppercase tracking-[0.6px] text-teal-300">Durum</div>
				<div class="text-[13px] font-semibold mt-0.5 {proj.negative ? 'text-red-300' : 'text-emerald-300'}">
					{proj.negative ? '⚠ ' : '✓ '}{proj.statusText}
				</div>
			</div>
		</div>
		<div class="mt-3">
			<div class="relative" style="touch-action:none" role="img" aria-label="Dönem banka bakiyesi runway eğrisi — üzerinde gezinerek gün ve bakiye görün"
				onpointermove={onChartMove} onpointerdown={onChartMove} onpointerleave={onChartLeave}>
				<svg viewBox="0 0 620 120" preserveAspectRatio="none" class="w-full h-[88px] block" aria-hidden="true">
					<defs>
						<linearGradient id="runwayStroke" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="120">
							<stop offset={proj.zeroOffset} stop-color="#8fd0a8" />
							<stop offset={proj.zeroOffset} stop-color="#e8a06a" />
						</linearGradient>
					</defs>
					<line x1="0" y1={proj.zeroY} x2="620" y2={proj.zeroY} stroke="#e07a6a" stroke-width="1" stroke-dasharray="4 4" opacity="0.7" />
					<polyline points={proj.pts} fill="none" stroke="url(#runwayStroke)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
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
						<div class="tabular-nums text-[9.5px] text-teal-300 tracking-[0.4px]">{labelIso(h.date)}{h.carry ? ' · Devir' : ''}</div>
						<div class="tabular-nums text-[13px] font-semibold" style="color:{h.bal >= 0 ? '#8fd0a8' : '#f0a58f'}">{signed(h.bal)}</div>
					</div>
				{/if}
			</div>
			<div class="flex justify-between tabular-nums text-[9.5px] text-teal-300 mt-1">
				<span>{proj.firstLabel}</span><span>{proj.lastLabel}</span>
			</div>
		</div>
		<div class="text-[11.5px] text-teal-200 mt-2">En düşük bakiye: <span class="{proj.negative ? 'text-red-300' : 'text-brass-light'} font-semibold">{proj.lowLabel}</span> · Dönem sonu: <span class="text-white font-semibold">{signed(proj.endBal)}</span></div>
	</div>
{/if}
