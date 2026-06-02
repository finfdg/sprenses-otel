<script lang="ts">
	import { authState, hasPermission } from '$lib/stores/auth.svelte';
	import { api } from '$lib/api';
	import { onMount } from 'svelte';

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
					}).catch(() => {})
				);
			}

			// Çekler
			if (canChecks) {
				promises.push(
					api.get<any>('/finance/checks/summary').then(data => {
						checksAmount = data.pending_amount_eur != null ? `€${fmt(data.pending_amount_eur)}` : `₺${fmt(data.pending_amount ?? 0)}`;
						checksSublabel = `${data.pending_count ?? 0} bekleyen`;
						checksDetail = data.overdue_count > 0 ? `${data.overdue_count} vadesi geçmiş` : '';
					}).catch(() => {})
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
					}).catch(() => {})
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
					}).catch(() => {})
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
					}).catch(() => {})
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
					}).catch(() => {})
				);
			}

			await Promise.allSettled(promises);
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
				<div class="bg-white rounded-xl border border-gray-100 p-4 md:p-5 animate-pulse flex-1 min-w-[140px]">
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
			<!-- Bankalar -->
			{#if canBanks}
				<a href="/dashboard/finans/bankalar" class="group bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-md p-4 md:p-5 transition-all flex-1 min-w-[140px]">
					<div class="flex items-center gap-2 mb-2">
						<div class="w-8 h-8 rounded-lg bg-teal-50 flex items-center justify-center">
							<svg class="w-4 h-4 text-teal-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0012 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75z" />
							</svg>
						</div>
						<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Bankalar</span>
					</div>
					<div class="text-lg md:text-xl font-bold text-gray-800">
						{bankTotal || '—'}
					</div>
					<p class="text-xs text-gray-500 mt-1">{bankSublabel}</p>
				</a>
			{/if}

			<!-- Çekler -->
			{#if canChecks}
				<a href="/dashboard/finans/cekler" class="group bg-white rounded-xl border border-gray-100 hover:border-amber-200 hover:shadow-md p-4 md:p-5 transition-all flex-1 min-w-[140px]">
					<div class="flex items-center gap-2 mb-2">
						<div class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
							<svg class="w-4 h-4 text-amber-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25z" />
							</svg>
						</div>
						<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Çekler</span>
					</div>
					<div class="text-lg md:text-xl font-bold text-gray-800">
						{checksAmount || '—'}
					</div>
					<p class="text-xs text-gray-500 mt-1">{checksSublabel}</p>
					{#if checksDetail}
						<p class="text-xs text-amber-600 mt-0.5">{checksDetail}</p>
					{/if}
				</a>
			{/if}

			<!-- Krediler -->
			{#if canCredits}
				<a href="/dashboard/finans/krediler" class="group bg-white rounded-xl border border-gray-100 hover:border-amber-200 hover:shadow-md p-4 md:p-5 transition-all flex-1 min-w-[140px]">
					<div class="flex items-center gap-2 mb-2">
						<div class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
							<svg class="w-4 h-4 text-amber-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
							</svg>
						</div>
						<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Krediler</span>
					</div>
					<div class="text-lg md:text-xl font-bold text-gray-800">
						{creditAmount || '—'}
					</div>
					<p class="text-xs text-gray-500 mt-1">{creditSublabel}</p>
					{#if creditDetail}
						<p class="text-xs text-amber-600 mt-0.5">{creditDetail}</p>
					{/if}
				</a>
			{/if}

			<!-- Avanslar -->
			{#if canAdvances}
				<a href="/dashboard/finans/avanslar" class="group bg-white rounded-xl border border-gray-100 hover:border-purple-200 hover:shadow-md p-4 md:p-5 transition-all flex-1 min-w-[140px]">
					<div class="flex items-center gap-2 mb-2">
						<div class="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
							<svg class="w-4 h-4 text-purple-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
							</svg>
						</div>
						<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Avanslar</span>
					</div>
					<div class="text-lg md:text-xl font-bold text-gray-800">
						{advancesAmount || '—'}
					</div>
					<p class="text-xs text-gray-500 mt-1">{advancesSublabel}</p>
					{#if advancesDetail}
						<p class="text-xs text-purple-600 mt-0.5">{advancesDetail}</p>
					{/if}
				</a>
			{/if}

			<!-- Cariler -->
			{#if canCariler}
				<a href="/dashboard/finans/cariler" class="group bg-white rounded-xl border border-gray-100 hover:border-red-200 hover:shadow-md p-4 md:p-5 transition-all flex-1 min-w-[140px]">
					<div class="flex items-center gap-2 mb-2">
						<div class="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
							<svg class="w-4 h-4 text-red-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
							</svg>
						</div>
						<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Cariler</span>
					</div>
					<div class="text-lg md:text-xl font-bold text-gray-800">
						{vendorAmount || '—'}
					</div>
					<p class="text-xs text-gray-500 mt-1">{vendorSublabel}</p>
				</a>
			{/if}
		</div>

		<!-- Hızlı Erişim -->
		<div class="mb-5 md:mb-6">
			<h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3 px-1">Hızlı Erişim</h2>
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 md:gap-3">
				{#if canFinance}
					<a href="/dashboard/finans/nakit-akim" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all">
						<svg class="w-5 h-5 text-teal-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
						</svg>
						<span class="text-sm font-medium text-gray-700">Nakit Akım</span>
					</a>
				{/if}
				{#if canBanks}
					<a href="/dashboard/finans/bankalar" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all">
						<svg class="w-5 h-5 text-teal-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path stroke-linecap="round" stroke-linejoin="round" d="M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0012 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75z" />
						</svg>
						<span class="text-sm font-medium text-gray-700">Bankalar</span>
					</a>
				{/if}
				{#if canQuality}
					<a href="/dashboard/kalite/formlar" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all">
						<svg class="w-5 h-5 text-teal-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path stroke-linecap="round" stroke-linejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 019 9v.375M10.125 2.25A3.375 3.375 0 0113.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 013.375 3.375M9 15l2.25 2.25L15 12" />
						</svg>
						<span class="text-sm font-medium text-gray-700">Kalite Formları</span>
					</a>
				{/if}
				<a href="/dashboard/mesajlasma" class="flex items-center gap-3 bg-white rounded-xl border border-gray-100 hover:border-teal-200 hover:shadow-sm px-4 py-3 transition-all">
					<svg class="w-5 h-5 text-teal-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
					</svg>
					<span class="text-sm font-medium text-gray-700">Mesajlaşma</span>
				</a>
			</div>
		</div>
	{/if}
</div>
