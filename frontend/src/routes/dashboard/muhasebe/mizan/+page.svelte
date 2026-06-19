<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import {
		Scale, ArrowDownUp, CheckCircle2, AlertTriangle, Hash, RefreshCw, Calendar,
		ChevronLeft, ChevronRight, Loader2, Search, X, BookOpen
	} from 'lucide-svelte';

	const now = new Date();

	// State — filtreler
	let year = $state(now.getFullYear());
	let search = $state('');

	// State — veri
	let loading = $state(true);
	let configured = $state(true);
	let meta = $state<any>({ grand_total_borc: 0, grand_total_alacak: 0, balanced: true, account_count: 0 });
	let rows = $state<any[]>([]); // ağaç: düz liste + _level/_expanded/_loading

	// Türetilmiş
	let years = $derived([...new Set([year, ...Array.from({ length: 6 }, (_, i) => now.getFullYear() - i)])].sort((a, b) => b - a));
	let start = $derived(`${year}-01-01`);
	let end = $derived(`${year}-12-31`);
	let searchMode = $derived(search.trim().length > 0);
	let fark = $derived(Math.abs((meta.grand_total_borc || 0) - (meta.grand_total_alacak || 0)));
	let viewBorc = $derived(rows.reduce((s, r) => s + (r.borc || 0), 0));
	let viewAlacak = $derived(rows.reduce((s, r) => s + (r.alacak || 0), 0));

	function fmt(n: number): string {
		return (n || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	async function loadRoot() {
		loading = true;
		try {
			const d = await api.get<any>(`/accounting/mizan/summary?start_date=${start}&end_date=${end}&level=1`);
			meta = d;
			rows = (d.rows || []).map((r: any) => ({ ...r, _level: 0, _expanded: false, _loading: false }));
			configured = true;
		} catch (e: any) {
			console.error('Mizan yüklenemedi:', e);
			if (e?.status === 503) configured = false;
			rows = [];
			meta = { grand_total_borc: 0, grand_total_alacak: 0, balanced: true, account_count: 0 };
		} finally {
			loading = false;
		}
	}

	async function toggleExpand(row: any) {
		const idx = rows.findIndex((r) => r.code === row.code);
		if (idx < 0) return;
		if (row._expanded) {
			// daralt: ardındaki daha derin (_level büyük) satırları çıkar
			let j = idx + 1;
			while (j < rows.length && rows[j]._level > row._level) j++;
			rows.splice(idx + 1, j - (idx + 1));
			row._expanded = false;
			rows = rows;
			return;
		}
		row._loading = true;
		rows = rows;
		try {
			const d = await api.get<any>(`/accounting/mizan/summary?start_date=${start}&end_date=${end}&parent=${encodeURIComponent(row.code)}`);
			const children = (d.rows || []).map((r: any) => ({ ...r, _level: row._level + 1, _expanded: false, _loading: false }));
			rows.splice(idx + 1, 0, ...children);
			row._expanded = true;
		} catch (e) {
			console.error('Alt hesap yüklenemedi:', e);
		} finally {
			row._loading = false;
			rows = rows;
		}
	}

	let searchTimer: any;
	function onSearch() {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(runSearch, 300);
	}
	async function runSearch() {
		const q = search.trim();
		if (!q) {
			loadRoot();
			return;
		}
		loading = true;
		try {
			// kademe 6 ≈ leaf düzeyi → tüm hesaplarda kod/ad araması (düz sonuç)
			const d = await api.get<any>(`/accounting/mizan/summary?start_date=${start}&end_date=${end}&level=6&search=${encodeURIComponent(q)}`);
			meta = d;
			rows = (d.rows || []).map((r: any) => ({ ...r, _level: 0, _expanded: false, _loading: false }));
		} catch (e) {
			console.error('Arama hatası:', e);
			rows = [];
		} finally {
			loading = false;
		}
	}
	function clearSearch() {
		search = '';
		loadRoot();
	}

	function shiftYear(delta: number) {
		year += delta;
		search ? runSearch() : loadRoot();
	}
	function onYearChange() {
		search ? runSearch() : loadRoot();
	}

	// ───── Drill-down: hesap → hareketler (defter) ─────
	let txOpen = $state(false);
	let txLoading = $state(false);
	let txData = $state<any>(null);
	let txTitle = $state('');

	async function openTx(row: any) {
		txOpen = true;
		txLoading = true;
		txData = null;
		txTitle = `${row.code} · ${row.name || ''}`.trim();
		try {
			txData = await api.get<any>(`/accounting/mizan/transactions?code=${encodeURIComponent(row.code)}&start_date=${start}&end_date=${end}`);
		} catch (e) {
			console.error('Hareketler yüklenemedi:', e);
		} finally {
			txLoading = false;
		}
	}

	function fmtD(s: string | null): string {
		if (!s) return '—';
		const [y, m, d] = s.split('-');
		return `${d}.${m}.${y.slice(2)}`;
	}

	onMount(loadRoot);
</script>

<svelte:head><title>Mizan · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader title="Mizan" description="Sedna muhasebe hesaplarının dönem borç / alacak / bakiye özeti — ana hesaptan alt hesaba ve hareketlere kadar." />

	{#if !configured}
		<EmptyState icon={Scale} title="Sedna bağlantısı yok" description="Mizan canlı Sedna muhasebe verisinden gelir; bağlantı (SEDNA_PASSWORD) yapılandırılmamış." />
	{:else}
		<!-- Filtre barı -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3 sm:p-4 flex flex-wrap items-center gap-3">
			<!-- Yıl (◀ önceki / sonraki ▶) -->
			<div class="inline-flex items-center gap-1">
				<button onclick={() => shiftYear(-1)} aria-label="Önceki yıl" title="Önceki yıl"
					class="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 hover:text-teal-700">
					<ChevronLeft size={16} />
				</button>
				<label class="inline-flex items-center gap-1.5 text-sm text-gray-600">
					<Calendar size={15} class="text-gray-400" />
					<Select size="sm" fullWidth={false} bind:value={year} onchange={onYearChange}>
						{#each years as y}<option value={y}>{y}</option>{/each}
					</Select>
				</label>
				<button onclick={() => shiftYear(1)} aria-label="Sonraki yıl" title="Sonraki yıl"
					class="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 hover:text-teal-700">
					<ChevronRight size={16} />
				</button>
			</div>

			<!-- Arama -->
			<div class="relative flex-1 min-w-[180px] max-w-xs">
				<Search size={15} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
				<Input
					size="sm" fullWidth={false} bind:value={search} oninput={onSearch} placeholder="Hesap kodu / adı ara…"
					class="w-full pl-8 pr-8" />
				{#if search}
					<button onclick={clearSearch} aria-label="Temizle" class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"><X size={14} /></button>
				{/if}
			</div>

			<button onclick={() => (search ? runSearch() : loadRoot())} class="ml-auto inline-flex items-center gap-1.5 text-sm text-teal-700 hover:text-teal-800 font-medium">
				<RefreshCw size={15} class={loading ? 'animate-spin' : ''} /> Yenile
			</button>
		</div>

		<!-- Özet kartlar -->
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
			<StatCard label="Toplam Borç" value="₺{fmt(meta.grand_total_borc)}" accent="teal" icon={ArrowDownUp} hint="{year} dönemi" />
			<StatCard label="Toplam Alacak" value="₺{fmt(meta.grand_total_alacak)}" accent="blue" icon={ArrowDownUp} hint="{year} dönemi" />
			<StatCard
				label="Denge"
				value={meta.balanced ? 'Dengeli' : 'Dengesiz'}
				accent={meta.balanced ? 'emerald' : 'red'}
				icon={meta.balanced ? CheckCircle2 : AlertTriangle}
				hint={meta.balanced ? 'Borç = Alacak' : `Fark ₺${fmt(fark)}`} />
			<StatCard label="Hesap" value={String(meta.account_count)} accent="gray" icon={Hash} hint={searchMode ? 'Arama sonucu' : 'Görünen kademe'} />
		</div>

		<!-- Mizan tablosu (ağaç) -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			{#if loading}
				<TableSkeleton rows={8} columns={6} />
			{:else if rows.length === 0}
				<EmptyState icon={Scale} title={searchMode ? 'Sonuç yok' : 'Kayıt yok'} description={searchMode ? 'Aramanıza uyan hesap bulunamadı.' : 'Seçilen dönemde muhasebe hareketi yok.'} />
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm border-collapse">
						<thead>
							<tr class="bg-gray-50 border-b border-gray-200 text-gray-700">
								<th class="text-left font-semibold px-3 py-2.5 min-w-[260px]">Hesap</th>
								<th class="text-right font-semibold px-3 py-2.5 whitespace-nowrap">Borç</th>
								<th class="text-right font-semibold px-3 py-2.5 whitespace-nowrap">Alacak</th>
								<th class="text-right font-semibold px-3 py-2.5 whitespace-nowrap">Borç Bakiye</th>
								<th class="text-right font-semibold px-3 py-2.5 whitespace-nowrap">Alacak Bakiye</th>
								<th class="w-10 px-2 py-2.5"></th>
							</tr>
						</thead>
						<tbody>
							{#each rows as r (r.code)}
								<tr class="border-b border-gray-100 hover:bg-gray-50/60">
									<td class="px-3 py-2">
										<div class="flex items-center gap-1" style="padding-left: {r._level * 18}px">
											{#if r.has_children && !searchMode}
												<button onclick={() => toggleExpand(r)} aria-label="Aç/Kapat" class="shrink-0 p-0.5 text-gray-400 hover:text-teal-700">
													{#if r._loading}
														<Loader2 size={14} class="animate-spin" />
													{:else}
														<ChevronRight size={14} class="transition-transform {r._expanded ? 'rotate-90' : ''}" />
													{/if}
												</button>
											{:else}
												<span class="inline-block w-[18px] shrink-0"></span>
											{/if}
											<span class="font-mono text-xs text-gray-400 tabular-nums shrink-0">{r.code}</span>
											<span class="text-gray-800 truncate {r._level === 0 ? 'font-semibold' : ''}">{r.name || ''}</span>
										</div>
									</td>
									<td class="text-right px-3 py-2 tabular-nums {r.borc ? 'text-gray-700' : 'text-gray-300'}">{r.borc ? fmt(r.borc) : '—'}</td>
									<td class="text-right px-3 py-2 tabular-nums {r.alacak ? 'text-gray-700' : 'text-gray-300'}">{r.alacak ? fmt(r.alacak) : '—'}</td>
									<td class="text-right px-3 py-2 tabular-nums font-medium {r.borc_bakiye ? 'text-gray-900' : 'text-gray-300'}">{r.borc_bakiye ? fmt(r.borc_bakiye) : '—'}</td>
									<td class="text-right px-3 py-2 tabular-nums font-medium {r.alacak_bakiye ? 'text-gray-900' : 'text-gray-300'}">{r.alacak_bakiye ? fmt(r.alacak_bakiye) : '—'}</td>
									<td class="px-2 py-2 text-center">
										<button onclick={() => openTx(r)} title="Hareketler (defter)" class="p-1 text-gray-400 hover:text-teal-700"><BookOpen size={15} /></button>
									</td>
								</tr>
							{/each}
						</tbody>
						<tfoot>
							<tr class="bg-gray-50 border-t-2 border-gray-200 font-semibold text-gray-800">
								<td class="px-3 py-2.5">{searchMode ? 'ARAMA TOPLAMI' : 'GÖRÜNEN TOPLAM'}</td>
								<td class="text-right px-3 py-2.5 tabular-nums">{fmt(viewBorc)}</td>
								<td class="text-right px-3 py-2.5 tabular-nums">{fmt(viewAlacak)}</td>
								<td colspan="3"></td>
							</tr>
						</tfoot>
					</table>
				</div>
			{/if}
		</div>

		<p class="text-[11px] text-gray-500">
			Kaynak: Sedna muhasebe (canlı, fiş tarihine göre) · <span class="font-medium">Ana hesabın yanındaki ›'ye tıkla → alt hesaplar açılır;
			defter ikonu → hesabın hareketleri.</span> Toplam borç = toplam alacak olmalı (çift taraflı kayıt dengesi).
		</p>
	{/if}
</div>

<!-- Drill-down: hesap hareketleri (defter) -->
<Modal bind:show={txOpen} title={txTitle} maxWidth="max-w-3xl">
	{#if txLoading}
		<div class="py-10 text-center text-gray-500 text-sm"><Loader2 class="animate-spin inline" size={20} /> Yükleniyor…</div>
	{:else if !txData || txData.count === 0}
		<p class="py-8 text-center text-gray-500 text-sm">Bu dönemde hareket yok.</p>
	{:else}
		<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 mb-2">
			<span>{txData.count} hareket{txData.truncated ? ' (ilk 1000)' : ''}</span>
			<span>Borç <span class="font-semibold text-gray-700 tabular-nums">₺{fmt(txData.total_debit)}</span></span>
			<span>Alacak <span class="font-semibold text-gray-700 tabular-nums">₺{fmt(txData.total_credit)}</span></span>
			<span>Bakiye <span class="font-semibold {txData.balance >= 0 ? 'text-teal-700' : 'text-red-600'} tabular-nums">₺{fmt(txData.balance)}</span></span>
		</div>
		<div class="max-h-[60vh] overflow-y-auto">
			<table class="w-full text-xs">
				<thead class="sticky top-0 bg-white">
					<tr class="text-gray-400 border-b border-gray-200">
						<th class="text-left font-medium py-1.5 w-16">Tarih</th>
						<th class="text-left font-medium py-1.5 w-12">Fiş</th>
						<th class="text-left font-medium py-1.5">Açıklama</th>
						<th class="text-right font-medium py-1.5 w-24">Borç</th>
						<th class="text-right font-medium py-1.5 w-24">Alacak</th>
						<th class="text-right font-medium py-1.5 w-28">Bakiye</th>
					</tr>
				</thead>
				<tbody>
					{#each txData.transactions as t, i (i)}
						<tr class="border-b border-gray-100">
							<td class="py-1.5 text-gray-500 tabular-nums">{fmtD(t.fiche_date)}</td>
							<td class="py-1.5 text-gray-500">#{t.voucher}</td>
							<td class="py-1.5 text-gray-700">
								<span class="text-gray-400 font-mono">{t.code}</span>
								{t.remark || ''}
							</td>
							<td class="py-1.5 text-right tabular-nums {t.debit ? 'text-gray-800' : 'text-gray-300'}">{t.debit ? fmt(t.debit) : '—'}</td>
							<td class="py-1.5 text-right tabular-nums {t.credit ? 'text-gray-800' : 'text-gray-300'}">{t.credit ? fmt(t.credit) : '—'}</td>
							<td class="py-1.5 text-right tabular-nums {t.balance >= 0 ? 'text-gray-600' : 'text-red-600'}">{fmt(t.balance)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</Modal>
