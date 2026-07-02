<script lang="ts">
	import type { DayRenderUnit } from '$lib/utils/finance';
	import { formatCurrency } from '$lib/utils/finance';
	import type { TransactionCategory } from '$lib/types/finance';
	import CashFlowItem from './CashFlowItem.svelte';
	import { ChevronDown, ChevronRight, FileText, Building2, Landmark, CreditCard } from 'lucide-svelte';

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

	// Kaynak → görünüm eşlemesi (CashFlowItem renkleriyle uyumlu: check=orange,
	// vendor_payment=purple, credit=indigo, cc_payment=pink) — AA metin tonları (700).
	// 'Kredi Taksitleri' leasing'i de kapsar (leasing = kredi ürün tipi, source='credit').
	const STYLES = {
		check: { label: 'Verilen Çekler', icon: FileText,
			header: 'bg-orange-50 border-orange-200 hover:bg-orange-100 text-orange-700', border: 'border-orange-200' },
		vendor_payment: { label: 'Cari Ödemeleri', icon: Building2,
			header: 'bg-purple-50 border-purple-200 hover:bg-purple-100 text-purple-700', border: 'border-purple-200' },
		credit: { label: 'Kredi / Leasing Taksitleri', icon: Landmark,
			header: 'bg-indigo-50 border-indigo-200 hover:bg-indigo-100 text-indigo-700', border: 'border-indigo-200' },
		cc_payment: { label: 'KK Borç Ödemeleri', icon: CreditCard,
			header: 'bg-pink-50 border-pink-200 hover:bg-pink-100 text-pink-700', border: 'border-pink-200' },
	} as const;

	const style = $derived(STYLES[unit.source]);
	const label = $derived(style.label);
	const Icon = $derived(style.icon);
	const isMobile = $derived(variant === 'mobile');
</script>

<div class="rounded-lg border {style.border} overflow-hidden">
	<button
		type="button"
		onclick={() => (open = !open)}
		aria-expanded={open}
		aria-label={`${label} grubunu ${open ? 'kapat' : 'aç'} (${unit.count} kayıt)`}
		class="w-full flex items-center gap-1.5 {isMobile ? 'px-1.5 py-1' : 'px-2.5 py-1.5'} {style.header} transition-colors touch-target"
	>
		{#if open}<ChevronDown size={isMobile ? 12 : 14} class="shrink-0" />{:else}<ChevronRight size={isMobile ? 12 : 14} class="shrink-0" />{/if}
		<Icon size={isMobile ? 12 : 14} class="shrink-0" />
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
