<script lang="ts" module>
	export type BreadcrumbItem = {
		label: string;
		href?: string;
	};
</script>

<script lang="ts">
	import { ChevronRight } from 'lucide-svelte';

	let {
		items
	}: {
		items: BreadcrumbItem[];
	} = $props();
</script>

{#if items.length > 0}
	<nav aria-label="Yol göstergesi" class="flex items-center gap-1 text-xs text-gray-500 mb-3">
		{#each items as item, i (i)}
			{#if i > 0}
				<ChevronRight size={12} class="text-gray-500 shrink-0" />
			{/if}
			{#if item.href && i < items.length - 1}
				<a
					href={item.href}
					class="hover:text-teal-600 transition-colors cursor-pointer truncate"
				>
					{item.label}
				</a>
			{:else}
				<span class="text-gray-700 font-medium truncate" aria-current={i === items.length - 1 ? 'page' : undefined}>
					{item.label}
				</span>
			{/if}
		{/each}
	</nav>
{/if}
