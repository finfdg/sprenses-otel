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
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { projectRunway } from '$lib/utils/finance';
	import { RotateCcw, ShieldCheck, ChevronDown } from 'lucide-svelte';

	// embedded=true → dış kart kabuğu yok (Nakit Akım kartının içinde ayraçla gösterilir)
	let { embedded = false }: { embedded?: boolean } = $props();
	// Erteleme (tarih değiştirme) yalnız finance.cash_flow KULLANIM yetkisi olanlara açık;
	// yetkisizler runway'i salt-görünüm olarak görür (tarih seçici/sıfırla gizli).
	const canDefer = hasPermission('finance.cash_flow', 'use');

	type Flow = { id: string; date: string; name: string; amount_eur: number; source_type?: string };
	type RunwayData = {
		month_label: string; month_start: string; month_end: string; today: string;
		start_eur: number; inflows: Flow[]; outs: Flow[]; skipped_no_rate: number;
	};

	const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	// Kaynak türü → Türkçe grup başlığı (Nakit Akım gruplama etiketleriyle uyumlu)
	const SRC_LABELS: Record<string, string> = {
		vendor_payment: 'Cari Ödemeleri', credit: 'Kredi / Leasing Taksitleri',
		cc_payment: 'KK Borç Ödemeleri', check: 'Verilen Çekler', salary: 'Maaş Ödemeleri',
		sgk: 'SGK', tax: 'Vergiler', recurring: 'Düzenli Ödemeler', withholding: 'Stopajlar',
		dividend: 'Temettü', rent_expense: 'Verilen Kiralar', advance: 'Avanslar',
	};

	let data = $state<RunwayData | null>(null);
	let loading = $state(true);
	// Ertelenen ödemelerin yeni tarihi (id → 'YYYY-MM-DD'); boşsa orijinal tarih
	let dates = $state<Record<string, string>>({});
	// Açık akordiyon grupları (key → bool)
	let openGroups = $state<Record<string, boolean>>({});

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
	// Üye detay adını sadeleştir: baştaki "[Maaş] "/"[Taksitli Kredi] " ön ekini at
	function cleanName(name: string): string {
		return name.replace(/^\[[^\]]*\]\s*/, '');
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

		// Her ödemeyi GÜN + KAYNAK türü bazında sade başlık altında grupla (tek üye olsa
		// da — çek/kredi/maaş/SGK hepsi düzenli başlık altında). Grup toptan ertelenir
		// (tek tarih seçici tüm üyeleri taşır); verbose ad detayda (aç/kapa) gösterilir.
		type EffOut = (typeof effOut)[number];
		const groupsMap = new Map<string, EffOut[]>();
		for (const o of effOut) {
			const key = `${o.date}|${o.source_type ?? 'other'}`;
			const arr = groupsMap.get(key);
			if (arr) arr.push(o); else groupsMap.set(key, [o]);
		}
		type Unit = { key: string; label: string; day: string; members: EffOut[]; memberIds: string[]; total: number; effIso: string; effDay: number | null; changed: boolean };
		const units: Unit[] = [];
		for (const [key, members] of groupsMap) {
			const first = members[0];
			units.push({
				key, label: SRC_LABELS[first.source_type ?? ''] ?? cleanName(first.name),
				day: first.date, members, memberIds: members.map((m) => m.id),
				total: members.reduce((s, m) => s + m.amount_eur, 0),
				effIso: first.effIso, effDay: first.effDay,
				changed: members.some((m) => m.changed),
			});
		}

		// Eğri TÜM ödemeleri kullanır; liste en büyük N ünite gösterir. Ertelenmiş olanlar
		// tutarı küçük olsa da kalır (kullanıcı geri alabilsin).
		const TOP_N = 20;
		units.sort((a, b) => b.total - a.total);
		const shown = new Set<Unit>(units.slice(0, TOP_N));
		for (const u of units) if (u.changed) shown.add(u);
		const shownUnits = [...shown].sort((a, b) => dayNum(a.day) - dayNum(b.day));
		const otherUnits = units.filter((u) => !shown.has(u));
		const otherCount = otherUnits.reduce((s, u) => s + u.members.length, 0);
		const otherSum = otherUnits.reduce((s, u) => s + u.total, 0);

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
			shownUnits,
			otherCount,
			otherSum,
			totalOut: effOut.length,
			firstLabel: labelDate(data.today),
			lastLabel: labelDate(data.month_end),
		};
	});

	// Grup: tek tarih seçici tüm üyeleri toptan erteler / sıfırlar
	// Beklenen tahsilatlar: aynı gün + aynı tür → tek çip (tekse asıl ad, çoksa "N tahsilat").
	// Ertelenemez (referans) olduğundan çip biçimi korunur, akordiyon yok.
	const groupedInflows = $derived.by(() => {
		if (!data) return [];
		const map = new Map<string, Flow[]>();
		for (const i of data.inflows) {
			const key = `${i.date}|${i.source_type ?? 'other'}`;
			const arr = map.get(key);
			if (arr) arr.push(i); else map.set(key, [i]);
		}
		const out = [];
		for (const [key, members] of map) {
			out.push({
				key, date: members[0].date,
				label: members.length === 1 ? cleanName(members[0].name) : `${members.length} tahsilat`,
				title: members.map((m) => cleanName(m.name)).join(', '),
				total: members.reduce((s, m) => s + m.amount_eur, 0),
			});
		}
		return out.sort((a, b) => dayNum(a.date) - dayNum(b.date));
	});

	function setGroupDate(ids: string[], v: string) {
		if (!v) return;
		for (const id of ids) dates[id] = v;
	}
	function resetGroup(ids: string[]) {
		for (const id of ids) delete dates[id];
		dates = { ...dates };
	}
	function toggleGroup(key: string) {
		openGroups[key] = !openGroups[key];
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

<div class={embedded ? 'mt-5 pt-5 border-t border-gray-200' : 'bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6'}>
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

		<!-- BEKLENEN TAHSİLATLAR — aynı gün+tür gruplu çipler -->
		{#if groupedInflows.length > 0}
			<div class="mt-4 text-[11px] tracking-[1px] uppercase text-green-700 font-bold">Beklenen Tahsilatlar</div>
			<div class="flex gap-2 flex-wrap mt-2">
				{#each groupedInflows as g (g.key)}
					<span class="inline-flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg px-2.5 py-1.5 text-xs" title={g.title}>
						<span class="tabular-nums text-gray-500">{labelDate(g.date)}</span>
						<span class="text-gray-700 truncate max-w-[160px]">{g.label}</span>
						<span class="tabular-nums font-semibold text-green-700">+{fmtEur(g.total)}</span>
					</span>
				{/each}
			</div>
		{/if}

		<!-- BU AY PLANLI ÖDEMELER — gün+tür bazında gruplu, ertelenebilir -->
		<div class="flex items-center justify-between mt-5 mb-1.5">
			<div class="text-[11px] tracking-[1px] uppercase text-brass-dark font-bold">Bu Ay Planlı Ödemeler</div>
			<div class="text-[11.5px] text-gray-500">
				{#if canDefer}{proj.defCount > 0 ? `${proj.defCount} ödeme ertelendi` : 'ödemeleri erteleyerek koruyun'}{/if}
			</div>
		</div>
		{#if proj.shownUnits.length === 0}
			<p class="text-xs text-gray-500 py-3">Bu ay planlı ödeme yok.</p>
		{/if}
		{#each proj.shownUnits as u (u.key)}
			{@const gout = u.effDay === null}
			{@const multi = u.members.length > 1}
			<div class="border-b border-gray-100 py-2.5">
				<!-- flex-wrap: mobilde tarih seçici + sıfırla alt satıra kayar (isim/tarih üst üste gelmez) -->
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5 sm:gap-x-3">
					<span class="tabular-nums text-[11.5px] text-gray-500 w-10 shrink-0">{labelDate(u.day)}</span>
					<button type="button" onclick={() => toggleGroup(u.key)} aria-expanded={!!openGroups[u.key]}
						class="flex-1 min-w-0 flex items-center gap-1.5 text-left cursor-pointer">
						<ChevronDown size={14} class="shrink-0 text-gray-500 transition-transform {openGroups[u.key] ? '' : '-rotate-90'}" />
						<span class="text-[13px] sm:text-[13.5px] font-semibold truncate {gout ? 'text-gray-400 line-through' : 'text-gray-900'}">{u.label}</span>
						{#if multi}<span class="text-[11px] text-gray-500 shrink-0">{u.members.length} ödeme</span>{/if}
					</button>
					<span class="tabular-nums text-[13px] sm:text-[13.5px] font-semibold w-[76px] text-right shrink-0 {gout ? 'text-gray-400 line-through' : 'text-brass-dark'}">−{fmtEur(u.total)}</span>
					{#if canDefer}
						<div class="flex items-center gap-2 w-full sm:w-auto justify-end">
							<input
								type="date"
								value={u.effIso}
								min={u.day}
								max={`${data.month_start.slice(0, 4)}-12-31`}
								onchange={(e) => setGroupDate(u.memberIds, (e.currentTarget as HTMLInputElement).value)}
								aria-label={`${u.label} (${labelDate(u.day)}) ödemelerini ertele`}
								class="date-filter-input shrink-0 w-[130px] rounded-lg border px-2 py-1.5 text-[11.5px] cursor-pointer focus:ring-2 focus:ring-teal-500 focus:outline-none {u.changed ? 'border-brass/50 bg-brass-soft text-brass-dark' : 'border-gray-200 bg-white text-gray-700'}"
							/>
							<button type="button" onclick={() => resetGroup(u.memberIds)} disabled={!u.changed}
								title="Erteleme tarihini sıfırla" aria-label="Erteleme tarihini sıfırla"
								class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg border border-gray-200 bg-white text-brass-dark cursor-pointer disabled:opacity-30 disabled:cursor-default hover:bg-gray-50">
								<RotateCcw size={13} />
							</button>
						</div>
					{/if}
				</div>
				{#if u.changed}
					<div class="pl-10 pt-1 text-[10.5px] text-brass-dark">→ {labelDate(u.effIso)}{gout ? ' tarihine ertelendi (gelecek aya)' : ' tarihine ertelendi'}</div>
				{/if}
				{#if openGroups[u.key]}
					<div class="pl-10 pt-1.5 space-y-1">
						{#each u.members as m (m.id)}
							<div class="flex items-center gap-2 text-[12px]">
								<span class="text-gray-700 truncate">{cleanName(m.name)}</span>
								<span class="ml-auto tabular-nums text-gray-600 shrink-0">−{fmtEur(m.amount_eur)}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/each}
		{#if proj.otherCount > 0}
			<p class="text-[11.5px] text-gray-500 pt-2">
				+{proj.otherCount} daha küçük ödeme (toplam {fmtEur(proj.otherSum)}) — projeksiyona dahildir.
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
