<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import { FileText, Users, Trophy, Sigma, RefreshCw, Calendar, ChevronLeft, ChevronRight, Loader2, ChevronDown } from 'lucide-svelte';

	const AY = ['', 'Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const now = new Date();

	// State — filtreler
	let granularity = $state<'month' | 'day'>('month');
	let dateField = $state<'record' | 'fiche'>('record');
	let year = $state(now.getFullYear());
	let month = $state(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`);

	// State — veri
	let loading = $state(true);
	let configured = $state(true);
	let data = $state<any>({ periods: [], users: [], period_totals: {}, grand_total: 0, user_count: 0 });

	// Türetilmiş
	let years = $derived([...new Set([year, ...Array.from({ length: 5 }, (_, i) => now.getFullYear() - i)])].sort((a, b) => b - a));
	let maxCell = $derived(Math.max(1, ...data.users.flatMap((u: any) => Object.values(u.by_period || {}) as number[])));
	let topUser = $derived(data.users[0]);
	let avgPerUser = $derived(data.user_count ? Math.round(data.grand_total / data.user_count) : 0);

	function periodLabel(p: string): string {
		if (granularity === 'month') { const [y, m] = p.split('-'); return `${AY[Number(m)]} ${y.slice(2)}`; }
		return p.slice(8); // gün numarası
	}

	function cellStyle(count: number): string {
		if (!count) return '';
		const a = 0.08 + 0.55 * (count / maxCell);
		return `background-color: rgba(13,148,136,${a.toFixed(3)});`;
	}

	function computeRange(): { start: string; end: string } {
		if (granularity === 'month') return { start: `${year}-01-01`, end: `${year}-12-31` };
		const [y, m] = month.split('-').map(Number);
		const last = new Date(y, m, 0).getDate();
		return { start: `${month}-01`, end: `${month}-${String(last).padStart(2, '0')}` };
	}

	async function load() {
		loading = true;
		try {
			const { start, end } = computeRange();
			const qs = `start_date=${start}&end_date=${end}&granularity=${granularity}&date_field=${dateField}`;
			data = await api.get<any>(`/accounting/fis-icmali/summary?${qs}`);
			configured = true;
		} catch (e: any) {
			console.error('Fiş icmali yüklenemedi:', e);
			if (e?.status === 503) configured = false;
			data = { periods: [], users: [], period_totals: {}, grand_total: 0, user_count: 0 };
		} finally {
			loading = false;
		}
	}

	function setGranularity(g: 'month' | 'day') { if (granularity !== g) { granularity = g; load(); } }
	function setDateField(d: 'record' | 'fiche') { if (dateField !== d) { dateField = d; load(); } }

	// ───── Drill-down: hücre → fiş listesi → fiş satırları ─────
	let drillOpen = $state(false);
	let drillLoading = $state(false);
	let drillLabel = $state('');
	let drillVouchers = $state<any[]>([]);
	let drillTotal = $state(0);
	let drillCount = $state(0);
	let expandedRec = $state<number | null>(null);
	let drillDetail = $state<any>(null);
	let detailLoading = $state(false);

	function periodRange(p: string): { start: string; end: string } {
		if (granularity === 'day') return { start: p, end: p }; // p = YYYY-MM-DD
		const [y, m] = p.split('-').map(Number); // p = YYYY-MM
		const last = new Date(y, m, 0).getDate();
		return { start: `${p}-01`, end: `${p}-${String(last).padStart(2, '0')}` };
	}

	async function openDrill(userCode: string, userName: string, start: string, end: string, label: string) {
		drillOpen = true;
		drillLoading = true;
		drillLabel = label;
		drillVouchers = [];
		drillTotal = 0;
		drillCount = 0;
		expandedRec = null;
		drillDetail = null;
		try {
			const qs = `user_code=${encodeURIComponent(userCode)}&start_date=${start}&end_date=${end}&date_field=${dateField}`;
			const r = await api.get<any>(`/accounting/fis-icmali/vouchers?${qs}`);
			drillVouchers = r.vouchers || [];
			drillTotal = r.total || 0;
			drillCount = r.count || 0;
		} catch (e) {
			console.error('Fişler yüklenemedi:', e);
		} finally {
			drillLoading = false;
		}
	}

	function drillCell(u: any, p: string) {
		if (!(u.by_period[p] || 0)) return;
		const { start, end } = periodRange(p);
		openDrill(u.user_code, u.user_name, start, end, `${u.user_name} · ${periodLabel(p)}`);
	}

	function drillUserTotal(u: any) {
		openDrill(u.user_code, u.user_name, data.start_date, data.end_date,
			`${u.user_name} · ${data.start_date} → ${data.end_date}`);
	}

	async function toggleVoucher(recId: number) {
		if (expandedRec === recId) { expandedRec = null; return; }
		expandedRec = recId;
		drillDetail = null;
		detailLoading = true;
		try {
			drillDetail = await api.get<any>(`/accounting/fis-icmali/voucher-detail?rec_id=${recId}`);
		} catch (e) {
			console.error('Fiş detayı yüklenemedi:', e);
		} finally {
			detailLoading = false;
		}
	}

	function fmtD(s: string | null): string {
		if (!s) return '—';
		const [y, m, d] = s.split('-');
		return `${d}.${m}.${y.slice(2)}`;
	}

	function shiftPeriod(delta: number) {
		if (granularity === 'month') {
			year += delta;
		} else {
			const [y, m] = month.split('-').map(Number);
			const d = new Date(y, m - 1 + delta, 1);
			month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
		}
		load();
	}

	onMount(load);
</script>

<svelte:head><title>Kullanıcı Fiş İcmali · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader title="Kullanıcı Fiş İcmali" description="Sedna muhasebe fişlerini kim, ne zaman, ne kadar kesmiş — gün/ay bazında kullanıcı icmali." />

	{#if !configured}
		<EmptyState icon={FileText} title="Sedna bağlantısı yok" message="Fiş icmali canlı Sedna muhasebe verisinden gelir; bağlantı (SEDNA_PASSWORD) yapılandırılmamış." />
	{:else}
		<!-- Filtre barı -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3 sm:p-4 flex flex-wrap items-center gap-3">
			<!-- Granularite -->
			<div class="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm">
				<button onclick={() => setGranularity('month')} class="px-3 py-1.5 font-medium {granularity === 'month' ? 'bg-teal-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}">Aylık</button>
				<button onclick={() => setGranularity('day')} class="px-3 py-1.5 font-medium border-l border-gray-200 {granularity === 'day' ? 'bg-teal-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}">Günlük</button>
			</div>

			<!-- Dönem seçici (◀ önceki / sonraki ▶) -->
			<div class="inline-flex items-center gap-1">
				<button onclick={() => shiftPeriod(-1)} aria-label="Önceki dönem"
					title={granularity === 'month' ? 'Önceki yıl' : 'Önceki ay'}
					class="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 hover:text-teal-700">
					<ChevronLeft size={16} />
				</button>
				{#if granularity === 'month'}
					<label class="inline-flex items-center gap-1.5 text-sm text-gray-600">
						<Calendar size={15} class="text-gray-400" />
						<select bind:value={year} onchange={load} class="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-teal-500 focus:border-teal-500">
							{#each years as y}<option value={y}>{y}</option>{/each}
						</select>
					</label>
				{:else}
					<label class="inline-flex items-center gap-1.5 text-sm text-gray-600">
						<Calendar size={15} class="text-gray-400" />
						<input type="month" bind:value={month} onchange={load} class="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-teal-500 focus:border-teal-500" />
					</label>
				{/if}
				<button onclick={() => shiftPeriod(1)} aria-label="Sonraki dönem"
					title={granularity === 'month' ? 'Sonraki yıl' : 'Sonraki ay'}
					class="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 hover:text-teal-700">
					<ChevronRight size={16} />
				</button>
			</div>

			<!-- Tarih ekseni -->
			<div class="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm">
				<button onclick={() => setDateField('record')} class="px-3 py-1.5 {dateField === 'record' ? 'bg-teal-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}" title="Fişin sisteme girildiği tarih (üretkenlik)">Kayıt Tarihi</button>
				<button onclick={() => setDateField('fiche')} class="px-3 py-1.5 border-l border-gray-200 {dateField === 'fiche' ? 'bg-teal-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}" title="Fişin muhasebe (fiş) tarihi">Fiş Tarihi</button>
			</div>

			<button onclick={load} class="ml-auto inline-flex items-center gap-1.5 text-sm text-teal-700 hover:text-teal-800 font-medium">
				<RefreshCw size={15} class={loading ? 'animate-spin' : ''} /> Yenile
			</button>
		</div>

		<!-- Özet kartlar -->
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
			<StatCard label="Toplam Fiş" value={data.grand_total.toLocaleString('tr-TR')} accent="teal" icon={FileText} hint={granularity === 'month' ? `${year} yılı` : periodLabel(month + '-01')} />
			<StatCard label="Kullanıcı" value={String(data.user_count)} accent="blue" icon={Users} hint="Fiş kesen" />
			<StatCard label="En Aktif" value={topUser ? topUser.total.toLocaleString('tr-TR') : '–'} accent="amber" icon={Trophy} hint={topUser ? topUser.user_name : '–'} />
			<StatCard label="Ø Kullanıcı Başı" value={avgPerUser.toLocaleString('tr-TR')} accent="gray" icon={Sigma} hint="Ortalama fiş" />
		</div>

		<!-- Pivot tablo -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			{#if loading}
				<div class="py-12 text-center text-gray-400 text-sm">Yükleniyor…</div>
			{:else if data.users.length === 0}
				<EmptyState icon={FileText} title="Kayıt yok" message="Seçilen dönemde fiş kesilmemiş." />
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm border-collapse">
						<thead>
							<tr class="bg-gray-50 border-b border-gray-200">
								<th class="text-left font-semibold text-gray-700 px-3 py-2.5 sticky left-0 bg-gray-50 z-10 min-w-[180px]">Kullanıcı</th>
								{#each data.periods as p (p)}
									<th class="text-center font-medium text-gray-500 px-2 py-2.5 whitespace-nowrap tabular-nums">{periodLabel(p)}</th>
								{/each}
								<th class="text-right font-semibold text-gray-700 px-3 py-2.5 whitespace-nowrap">Toplam</th>
							</tr>
						</thead>
						<tbody>
							{#each data.users as u (u.user_code)}
								<tr class="border-b border-gray-100 hover:bg-gray-50/60">
									<td class="sticky left-0 bg-white z-10 max-w-[200px]">
										<button onclick={() => drillUserTotal(u)} title="Tüm fişlerini gör" class="px-3 py-2 text-left font-medium text-teal-700 hover:text-teal-900 hover:underline truncate w-full">{u.user_name}</button>
									</td>
									{#each data.periods as p (p)}
										{@const c = u.by_period[p] || 0}
										{#if c}
											<td class="p-0 text-center" style={cellStyle(c)}>
												<button onclick={() => drillCell(u, p)} title="Fişleri gör" class="w-full px-2 py-2 tabular-nums text-gray-800 hover:ring-2 hover:ring-teal-500 hover:ring-inset">{c}</button>
											</td>
										{:else}
											<td class="text-center px-2 py-2 tabular-nums text-gray-300">·</td>
										{/if}
									{/each}
									<td class="text-right">
										<button onclick={() => drillUserTotal(u)} title="Tüm fişlerini gör" class="px-3 py-2 font-semibold text-gray-900 hover:text-teal-700 hover:underline tabular-nums">{u.total.toLocaleString('tr-TR')}</button>
									</td>
								</tr>
							{/each}
						</tbody>
						<tfoot>
							<tr class="bg-gray-50 border-t-2 border-gray-200 font-semibold text-gray-800">
								<td class="px-3 py-2.5 sticky left-0 bg-gray-50 z-10">TOPLAM</td>
								{#each data.periods as p (p)}
									<td class="text-center px-2 py-2.5 tabular-nums">{(data.period_totals[p] || 0).toLocaleString('tr-TR')}</td>
								{/each}
								<td class="text-right px-3 py-2.5 tabular-nums text-teal-800">{data.grand_total.toLocaleString('tr-TR')}</td>
							</tr>
						</tfoot>
					</table>
				</div>
			{/if}
		</div>

		<p class="text-[11px] text-gray-400">
			Kaynak: Sedna muhasebe (canlı) · <span class="font-medium">{dateField === 'record' ? 'Kayıt tarihi' : 'Fiş tarihi'}</span> ekseni ·
			koyuluk fiş yoğunluğunu gösterir. <span class="font-medium">Hücreye veya kullanıcıya tıkla → fişleri, fişe tıkla → muhasebe satırlarını gör.</span>
		</p>
	{/if}
</div>

<!-- Drill-down: fiş listesi + fiş satırları -->
<Modal bind:show={drillOpen} title={drillLabel} maxWidth="max-w-2xl">
	{#if drillLoading}
		<div class="py-10 text-center text-gray-400 text-sm"><Loader2 class="animate-spin inline" size={20} /> Yükleniyor…</div>
	{:else if drillVouchers.length === 0}
		<p class="py-8 text-center text-gray-400 text-sm">Bu dönemde fiş yok.</p>
	{:else}
		<div class="text-xs text-gray-500 mb-2">{drillCount} fiş · toplam ₺{drillTotal.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
		<div class="max-h-[60vh] overflow-y-auto -mx-1">
			{#each drillVouchers as v (v.rec_id)}
				<div class="border-b border-gray-100">
					<button onclick={() => toggleVoucher(v.rec_id)} class="w-full flex items-center gap-2 px-1 py-2 text-left hover:bg-gray-50 text-sm">
						<ChevronDown size={14} class="text-gray-400 shrink-0 transition-transform {expandedRec === v.rec_id ? 'rotate-180' : ''}" />
						<span class="text-gray-400 tabular-nums w-14 shrink-0">{fmtD(v.record_date)}</span>
						<span class="font-medium text-gray-700 w-12 shrink-0">#{v.voucher}</span>
						<span class="text-gray-600 truncate flex-1">{v.remark || '—'}</span>
						<span class="font-semibold text-gray-800 tabular-nums shrink-0">₺{v.total.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
					</button>
					{#if expandedRec === v.rec_id}
						<div class="px-7 pb-3 pt-1 bg-gray-50/60">
							{#if detailLoading}
								<div class="py-3 text-center text-gray-400 text-xs"><Loader2 class="animate-spin inline" size={14} /> …</div>
							{:else if drillDetail}
								<div class="text-[11px] text-gray-400 mb-1">Fiş tarihi {fmtD(drillDetail.fiche_date)} · kesen {drillDetail.record_user}{drillDetail.change_user && drillDetail.change_user !== drillDetail.record_user ? ` · değiştiren ${drillDetail.change_user}` : ''}</div>
								<table class="w-full text-xs">
									<thead><tr class="text-gray-400 border-b border-gray-200"><th class="text-left font-medium py-1">Hesap</th><th class="text-right font-medium py-1 w-24">Borç</th><th class="text-right font-medium py-1 w-24">Alacak</th></tr></thead>
									<tbody>
										{#each drillDetail.lines as l, i (i)}
											<tr class="border-b border-gray-100">
												<td class="py-1 text-gray-700"><span class="text-gray-400 tabular-nums">{l.code}</span> {l.account_name || ''}</td>
												<td class="py-1 text-right tabular-nums {l.debit ? 'text-gray-800' : 'text-gray-300'}">{l.debit ? l.debit.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
												<td class="py-1 text-right tabular-nums {l.credit ? 'text-gray-800' : 'text-gray-300'}">{l.credit ? l.credit.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
											</tr>
										{/each}
										<tr class="font-semibold text-gray-700"><td class="py-1 text-right">TOPLAM</td><td class="py-1 text-right tabular-nums">{drillDetail.total_debit.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td><td class="py-1 text-right tabular-nums">{drillDetail.total_credit.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td></tr>
									</tbody>
								</table>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</Modal>
