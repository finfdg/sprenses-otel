<script lang="ts">
	import { Loader2 } from 'lucide-svelte';

	let { show = false, message = 'Yükleniyor...' }: { show?: boolean; message?: string } = $props();
</script>

{#if show}
	<div class="absolute inset-0 z-10 bg-white/80 rounded-xl flex items-center justify-center">
		<div class="flex items-center gap-2 text-teal-700">
			<Loader2 size={20} class="animate-spin" />
			<span class="text-sm font-medium">{message}</span>
		</div>
	</div>
{/if}
