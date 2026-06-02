<script lang="ts">
	import type { CashFlowItem, TransactionCategory } from '$lib/types/finance';
	import { formatCurrency, formatCompact } from '$lib/utils/finance';
	import { categoryColorMap, getColor } from '$lib/utils/colorMap';
	import { getPaymentMethod } from '$lib/utils/paymentMethods';
	import TagSelector from './TagSelector.svelte';

	let {
		item,
		variant = 'desktop',
		narrow = false,
		categories = [],
		matchMode = false,
		onTagAssign,
		onCreateCategory,
		onMatchSelect,
		onCCMatchStart,
	}: {
		item: CashFlowItem;
		variant?: 'mobile' | 'desktop';
		narrow?: boolean;
		categories?: TransactionCategory[];
		matchMode?: boolean;
		onTagAssign?: (txId: number, categoryId: number | null, note: string | null, vendorId?: number | null, paymentMethod?: string | null, ccStatementId?: number | null) => void;
		onCreateCategory?: (name: string, color: string) => Promise<TransactionCategory | null>;
		onMatchSelect?: (txId: number) => void;
		onCCMatchStart?: (statementId: number, type: 'cc' | 'credit', description: string, amount: number) => void;
	} = $props();

	let showTagSelector = $state(false);
	let clickX = $state(0);
	let clickY = $state(0);

	const isExpense = $derived(item.type === 'expense');
	const isEur = $derived(item.currency !== 'TRY');
	const bgClass = $derived(isEur ? 'bg-blue-50 border-blue-200' : isExpense ? 'bg-rose-50 border-rose-200' : 'bg-emerald-50 border-emerald-200');
	const amountColor = $derived(isEur ? 'text-blue-600' : isExpense ? 'text-rose-600' : 'text-emerald-600');
	const arrowBorderOuter = $derived(isEur ? (isExpense ? 'border-l-blue-200' : 'border-r-blue-200') : isExpense ? 'border-l-rose-200' : 'border-r-emerald-200');
	const arrowBorderInner = $derived(isEur ? (isExpense ? 'border-l-blue-50' : 'border-r-blue-50') : isExpense ? 'border-l-rose-50' : 'border-r-emerald-50');

	const colorMap = categoryColorMap;

	function handleAssign(categoryId: number | null, note: string | null, vendorId?: number | null, paymentMethod?: string | null, ccStatementId?: number | null) {
		showTagSelector = false;
		if (onTagAssign) {
			onTagAssign(item.id, categoryId, note, vendorId, paymentMethod, ccStatementId);
		}
	}

	function handleTagClick(e: MouseEvent) {
		e.stopPropagation();
		// CC/credit satırına tıklayınca eşleştirme modunu başlat
		if ((item.source === 'cc_payment' || item.source === 'credit') && onCCMatchStart) {
			const type = item.source === 'cc_payment' ? 'cc' : 'credit';
			onCCMatchStart(item.id, type as 'cc' | 'credit', item.description, Math.abs(item.amount));
			return;
		}
		if (!showTagSelector) {
			clickX = e.clientX;
			clickY = e.clientY;
		}
		showTagSelector = !showTagSelector;
	}
</script>

{#if variant === 'mobile'}
	<!-- Mobil kart -->
	{@const isInteractive = item.source !== 'check' && item.source !== 'vendor_payment'}
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		class="{item.source === 'check' ? 'bg-orange-50 border-orange-200' : item.source === 'vendor_payment' ? 'bg-purple-50 border-purple-200' : item.source === 'cc_payment' ? 'bg-pink-50 border-pink-200' : item.source === 'credit' ? 'bg-indigo-50 border-indigo-200' : bgClass} border rounded-xl p-1.5 {isInteractive ? 'cursor-pointer' : ''}"
		onclick={isInteractive ? handleTagClick : undefined}
		onkeydown={isInteractive ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleTagClick(e as any); } } : undefined}
		role={isInteractive ? 'button' : undefined}
		tabindex={isInteractive ? 0 : -1}
		aria-label={isInteractive ? 'Etiket düzenle' : undefined}
	>
		<h4 class="font-semibold text-gray-800 text-[10px] leading-tight truncate">
			{#if item.source === 'check'}📄 {:else if item.source === 'vendor_payment'}🏢 {/if}{item.description}
		</h4>
		<div class="flex items-center justify-between mt-0.5 gap-1">
			<span class="text-[10px] font-bold {amountColor}">{formatCompact(item.amount, item.currency)}</span>
			<div class="flex items-center gap-0.5">
			{#if item.payment_method && item.payment_method !== 'diger' && !(item.source === 'vendor_payment' && item.payment_method === 'cari') && !(item.source === 'check' && item.payment_method === 'cek')}
				{@const pm = getPaymentMethod(item.payment_method)}
				{#if pm}
					<span class="text-[10px] font-medium {pm.bg} {pm.text} px-1 py-0.5 rounded truncate max-w-[45px]">{pm.label}</span>
				{/if}
			{/if}
			{#if item.category_name && item.category_color}
				{@const c = colorMap[item.category_color] ?? colorMap.gray}
				<span class="text-[10px] font-semibold {c.bg} {c.text} {c.border} border px-1 py-0.5 rounded truncate max-w-[60px]">{item.category_name}</span>
			{:else}
				<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0"></span>
			{/if}
			</div>
		</div>
		{#if showTagSelector && categories.length > 0}
			<TagSelector
				{categories}
				currentCategoryId={item.category_id}
				currentNote={item.tag_note}
				currentVendorId={item.vendor_id}
				currentVendorName={item.vendor_name}
				anchorX={clickX}
				anchorY={clickY}
				onAssign={handleAssign}
				onClose={() => { showTagSelector = false; }}
				{onCreateCategory}
			/>
		{/if}
	</div>
{:else if narrow}
	<!-- Masaüstü daraltılmış -->
	{@const isInteractiveNarrow = item.source !== 'check' && item.source !== 'vendor_payment'}
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		class="{item.source === 'cc_payment' ? 'bg-pink-50 border-pink-200' : item.source === 'credit' ? 'bg-indigo-50 border-indigo-200' : bgClass} border rounded-xl p-2 text-center {isInteractiveNarrow ? 'cursor-pointer' : ''}"
		onclick={isInteractiveNarrow ? handleTagClick : undefined}
		onkeydown={isInteractiveNarrow ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleTagClick(e as any); } } : undefined}
		role={isInteractiveNarrow ? 'button' : undefined}
		tabindex={isInteractiveNarrow ? 0 : -1}
		aria-label={isInteractiveNarrow ? 'Etiket düzenle' : undefined}
	>
		<div class="text-[11px] font-medium text-gray-700 truncate">{item.description}</div>
		<div class="text-xs font-bold {amountColor} mt-0.5">{formatCompact(item.amount, item.currency)}</div>
		{#if item.category_name && item.category_color}
			{@const c = colorMap[item.category_color] ?? colorMap.gray}
			<span class="inline-block text-[10px] font-semibold {c.bg} {c.text} {c.border} border px-1 py-0.5 rounded mt-0.5">{item.category_name}</span>
		{:else}
			<span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse mt-1"></span>
		{/if}
		{#if showTagSelector && categories.length > 0}
			<TagSelector
				{categories}
				currentCategoryId={item.category_id}
				currentNote={item.tag_note}
				currentVendorId={item.vendor_id}
				currentVendorName={item.vendor_name}
				anchorX={clickX}
				anchorY={clickY}
				onAssign={handleAssign}
				onClose={() => { showTagSelector = false; }}
				{onCreateCategory}
			/>
		{/if}
	</div>
{:else}
	<!-- Masaüstü tam -->
	{@const isInteractiveFull = item.source !== 'check' && item.source !== 'vendor_payment'}
	<div class="group relative">
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div
			class="relative {item.source === 'check' ? 'bg-orange-50 border-orange-200' : item.source === 'vendor_payment' ? 'bg-purple-50 border-purple-200' : item.source === 'cc_payment' ? 'bg-pink-50 border-pink-200' : item.source === 'credit' ? 'bg-indigo-50 border-indigo-200' : bgClass} border rounded-2xl {isExpense ? 'rounded-tr-sm' : 'rounded-tl-sm'} p-3 hover:shadow-md transition-shadow {isInteractiveFull ? 'cursor-pointer' : ''}"
			onclick={isInteractiveFull ? handleTagClick : undefined}
			onkeydown={isInteractiveFull ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleTagClick(e as any); } } : undefined}
			role={isInteractiveFull ? 'button' : undefined}
			tabindex={isInteractiveFull ? 0 : -1}
			aria-label={isInteractiveFull ? 'Etiket düzenle' : undefined}
		>
			<div class="flex items-start justify-between gap-2">
				<div class="min-w-0 flex-1">
					<h4 class="font-semibold text-gray-800 text-sm truncate">
						{#if item.source === 'check'}📄 Çek #{item.check_no} — {:else if item.source === 'vendor_payment'}🏢 {/if}{item.description}
					</h4>
					<div class="flex items-center gap-2 mt-0.5 flex-wrap">
						{#if item.source === 'check'}
							<span class="text-[10px] font-bold text-orange-600 bg-orange-100 px-1.5 py-0.5 rounded border border-orange-200">Verilen Çek</span>
							{#if item.check_status === 'paid'}
								<span class="text-[10px] font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">Ödendi</span>
							{:else if item.check_status === 'cancelled'}
								<span class="text-[10px] font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">İptal</span>
							{:else}
								<span class="text-[10px] font-medium text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">Bekliyor</span>
							{/if}
							{#if item.vendor_code}
								<span class="text-[10px] text-gray-500 font-mono">{item.vendor_code}</span>
							{/if}
						{:else if item.source === 'vendor_payment'}
							<span class="text-[10px] font-bold text-purple-600 bg-purple-100 px-1.5 py-0.5 rounded border border-purple-200">Cari Ödeme</span>
							<span class="text-[10px] font-medium text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">Bekliyor</span>
							{#if item.vendor_code}
								<span class="text-[10px] text-gray-500 font-mono">{item.vendor_code}</span>
							{/if}
							{#if item.invoice_count && item.invoice_count > 1}
								<span class="text-[10px] font-medium text-purple-500 bg-purple-50 px-1.5 py-0.5 rounded">{item.invoice_count} fatura</span>
							{:else if item.tag_note}
								<span class="text-[10px] text-gray-500">{item.tag_note}</span>
							{/if}
						{:else if item.source === 'cc_payment'}
							<span class="text-[10px] font-bold text-pink-600 bg-pink-100 px-1.5 py-0.5 rounded border border-pink-200">KK Borç Ödeme</span>
							<span class="text-[10px] font-medium text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">Bekliyor</span>
						{:else if item.source === 'credit'}
							<span class="text-[10px] font-bold text-indigo-600 bg-indigo-100 px-1.5 py-0.5 rounded border border-indigo-200">Kredi Taksit</span>
							<span class="text-[10px] font-medium text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">Bekliyor</span>
						{:else}
							<span class="text-[10px] font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">{item.bank_name}</span>
						{/if}
						{#if item.currency !== 'TRY'}
							<span class="text-[10px] font-medium text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">{item.currency}</span>
						{/if}
						{#if item.payment_method && item.payment_method !== 'diger' && !(item.source === 'vendor_payment' && item.payment_method === 'cari') && !(item.source === 'check' && item.payment_method === 'cek')}
							{@const pm = getPaymentMethod(item.payment_method)}
							{#if pm}
								<span class="text-[10px] font-medium {pm.bg} {pm.text} border {pm.border} px-1.5 py-0.5 rounded">{pm.label}</span>
							{/if}
						{/if}
						{#if item.receipt_no}
							<span class="text-[10px] text-gray-500">#{item.receipt_no}</span>
						{/if}
						<!-- Etiket badge -->
						{#if item.category_name && item.category_color}
							{@const c = colorMap[item.category_color] ?? colorMap.gray}
							<span class="text-[10px] font-semibold {c.bg} {c.text} {c.border} border px-1.5 py-0.5 rounded-full flex items-center gap-1">
								<span class="w-1.5 h-1.5 rounded-full {c.bg} {c.border} border shrink-0"></span>
								{item.category_name}
								{#if item.match_number}
									<span class="text-[10px] font-bold opacity-60">#{item.match_number}</span>
								{/if}
								{#if item.vendor_name}
									<span class="text-[10px] opacity-70">· {item.vendor_name}</span>
								{:else if item.tag_note}
									<span class="text-[10px] opacity-70">· {item.tag_note}</span>
								{/if}
							</span>
						{:else}
							<!-- Etiketlenmemiş göstergesi -->
							<span class="flex items-center gap-1 text-[10px] text-amber-500">
								<span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0"></span>
								<span class="hidden sm:inline">Etiketsiz</span>
							</span>
						{/if}
					</div>
				</div>
				<div class="flex items-center gap-2">
					{#if matchMode && item.source === 'bank' && onMatchSelect}
						<button
							onclick={(e) => { e.stopPropagation(); onMatchSelect?.(item.id); }}
							class="text-[10px] font-bold px-2.5 py-1 rounded-lg bg-teal-600 text-white hover:bg-teal-700 active:bg-teal-800 transition-colors cursor-pointer whitespace-nowrap"
						>
							Eşleştir
						</button>
					{/if}
					<span class="text-base font-bold {amountColor} whitespace-nowrap">
						{formatCurrency(item.amount, item.currency)}
					</span>
				</div>
			</div>
			{#if isExpense}
				<div class="absolute top-4 -right-2 w-0 h-0 border-t-[8px] border-t-transparent border-b-[8px] border-b-transparent border-l-[8px] {arrowBorderOuter}"></div>
				<div class="absolute top-4 -right-[7px] w-0 h-0 border-t-[8px] border-t-transparent border-b-[8px] border-b-transparent border-l-[8px] {arrowBorderInner}"></div>
			{:else}
				<div class="absolute top-4 -left-2 w-0 h-0 border-t-[8px] border-t-transparent border-b-[8px] border-b-transparent border-r-[8px] {arrowBorderOuter}"></div>
				<div class="absolute top-4 -left-[7px] w-0 h-0 border-t-[8px] border-t-transparent border-b-[8px] border-b-transparent border-r-[8px] {arrowBorderInner}"></div>
			{/if}
		</div>
		{#if showTagSelector && categories.length > 0}
			<TagSelector
				{categories}
				currentCategoryId={item.category_id}
				currentNote={item.tag_note}
				currentVendorId={item.vendor_id}
				currentVendorName={item.vendor_name}
				anchorX={clickX}
				anchorY={clickY}
				onAssign={handleAssign}
				onClose={() => { showTagSelector = false; }}
				{onCreateCategory}
			/>
		{/if}
	</div>
{/if}
