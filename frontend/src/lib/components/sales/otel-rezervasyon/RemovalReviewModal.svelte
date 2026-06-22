<script lang="ts">
	import type { RemovalCandidate } from '$lib/types/reservation';
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';
	import { Trash2 } from 'lucide-svelte';

	let {
		show = $bindable(),
		candidates,
		selectedIds = $bindable(),
		selectedTotalEur,
		bulkDeleting,
		onRequestDelete,
	}: {
		show: boolean;
		candidates: RemovalCandidate[];
		selectedIds: Set<number>;
		selectedTotalEur: number;
		bulkDeleting: boolean;
		onRequestDelete: () => void;
	} = $props();

	function toggleRemoval(id: number) {
		const next = new Set(selectedIds);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedIds = next;
	}

	function toggleAllRemovals() {
		if (selectedIds.size === candidates.length) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(candidates.map((c) => c.id));
		}
	}

	function formatEur(n: number, withCurrency = true): string {
		if (n == null || isNaN(n)) return '-';
		const formatted = new Intl.NumberFormat('tr-TR', {
			minimumFractionDigits: 0,
			maximumFractionDigits: 0,
		}).format(Math.round(n));
		return withCurrency ? `${formatted} €` : formatted;
	}
	function formatInt(n: number): string {
		if (n == null || isNaN(n)) return '-';
		return new Intl.NumberFormat('tr-TR').format(n);
	}
	function formatRangeDate(iso: string): string {
		// 2026-05-16 → 16.05
		const [, m, d] = iso.split('-');
		return `${d}.${m}`;
	}
</script>

<!-- ── Silme Adayları İnceleme Modalı ── -->
<Modal bind:show title="Kaynakta Olmayan Rezervasyonlar" maxWidth="max-w-5xl">
	<div class="space-y-3 text-sm">
		<div class="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 leading-snug">
			Aşağıdaki <strong>{formatInt(candidates.length)}</strong> kayıt yüklemenin
			kapsamı içinde olduğu halde son Excel'de bulunmuyor. Silmek istemediklerinizin
			işaretini kaldırın. <strong>Silme işlemi geri alınamaz</strong> — yine de audit
			loglarında detay saklanır.
		</div>

		<div class="flex items-center justify-between gap-2 flex-wrap">
			<label class="inline-flex items-center gap-2 cursor-pointer select-none">
				<input
					type="checkbox"
					checked={selectedIds.size === candidates.length && candidates.length > 0}
					indeterminate={selectedIds.size > 0 && selectedIds.size < candidates.length}
					onchange={toggleAllRemovals}
					class="w-4 h-4 rounded border-gray-300 text-rose-600 focus:ring-rose-500"
				/>
				<span class="text-xs text-gray-700 font-medium">
					{selectedIds.size} / {candidates.length} seçili
				</span>
			</label>
			<div class="text-xs text-gray-600 tabular-nums">
				Seçilen toplam: <strong class="text-rose-700">{formatEur(selectedTotalEur)}</strong>
			</div>
		</div>

		<div class="max-h-[55vh] overflow-y-auto border border-gray-200 rounded-lg">
			<table class="w-full text-xs">
				<thead class="bg-gray-50 sticky top-0 z-10">
					<tr class="text-gray-600 uppercase">
						<th class="text-left py-2 px-2 w-10"></th>
						<th class="text-left py-2 px-2">Acente</th>
						<th class="text-left py-2 px-2 hidden sm:table-cell">Oda Tipi</th>
						<th class="text-left py-2 px-2 hidden md:table-cell">Misafir</th>
						<th class="text-left py-2 px-2">Tarih</th>
						<th class="text-right py-2 px-2">Oda</th>
						<th class="text-right py-2 px-2">EUR</th>
					</tr>
				</thead>
				<tbody>
					{#each candidates as c (c.id)}
						{@const checked = selectedIds.has(c.id)}
						<tr
							class="border-t border-gray-100 hover:bg-rose-50/40 cursor-pointer"
							class:bg-rose-50={checked}
							onclick={() => toggleRemoval(c.id)}
						>
							<td class="py-1.5 px-2">
								<input
									type="checkbox"
									{checked}
									onclick={(e) => e.stopPropagation()}
									onchange={() => toggleRemoval(c.id)}
									class="w-4 h-4 rounded border-gray-300 text-rose-600 focus:ring-rose-500"
								/>
							</td>
							<td class="py-1.5 px-2 text-gray-900 truncate max-w-[140px]" title={c.agency ?? ''}>
								{c.agency ?? '-'}
							</td>
							<td class="py-1.5 px-2 text-gray-700 hidden sm:table-cell">{c.room_type ?? '-'}</td>
							<td class="py-1.5 px-2 text-gray-600 hidden md:table-cell truncate max-w-[160px]" title={c.guests ?? ''}>
								{c.guests ?? '-'}
							</td>
							<td class="py-1.5 px-2 text-gray-700 whitespace-nowrap">
								{formatRangeDate(c.checkin_date)} → {formatRangeDate(c.checkout_date)}
								<span class="text-gray-500 ml-1">({c.nights}n)</span>
							</td>
							<td class="py-1.5 px-2 text-right tabular-nums">{c.rooms}</td>
							<td class="py-1.5 px-2 text-right tabular-nums text-rose-700">{formatEur(c.eur_total)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div class="flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
			<Button variant="secondary" onclick={() => (show = false)}>Vazgeç</Button>
			<Button variant="danger" onclick={onRequestDelete} loading={bulkDeleting} disabled={selectedIds.size === 0 || bulkDeleting}>
				{#if !bulkDeleting}<Trash2 size={14} />{/if}
				Seçilenleri Sil ({selectedIds.size})
			</Button>
		</div>
	</div>
</Modal>
