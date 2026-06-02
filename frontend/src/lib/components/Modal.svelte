<script lang="ts">
	import type { Snippet } from 'svelte';
	import { focusTrap } from '$lib/utils/focus-trap';

	let { show = $bindable(false), title = '', maxWidth = 'max-w-lg', onclose, children }: {
		show: boolean;
		title: string;
		maxWidth?: string;
		onclose?: () => void;
		children: Snippet;
	} = $props();

	function handleClose() {
		show = false;
		onclose?.();
	}

	function handleBackdrop(e: MouseEvent) {
		if (e.target === e.currentTarget) handleClose();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') handleClose();
	}
</script>

{#if show}
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
	onclick={handleBackdrop}
	onkeydown={handleKeydown}
	role="dialog"
	aria-modal="true"
	aria-label={title}
	tabindex="-1"
	use:focusTrap
>
	<div class="bg-white rounded-2xl shadow-xl w-full {maxWidth} max-h-[90vh] overflow-y-auto">
		<div class="flex items-center justify-between p-4 sm:p-5 border-b border-gray-200">
			<h2 class="text-base sm:text-lg font-bold text-gray-800">{title}</h2>
			<button onclick={handleClose} class="text-gray-400 hover:text-gray-600 text-xl cursor-pointer touch-target w-11 h-11 -mr-2 flex items-center justify-center rounded-lg hover:bg-gray-100 transition-colors" aria-label="Kapat">&times;</button>
		</div>
		<div class="p-4 sm:p-5">
			{@render children()}
		</div>
	</div>
</div>
{/if}
