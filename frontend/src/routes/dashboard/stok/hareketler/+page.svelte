<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { formatCurrency } from '$lib/utils/finance';
	import { ArrowRightLeft, Search, X } from 'lucide-svelte';

	const DIR_LABEL: Record<string, string> = { in: 'Alış', out: 'Çıkış', consume: 'Tüketim', count: 'Sayım', other: 'Diğer' };
	const DIR_CLASS: Record<string, string> = {
		in: 'bg-blue-50 text-blue-700', out: 'bg-gray-100 text-gray-600',
		consume: 'bg-amber-50 text-amber-700', count: 'bg-violet-50 text-violet-700', other: 'bg-gray-100 text-gray-500',
	};

	let loading = $state(true);
	let items = $state<any[]>([]);
	let total = $state(0);
	let page = $state(1);
	let pageSize = $state(50);
	let direction = $state('');

	let searchInput = $state('');
	let search = $state('');
	$effect(() => {
		const v = searchInput;
		const t = setTimeout(() => { search = v; page = 1; }, 300);
		return () => clearTimeout(t);
	});

	function fmtDate(d: string | null): string {
		if (!d) return '—';
		const [y, m, day] = d.split('-');
		return `${day}.${m}.${y}`;
	}

	async function load() {
		loading = true;
		try {
			const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
			if (direction) params.set('direction', direction);
			if (search.trim()) params.set('search', search.trim());
			const r = await api.get<any>(`/stok/movements?${params}`);
			items = r.items || [];
			total = r.total || 0;
		} catch (e) {
			console.error('Hareketler yüklenemedi:', e);
		} finally {
			loading = false;
		}
	}
	$effect(() => { void [page, pageSize, search, direction]; load(); });
	onMount(load);
</script>

<svelte:head><title>Stok Hareketleri · Sprenses</title></svelte:head>

<div class="space-y-4">
	<PageHeader title="Stok Hareketleri" description="Sedna stok giriş (alış) / çıkış / departman tüketim hareketleri." />

	<!-- Filtre barı -->
	<div class="flex flex-col sm:flex-row sm:items-center gap-3">
		<div class="relative flex-1 max-w-md">
			<Search size={16} class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
			<input type="text" bind:value={searchInput} placeholder="Ürün, tedarikçi veya belge no..."
				class="w-full pl-9 pr-9 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500" />
			{#if searchInput}
				<button onclick={() => (searchInput = '')} aria-label="Temizle" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-500 hover:text-gray-700 cursor-pointer"><X size={14} /></button>
			{/if}
		</div>
		<select bind:value={direction} onchange={() => (page = 1)} aria-label="Hareket tipi"
			class="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer sm:ml-auto">
			<option value="">Tüm Hareketler</option>
			<option value="in">Alış / Giriş</option>
			<option value="consume">Tüketim</option>
			<option value="out">Çıkış / Transfer</option>
			<option value="count">Sayım</option>
		</select>
		<span class="text-xs text-gray-500 tabular-nums">{total} hareket</span>
	</div>

	{#if loading}
		<TableSkeleton rows={8} columns={6} />
	{:else if items.length === 0}
		<EmptyState icon={ArrowRightLeft} title="Hareket bulunamadı" message="Filtre kriterine uygun stok hareketi yok." />
	{:else}
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-x-auto">
			<table class="w-full text-sm">
				<thead class="bg-gray-50 text-gray-500 text-xs uppercase">
					<tr>
						<th class="text-left font-medium px-3 py-2.5 whitespace-nowrap">Tarih</th>
						<th class="text-left font-medium px-3 py-2.5">Tip</th>
						<th class="text-left font-medium px-3 py-2.5">Ürün</th>
						<th class="text-right font-medium px-3 py-2.5">Miktar</th>
						<th class="text-right font-medium px-3 py-2.5">Tutar</th>
						<th class="text-left font-medium px-3 py-2.5">Tedarikçi / Depo</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each items as m (m.id)}
						<tr class="hover:bg-gray-50/60">
							<td class="px-3 py-2.5 text-gray-500 text-xs tabular-nums whitespace-nowrap">{fmtDate(m.date)}</td>
							<td class="px-3 py-2.5">
								<span class="text-[10px] px-1.5 py-0.5 rounded {DIR_CLASS[m.direction] || DIR_CLASS.other}">{m.type_label || DIR_LABEL[m.direction] || '—'}</span>
							</td>
							<td class="px-3 py-2.5 text-gray-800 truncate max-w-[16rem]" title={m.product_name}>{m.product_name || '—'}</td>
							<td class="px-3 py-2.5 text-right tabular-nums text-gray-600">{(m.quantity ?? 0).toLocaleString('tr-TR', { maximumFractionDigits: 2 })}</td>
							<td class="px-3 py-2.5 text-right tabular-nums font-medium text-gray-800">{formatCurrency(m.net_amount, 'TRY')}</td>
							<td class="px-3 py-2.5 text-gray-500 text-xs truncate max-w-[14rem]" title={m.supplier_name || m.cons_depot || ''}>{m.supplier_name || m.cons_depot || m.exit_depot || '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<Pagination {page} {pageSize} {total} onPageChange={(p) => (page = p)} onPageSizeChange={(s) => { pageSize = s; page = 1; }} />
	{/if}
</div>
