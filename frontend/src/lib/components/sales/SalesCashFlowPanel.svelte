<script lang="ts">
	// Nakit Akım sekmesi — basit tasarım (2026-07-19): avans/fatura/mahsup/vadesi geçen
	// KPI'ları + Tahsilat Takvimi (tahsil edildi lacivert · vadesi geçti kırmızı · bekleyen
	// çizgili) + Acente Avans & Mahsup + Vadesi Geçen Alacaklar. Veri: /sales/acente-mahsup/
	// projeksiyonu (rezervasyon cirosu + acente vadesi + gerçek avans/hak ediş gecikmesi).
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { Inbox, Wallet, ReceiptText, Scale, AlarmClock } from 'lucide-svelte';
	import { FUTURE_STRIPE, eurCompact, monthKeyLabel, trInt } from '$lib/utils/salesDesign';

	// ── Props ────────────────────────────────────────────────
	let {
		year,
		yearOpts,
		onYear,
		tick = 0,
	}: {
		year: number;
		yearOpts: number[];
		onYear: (y: number) => void;
		tick?: number;
	} = $props();

	// ── State ────────────────────────────────────────────────
	let loading = $state(true);
	let data = $state<any>(null);

	// ── Türetilmiş ───────────────────────────────────────────
	let calRows = $derived.by(() => {
		if (!data?.cashflow?.calendar) return [];
		const months = data.cashflow.calendar.months as any[];
		const dev = data.cashflow.calendar.devreden || 0;
		const max = Math.max(1, dev, ...months.map((m) => m.collected + m.overdue + m.pending));
		const w = (v: number) => ((v / max) * 100).toFixed(2);
		const rows = months.map((m) => ({
			key: 'm' + m.month,
			label: m.name,
			s1: w(m.collected),
			s2: w(m.overdue),
			s3: w(m.pending),
			pendingStripe: true,
			amt: eurCompact(m.total),
			cum: `küm. ${eurCompact(m.cumulative)}`,
			title:
				`${m.name} — tahsilat ${eurCompact(m.total)}` +
				(m.overdue > 0 ? ` · vadesi geçen ${eurCompact(m.overdue)}` : '') +
				` · kümülatif ${eurCompact(m.cumulative)}`,
		}));
		rows.push({
			key: 'dev',
			label: 'Dev.',
			s1: '0',
			s2: '0',
			s3: w(dev),
			pendingStripe: true,
			amt: eurCompact(dev),
			cum: `${year + 1}'e devreden`,
			title: `${year + 1}'e devreden vadeli tahsilat — son ayların vadeli kısmı`,
		});
		return rows;
	});
	let overdueRows = $derived(data?.overdue?.rows ?? []);
	let advRows = $derived(data?.advances?.rows ?? []);

	// ── Veri fonksiyonları ───────────────────────────────────
	async function load() {
		loading = true;
		try {
			data = await api.get<any>(`/sales/acente-mahsup/?year=${year}`);
		} catch (e) {
			console.error('Satış nakit akımı yüklenemedi:', e);
			showToast('Satış nakit akımı yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	// Yıl veya canlı-yenileme tetiği değişince yeniden yükle
	$effect(() => {
		const _y = year, _t = tick;
		load();
	});
</script>

<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
	<!-- Başlık + yıl -->
	<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
		<h2 class="text-base font-semibold text-gray-900">{year} Satış Nakit Akımı</h2>
		<select
			value={year}
			onchange={(e) => onYear(Number((e.currentTarget as HTMLSelectElement).value))}
			aria-label="Yıl"
			class="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm focus:ring-2 focus:ring-teal-500"
		>
			{#each yearOpts as y}<option value={y}>{y}</option>{/each}
		</select>
	</div>

	{#if loading && !data}
		<TableSkeleton rows={8} columns={4} />
	{:else if !data}
		<EmptyState icon={Inbox} title="Veri yok" description="Nakit akım projeksiyonu oluşturulamadı." />
	{:else}
		<!-- KPI kutuları -->
		<div class="mb-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
			<StatCard icon={Wallet} accent="teal" label="Alınan Avans" value={eurCompact(data.kpi.advance_received)} hint="{advRows.length} acente · depozit" />
			<StatCard icon={ReceiptText} accent="teal" label="Kesilen Fatura" value={eurCompact(data.kpi.realized)} hint="yıl projeksiyonu {eurCompact(data.kpi.grand_total)}" />
			<StatCard icon={Scale} accent="emerald" label="Mahsuplaşma" value={eurCompact(data.kpi.advance_applied)} hint="kalan avans {eurCompact(data.kpi.advance_remaining)}" />
			<StatCard
				icon={AlarmClock}
				accent={data.overdue.total > 0 ? 'red' : 'gray'}
				label="Vadesi Geçen"
				value={data.overdue.total > 0 ? eurCompact(data.overdue.total) : '—'}
				hint={data.overdue.total > 0 ? `${overdueRows.length} acente · takipte` : 'gecikme yok'}
			/>
		</div>

		<!-- Tahsilat Takvimi -->
		<div class="mb-2.5 flex flex-wrap items-center justify-between gap-2.5">
			<h3 class="text-sm font-semibold text-gray-800">Tahsilat Takvimi</h3>
			<div class="flex flex-wrap gap-3.5 text-[11px] text-gray-600">
				<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm bg-teal-700"></span>Tahsil edildi</span>
				<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm bg-red-600"></span>Vadesi geçti</span>
				<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-sm" style="background:{FUTURE_STRIPE}"></span>Bekleyen (vadeli)</span>
			</div>
		</div>
		<div class="flex flex-col gap-1.5">
			{#each calRows as m (m.key)}
				<div class="flex items-center gap-3 px-1.5 py-0.5" title={m.title}>
					<span class="w-[46px] shrink-0 text-xs font-semibold tabular-nums text-gray-600">{m.label}</span>
					<span class="flex h-[18px] min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
						<span class="h-full bg-teal-700" style="width:{m.s1}%"></span>
						<span class="h-full bg-red-600" style="width:{m.s2}%"></span>
						<span class="h-full" style="width:{m.s3}%;background:{FUTURE_STRIPE}"></span>
					</span>
					<span class="w-[84px] shrink-0 text-right sm:w-[120px]">
						<span class="block text-xs font-semibold tabular-nums text-teal-700">{m.amt}</span>
						<span class="hidden text-[10.5px] tabular-nums whitespace-nowrap text-gray-500 sm:block">{m.cum}</span>
					</span>
				</div>
			{/each}
		</div>
		<p class="mt-2.5 text-xs leading-relaxed text-gray-500">
			Kesilen fatura {eurCompact(data.kpi.realized)} − avans mahsubu {eurCompact(data.kpi.advance_applied)} = net tahsil edilecek tutar, acente vadesine göre (peşin / 30 / 60 gün karması) tahsilat ayına yazılır. Kalan avanslar ({eurCompact(data.kpi.advance_remaining)}) ileri ayların faturalarına mahsup edilecektir.
		</p>

		<!-- Acente Avans & Mahsup -->
		<div class="mt-4.5 border-t border-gray-200 pt-3.5">
			<h3 class="mb-2.5 text-sm font-semibold text-gray-800">Acente Avans &amp; Mahsup</h3>
			{#if advRows.length === 0}
				<p class="text-xs text-gray-500">Kayıtlı acente avansı bulunmuyor.</p>
			{:else}
				<div class="flex flex-col gap-1.5">
					{#each advRows as a (a.agency_id)}
						<div
							class="flex items-center gap-3 px-1.5 py-0.5"
							title="{a.agency} — alınan €{trInt(a.received)} · mahsup €{trInt(a.applied)} · kalan €{trInt(a.remaining)}"
						>
							<span class="w-24 shrink-0 truncate text-xs font-medium text-gray-600 sm:w-[170px]">{a.agency}</span>
							<span class="relative h-4 min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
								<span class="block h-full rounded-full bg-emerald-500" style="width:{Math.max(a.pct, 1).toFixed(1)}%"></span>
								<span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10.5px] font-semibold tabular-nums whitespace-nowrap text-gray-700">%{Math.round(a.pct)} mahsup</span>
							</span>
							<span class="w-[84px] shrink-0 text-right sm:w-[120px]">
								<span class="block text-xs font-semibold tabular-nums text-teal-700">{eurCompact(a.remaining)}</span>
								<span class="hidden text-[10.5px] tabular-nums whitespace-nowrap text-gray-500 sm:block">alınan {eurCompact(a.received)}</span>
							</span>
						</div>
					{/each}
				</div>
				<p class="mt-2.5 text-xs leading-relaxed text-gray-500">
					Yeşil bar avansın faturalarla mahsup edilen kısmıdır; sağdaki tutar mahsup bekleyen kalan avanstır. Mahsup edilen kısım vadesinde tekrar tahsil edilmez.
				</p>
			{/if}
		</div>

		<!-- Vadesi Geçen Alacaklar -->
		<div class="mt-4.5 border-t border-gray-200 pt-3.5">
			<h3 class="mb-2.5 text-sm font-semibold text-red-700">Vadesi Geçen Alacaklar</h3>
			{#if overdueRows.length > 0}
				<div class="flex flex-col gap-0.5">
					{#each overdueRows as o (o.agency_id)}
						<div class="flex items-center gap-3 rounded-lg px-1.5 py-1.5 hover:bg-gray-50">
							<span class="min-w-0 flex-1">
								<span class="block truncate text-xs font-medium text-gray-800">{o.agency}</span>
								<span class="block text-[10.5px] tabular-nums whitespace-nowrap text-gray-500">Vade ayı: {monthKeyLabel(o.oldest_due_month)} · hak ediş faturası</span>
							</span>
							<span class="shrink-0 rounded-full bg-red-50 px-2.5 py-0.5 text-[10px] font-semibold whitespace-nowrap text-red-700">{o.max_days} gün gecikti</span>
							<span class="w-[86px] shrink-0 text-right text-xs font-semibold tabular-nums text-red-700">{eurCompact(o.amount)}</span>
						</div>
					{/each}
				</div>
				<div class="mt-2 flex items-center gap-3 border-t border-gray-200 px-1.5 pt-2">
					<span class="flex-1 text-xs font-semibold text-gray-800">Toplam</span>
					<span class="text-[13px] font-bold tabular-nums text-red-700">{eurCompact(data.overdue.total)}</span>
				</div>
			{:else}
				<p class="text-xs text-gray-500">Seçili yılda vadesi geçmiş alacak bulunmuyor.</p>
			{/if}
		</div>
	{/if}
</div>
