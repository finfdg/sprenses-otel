<script lang="ts">
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
		<div class="flex justify-center mb-3 text-gray-300">
			<IconComponent size={48} />
		</div>
	{/if}
	<h3 class="text-base font-semibold text-gray-700 mb-1">{title}</h3>
	{#if description}
		<p class="text-sm text-gray-500 mb-4 max-w-md mx-auto">{description}</p>
	{/if}
	{#if showCta}
		<button
			onclick={onCta}
			class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 transition-colors cursor-pointer"
		>
			{ctaText}
		</button>
	{/if}
</div>
