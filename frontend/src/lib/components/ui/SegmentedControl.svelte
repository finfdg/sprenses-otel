<!--
	SegmentedControl.svelte — Segment / sekme / filtre-çip grubu (tasarım sistemi primitive'i).

	Neden: 8+ sayfa kendi tab/chip stilini elle yazıyordu (cariler, satis-faturalari, cekler,
	doviz, talimatlar, fis-icmali, mizan, devam-takip) → 5+ farklı görsel dil. Bu bileşen tek
	tutarlı segment grubu verir: aktif = teal-700 + beyaz (AA 5.3:1), pasif = gray-600, opsiyonel
	sayı rozeti, dokunma hedefi 44px (touch-target), ARIA tablist.

	Kullanım:
		<SegmentedControl
			options={[{ value: '', label: 'Tümü' }, { value: 'paid', label: 'Ödendi', count: 12 }]}
			value={statusFilter}
			onchange={(v) => (statusFilter = v)}
			ariaLabel="Durum filtresi"
		/>
-->
<script lang="ts" module>
	export type SegmentOption = {
		value: string;
		label: string;
		/** Opsiyonel sayı rozeti (ör. filtre eşleşme sayısı). */
		count?: number;
		/** Opsiyonel Lucide ikon. */
		icon?: any;
	};
</script>

<script lang="ts">
	let {
		options,
		value,
		onchange,
		size = 'md',
		fullWidth = false,
		ariaLabel = undefined,
		class: extraClass = '',
	}: {
		options: SegmentOption[];
		value: string;
		onchange: (value: string) => void;
		size?: 'sm' | 'md';
		/** true → segmentler eşit genişlikte yayılır (mobil tam-genişlik için). */
		fullWidth?: boolean;
		ariaLabel?: string;
		/** Yalnızca layout (genişlik/boşluk) için ek sınıf. */
		class?: string;
	} = $props();

	const SIZE = {
		sm: 'text-xs px-2.5 py-1.5 gap-1',
		md: 'text-sm px-3 py-2 gap-1.5',
	};
	let segCls = $derived(SIZE[size]);
</script>

<div
	role="tablist"
	aria-label={ariaLabel}
	class="inline-flex items-center bg-gray-100 rounded-lg p-1 {fullWidth ? 'w-full' : ''} {extraClass}"
>
	{#each options as opt (opt.value)}
		{@const active = opt.value === value}
		{@const SegIcon = opt.icon}
		<button
			type="button"
			role="tab"
			aria-selected={active}
			onclick={() => onchange(opt.value)}
			class="touch-target inline-flex items-center justify-center font-medium rounded-md transition-colors cursor-pointer
				focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-1
				{fullWidth ? 'flex-1' : ''} {segCls}
				{active ? 'bg-teal-700 text-white shadow-sm' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-200'}"
		>
			{#if SegIcon}<SegIcon size={size === 'sm' ? 14 : 16} aria-hidden="true" />{/if}
			<span>{opt.label}</span>
			{#if opt.count !== undefined}
				<span
					class="ml-0.5 inline-flex items-center justify-center min-w-[1.25rem] px-1 rounded-full text-[0.7rem] font-semibold tabular-nums
						{active ? 'bg-white/25 text-white' : 'bg-gray-200 text-gray-600'}"
				>{opt.count}</span>
			{/if}
		</button>
	{/each}
</div>
