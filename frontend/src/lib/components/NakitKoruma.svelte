<!--
	NakitKoruma.svelte — Nakit Koruma · Ödeme Erteleme (Runway projeksiyonu).

	Panelde Nakit Akım T Hesap'ın altında yer alır. Bankadaki nakitten başlayıp ay
	içindeki planlı hareketleri (tahsilatlar +, ödemeler −) gün gün projekte eder;
	bakiyenin negatife düştüğü günü gösterir. Kullanıcı bir ödemeyi ileri bir tarihe
	**erteleyerek** (tarih seçici) eğriyi canlı güncelleyip negatifi önleyebilir.

	Erteleme şimdilik YALNIZ projeksiyon (what-if) — borç silmez, kaydı kalıcı
	değiştirmez (ay dışına ertelenen ödeme bu ayın projeksiyonundan çıkar). Kalıcı
	`deferred_to` yazımı ayrı bir iş (backend PATCH + onay akışı).
	Veri: GET /finance/cash-flow/runway. Tasarım: design_handoff_panel_redesign.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { projectRunway } from '$lib/utils/finance';
	import { RotateCcw, ShieldCheck } from 'lucide-svelte';

	type Flow = { id: string; date: string; name: string; amount_eur: number; source_type?: string };
	type RunwayData = {
		month_label: string; month_start: string; month_end: string; today: string;
		start_eur: number; inflows: Flow[]; outs: Flow[]; skipped_no_rate: number;
	};

	const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];

	let data = $state<RunwayData | null>(null);
	let loading = $state(true);
	// Ertelenen ödemelerin yeni tarihi (id → 'YYYY-MM-DD'); boşsa orijinal tarih
	let dates = $state<Record<string, string>>({});

	function fmtEur(n: number): string {
		return '€' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(Math.abs(n)));
	}
	function signed(n: number): string {
		return (n >= 0 ? '+' : '−') + fmtEur(n);
	}
	function labelDate(iso: string): string {
		const [, m, d] = iso.split('-').map(Number);
		return `${d} ${MONTHS_SHORT[m - 1]}`;
	}
	function dayNum(iso: string): number {
		return Number(iso.split('-')[2]);
	}

	// Projeksiyon — dates (erteleme) değişince canlı yeniden hesaplanır
	const proj = $derived.by(() => {
		if (!data) return null;
		const startDay = dayNum(data.today);
		const endDay = dayNum(data.month_end);
		const ym = data.month_start.slice(0, 7); // 'YYYY-MM'

		// Etkin ödeme tarihleri (erteleme uygulanmış); ay içinde mi?
		const effOut = data.outs.map((o) => {
			const iso = dates[o.id] || o.date;
			const inMonth = iso.slice(0, 7) === ym;
			return { ...o, effIso: iso, effDay: inMonth ? dayNum(iso) : null, changed: iso !== o.date };
		});

		// Gün gün bakiye projeksiyonu (saf, testli helper — ay dışına ertelenen çıkar)
		const { byDay, firstNeg, lowVal, lowDay, endBal } =
			projectRunway(data.start_eur, data.inflows, data.outs, data.today, data.month_end, dates);

		// SVG ölçek
		const vals = byDay.map((p) => p.bal);
		const hi = Math.max(data.start_eur, ...vals);
		const lo = Math.min(0, ...vals);
		const pad = (hi - lo) * 0.14 || 1;
		const top = 12, bottom = 108;
		const span = endDay - startDay || 1;
		const mapX = (d: number) => ((d - startDay) / span) * 620;
		const mapY = (v: number) => bottom - ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (bottom - top);
		const pts = byDay.map((p) => `${mapX(p.day).toFixed(1)},${mapY(p.bal).toFixed(1)}`).join(' ');

		const negative = firstNeg !== null;
		const defCount = effOut.filter((o) => o.changed).length;

		// Eğri TÜM ödemeleri kullanır; ama ertelenebilir LİSTE yalnız en büyük N ödemeyi
		// gösterir (gerçek veride yüzlerce küçük cari ödemesi olabilir — küçüğü ertelemek
		// runway'i kayda değer oynatmaz + liste kullanılamaz hale gelir). Ertelenmiş olanlar
		// tutar küçük olsa da listede kalır (kullanıcı geri alabilsin).
		const TOP_N = 12;
		const ranked = [...effOut].sort((a, b) => b.amount_eur - a.amount_eur);
		const shownIds = new Set(ranked.slice(0, TOP_N).map((o) => o.id));
		for (const o of effOut) if (o.changed) shownIds.add(o.id);
		const shownOuts = effOut
			.filter((o) => shownIds.has(o.id))
			.sort((a, b) => dayNum(a.date) - dayNum(b.date));
		const otherOuts = effOut.filter((o) => !shownIds.has(o.id));
		const otherSum = otherOuts.reduce((s, o) => s + o.amount_eur, 0);

		return {
			negative,
			statusText: negative
				? `${firstNeg} ${MONTHS_SHORT[Number(ym.slice(5, 7)) - 1]}'de bakiye negatife düşüyor`
				: 'Ay boyunca nakit pozitif kalıyor',
			pts,
			zeroY: mapY(0).toFixed(1),
			lowX: mapX(lowDay).toFixed(1),
			lowY: mapY(lowVal).toFixed(1),
			lowLabel: `${labelDate(`${ym}-${String(lowDay).padStart(2, '0')}`)} · ${signed(lowVal)}`,
			endBal,
			defCount,
			shownOuts,
			otherCount: otherOuts.length,
			otherSum,
			totalOut: effOut.length,
			firstLabel: labelDate(data.today),
			lastLabel: labelDate(data.month_end),
		};
	});

	function setDate(id: string, v: string) {
		if (v) dates[id] = v;
	}
	function resetDate(id: string) {
		delete dates[id];
		dates = { ...dates };
	}

	onMount(async () => {
		try {
			data = await api.get<RunwayData>('/finance/cash-flow/runway');
		} catch (err) {
			console.error('Nakit koruma verisi yüklenemedi:', err);
			showToast('Nakit koruma verisi yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	});
</script>

<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
	<!-- Başlık -->
	<div class="flex items-start justify-between gap-3 mb-4">
		<div>
			<h3 class="text-[17px] text-gray-900 flex items-center gap-2"><ShieldCheck size={18} class="text-teal-700" /> Nakit Koruma · Ödeme Erteleme</h3>
			<p class="text-xs text-gray-500 mt-0.5">Bakiyeyi negatife düşürmeden ödemeleri planla{data ? ` · ${data.month_label}` : ''}</p>
		</div>
		{#if data}
			<span class="shrink-0 text-xs font-semibold bg-teal-700 text-brass-soft rounded-lg px-3 py-1.5">Bu Ay</span>
		{/if}
	</div>

	{#if loading}
		<div class="h-40 bg-gray-100 rounded-xl animate-pulse" aria-hidden="true"></div>
	{:else if data && proj}
		<!-- RUNWAY DURUM KARTI -->
		<div class="rounded-2xl bg-teal-700 px-5 py-4 text-teal-100">
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
			<!-- Projeksiyon eğrisi -->
			<div class="mt-3">
				<svg viewBox="0 0 620 120" preserveAspectRatio="none" class="w-full h-[88px] block" role="img" aria-label="Nakit projeksiyon eğrisi">
					<line x1="0" y1={proj.zeroY} x2="620" y2={proj.zeroY} stroke="#e07a6a" stroke-width="1" stroke-dasharray="4 4" opacity="0.7" />
					<polyline points={proj.pts} fill="none" stroke={proj.negative ? '#e8a06a' : '#8fd0a8'} stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
					<circle cx={proj.lowX} cy={proj.lowY} r="4.5" fill="#e8c979" />
				</svg>
				<div class="flex justify-between tabular-nums text-[9.5px] text-teal-300 mt-1">
					<span>{proj.firstLabel}</span><span>{proj.lastLabel}</span>
				</div>
			</div>
			<div class="text-[11.5px] text-teal-200 mt-2">En düşük bakiye: <span class="text-brass-light font-semibold">{proj.lowLabel}</span></div>
		</div>

		<!-- BEKLENEN TAHSİLATLAR -->
		{#if data.inflows.length > 0}
			<div class="mt-4 text-[11px] tracking-[1px] uppercase text-green-700 font-bold">Beklenen Tahsilatlar</div>
			<div class="flex gap-2 flex-wrap mt-2">
				{#each data.inflows as i (i.id)}
					<span class="inline-flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg px-2.5 py-1.5 text-xs">
						<span class="tabular-nums text-gray-500">{labelDate(i.date)}</span>
						<span class="text-gray-700 truncate max-w-[160px]">{i.name}</span>
						<span class="tabular-nums font-semibold text-green-700">+{fmtEur(i.amount_eur)}</span>
					</span>
				{/each}
			</div>
		{/if}

		<!-- BU AY PLANLI ÖDEMELER (en büyükler — ertelenebilir) -->
		<div class="flex items-center justify-between mt-5 mb-1.5">
			<div class="text-[11px] tracking-[1px] uppercase text-brass-dark font-bold">
				Bu Ay Planlı Ödemeler{proj.totalOut > proj.shownOuts.length ? ` · en büyük ${proj.shownOuts.length}` : ''}
			</div>
			<div class="text-[11.5px] text-gray-500">{proj.defCount > 0 ? `${proj.defCount} ödeme ertelendi` : 'ödemeleri erteleyerek koruyun'}</div>
		</div>
		{#if proj.shownOuts.length === 0}
			<p class="text-xs text-gray-500 py-3">Bu ay planlı ödeme yok.</p>
		{/if}
		{#each proj.shownOuts as o (o.id)}
			{@const out = o.effDay === null}
			<div class="flex items-center gap-2 sm:gap-3 py-2.5 border-b border-gray-100">
				<span class="tabular-nums text-[11.5px] text-gray-500 w-11 shrink-0">{labelDate(o.date)}</span>
				<div class="flex-1 min-w-0">
					<div class="text-[13.5px] font-medium truncate {out ? 'text-gray-400 line-through' : 'text-gray-900'}">{o.name}</div>
					{#if o.changed}
						<div class="text-[10.5px] text-brass-dark">→ {labelDate(o.effIso)}{out ? ' tarihine ertelendi (gelecek aya)' : ' tarihine ertelendi'}</div>
					{/if}
				</div>
				<span class="tabular-nums text-[13.5px] font-semibold w-[78px] text-right shrink-0 {out ? 'text-gray-400 line-through' : 'text-brass-dark'}">−{fmtEur(o.amount_eur)}</span>
				<input
					type="date"
					value={o.effIso}
					min={o.date}
					max={`${data.month_start.slice(0, 4)}-12-31`}
					onchange={(e) => setDate(o.id, (e.currentTarget as HTMLInputElement).value)}
					aria-label={`${o.name} ödeme tarihini ertele`}
					class="date-filter-input shrink-0 w-[128px] rounded-lg border px-2 py-1.5 text-[11.5px] cursor-pointer focus:ring-2 focus:ring-teal-500 focus:outline-none {o.changed ? 'border-brass/50 bg-brass-soft text-brass-dark' : 'border-gray-200 bg-white text-gray-700'}"
				/>
				<button type="button" onclick={() => resetDate(o.id)} disabled={!o.changed}
					title="Erteleme tarihini sıfırla" aria-label="Erteleme tarihini sıfırla"
					class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg border border-gray-200 bg-white text-brass-dark cursor-pointer disabled:opacity-30 disabled:cursor-default hover:bg-gray-50">
					<RotateCcw size={13} />
				</button>
			</div>
		{/each}
		{#if proj.otherCount > 0}
			<p class="text-[11.5px] text-gray-500 pt-2">
				+{proj.otherCount} daha küçük ödeme (toplam {fmtEur(proj.otherSum)}) — projeksiyona dahil, erteleme için Nakit Akım sayfasını kullanın.
			</p>
		{/if}

		<!-- AY SONU PROJEKSİYON BAKİYESİ -->
		<div class="flex items-center justify-between mt-4 rounded-xl bg-teal-700 px-5 py-3.5">
			<span class="text-xs sm:text-[12.5px] text-teal-100">Ay Sonu Projeksiyon Bakiyesi</span>
			<span class="tabular-nums text-lg font-semibold {proj.endBal >= 0 ? 'text-emerald-300' : 'text-red-300'}">{signed(proj.endBal)}</span>
		</div>
		<p class="text-[11.5px] text-gray-500 mt-2.5 leading-relaxed">
			Ertelenen ödemeler bu ayın nakit projeksiyonundan çıkarılır — borç ortadan kalkmaz, yalnızca zamanlaması değişir.
			Bu bir <strong>planlama önizlemesidir</strong>; ödeme tarihini kalıcı değiştirmez. Tahsilat tarafında yalnızca
			<strong>kayıtlı beklenen girişler</strong> yer alır (günlük gerçekleşen oda geliri bu projeksiyona dahil değildir),
			bu yüzden gerçek nakit durumu daha olumlu olabilir.
		</p>
		{#if data.skipped_no_rate > 0}
			<p class="text-[11px] text-amber-700 mt-1">{data.skipped_no_rate} kalem kur bilgisi olmadığından hesaba katılamadı.</p>
		{/if}
	{/if}
</div>
