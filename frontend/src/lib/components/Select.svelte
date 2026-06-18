<!--
	Select.svelte — Tüm formlarda ortak açılır liste (tasarım sistemi primitive'i).

	Neden: 46 <select> elle aynı sınıf dizisini kopyalıyordu. Stil, odak halkası,
	hata kenarlığı ve cursor-pointer burada standarttır. <option>'lar children olarak verilir.

	Kullanım:
		<Select bind:value={form.currency}>
			{#each CURRENCIES as c}<option value={c}>{c}</option>{/each}
		</Select>
		<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={statusFilter}>
			<option value="">Tüm Durumlar</option>
		</Select>
-->
<script lang="ts" module>
	export type SelectSize = 'sm' | 'md';
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLSelectAttributes } from 'svelte/elements';

	let {
		value = $bindable(),
		size = 'md',
		invalid = false,
		fullWidth = true,
		class: klass = '',
		children,
		...rest
	}: {
		value?: any;
		size?: SelectSize;
		invalid?: boolean;
		fullWidth?: boolean;
		/** Yalnızca layout (genişlik/boşluk) için ek sınıf */
		class?: string;
		children: Snippet;
	} & Omit<HTMLSelectAttributes, 'value' | 'size' | 'class'> = $props();

	const PAD: Record<SelectSize, string> = { sm: 'py-2', md: 'py-2.5' };

	let cls = $derived(
		(fullWidth ? 'w-full ' : '') +
			'px-3 ' + PAD[size] + ' border rounded-lg text-sm bg-white text-gray-900 cursor-pointer ' +
			'focus:outline-none focus:ring-2 focus:ring-teal-500 ' +
			'disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed ' +
			(invalid ? 'border-red-400 ' : 'border-gray-300 ') +
			klass
	);
</script>

<select bind:value class={cls} aria-invalid={invalid || undefined} {...rest}>
	{@render children()}
</select>
