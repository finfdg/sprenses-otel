<!--
	MonthlyBalances.svelte — Cariler "Aylık Bakiye" sekmesi (2026-07-23 yeniden tasarımı).

	İki mod:
	- FIFO Kalan: seçilen ayın faturalarından FIFO sonrası kalanı olan cariler
	  (ödemeler en eski faturadan düşülür; tamamen kapananlar gizli).
	- Dönem Sonu Bakiye: ay sonu itibarıyla yürüyen bakiye (+ sıfırları gizle).

	Veri: GET /finance/cariler/monthly-balances — satır sayısı cari sayısıyla sınırlı,
	sıralama istemci tarafında yapılır. Satıra tıklanınca cari detayı açılır (onOpenVendor).
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { CalendarRange } from 'lucide-svelte';
	import type { MonthlyFifoRow, MonthlyPeriodRow } from '$lib/types/vendor';

	let { onOpenVendor }: { onOpenVendor: (vendorId: number) => void } = $props();

	const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
	const now = new Date();
	const YEAR = now.getFullYear();
	const CUR_MONTH = now.getMonth() + 1;

	let mode = $state<'fifo' | 'period'>('fifo');
	let month = $state(CUR_MONTH);
	let hideZero = $state(true);
	let loading = $state(true);
	let fifoRows = $state<MonthlyFifoRow[]>([]);
	let periodRows = $state<MonthlyPeriodRow[]>([]);
	let totals = $state<Record<string, number>>({});

	// Kolon sıralaması — c1/c2/c3 mod bağımsız kolon kimlikleri
	let sortKey = $state<'name' | 'c1' | 'c2' | 'c3'>('c3');
	let sortDir = $state<'asc' | 'desc'>('desc');

	function fmt(n: number): string {
		return new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(n);
	}

	async function loadData() {
		loading = true;
		try {
			const params = new URLSearchParams({
				year: String(YEAR),
				month: String(month),
				mode,
				hide_zero: String(hideZero),
			});
			const res = await api.get<any>(`/finance/cariler/monthly-balances?${params}`);
			if (mode === 'fifo') fifoRows = res.items;
			else periodRows = res.items;
			totals = res.totals;
		} catch (err) {
			console.error('Aylık bakiye alınamadı:', err);
			showToast('Aylık bakiye yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	function setMode(m: 'fifo' | 'period') {
		mode = m;
		sortKey = 'c3';
		sortDir = m === 'fifo' ? 'desc' : 'asc';
		loadData();
	}

	function setMonth(m: number) {
		month = m;
		loadData();
	}

	function toggleHideZero() {
		hideZero = !hideZero;
		loadData();
	}

	function cycleSort(key: 'name' | 'c1' | 'c2' | 'c3', defDir: 'asc' | 'desc') {
		if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else { sortKey = key; sortDir = defDir; }
	}

	// c1/c2/c3 değer çıkarıcıları (mod bazlı)
	function colVal(row: any, key: string): number | string {
		if (key === 'name') return row.hesap_adi as string;
		if (mode === 'fifo') {
			return key === 'c1' ? row.invoiced : key === 'c2' ? row.closed : row.remaining;
		}
		return key === 'c1' ? row.total_borc : key === 'c2' ? row.total_alacak : row.balance;
	}

	let sortedRows = $derived.by(() => {
		const rows = (mode === 'fifo' ? fifoRows : periodRows) as any[];
		const dir = sortDir === 'asc' ? 1 : -1;
		return [...rows].sort((a, b) => {
			const x = colVal(a, sortKey);
			const y = colVal(b, sortKey);
			const c = typeof x === 'string' ? x.localeCompare(y as string, 'tr') : (x as number) - (y as number);
			return (c || a.hesap_adi.localeCompare(b.hesap_adi, 'tr')) * dir;
		});
	});

	// FIFO modunda yalnız Kalan gösterilir (2026-07-23 kullanıcı geri bildirimi):
	// ilerki aylarda ödenen tutar zaten kalandan düşer — fatura/kapanan kolonları kaldırıldı.
	let headers = $derived(
		mode === 'fifo'
			? [
					{ key: 'name' as const, label: 'Cari', right: false, defDir: 'asc' as const },
					{ key: 'c3' as const, label: 'Kalan', right: true, defDir: 'desc' as const },
				]
			: [
					{ key: 'name' as const, label: 'Cari', right: false, defDir: 'asc' as const },
					{ key: 'c1' as const, label: 'Borç (ödenen)', right: true, defDir: 'desc' as const },
					{ key: 'c2' as const, label: 'Alacak (fatura)', right: true, defDir: 'desc' as const },
					{ key: 'c3' as const, label: 'Dönem Sonu Bakiye', right: true, defDir: 'asc' as const },
				]
	);

	let totalC3 = $derived(mode === 'fifo' ? (totals.remaining ?? 0) : (totals.balance ?? 0));
	let totalMeta = $derived(
		mode === 'fifo'
			? 'ödemeler en eski faturadan düşüldü'
			: `borç ${fmt(totals.total_borc ?? 0)} − alacak ${fmt(totals.total_alacak ?? 0)}`
	);

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
	<!-- Başlık + mod seçimi -->
	<div class="flex items-start justify-between gap-3 flex-wrap mb-3">
		<div>
			<h2 class="text-base font-semibold text-gray-900">Ay Sonu Bakiyeleri</h2>
			<p class="text-xs text-gray-500 mt-0.5 max-w-2xl">
				{mode === 'fifo'
					? 'Havale / EFT, kredi kartı ve çek ödemeleri FIFO ile en eski faturadan düşülür — seçilen ayın faturalarından kalanı olan firmalar listelenir, tamamen kapananlar gösterilmez.'
					: 'Seçilen ay sonu itibarıyla firma bazında yürüyen bakiye — o tarihe kadarki tüm borç/alacak hareketlerinden hesaplanır.'}
			</p>
		</div>
		<div class="flex items-center gap-1.5 flex-wrap">
			{#each [{ k: 'fifo', label: 'FIFO Kalan' }, { k: 'period', label: 'Dönem Sonu Bakiye' }] as m (m.k)}
				<button onclick={() => setMode(m.k as any)} class="px-3 py-1 rounded-full text-xs font-semibold border transition-colors cursor-pointer {mode === m.k ? 'bg-brass-soft border-brass text-brass-dark' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}">{m.label}</button>
			{/each}
			{#if mode === 'period'}
				<button onclick={toggleHideZero} class="px-3 py-1 rounded-full text-xs font-semibold border transition-colors cursor-pointer {hideZero ? 'bg-teal-700 border-teal-700 text-white' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}">Sıfır bakiyeleri gizle</button>
			{/if}
		</div>
	</div>

	<!-- Ay seçimi -->
	<div class="flex items-center gap-1.5 flex-wrap mb-3">
		{#each MONTH_NAMES.slice(0, CUR_MONTH) as name, i (i)}
			<button onclick={() => setMonth(i + 1)} class="px-3 py-1 rounded-full text-xs font-semibold border transition-colors cursor-pointer {month === i + 1 ? 'bg-teal-700 border-teal-700 text-white' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}">{name} {YEAR}</button>
		{/each}
	</div>

	{#if loading}
		<TableSkeleton rows={8} columns={4} />
	{:else if sortedRows.length === 0}
		<EmptyState
			icon={CalendarRange}
			title={mode === 'fifo' ? 'Kalan bakiye yok' : 'Bakiyeli firma yok'}
			description={mode === 'fifo'
				? `${MONTH_NAMES[month - 1]} ${YEAR} faturalarının tamamı kapanmış — kalan bakiye yok.`
				: 'Bu ay sonu itibarıyla bakiyesi kalan firma yok.'}
		/>
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-xs {mode === 'fifo' ? 'min-w-[420px]' : 'min-w-[720px]'}">
				<thead class="bg-gray-50">
					<tr>
						{#each headers as h (h.key)}
							<th class="px-3 py-2 font-medium text-gray-600 {h.right ? 'text-right' : 'text-left'}">
								<button onclick={() => cycleSort(h.key, h.defDir)} class="inline-flex items-center gap-1 cursor-pointer hover:text-teal-700 {sortKey === h.key ? 'text-teal-700 font-semibold' : ''}" title="Sırala">
									{h.label}
									<span class="text-[9px] {sortKey === h.key ? 'opacity-100' : 'opacity-40'}">{sortKey === h.key ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}</span>
								</button>
							</th>
						{/each}
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each sortedRows as r (r.vendor_id)}
						<tr onclick={() => onOpenVendor(r.vendor_id)} class="hover:bg-gray-50 cursor-pointer" title="Cari detayını aç">
							<td class="px-3 py-2">
								<div class="font-semibold text-gray-900 truncate max-w-[280px]">{r.hesap_adi}</div>
								<div class="font-mono text-[10px] text-gray-500">{r.hesap_kodu}</div>
							</td>
							{#if mode === 'fifo'}
								<td class="px-3 py-2 text-right tabular-nums font-semibold text-brass-dark">{fmt(r.remaining)}</td>
							{:else}
								<td class="px-3 py-2 text-right tabular-nums text-emerald-700">{r.total_borc > 0 ? fmt(r.total_borc) : '—'}</td>
								<td class="px-3 py-2 text-right tabular-nums text-gray-700">{r.total_alacak > 0 ? fmt(r.total_alacak) : '—'}</td>
								<td class="px-3 py-2 text-right tabular-nums font-semibold {r.balance < -0.004 ? 'text-brass-dark' : r.balance > 0.004 ? 'text-emerald-700' : 'text-gray-500'}">{fmt(r.balance)}</td>
							{/if}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<div class="pt-2 text-[11px] text-gray-500">
			{mode === 'fifo'
				? `${sortedRows.length} firmada kalan var · ödemeler en eski faturadan düşüldü`
				: `${sortedRows.length} firma listeleniyor`}
		</div>
		<div class="mt-3 flex items-center justify-between gap-3 flex-wrap bg-teal-700 rounded-xl px-4 py-3">
			<div>
				<div class="text-[10px] uppercase tracking-wide font-semibold text-teal-100/80">
					{mode === 'fifo' ? `${MONTH_NAMES[month - 1]} ${YEAR} faturalarından kalan` : `${MONTH_NAMES[month - 1]} ${YEAR} sonu — net bakiye`}
				</div>
				<div class="text-[10px] text-teal-100/60 mt-0.5">{totalMeta}</div>
			</div>
			<div class="tabular-nums text-lg font-bold text-brass-light">{fmt(totalC3)}</div>
		</div>
	{/if}
</div>
