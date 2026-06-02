<script lang="ts">
	let {
		rows = 5,
		columns = 4,
		showHeader = true
	}: {
		rows?: number;
		columns?: number;
		showHeader?: boolean;
	} = $props();

	const rowArr = $derived(Array.from({ length: Math.max(1, rows) }, (_, i) => i));
	const colArr = $derived(Array.from({ length: Math.max(1, columns) }, (_, i) => i));
</script>

<div class="bg-white border border-gray-200 rounded-2xl p-4 md:p-6 shadow-sm" role="status" aria-label="Yükleniyor">
	{#if showHeader}
		<div class="flex gap-4 mb-4 pb-3 border-b border-gray-100">
			{#each colArr as i (`h-${i}`)}
				<div class="h-3 bg-gray-200 rounded animate-pulse flex-1"></div>
			{/each}
		</div>
	{/if}
	{#each rowArr as r (`r-${r}`)}
		<div class="flex gap-4 py-3 border-b border-gray-100 last:border-0">
			{#each colArr as c (`r${r}-c${c}`)}
				<div class="h-4 bg-gray-100 rounded animate-pulse flex-1"></div>
			{/each}
		</div>
	{/each}
	<span class="sr-only">Yükleniyor...</span>
</div>
