<script lang="ts">
	import { authState, hasPermission } from '$lib/stores/auth.svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onMount } from 'svelte';
	import Modal from '$lib/components/Modal.svelte';
	import CashFlowTAccount from '$lib/components/CashFlowTAccount.svelte';
	import { CheckCircle2, ArrowRight } from 'lucide-svelte';

	// ── İzinler
	const canFinance = hasPermission('finance.cash_flow');
	const canBanks = hasPermission('finance.banks');
	const canChecks = hasPermission('finance.checks');
	const canCredits = hasPermission('finance.krediler');
	const canCariler = hasPermission('finance.cariler');
	const canAdvances = hasPermission('finance.avanslar');
	const canOccupancy = hasPermission('sales.hotel_reservation');
	const canApproval = hasPermission('system.approval');

	// ── KPI state
	type Kpi = { label: string; value: string; sub: string; href: string; negative?: boolean };
	let kpis = $state<Record<string, Kpi>>({});
	let loading = $state(true);

	// ── Son hareketler + bekleyen onay
	let recent = $state<any[]>([]);
	let pendingCount = $state(0);
	let pendingItems = $state<any[]>([]);
	let onayOpen = $state(false);

	const MODULE_LABELS: Record<string, string> = {
		'finance.krediler': 'Kredi', 'finance.checks': 'Çek', 'finance.avanslar': 'Avans',
		'finance.banks': 'Banka Hesabı', 'finance.butce': 'Bütçe', 'finance.cariler': 'Cari',
		'finance.hakedis': 'Hak Ediş Vadesi', 'accounting.taxes': 'Vergi',
		'accounting.recurring': 'Düzenli Ödeme', 'accounting.rent_income': 'Alınan Kira',
		'accounting.rent_expense': 'Verilen Kira', 'accounting.dividend': 'Temettü',
		'hr.salary': 'Maaş', 'hr.withholding': 'Stopaj', 'hr.sgk': 'SGK',
		'sales.room_types': 'Oda Tipi',
		'system.users': 'Kullanıcı', 'system.roles': 'Rol', 'system.modules': 'Modül',
	};
	const ACTION_LABELS: Record<string, string> = { create: 'Yeni', update: 'Güncelleme', delete: 'Silme' };

	function fmt(n: number): string {
		if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(2).replace('.', ',') + 'M';
		return new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(n);
	}
	function fmtDate(iso: string): string {
		if (!iso) return '';
		const d = new Date(iso);
		return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
	}
	function moduleLabel(code: string): string {
		return MODULE_LABELS[code] ?? code;
	}

	// Bekleyen onay çipleri: modül bazında sayım ("3 Kredi" gibi, ilk 3)
	const pendingChips = $derived.by(() => {
		const byModule: Record<string, number> = {};
		for (const r of pendingItems) {
			const l = moduleLabel(r.module_code ?? r.entity_type ?? '?');
			byModule[l] = (byModule[l] ?? 0) + 1;
		}
		return Object.entries(byModule).sort((a, b) => b[1] - a[1]).slice(0, 3);
	});

	let failedCards = 0;
	function cardError(label: string) {
		return (err: unknown) => {
			console.error(`Panel kartı yüklenemedi (${label}):`, err);
			failedCards++;
		};
	}

	onMount(async () => {
		try {
			const promises: Promise<void>[] = [];

			// Bankalar — blocked_amount düşülerek, EUR karşılığı
			if (canBanks) {
				promises.push(
					Promise.all([
						api.get<any>('/finance/banks/accounts/'),
						api.get<any>('/finance/exchange-rates/latest'),
					]).then(([data, ratesData]) => {
						const accs = data.items ?? data;
						const rates = ratesData.rates || [];
						const eurSelling = rates.find((r: any) => r.currency_code === 'EUR')?.forex_selling;
						const usdSelling = rates.find((r: any) => r.currency_code === 'USD')?.forex_selling;
						const eff = (a: any) => (a.last_balance ?? 0) - (a.blocked_amount ?? 0);
						const totalTRY = accs.filter((a: any) => a.currency === 'TRY').reduce((s: number, a: any) => s + eff(a), 0);
						const totalEUR = accs.filter((a: any) => a.currency === 'EUR').reduce((s: number, a: any) => s + eff(a), 0);
						const totalUSD = accs.filter((a: any) => a.currency === 'USD').reduce((s: number, a: any) => s + eff(a), 0);
						const value = eurSelling > 0
							? `€${fmt(totalTRY / eurSelling + totalEUR + (usdSelling > 0 ? (totalUSD * usdSelling) / eurSelling : 0))}`
							: `₺${fmt(totalTRY)}`;
						kpis.banks = { label: 'Bankalar', value, sub: `${accs.length} hesap`, href: '/dashboard/finans/bankalar' };
					}).catch(cardError('Bankalar'))
				);
			}

			// Doluluk
			if (canOccupancy) {
				promises.push(
					api.get<any>('/sales/reservations/summary').then((d) => {
						const pct = d.kpi?.occupancy_pct;
						if (pct != null) {
							kpis.occupancy = {
								label: 'Doluluk', value: `%${Math.round(pct)}`,
								sub: d.kpi?.total_rez != null ? `${d.kpi.total_rez} rezervasyon` : 'oda doluluk oranı',
								href: '/dashboard/satis/otel-rezervasyon',
							};
						}
					}).catch(cardError('Doluluk'))
				);
			}

			// Avanslar
			if (canAdvances) {
				promises.push(
					Promise.all([
						api.get<any>('/finance/avanslar/summary'),
						api.get<any>('/finance/exchange-rates/latest').catch(() => null),
					]).then(([data, ratesData]) => {
						const eurSelling = ratesData?.rates?.find((r: any) => r.currency_code === 'EUR')?.forex_selling ?? 0;
						const usdSelling = ratesData?.rates?.find((r: any) => r.currency_code === 'USD')?.forex_selling ?? 0;
						let receivedEur = 0, pendingEur = 0, pCount = 0;
						for (const [currency, val] of Object.entries(data) as [string, any][]) {
							const toEur = (a: number) => currency === 'EUR' ? a
								: currency === 'USD' && usdSelling > 0 && eurSelling > 0 ? (a * usdSelling) / eurSelling
								: eurSelling > 0 ? a / eurSelling : 0;
							receivedEur += toEur(val.received ?? 0);
							pendingEur += toEur(val.pending ?? 0);
							pCount += val.pending_count ?? 0;
						}
						kpis.advances = {
							label: 'Avanslar', value: `€${fmt(pendingEur)}`,
							sub: `€${fmt(receivedEur)} alındı · ${pCount} bekleyen`, href: '/dashboard/finans/avanslar',
						};
					}).catch(cardError('Avanslar'))
				);
			}

			// Cariler (borç — kırmızı değer)
			if (canCariler) {
				promises.push(
					api.get<any>('/finance/cariler/vendors/summary').then((d) => {
						const value = d.negative_total_eur != null ? `€${fmt(d.negative_total_eur)}` : `₺${fmt(Math.abs(d.negative_total ?? 0))}`;
						kpis.vendors = { label: 'Cariler', value, sub: `${d.negative_count ?? 0} borçlu cari`, href: '/dashboard/finans/cariler', negative: true };
					}).catch(cardError('Cariler'))
				);
			}

			// Çekler
			if (canChecks) {
				promises.push(
					api.get<any>('/finance/checks/summary').then((d) => {
						kpis.checks = {
							label: 'Çekler',
							value: d.pending_amount_eur != null ? `€${fmt(d.pending_amount_eur)}` : `₺${fmt(d.pending_amount ?? 0)}`,
							sub: [`${d.pending_count ?? 0} bekleyen`, d.overdue_count > 0 ? `${d.overdue_count} vadesi geçmiş` : ''].filter(Boolean).join(' · '),
							href: '/dashboard/finans/cekler',
						};
					}).catch(cardError('Çekler'))
				);
			}

			// Krediler
			if (canCredits) {
				promises.push(
					api.get<any[]>('/finance/krediler/summary/by-type').then((d) => {
						const totalCount = d.reduce((s: number, t: any) => s + (t.count ?? 0), 0);
						const totalEur = d.reduce((s: number, t: any) => s + (t.remaining_amount_eur ?? 0), 0);
						const value = totalEur > 0 ? `€${fmt(totalEur)}` : `₺${fmt(d.reduce((s: number, t: any) => s + (t.remaining_amount ?? 0), 0))}`;
						kpis.credits = { label: 'Krediler', value, sub: `${totalCount} ürün · kalan borç`, href: '/dashboard/finans/krediler' };
					}).catch(cardError('Krediler'))
				);
			}

			// Son hareketler — son 5 GERÇEKLEŞMİŞ kayıt (end_date=bugün: liste vadeli/planlı
			// gelecek kayıtları da içerir, filtresiz ilk 5 en ileri vadeli işlemler olurdu)
			if (canFinance) {
				const today = new Date().toISOString().slice(0, 10);
				promises.push(
					api.get<any>(`/finance/cash-flow/?page_size=5&end_date=${today}`).then((d) => {
						recent = d.items ?? [];
					}).catch(cardError('Son Hareketler'))
				);
			}

			// Bekleyen onaylar
			if (canApproval) {
				promises.push(
					Promise.all([
						api.get<any>('/approval/requests/pending/count').catch(() => null),
						api.get<any>('/approval/requests/pending?page_size=5').catch(() => null),
					]).then(([c, p]) => {
						pendingItems = p?.items ?? [];
						pendingCount = c?.count ?? c?.total ?? p?.total ?? pendingItems.length;
					}).catch(cardError('Bekleyen Onay'))
				);
			}

			await Promise.allSettled(promises);
			if (failedCards > 0) showToast('Bazı panel verileri yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	});

	function getGreeting(): string {
		const hour = new Date().getHours();
		if (hour < 12) return 'Günaydın';
		if (hour < 18) return 'İyi günler';
		return 'İyi akşamlar';
	}
	const todayLabel = new Date().toLocaleDateString('tr-TR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
	const KPI_ORDER = ['banks', 'occupancy', 'advances', 'vendors', 'checks', 'credits'];
</script>

<svelte:head>
	<title>Sprenses - Panel</title>
</svelte:head>

<div class="max-w-6xl mx-auto mt-2 md:mt-4 px-3 sm:px-4 pb-8 flex flex-col gap-5">
	<!-- Karşılama -->
	<div>
		<h1 class="text-xl md:text-2xl text-gray-900">{getGreeting()}, {authState.user?.first_name}</h1>
		<p class="text-sm text-gray-500 mt-1">{todayLabel}</p>
	</div>

	<!-- KPI ızgarası (2 sütun mobil / 3 masaüstü) -->
	{#if loading}
		<div class="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-4">
			{#each Array(6) as _}
				<div class="bg-white rounded-xl border border-gray-200 p-4 animate-pulse">
					<div class="h-3 bg-gray-200 rounded w-16 mb-3"></div>
					<div class="h-6 bg-gray-200 rounded w-24 mb-2"></div>
					<div class="h-3 bg-gray-100 rounded w-20"></div>
				</div>
			{/each}
		</div>
	{:else}
		<div class="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-4">
			{#each KPI_ORDER as key (key)}
				{#if kpis[key]}
					{@const k = kpis[key]}
					<a href={k.href} class="bg-white rounded-xl border border-gray-200 shadow-sm px-4 py-3.5 hover:shadow-md transition-shadow">
						<div class="text-[10px] font-semibold uppercase tracking-[0.5px] text-gray-500">{k.label}</div>
						<div class="tabular-nums text-lg md:text-[22px] font-semibold mt-1 {k.negative ? 'text-red-700' : 'text-teal-700'}">{k.value || '—'}</div>
						<div class="text-xs text-gray-500 mt-1 truncate">{k.sub}</div>
					</a>
				{/if}
			{/each}
		</div>
	{/if}

	<!-- Nakit Akım · T Hesap Cetveli (Nakit Koruma / runway en altında gömülü) -->
	{#if canFinance}
		<CashFlowTAccount />
	{/if}

	<!-- Son Hareketler -->
	{#if canFinance && recent.length > 0}
		<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
			<h3 class="text-base text-gray-900 mb-3">Son Hareketler</h3>
			<div class="space-y-2">
				{#each recent as r (`${r.source}-${r.id}`)}
					<div class="flex items-center gap-2.5 text-sm">
						<span class="w-2 h-2 rounded-full shrink-0 {r.type === 'income' ? 'bg-green-600' : 'bg-red-400'}"></span>
						<span class="text-gray-700 truncate">{r.description}</span>
						<span class="text-gray-500 text-xs shrink-0">· {fmtDate(r.date)}</span>
						<span class="ml-auto tabular-nums text-xs {r.type === 'income' ? 'text-green-700' : 'text-gray-600'} shrink-0">
							{r.type === 'income' ? '+' : '−'}{new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(r.amount)} {r.currency === 'TRY' ? '₺' : r.currency}
						</span>
					</div>
				{/each}
			</div>
			<a href="/dashboard/finans/nakit-akim" class="inline-block mt-3 text-xs font-medium text-teal-600 hover:text-teal-700">Tümünü gör →</a>
		</div>
	{/if}

	<!-- Bekleyen Onay — uzun lacivert kart -->
	{#if canApproval && pendingCount > 0}
		<button type="button" onclick={() => (onayOpen = true)}
			class="w-full text-left bg-teal-700 hover:bg-teal-800 transition-colors rounded-2xl px-5 py-5 sm:px-6 flex flex-wrap items-center gap-4 cursor-pointer">
			<span class="w-10 h-10 rounded-full bg-brass flex items-center justify-center shrink-0">
				<CheckCircle2 size={20} class="text-teal-900" />
			</span>
			<span class="flex items-baseline gap-2.5">
				<span class="text-[10px] font-semibold tracking-[1.5px] text-teal-200 uppercase">Bekleyen Onay</span>
				<span class="tabular-nums text-[28px] leading-none font-semibold text-brass-light">{pendingCount}</span>
				<span class="text-sm text-teal-200">işlem onayınızı bekliyor</span>
			</span>
			<span class="flex flex-wrap gap-2">
				{#each pendingChips as [label, count] (label)}
					<span class="text-xs text-teal-100 bg-white/10 border border-white/15 rounded-full px-3 py-1">{count} {label}</span>
				{/each}
			</span>
			<span class="ml-auto flex items-center gap-1 text-sm font-medium text-brass-light shrink-0">İncele <ArrowRight size={15} /></span>
		</button>
	{/if}
</div>

<!-- Onay Kutusu modalı -->
<Modal bind:show={onayOpen} title="Onay Kutusu" maxWidth="max-w-lg">
	<div class="space-y-1">
		<p class="text-xs text-gray-500 mb-3">
			<span class="inline-block bg-brass-soft text-brass-dark font-medium rounded-full px-2.5 py-0.5">{pendingCount} bekliyor</span>
		</p>
		{#each pendingItems as r (r.id)}
			<div class="flex items-center gap-3 py-2.5 border-t border-gray-100">
				<span class="w-9 h-9 rounded-lg bg-brass-soft flex items-center justify-center shrink-0">
					<CheckCircle2 size={16} class="text-brass-dark" />
				</span>
				<span class="min-w-0">
					<span class="block text-sm font-medium text-gray-900 truncate">
						{moduleLabel(r.module_code ?? r.entity_type ?? '')} · {ACTION_LABELS[r.action_type] ?? r.action_type}
					</span>
					<span class="block text-xs text-gray-500 truncate">
						{r.requester_name ?? r.requested_by_name ?? '—'}{r.requested_at ? ` · ${fmtDate(r.requested_at)}` : ''}
					</span>
				</span>
			</div>
		{/each}
		{#if pendingItems.length === 0}
			<p class="text-sm text-gray-500 py-4">Bekleyen onay talebi yok.</p>
		{/if}
		<a href="/dashboard/sistem/onay-akisi"
			class="mt-3 flex items-center justify-center gap-1.5 w-full rounded-xl bg-teal-50 hover:bg-teal-100 text-teal-700 text-sm font-medium py-2.5 transition-colors">
			Tüm onayları gör <ArrowRight size={14} />
		</a>
	</div>
</Modal>
