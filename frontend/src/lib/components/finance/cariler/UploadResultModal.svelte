<script lang="ts">
	import type { VendorUploadResult } from '$lib/types/vendor';
	import { formatCurrency } from '$lib/utils/finance';
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';

	let {
		show = $bindable(),
		result,
		selectedIds = $bindable(),
		bulkDeleting,
		canUse,
		onConfirmDelete,
		onSkip,
	}: {
		show: boolean;
		result: VendorUploadResult | null;
		selectedIds: Set<number>;
		bulkDeleting: boolean;
		canUse: boolean;
		onConfirmDelete: () => void;
		onSkip: () => void;
	} = $props();

	function toggleSelection(id: number) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedIds = next;
	}

	function toggleAll() {
		if (!result) return;
		if (selectedIds.size === result.removal_candidates.length) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(result.removal_candidates.map(c => c.id));
		}
	}

	function formatDate(dateStr: string): string {
		const d = new Date(dateStr);
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}
</script>

<!-- Upload Result Modal -->
<Modal bind:show title="Yükleme Sonucu" maxWidth={result && result.removal_candidates.length > 0 ? 'max-w-4xl' : 'max-w-md'}>
	{#if result}
		<div class="space-y-4 py-2">
			<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
				<div class="bg-gray-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-gray-900">{result.total_vendors}</p>
					<p class="text-xs text-gray-500 mt-1">Cari</p>
				</div>
				<div class="bg-gray-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-gray-900">{result.total_transactions}</p>
					<p class="text-xs text-gray-500 mt-1">Toplam İşlem</p>
				</div>
				<div class="bg-emerald-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-emerald-600">{result.new_transactions}</p>
					<p class="text-xs text-gray-500 mt-1">Yeni</p>
				</div>
				<div class="bg-amber-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-amber-600">{result.skipped_transactions}</p>
					<p class="text-xs text-gray-500 mt-1">Mükerrer</p>
				</div>
			</div>

			{#if result.removal_candidates.length > 0}
				<div class="border border-red-200 rounded-xl bg-red-50 p-4 space-y-3">
					<div class="flex items-start gap-3">
						<div class="flex-shrink-0 w-8 h-8 rounded-full bg-red-100 flex items-center justify-center text-red-600 font-bold">!</div>
						<div class="flex-1">
							<h3 class="text-sm font-semibold text-red-900">Kaynakta Bulunmayan Kayıtlar</h3>
							<p class="text-xs text-red-700 mt-1">
								Aşağıdaki <strong>{result.removal_candidates.length}</strong> kayıt yüklediğiniz Excel'in kapsamında (cari + tarih aralığı) olduğu halde dosyada bulunamadı. Kaynakta silindiyse bunları DB'den de silebilirsiniz. Banka/çek eşleşmesi olan veya departmana atanmış kayıtlar bu listeye dahil edilmedi.
							</p>
						</div>
					</div>

					<div class="bg-white rounded-lg border border-red-100 overflow-hidden">
						<div class="max-h-80 overflow-y-auto">
							<table class="w-full text-xs">
								<thead class="bg-gray-50 sticky top-0 z-10">
									<tr class="border-b border-gray-200">
										<th class="px-2 py-2 text-left w-8">
											<input
												type="checkbox"
												checked={selectedIds.size === result.removal_candidates.length && result.removal_candidates.length > 0}
												onchange={toggleAll}
												class="rounded border-gray-300 text-teal-600 focus:ring-teal-500"
											/>
										</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Cari</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Tarih</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Evrak No</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Tip</th>
										<th class="px-2 py-2 text-right font-medium text-gray-600">Borç</th>
										<th class="px-2 py-2 text-right font-medium text-gray-600">Alacak</th>
									</tr>
								</thead>
								<tbody>
									{#each result.removal_candidates as c (c.id)}
										<tr class="border-b border-gray-100 hover:bg-gray-50 cursor-pointer" onclick={() => toggleSelection(c.id)}>
											<td class="px-2 py-2">
												<input
													type="checkbox"
													checked={selectedIds.has(c.id)}
													onclick={(e) => e.stopPropagation()}
													onchange={() => toggleSelection(c.id)}
													class="rounded border-gray-300 text-teal-600 focus:ring-teal-500"
												/>
											</td>
											<td class="px-2 py-2 text-gray-900 max-w-[180px] truncate" title={c.hesap_adi}>{c.hesap_adi}</td>
											<td class="px-2 py-2 text-gray-700 whitespace-nowrap">{formatDate(c.date)}</td>
											<td class="px-2 py-2 text-gray-700 whitespace-nowrap">{c.evrak_no || '—'}</td>
											<td class="px-2 py-2 text-gray-600 max-w-[140px] truncate" title={c.transaction_type || ''}>{c.transaction_type || '—'}</td>
											<td class="px-2 py-2 text-right whitespace-nowrap {c.borc > 0 ? 'text-emerald-700' : 'text-gray-500'}">{c.borc > 0 ? formatCurrency(c.borc) : '—'}</td>
											<td class="px-2 py-2 text-right whitespace-nowrap {c.alacak > 0 ? 'text-red-700' : 'text-gray-500'}">{c.alacak > 0 ? formatCurrency(c.alacak) : '—'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>

					<div class="flex items-center justify-between text-xs text-red-700">
						<span>{selectedIds.size} / {result.removal_candidates.length} seçili</span>
						<button
							onclick={toggleAll}
							class="font-medium hover:underline"
						>
							{selectedIds.size === result.removal_candidates.length ? 'Hiçbirini seçme' : 'Hepsini seç'}
						</button>
					</div>
				</div>

				<div class="flex items-center justify-end gap-3">
					<Button variant="secondary" onclick={onSkip} disabled={bulkDeleting}>Atla / Hiçbirini silme</Button>
					<Button variant="danger" onclick={onConfirmDelete} loading={bulkDeleting} disabled={bulkDeleting || selectedIds.size === 0 || !canUse}>{bulkDeleting ? 'Siliniyor...' : `Seçilenleri Sil (${selectedIds.size})`}</Button>
				</div>
			{:else}
				<Button fullWidth onclick={() => { show = false; }}>Tamam</Button>
			{/if}
		</div>
	{/if}
</Modal>
