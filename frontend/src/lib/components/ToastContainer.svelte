<script lang="ts">
	import { toasts, removeToast } from '$lib/stores/toast.svelte';
</script>

{#if toasts.length > 0}
	<div class="fixed top-4 right-4 z-50 flex flex-col gap-3 max-w-sm w-full pointer-events-none">
		{#each toasts as toast (toast.id)}
			<div
				class="pointer-events-auto flex items-start gap-3 bg-white shadow-lg rounded-xl p-4 border-l-4 animate-slide-in
					{toast.type === 'success' ? 'border-l-green-500' : ''}
					{toast.type === 'error' ? 'border-l-red-500' : ''}
					{toast.type === 'warning' ? 'border-l-amber-500' : ''}
					{toast.type === 'info' ? 'border-l-blue-500' : ''}"
				role="alert"
			>
				<!-- İkon -->
				<div class="shrink-0 mt-0.5">
					{#if toast.type === 'success'}
						<div class="w-6 h-6 rounded-full bg-green-100 flex items-center justify-center">
							<svg class="w-4 h-4 text-green-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
							</svg>
						</div>
					{:else if toast.type === 'error'}
						<div class="w-6 h-6 rounded-full bg-red-100 flex items-center justify-center">
							<svg class="w-4 h-4 text-red-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</div>
					{:else if toast.type === 'warning'}
						<div class="w-6 h-6 rounded-full bg-amber-100 flex items-center justify-center">
							<span class="text-amber-600 text-sm font-bold leading-none">!</span>
						</div>
					{:else if toast.type === 'info'}
						<div class="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center">
							<span class="text-blue-600 text-sm font-bold leading-none">i</span>
						</div>
					{/if}
				</div>

				<!-- Mesaj -->
				<p class="flex-1 text-sm text-gray-700 leading-snug">{toast.message}</p>

				<!-- Kapat butonu -->
				<button
					onclick={() => removeToast(toast.id)}
					class="shrink-0 text-gray-300 hover:text-gray-500 transition-colors cursor-pointer"
					aria-label="Bildirimi kapat"
				>
					<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
		{/each}
	</div>
{/if}

<style>
	@keyframes slide-in {
		from {
			opacity: 0;
			transform: translateX(1rem);
		}
		to {
			opacity: 1;
			transform: translateX(0);
		}
	}

	.animate-slide-in {
		animation: slide-in 0.3s ease-out;
	}
</style>
