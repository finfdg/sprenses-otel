<script lang="ts" module>
	export type SortOrder = 'asc' | 'desc' | null;

	/**
	 * Sort cycle: inactive → asc → desc → temizle (inactive).
	 * Başka kolon aktifse → aktif kolon olur, asc başlar.
	 */
	export function getNextSort(
		column: string,
		activeKey: string | null,
		activeOrder: SortOrder
	): { key: string | null; order: SortOrder } {
		if (activeKey !== column) {
			return { key: column, order: 'asc' };
		}
		if (activeOrder === 'asc') return { key: column, order: 'desc' };
		if (activeOrder === 'desc') return { key: null, order: null };
		return { key: column, order: 'asc' };
	}
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import { ArrowUp, ArrowDown, ChevronsUpDown } from 'lucide-svelte';

	let {
		column,
		sortKey,
		sortOrder,
		onSort,
		children,
		align = 'left'
	}: {
		column: string;
		sortKey: string | null;
		sortOrder: SortOrder;
		onSort: (key: string | null, order: SortOrder) => void;
		children: Snippet;
		align?: 'left' | 'center' | 'right';
	} = $props();

	const isActive = $derived(sortKey === column);
	const alignClass = $derived(
		align === 'right' ? 'justify-end' : align === 'center' ? 'justify-center' : 'justify-start'
	);

	function handleClick() {
		const next = getNextSort(column, sortKey, sortOrder);
		onSort(next.key, next.order);
	}
</script>

<!--
	Not: aria-sort attribute'u <th> rolüyle kullanılır. Bu bileşeni saran parent
	<th>'ye istendiğinde aria-sort={sortOrder ?? 'none'} eklenebilir.
-->
<button
	type="button"
	onclick={handleClick}
	aria-label="{isActive
		? sortOrder === 'asc'
			? 'Sıralama: artan. Azalan için tıkla.'
			: 'Sıralama: azalan. Temizlemek için tıkla.'
		: 'Sıralamak için tıkla'}"
	data-sort-order={isActive ? sortOrder : 'none'}
	class="inline-flex items-center gap-1 w-full {alignClass} text-xs font-medium uppercase tracking-wider transition-colors cursor-pointer {isActive
		? 'text-teal-600'
		: 'text-gray-500 hover:text-gray-700'}"
>
	<span>{@render children()}</span>
	{#if isActive && sortOrder === 'asc'}
		<ArrowUp size={12} />
	{:else if isActive && sortOrder === 'desc'}
		<ArrowDown size={12} />
	{:else}
		<ChevronsUpDown size={12} class="opacity-40" />
	{/if}
</button>
