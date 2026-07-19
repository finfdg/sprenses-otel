<script lang="ts">
	// Günlük Hareketler sekmesi — basit tasarım (2026-07-19): son 14 günün gün kartları
	// (gelen/iptal kutuları + net ciro). Bir kartı tıklayınca o günün AYLIK DOLULUK ETKİSİ
	// (mevcut doluluk lacivert + gelen katkısı pirinç + iptal kaybı kırmızı) ve hareket
	// listesi açılır. Veri: /sales/daily-activity/* (Sedna canlı) + occupancy-overview (taban).
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { CloudOff } from 'lucide-svelte';
	import {
		MONTHS_FULL_TR,
		MONTHS_TR,
		WEEKDAYS_TR,
		eurCompact,
		spreadStayMonths,
		stayRangeLabel,
		trInt,
	} from '$lib/utils/salesDesign';

	// ── Props ────────────────────────────────────────────────
	let { tick = 0 }: { tick?: number } = $props();

	// ── Sabitler ─────────────────────────────────────────────
	const RANGE_DAYS = 14;

	// ── State ────────────────────────────────────────────────
	let loading = $state(true);
	let unavailable = $state<string | null>(null); // Sedna kapalı/erişilemez mesajı
	let days = $state<any[]>([]);
	let totals = $state<any>(null);
	let openDate = $state<string | null>(null);
	let detailLoading = $state(false);
	let moves = $state<any[]>([]);
	let effRows = $state<any[]>([]);
	const occCache = new Map<number, any>(); // yıl → occupancy-overview (etki tabanı)

	// ── Formatlama ───────────────────────────────────────────
	function iso(d: Date): string {
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	}
	function dayLabel(dateStr: string): string {
		const d = new Date(dateStr + 'T00:00:00');
		return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')} ${WEEKDAYS_TR[d.getDay()]}`;
	}

	// ── Veri fonksiyonları ───────────────────────────────────
	async function load() {
		loading = true;
		unavailable = null;
		try {
			const end = new Date();
			const start = new Date();
			start.setDate(end.getDate() - (RANGE_DAYS - 1));
			const data = await api.get<any>(
				`/sales/daily-activity/summary?start_date=${iso(start)}&end_date=${iso(end)}`,
			);
			days = data.days || [];
			totals = data.totals || null;
		} catch (e: any) {
			console.error('Günlük hareketler yüklenemedi:', e);
			if (typeof e?.message === 'string' && e.message.includes('Sedna')) {
				unavailable = e.message;
			} else {
				showToast('Günlük hareketler yüklenemedi', 'error');
			}
		} finally {
			loading = false;
		}
	}

	async function ensureOccYear(y: number): Promise<any | null> {
		if (occCache.has(y)) return occCache.get(y);
		try {
			const data = await api.get<any>(`/sales/reservations/occupancy-overview?year=${y}`);
			occCache.set(y, data);
			return data;
		} catch (e) {
			console.error('Doluluk tabanı yüklenemedi:', e);
			return null;
		}
	}

	async function openDay(date: string) {
		if (openDate === date) {
			openDate = null;
			return;
		}
		openDate = date;
		detailLoading = true;
		moves = [];
		effRows = [];
		try {
			const [gelen, iptal] = await Promise.all([
				api.get<any>(`/sales/daily-activity/details?activity_date=${date}&type=new`),
				api.get<any>(`/sales/daily-activity/details?activity_date=${date}&type=cancelled`),
			]);
			// Hareket listesi: o gün GELEN + o gün İPTAL edilen (aynı kayıt her ikisinde olabilir — net 0)
			const gelenItems = (gelen.items || []).map((it: any) => ({ ...it, _cancelled: false }));
			const iptalItems = (iptal.items || []).map((it: any) => ({ ...it, _cancelled: true }));
			moves = [...gelenItems, ...iptalItems];

			// Aylık doluluk etkisi: konaklama geceleri aylara yayılır, taban = occupancy-overview
			const eff = spreadStayMonths(
				moves.map((it) => ({ ...it, is_cancelled: it._cancelled })),
			);
			const years = [...new Set(eff.map((e) => e.y))];
			const bases = new Map<number, any>();
			for (const y of years) {
				const b = await ensureOccYear(y);
				if (b) bases.set(y, b);
			}
			const nowYear = new Date().getFullYear();
			effRows = eff.map((e) => {
				const bm = bases.get(e.y)?.months?.[e.m - 1];
				const cap = Math.max(1, bm?.capacity_nights || 0);
				const basePct = bm ? bm.occupancy_pct : 0;
				const gW = e.gelen > 0 ? Math.max((e.gelen / cap) * 100, 0.8) : 0;
				const iW = e.iptal > 0 ? Math.max((e.iptal / cap) * 100, 0.8) : 0;
				return {
					key: e.key,
					label: MONTHS_TR[e.m - 1] + (e.y !== nowYear ? ` ${String(e.y).slice(2)}` : ''),
					baseW: Math.max(basePct - gW, 0),
					gW,
					iW,
					pct: Math.round(basePct),
					gelen: e.gelen,
					iptal: e.iptal,
					title: `${MONTHS_FULL_TR[e.m - 1]} ${e.y} — mevcut %${Math.round(basePct)} · gelen +${trInt(e.gelen)} oda-gece · iptal −${trInt(e.iptal)}`,
				};
			});
		} catch (e) {
			console.error('Gün detayı yüklenemedi:', e);
			showToast('Gün detayı yüklenemedi', 'error');
		} finally {
			detailLoading = false;
		}
	}

	// Canlı yenileme tetiği değişince yeniden yükle
	$effect(() => {
		const _t = tick;
		load();
	});

	let todayIso = $derived(iso(new Date()));
</script>

<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
	<div class="mb-4 flex flex-wrap items-baseline justify-between gap-3">
		<h2 class="text-base font-semibold text-gray-900">Günlük Hareketler</h2>
		{#if totals}
			<span class="text-xs tabular-nums text-gray-500">
				Son {RANGE_DAYS} gün · {trInt(totals.new?.count || 0)} gelen · {trInt(totals.cancelled?.count || 0)} iptal
			</span>
		{/if}
	</div>

	{#if loading && days.length === 0}
		<TableSkeleton rows={6} columns={3} />
	{:else if unavailable}
		<EmptyState icon={CloudOff} title="Sedna bağlantısı yok" description={unavailable} />
	{:else if days.length === 0}
		<EmptyState icon={CloudOff} title="Hareket yok" description="Seçili dönemde rezervasyon hareketi bulunmuyor." />
	{:else}
		<div class="flex flex-col gap-2">
			{#each days as dy (dy.date)}
				{@const open = openDate === dy.date}
				{@const isToday = dy.date === todayIso}
				{@const net = dy.net_eur || 0}
				<div class="rounded-xl border bg-white {open ? 'border-brass shadow-md' : 'border-gray-200'}">
					<button type="button" class="w-full cursor-pointer px-3.5 py-3 text-left" onclick={() => openDay(dy.date)}>
						<div class="mb-2 flex items-center justify-between">
							<span class="text-xs font-semibold tabular-nums text-gray-800">
								{dayLabel(dy.date)}
								{#if isToday}
									<span class="ml-2 rounded-full border border-brass-light bg-brass-soft px-2 py-0.5 text-[9.5px] font-semibold text-brass-dark">Bugün</span>
								{/if}
							</span>
							<span class="text-xs font-semibold tabular-nums {net >= 0 ? 'text-teal-700' : 'text-red-700'}">
								{net >= 0 ? '+' : '−'}€{trInt(Math.abs(net))}
							</span>
						</div>
						<div class="grid grid-cols-2 gap-2">
							<div class="rounded-lg border border-teal-100 bg-teal-50 px-2.5 py-1.5">
								<span class="block text-[10.5px] font-medium text-teal-600">Gelen</span>
								<span class="text-xs font-semibold tabular-nums whitespace-nowrap text-teal-700">
									{dy.new.count} rez · {eurCompact(dy.new.eur)}
								</span>
							</div>
							<div class="rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 {dy.cancelled.count > 0 ? '' : 'opacity-45'}">
								<span class="block text-[10.5px] font-medium text-red-700">İptal</span>
								<span class="text-xs font-semibold tabular-nums whitespace-nowrap text-red-700">
									{dy.cancelled.count > 0 ? `${dy.cancelled.count} rez · ${eurCompact(dy.cancelled.eur)}` : 'iptal yok'}
								</span>
							</div>
						</div>
					</button>
					{#if open}
						<div class="border-t border-gray-200 px-3.5 pb-4 pt-3.5">
							{#if detailLoading}
								<TableSkeleton rows={4} columns={2} />
							{:else}
								<div class="mb-2.5 flex flex-wrap items-center justify-between gap-2.5">
									<h3 class="text-[13.5px] font-semibold text-gray-800">Aylık Doluluk Etkisi</h3>
									<div class="flex flex-wrap gap-3.5 text-[11px] text-gray-600">
										<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm bg-teal-700"></span>Mevcut doluluk</span>
										<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm bg-brass"></span>Gelen katkısı</span>
										<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm bg-red-600"></span>İptal (kayıp)</span>
									</div>
								</div>
								{#if effRows.length === 0}
									<p class="py-2 text-xs text-gray-500">Konaklama tarihi olan hareket bulunmuyor.</p>
								{:else}
									<div class="flex flex-col gap-1.5">
										{#each effRows as m (m.key)}
											<div class="flex items-center gap-3 py-0.5" title={m.title}>
												<span class="w-[46px] shrink-0 text-xs font-semibold tabular-nums text-gray-600">{m.label}</span>
												<span class="flex h-[18px] min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
													<span class="h-full bg-teal-700" style="width:{m.baseW.toFixed(2)}%"></span>
													<span class="h-full bg-brass" style="width:{m.gW.toFixed(2)}%"></span>
													<span class="h-full bg-red-600" style="width:{m.iW.toFixed(2)}%"></span>
												</span>
												<span class="w-[78px] shrink-0 text-right sm:w-[110px]">
													<span class="block text-xs font-semibold tabular-nums text-teal-700">%{m.pct}</span>
													<span class="block text-[10px] tabular-nums whitespace-nowrap">
														{#if m.gelen > 0}<span class="text-brass-dark">+{trInt(m.gelen)}</span>{/if}
														{#if m.iptal > 0}<span class="text-red-700">−{trInt(m.iptal)}</span>{/if}
														<span class="text-gray-500">gece</span>
													</span>
												</span>
											</div>
										{/each}
									</div>
								{/if}
								<div class="mt-3.5 border-t border-dashed border-gray-200 pt-2.5">
									<div class="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Hareket listesi</div>
									<div class="flex flex-col gap-0.5">
										{#each moves as v (v.rec_id + (v._cancelled ? '-i' : '-g'))}
											<div class="flex items-center gap-2.5 rounded-lg px-1 py-1.5 hover:bg-gray-50">
												<span class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold {v._cancelled ? 'bg-red-50 text-red-700' : 'bg-brass-soft text-brass-dark'}">
													{v._cancelled ? 'İptal' : 'Gelen'}
												</span>
												<span class="min-w-0 flex-1">
													<span class="block truncate text-xs font-medium text-gray-800">{v.agency || '(acente yok)'}</span>
													<span class="block text-[10.5px] tabular-nums whitespace-nowrap text-gray-500">
														{stayRangeLabel(v.checkin_date, v.checkout_date)} · {v.nights} gece · {v.pax} kişi
													</span>
												</span>
												<span class="shrink-0 text-xs font-semibold tabular-nums {v._cancelled ? 'text-red-700' : 'text-teal-700'}">
													{v._cancelled ? '−' : ''}€{trInt(v.eur)}
												</span>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
		<p class="mt-3.5 text-xs leading-relaxed text-gray-500">
			Bir gün kartına tıklayınca o günün aylık doluluk etkisi ve hareket detayı açılır. Lacivert çubuk mevcut doluluk; pirinç gelen katkısı, kırmızı iptal kaybıdır.
		</p>
	{/if}
</div>
