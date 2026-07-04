<!--
	NakitKoruma.svelte — Nakit Koruma · Ödeme Erteleme (Runway) + Vadesi Geçenler.

	Bankadaki nakitten ay-sonuna gün gün projeksiyon; bakiyenin negatife düştüğü gün
	uyarısı. Ödemeler gün+tür bazında gruplu; tarih seçiciyle **kalıcı ötelenir**
	(POST /finance/cash-flow/defer → tüm açık ekranlara WS ile yansır). Vadesi geçmiş
	ödenmemiş kalemler "Vadesi Geçenler" başlığı altında (Cuma roll-over kaldırıldı).
	Erteleme yalnız finance.cash_flow USE yetkisi olanlara açık. Tasarım: lacivert/altın.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { WS_EVENT } from '$lib/constants/realtime';
	import { projectRunway } from '$lib/utils/finance';
	import { RotateCcw, ShieldCheck, ChevronDown, AlertTriangle } from 'lucide-svelte';

	type Flow = { id: string; date: string; name: string; amount_eur: number; source_type?: string; deferred?: boolean; original_date?: string; projected?: boolean };
	type RunwayData = {
		month_label: string; month_start: string; month_end: string; today: string;
		start_eur: number; inflows: Flow[]; outs: Flow[]; overdue: Flow[]; skipped_no_rate: number;
	};

	let { embedded = false }: { embedded?: boolean } = $props();
	// Erteleme (öteleme) yalnız finance.cash_flow KULLANIM yetkisi olanlara açık.
	const canDefer = hasPermission('finance.cash_flow', 'use');

	const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const SRC_LABELS: Record<string, string> = {
		vendor_payment: 'Cari Ödemeleri', credit: 'Kredi / Leasing Taksitleri',
		cc_payment: 'KK Borç Ödemeleri', check: 'Verilen Çekler', salary: 'Maaş Ödemeleri',
		sgk: 'SGK', tax: 'Vergiler', recurring: 'Düzenli Ödemeler', withholding: 'Stopajlar',
		dividend: 'Temettü', rent_expense: 'Verilen Kiralar', advance: 'Avanslar',
	};

	let data = $state<RunwayData | null>(null);
	let loading = $state(true);
	let mutating = $state(false); // öteleme POST'u sürerken
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
	function cleanName(name: string): string {
		return name.replace(/^\[[^\]]*\]\s*/, '');
	}

	type Unit = { key: string; label: string; day: string; members: Flow[]; memberIds: string[]; deferIds: string[]; deferrable: boolean; total: number; deferred: boolean; overdue: boolean };

	// Kalemleri gün + kaynak türü bazında grupla (tek üye olsa da başlık altında)
	function groupUnits(items: Flow[], overdue: boolean): Unit[] {
		const map = new Map<string, Flow[]>();
		for (const o of items) {
			const key = `${overdue ? 'od:' : ''}${o.date}|${o.source_type ?? 'other'}`;
			const arr = map.get(key);
			if (arr) arr.push(o); else map.set(key, [o]);
		}
		const units: Unit[] = [];
		for (const [key, members] of map) {
			const first = members[0];
			// Tahmini (projected) kalemler ötelenemez → yalnız gerçek üyeler defer edilir
			const deferIds = members.filter((m) => !m.projected).map((m) => m.id);
			units.push({
				key, label: SRC_LABELS[first.source_type ?? ''] ?? cleanName(first.name),
				day: first.date, members, memberIds: members.map((m) => m.id),
				deferIds, deferrable: deferIds.length > 0,
				total: members.reduce((s, m) => s + m.amount_eur, 0),
				deferred: members.some((m) => m.deferred),
				overdue,
			});
		}
		return units.sort((a, b) => a.day.localeCompare(b.day));
	}

	// Projeksiyon — outs + overdue (vadesi geçen bugüne çekilir; hâlâ ödenecek borç)
	const proj = $derived.by(() => {
		if (!data) return null;
		const today = data.today;
		const projOuts: { id: string; date: string; amount_eur: number }[] = [
			...data.outs.map((o) => ({ id: o.id, date: o.date, amount_eur: o.amount_eur })),
			// vadesi geçenler → bugün öденecekmiş gibi projeksiyona girer
			...data.overdue.map((o) => ({ id: o.id, date: today, amount_eur: o.amount_eur })),
		];
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

		// Gösterilecek üniteler: outs (tarihe göre) + top-N
		const outUnits = groupUnits(data.outs, false);
		const overdueUnits = groupUnits(data.overdue, true);
		const TOP_N = 20;
		outUnits.sort((a, b) => b.total - a.total);
		const shownOut = new Set<Unit>(outUnits.slice(0, TOP_N));
		const otherOut = outUnits.filter((u) => !shownOut.has(u));
		const shownOutUnits = [...shownOut].sort((a, b) => a.day.localeCompare(b.day));

		return {
			negative,
			statusText: negative
				? `${r.firstNeg} ${MONTHS_SHORT[Number(ym.slice(5, 7)) - 1]}'de bakiye negatife düşüyor`
				: 'Ay boyunca nakit pozitif kalıyor',
			pts,
			zeroY: mapY(0).toFixed(1),
			lowX: mapX(r.lowDay).toFixed(1),
			lowY: mapY(r.lowVal).toFixed(1),
			lowLabel: `${labelDate(`${ym}-${String(r.lowDay).padStart(2, '0')}`)} · ${signed(r.lowVal)}`,
			endBal: r.endBal,
			shownOutUnits,
			overdueUnits,
			overdueTotal: data.overdue.reduce((s, o) => s + o.amount_eur, 0),
			otherCount: otherOut.reduce((s, u) => s + u.members.length, 0),
			otherSum: otherOut.reduce((s, u) => s + u.total, 0),
			firstLabel: labelDate(today),
			lastLabel: labelDate(data.month_end),
		};
	});

	// Beklenen tahsilatlar — aynı gün+tür tek çip
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

	async function load() {
		try {
			data = await api.get<RunwayData>('/finance/cash-flow/runway');
		} catch (err) {
			console.error('Nakit koruma verisi yüklenemedi:', err);
			showToast('Nakit koruma verisi yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	function parseId(id: string): { source_type: string; source_id: number } {
		const i = id.lastIndexOf(':');
		return { source_type: id.slice(0, i), source_id: Number(id.slice(i + 1)) };
	}

	// Grubu KALICI ötele/geri al — TEK batch isteği (büyük grupta N POST değil), sonra tazele.
	async function mutateGroup(memberIds: string[], deferredTo: string | null, okMsg: string) {
		if (mutating) return;
		mutating = true;
		try {
			const items = memberIds.map(parseId);
			await api.post('/finance/cash-flow/defer-batch', { items, deferred_to: deferredTo });
			await load();
			showToast(okMsg, 'success');
		} catch (err: any) {
			console.error('Öteleme işlemi başarısız:', err);
			showToast(err?.message || 'İşlem başarısız', 'error');
		} finally {
			mutating = false;
		}
	}
	function deferGroup(memberIds: string[], newDate: string) {
		if (!newDate) return;
		mutateGroup(memberIds, newDate, 'Ödeme ertelendi');
	}
	function resetGroup(memberIds: string[]) {
		mutateGroup(memberIds, null, 'Öteleme geri alındı');
	}
	function toggleGroup(key: string) {
		openGroups[key] = !openGroups[key];
	}

	let unsubWs: (() => void) | null = null;
	onMount(() => {
		load();
		// Başka kullanıcı öteleme yapınca / finans değişince tazele
		unsubWs = onWsEvent(WS_EVENT.FINANCE_UPDATED, () => load());
		return () => unsubWs?.();
	});
</script>

<div class={embedded ? 'mt-5 pt-5 border-t border-gray-200' : 'bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6'}>
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
		<div class="rounded-2xl bg-teal-700 px-5 py-4 text-teal-100 {mutating ? 'opacity-70' : ''}">
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

		<!-- VADESİ GEÇENLER -->
		{#if proj.overdueUnits.length > 0}
			<div class="mt-4 flex items-center gap-2 text-[11px] tracking-[1px] uppercase text-red-700 font-bold">
				<AlertTriangle size={13} /> Vadesi Geçenler · {fmtEur(proj.overdueTotal)}
			</div>
			<div class="mt-1.5 rounded-xl border border-red-200 bg-red-50/40 divide-y divide-red-100">
				{#each proj.overdueUnits as u (u.key)}
					{@const multi = u.members.length > 1}
					<div class="px-2.5 py-2.5">
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5 sm:gap-x-3">
							<span class="tabular-nums text-[11.5px] text-red-600 w-10 shrink-0">{labelDate(u.day)}</span>
							<button type="button" onclick={() => toggleGroup(u.key)} aria-expanded={!!openGroups[u.key]}
								class="flex-1 min-w-0 flex items-center gap-1.5 text-left cursor-pointer">
								<ChevronDown size={14} class="shrink-0 text-red-400 transition-transform {openGroups[u.key] ? '' : '-rotate-90'}" />
								<span class="text-[13px] sm:text-[13.5px] font-semibold truncate text-gray-900">{u.label}</span>
								{#if multi}<span class="text-[11px] text-red-500 shrink-0">{u.members.length} ödeme</span>{/if}
							</button>
							<span class="tabular-nums text-[13px] sm:text-[13.5px] font-semibold w-[76px] text-right shrink-0 text-red-700">−{fmtEur(u.total)}</span>
							{#if canDefer && u.deferrable}
								<div class="flex items-center gap-2 w-full sm:w-auto justify-end">
									<input type="date" value="" min={data.today} max={`${data.month_start.slice(0, 4)}-12-31`}
										disabled={mutating}
										onchange={(e) => deferGroup(u.deferIds, (e.currentTarget as HTMLInputElement).value)}
										aria-label={`${u.label} vadesi geçen ödemeyi ileri tarihe ötele`}
										class="date-filter-input shrink-0 w-[130px] rounded-lg border border-gray-200 bg-white text-gray-700 px-2 py-1.5 text-[11.5px] cursor-pointer focus:ring-2 focus:ring-teal-500 focus:outline-none disabled:opacity-50" />
								</div>
							{/if}
						</div>
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
			</div>
		{/if}

		<!-- BEKLENEN TAHSİLATLAR -->
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

		<!-- BU AY PLANLI ÖDEMELER -->
		<div class="flex items-center justify-between mt-5 mb-1.5">
			<div class="text-[11px] tracking-[1px] uppercase text-brass-dark font-bold">Bu Ay Planlı Ödemeler</div>
			<div class="text-[11.5px] text-gray-500">{canDefer ? 'tarih seçerek öteleyin' : ''}</div>
		</div>
		{#if proj.shownOutUnits.length === 0}
			<p class="text-xs text-gray-500 py-3">Bu ay planlı ödeme yok.</p>
		{/if}
		{#each proj.shownOutUnits as u (u.key)}
			{@const multi = u.members.length > 1}
			<div class="border-b border-gray-100 py-2.5">
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5 sm:gap-x-3">
					<span class="tabular-nums text-[11.5px] text-gray-500 w-10 shrink-0">{labelDate(u.day)}</span>
					<button type="button" onclick={() => toggleGroup(u.key)} aria-expanded={!!openGroups[u.key]}
						class="flex-1 min-w-0 flex items-center gap-1.5 text-left cursor-pointer">
						<ChevronDown size={14} class="shrink-0 text-gray-500 transition-transform {openGroups[u.key] ? '' : '-rotate-90'}" />
						<span class="text-[13px] sm:text-[13.5px] font-semibold truncate text-gray-900">{u.label}</span>
						{#if multi}<span class="text-[11px] text-gray-500 shrink-0">{u.members.length} ödeme</span>{/if}
					</button>
					<span class="tabular-nums text-[13px] sm:text-[13.5px] font-semibold w-[76px] text-right shrink-0 text-brass-dark">−{fmtEur(u.total)}</span>
					{#if canDefer && u.deferrable}
						<div class="flex items-center gap-2 w-full sm:w-auto justify-end">
							<input type="date" value={u.day} min={data.today} max={`${data.month_start.slice(0, 4)}-12-31`}
								disabled={mutating}
								onchange={(e) => deferGroup(u.deferIds, (e.currentTarget as HTMLInputElement).value)}
								aria-label={`${u.label} (${labelDate(u.day)}) ödemelerini ötele`}
								class="date-filter-input shrink-0 w-[130px] rounded-lg border px-2 py-1.5 text-[11.5px] cursor-pointer focus:ring-2 focus:ring-teal-500 focus:outline-none disabled:opacity-50 {u.deferred ? 'border-brass/50 bg-brass-soft text-brass-dark' : 'border-gray-200 bg-white text-gray-700'}" />
							<button type="button" onclick={() => resetGroup(u.deferIds)} disabled={!u.deferred || mutating}
								title="Ötelemeyi geri al" aria-label="Ötelemeyi geri al"
								class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg border border-gray-200 bg-white text-brass-dark cursor-pointer disabled:opacity-30 disabled:cursor-default hover:bg-gray-50">
								<RotateCcw size={13} />
							</button>
						</div>
					{/if}
				</div>
				{#if u.deferred}
					<div class="pl-10 pt-1 text-[10.5px] text-brass-dark">→ {labelDate(u.day)} tarihine ertelendi</div>
				{/if}
				{#if openGroups[u.key]}
					<div class="pl-10 pt-1.5 space-y-1">
						{#each u.members as m (m.id)}
							<div class="flex items-center gap-2 text-[12px]">
								<span class="text-gray-700 truncate">{cleanName(m.name)}</span>
								{#if m.deferred && m.original_date}<span class="text-[10px] text-gray-400">(asıl {labelDate(m.original_date)})</span>{/if}
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
			Öteleme <strong>kalıcıdır</strong> ve tüm kullanıcılara yansır — ödemenin vade tarihi ileri çekilir
			(borç ortadan kalkmaz, yalnızca zamanlaması değişir). Vadesi geçen ödemeler artık otomatik olarak
			bir sonraki Cuma'ya kaydırılmaz; ödenene veya ötelenene kadar "Vadesi Geçenler" altında kalır.
			Tahsilat tarafında yalnızca kayıtlı beklenen girişler yer alır (günlük gerçekleşen oda geliri hariç).
		</p>
		{#if data.skipped_no_rate > 0}
			<p class="text-[11px] text-amber-700 mt-1">{data.skipped_no_rate} kalem kur bilgisi olmadığından hesaba katılamadı.</p>
		{/if}
	{/if}
</div>
