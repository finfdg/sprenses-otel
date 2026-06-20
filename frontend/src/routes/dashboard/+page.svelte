<script lang="ts">
	import { authState, hasPermission } from '$lib/stores/auth.svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onMount } from 'svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import { Landmark, Scroll, CreditCard, Wallet, Users, TrendingUp, ClipboardCheck, MessageCircle } from 'lucide-svelte';

	// Dashboard özet verileri
	let bankTotal = $state<string>('');
	let bankSublabel = $state<string>('');
	let checksAmount = $state<string>('');
	let checksSublabel = $state<string>('');
	let checksDetail = $state<string>('');
	let creditAmount = $state<string>('');
	let creditSublabel = $state<string>('');
	let creditDetail = $state<string>('');
	let vendorAmount = $state<string>('');
	let vendorSublabel = $state<string>('');
	let advancesAmount = $state<string>('');
	let advancesSublabel = $state<string>('');
	let advancesDetail = $state<string>('');
	let eurRate = $state<string>('');
	let eurUsdParity = $state<string>('');
	let loading = $state(true);

	const canFinance = hasPermission('finance.cash_flow');
	const canBanks = hasPermission('finance.banks');
	const canChecks = hasPermission('finance.checks');
	const canCredits = hasPermission('finance.krediler');
	const canCariler = hasPermission('finance.cariler');
	const canAdvances = hasPermission('finance.avanslar');
	const canDoviz = hasPermission('finance.doviz');
	const canQuality = hasPermission('quality.forms');

	function fmt(n: number): string {
		if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1).replace('.0', '') + 'M';
		if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + 'K';
		return n.toFixed(0);
	}

	// Kart bazlı veri hatası: konsola logla, sayfa sonunda tek toast göster (kart başına toast spam'i yok)
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

			// Banka verileri — blocked_amount düşülerek hesaplanır (Nakit Akım ile tutarlı)
			if (canBanks) {
				promises.push(
					Promise.all([
						api.get<any>('/finance/banks/accounts/'),
						api.get<any>('/finance/exchange-rates/latest')
					]).then(([data, ratesData]) => {
						const accs = data.items ?? data;
						const rates = ratesData.rates || [];
						const eurSelling = rates.find((r: any) => r.currency_code === 'EUR')?.forex_selling;
						const usdSelling = rates.find((r: any) => r.currency_code === 'USD')?.forex_selling;

						const eff = (a: any) => (a.last_balance ?? 0) - (a.blocked_amount ?? 0);
						const totalTRY = accs.filter((a: any) => a.currency === 'TRY').reduce((s: number, a: any) => s + eff(a), 0);
						const totalEUR = accs.filter((a: any) => a.currency === 'EUR').reduce((s: number, a: any) => s + eff(a), 0);
						const totalUSD = accs.filter((a: any) => a.currency === 'USD').reduce((s: number, a: any) => s + eff(a), 0);

						if (eurSelling > 0) {
							const tryAsEur = totalTRY / eurSelling;
							const usdAsEur = usdSelling > 0 ? (totalUSD * usdSelling) / eurSelling : 0;
							const grandTotalEur = tryAsEur + totalEUR + usdAsEur;
							bankTotal = `€${fmt(grandTotalEur)}`;
						} else {
							bankTotal = `₺${fmt(totalTRY)}`;
						}
						bankSublabel = `${accs.length} hesap`;

						if (eurSelling) eurRate = Number(eurSelling).toFixed(4);
						if (eurSelling && usdSelling && usdSelling > 0) eurUsdParity = (eurSelling / usdSelling).toFixed(4);
					}).catch(cardError('Bankalar'))
				);
			}

			// Çekler
			if (canChecks) {
				promises.push(
					api.get<any>('/finance/checks/summary').then(data => {
						checksAmount = data.pending_amount_eur != null ? `€${fmt(data.pending_amount_eur)}` : `₺${fmt(data.pending_amount ?? 0)}`;
						checksSublabel = `${data.pending_count ?? 0} bekleyen`;
						checksDetail = data.overdue_count > 0 ? `${data.overdue_count} vadesi geçmiş` : '';
					}).catch(cardError('Çekler'))
				);
			}

			// Krediler
			if (canCredits) {
				promises.push(
					api.get<any[]>('/finance/krediler/summary/by-type').then(data => {
						const totalCount = data.reduce((s: number, t: any) => s + (t.count ?? 0), 0);
						const totalEur = data.reduce((s: number, t: any) => s + (t.remaining_amount_eur ?? 0), 0);
						if (totalEur > 0) {
							creditAmount = `€${fmt(totalEur)}`;
						} else {
							const totalRemaining = data.reduce((s: number, t: any) => s + (t.remaining_amount ?? 0), 0);
							creditAmount = `₺${fmt(totalRemaining)}`;
						}
						creditSublabel = `${totalCount} ürün`;
						creditDetail = 'kalan borç';
					}).catch(cardError('Krediler'))
				);
			}

			// Döviz kurları (banka yoksa ayrı çek)
			if (canDoviz && !canBanks) {
				promises.push(
					api.get<any>('/finance/exchange-rates/latest').then(data => {
						const rates = data.rates || [];
						const usdSelling = rates.find((r: any) => r.currency_code === 'USD')?.forex_selling;
						const eurSelling = rates.find((r: any) => r.currency_code === 'EUR')?.forex_selling;
						if (eurSelling) eurRate = Number(eurSelling).toFixed(4);
						if (eurSelling && usdSelling && usdSelling > 0) eurUsdParity = (eurSelling / usdSelling).toFixed(4);
					}).catch(cardError('Döviz'))
				);
			}

			// Cariler — EUR cinsinden (Nakit Akım ile tutarlı)
			if (canCariler) {
				promises.push(
					api.get<any>('/finance/cariler/vendors/summary').then(data => {
						if (data.negative_total_eur != null) {
							vendorAmount = `€${fmt(data.negative_total_eur)}`;
						} else {
							vendorAmount = `₺${fmt(Math.abs(data.negative_total ?? 0))}`;
						}
						vendorSublabel = `${data.negative_count ?? 0} borçlu cari`;
					}).catch(cardError('Cariler'))
				);
			}

			// Avanslar — /summary endpoint (Nakit Akım ile tutarlı)
			if (canAdvances) {
				promises.push(
					Promise.all([
						api.get<any>('/finance/avanslar/summary'),
						api.get<any>('/finance/exchange-rates/latest').catch(() => null),
					]).then(([data, ratesData]) => {
						const eurSelling = ratesData?.rates?.find((r: any) => r.currency_code === 'EUR')?.forex_selling ?? 0;
						const usdSelling = ratesData?.rates?.find((r: any) => r.currency_code === 'USD')?.forex_selling ?? 0;

						let receivedEur = 0;
						let pendingEur = 0;
						let pendingCount = 0;

						for (const [currency, val] of Object.entries(data) as [string, any][]) {
							const toEur = (amount: number) => {
								if (currency === 'EUR') return amount;
								if (currency === 'USD' && usdSelling > 0 && eurSelling > 0) return (amount * usdSelling) / eurSelling;
								if (eurSelling > 0) return amount / eurSelling;
								return 0;
							};
							receivedEur += toEur(val.received ?? 0);
							pendingEur += toEur(val.pending ?? 0);
							pendingCount += val.pending_count ?? 0;
						}

						advancesAmount = `€${fmt(receivedEur)}`;
						advancesSublabel = `€${fmt(pendingEur)} alındı`;
						advancesDetail = `${pendingCount} bekleyen`;
					}).catch(cardError('Avanslar'))
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
</script>

<svelte:head>
	<title>Sprenses - Panel</title>
</svelte:head>

<div class="max-w-6xl mx-auto mt-2 md:mt-4 px-3 sm:px-4">
	<!-- Karşılama -->
	<div class="mb-5 md:mb-6">
		<h1 class="text-2xl font-semibold text-gray-900">
			{getGreeting()}, {authState.user?.first_name}!
		</h1>
		<p class="text-sm text-gray-500 mt-1">İşte bugünkü genel bakış</p>
	</div>

	{#if loading}
		<div class="flex flex-wrap gap-3 md:gap-4">
			{#each Array(5) as _}
				<div class="bg-white rounded-2xl border border-gray-200 p-4 md:p-5 animate-pulse flex-1 min-w-[140px]">
					<div class="h-3 bg-gray-200 rounded w-20 mb-3"></div>
					<div class="h-6 bg-gray-200 rounded w-28 mb-2"></div>
					<div class="h-3 bg-gray-100 rounded w-16"></div>
				</div>
			{/each}
		</div>
	{:else}
		<!-- Döviz Kurları Bandı -->
		{#if eurRate || eurUsdParity}
			<div class="flex items-center gap-2 sm:gap-4 mb-4 md:mb-5 px-1">
				{#if eurRate}
					<div class="flex items-center gap-2 text-sm">
						<span class="text-blue-600 font-bold">€</span>
						<span class="text-gray-600 font-medium">EUR/TRY</span>
						<span class="font-bold text-gray-800">₺{eurRate}</span>
					</div>
				{/if}
				{#if eurUsdParity}
					<div class="flex items-center gap-2 text-sm">
						<span class="text-amber-600 font-bold">€/$</span>
						<span class="text-gray-600 font-medium">EUR/USD</span>
						<span class="font-bold text-gray-800">{eurUsdParity}</span>
					</div>
				{/if}
				<a href="/dashboard/finans/doviz" class="text-xs text-teal-600 hover:text-teal-700 ml-auto">Detay →</a>
			</div>
		{/if}

		<!-- Özet Kartlar -->
		<div class="flex flex-wrap gap-3 md:gap-4 mb-5 md:mb-6">
			{#if canBanks}
				<StatCard class="flex-1 min-w-[140px]" href="/dashboard/finans/bankalar" label="Bankalar" value={bankTotal || '—'} accent="teal" icon={Landmark} hint={bankSublabel} />
			{/if}
			{#if canChecks}
				<StatCard class="flex-1 min-w-[140px]" href="/dashboard/finans/cekler" label="Çekler" value={checksAmount || '—'} accent="amber" icon={Scroll} hint={[checksSublabel, checksDetail].filter(Boolean).join(' · ')} />
			{/if}
			{#if canCredits}
				<StatCard class="flex-1 min-w-[140px]" href="/dashboard/finans/krediler" label="Krediler" value={creditAmount || '—'} accent="amber" icon={CreditCard} hint={[creditSublabel, creditDetail].filter(Boolean).join(' · ')} />
			{/if}
			{#if canAdvances}
				<StatCard class="flex-1 min-w-[140px]" href="/dashboard/finans/avanslar" label="Avanslar" value={advancesAmount || '—'} accent="blue" icon={Wallet} hint={[advancesSublabel, advancesDetail].filter(Boolean).join(' · ')} />
			{/if}
			{#if canCariler}
				<StatCard class="flex-1 min-w-[140px]" href="/dashboard/finans/cariler" label="Cariler" value={vendorAmount || '—'} accent="red" icon={Users} hint={vendorSublabel} />
			{/if}
		</div>

		<!-- Hızlı Erişim -->
		<div class="mb-5 md:mb-6">
			<h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3 px-1">Hızlı Erişim</h2>
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 md:gap-3">
				{#if canFinance}
					<a href="/dashboard/finans/nakit-akim" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all touch-target">
						<TrendingUp class="w-5 h-5 text-teal-600 shrink-0" />
						<span class="text-sm font-medium text-gray-700">Nakit Akım</span>
					</a>
				{/if}
				{#if canBanks}
					<a href="/dashboard/finans/bankalar" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all touch-target">
						<Landmark class="w-5 h-5 text-teal-600 shrink-0" />
						<span class="text-sm font-medium text-gray-700">Bankalar</span>
					</a>
				{/if}
				{#if canQuality}
					<a href="/dashboard/kalite/formlar" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all touch-target">
						<ClipboardCheck class="w-5 h-5 text-teal-600 shrink-0" />
						<span class="text-sm font-medium text-gray-700">Kalite Formları</span>
					</a>
				{/if}
				<a href="/dashboard/mesajlasma" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all touch-target">
					<MessageCircle class="w-5 h-5 text-teal-600 shrink-0" />
					<span class="text-sm font-medium text-gray-700">Mesajlaşma</span>
				</a>
			</div>
		</div>
	{/if}
</div>
