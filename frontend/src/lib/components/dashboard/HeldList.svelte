<!--
	HeldList.svelte — Bekleme Listesi (beklemeye alınmış / akım-dışı park edilmiş kalemler).

	Panel Nakit Akım kartının altında (Vadesi Geçenler'in hemen üstünde) gösterilir. Veri
	paylaşımlı `runway.svelte` deposundan (`data.held`). Beklemeye alınan kalem nakit akıma
	dahil edilmez (kolon toplamı/net/projeksiyon etkilenmez); burada sarı (amber) temayla
	AYRICA listelenir — kalem eski yerinde (giriş/çıkış listesinde) de sarı kalır. "Beklet"
	modu (option butonu) AÇIKKEN ve `finance.cash_flow` USE yetkisi varsa **her hareket tek tek**
	"geri al" ile bekletmeden çıkarılabilir (→ tekrar sayılan bekleyen listeye döner). Kapalıyken
	salt gösterim. Hiç bekleyen yoksa render edilmez. Vade geçince kalem otomatik Vadesi
	Geçenler'e, ödenince Gerçekleşen'e geçer.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { RotateCcw, ChevronDown, PauseCircle } from 'lucide-svelte';
	import {
		runwayStore, subscribeRunway, holdBatch,
		fmtEur, fmtNative, labelDate, cleanName, SRC_LABELS, type Flow, type SourceRef,
	} from '$lib/stores/runway.svelte';

	const canHold = hasPermission('finance.cash_flow', 'use');

	const data = $derived(runwayStore.data);
	const loading = $derived(runwayStore.loading);
	const holdMode = $derived(runwayStore.holdMode);
	let mutating = $state(false);
	let openGroups = $state<Record<string, boolean>>({});

	type Unit = { key: string; label: string; members: Flow[]; total: number };

	function parseRef(id: string): SourceRef {
		const i = id.lastIndexOf(':');
		return { source_type: id.slice(0, i), source_id: Number(id.slice(i + 1)) };
	}

	// Beklemedekiler: aynı başlık (kaynak türü) altında birleşir; tutara göre azalan sıralı.
	function groupByLabel(items: Flow[]): Unit[] {
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
			units.push({
				key: `hd:${key}`, label: SRC_LABELS[first.source_type ?? ''] ?? cleanName(first.name),
				members, total: members.reduce((s, m) => s + m.amount_eur, 0),
			});
		}
		return units.sort((a, b) => b.total - a.total);
	}

	const units = $derived(data?.held ? groupByLabel(data.held) : []);
	const total = $derived(data?.held ? data.held.reduce((s, o) => s + o.amount_eur, 0) : 0);

	// Bekletmeyi TEK bir hareket için kaldır (kullanıcı isteği 2026-07-07: "her hareket tek tek")
	async function unholdOne(m: Flow) {
		if (mutating || !canHold || !holdMode) return;
		mutating = true;
		try {
			await holdBatch([parseRef(m.id)], false);
			showToast('Bekletme kaldırıldı', 'success');
		} catch (err: any) {
			console.error('Bekletme kaldırma başarısız:', err);
			showToast(err?.message || 'İşlem başarısız', 'error');
		} finally {
			mutating = false;
		}
	}
	function toggleGroup(key: string) {
		openGroups[key] = !openGroups[key];
	}
</script>

{#if !loading && data && units.length > 0}
	<div class="mt-5 pt-5 border-t border-gray-200">
		<div class="flex items-center gap-2 text-[11px] tracking-[1px] uppercase text-amber-700 font-bold">
			<PauseCircle size={13} /> Bekleme Listesi · {fmtEur(total)}
		</div>
		<div class="mt-1.5 rounded-xl border border-amber-200 bg-amber-50/50 divide-y divide-amber-100">
			{#each units as u (u.key)}
				{@const multi = u.members.length > 1}
				<div class="px-2.5 py-2.5">
					<button type="button" onclick={() => toggleGroup(u.key)} aria-expanded={!!openGroups[u.key]}
						class="w-full flex items-center gap-1.5 text-left cursor-pointer">
						<ChevronDown size={14} class="shrink-0 text-amber-500 transition-transform {openGroups[u.key] ? '' : '-rotate-90'}" />
						<span class="text-[13px] sm:text-[13.5px] font-semibold truncate text-gray-900">{u.label}</span>
						{#if multi}<span class="text-[11px] text-amber-600 shrink-0">{u.members.length} kalem</span>{/if}
						<span class="ml-auto tabular-nums text-[13px] sm:text-[13.5px] font-semibold text-amber-700 shrink-0">{fmtEur(u.total)}</span>
					</button>
					{#if openGroups[u.key]}
						<div class="pl-5 pt-1.5 space-y-0.5">
							{#each u.members as m (m.id)}
								<div class="flex items-center gap-2 text-[12px] py-0.5">
									<span class="text-gray-700 truncate">{cleanName(m.name)}</span>
									<span class="text-[10px] text-amber-500 shrink-0">{labelDate(m.date)}</span>
									<span class="ml-auto tabular-nums text-gray-600 shrink-0">{m.currency ? fmtNative(m.amount_native ?? m.amount_eur, m.currency) : fmtEur(m.amount_eur)}</span>
									{#if canHold && holdMode}
										<button type="button" onclick={() => unholdOne(m)} disabled={mutating}
											aria-label="{cleanName(m.name)} bekletmeyi kaldır" title="Bu hareketi bekletmeden çıkar"
											class="touch-target shrink-0 flex items-center gap-1 rounded-md border border-amber-300 bg-white text-amber-700 px-2 py-1 text-[11px] font-medium hover:bg-amber-100 cursor-pointer disabled:opacity-50">
											<RotateCcw size={12} /> Geri al
										</button>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>
		<p class="text-[11px] text-gray-500 mt-2">
			Beklemeye alınan kalemler nakit akıma dahil edilmez (kolon toplamı/net/projeksiyon etkilenmez); listede sarı kalır. Vade geçince Vadesi Geçenler'e, ödenince Gerçekleşen'e geçer.
			{#if canHold && !holdMode}<span class="text-amber-700"> Geri almak için “Beklet” butonunu açın.</span>{/if}
		</p>
	</div>
{/if}
