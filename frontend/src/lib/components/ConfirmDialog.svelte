<script lang="ts">
	import { focusTrap } from '$lib/utils/focus-trap';
	import Button from '$lib/components/Button.svelte';

	let {
		show = $bindable(false),
		title = 'Onay',
		message = '',
		confirmText = 'Evet',
		cancelText = 'İptal',
		danger = false,
		onConfirm,
		onCancel,
	}: {
		show: boolean;
		title?: string;
		message: string;
		confirmText?: string;
		cancelText?: string;
		danger?: boolean;
		onConfirm: () => void;
		onCancel?: () => void;
	} = $props();

	function handleConfirm() {
		show = false;
		onConfirm();
	}

	function handleCancel() {
		show = false;
		onCancel?.();
	}
</script>

{#if show}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/40 flex items-center justify-center z-[60] p-4"
		onclick={handleCancel}
		onkeydown={(e) => { if (e.key === 'Escape') handleCancel(); }}
		role="dialog"
		aria-modal="true"
		aria-label={title}
		tabindex="-1"
		use:focusTrap
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="bg-white rounded-2xl w-full max-w-sm shadow-xl overflow-hidden" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<div class="px-5 pt-5 pb-2">
				<h3 class="text-lg font-bold text-gray-900">{title}</h3>
				<p class="text-sm text-gray-500 mt-2">{message}</p>
			</div>
			<div class="px-5 py-4 flex gap-2">
				<Button variant="secondary" class="flex-1" onclick={handleCancel}>{cancelText}</Button>
				<Button variant={danger ? 'danger' : 'primary'} class="flex-1" onclick={handleConfirm}>{confirmText}</Button>
			</div>
		</div>
	</div>
{/if}
