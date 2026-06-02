<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';

	interface CardData {
		label: string;
		sublabel: string;
		amount: string;
		detail: string;
		icon: string;
		color: string;
		href: string;
		loading: boolean;
	}

	let cards = $state<CardData[]>([
		{ label: 'Bankalar', sublabel: '', amount: '', detail: '', icon: 'M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0012 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75z', color: 'teal', href: '/dashboard/finans/bankalar', loading: true },
		{ label: 'Çekler', sublabel: '', amount: '', detail: '', icon: 'M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z', color: 'orange', href: '/dashboard/finans/cekler', loading: true },
		{ label: 'Krediler', sublabel: '', amount: '', detail: '', icon: 'M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z', color: 'amber', href: '/dashboard/finans/krediler', loading: true },
		{ label: 'Avanslar', sublabel: '', amount: '', detail: '', icon: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z', color: 'violet', href: '/dashboard/finans/avanslar', loading: true },
		{ label: 'Cariler', sublabel: '', amount: '', detail: '', icon: 'M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z', color: 'rose', href: '/dashboard/finans/cariler', loading: true },
	]);

	const colorMap: Record<string, { bg: string; border: string; icon: string; text: string; amount: string; hover: string }> = {
		teal:   { bg: 'bg-teal-50',   border: 'border-teal-200',   icon: 'text-teal-500',   text: 'text-teal-700',   amount: 'text-teal-800',   hover: 'hover:bg-teal-100 hover:border-teal-300' },
		orange: { bg: 'bg-orange-50', border: 'border-orange-200', icon: 'text-orange-500', text: 'text-orange-700', amount: 'text-orange-800', hover: 'hover:bg-orange-100 hover:border-orange-300' },
		amber:  { bg: 'bg-amber-50',  border: 'border-amber-200',  icon: 'text-amber-500',  text: 'text-amber-700',  amount: 'text-amber-800',  hover: 'hover:bg-amber-100 hover:border-amber-300' },
		violet: { bg: 'bg-violet-50', border: 'border-violet-200', icon: 'text-violet-500', text: 'text-violet-700', amount: 'text-violet-800', hover: 'hover:bg-violet-100 hover:border-violet-300' },
		rose:   { bg: 'bg-rose-50',   border: 'border-rose-200',   icon: 'text-rose-500',   text: 'text-rose-700',   amount: 'text-rose-800',   hover: 'hover:bg-rose-100 hover:border-rose-300' },
	};

	function fmt(n: number): string {
		if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1).replace('.0', '') + 'M';
		if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + 'K';
		return n.toFixed(0);
	}

	onMount(() => {
		loadBankSummary();
		loadCheckSummary();
		loadCreditSummary();
		loadAdvanceSummary();
		loadVendorSummary();
	});

	async function loadBankSummary() {
		try {
			const [data, ratesData] = await Promise.all([
				api.get<any>('/finance/banks/accounts/'),
				api.get<any>('/finance/exchange-rates/latest').catch(() => null),
			]);
			const accounts = data.items ?? data;
			const eff = (a: any) => (a.last_balance ?? 0) - (a.blocked_amount ?? 0);
			const totalTRY = accounts.filter((a: any) => a.currency === 'TRY').reduce((s: number, a: any) => s + eff(a), 0);
			const totalEUR = accounts.filter((a: any) => a.currency === 'EUR').reduce((s: number, a: any) => s + eff(a), 0);
			const totalUSD = accounts.filter((a: any) => a.currency === 'USD').reduce((s: number, a: any) => s + eff(a), 0);

			const eurRate = ratesData?.rates?.find((r: any) => r.currency_code === 'EUR')?.forex_selling ?? 0;
			const usdRate = ratesData?.rates?.find((r: any) => r.currency_code === 'USD')?.forex_selling ?? 0;

			if (eurRate > 0) {
				const tryAsEur = totalTRY / eurRate;
				const usdAsEur = usdRate > 0 ? (totalUSD * usdRate) / eurRate : 0;
				const grandTotalEur = tryAsEur + totalEUR + usdAsEur;
				cards[0].amount = `€${fmt(grandTotalEur)}`;
			} else {
				cards[0].amount = `₺${fmt(totalTRY)}`;
			}
			cards[0].sublabel = `${accounts.length} hesap`;
			cards[0].detail = '';
		} catch (err) {
			console.error('Banka özeti hatası:', err);
			cards[0].sublabel = '—';
		}
		cards[0].loading = false;
	}

	async function loadCheckSummary() {
		try {
			const data = await api.get<any>('/finance/checks/summary');
			cards[1].amount = data.pending_amount_eur != null ? `€${fmt(data.pending_amount_eur)}` : `₺${fmt(data.pending_amount ?? 0)}`;
			cards[1].sublabel = `${data.pending_count ?? 0} bekleyen`;
			cards[1].detail = data.overdue_count > 0 ? `${data.overdue_count} vadesi geçmiş` : '';
		} catch (err) {
			console.error('Çek özeti hatası:', err);
			cards[1].sublabel = '—';
		}
		cards[1].loading = false;
	}

	async function loadCreditSummary() {
		try {
			const data = await api.get<any[]>('/finance/krediler/summary/by-type');
			const totalCount = data.reduce((s: number, t: any) => s + (t.count ?? 0), 0);
			const totalEur = data.reduce((s: number, t: any) => s + (t.remaining_amount_eur ?? 0), 0);

			if (totalEur > 0) {
				cards[2].amount = `€${fmt(totalEur)}`;
			} else {
				const totalRemaining = data.reduce((s: number, t: any) => s + (t.remaining_amount ?? 0), 0);
				cards[2].amount = `₺${fmt(totalRemaining)}`;
			}
			cards[2].sublabel = `${totalCount} ürün`;
			cards[2].detail = 'kalan borç';
		} catch (err) {
			console.error('Kredi özeti hatası:', err);
			cards[2].sublabel = '—';
		}
		cards[2].loading = false;
	}

	async function loadAdvanceSummary() {
		try {
			const [data, ratesData] = await Promise.all([
				api.get<any>('/finance/avanslar/summary'),
				api.get<any>('/finance/exchange-rates/latest').catch(() => null),
			]);
			const eurRate = ratesData?.rates?.find((r: any) => r.currency_code === 'EUR')?.forex_selling ?? 0;
			const usdRate = ratesData?.rates?.find((r: any) => r.currency_code === 'USD')?.forex_selling ?? 0;

			let receivedEur = 0;
			let pendingEur = 0;
			let pendingCount = 0;

			for (const [currency, val] of Object.entries(data) as [string, any][]) {
				const toEur = (amount: number) => {
					if (currency === 'EUR') return amount;
					if (currency === 'USD' && usdRate > 0 && eurRate > 0) return (amount * usdRate) / eurRate;
					if (eurRate > 0) return amount / eurRate;
					return 0;
				};
				receivedEur += toEur(val.received ?? 0);
				pendingEur += toEur(val.pending ?? 0);
				pendingCount += val.pending_count ?? 0;
			}

			cards[3].amount = `€${fmt(receivedEur)}`;
			cards[3].sublabel = `€${fmt(pendingEur)} alındı`;
			cards[3].detail = `${pendingCount} bekleyen`;
		} catch (err) {
			console.error('Avans özeti hatası:', err);
			cards[3].sublabel = '—';
		}
		cards[3].loading = false;
	}

	async function loadVendorSummary() {
		try {
			const data = await api.get<any>('/finance/cariler/vendors/summary');
			if (data.negative_total_eur != null) {
				cards[4].amount = `€${fmt(data.negative_total_eur)}`;
			} else {
				cards[4].amount = `₺${fmt(Math.abs(data.negative_total ?? 0))}`;
			}
			cards[4].sublabel = `${data.negative_count ?? 0} borçlu cari`;
			cards[4].detail = '';
		} catch (err) {
			console.error('Cari özeti hatası:', err);
			cards[4].sublabel = '—';
		}
		cards[4].loading = false;
	}
</script>

<div class="grid grid-cols-3 sm:grid-cols-5 gap-2 sm:gap-3 mb-6">
	{#each cards as card}
		{@const c = colorMap[card.color]}
		<button
			onclick={() => goto(card.href)}
			class="{c.bg} border {c.border} {c.hover} rounded-2xl p-2 sm:p-3 text-center shadow-sm transition-all cursor-pointer active:scale-95"
		>
			<!-- İkon + Başlık -->
			<div class="flex items-center justify-center gap-1 sm:gap-1.5">
				<svg class="w-3.5 h-3.5 sm:w-4 sm:h-4 {c.icon} shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path stroke-linecap="round" stroke-linejoin="round" d={card.icon} />
				</svg>
				<span class="text-[10px] sm:text-xs font-semibold {c.text} truncate">{card.label}</span>
			</div>

			<!-- Tutar -->
			{#if card.loading}
				<div class="mt-1.5 sm:mt-2 h-4 sm:h-5 flex items-center justify-center">
					<div class="w-12 h-2.5 bg-gray-200 rounded animate-pulse"></div>
				</div>
			{:else}
				<div class="mt-1 sm:mt-1.5 text-sm sm:text-base font-bold {c.amount} truncate leading-tight">
					{card.amount}
				</div>
			{/if}

			<!-- Alt bilgi -->
			<div class="mt-0.5 text-[10px] sm:text-[10px] text-gray-500 truncate leading-tight">
				{#if card.loading}
					<span>&nbsp;</span>
				{:else}
					{card.sublabel}
				{/if}
			</div>

			<!-- Detay -->
			{#if card.detail && !card.loading}
				<div class="mt-0.5 text-[10px] sm:text-[10px] text-gray-500 truncate leading-tight">
					{card.detail}
				</div>
			{/if}
		</button>
	{/each}
</div>
