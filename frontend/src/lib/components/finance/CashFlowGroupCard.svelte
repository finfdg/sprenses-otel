<script lang="ts">
	import type { DayRenderUnit } from '$lib/utils/finance';
	import { formatCurrency } from '$lib/utils/finance';
	import type { TransactionCategory } from '$lib/types/finance';
	import CashFlowItem from './CashFlowItem.svelte';
	import { ChevronDown, ChevronRight, FileText, Building2 } from 'lucide-svelte';

	let {
		unit,
		variant = 'desktop',
		narrow = false,
		categories = [],
		onTagAssign,
		matchMode = false,
		onMatchSelect,
		onCCMatchStart,
		onCreateCategory,
	}: {
		unit: Extract<DayRenderUnit, { kind: 'group' }>;
		variant?: 'mobile' | 'desktop';
		narrow?: boolean;
		categories?: TransactionCategory[];
		onTagAssign?: (txId: number, categoryId: number | null, note: string | null, vendorId?: number | null, paymentMethod?: string | null, ccStatementId?: number | null) => void;
		matchMode?: boolean;
		onMatchSelect?: (txId: number) => void;
		onCCMatchStart?: (statementId: number, type: 'credit' | 'cc', description: string, amount: number) => void;
		onCreateCategory?: (name: string, color: string) => Promise<TransactionCategory | null>;
	} = $props();

	let open = $state(false);

	const isCheck = $derived(unit.source === 'check');
	const label = $derived(isCheck ? 'Verilen Çekler' : 'Cari Ödemeleri');
	// Kaynak renkleriyle uyumlu (CashFlowItem: check=orange, vendor_payment=purple) — AA metin tonları (700)
	const headerCls = $derived(isCheck
		? 'bg-orange-50 border-orange-200 hover:bg-orange-100 text-orange-700'
		: 'bg-purple-50 border-purple-200 hover:bg-purple-100 text-purple-700');
	const isMobile = $derived(variant === 'mobile');
</script>

<div class="rounded-lg border {isCheck ? 'border-orange-200' : 'border-purple-200'} overflow-hidden">
	<button
		type="button"
		onclick={() => (open = !open)}
		aria-expanded={open}
		aria-label={`${label} grubunu ${open ? 'kapat' : 'aç'} (${unit.count} kayıt)`}
		class="w-full flex items-center gap-1.5 {isMobile ? 'px-1.5 py-1' : 'px-2.5 py-1.5'} {headerCls} transition-colors touch-target"
	>
		{#if open}<ChevronDown size={isMobile ? 12 : 14} class="shrink-0" />{:else}<ChevronRight size={isMobile ? 12 : 14} class="shrink-0" />{/if}
		{#if isCheck}<FileText size={isMobile ? 12 : 14} class="shrink-0" />{:else}<Building2 size={isMobile ? 12 : 14} class="shrink-0" />{/if}
		<span class="{isMobile ? 'text-[10px]' : 'text-xs'} font-medium truncate">{label}</span>
		<span class="{isMobile ? 'text-[10px]' : 'text-xs'} opacity-80 shrink-0">· {unit.count} kayıt</span>
		<span class="ml-auto {isMobile ? 'text-[10px]' : 'text-xs'} font-semibold tabular-nums shrink-0">
			{#if unit.nativeTotal !== null && unit.currency}
				{formatCurrency(unit.nativeTotal, unit.currency)}
			{:else}
				{formatCurrency(unit.totalTry, 'TRY')}
			{/if}
		</span>
	</button>

	{#if open}
		<div class="{isMobile ? 'p-1 space-y-1' : 'p-1.5 space-y-1.5'} bg-white/60">
			{#each unit.items as item (`${item.source}-${item.id}`)}
				<CashFlowItem {item} {variant} {narrow} {categories} {onTagAssign} {matchMode} {onMatchSelect} {onCCMatchStart} {onCreateCategory} />
			{/each}
		</div>
	{/if}
</div>
