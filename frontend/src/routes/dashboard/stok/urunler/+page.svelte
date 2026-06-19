<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import Input from '$lib/components/Input.svelte';
	import { formatCurrency } from '$lib/utils/finance';
	import { Boxes, Search } from 'lucide-svelte';

	let loading = $state(true);
	let items = $state<any[]>([]);
	let total = $state(0);
	let page = $state(1);
	let pageSize = $state(50);
	let inStock = $state(true);

	let searchInput = $state('');
	let search = $state('');
	$effect(() => {
		const v = searchInput;
		const t = setTimeout(() => { search = v; page = 1; }, 300);
		return () => clearTimeout(t);
	});

	async function load() {
		loading = true;
		try {
			const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
			if (search.trim()) params.set('search', search.trim());
			if (inStock) params.set('in_stock', 'true');
			const r = await api.get<any>(`/stok/products?${params}`);
			items = r.items || [];
			total = r.total || 0;
		} catch (e) {
			console.error('Ürünler yüklenemedi:', e);
		} finally {
			loading = false;
		}
	}
	$effect(() => { void [page, pageSize, search, inStock]; load(); });
	onMount(load);
</script>

<svelte:head><title>Ürünler & Stok · Sprenses</title></svelte:head>

<div class="space-y-4">
	<PageHeader title="Ürünler & Stok" description="Sedna ürün kartları ve anlık stok değeri (qty × son maliyet)." />

	<!-- Filtre barı -->
	<div class="flex flex-col sm:flex-row sm:items-center gap-3">
		<Input type="search" icon={Search} clearable bind:value={searchInput} placeholder="Ürün adı veya koduna göre ara..."
			size="sm" fullWidth={false} class="flex-1 max-w-md" />
		<label class="inline-flex items-center gap-2 text-sm text-gray-600 cursor-pointer sm:ml-auto">
			<input type="checkbox" bind:checked={inStock} class="w-4 h-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500 cursor-pointer" />
			Sadece stokta olanlar
		</label>
		<span class="text-xs text-gray-500 tabular-nums">{total} ürün</span>
	</div>

	{#if loading}
		<TableSkeleton rows={8} columns={5} />
	{:else if items.length === 0}
		<EmptyState icon={Boxes} title="Ürün bulunamadı" description="Arama/filtre kriterine uygun ürün yok." />
	{:else}
		<!-- Masaüstü: tablo -->
		<div class="hidden sm:block bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			<table class="w-full text-sm">
				<thead class="bg-gray-50 text-gray-500 text-xs uppercase">
					<tr>
						<th class="text-left font-medium px-4 py-2.5">Kod</th>
						<th class="text-left font-medium px-4 py-2.5">Ürün</th>
						<th class="text-right font-medium px-4 py-2.5">Stok</th>
						<th class="text-right font-medium px-4 py-2.5">Birim Maliyet</th>
						<th class="text-right font-medium px-4 py-2.5">Değer</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each items as p (p.id)}
						<tr class="hover:bg-gray-50/60">
							<td class="px-4 py-2.5 text-gray-500 text-xs tabular-nums">{p.code || '—'}</td>
							<td class="px-4 py-2.5 text-gray-800 truncate max-w-[20rem]" title={p.name}>{p.name}</td>
							<td class="px-4 py-2.5 text-right tabular-nums {p.current_stock > 0 ? 'text-gray-800' : 'text-gray-400'}">{p.current_stock.toLocaleString('tr-TR', { maximumFractionDigits: 2 })}</td>
							<td class="px-4 py-2.5 text-right tabular-nums text-gray-500">{formatCurrency(p.last_cost, p.currency)}</td>
							<td class="px-4 py-2.5 text-right tabular-nums font-semibold text-gray-800">{formatCurrency(p.current_value, 'TRY')}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Mobil: kart görünümü -->
		<div class="sm:hidden space-y-2">
			{#each items as p (p.id)}
				<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3">
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0">
							<div class="text-sm font-medium text-gray-800 truncate" title={p.name}>{p.name}</div>
							<div class="text-xs text-gray-500 tabular-nums">{p.code || '—'}</div>
						</div>
						<span class="text-sm font-semibold text-gray-800 tabular-nums shrink-0">{formatCurrency(p.current_value, 'TRY')}</span>
					</div>
					<div class="mt-2 flex items-center justify-between text-xs">
						<span class="text-gray-500">Stok: <span class="tabular-nums {p.current_stock > 0 ? 'text-gray-800' : 'text-gray-400'}">{p.current_stock.toLocaleString('tr-TR', { maximumFractionDigits: 2 })}</span></span>
						<span class="text-gray-500 tabular-nums">Birim: {formatCurrency(p.last_cost, p.currency)}</span>
					</div>
				</div>
			{/each}
		</div>
		<Pagination {page} {pageSize} {total} onPageChange={(p) => (page = p)} onPageSizeChange={(s) => { pageSize = s; page = 1; }} />
	{/if}
</div>
