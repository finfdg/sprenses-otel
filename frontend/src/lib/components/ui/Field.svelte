<!--
	Field.svelte — Form alanı sarmalayıcı: label + zorunlu (*) + hata/ipucu + ARIA bağlama.

	Neden: label + kırmızı * + hata mesajı + aria-invalid/aria-describedby kablolaması her
	formda elle tekrarlanıyordu. Field bunu tek yerden yönetir; kontrolü children snippet'i
	ile alır ve { id, invalid, describedby } değerlerini geri verir → kontrol bunları kullanır.

	Kullanım:
		<Field label="Acente Adı" required for="agency_name" error={fieldErrors.agency_name}>
			{#snippet children({ id, invalid, describedby })}
				<Input {id} {invalid} aria-describedby={describedby} bind:value={form.agency_name} />
			{/snippet}
		</Field>

		<Field label="Tutar" required for="amount" error={fieldErrors.amount}>
			{#snippet children({ id, invalid, describedby })}
				<MoneyInput {id} ariaInvalid={invalid} ariaDescribedby={describedby} bind:value={form.amount} />
			{/snippet}
		</Field>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		label = '',
		required = false,
		error = '',
		hint = '',
		for: forId = undefined,
		class: klass = '',
		children,
	}: {
		label?: string;
		required?: boolean;
		error?: string;
		hint?: string;
		/** Kontrolün id'si — label for + hata/ipucu id eşleşmesi için */
		for?: string;
		class?: string;
		children: Snippet<[{ id: string | undefined; invalid: boolean; describedby: string | undefined }]>;
	} = $props();

	const describedby = $derived(
		error && forId ? `${forId}-error` : hint && forId ? `${forId}-hint` : undefined
	);
</script>

<div class={klass}>
	{#if label}
		<label for={forId} class="block text-sm font-medium text-gray-700 mb-1">
			{label}{#if required}<span class="text-red-600"> *</span>{/if}
		</label>
	{/if}
	{@render children({ id: forId, invalid: !!error, describedby })}
	{#if error}
		<p id={describedby} class="text-xs text-red-600 mt-1" role="alert">{error}</p>
	{:else if hint}
		<p id={describedby} class="text-xs text-gray-500 mt-1">{hint}</p>
	{/if}
</div>
