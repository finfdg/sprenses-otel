<!--
	YearlyTurnover.svelte — Cariler "Yıllık Ciro" sekmesi (2026-07-23 yeniden tasarımı).

	Firma bazında yıl içi fatura (alacak) hacmi — devir/açılış kayıtları hariç.
	Aylık dağılım mini çubukları (altın = firmanın zirve ayı), fatura sayısı,
	toplam ciro içindeki pay yüzdesi. Satıra tıklanınca cari detayı açılır.

	Veri: GET /finance/cariler/yearly-turnover — sıralama istemci tarafında.
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { BarChart3 } from 'lucide-svelte';
	import type { YearlyTurnoverRow } from '$lib/types/vendor';

	let { onOpenVendor }: { onOpenVendor: (vendorId: number) => void } = $props();

	const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
	const now = new Date();
	const YEAR = now.getFullYear();
	const CUR_MONTH = now.getMonth() + 1; // dağılım çubukları Oca..içinde bulunulan ay

	let loading = $state(true);
	let rows = $state<YearlyTurnoverRow[]>([]);
	let totalTurnover = $state(0);
	let totalInvoices = $state(0);

	let sortKey = $state<'name' | 'fatura' | 'ciro'>('ciro');
	let sortDir = $state<'asc' | 'desc'>('desc');

	function fmt(n: number): string {
		return new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(n);
	}

	async function loadData() {
		loading = true;
		try {
			const res = await api.get<any>(`/finance/cariler/yearly-turnover?year=${YEAR}`);
			rows = res.items;
			totalTurnover = res.total_turnover;
			totalInvoices = res.total_invoices;
		} catch (err) {
			console.error('Yıllık ciro alınamadı:', err);
			showToast('Yıllık ciro yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	function cycleSort(key: 'name' | 'fatura' | 'ciro', defDir: 'asc' | 'desc') {
		if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else { sortKey = key; sortDir = defDir; }
	}

	let sortedRows = $derived.by(() => {
		const dir = sortDir === 'asc' ? 1 : -1;
		return [...rows].sort((a, b) => {
			let c: number;
			if (sortKey === 'name') c = a.hesap_adi.localeCompare(b.hesap_adi, 'tr');
			else if (sortKey === 'fatura') c = a.invoice_count - b.invoice_count;
			else c = a.turnover - b.turnover;
			return (c || a.hesap_adi.localeCompare(b.hesap_adi, 'tr')) * dir;
		});
	});

	function bars(r: YearlyTurnoverRow) {
		const slice = r.monthly.slice(0, CUR_MONTH);
		const max = Math.max(...slice, 0) || 1;
		return slice.map((m, i) => ({
			h: Math.max(2, Math.round((m / max) * 26)),
			peak: m > 0 && m === max,
			zero: m <= 0,
			tip: `${MONTH_NAMES[i]}: ${fmt(m)}`,
		}));
	}

	function sharePct(r: YearlyTurnoverRow): number {
		return totalTurnover > 0 ? (r.turnover / totalTurnover) * 100 : 0;
	}

	let unsubFinance: (() => void) | null = null;

	onMount(() => {
		loadData();
		unsubFinance = onWsEvent('finance_updated', () => loadData());
	});

	onDestroy(() => {
		unsubFinance?.();
	});
</script>

<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
	<div class="flex items-start justify-between gap-3 flex-wrap mb-3">
		<div>
			<h2 class="text-base font-semibold text-gray-900">{YEAR} Yıllık Ciro</h2>
			<p class="text-xs text-gray-500 mt-0.5 max-w-2xl">Firmaların yıl içindeki fatura (alacak) hacmi — kolon başlıklarından sıralanır, altın çubuk firmanın en yüksek ayıdır. Devir bakiyeleri hariçtir.</p>
		</div>
		<div class="bg-teal-700 rounded-xl px-4 py-2.5 text-right">
			<div class="text-[9px] uppercase tracking-wide font-semibold text-teal-100/80">Toplam Ciro</div>
			<div class="tabular-nums text-base font-bold text-brass-light whitespace-nowrap">{fmt(totalTurnover)}</div>
		</div>
	</div>

	{#if loading}
		<TableSkeleton rows={8} columns={5} />
	{:else if sortedRows.length === 0}
		<EmptyState icon={BarChart3} title="Ciro verisi yok" description="Bu yıl için fatura kaydı bulunmuyor." />
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-xs min-w-[820px]">
				<thead class="bg-gray-50">
					<tr>
						<th class="px-3 py-2 text-left font-medium text-gray-600">
							<button onclick={() => cycleSort('name', 'asc')} class="inline-flex items-center gap-1 cursor-pointer hover:text-teal-700 {sortKey === 'name' ? 'text-teal-700 font-semibold' : ''}" title="Sırala">Cari <span class="text-[9px] {sortKey === 'name' ? 'opacity-100' : 'opacity-40'}">{sortKey === 'name' ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}</span></button>
						</th>
						<th class="px-3 py-2 text-left font-medium text-gray-600">Aylık Dağılım (Oca–{MONTH_NAMES[CUR_MONTH - 1].slice(0, 3)})</th>
						<th class="px-3 py-2 text-right font-medium text-gray-600">
							<button onclick={() => cycleSort('fatura', 'desc')} class="inline-flex items-center gap-1 cursor-pointer hover:text-teal-700 {sortKey === 'fatura' ? 'text-teal-700 font-semibold' : ''}" title="Sırala">Fatura <span class="text-[9px] {sortKey === 'fatura' ? 'opacity-100' : 'opacity-40'}">{sortKey === 'fatura' ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}</span></button>
						</th>
						<th class="px-3 py-2 text-right font-medium text-gray-600">Pay</th>
						<th class="px-3 py-2 text-right font-medium text-gray-600">
							<button onclick={() => cycleSort('ciro', 'desc')} class="inline-flex items-center gap-1 cursor-pointer hover:text-teal-700 {sortKey === 'ciro' ? 'text-teal-700 font-semibold' : ''}" title="Sırala">Yıllık Ciro <span class="text-[9px] {sortKey === 'ciro' ? 'opacity-100' : 'opacity-40'}">{sortKey === 'ciro' ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}</span></button>
						</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each sortedRows as r (r.vendor_id)}
						<tr onclick={() => onOpenVendor(r.vendor_id)} class="hover:bg-gray-50 cursor-pointer" title="Cari detayını aç">
							<td class="px-3 py-2">
								<div class="font-semibold text-gray-900 truncate max-w-[260px]">{r.hesap_adi}</div>
								<div class="font-mono text-[10px] text-gray-500">{r.hesap_kodu}</div>
							</td>
							<td class="px-3 py-2">
								<div class="flex items-end gap-[3px] h-[30px]">
									{#each bars(r) as b, i (i)}
										<div title={b.tip} class="w-[14px] rounded-t-[3px] {b.zero ? 'bg-gray-100' : b.peak ? 'bg-brass' : 'bg-teal-300'}" style="height: {b.h}px"></div>
									{/each}
								</div>
							</td>
							<td class="px-3 py-2 text-right tabular-nums text-gray-700">{r.invoice_count}</td>
							<td class="px-3 py-2">
								<div class="text-right tabular-nums font-semibold text-brass-dark">%{sharePct(r).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</div>
								<div class="mt-1 h-1 rounded-full bg-gray-100 overflow-hidden"><div class="h-full bg-brass-light rounded-full" style="width: {Math.max(1.5, sharePct(r))}%"></div></div>
							</td>
							<td class="px-3 py-2 text-right tabular-nums font-semibold text-teal-700 whitespace-nowrap">{fmt(r.turnover)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<div class="pt-2 text-[11px] text-gray-500">{sortedRows.length} firma · {totalInvoices} fatura · devir bakiyeleri hariç</div>
	{/if}
</div>
