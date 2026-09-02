<script lang="ts">
	import type { Snippet } from 'svelte';
	import { X } from 'lucide-svelte';

	let {
		count,
		onClear,
		children
	}: {
		count: number;
		onClear: () => void;
		children: Snippet;
	} = $props();
</script>

{#if count > 0}
	<div
		class="flex items-center justify-between gap-3 px-4 py-2.5 bg-teal-50 border border-teal-200 rounded-xl shadow-sm"
		role="toolbar"
		aria-label="Toplu işlem barı"
	>
		<div class="flex items-center gap-3">
			<button
				onclick={onClear}
				aria-label="Seçimi temizle"
				class="p-1 text-teal-700 hover:bg-teal-100 rounded-lg cursor-pointer transition-colors"
			>
				<X size={16} />
			</button>
			<span class="text-sm font-medium text-teal-800">
				{count} kayıt seçildi
			</span>
		</div>
		<div class="flex items-center gap-2 flex-wrap">
			{@render children()}
		</div>
	</div>
{/if}
