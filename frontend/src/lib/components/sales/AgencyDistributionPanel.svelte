<script lang="ts">
	// Acenteler sekmesi — basit tasarım (2026-07-19): Acente Dağılımı. Bireysel görünümde
	// her acente pay bazlı tek renk (teal-500) barla; Gruplu görünümde acente grupları
	// toplanır ve satıra tıklayınca üye acenteler açılır. Bar = seçili yıl cirosundaki pay.
	// Veri: /sales/reservations/summary (by_agency) + /sales/agency-groups/.
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { Inbox } from 'lucide-svelte';
	import { eurCompact, rollupAgencyGroups, trInt } from '$lib/utils/salesDesign';

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

	// ── Sabitler ─────────────────────────────────────────────
	const MODE_OPTS = [
		{ value: 'bireysel', label: 'Bireysel' },
		{ value: 'gruplu', label: 'Gruplu' },
	];

	// ── State ────────────────────────────────────────────────
	let loading = $state(true);
	let byAgency = $state<any[]>([]);
	let groups = $state<any[]>([]);
	let mode = $state('bireysel');
	let openGroup = $state<string | null>(null);

	// ── Türetilmiş ───────────────────────────────────────────
	let totalEur = $derived(byAgency.reduce((s, a) => s + (a.eur || 0), 0));
	let totalRez = $derived(byAgency.reduce((s, a) => s + (a.rez || 0), 0));
	let groupRows = $derived(rollupAgencyGroups(byAgency, groups));

	// ── Formatlama ───────────────────────────────────────────
	const valLabel = (eur: number, pct: number) => `${eurCompact(eur)} (${pct.toFixed(1).replace('.', ',')}%)`;

	// ── Veri fonksiyonları ───────────────────────────────────
	async function load() {
		loading = true;
		try {
			const [summary, groupList] = await Promise.all([
				api.get<any>(`/sales/reservations/summary?start_date=${year}-01-01&end_date=${year}-12-31`),
				api.get<any[]>('/sales/agency-groups/'),
			]);
			byAgency = summary.by_agency || [];
			groups = groupList || [];
		} catch (e) {
			console.error('Acente dağılımı yüklenemedi:', e);
			showToast('Acente dağılımı yüklenemedi', 'error');
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
	<!-- Başlık + kontroller -->
	<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
		<div class="flex items-baseline gap-2">
			<h2 class="text-base font-semibold text-gray-900">Acente Dağılımı</h2>
			<span class="text-xs text-gray-500">Tümü ({byAgency.length})</span>
		</div>
		<div class="flex flex-wrap items-center gap-2.5">
			<select
				value={year}
				onchange={(e) => onYear(Number((e.currentTarget as HTMLSelectElement).value))}
				aria-label="Yıl"
				class="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm focus:ring-2 focus:ring-teal-500"
			>
				{#each yearOpts as y}<option value={y}>{y}</option>{/each}
			</select>
			<SegmentedControl options={MODE_OPTS} value={mode} onchange={(v) => (mode = v)} ariaLabel="Görünüm" size="sm" />
		</div>
	</div>

	{#if loading && byAgency.length === 0}
		<TableSkeleton rows={8} columns={2} />
	{:else if byAgency.length === 0}
		<EmptyState icon={Inbox} title="Rezervasyon yok" description="Seçili yılda acente cirosu bulunmuyor." />
	{:else if mode === 'bireysel'}
		<div class="flex flex-col gap-1.5">
			{#each byAgency as a (a.name)}
				<div class="flex items-center gap-3 rounded-xl px-1.5 py-0.5" title="{a.name} — {trInt(a.rez)} rezervasyon · {trInt(a.eur)} €">
					<span class="w-24 shrink-0 truncate text-xs font-medium text-gray-600 sm:w-[170px]">{a.name}</span>
					<span class="relative h-6 min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
						<span class="block h-full rounded-full bg-teal-500" style="width:{Math.max(a.pct, 1).toFixed(1)}%"></span>
						<span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] font-semibold tabular-nums whitespace-nowrap text-gray-700">{valLabel(a.eur, a.pct)}</span>
					</span>
				</div>
			{/each}
		</div>
	{:else}
		{#snippet groupRowInner(g: any, open: boolean)}
			<span class="flex w-24 shrink-0 items-center gap-1.5 text-xs font-medium text-gray-600 sm:w-[170px]">
				{#if g.isGroup}
					<span class="shrink-0 text-[11px] text-gray-500 transition-transform {open ? 'rotate-90' : ''}">▸</span>
				{/if}
				<span class="truncate">{g.isGroup ? `${g.name} (${g.members.length})` : g.name}</span>
			</span>
			<span class="relative h-6 min-w-0 flex-1 overflow-hidden rounded-full {g.isGroup ? 'bg-teal-100' : 'bg-gray-100'}">
				<span class="block h-full rounded-full bg-teal-500" style="width:{Math.max(g.pct, 1).toFixed(1)}%"></span>
				<span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] font-semibold tabular-nums whitespace-nowrap text-gray-700">{valLabel(g.eur, g.pct)}</span>
			</span>
		{/snippet}
		<div class="flex flex-col gap-1.5">
			{#each groupRows as g (g.name)}
				{@const open = openGroup === g.name}
				<div>
					{#if g.isGroup}
						<button
							type="button"
							class="flex w-full cursor-pointer items-center gap-3 rounded-xl px-1.5 py-0.5 text-left hover:bg-gray-50"
							title="{g.name} — {trInt(g.rez)} rezervasyon · {g.members.length} acente"
							onclick={() => (openGroup = open ? null : g.name)}
						>{@render groupRowInner(g, open)}</button>
					{:else}
						<div
							class="flex w-full items-center gap-3 rounded-xl px-1.5 py-0.5 text-left"
							title="{g.name} — {trInt(g.rez)} rezervasyon"
						>{@render groupRowInner(g, open)}</div>
					{/if}
					{#if g.isGroup && open}
						<div class="flex flex-col gap-1 py-1.5">
							{#each g.members as m (m.name)}
								<div class="flex items-center gap-3 px-1.5" title="{m.name} — {trInt(m.rez)} rezervasyon">
									<span class="w-24 shrink-0 truncate pl-4 text-[11.5px] font-medium text-gray-500 sm:w-[170px]">{m.name}</span>
									<span class="relative h-4 min-w-0 flex-1 overflow-hidden rounded-full bg-gray-100">
										<span class="block h-full rounded-full bg-teal-300" style="width:{Math.max(m.pct, 1).toFixed(1)}%"></span>
										<span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10.5px] font-semibold tabular-nums whitespace-nowrap text-gray-500">{valLabel(m.eur, m.pct)}</span>
									</span>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if byAgency.length > 0}
		<div class="mt-3 flex items-center gap-3 border-t border-gray-200 pt-2.5">
			<span class="text-xs font-semibold text-gray-700">Toplam</span>
			<span class="flex-1"></span>
			<span class="text-[13px] font-bold tabular-nums text-teal-700">{eurCompact(totalEur)} · {trInt(totalRez)} rez.</span>
		</div>
		<p class="mt-3 text-xs leading-relaxed text-gray-500">
			Bar, acentenin seçili yıl toplam cirosundaki payını gösterir. Gruplu görünümde bir grup satırına tıklayarak üye acenteleri açabilirsiniz.
		</p>
	{/if}
</div>
