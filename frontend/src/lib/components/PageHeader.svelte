<!--
	PageHeader.svelte — Tutarlı sayfa başlığı (tasarım sistemi primitive'i).

	Neden: 19 sayfada hiç <h1> yoktu, olanlar font-bold/font-semibold arasında
	çatallıydı. Bu bileşen her sayfaya aynı başlık yapısını verir.

	Kullanım:
		<PageHeader title="Alınan Avanslar" description="...">
			{#snippet actions()}
				<Button onclick={openAdd}><Plus size={16} /> Yeni Avans</Button>
			{/snippet}
		</PageHeader>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		description = undefined,
		actions = undefined,
	}: {
		title: string;
		description?: string;
		actions?: Snippet;
	} = $props();
</script>

<div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
	<div class="min-w-0">
		<h1 class="text-xl sm:text-2xl font-semibold text-gray-900">{title}</h1>
		{#if description}
			<p class="text-sm text-gray-500 mt-1">{description}</p>
		{/if}
	</div>
	{#if actions}
		<div class="flex items-center gap-2 shrink-0">{@render actions()}</div>
	{/if}
</div>
