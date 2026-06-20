<script lang="ts">
	import Button from '$lib/components/Button.svelte';
	// Icon: herhangi bir Svelte bileşeni (tipik: lucide-svelte ikonu).
	// Tip kontrolünü gevşetiyoruz ki Lucide'ın kendi Component tipleri uyumsuzluk yaratmasın.
	let {
		title = 'Henüz kayıt yok',
		description = '',
		icon = null,
		ctaText = '',
		onCta = null
	}: {
		title?: string;
		description?: string;
		icon?: any;
		ctaText?: string;
		onCta?: (() => void) | null;
	} = $props();

	const IconComponent = $derived(icon);
	const showCta = $derived(Boolean(ctaText && onCta));
</script>

<div class="bg-white border border-gray-200 rounded-2xl p-8 text-center shadow-sm">
	{#if IconComponent}
		<div class="flex justify-center mb-3 text-gray-500">
			<IconComponent size={48} />
		</div>
	{/if}
	<h3 class="text-base font-semibold text-gray-700 mb-1">{title}</h3>
	{#if description}
		<p class="text-sm text-gray-500 mb-4 max-w-md mx-auto">{description}</p>
	{/if}
	{#if showCta}
		<Button onclick={onCta ?? undefined}>{ctaText}</Button>
	{/if}
</div>
