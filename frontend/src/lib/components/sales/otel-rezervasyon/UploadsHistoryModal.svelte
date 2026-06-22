<script lang="ts">
	import type { UploadHistory } from '$lib/types/reservation';
	import Modal from '$lib/components/Modal.svelte';
	import { Trash2 } from 'lucide-svelte';

	let {
		show = $bindable(),
		uploads,
		canUse,
		onDelete,
	}: {
		show: boolean;
		uploads: UploadHistory[];
		canUse: boolean;
		onDelete: (u: UploadHistory) => void;
	} = $props();

	function formatInt(n: number): string {
		if (n == null || isNaN(n)) return '-';
		return new Intl.NumberFormat('tr-TR').format(n);
	}
	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		const d = new Date(iso);
		return new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(d);
	}
</script>

<!-- ── Yüklemeler Geçmişi Modal ── -->
<Modal bind:show title="Yükleme Geçmişi" maxWidth="max-w-3xl">
	{#if uploads.length === 0}
		<p class="text-sm text-gray-500 text-center py-6">Henüz yükleme yok.</p>
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="text-xs text-gray-500 uppercase border-b border-gray-100">
						<th class="text-left py-2 px-2">Tarih</th>
						<th class="text-left py-2 px-2">Dosya</th>
						<th class="text-left py-2 px-2 hidden sm:table-cell">Otel</th>
						<th class="text-right py-2 px-2">Toplam</th>
						<th class="text-right py-2 px-2">Yeni</th>
						<th class="text-right py-2 px-2">Güncelle</th>
						<th class="text-left py-2 px-2 hidden md:table-cell">Yükleyen</th>
						{#if canUse}
							<th class="text-right py-2 px-2"></th>
						{/if}
					</tr>
				</thead>
				<tbody>
					{#each uploads as u (u.id)}
						<tr class="border-b border-gray-50 hover:bg-gray-50/50">
							<td class="py-2 px-2 text-xs text-gray-600 whitespace-nowrap">{formatDate(u.uploaded_at)}</td>
							<td class="py-2 px-2 text-xs text-gray-900 truncate max-w-[180px]" title={u.file_name}>{u.file_name}</td>
							<td class="py-2 px-2 text-xs text-gray-600 hidden sm:table-cell truncate max-w-[140px]">{u.hotel_name ?? '-'}</td>
							<td class="py-2 px-2 text-right tabular-nums">{formatInt(u.total_rows)}</td>
							<td class="py-2 px-2 text-right tabular-nums text-emerald-700">{formatInt(u.new_rows)}</td>
							<td class="py-2 px-2 text-right tabular-nums text-amber-700">{formatInt(u.updated_rows)}</td>
							<td class="py-2 px-2 text-xs text-gray-500 hidden md:table-cell">{u.uploader_name ?? '-'}</td>
							{#if canUse}
								<td class="py-2 px-2 text-right">
									<button
										onclick={() => onDelete(u)}
										class="p-1.5 rounded text-red-600 hover:bg-red-50"
										title="Sil"
									>
										<Trash2 size={14} />
									</button>
								</td>
							{/if}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</Modal>
