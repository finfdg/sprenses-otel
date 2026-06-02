<script lang="ts">
	import type { CashFlowItem, TransactionCategory } from '$lib/types/finance';
	import { filterColorMap, getColor } from '$lib/utils/colorMap';
	import { PAYMENT_METHODS } from '$lib/utils/paymentMethods';

	let {
		itemCount,
		categories,
		tagFilter,
		untaggedCount,
		paymentMethodFilter = null,
		onSetFilter,
		onSetPaymentMethod,
	}: {
		itemCount: number;
		categories: TransactionCategory[];
		tagFilter: 'all' | 'untagged' | number;
		untaggedCount: number;
		paymentMethodFilter?: string | null;
		onSetFilter: (filter: 'all' | 'untagged' | number) => void;
		onSetPaymentMethod?: (method: string | null) => void;
	} = $props();
</script>

<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-2 sm:p-3 mb-3 sm:mb-4">
	<div class="flex items-center gap-1.5 sm:gap-2 flex-wrap">
		<!-- Tümü -->
		<button
			onclick={() => onSetFilter('all')}
			class="text-[10px] sm:text-xs font-medium px-2 sm:px-3 py-1.5 sm:py-2 rounded-full border transition-colors cursor-pointer {tagFilter === 'all' ? 'bg-blue-100 text-blue-700 border-blue-300' : 'bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100'}"
		>
			Tümü
			<span class="ml-1 text-[10px] opacity-70">{itemCount}</span>
		</button>

		<!-- Etiketsiz -->
		<button
			onclick={() => onSetFilter('untagged')}
			class="text-[10px] sm:text-xs font-medium px-2 sm:px-3 py-1.5 sm:py-2 rounded-full border transition-colors cursor-pointer flex items-center gap-1 sm:gap-1.5 {tagFilter === 'untagged' ? 'bg-amber-100 text-amber-700 border-amber-300' : 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100'}"
		>
			<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
			Etiketsiz
			{#if untaggedCount > 0}
				<span class="text-[10px] font-bold bg-amber-200 text-amber-800 px-1.5 py-0.5 rounded-full">{untaggedCount}</span>
			{/if}
		</button>

		<!-- Ayırıcı -->
		<div class="w-px h-4 sm:h-5 bg-gray-200 mx-0.5 sm:mx-1"></div>

		<!-- Kategori pilleri -->
		{#each categories as cat (cat.id)}
			{@const c = getColor(cat.color, filterColorMap)}
			{@const isActive = tagFilter === cat.id}
			<button
				onclick={() => onSetFilter(cat.id)}
				class="text-[10px] sm:text-[11px] font-medium px-2 sm:px-2.5 py-1 rounded-full border transition-colors cursor-pointer flex items-center gap-1 {isActive ? `${c.bgActive} ${c.text} ${c.border}` : `${c.bg} ${c.text} ${c.border}`}"
			>
				<span class="w-1.5 h-1.5 rounded-full {c.bgActive} {c.border} border shrink-0"></span>
				{cat.name}
			</button>
		{/each}

		<!-- Ödeme Yöntemi filtresi -->
		{#if onSetPaymentMethod}
			<div class="w-px h-4 sm:h-5 bg-gray-200 mx-0.5 sm:mx-1"></div>
			{#each Object.entries(PAYMENT_METHODS) as [code, pm] (code)}
				{#if code !== 'diger'}
					<button
						onclick={() => onSetPaymentMethod?.(paymentMethodFilter === code ? null : code)}
						class="text-[10px] font-medium px-1.5 sm:px-2 py-1 rounded-full border transition-colors cursor-pointer {paymentMethodFilter === code ? `${pm.bg} ${pm.text} ${pm.border} ring-1 ring-offset-1` : `bg-white ${pm.text} ${pm.border} hover:${pm.bg}`}"
					>
						{pm.label}
					</button>
				{/if}
			{/each}
		{/if}

	</div>
</div>
