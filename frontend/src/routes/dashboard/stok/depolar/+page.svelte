<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { formatCurrency } from '$lib/utils/finance';
	import { Building2 } from 'lucide-svelte';

	let loading = $state(true);
	let items = $state<any[]>([]);

	let sorted = $derived([...items].sort((a, b) => b.consumption_total - a.consumption_total));
	let maxCons = $derived(Math.max(1, ...items.map((d) => d.consumption_total)));

	async function load() {
		loading = true;
		try {
			const r = await api.get<any>('/stok/depots');
			items = r.items || [];
		} catch (e) {
			console.error('Depolar yüklenemedi:', e);
		} finally {
			loading = false;
		}
	}
	onMount(load);
</script>

<svelte:head><title>Depolar · Sprenses</title></svelte:head>

<div class="space-y-4">
	<PageHeader title="Depolar / Departmanlar" description="Sedna depo/departman tanımları ve toplam tüketim maliyeti (maliyet merkezi)." />

	{#if loading}
		<TableSkeleton rows={8} columns={3} />
	{:else if items.length === 0}
		<EmptyState icon={Building2} title="Depo bulunamadı" message="Üst bardaki 'Sedna' butonuyla içe aktarın." />
	{:else}
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			<table class="w-full text-sm">
				<thead class="bg-gray-50 text-gray-500 text-xs uppercase">
					<tr>
						<th class="text-left font-medium px-4 py-2.5">Kod</th>
						<th class="text-left font-medium px-4 py-2.5">Departman / Depo</th>
						<th class="text-right font-medium px-4 py-2.5 w-1/2">Toplam Tüketim</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each sorted as d (d.id)}
						<tr class="hover:bg-gray-50/60">
							<td class="px-4 py-2.5 text-gray-500 text-xs tabular-nums">{d.code}</td>
							<td class="px-4 py-2.5 text-gray-800">{d.name}</td>
							<td class="px-4 py-2.5">
								<div class="flex items-center gap-3 justify-end">
									{#if d.consumption_total > 0}
										<div class="flex-1 max-w-[16rem] h-3 bg-gray-100 rounded-md overflow-hidden">
											<div class="h-full bg-amber-400 rounded-md" style="width: {(d.consumption_total / maxCons) * 100}%"></div>
										</div>
										<span class="w-28 text-right text-xs font-semibold text-gray-800 tabular-nums">{formatCurrency(d.consumption_total, 'TRY')}</span>
									{:else}
										<span class="text-xs text-gray-400">—</span>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
