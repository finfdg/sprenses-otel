<!--
	ListPage.svelte — Liste/CRUD sayfaları için ortak iskelet (tasarım sistemi).

	Neden: Bespoke liste sayfaları aynı yapıyı tekrar tekrar elle yazıyordu —
	sayfa başlığı, filtre barı kartı, loading/empty durumları ve pagination.
	Bu bileşen kanonik iskeleti tek yerde toplar; sayfa yalnızca kendine özel
	içeriği (tablo satırları, modallar) snippet olarak verir.

	Kanonik sıra (docs/ui-kurallari.md): PageHeader → Stat kartları → Filtre barı
	→ İçerik (loading=Skeleton / boş=EmptyState / children) → Pagination.

	Kullanım:
		<ListPage
			title="Audit Logları"
			description={`Sistem etkinlik kayıtları — ${total} kayıt`}
			{loading}
			isEmpty={logs.length === 0}
			emptyIcon={ClipboardList}
			emptyTitle="Kayıt bulunamadı"
			page={page} pages={pages} total={total} pageSize={pageSize}
			onPageChange={(p) => { page = p; loadLogs(); }}
		>
			{#snippet actions()}<Button onclick={openAdd}>Yeni</Button>{/snippet}
			{#snippet filters()}<select ...>...</select>{/snippet}
			<table>...</table>            (children: ana icerik)
		</ListPage>

	Arama (opsiyonel): `search` (bindable) + `onSearch` verilirse filtre barında
	debounce'lu arama kutusu + temizle (✕) butonu otomatik gelir.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Search, X } from 'lucide-svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';

	let {
		title,
		description = undefined,
		loading = false,
		isEmpty = false,
		// Boş durum
		emptyIcon = undefined,
		emptyTitle = 'Kayıt bulunamadı',
		emptyMessage = undefined,
		emptyCtaText = undefined,
		onEmptyCta = undefined,
		// Arama (opsiyonel)
		search = $bindable(''),
		searchPlaceholder = 'Ara...',
		onSearch = undefined,
		// Pagination (opsiyonel)
		page = 1,
		pages = 1,
		total = 0,
		pageSize = 50,
		onPageChange = undefined,
		// Skeleton boyutu (varsayılan TableSkeleton)
		skeletonRows = 6,
		skeletonColumns = 5,
		// İçeriği beyaz kart içine sar (tablo için true; kart-listesi sayfaları için false)
		card = true,
		// Sayfa maksimum genişliği (Tailwind max-w-* sınıfı)
		maxWidth = 'max-w-7xl',
		// Snippet'ler
		actions = undefined,
		stats = undefined,
		filters = undefined,
		skeleton = undefined,
		children,
	}: {
		title: string;
		description?: string;
		loading?: boolean;
		isEmpty?: boolean;
		emptyIcon?: any;
		emptyTitle?: string;
		emptyMessage?: string;
		emptyCtaText?: string;
		onEmptyCta?: (() => void) | null;
		search?: string;
		searchPlaceholder?: string;
		onSearch?: (value: string) => void;
		page?: number;
		pages?: number;
		total?: number;
		pageSize?: number;
		onPageChange?: (page: number) => void;
		skeletonRows?: number;
		skeletonColumns?: number;
		card?: boolean;
		maxWidth?: string;
		actions?: Snippet;
		stats?: Snippet;
		filters?: Snippet;
		skeleton?: Snippet;
		children: Snippet;
	} = $props();

	const hasSearch = $derived(onSearch !== undefined);
	const showFilterBar = $derived(hasSearch || filters !== undefined);
	const showPagination = $derived(onPageChange !== undefined && pages > 1);

	// Debounce'lu arama (300ms) — kuralı tek yerde uygula
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	function onSearchInput(e: Event) {
		search = (e.target as HTMLInputElement).value;
		if (!onSearch) return;
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => onSearch?.(search), 300);
	}
	function clearSearch() {
		search = '';
		if (searchTimer) clearTimeout(searchTimer);
		onSearch?.('');
	}
</script>

<div class="{maxWidth} mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4">
	<!-- 1. Başlık -->
	<PageHeader {title} {description} {actions} />

	<!-- 2. Stat kartları -->
	{#if stats}
		{@render stats()}
	{/if}

	<!-- 3. Filtre barı -->
	{#if showFilterBar}
		<div class="bg-white rounded-xl border border-gray-200 p-3 sm:p-4 shadow-sm">
			<div class="flex flex-wrap gap-2 sm:gap-3 items-end">
				{#if hasSearch}
					<div class="flex-1 min-w-[180px]">
						<div class="relative">
							<Search size={16} class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
							<input
								type="text"
								value={search}
								oninput={onSearchInput}
								placeholder={searchPlaceholder}
								class="w-full text-sm border border-gray-200 rounded-lg pl-9 pr-9 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/40"
							/>
							{#if search}
								<button
									onclick={clearSearch}
									class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600 rounded cursor-pointer"
									aria-label="Aramayı temizle"
								>
									<X size={14} />
								</button>
							{/if}
						</div>
					</div>
				{/if}
				{#if filters}
					{@render filters()}
				{/if}
			</div>
		</div>
	{/if}

	<!-- 4. Ana içerik (card=true → beyaz kart sarmalayıcı; false → çıplak, kart-listeleri için) -->
	{#snippet body()}
		{#if loading}
			{#if skeleton}
				{@render skeleton()}
			{:else}
				<TableSkeleton rows={skeletonRows} columns={skeletonColumns} />
			{/if}
		{:else if isEmpty}
			<EmptyState icon={emptyIcon} title={emptyTitle} description={emptyMessage ?? ''} ctaText={emptyCtaText ?? ''} onCta={onEmptyCta ?? null} />
		{:else}
			{@render children()}
		{/if}

		<!-- 5. Pagination -->
		{#if showPagination}
			<div class="flex items-center justify-between px-4 py-3 border-t border-gray-100 bg-gray-50">
				<span class="text-xs text-gray-500">
					{(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} / {total}
				</span>
				<div class="flex items-center gap-2">
					<button
						onclick={() => onPageChange?.(page - 1)}
						disabled={page <= 1}
						class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 bg-white disabled:opacity-40 hover:bg-gray-50 transition-colors cursor-pointer"
					>Önceki</button>
					<span class="text-xs text-gray-500">{page}/{pages}</span>
					<button
						onclick={() => onPageChange?.(page + 1)}
						disabled={page >= pages}
						class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 bg-white disabled:opacity-40 hover:bg-gray-50 transition-colors cursor-pointer"
					>Sonraki</button>
				</div>
			</div>
		{/if}
	{/snippet}

	{#if card}
		<div class="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
			{@render body()}
		</div>
	{:else}
		{@render body()}
	{/if}
</div>
