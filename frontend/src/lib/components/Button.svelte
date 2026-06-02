<!--
	Button.svelte — Tüm uygulamada ortak buton bileşeni (tasarım sistemi primitive'i).

	Neden: buton stilleri 6+ farklı padding/renk/rounding'e dağılmıştı. Bu bileşen
	primary rengin TEK kaynağıdır — markayı değiştirmek için sadece burayı düzenleyin.

	Renkler WCAG AA uyumludur (teal-700 = 5.3:1, red-600 = 4.8:1 beyaz üzerinde).

	Kullanım:
		<Button onclick={openAdd}><Plus size={16} /> Yeni Avans</Button>
		<Button variant="secondary" size="sm" onclick={...}>İptal</Button>
		<Button variant="danger" loading={saving} type="submit">Sil</Button>
-->
<script lang="ts" module>
	export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
	export type ButtonSize = 'sm' | 'md';
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Loader2 } from 'lucide-svelte';

	let {
		variant = 'primary',
		size = 'md',
		type = 'button',
		disabled = false,
		loading = false,
		href = undefined,
		onclick = undefined,
		ariaLabel = undefined,
		title = undefined,
		fullWidth = false,
		class: extraClass = '',
		children,
	}: {
		variant?: ButtonVariant;
		size?: ButtonSize;
		type?: 'button' | 'submit' | 'reset';
		disabled?: boolean;
		loading?: boolean;
		href?: string;
		onclick?: (e: MouseEvent) => void;
		ariaLabel?: string;
		title?: string;
		fullWidth?: boolean;
		/** Yalnızca layout (genişlik/kenar boşluğu vb.) için ek sınıf — renk/stil variant'tan gelir */
		class?: string;
		children: Snippet;
	} = $props();

	const VARIANTS: Record<ButtonVariant, string> = {
		primary: 'bg-teal-700 text-white hover:bg-teal-800 focus-visible:ring-teal-600 shadow-sm',
		secondary: 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50 focus-visible:ring-teal-500',
		danger: 'bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-500 shadow-sm',
		ghost: 'bg-transparent text-gray-600 hover:bg-gray-100 focus-visible:ring-teal-500',
	};
	const SIZES: Record<ButtonSize, string> = {
		sm: 'text-xs px-3 py-1.5 gap-1.5',
		md: 'text-sm px-4 py-2.5 gap-2',
	};

	let cls = $derived(
		'inline-flex items-center justify-center font-medium rounded-lg transition-colors cursor-pointer ' +
		'focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 ' +
		'disabled:opacity-50 disabled:cursor-not-allowed ' +
		VARIANTS[variant] + ' ' + SIZES[size] + (fullWidth ? ' w-full' : '') +
		(extraClass ? ' ' + extraClass : '')
	);

	let isDisabled = $derived(disabled || loading);
	let spinnerSize = $derived(size === 'sm' ? 14 : 16);
</script>

{#if href && !isDisabled}
	<a {href} class={cls} aria-label={ariaLabel} {title}>
		{#if loading}<Loader2 size={spinnerSize} class="animate-spin" />{/if}
		{@render children()}
	</a>
{:else}
	<button
		{type}
		{onclick}
		{title}
		disabled={isDisabled}
		aria-label={ariaLabel}
		aria-busy={loading}
		class={cls}
	>
		{#if loading}<Loader2 size={spinnerSize} class="animate-spin" />{/if}
		{@render children()}
	</button>
{/if}
