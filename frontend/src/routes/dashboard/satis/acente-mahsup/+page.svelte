<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { useLiveRefetch } from '$lib/utils/liveRefetch.svelte';
	import { BROADCAST_MODULE } from '$lib/constants/realtime';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Button from '$lib/components/Button.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import OccupancyPanel from '$lib/components/sales/OccupancyPanel.svelte';
	import AgencyDistributionPanel from '$lib/components/sales/AgencyDistributionPanel.svelte';
	import DailyMovesPanel from '$lib/components/sales/DailyMovesPanel.svelte';
	import SalesCashFlowPanel from '$lib/components/sales/SalesCashFlowPanel.svelte';
	import ReservationsPanel from '$lib/components/sales/ReservationsPanel.svelte';
	import RoomTypesPanel from '$lib/components/sales/RoomTypesPanel.svelte';
	import KontratlarPanel from '$lib/components/sales/KontratlarPanel.svelte';
	import { Inbox, CalendarCheck2, Gauge, CalendarRange } from 'lucide-svelte';
	import { MONTHS_FULL_TR, trInt } from '$lib/utils/salesDesign';

	// ── Sabitler ─────────────────────────────────────────────
	// Basit tasarım (2026-07-19, finfdg yüklemesi): 4 ana sekme — Doluluk · Acenteler ·
	// Günlük Hareketler · Nakit Akım. Tasarımda karşılığı olmayan işlevsel paneller
	// (Rezervasyonlar detay/yükleme, Oda Tipleri, Kontratlar) sekme olarak korunur.
	// Eski Genel Bakış / Rezervasyon & Ciro / Avanslar / Faturalar / eski Nakit Akım
	// sekmeleri yeni Nakit Akım + Acenteler sekmelerinde birleştirildi.
	const TABS = [
		{ value: 'doluluk', label: 'Doluluk' },
		{ value: 'acente', label: 'Acenteler' },
		{ value: 'hareket', label: 'Günlük Hareketler' },
		{ value: 'nakit', label: 'Nakit Akım' },
		{ value: 'rezervasyon', label: 'Rezervasyonlar' },
		{ value: 'oda', label: 'Oda Tipleri' },
		// Kontratlar sekmesi AYRI izin kodudur (sales.kontratlar) — görünürlük aşağıda filtrelenir
		{ value: 'kontrat', label: 'Kontratlar' },
	];
	const NOW_YEAR = new Date().getFullYear();
	const YEARS = [NOW_YEAR - 1, NOW_YEAR, NOW_YEAR + 1];

	// ── Türetilmiş ───────────────────────────────────────────
	let canConfig = $derived(hasPermission('sales.acente_mahsup', 'use'));
	// Kontratlar sekmesi ayrı modül izniyle görünür (sales.kontratlar view)
	let visibleTabs = $derived(
		hasPermission('sales.kontratlar', 'view') ? TABS : TABS.filter((t) => t.value !== 'kontrat')
	);

	// ── State ────────────────────────────────────────────────
	let activeTab = $state('doluluk');
	// Sekmeler tembel mount edilir, ziyaret edilince mount kalır (state korunur)
	let visitedTabs = $state(new Set<string>(['doluluk']));
	let year = $state(NOW_YEAR); // tüm sekmelerin ortak yıl seçimi (tasarım: tek year state)
	let overview = $state<any>(null); // occupancy-overview (chip'ler + Doluluk paneli)
	let overviewLoading = $state(true);
	let tick = $state(0); // canlı yenileme tetiği — panel fetch'leri $effect ile dinler
	let chipIdx = $state(0); // mobil chip kaydırma göstergesi

	// Ayarlar modalı (acente vade + kickback — Tahsilat Takvimi'nin vade girdisi)
	let showSettings = $state(false);
	let groups = $state<any[]>([]);
	let groupsLoading = $state(false);
	let savingId = $state<number | null>(null);

	// ── Veri fonksiyonları ───────────────────────────────────
	async function loadOverview() {
		overviewLoading = true;
		try {
			overview = await api.get<any>(`/sales/reservations/occupancy-overview?year=${year}`);
		} catch (e) {
			console.error('Doluluk özeti yüklenemedi:', e);
			showToast('Doluluk özeti yüklenemedi', 'error');
		} finally {
			overviewLoading = false;
		}
	}

	// Yıl değişince doluluk özetini yeniden çek (chip 3 + Doluluk paneli aynı veriyi kullanır)
	$effect(() => {
		const _y = year;
		loadOverview();
	});

	// ── UI yardımcıları ──────────────────────────────────────
	function selectTab(v: string) {
		activeTab = v;
		if (!visitedTabs.has(v)) visitedTabs = new Set([...visitedTabs, v]);
		// Deep-link: ?tab= parametresini güncelle (sayfa yeniden yüklenmeden)
		try {
			const url = new URL(window.location.href);
			if (v === 'doluluk') url.searchParams.delete('tab');
			else url.searchParams.set('tab', v);
			replaceState(url, {});
		} catch (e) {
			console.error('Sekme URL güncellenemedi:', e);
		}
	}

	function setYear(y: number) {
		year = y;
	}

	function onChipsScroll(e: Event) {
		const el = e.currentTarget as HTMLElement;
		const i = Math.max(0, Math.min(2, Math.round(el.scrollLeft / Math.max(1, el.clientWidth * 0.86))));
		if (i !== chipIdx) chipIdx = i;
	}

	// ── Ayarlar (vade + kickback) ────────────────────────────
	async function openSettings() {
		showSettings = true;
		groupsLoading = true;
		try {
			const rows = await api.get<any[]>('/sales/agency-groups/');
			groups = rows.map((g) => ({ ...g, kickback_percent: Number(g.kickback_percent) || 0 }));
		} catch (e) {
			console.error('Acente grupları yüklenemedi:', e);
			showToast('Acente grupları yüklenemedi', 'error');
		} finally {
			groupsLoading = false;
		}
	}

	async function saveGroup(g: any) {
		savingId = g.id;
		try {
			await api.patch(`/sales/agency-groups/${g.id}`, {
				term_days: Math.round(g.term_days),
				kickback_percent: g.kickback_percent ?? 0,
			});
			showToast(`${g.name} ayarları kaydedildi`, 'success');
			markReload(); // endpoint AGENCY_GROUPS broadcast'i yayar — yankı çift yükleme yapmasın
			tick += 1;
		} catch (e) {
			console.error('Ayar kaydedilemedi:', e);
			showToast('Ayar kaydedilemedi', 'error');
		} finally {
			savingId = null;
		}
	}

	// ── Canlı yenileme ───────────────────────────────────────
	// Doluluk/Acenteler/Nakit Akım rezervasyon + avans + fatura + grup verisinden türediğinden
	// hem sales hem finance yayınlarını dinler. ReservationsPanel/RoomTypesPanel/KontratlarPanel
	// KENDİ aboneliğiyle tazelenir; burada overview + panel tetiği (tick) yenilenir.
	const { markReload } = useLiveRefetch({
		modules: [BROADCAST_MODULE.SALES_INVOICES, BROADCAST_MODULE.ADVANCES],
		salesModules: [
			BROADCAST_MODULE.HOTEL_RESERVATION,
			BROADCAST_MODULE.ROOM_TYPES,
			BROADCAST_MODULE.AGENCY_GROUPS,
		],
		reload: () => {
			loadOverview();
			tick += 1;
		},
	});

	// ── Yaşam döngüsü ────────────────────────────────────────
	onMount(() => {
		// Deep-link: ?tab=nakit vb. ile doğrudan sekme açılır
		try {
			const wanted = new URL(window.location.href).searchParams.get('tab');
			if (wanted && TABS.some((t) => t.value === wanted)) selectTab(wanted);
		} catch (e) {
			console.error('Sekme parametresi okunamadı:', e);
		}
	});

	// ── Görsel yardımcılar (chip'ler) ────────────────────────
	let chips = $derived.by(() => {
		if (!overview) return [];
		const t = new Date(overview.today + 'T00:00:00');
		const cm = overview.current_month;
		return [
			{
				icon: CalendarCheck2,
				label: `Bugün · ${t.getDate()} ${MONTHS_FULL_TR[t.getMonth()]}`,
				value: `%${Math.round(overview.today_pct)}`,
				hint: `${trInt(overview.today_rooms)} / ${trInt(overview.capacity)} oda`,
			},
			{
				icon: Gauge,
				label: `${MONTHS_FULL_TR[cm.month - 1]} ortalaması`,
				value: `%${Math.round(cm.occupancy_pct)}`,
				hint: `${trInt(cm.room_nights)} oda-gece`,
			},
			{
				icon: CalendarRange,
				label: `${year} ortalaması`,
				value: `%${Math.round(overview.year_pct)}`,
				hint: `12 ay · ${trInt(overview.year_capacity_nights)} oda-gece kapasite`,
			},
		];
	});
</script>

<svelte:head><title>Acente Mahsup & Nakit Akım · Sprenses</title></svelte:head>

<div class="space-y-5">
	<PageHeader title="Acente Mahsup & Nakit Akım" />

	<!-- Doluluk özet kartları (yalnız Doluluk sekmesinde; mobilde yatay kaydırma + nokta) -->
	{#if activeTab === 'doluluk' && chips.length > 0}
		<div>
			<div
				class="chips-scroll flex snap-x snap-mandatory gap-3 overflow-x-auto sm:grid sm:snap-none sm:grid-cols-3 sm:overflow-visible"
				onscroll={onChipsScroll}
			>
				{#each chips as c (c.label)}
					<StatCard
						icon={c.icon}
						accent="teal"
						label={c.label}
						value={c.value}
						hint={c.hint}
						class="min-w-[86%] snap-start sm:min-w-0"
					/>
				{/each}
			</div>
			<div class="mt-2 flex justify-center gap-1.5 sm:hidden" aria-hidden="true">
				{#each chips as c, i (c.label)}
					<span
						class="h-1.5 rounded-full transition-all {i === chipIdx ? 'w-4 bg-teal-700' : 'w-1.5 bg-gray-300'}"
					></span>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Sekme barı (alt-çizgili, tasarım deseni; dar ekranda yatay kaydırma) -->
	<div class="overflow-x-auto border-b border-gray-200" role="tablist" aria-label="Sekmeler">
		<div class="flex min-w-max gap-5 px-0.5">
			{#each visibleTabs as t (t.value)}
				<button
					type="button"
					role="tab"
					aria-selected={activeTab === t.value}
					class="-mb-px whitespace-nowrap border-b-2 px-0.5 pb-2.5 pt-1.5 text-sm font-semibold transition-colors {activeTab === t.value
						? 'border-teal-700 text-teal-700'
						: 'border-transparent text-gray-500 hover:text-gray-700'}"
					onclick={() => selectTab(t.value)}
				>{t.label}</button>
			{/each}
		</div>
	</div>

	<!-- Sekme içerikleri (keep-alive: ziyaret edilince mount kalır) -->
	{#if visitedTabs.has('doluluk')}
		<div class={activeTab === 'doluluk' ? '' : 'hidden'}>
			<OccupancyPanel {overview} loading={overviewLoading} {year} yearOpts={YEARS} onYear={setYear} />
		</div>
	{/if}
	{#if visitedTabs.has('acente')}
		<div class={activeTab === 'acente' ? '' : 'hidden'}>
			<AgencyDistributionPanel {year} yearOpts={YEARS} onYear={setYear} {tick} {canConfig} onSettings={openSettings} />
		</div>
	{/if}
	{#if visitedTabs.has('hareket')}
		<div class={activeTab === 'hareket' ? '' : 'hidden'}><DailyMovesPanel {tick} /></div>
	{/if}
	{#if visitedTabs.has('nakit')}
		<div class={activeTab === 'nakit' ? '' : 'hidden'}>
			<SalesCashFlowPanel {year} yearOpts={YEARS} onYear={setYear} {tick} />
		</div>
	{/if}
	{#if visitedTabs.has('rezervasyon')}
		<div class={activeTab === 'rezervasyon' ? '' : 'hidden'}><ReservationsPanel /></div>
	{/if}
	{#if visitedTabs.has('oda')}
		<div class={activeTab === 'oda' ? '' : 'hidden'}><RoomTypesPanel /></div>
	{/if}
	{#if visitedTabs.has('kontrat')}
		<div class={activeTab === 'kontrat' ? '' : 'hidden'}><KontratlarPanel /></div>
	{/if}
</div>

<!-- Acente Ayarları Modalı (vade + kickback — Nakit Akım tahsilat vadelerinin girdisi) -->
<Modal bind:show={showSettings} title="Acente Ayarları — Vade & Kickback" maxWidth="max-w-2xl">
	{#if groupsLoading}
		<TableSkeleton rows={4} columns={3} />
	{:else if groups.length === 0}
		<EmptyState icon={Inbox} title="Acente grubu yok" description="Önce Rezervasyonlar sekmesindeki Grupları Yönet ile acente grupları oluşturun." />
	{:else}
		<p class="mb-3 text-sm text-gray-600">Her acente grubunun tahsilat vadesini (gün) ve yıl sonu kickback oranını (%) ayarlayın.</p>
		<div class="space-y-2">
			{#each groups as g (g.id)}
				<div class="flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 p-3">
					<span class="min-w-[120px] flex-1 font-medium">{g.name}</span>
					<label class="flex items-center gap-2 text-sm">
						<span class="text-gray-600">Vade</span>
						<input type="number" min="0" max="365" bind:value={g.term_days}
							class="w-20 rounded-lg border border-gray-300 px-2 py-1.5 text-right tabular-nums focus:ring-2 focus:ring-teal-500" />
						<span class="text-gray-500">gün</span>
					</label>
					<label class="flex items-center gap-2 text-sm">
						<span class="text-gray-600">Kickback</span>
						<div class="w-24"><MoneyInput bind:value={g.kickback_percent} currency="%" min={0} decimals={1} /></div>
					</label>
					<Button size="sm" variant="secondary" loading={savingId === g.id} onclick={() => saveGroup(g)}>Kaydet</Button>
				</div>
			{/each}
		</div>
	{/if}
</Modal>

<style>
	.chips-scroll {
		scrollbar-width: none;
	}
	.chips-scroll::-webkit-scrollbar {
		display: none;
	}
</style>
