<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import StatCard, { type StatAccent } from '$lib/components/StatCard.svelte';
	import { Landmark, Scroll, CreditCard, Wallet, Users } from 'lucide-svelte';

	interface CardData {
		label: string;
		sublabel: string;
		amount: string;
		detail: string;
		icon: any;
		accent: StatAccent;
		href: string;
		loading: boolean;
	}

	let cards = $state<CardData[]>([
		{ label: 'Bankalar', sublabel: '', amount: '', detail: '', icon: Landmark, accent: 'teal', href: '/dashboard/finans/bankalar', loading: true },
		{ label: 'Çekler', sublabel: '', amount: '', detail: '', icon: Scroll, accent: 'amber', href: '/dashboard/finans/cekler', loading: true },
		{ label: 'Krediler', sublabel: '', amount: '', detail: '', icon: CreditCard, accent: 'blue', href: '/dashboard/finans/krediler', loading: true },
		{ label: 'Avanslar', sublabel: '', amount: '', detail: '', icon: Wallet, accent: 'emerald', href: '/dashboard/finans/avanslar', loading: true },
		{ label: 'Cariler', sublabel: '', amount: '', detail: '', icon: Users, accent: 'red', href: '/dashboard/finans/cariler', loading: true },
	]);

	function fmt(n: number): string {
		if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(2).replace('.', ',') + 'M';
		return new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(n);
	}

	// sublabel + detail birleştirilerek StatCard hint'i oluşturulur
	function cardHint(card: CardData): string {
		return [card.sublabel, card.detail].filter(Boolean).join(' · ');
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

<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 sm:gap-3 mb-6">
	{#each cards as card}
		{#if card.loading}
			<!-- Yükleme iskeleti — StatCard ile aynı radius/kenarlık -->
			<div class="bg-white border border-gray-200 rounded-2xl p-4 sm:p-5 shadow-sm">
				<div class="h-3 w-16 bg-gray-200 rounded animate-pulse"></div>
				<div class="mt-3 h-5 w-20 bg-gray-200 rounded animate-pulse"></div>
				<div class="mt-2 h-2.5 w-12 bg-gray-100 rounded animate-pulse"></div>
			</div>
		{:else}
			<StatCard
				label={card.label}
				value={card.amount}
				icon={card.icon}
				accent={card.accent}
				hint={cardHint(card)}
				href={card.href}
			/>
		{/if}
	{/each}
</div>
