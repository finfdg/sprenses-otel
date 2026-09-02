<script lang="ts">
	let {
		fields = 4,
		showSubmit = true
	}: {
		fields?: number;
		showSubmit?: boolean;
	} = $props();

	const fieldArr = $derived(Array.from({ length: Math.max(1, fields) }, (_, i) => i));
</script>

<div class="space-y-4" role="status" aria-label="Form yükleniyor">
	{#each fieldArr as i (`f-${i}`)}
		<div class="space-y-2">
			<div class="h-3 bg-gray-200 rounded animate-pulse w-24"></div>
			<div class="h-10 bg-gray-100 rounded-lg animate-pulse"></div>
		</div>
	{/each}
	{#if showSubmit}
		<div class="flex justify-end gap-2 pt-2">
			<div class="h-10 w-20 bg-gray-100 rounded-lg animate-pulse"></div>
			<div class="h-10 w-24 bg-gray-200 rounded-lg animate-pulse"></div>
		</div>
	{/if}
	<span class="sr-only">Yükleniyor...</span>
</div>
