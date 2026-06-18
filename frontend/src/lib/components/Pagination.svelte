<script lang="ts" module>
	/**
	 * Görünür sayfa numaralarını hesaplar — windowed pagination.
	 * Her zaman 1 ve totalPages gösterilir, current ± 1 görünür, araya '...' konur.
	 *
	 * @example getPageNumbers(5, 10) → [1, '...', 4, 5, 6, '...', 10]
	 * @example getPageNumbers(1, 5)  → [1, 2, 3, 4, 5]
	 * @example getPageNumbers(2, 10) → [1, 2, 3, '...', 10]
	 */
	export function getPageNumbers(current: number, totalPages: number): (number | '...')[] {
		if (totalPages <= 0) return [];
		if (totalPages === 1) return [1];
		if (totalPages <= 7) {
			return Array.from({ length: totalPages }, (_, i) => i + 1);
		}
		const pages: (number | '...')[] = [1];
		const start = Math.max(2, current - 1);
		const end = Math.min(totalPages - 1, current + 1);
		if (start > 2) pages.push('...');
		for (let i = start; i <= end; i++) pages.push(i);
		if (end < totalPages - 1) pages.push('...');
		pages.push(totalPages);
		return pages;
	}

	export const DEFAULT_PAGE_SIZES = [25, 50, 100, 200];
</script>

<script lang="ts">
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';
	import Select from '$lib/components/Select.svelte';

	let {
		page,
		pageSize,
		total,
		pageSizes = DEFAULT_PAGE_SIZES,
		onPageChange,
		onPageSizeChange
	}: {
		page: number;
		pageSize: number;
		total: number;
		pageSizes?: number[];
		onPageChange: (page: number) => void;
		onPageSizeChange: (size: number) => void;
	} = $props();

	const totalPages = $derived(Math.max(1, Math.ceil(total / Math.max(1, pageSize))));
	const visibleNumbers = $derived(getPageNumbers(page, totalPages));
	const canPrev = $derived(page > 1);
	const canNext = $derived(page < totalPages);

	function go(p: number) {
		if (p < 1 || p > totalPages || p === page) return;
		onPageChange(p);
	}
</script>

<div class="flex flex-col sm:flex-row items-center justify-between gap-3 py-3 text-sm">
	<div class="flex items-center gap-2 text-gray-500">
		<span>Sayfa boyutu:</span>
		<Select
			size="sm"
			fullWidth={false}
			value={pageSize}
			onchange={(e) => onPageSizeChange(parseInt(e.currentTarget.value))}
		>
			{#each pageSizes as size (size)}
				<option value={size}>{size}</option>
			{/each}
		</Select>
		<span class="text-gray-500 hidden sm:inline">· Toplam {total}</span>
	</div>

	<div class="flex items-center gap-1">
		<button
			onclick={() => go(page - 1)}
			disabled={!canPrev}
			aria-label="Önceki sayfa"
			class="p-2 text-gray-500 rounded-lg hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
		>
			<ChevronLeft size={16} />
		</button>

		{#each visibleNumbers as n, i (`${n}-${i}`)}
			{#if n === '...'}
				<span class="px-2 text-gray-500">…</span>
			{:else}
				<button
					onclick={() => go(n)}
					aria-current={n === page ? 'page' : undefined}
					aria-label={`Sayfa ${n}`}
					class="min-w-[2rem] h-8 px-2 rounded-lg text-sm cursor-pointer transition-colors {n === page
						? 'bg-teal-700 text-white font-medium'
						: 'text-gray-600 hover:bg-gray-100'}"
				>
					{n}
				</button>
			{/if}
		{/each}

		<button
			onclick={() => go(page + 1)}
			disabled={!canNext}
			aria-label="Sonraki sayfa"
			class="p-2 text-gray-500 rounded-lg hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
		>
			<ChevronRight size={16} />
		</button>
	</div>
</div>
