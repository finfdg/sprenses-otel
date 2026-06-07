<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge, { type BadgeType } from '$lib/components/StatusBadge.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { ReceiptText, FileText, CircleCheck, CircleDashed, Search, X, Wallet } from 'lucide-svelte';

	const STATUS_LABELS: Record<string, string> = { paid: 'Tahsil edildi', partial: 'Kısmi', open: 'Açık' };
	const STATUS_BADGE: Record<string, BadgeType> = { paid: 'success', partial: 'warning', open: 'neutral' };

	let canView = $derived(hasPermission('finance.sales_invoices', 'view'));

	type Summary = {
		total: { invoiced: number; collected: number; outstanding: number; count: number };
		munferit: { invoiced: number; collected: number; outstanding: number; count: number };
		agency: { invoiced: number; collected: number; outstanding: number; count: number };
		status_counts: { paid: number; partial: number; open: number };
		advance: { by_currency: Record<string, number>; agency_count: number };
	};
	type Invoice = {
		id: number; customer_code: string; customer_name: string; is_munferit: boolean;
		invoice_no: string | null; invoice_date: string; amount: number; amount_tl: number; currency: string;
		collected: number; remaining: number; status: string;
		advance_covered: number; by_advance: boolean;
	};
	type Advance = {
		customer_name: string; currency: string; source: string; is_munferit: boolean;
		received: number; consumed: number; remaining: number;
	};

	let view = $state<'invoices' | 'advances'>('invoices');
	let summary = $state<Summary | null>(null);
	let items = $state<Invoice[]>([]);
	let advances = $state<Advance[]>([]);
	let advByCur = $state<Record<string, number>>({});
	let advLoaded = $state(false);
	let loading = $state(true);
	let total = $state(0);
	let page = $state(1);
	let pageSize = $state(50);
	let pages = $state(1);
	let typeFilter = $state<'' | 'munferit' | 'agency'>('');
	let statusFilter = $state<'' | 'open' | 'partial' | 'paid'>('');
	let search = $state('');
	let searchTimer: ReturnType<typeof setTimeout> | null = null;

	function fmt(n: number): string {
		return new Intl.NumberFormat('tr-TR', { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n || 0) + ' ₺';
	}
	function fmt2(n: number): string {
		return new Intl.NumberFormat('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0);
	}
	function curSym(c: string): string {
		return c === 'EUR' ? '€' : c === 'USD' ? '$' : c === 'GBP' ? '£' : '₺';
	}
	function fmtCur(n: number, c: string): string { return fmt2(n) + ' ' + curSym(c); }
	function fmtCurMap(m: Record<string, number>): string {
		const parts = Object.entries(m || {}).filter(([, v]) => Math.abs(v) > 0.01).map(([c, v]) => fmtCur(v, c));
		return parts.length ? parts.join(' · ') : '0 ₺';
	}
	function fmtDate(s: string): string {
		if (!s) return '-';
		const [y, m, d] = s.split('-');
		return `${d}.${m}.${y}`;
	}

	async function loadSummary() {
		try {
			summary = await api.get<Summary>('/finance/sales-invoices/summary');
		} catch (e) {
			console.error('Satış faturası özeti alınamadı:', e);
		}
	}
	async function loadList() {
		loading = true;
		try {
			const p = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
			if (typeFilter) p.set('customer_type', typeFilter);
			if (statusFilter) p.set('status', statusFilter);
			if (search.trim()) p.set('search', search.trim());
			const r = await api.get<any>(`/finance/sales-invoices/?${p}`);
			items = r.items;
			total = r.total;
			pages = r.pages;
		} catch (e) {
			console.error('Satış faturaları alınamadı:', e);
			items = [];
		} finally {
			loading = false;
		}
	}
	async function loadAdvances() {
		if (advLoaded) return;
		try {
			const r = await api.get<{ items: Advance[]; total_by_currency: Record<string, number> }>('/finance/sales-invoices/advances');
			advances = r.items;
			advByCur = r.total_by_currency;
			advLoaded = true;
		} catch (e) {
			console.error('Acente avansları alınamadı:', e);
		}
	}
	function setView(v: 'invoices' | 'advances') {
		view = v;
		if (v === 'advances') loadAdvances();
	}
	function setType(t: typeof typeFilter) { typeFilter = t; page = 1; loadList(); }
	function setStatus(s: typeof statusFilter) { statusFilter = s; page = 1; loadList(); }
	function onSearch() {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { page = 1; loadList(); }, 300);
	}
	function clearSearch() { search = ''; page = 1; loadList(); }
	function changePage(p: number) { page = p; loadList(); }
	function changePageSize(s: number) { pageSize = s; page = 1; loadList(); }

	onMount(() => { loadSummary(); loadList(); });
</script>

<svelte:head><title>Satış Faturaları · Sprenses</title></svelte:head>

{#if !canView}
	<EmptyState icon={ReceiptText} title="Yetkiniz yok" message="Bu sayfayı görüntüleme izniniz bulunmuyor." />
{:else}
	<PageHeader title="Satış Faturaları" description="Otel oda/hizmet satış faturaları ve tahsilat durumu (Sedna muhasebeden). Üst bardaki 'Sedna' butonuyla güncellenir." />

	<!-- Özet kartları -->
	{#if summary}
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
			<StatCard label="Toplam Faturalanan" value={fmt(summary.total.invoiced)} accent="blue" icon={FileText} hint={`${summary.total.count} fatura`} />
			<StatCard label="Tahsil Edilen" value={fmt(summary.total.collected)} accent="emerald" icon={CircleCheck} hint={`${summary.status_counts.paid} ödendi`} />
			<StatCard label="Açık (Tahsil Edilmemiş)" value={fmt(summary.total.outstanding)} accent="amber" icon={CircleDashed} hint={`${summary.status_counts.open} açık · ${summary.status_counts.partial} kısmi`} />
			<button onclick={() => setView('advances')} class="text-left cursor-pointer">
				<StatCard label="Acente Avansı (kullanılmamış)" value={`${fmt(summary.advance.by_currency.TL ?? 0)} ₺`} accent="teal" icon={Wallet} hint={`${summary.advance.agency_count} acente${summary.advance.by_currency.EUR ? ' · ' + fmt(summary.advance.by_currency.EUR) + ' €' : ''} → görüntüle`} />
			</button>
		</div>
	{/if}

	<!-- Görünüm geçişi -->
	<div class="flex items-center gap-1 mb-3">
		<button onclick={() => setView('invoices')} class="text-sm font-medium px-3.5 py-1.5 rounded-lg border transition-colors cursor-pointer {view === 'invoices' ? 'bg-teal-700 text-white border-teal-700' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}">Faturalar</button>
		<button onclick={() => setView('advances')} class="text-sm font-medium px-3.5 py-1.5 rounded-lg border transition-colors cursor-pointer {view === 'advances' ? 'bg-teal-700 text-white border-teal-700' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}">Acente Avansları</button>
	</div>

	{#if view === 'invoices'}
	<!-- Filtre barı -->
	<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3 mb-4 flex flex-wrap items-center gap-2">
		<!-- Tür -->
		<div class="flex items-center gap-1">
			{#each [['', 'Tümü'], ['munferit', 'Münferit'], ['agency', 'Acente']] as [val, lbl]}
				<button onclick={() => setType(val as any)} class="text-xs font-medium px-3 py-1.5 rounded-full border transition-colors cursor-pointer {typeFilter === val ? 'bg-teal-100 text-teal-700 border-teal-300' : 'bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100'}">{lbl}</button>
			{/each}
		</div>
		<span class="w-px h-5 bg-gray-200"></span>
		<!-- Durum -->
		<div class="flex items-center gap-1">
			{#each [['', 'Hepsi'], ['open', 'Açık'], ['partial', 'Kısmi'], ['paid', 'Tahsil']] as [val, lbl]}
				<button onclick={() => setStatus(val as any)} class="text-xs font-medium px-3 py-1.5 rounded-full border transition-colors cursor-pointer {statusFilter === val ? 'bg-blue-100 text-blue-700 border-blue-300' : 'bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100'}">{lbl}</button>
			{/each}
		</div>
		<!-- Arama -->
		<div class="relative ml-auto">
			<Search size={15} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
			<input bind:value={search} oninput={onSearch} placeholder="Fatura no / müşteri ara" class="pl-8 pr-7 py-1.5 text-sm border border-gray-200 rounded-lg w-56 focus:outline-none focus:ring-2 focus:ring-teal-500/40" />
			{#if search}
				<button onclick={clearSearch} class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 cursor-pointer" aria-label="Temizle"><X size={14} /></button>
			{/if}
		</div>
		<span class="text-xs text-gray-400 tabular-nums">{total} kayıt</span>
	</div>

	<!-- İçerik -->
	<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
		{#if loading}
			<div class="p-4"><TableSkeleton rows={8} /></div>
		{:else if items.length === 0}
			<EmptyState icon={ReceiptText} title="Fatura yok" message="Filtreye uyan satış faturası bulunamadı. Üst bardaki 'Sedna' butonuyla içe aktarın." />
		{:else}
			<!-- Masaüstü tablo -->
			<table class="w-full text-sm hidden md:table">
				<thead class="bg-gray-50 text-gray-500 text-xs uppercase">
					<tr>
						<th class="text-left font-medium px-4 py-2.5">Tarih</th>
						<th class="text-left font-medium px-4 py-2.5">Fatura No</th>
						<th class="text-left font-medium px-4 py-2.5">Müşteri</th>
						<th class="text-right font-medium px-4 py-2.5">Tutar</th>
						<th class="text-right font-medium px-4 py-2.5">Tahsil</th>
						<th class="text-right font-medium px-4 py-2.5">Kalan</th>
						<th class="text-center font-medium px-4 py-2.5">Durum</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each items as inv}
						<tr class="hover:bg-gray-50/60">
							<td class="px-4 py-2.5 text-gray-600 tabular-nums whitespace-nowrap">{fmtDate(inv.invoice_date)}</td>
							<td class="px-4 py-2.5 text-gray-700 font-medium">{inv.invoice_no ?? '-'}</td>
							<td class="px-4 py-2.5 text-gray-700">
								<span class="inline-flex items-center gap-1.5">
									<span class="text-[10px] px-1.5 py-0.5 rounded {inv.is_munferit ? 'bg-purple-50 text-purple-600' : 'bg-cyan-50 text-cyan-700'}">{inv.is_munferit ? 'Münferit' : 'Acente'}</span>
									<span class="truncate max-w-[18rem]">{inv.customer_name}</span>
								</span>
							</td>
							<td class="px-4 py-2.5 text-right tabular-nums text-gray-800 whitespace-nowrap">{fmtCur(inv.amount, inv.currency)}</td>
							<td class="px-4 py-2.5 text-right tabular-nums text-emerald-600">{inv.collected ? fmt2(inv.collected) : '—'}</td>
							<td class="px-4 py-2.5 text-right tabular-nums {inv.remaining > 0.01 ? 'text-amber-700 font-medium' : 'text-gray-400'}">{inv.remaining > 0.01 ? fmt2(inv.remaining) : '—'}</td>
							<td class="px-4 py-2.5 text-center">
								<span class="inline-flex items-center gap-1">
									<StatusBadge type={STATUS_BADGE[inv.status] ?? 'neutral'}>{STATUS_LABELS[inv.status] ?? inv.status}</StatusBadge>
									{#if inv.by_advance}<span class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-700 inline-flex items-center gap-0.5" title="Acente avansından mahsup edildi"><Wallet size={10} /> avans</span>{/if}
								</span>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>

			<!-- Mobil kart -->
			<div class="md:hidden divide-y divide-gray-100">
				{#each items as inv}
					<div class="p-3">
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0">
								<p class="text-sm font-medium text-gray-800 truncate">{inv.customer_name}</p>
								<p class="text-xs text-gray-500 mt-0.5">{inv.invoice_no ?? '-'} · {fmtDate(inv.invoice_date)} · {inv.is_munferit ? 'Münferit' : 'Acente'}</p>
							</div>
							<StatusBadge type={STATUS_BADGE[inv.status] ?? 'neutral'}>{STATUS_LABELS[inv.status] ?? inv.status}</StatusBadge>
						</div>
						<div class="flex items-center justify-between mt-2 text-xs tabular-nums">
							<span class="text-gray-500">Tutar: <span class="text-gray-800">{fmtCur(inv.amount, inv.currency)}</span></span>
							{#if inv.remaining > 0.01}<span class="text-amber-700">Kalan: {fmtCur(inv.remaining, inv.currency)}</span>{:else}<span class="text-emerald-600 inline-flex items-center gap-1">Tahsil edildi{#if inv.by_advance}<span class="text-teal-600 text-[10px]">· avans</span>{/if}</span>{/if}
						</div>
					</div>
				{/each}
			</div>

			<div class="px-4 py-3 border-t border-gray-100">
				<Pagination {page} {pageSize} {total} onPageChange={changePage} onPageSizeChange={changePageSize} />
			</div>
		{/if}
	</div>
	{:else}
		<!-- ═══ ACENTE AVANSLARI ═══ -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			<div class="px-4 py-3 border-b border-gray-100 bg-teal-50/40 flex items-center justify-between flex-wrap gap-2">
				<p class="text-sm text-gray-600 max-w-2xl">Acentelerin yatırıp henüz fatura ile kapatmadığı <strong>kullanılmamış avans</strong>. <span class="text-teal-700">Avans hesabı</span> = Sedna 340 (asıl defter), <span class="text-amber-700">Cari net</span> = 120 cariye doğrudan yatan. Faturalar kesildikçe mahsup edilir.</p>
				<span class="text-sm font-semibold text-teal-700 tabular-nums whitespace-nowrap">Toplam: {fmtCurMap(advByCur)}</span>
			</div>
			{#if advances.length === 0}
				<EmptyState icon={Wallet} title="Açık avans yok" message="Net avans bakiyesi olan acente bulunmuyor. Üst bardaki 'Sedna' butonuyla içe aktarın." />
			{:else}
				<table class="w-full text-sm hidden md:table">
					<thead class="bg-gray-50 text-gray-500 text-xs uppercase">
						<tr>
							<th class="text-left font-medium px-4 py-2.5">Müşteri</th>
							<th class="text-right font-medium px-4 py-2.5">Yatırılan</th>
							<th class="text-right font-medium px-4 py-2.5">Faturayla Kapanan</th>
							<th class="text-right font-medium px-4 py-2.5">Kalan Avans</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-100">
						{#each advances as a}
							{@const isFx = a.currency !== 'TL'}
							<tr class="{isFx ? 'bg-blue-50/50 hover:bg-blue-50' : 'hover:bg-gray-50/60'}">
								<td class="px-4 py-2.5 text-gray-700 {isFx ? 'border-l-2 border-blue-400' : ''}">
									<span class="inline-flex items-center gap-1.5">
										<span class="text-[10px] px-1.5 py-0.5 rounded {a.source === '340' ? 'bg-teal-50 text-teal-700' : 'bg-amber-50 text-amber-700'}" title={a.source === '340' ? 'Sedna 340 Alınan Avanslar hesabı' : '120 cari net alacak (faturaya mahsup edilecek)'}>{a.source === '340' ? 'Avans hesabı' : 'Cari net'}</span>
										<span class="truncate max-w-[24rem]">{a.customer_name}</span>
									</span>
								</td>
								<td class="px-4 py-2.5 text-right tabular-nums text-gray-800">{fmt2(a.received)}</td>
								<td class="px-4 py-2.5 text-right tabular-nums text-gray-400">{a.consumed > 0.01 ? fmt2(a.consumed) : '—'}</td>
								<td class="px-4 py-2.5 text-right tabular-nums font-semibold whitespace-nowrap {isFx ? 'text-blue-700' : 'text-teal-700'}">{fmtCur(a.remaining, a.currency)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<div class="md:hidden divide-y divide-gray-100">
					{#each advances as a}
						{@const isFx = a.currency !== 'TL'}
						<div class="p-3 {isFx ? 'bg-blue-50/50 border-l-2 border-blue-400' : ''}">
							<div class="flex items-center justify-between gap-2">
								<p class="text-sm font-medium text-gray-800 truncate">{a.customer_name}</p>
								<span class="text-sm font-semibold tabular-nums whitespace-nowrap {isFx ? 'text-blue-700' : 'text-teal-700'}">{fmtCur(a.remaining, a.currency)}</span>
							</div>
							<p class="text-xs text-gray-500 mt-1 tabular-nums"><span class="px-1 rounded {a.source === '340' ? 'bg-teal-50 text-teal-700' : 'bg-amber-50 text-amber-700'}">{a.source === '340' ? 'avans hesabı' : 'cari net'}</span> · Yatırılan {fmt2(a.received)} · Kapanan {fmt2(a.consumed)}</p>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
{/if}
