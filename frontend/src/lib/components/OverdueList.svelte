<!--
	OverdueList.svelte — Vadesi Geçenler (ödenmemiş, vadesi geçmiş kalemler).

	Panel Nakit Akım kartının EN ALTINDA gösterilir (kullanıcı isteği 2026-07-06). Veri
	paylaşımlı `runway.svelte` deposundan (grafikle ortak tek fetch). Aynı kaynak türü (Cari
	Ödemeleri vb.) tek başlıkta birleşir; açılan detayda tarih alt-başlığı altında listelenir.
	`finance.cash_flow` USE yetkisi olan tarih seçerek kalemi KALICI öteler. Hiç vadesi geçen
	yoksa hiçbir şey render edilmez. Eski NakitKoruma'dan ayrılan parça.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { RotateCcw, ChevronDown, AlertTriangle } from 'lucide-svelte';
	import {
		runwayStore, subscribeRunway, deferBatch,
		fmtEur, fmtNative, labelDate, cleanName, SRC_LABELS, type Flow,
	} from '$lib/stores/runway.svelte';

	// Öteleme yalnız finance.cash_flow KULLANIM yetkisi olanlara açık
	const canDefer = hasPermission('finance.cash_flow', 'use');

	const data = $derived(runwayStore.data);
	const loading = $derived(runwayStore.loading);
	let mutating = $state(false);
	let openGroups = $state<Record<string, boolean>>({});

	type Unit = { key: string; label: string; day: string; members: Flow[]; deferIds: string[]; deferrable: boolean; total: number; deferred: boolean };

	// Vadesi geçenler: aynı başlık (kaynak türü) altındaki TÜM tarihler tek grupta birleşir;
	// açılan detayda tarih alt-başlığı altında listelenir. Tutara göre azalan sıralı.
	function groupOverdueByLabel(items: Flow[]): Unit[] {
		const map = new Map<string, Flow[]>();
		for (const o of items) {
			const key = o.source_type ?? 'other';
			const arr = map.get(key);
			if (arr) arr.push(o); else map.set(key, [o]);
		}
		const units: Unit[] = [];
		for (const [key, membersRaw] of map) {
			const members = membersRaw.slice().sort((a, b) => a.date.localeCompare(b.date));
			const first = members[0];
			const deferIds = members.filter((m) => !m.projected).map((m) => m.id);
			units.push({
				key: `od:${key}`, label: SRC_LABELS[first.source_type ?? ''] ?? cleanName(first.name),
				day: first.date, members, deferIds, deferrable: deferIds.length > 0,
				total: members.reduce((s, m) => s + m.amount_eur, 0),
				deferred: members.some((m) => m.deferred),
			});
		}
		return units.sort((a, b) => b.total - a.total);
	}

	// Açılan grubun kalemlerini tarih alt-başlığı altında grupla (members tarih sıralı gelir)
	function groupMembersByDate(items: Flow[]): { date: string; label: string; items: Flow[] }[] {
		const out: { date: string; label: string; items: Flow[] }[] = [];
		let cur: { date: string; label: string; items: Flow[] } | null = null;
		for (const it of items) {
			if (!cur || cur.date !== it.date) {
				cur = { date: it.date, label: labelDate(it.date), items: [] };
				out.push(cur);
			}
			cur.items.push(it);
		}
		return out;
	}

	const units = $derived(data ? groupOverdueByLabel(data.overdue) : []);
	const total = $derived(data ? data.overdue.reduce((s, o) => s + o.amount_eur, 0) : 0);

	async function mutateGroup(memberIds: string[], deferredTo: string | null, okMsg: string) {
		if (mutating) return;
		mutating = true;
		try {
			await deferBatch(memberIds, deferredTo);
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
	function toggleGroup(key: string) {
		openGroups[key] = !openGroups[key];
	}

	onMount(() => subscribeRunway());
</script>

{#if !loading && data && units.length > 0}
	<div class="mt-5 pt-5 border-t border-gray-200">
		<div class="flex items-center gap-2 text-[11px] tracking-[1px] uppercase text-red-700 font-bold">
			<AlertTriangle size={13} /> Vadesi Geçenler · {fmtEur(total)}
		</div>
		<div class="mt-1.5 rounded-xl border border-red-200 bg-red-50/40 divide-y divide-red-100">
			{#each units as u (u.key)}
				{@const multi = u.members.length > 1}
				<div class="px-2.5 py-2.5">
					<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5 sm:gap-x-3">
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
						<div class="pl-5 pt-1.5">
							{#each groupMembersByDate(u.members) as day (day.date)}
								<div class="pt-1.5 pb-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-400">{day.label}</div>
								{#each day.items as m (m.id)}
									<div class="flex items-center gap-2 text-[12px] py-0.5">
										<span class="text-gray-700 truncate">{cleanName(m.name)}</span>
										<span class="ml-auto tabular-nums text-gray-600 shrink-0">−{m.amount_native != null ? fmtNative(m.amount_native, m.currency) : fmtEur(m.amount_eur)}</span>
									</div>
								{/each}
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>
		{#if canDefer}
			<p class="text-[11px] text-gray-500 mt-2">Tarih seçerek bir kalemi ileri tarihe <strong>kalıcı</strong> ötelersiniz (borç kalkmaz, vade değişir).</p>
		{/if}
	</div>
{/if}
