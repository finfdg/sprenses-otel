<script lang="ts">
	import type { BankAccount, BankTransaction, BankStatement, UploadResult } from '$lib/types/bank';
	import type { LatestRates } from '$lib/types/exchange-rate';
	import { page } from '$app/stores';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import Button from '$lib/components/Button.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import {
		Upload, Plus, Pencil, Trash2, Check, ChevronRight, Building2, FileText, FileSpreadsheet, Loader2
	} from 'lucide-svelte';

	// ─── Logo haritası ──────────────────────────────────────
	const BANK_LOGOS: Record<string, string> = {
		'Ziraat Bankası': '/bankalar/ziraat.svg',
		'Yapı Kredi': '/bankalar/yapikredi.svg',
		'TEB': '/bankalar/teb.svg',
		'VakıfBank': '/bankalar/vakifbank.svg',
		'Garanti BBVA': '/bankalar/garanti.svg',
		'Halkbank': '/bankalar/halkbank.svg',
		'QNB': '/bankalar/qnb.svg',
	};

	const CURRENCY_SYMBOLS: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$' };

	// ─── State ──────────────────────────────────────────────
	let accounts = $state<BankAccount[]>([]);
	let loading = $state(true);

	// Döviz kurları (EUR çevrimi için)
	let latestRates = $state<LatestRates | null>(null);

	// Akordiyon state
	let expandedBanks = $state<Record<string, boolean>>({});
	let expandedAccount = $state<number | null>(null);
	let activeTab = $state<'transactions' | 'statements'>('transactions');

	// İşlem & ekstre
	let transactions = $state<BankTransaction[]>([]);
	let statements = $state<BankStatement[]>([]);
	let txLoading = $state(false);
	let txPage = $state(1);
	let txTotal = $state(0);
	let txPages = $state(1);
	const txPageSize = 50;

	// Upload — sürükle/bırak
	let uploading = $state(false);
	let uploadResult = $state<UploadResult | null>(null);
	let showUploadResult = $state(false);

	// Manuel (ekstre-dışı) hareket
	let showManualTx = $state(false);
	let manualTxAccount = $state<BankAccount | null>(null);
	let manualForm = $state({ date: '', direction: 'out' as 'in' | 'out', amount: null as number | null, description: '' });
	let manualSaving = $state(false);
	let manualError = $state('');

	// Hesap formu
	let showAccountForm = $state(false);
	let editingAccount = $state<BankAccount | null>(null);
	let formBankSelect = $state('');
	let formBankCustom = $state('');
	let formIban = $state('');
	let formCurrency = $state('TRY');
	let formBranchName = $state('');
	let formAccountNo = $state('');
	let formHolderName = $state('');
	let formBlockedAmount = $state<number | null>(null);
	let formError = $state('');
	let savingAccount = $state(false);

	const KNOWN_BANKS = Object.keys(BANK_LOGOS);
	const canUse = hasPermission('finance.banks', 'use');

	// ─── Derived ────────────────────────────────────────────
	// Kur dönüşüm yardımcısı: TRY ve USD → EUR
	let eurRate = $derived(latestRates?.rates.find(r => r.currency_code === 'EUR')?.forex_selling ?? null);
	let usdRate = $derived(latestRates?.rates.find(r => r.currency_code === 'USD')?.forex_selling ?? null);

	// Sisteme kayıtlı ama BANK_LOGOS'ta tanımsız bankalar da dahil
	let allBankNames = $derived.by(() => {
		const names = new Set(KNOWN_BANKS);
		for (const acc of accounts) {
			names.add(acc.bank_name);
		}
		return [...names].sort((a, b) => a.localeCompare(b, 'tr'));
	});

	let formBankName = $derived(formBankSelect === '__other__' ? formBankCustom.trim() : formBankSelect);

	// ─── Banka gruplama ─────────────────────────────────────
	interface BankGroup {
		bankName: string;
		logoUrl: string;
		accounts: BankAccount[];
		totalEUR: number | null;
		totalAccountCount: number;
		totalTxCount: number;
		hasUploadToday: boolean;
	}

	/** Bugünün tarihini YYYY-MM-DD olarak al */
	function todayStr(): string {
		const d = new Date();
		return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
	}

	/** Hesabın bugün ekstre yüklenip yüklenmediğini kontrol et */
	function isUploadedToday(acc: BankAccount): boolean {
		if (!acc.last_statement_date) return false;
		return acc.last_statement_date === todayStr();
	}

	/** Hesap bakiyesini EUR'ya çevir. Kur yoksa null döner. */
	function toEur(balance: number | null, currency: string): number | null {
		if (balance === null) return null;
		if (currency === 'EUR') return balance;
		if (currency === 'TRY' && eurRate) return balance / eurRate;
		if (currency === 'USD' && usdRate && eurRate) return (balance * usdRate) / eurRate;
		return null;
	}

	let bankGroups = $derived.by(() => {
		const map = new Map<string, BankAccount[]>();
		for (const acc of accounts) {
			const existing = map.get(acc.bank_name) || [];
			existing.push(acc);
			map.set(acc.bank_name, existing);
		}

		const groups: BankGroup[] = [];
		for (const [bankName, accs] of map) {
			let totalEUR: number | null = 0;
			let totalTxCount = 0;
			for (const acc of accs) {
				totalTxCount += acc.transaction_count;
				const effectiveBalance = acc.last_balance !== null ? acc.last_balance - (acc.blocked_amount ?? 0) : null;
				const eurVal = toEur(effectiveBalance, acc.currency);
				if (eurVal !== null && totalEUR !== null) {
					totalEUR += eurVal;
				} else if (effectiveBalance !== null && effectiveBalance !== 0) {
					totalEUR = null; // kur yoksa toplam gösterilmez
				}
			}
			groups.push({
				bankName,
				logoUrl: BANK_LOGOS[bankName] || '',
				accounts: accs,
				totalEUR,
				totalAccountCount: accs.length,
				totalTxCount,
				hasUploadToday: accs.every(a => isUploadedToday(a)),
			});
		}
		return groups.sort((a, b) => (b.totalEUR ?? -Infinity) - (a.totalEUR ?? -Infinity));
	});

	// Tüm bankaların EUR genel toplamı
	let grandTotalEUR = $derived.by(() => {
		let total = 0;
		let hasData = false;
		for (const g of bankGroups) {
			if (g.totalEUR !== null && g.totalEUR !== 0) {
				total += g.totalEUR;
				hasData = true;
			}
		}
		return hasData ? total : null;
	});

	// ─── API ────────────────────────────────────────────────
	async function loadAccounts() {
		try {
			accounts = await api.get<BankAccount[]>('/finance/banks/accounts/');
		} catch (err: any) {
			console.error('Hesaplar yüklenemedi:', err);
		}
		loading = false;
	}

	async function loadRates() {
		try {
			latestRates = await api.get<LatestRates>('/finance/exchange-rates/latest');
		} catch (err: any) {
			console.error('Döviz kurları yüklenemedi:', err);
		}
	}

	async function loadTransactions(accountId: number) {
		txLoading = true;
		try {
			const data = await api.get<{ items: BankTransaction[]; total: number; pages: number }>(
				`/finance/banks/accounts/${accountId}/transactions?page=${txPage}&page_size=${txPageSize}`
			);
			transactions = data.items;
			txTotal = data.total;
			txPages = data.pages;
		} catch (err: any) {
			console.error('İşlemler yüklenemedi:', err);
		}
		txLoading = false;
	}

	async function loadStatements(accountId: number) {
		try {
			statements = await api.get<BankStatement[]>(
				`/finance/banks/accounts/${accountId}/statements`
			);
		} catch (err: any) {
			console.error('Ekstreler yüklenemedi:', err);
		}
	}

	// ─── Akordiyon ──────────────────────────────────────────
	function toggleBank(bankName: string) {
		expandedBanks[bankName] = !expandedBanks[bankName];
	}

	function toggleAccount(acc: BankAccount) {
		if (expandedAccount === acc.id) {
			expandedAccount = null;
			transactions = [];
			statements = [];
		} else {
			expandedAccount = acc.id;
			txPage = 1;
			activeTab = 'transactions';
			loadTransactions(acc.id);
		}
	}

	function openAccountById(accountId: number) {
		const acc = accounts.find(a => a.id === accountId);
		if (!acc) return;
		// Banka grubunu aç
		expandedBanks[acc.bank_name] = true;
		// Hesabı aç
		expandedAccount = acc.id;
		txPage = 1;
		activeTab = 'transactions';
		loadTransactions(acc.id);
		// Hesap kartına scroll
		setTimeout(() => {
			const el = document.getElementById(`account-${acc.id}`);
			if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}, 200);
	}

	function switchTab(tab: 'transactions' | 'statements', accountId: number) {
		activeTab = tab;
		if (tab === 'statements') {
			loadStatements(accountId);
		}
	}

	function changeTxPage(delta: number) {
		txPage += delta;
		if (expandedAccount) loadTransactions(expandedAccount);
	}

	// ─── Dosya yükleme ──────────────────────────────────────
	function handleDropError(errors: string[]) {
		for (const err of errors) showToast(err, 'error', 4000);
	}

	async function uploadFiles(files: File[]) {
		for (const file of files) {
			uploading = true;
			try {
				const formData = new FormData();
				formData.append('file', file);
				const result = await api.upload<UploadResult>('/finance/banks/upload', formData);
				uploadResult = result;
				showUploadResult = true;
				showToast(`${result.new_transactions} yeni işlem eklendi`, 'success');
				await loadAccounts();

				// Yüklenen hesabın bankasını aç
				if (result.account_iban) {
					const targetAcc = accounts.find(a => a.iban === result.account_iban);
					if (targetAcc) {
						expandedBanks[targetAcc.bank_name] = true;
						expandedAccount = targetAcc.id;
						txPage = 1;
						activeTab = 'transactions';
						loadTransactions(targetAcc.id);
					}
				}
			} catch (err: any) {
				showToast(err.message || `${file.name} yüklenemedi`, 'error');
				console.error('Yükleme hatası:', err);
			}
			uploading = false;
		}
	}

	// ─── Hesap formu ────────────────────────────────────────
	function openAccountForm(acc: BankAccount | null = null) {
		editingAccount = acc;
		if (acc) {
			if (allBankNames.includes(acc.bank_name)) {
				formBankSelect = acc.bank_name;
				formBankCustom = '';
			} else {
				formBankSelect = '__other__';
				formBankCustom = acc.bank_name;
			}
			formIban = acc.iban;
			formCurrency = acc.currency;
			formBranchName = acc.branch_name || '';
			formAccountNo = acc.account_no || '';
			formHolderName = acc.holder_name || '';
			formBlockedAmount = acc.blocked_amount !== null ? Number(acc.blocked_amount) : null;
		} else {
			formBankSelect = ''; formBankCustom = '';
			formIban = ''; formCurrency = 'TRY';
			formBranchName = ''; formAccountNo = ''; formHolderName = '';
			formBlockedAmount = null;
		}
		formError = '';
		showAccountForm = true;
	}

	async function saveAccount() {
		formError = '';
		if (!formBankName.trim()) { formError = 'Banka adı zorunludur'; return; }
		if (!formIban.trim()) { formError = 'IBAN zorunludur'; return; }

		savingAccount = true;
		try {
			const payload = {
				bank_name: formBankName.trim(),
				iban: formIban.trim().replace(/\s/g, ''),
				currency: formCurrency,
				branch_name: formBranchName.trim() || null,
				account_no: formAccountNo.trim() || null,
				holder_name: formHolderName.trim() || null,
				blocked_amount: formBlockedAmount !== null && Number.isFinite(formBlockedAmount) ? formBlockedAmount : null,
			};

			if (editingAccount) {
				await api.patch(`/finance/banks/accounts/${editingAccount.id}`, payload);
				showToast('Hesap güncellendi', 'success');
			} else {
				await api.post('/finance/banks/accounts/', payload);
				showToast('Hesap eklendi', 'success');
			}
			showAccountForm = false;
			await loadAccounts();
		} catch (err: any) {
			formError = err.message || 'Kayıt başarısız';
			console.error('Hesap kayıt hatası:', err);
		}
		savingAccount = false;
	}

	// Silme onayı state
	let showDeleteConfirm = $state(false);
	let deleteTarget = $state<BankAccount | null>(null);

	function askDelete(acc: BankAccount) {
		deleteTarget = acc;
		showDeleteConfirm = true;
	}

	async function deleteAccount() {
		if (!deleteTarget) return;
		const acc = deleteTarget;
		try {
			await api.delete(`/finance/banks/accounts/${acc.id}`);
			showToast('Hesap silindi', 'success');
			if (expandedAccount === acc.id) {
				expandedAccount = null;
				transactions = [];
			}
			await loadAccounts();
		} catch (err: any) {
			showToast(err.message || 'Silinemedi', 'error');
			console.error('Silme hatası:', err);
		}
	}

	// ─── Format helpers ─────────────────────────────────────
	// ─── Manuel (ekstre-dışı) hareket ──────────────────────
	function openManualTx(acc: BankAccount) {
		manualTxAccount = acc;
		manualError = '';
		const t = new Date();
		const iso = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
		manualForm = { date: iso, direction: 'out', amount: null, description: '' };
		showManualTx = true;
	}
	async function submitManualTx() {
		if (!manualTxAccount) return;
		manualError = '';
		if (!manualForm.date) { manualError = 'Tarih zorunlu'; return; }
		if (!manualForm.amount || manualForm.amount <= 0) { manualError = 'Tutar girin'; return; }
		if (!manualForm.description.trim()) { manualError = 'Açıklama zorunlu'; return; }
		manualSaving = true;
		try {
			const signed = manualForm.direction === 'out' ? -Math.abs(manualForm.amount) : Math.abs(manualForm.amount);
			await api.post(`/finance/banks/accounts/${manualTxAccount.id}/manual-transaction`, {
				date: manualForm.date, amount: signed, description: manualForm.description.trim(),
			});
			const accId = manualTxAccount.id;
			showManualTx = false;
			showToast('Manuel hareket eklendi — ilgili ekstre yüklenince otomatik temizlenir', 'success');
			await loadAccounts();
			if (expandedAccount === accId) loadTransactions(accId);
		} catch (e: any) {
			manualError = e?.message || 'Eklenemedi';
		} finally {
			manualSaving = false;
		}
	}

	function formatCurrency(amount: number, currency: string = 'TRY'): string {
		return new Intl.NumberFormat('tr-TR', { style: 'currency', currency }).format(amount);
	}

	function formatCompact(amount: number): string {
		if (Math.abs(amount) >= 1_000_000) return (amount / 1_000_000).toFixed(1) + 'M';
		if (Math.abs(amount) >= 1_000) return (amount / 1_000).toFixed(1) + 'K';
		return amount.toFixed(0);
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr + 'T00:00:00').toLocaleDateString('tr-TR', {
			day: '2-digit', month: '2-digit', year: 'numeric'
		});
	}

	function formatIban(iban: string): string {
		return iban.replace(/(.{4})/g, '$1 ').trim();
	}

	function getAccCurrency(accId: number | null): string {
		if (!accId) return 'TRY';
		const acc = accounts.find(a => a.id === accId);
		return acc?.currency || 'TRY';
	}

	$effect(() => {
		loadAccounts().then(() => {
			// URL'de ?account=ID varsa o hesabı aç (push bildirimden gelme)
			const accParam = $page.url.searchParams.get('account');
			if (accParam) {
				const accId = parseInt(accParam, 10);
				if (!isNaN(accId)) {
					// Hesaplar yüklendikten sonra aç
					setTimeout(() => openAccountById(accId), 100);
				}
				// URL'den parametreyi temizle (tekrar açılmasını engelle)
				const url = new URL(window.location.href);
				url.searchParams.delete('account');
				window.history.replaceState({}, '', url.toString());
			}
		});
		loadRates();
	});

	// Banka ekstresi yüklenince veriyi yenile (toast bildirimi layout'tan gelir)
	$effect(() => {
		const unsubscribe = onWsEvent('bank_statement_uploaded', (data: any) => {
			const accountId = data.account_id;

			// Hesap listesini yenile ve ilgili hesabı aç
			loadAccounts().then(() => {
				if (accountId) {
					openAccountById(accountId);
				}
			});
		});

		return unsubscribe;
	});

	// Finans güncelleme event'i — başka kullanıcı değişiklik yapınca otomatik yenile
	$effect(() => {
		const unsub = onWsEvent('finance_updated', () => {
			loadAccounts();
		});
		return unsub;
	});
</script>

<div class="p-4 md:p-6 max-w-7xl mx-auto">

	<!-- ─── Başlık ──────────────────────────────────────────── -->
	<div class="mb-6">
		<PageHeader title="Bankalar" description="Banka hesaplarınızı yönetin, ekstre yükleyin ve hareketleri takip edin">
			{#snippet actions()}
				{#if canUse}
					<Button onclick={() => openAccountForm()}><Plus size={16} /> Yeni Hesap</Button>
				{/if}
			{/snippet}
		</PageHeader>
	</div>

	<!-- ─── Sürükle & Bırak Yükleme Alanı ───────────────── -->
	{#if canUse}
		<div class="relative mb-6">
			{#if uploading}
				<div class="absolute inset-0 z-10 bg-white/80 rounded-xl flex items-center justify-center">
					<div class="flex items-center gap-2 text-teal-700">
						<Loader2 size={20} class="animate-spin" />
						<span class="text-sm font-medium">Yükleniyor...</span>
					</div>
				</div>
			{/if}
			<FileDropzone
				accept=".pdf,.xlsx,.xls"
				maxSize={50 * 1024 * 1024}
				multiple={true}
				disabled={uploading}
				label="Banka ekstresi yükleyin"
				hint="PDF veya Excel — IBAN'dan hesap otomatik tespit edilir"
				onSelect={uploadFiles}
				onError={handleDropError}
			/>
		</div>
	{/if}

	<!-- ─── Başlık ──────────────────────────────────────────── -->
	<div class="flex items-center justify-between mb-4">
		<div class="flex items-center gap-3">
			<h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wide">Banka Hesapları</h2>
			{#if grandTotalEUR !== null}
				<span class="px-2.5 py-1 text-xs font-bold bg-emerald-50 text-emerald-700 rounded-full border border-emerald-200">
					Toplam €{grandTotalEUR.toLocaleString('tr-TR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
				</span>
			{/if}
			{#if latestRates?.date}
				<span class="text-[10px] text-gray-500 hidden sm:inline">
					Kur: {new Date(latestRates.date + 'T00:00:00').toLocaleDateString('tr-TR')}
				</span>
			{/if}
		</div>
	</div>

	<!-- ─── Banka Akordiyon ─────────────────────────────────── -->
	{#if loading}
		<TableSkeleton rows={4} columns={3} showHeader={false} />
	{:else if bankGroups.length === 0}
		<EmptyState
			icon={Building2}
			title="Henüz banka hesabı eklenmemiş"
			description="Yeni hesap eklemek için sağ üstteki butonu kullanın veya yukarıdan ekstre yükleyin"
			ctaText={canUse ? 'Yeni Hesap' : ''}
			onCta={canUse ? () => openAccountForm() : null}
		/>
	{:else}
		<div class="space-y-3">
			{#each bankGroups as group}
				{@const isOpen = expandedBanks[group.bankName] ?? false}

				<!-- Banka Başlık -->
				<div class="{isOpen ? '' : 'rounded-xl'} overflow-hidden">
					<button
						onclick={() => toggleBank(group.bankName)}
						class="w-full flex items-center gap-3 px-4 py-3.5 transition-all cursor-pointer
							{isOpen
								? 'bg-teal-700 text-white rounded-t-xl'
								: group.hasUploadToday
									? 'bg-white border border-gray-200 hover:border-gray-300 hover:shadow-sm rounded-xl'
									: 'bg-gray-200 border border-gray-300 hover:border-gray-400 hover:shadow-sm rounded-xl'}"
					>
						<!-- Logo -->
						{#if group.logoUrl}
							<img
								src={group.logoUrl}
								alt={group.bankName}
								class="w-8 h-8 rounded-lg object-contain flex-shrink-0"
							/>
						{:else}
							<div class="w-8 h-8 rounded-lg bg-gray-200 flex items-center justify-center flex-shrink-0">
								<span class="text-xs font-bold text-gray-500">{group.bankName.charAt(0)}</span>
							</div>
						{/if}

						<!-- Banka Adı -->
						<span class="font-semibold text-sm {isOpen ? 'text-white' : 'text-gray-800'}">{group.bankName}</span>

						<!-- Hesap sayısı -->
						<span class="px-2 py-0.5 text-[10px] font-bold rounded-full {isOpen ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'}">
							{group.totalAccountCount} hesap
						</span>

						<!-- Spacer -->
						<div class="flex-1"></div>

						<!-- EUR Toplam -->
						{#if group.totalEUR !== null && group.totalEUR !== 0}
							<span class="text-sm font-bold mr-2 {isOpen ? 'text-teal-100' : 'text-gray-600'}">
								€{group.totalEUR!.toLocaleString('tr-TR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
							</span>
						{/if}

						<!-- İşlem sayısı -->
						<span class="text-xs mr-2 hidden sm:inline {isOpen ? 'text-teal-200' : 'text-gray-500'}">
							{group.totalTxCount} işlem
						</span>

						<!-- Chevron -->
						<ChevronRight size={16} class="flex-shrink-0 transition-transform duration-200 {isOpen ? 'rotate-90 text-white' : 'text-gray-500'}" />
					</button>

					<!-- ─── Hesap Listesi (banka açıkken) ──────── -->
					{#if isOpen}
						<div class="border border-t-0 border-gray-200 rounded-b-xl bg-gray-50/50 divide-y divide-gray-100">
							{#each group.accounts as acc}
								{@const isAccOpen = expandedAccount === acc.id}

								<!-- Hesap satırı -->
								{@const uploadedToday = isUploadedToday(acc)}
								<div id="account-{acc.id}">
									<button
										onclick={() => toggleAccount(acc)}
										class="w-full flex items-center gap-3 px-4 py-3 text-left transition-colors cursor-pointer
											{isAccOpen ? 'bg-teal-50' : uploadedToday ? 'hover:bg-gray-100/70' : 'bg-gray-200/80 hover:bg-gray-300/70'}"
									>
										<!-- Döviz rozeti -->
										<span class="px-2 py-0.5 text-[10px] font-bold rounded-md flex-shrink-0
											{acc.currency === 'TRY' ? 'bg-emerald-100 text-emerald-700'
												: acc.currency === 'EUR' ? 'bg-blue-100 text-blue-700'
												: 'bg-amber-100 text-amber-700'}">
											{acc.currency}
										</span>

										<!-- IBAN -->
										<span class="text-xs text-gray-500 font-mono hidden md:inline">{formatIban(acc.iban)}</span>
										<span class="text-xs text-gray-500 font-mono md:hidden">...{acc.iban.slice(-8)}</span>

										<div class="flex-1"></div>

										<!-- İşlem sayısı -->
										<span class="text-[11px] text-gray-500 hidden sm:inline">{acc.transaction_count} işlem</span>

										<!-- Bakiye -->
										<div class="text-right">
										{#if acc.last_balance !== null}
											{@const effective = acc.last_balance - (acc.blocked_amount ?? 0)}
											<span class="text-sm font-bold {effective >= 0 ? 'text-emerald-600' : 'text-rose-600'}">
												{formatCurrency(effective, acc.currency)}
											</span>
											{#if acc.blocked_amount}
												<div class="text-[10px] text-amber-600">
													Bloke: {formatCurrency(acc.blocked_amount, acc.currency)}
												</div>
											{/if}
										{:else}
											<span class="text-xs text-gray-500">—</span>
										{/if}
									</div>

										<!-- Hesap aksiyonları -->
										{#if canUse}
											<div class="flex gap-0.5 ml-1">
												<!-- svelte-ignore a11y_no_static_element_interactions -->
												<span
													role="button"
													tabindex="0"
													onclick={(e) => { e.stopPropagation(); openAccountForm(acc); }}
													onkeydown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); openAccountForm(acc); } }}
													class="p-1 text-gray-500 hover:text-blue-600 cursor-pointer"
													title="Düzenle"
												>
													<Pencil size={14} />
												</span>
												<!-- svelte-ignore a11y_no_static_element_interactions -->
												<span
													role="button"
													tabindex="0"
													onclick={(e) => { e.stopPropagation(); askDelete(acc); }}
													onkeydown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); askDelete(acc); } }}
													class="p-1 text-gray-500 hover:text-rose-600 cursor-pointer"
													title="Sil"
												>
													<Trash2 size={14} />
												</span>
											</div>
										{/if}

										<!-- Chevron -->
										<ChevronRight size={14} class="flex-shrink-0 transition-transform duration-200 {isAccOpen ? 'rotate-90 text-teal-600' : 'text-gray-500'}" />
									</button>

									<!-- ─── İşlem/Ekstre paneli (hesap açıkken) ─── -->
									{#if isAccOpen}
										<div class="bg-white border-t border-gray-100">
											<!-- Tab'lar -->
											<div class="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100">
												<button
													onclick={() => switchTab('transactions', acc.id)}
													class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer {activeTab === 'transactions' ? 'bg-teal-50 text-teal-700' : 'text-gray-500 hover:text-gray-700'}"
												>
													İşlemler
												</button>
												<button
													onclick={() => switchTab('statements', acc.id)}
													class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer {activeTab === 'statements' ? 'bg-teal-50 text-teal-700' : 'text-gray-500 hover:text-gray-700'}"
												>
													Ekstreler
												</button>
												{#if canUse}
													<button
														onclick={() => openManualTx(acc)}
														class="ml-auto inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg text-amber-700 bg-amber-50 hover:bg-amber-100 cursor-pointer"
														title="Ekstre-dışı (manuel) hareket ekle — ilgili ekstre yüklenince otomatik temizlenir"
													>
														<Plus size={13} /> Manuel Hareket
													</button>
												{/if}
											</div>

											{#if activeTab === 'transactions'}
												<!-- İşlemler -->
												{#if txLoading}
													<div class="p-2">
														<TableSkeleton rows={5} columns={5} />
													</div>
												{:else if transactions.length === 0}
													<div class="text-center py-8 text-gray-500">
														<p class="text-sm">Henüz işlem yok. Yukarıdan ekstre yükleyerek başlayın.</p>
													</div>
												{:else}
													<!-- Masaüstü tablo -->
													<div class="hidden md:block overflow-x-auto">
														<table class="w-full text-sm">
															<thead>
																<tr class="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-100">
																	<th class="px-4 py-2.5 font-medium">Tarih</th>
																	<th class="px-4 py-2.5 font-medium">Fiş No</th>
																	<th class="px-4 py-2.5 font-medium">Açıklama</th>
																	<th class="px-4 py-2.5 font-medium text-right">Tutar</th>
																	<th class="px-4 py-2.5 font-medium text-right">Bakiye</th>
																</tr>
															</thead>
															<tbody>
																{#each transactions as tx}
																	<tr class="border-b border-gray-50 hover:bg-gray-50/50">
																		<td class="px-4 py-2.5 text-gray-600 whitespace-nowrap">{formatDate(tx.date)}</td>
																		<td class="px-4 py-2.5 text-gray-500 whitespace-nowrap text-xs">{tx.receipt_no || '-'}</td>
																		<td class="px-4 py-2.5 text-gray-800 max-w-xs">
																			<div class="flex items-center gap-1.5 min-w-0">
																				<span class="truncate" title={tx.description}>{tx.description}</span>
																				{#if tx.source === 'manual'}<span class="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700">Manuel</span>{/if}
																			</div>
																		</td>
																		<td class="px-4 py-2.5 text-right font-medium whitespace-nowrap {tx.type === 'income' ? 'text-emerald-600' : 'text-rose-600'}">
																			{tx.type === 'income' ? '+' : ''}{formatCurrency(tx.amount, acc.currency)}
																		</td>
																		<td class="px-4 py-2.5 text-right text-gray-500 whitespace-nowrap">
																			{tx.balance !== null ? formatCurrency(tx.balance, acc.currency) : '-'}
																		</td>
																	</tr>
																{/each}
															</tbody>
														</table>
													</div>

													<!-- Mobil liste -->
													<div class="md:hidden divide-y divide-gray-50">
														{#each transactions as tx}
															<div class="px-4 py-3">
																<div class="flex items-start justify-between gap-2">
																	<div class="min-w-0 flex-1">
																		<div class="flex items-center gap-1.5 min-w-0">
																			<p class="text-sm text-gray-800 truncate">{tx.description}</p>
																			{#if tx.source === 'manual'}<span class="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700">Manuel</span>{/if}
																		</div>
																		<p class="text-[11px] text-gray-500 mt-0.5">{formatDate(tx.date)} {tx.receipt_no ? `• ${tx.receipt_no}` : ''}</p>
																	</div>
																	<span class="text-sm font-bold whitespace-nowrap {tx.type === 'income' ? 'text-emerald-600' : 'text-rose-600'}">
																		{tx.type === 'income' ? '+' : ''}{formatCurrency(tx.amount, acc.currency)}
																	</span>
																</div>
															</div>
														{/each}
													</div>

													<!-- Pagination -->
													{#if txPages > 1}
														<div class="flex items-center justify-between px-4 py-3 border-t border-gray-100">
															<span class="text-xs text-gray-500">Toplam {txTotal} işlem</span>
															<div class="flex items-center gap-2">
																<button
																	onclick={() => changeTxPage(-1)}
																	disabled={txPage <= 1}
																	class="px-2.5 py-1 text-xs text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-30 cursor-pointer disabled:cursor-default"
																>
																	Önceki
																</button>
																<span class="text-xs text-gray-500">{txPage} / {txPages}</span>
																<button
																	onclick={() => changeTxPage(1)}
																	disabled={txPage >= txPages}
																	class="px-2.5 py-1 text-xs text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-30 cursor-pointer disabled:cursor-default"
																>
																	Sonraki
																</button>
															</div>
														</div>
													{/if}
												{/if}
											{:else}
												<!-- Ekstre Geçmişi -->
												{#if statements.length === 0}
													<div class="text-center py-8 text-gray-500">
														<p class="text-sm">Henüz ekstre yüklenmemiş.</p>
													</div>
												{:else}
													<div class="divide-y divide-gray-50">
														{#each statements as stmt}
															<div class="px-4 py-3 flex items-center justify-between">
																<div>
																	<div class="flex items-center gap-2">
																		{#if stmt.file_type === 'pdf'}
																			<FileText size={16} class="text-rose-400" />
																		{:else}
																			<FileSpreadsheet size={16} class="text-emerald-400" />
																		{/if}
																		<span class="text-sm text-gray-800">{stmt.file_name}</span>
																	</div>
																	{#if stmt.period_start && stmt.period_end}
																		<p class="text-[11px] text-gray-500 mt-0.5 ml-6">
																			{formatDate(stmt.period_start)} — {formatDate(stmt.period_end)}
																		</p>
																	{/if}
																</div>
																<div class="text-right">
																	<div class="flex items-center gap-2 text-xs">
																		<span class="text-emerald-600 font-medium">{stmt.new_transactions} yeni</span>
																		{#if stmt.skipped_transactions > 0}
																			<span class="text-amber-500">{stmt.skipped_transactions} mükerrer</span>
																		{/if}
																	</div>
																	<p class="text-[10px] text-gray-500 mt-0.5">
																		{new Date(stmt.uploaded_at).toLocaleDateString('tr-TR')}
																	</p>
																</div>
															</div>
														{/each}
													</div>
												{/if}
											{/if}
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Yükleme Sonucu Modal -->
<Modal bind:show={showUploadResult} title="Yükleme Sonucu" maxWidth="max-w-sm">
	{#if uploadResult}
		<div class="space-y-3">
			<div class="text-center">
				<div class="w-12 h-12 mx-auto bg-emerald-100 rounded-full flex items-center justify-center mb-3">
					<Check size={24} class="text-emerald-600" />
				</div>
				<p class="text-sm font-medium text-gray-800">{uploadResult.file_name}</p>
				{#if uploadResult.account_iban}
					<p class="text-[11px] text-gray-500 mt-0.5">{uploadResult.account_iban} ({uploadResult.account_currency})</p>
				{/if}
			</div>
			<div class="grid grid-cols-3 gap-2 text-center">
				<div class="bg-gray-50 rounded-xl p-2.5">
					<div class="text-lg font-bold text-gray-700">{uploadResult.total_transactions}</div>
					<div class="text-[10px] text-gray-500 mt-0.5">Toplam</div>
				</div>
				<div class="bg-emerald-50 rounded-xl p-2.5">
					<div class="text-lg font-bold text-emerald-600">{uploadResult.new_transactions}</div>
					<div class="text-[10px] text-emerald-500 mt-0.5">Yeni</div>
				</div>
				<div class="bg-amber-50 rounded-xl p-2.5">
					<div class="text-lg font-bold text-amber-600">{uploadResult.skipped_transactions}</div>
					<div class="text-[10px] text-amber-500 mt-0.5">Mükerrer</div>
				</div>
			</div>
			<Button fullWidth onclick={() => showUploadResult = false}>Tamam</Button>
		</div>
	{/if}
</Modal>

<!-- Hesap Formu Modal -->
<Modal bind:show={showAccountForm} title={editingAccount ? 'Hesabı Düzenle' : 'Yeni Hesap'} maxWidth="max-w-lg">
	<form onsubmit={(e) => { e.preventDefault(); saveAccount(); }} class="space-y-4">
		{#if formError}
			<div class="bg-red-50 border border-red-200 text-red-600 px-3 py-2 rounded-lg text-sm">{formError}</div>
		{/if}

		<div>
			<label for="ba-bank" class="block text-sm font-medium text-gray-700 mb-1">Banka</label>
			<div class="flex items-center gap-2">
				{#if formBankSelect && formBankSelect !== '__other__' && BANK_LOGOS[formBankSelect]}
					<img src={BANK_LOGOS[formBankSelect]} alt={formBankSelect} class="w-9 h-9 rounded-lg object-contain flex-shrink-0" />
				{:else if formBankSelect === '__other__'}
					<div class="w-9 h-9 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
						<Plus size={20} class="text-gray-500" />
					</div>
				{/if}
				<select
					id="ba-bank"
					bind:value={formBankSelect}
					class="flex-1 px-3 py-2.5 border border-gray-200 rounded-xl text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500 bg-white"
				>
					<option value="" disabled>Banka seçin...</option>
					{#each allBankNames as bank}
						<option value={bank}>{bank}</option>
					{/each}
					<option value="__other__">Diğer (elle girin)</option>
				</select>
			</div>
			{#if formBankSelect === '__other__'}
				<input
					type="text"
					bind:value={formBankCustom}
					placeholder="Banka adını yazın..."
					class="w-full mt-2 px-3 py-2.5 border border-gray-200 rounded-xl text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500"
				/>
			{/if}
		</div>

		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="ba-iban" class="block text-sm font-medium text-gray-700 mb-1">IBAN</label>
				<input
					id="ba-iban"
					type="text"
					bind:value={formIban}
					placeholder="TR..."
					class="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500 font-mono"
				/>
			</div>
			<div>
				<label for="ba-currency" class="block text-sm font-medium text-gray-700 mb-1">Döviz Cinsi</label>
				<select
					id="ba-currency"
					bind:value={formCurrency}
					class="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500 bg-white"
				>
					<option value="TRY">TRY (Türk Lirası)</option>
					<option value="EUR">EUR (Euro)</option>
					<option value="USD">USD (Dolar)</option>
				</select>
			</div>
		</div>

		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="ba-branch" class="block text-sm font-medium text-gray-700 mb-1">Şube <span class="text-gray-500">(opsiyonel)</span></label>
				<input
					id="ba-branch"
					type="text"
					bind:value={formBranchName}
					class="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500"
				/>
			</div>
			<div>
				<label for="ba-accno" class="block text-sm font-medium text-gray-700 mb-1">Hesap No <span class="text-gray-500">(opsiyonel)</span></label>
				<input
					id="ba-accno"
					type="text"
					bind:value={formAccountNo}
					class="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500"
				/>
			</div>
		</div>

		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="ba-holder" class="block text-sm font-medium text-gray-700 mb-1">Hesap Sahibi <span class="text-gray-500">(opsiyonel)</span></label>
				<input
					id="ba-holder"
					type="text"
					bind:value={formHolderName}
					class="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500"
				/>
			</div>
			<div>
				<label for="ba-blocked" class="block text-sm font-medium text-gray-700 mb-1">Bloke Tutarı <span class="text-gray-500">(opsiyonel)</span></label>
				<MoneyInput
					id="ba-blocked"
					bind:value={formBlockedAmount}
					currency={formCurrency}
					min={0}
					placeholder="0,00"
				/>
			</div>
		</div>

		<div class="flex justify-end gap-3 pt-2">
			<Button type="button" variant="secondary" onclick={() => showAccountForm = false}>İptal</Button>
			<Button type="submit" loading={savingAccount}>{editingAccount ? 'Güncelle' : 'Ekle'}</Button>
		</div>
	</form>
</Modal>

<!-- Manuel (ekstre-dışı) hareket -->
<Modal bind:show={showManualTx} title="Manuel Hareket (Ekstre Dışı)" maxWidth="max-w-md">
	{#if manualTxAccount}
		<div class="space-y-4">
			<div class="bg-amber-50 border border-amber-200 rounded-lg p-2.5 text-xs text-amber-800 leading-snug">
				<strong>{manualTxAccount.bank_name}</strong> ({manualTxAccount.currency}) — ekstresi henüz gelmemiş bir işlemi yansıtır.
				İlgili ekstre yüklenince bu satır o tarih aralığında <strong>otomatik silinir</strong> (çift kayıt olmaz).
			</div>
			<div>
				<label for="mtx-date" class="block text-sm font-medium text-gray-700 mb-1">İşlem Tarihi <span class="text-red-500">*</span></label>
				<input id="mtx-date" type="date" bind:value={manualForm.date} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
			</div>
			<div>
				<span class="block text-sm font-medium text-gray-700 mb-1">Yön <span class="text-red-500">*</span></span>
				<div class="grid grid-cols-2 gap-2">
					<button type="button" onclick={() => (manualForm.direction = 'out')} class="px-3 py-2 rounded-lg text-sm font-medium border cursor-pointer transition-colors {manualForm.direction === 'out' ? 'bg-rose-700 text-white border-rose-700' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}">Çıkış (−)</button>
					<button type="button" onclick={() => (manualForm.direction = 'in')} class="px-3 py-2 rounded-lg text-sm font-medium border cursor-pointer transition-colors {manualForm.direction === 'in' ? 'bg-teal-700 text-white border-teal-700' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}">Giriş (+)</button>
				</div>
			</div>
			<div>
				<label for="mtx-amount" class="block text-sm font-medium text-gray-700 mb-1">Tutar <span class="text-red-500">*</span></label>
				<MoneyInput bind:value={manualForm.amount} currency={manualTxAccount.currency} min={0} placeholder="0,00" />
			</div>
			<div>
				<label for="mtx-desc" class="block text-sm font-medium text-gray-700 mb-1">Açıklama <span class="text-red-500">*</span></label>
				<input id="mtx-desc" type="text" bind:value={manualForm.description} placeholder="Ör: YKB ANTALYA hesabına virman" class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
			</div>
			{#if manualError}<div class="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">{manualError}</div>{/if}
			<div class="flex justify-end gap-2 pt-1">
				<Button type="button" variant="secondary" onclick={() => (showManualTx = false)}>İptal</Button>
				<Button onclick={submitManualTx} loading={manualSaving}>Ekle</Button>
			</div>
		</div>
	{/if}
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Banka Hesabını Sil"
	message={deleteTarget ? `${deleteTarget.bank_name} (${deleteTarget.currency}) hesabını ve tüm işlemlerini silmek istediğinize emin misiniz?` : ''}
	confirmText="Sil"
	cancelText="Vazgeç"
	danger={true}
	onConfirm={deleteAccount}
/>
