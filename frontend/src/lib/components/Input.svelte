<!--
	Input.svelte — Tüm formlarda ortak metin/tarih/sayı girişi (tasarım sistemi primitive'i).

	Neden: 160+ <input> elle aynı sınıf dizisini (border-gray-300 rounded-lg py-2.5
	focus:ring-teal-500) kopyalıyordu. Bu bileşen o stilin TEK kaynağıdır — odak halkası,
	hata kenarlığı (invalid → border-red-400) ve aria-invalid burada standarttır.

	Para girişi için MoneyInput, dosya için FileDropzone kullanılır — bu bileşen onları kapsamaz.

	Kullanım:
		<Input type="text" bind:value={form.name} placeholder="Ad girin" />
		<Input type="date" bind:value={form.date} invalid={!!err} aria-describedby="date-error" />
		<Input type="search" icon={Search} clearable bind:value={searchInput} placeholder="Ara…" />
		<Input size="sm" fullWidth={false} class="w-40" bind:value={x} />   <!-- filtre barı -->

	value tipi: string | number | null. type="number" → number|null, diğerleri string.
	Not: type dinamik olduğundan native bind:value yerine kontrollü value+oninput kullanılır.
-->
<script lang="ts" module>
	export type InputSize = 'sm' | 'md';
</script>

<script lang="ts">
	import { X } from 'lucide-svelte';
	import type { HTMLInputAttributes } from 'svelte/elements';

	let {
		value = $bindable(),
		type = 'text',
		size = 'md',
		invalid = false,
		fullWidth = true,
		icon = undefined,
		clearable = false,
		class: klass = '',
		oninput: callerOnInput = undefined,
		...rest
	}: {
		value?: string | number | null;
		type?: string;
		size?: InputSize;
		invalid?: boolean;
		fullWidth?: boolean;
		/** Soldaki Lucide ikonu (opsiyonel) — arama kutuları için */
		icon?: any;
		/** Değer varken sağda ✕ temizle butonu göster */
		clearable?: boolean;
		/** Yalnızca layout (genişlik/boşluk) için ek sınıf — stil bileşenden gelir */
		class?: string;
		oninput?: (e: Event) => void;
	} & Omit<HTMLInputAttributes, 'value' | 'type' | 'size' | 'class' | 'oninput'> = $props();

	const Icon = $derived(icon);
	const decorated = $derived(Boolean(icon) || clearable);
	const PAD: Record<InputSize, string> = { sm: 'py-2', md: 'py-2.5' };

	let inputCls = $derived(
		(fullWidth ? 'w-full ' : '') +
			'px-3 ' + PAD[size] + ' border rounded-lg text-sm bg-white text-gray-900 ' +
			'focus:outline-none focus:ring-2 focus:ring-teal-500 ' +
			'disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed ' +
			(invalid ? 'border-red-400 ' : 'border-gray-300 ') +
			(icon ? 'pl-9 ' : '') +
			(clearable ? 'pr-9 ' : '') +
			(decorated ? '' : klass)
	);

	function handleInput(e: Event) {
		const t = e.currentTarget as HTMLInputElement;
		value = type === 'number' ? (t.value === '' ? null : t.valueAsNumber) : t.value;
		callerOnInput?.(e);
	}
</script>

{#if decorated}
	<div class="relative {fullWidth ? 'w-full' : ''} {klass}">
		{#if Icon}
			<Icon size={16} class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" aria-hidden="true" />
		{/if}
		<input
			{type}
			value={value ?? ''}
			oninput={handleInput}
			aria-invalid={invalid || undefined}
			class={inputCls}
			{...rest}
		/>
		{#if clearable && value}
			<button
				type="button"
				onclick={() => (value = '')}
				aria-label="Temizle"
				class="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 cursor-pointer"
			>
				<X size={16} />
			</button>
		{/if}
	</div>
{:else}
	<input
		{type}
		value={value ?? ''}
		oninput={handleInput}
		aria-invalid={invalid || undefined}
		class={inputCls}
		{...rest}
	/>
{/if}
