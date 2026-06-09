<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { FileText, Users, Trophy, Sigma, RefreshCw, Calendar } from 'lucide-svelte';

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
	let years = $derived(Array.from({ length: 5 }, (_, i) => now.getFullYear() - i));
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

			<!-- Dönem seçici -->
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
									<td class="px-3 py-2 text-gray-800 sticky left-0 bg-white z-10 font-medium truncate max-w-[200px]" title={u.user_name}>{u.user_name}</td>
									{#each data.periods as p (p)}
										{@const c = u.by_period[p] || 0}
										<td class="text-center px-2 py-2 tabular-nums {c ? 'text-gray-800' : 'text-gray-300'}" style={cellStyle(c)}>{c || '·'}</td>
									{/each}
									<td class="text-right px-3 py-2 font-semibold text-gray-900 tabular-nums">{u.total.toLocaleString('tr-TR')}</td>
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
			koyuluk fiş yoğunluğunu gösterir. "Kayıt tarihi" fişin sisteme girildiği günü (kim ne zaman çalışmış), "Fiş tarihi" muhasebe dönemini verir.
		</p>
	{/if}
</div>
