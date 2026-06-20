<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import Breadcrumb from '$lib/components/Breadcrumb.svelte';
	import Button from '$lib/components/Button.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { ChevronDown, Send, Printer, Download, X } from 'lucide-svelte';

	// ─── Types ───────────────────────────────────────────
	interface BankAccount {
		id: number;
		bank_name: string;
		branch_name: string | null;
		account_no: string | null;
		iban: string;
		currency: string;
		holder_name: string | null;
		label: string;
	}

	interface BankGroup {
		bank_name: string;
		accounts: BankAccount[];
	}

	// ─── Constants ──────────────────────────────────────
	const CURRENCIES = ['TRY', 'EUR', 'USD', 'GBP'];
	const CURRENCY_LABELS: Record<string, string> = { TRY: 'TL', EUR: 'Euro', USD: 'USD', GBP: 'GBP' };

	/**
	 * PDF blob'u sayfa içi modal'da gösterir. iOS Safari, yeni sekmede açılan
	 * blob URL'lerine erişemiyor ("WebKitBlobResource hatası 1"); bu nedenle
	 * PDF aynı sayfada iframe içinde render edilir + yanında "İndir" butonu
	 * sunulur. Aynı-origin blob'lar iframe'de sorunsuz çalışır.
	 */
	function downloadPdfBlob(blob: Blob, filename: string) {
		// Önceki önizlemeyi temizle
		if (pdfPreview) URL.revokeObjectURL(pdfPreview.url);
		const url = URL.createObjectURL(blob);
		pdfPreview = { url, filename };
	}

	function closePdfPreview() {
		if (pdfPreview) {
			URL.revokeObjectURL(pdfPreview.url);
			pdfPreview = null;
		}
	}

	/**
	 * PDF'i yazdır. Masaüstünde iframe.contentWindow.print() çalışır.
	 * iOS Safari'de iframe print sinyali çoğu zaman yoksayıldığı için
	 * fallback olarak blob URL ayrı bir boyutsuz pencerede açılıp print tetiklenir;
	 * bu da başarısızsa kullanıcı Paylaş → Yazdır'ı kullanabilir.
	 */
	function printPdf() {
		if (!pdfPreview) return;
		const iframe = document.getElementById('pdf-preview-iframe') as HTMLIFrameElement | null;
		try {
			if (iframe?.contentWindow) {
				iframe.contentWindow.focus();
				iframe.contentWindow.print();
				return;
			}
		} catch (err) {
			console.error('iframe print hatası:', err);
		}
		// Fallback — blob'u gizli iframe'e yükleyip print
		const hidden = document.createElement('iframe');
		hidden.style.position = 'fixed';
		hidden.style.right = '0';
		hidden.style.bottom = '0';
		hidden.style.width = '0';
		hidden.style.height = '0';
		hidden.style.border = '0';
		hidden.src = pdfPreview.url;
		hidden.onload = () => {
			try {
				hidden.contentWindow?.focus();
				hidden.contentWindow?.print();
			} catch (err) {
				console.error('Fallback print hatası:', err);
				showToast('Yazdırma başlatılamadı — Paylaş menüsünden Yazdır\'ı kullanın', 'error');
			}
			setTimeout(() => hidden.remove(), 60000);
		};
		document.body.appendChild(hidden);
	}

	// ─── State ──────────────────────────────────────────
	let activeTab = $state<'transfer' | 'exchange'>('transfer');
	let accounts = $state<BankAccount[]>([]);
	let loading = $state(true);
	let generating = $state(false);
	let pdfPreview = $state<{ url: string; filename: string } | null>(null);

	// Sol imza seçenekleri (sağ imza her zaman İsmail ÖZDEN)
	const LEFT_SIGNERS = [
		{ value: 'ugur', label: 'Uğur CARUS', title: 'Yön.Kur.Üyesi' },
		{ value: 'erol', label: 'Erol YILDIZ', title: 'Yön.Kur.Bşk.Yrd.' },
	];

	// Transfer form
	let transferForm = $state<{
		source_account_id: number;
		dest_account_id: number;
		amount: number | null;
		instruction_date: string;
		description: string;
		left_signer: 'ugur' | 'erol';
	}>({
		source_account_id: 0,
		dest_account_id: 0,
		amount: null,
		instruction_date: new Date().toISOString().split('T')[0],
		description: '',
		left_signer: 'ugur',
	});

	// Exchange form
	let exchangeForm = $state<{
		source_account_id: number;
		target_currency: string;
		amount: number | null;
		target_account_id: number;
		instruction_date: string;
		description: string;
		left_signer: 'ugur' | 'erol';
	}>({
		source_account_id: 0,
		target_currency: '',
		amount: null,
		target_account_id: 0,
		instruction_date: new Date().toISOString().split('T')[0],
		description: '',
		left_signer: 'ugur',
	});

	// Accordion dropdown state
	let openDropdown = $state<string | null>(null);
	let expandedBanks = $state<Record<string, boolean>>({});

	// ─── Derived ────────────────────────────────────────
	let sourceAccount = $derived(accounts.find(a => a.id === transferForm.source_account_id));
	let destAccount = $derived(accounts.find(a => a.id === transferForm.dest_account_id));

	// EFT/Havale: Hedef hesap listesi kaynak hesabın para birimi ile süzülür
	// (TL → TL, EUR → EUR vb. — farklı para birimi için "Döviz Bozma Talimatı" kullanılır)
	let transferDestAccounts = $derived(
		sourceAccount
			? accounts.filter(a => a.id !== transferForm.source_account_id && a.currency === sourceAccount!.currency)
			: accounts.filter(a => a.id !== transferForm.source_account_id)
	);

	// Kaynak hesap değişince mevcut hedef seçimi uyumsuzsa sıfırla
	$effect(() => {
		const src = accounts.find(a => a.id === transferForm.source_account_id);
		const dst = accounts.find(a => a.id === transferForm.dest_account_id);
		if (src && dst && dst.currency !== src.currency) {
			transferForm.dest_account_id = 0;
		}
	});

	// İşlem türü: TL+aynı banka → Havale, TL+farklı banka → EFT, TL dışı → Transfer
	let transferTerm = $derived.by<'havale' | 'eft' | 'transfer' | null>(() => {
		if (!sourceAccount || !destAccount) return null;
		const cur = (sourceAccount.currency || 'TRY').toUpperCase();
		if (cur !== 'TRY') return 'transfer';
		const a = (sourceAccount.bank_name || '').trim().toLowerCase();
		const b = (destAccount.bank_name || '').trim().toLowerCase();
		return a && b && a === b ? 'havale' : 'eft';
	});
	let transferTermLabel = $derived(
		transferTerm === 'havale' ? 'Havale (aynı banka)'
		: transferTerm === 'eft' ? 'EFT (farklı banka)'
		: transferTerm === 'transfer' ? 'Döviz Transferi'
		: null
	);

	let exchSourceAccount = $derived(accounts.find(a => a.id === exchangeForm.source_account_id));
	let availableTargetCurrencies = $derived(
		CURRENCIES.filter(c => exchSourceAccount ? c !== exchSourceAccount.currency : true)
	);
	let targetAccounts = $derived(
		accounts.filter(a =>
			a.currency === exchangeForm.target_currency &&
			exchSourceAccount ? a.bank_name === exchSourceAccount.bank_name : true
		)
	);

	let bankGroups = $derived(groupByBank(accounts));

	const canUse = hasPermission('finance.banks', 'view');

	// ─── Formatters ────────────────────────────────────
	function formatIban(iban: string): string {
		return iban.replace(/(.{4})/g, '$1 ').trim();
	}

	function groupByBank(accs: BankAccount[]): BankGroup[] {
		const map = new Map<string, BankAccount[]>();
		for (const a of accs) {
			if (!map.has(a.bank_name)) map.set(a.bank_name, []);
			map.get(a.bank_name)!.push(a);
		}
		return Array.from(map.entries())
			.sort((a, b) => a[0].localeCompare(b[0], 'tr'))
			.map(([bank_name, accounts]) => ({ bank_name, accounts }));
	}

	function getAccountLabel(acc: BankAccount): string {
		return `${acc.bank_name} — ${acc.currency} (${formatIban(acc.iban)})`;
	}

	// ─── Dropdown helpers ──────────────────────────────
	function toggleDropdown(id: string) {
		if (openDropdown === id) {
			openDropdown = null;
		} else {
			openDropdown = id;
			expandedBanks = {};
		}
	}

	function toggleBank(bankName: string) {
		expandedBanks = { ...expandedBanks, [bankName]: !expandedBanks[bankName] };
	}

	function selectAccount(dropdownId: string, accountId: number, formSetter: (id: number) => void) {
		formSetter(accountId);
		openDropdown = null;
	}

	function handleClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (!target.closest('.accordion-dropdown')) {
			openDropdown = null;
		}
	}

	// ─── Data ───────────────────────────────────────────
	async function loadAccounts() {
		loading = true;
		try {
			accounts = await api.get<BankAccount[]>('/finance/bank-instructions/accounts');
		} catch (err) {
			console.error('Hesaplar yüklenemedi:', err);
			showToast('Banka hesapları yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	// ─── PDF oluşturma ─────────────────────────────────
	async function generateTransferPDF() {
		if (!transferForm.source_account_id || !transferForm.dest_account_id || !transferForm.amount) {
			showToast('Lütfen tüm zorunlu alanları doldurun', 'error');
			return;
		}

		const amount = transferForm.amount;
		if (!Number.isFinite(amount as number) || (amount as number) <= 0) {
			showToast('Geçerli bir tutar giriniz', 'error');
			return;
		}

		generating = true;
		try {
			const res = await api.fetchRaw('/finance/bank-instructions/transfer', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					source_account_id: transferForm.source_account_id,
					dest_account_id: transferForm.dest_account_id,
					amount,
					instruction_date: transferForm.instruction_date || undefined,
					description: transferForm.description || undefined,
					left_signer: transferForm.left_signer,
				}),
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail || 'PDF oluşturulamadı');
			}
			const blob = await res.blob();
			downloadPdfBlob(blob, `eft-talimat-${transferForm.instruction_date || 'tarihsiz'}.pdf`);
			showToast('Talimat PDF hazırlandı', 'success');
		} catch (err: any) {
			console.error('PDF oluşturma hatası:', err);
			showToast(err?.message || 'PDF oluşturulamadı', 'error');
		} finally {
			generating = false;
		}
	}

	async function generateExchangePDF() {
		if (!exchangeForm.source_account_id || !exchangeForm.target_currency || !exchangeForm.amount) {
			showToast('Lütfen tüm zorunlu alanları doldurun', 'error');
			return;
		}

		const amount = exchangeForm.amount;
		if (!Number.isFinite(amount as number) || (amount as number) <= 0) {
			showToast('Geçerli bir tutar giriniz', 'error');
			return;
		}

		generating = true;
		try {
			const res = await api.fetchRaw('/finance/bank-instructions/currency-exchange', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					source_account_id: exchangeForm.source_account_id,
					target_currency: exchangeForm.target_currency,
					amount,
					target_account_id: exchangeForm.target_account_id || undefined,
					instruction_date: exchangeForm.instruction_date || undefined,
					description: exchangeForm.description || undefined,
					left_signer: exchangeForm.left_signer,
				}),
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail || 'PDF oluşturulamadı');
			}
			const blob = await res.blob();
			downloadPdfBlob(blob, `doviz-talimat-${exchangeForm.instruction_date || 'tarihsiz'}.pdf`);
			showToast('Döviz talimatı PDF hazırlandı', 'success');
		} catch (err: any) {
			console.error('PDF oluşturma hatası:', err);
			showToast(err?.message || 'PDF oluşturulamadı', 'error');
		} finally {
			generating = false;
		}
	}

	function handleEscKey(e: KeyboardEvent) {
		if (e.key === 'Escape' && pdfPreview) closePdfPreview();
	}

	// ─── Lifecycle ──────────────────────────────────────
	onMount(() => {
		loadAccounts();
		document.addEventListener('click', handleClickOutside);
		document.addEventListener('keydown', handleEscKey);
		return () => {
			document.removeEventListener('click', handleClickOutside);
			document.removeEventListener('keydown', handleEscKey);
			if (pdfPreview) URL.revokeObjectURL(pdfPreview.url);
		};
	});
</script>

{#snippet accountDropdown(id: string, groups: BankGroup[], selectedId: number, selectedAccount: BankAccount | undefined, placeholder: string, onSelect: (id: number) => void)}
	<div class="relative accordion-dropdown">
		<button
			type="button"
			onclick={() => toggleDropdown(id)}
			class="w-full flex items-center justify-between px-3 py-2.5 text-sm border rounded-xl bg-white text-left transition-colors
				{openDropdown === id ? 'border-teal-400 ring-2 ring-teal-500/20' : 'border-gray-200 hover:border-gray-300'}"
		>
			{#if selectedAccount}
				<span class="truncate">
					<span class="font-medium text-gray-900">{selectedAccount.bank_name}</span>
					<span class="text-gray-500"> — {selectedAccount.currency} ({formatIban(selectedAccount.iban)})</span>
				</span>
			{:else}
				<span class="text-gray-500">{placeholder}</span>
			{/if}
			<ChevronDown size={16} class="text-gray-500 shrink-0 ml-2 transition-transform {openDropdown === id ? 'rotate-180' : ''}" />
		</button>

		{#if openDropdown === id}
			<div class="absolute z-50 mt-1 w-full bg-white border border-gray-200 rounded-xl shadow-lg max-h-72 overflow-y-auto">
				{#if selectedId}
					<button
						type="button"
						onclick={() => selectAccount(id, 0, onSelect)}
						class="w-full text-left px-3 py-2 text-sm text-gray-500 hover:bg-gray-50 border-b border-gray-100"
					>
						Seçimi kaldır
					</button>
				{/if}
				{#each groups as group}
					<div>
						<button
							type="button"
							onclick={() => toggleBank(group.bank_name)}
							class="w-full flex items-center justify-between px-3 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors border-b border-gray-100"
						>
							<span class="text-sm font-semibold text-gray-700">{group.bank_name}</span>
							<div class="flex items-center gap-2">
								<span class="text-xs text-gray-500">{group.accounts.length} hesap</span>
								<ChevronDown size={14} class="text-gray-500 transition-transform {expandedBanks[group.bank_name] ? 'rotate-180' : ''}" />
							</div>
						</button>
						{#if expandedBanks[group.bank_name]}
							{#each group.accounts as acc}
								<button
									type="button"
									onclick={() => selectAccount(id, acc.id, onSelect)}
									class="w-full text-left px-4 py-2 text-sm transition-colors
										{acc.id === selectedId ? 'bg-teal-50 text-teal-700' : 'text-gray-700 hover:bg-gray-50'}"
								>
									<span class="font-medium">{acc.currency}</span>
									<span class="text-gray-500"> — {formatIban(acc.iban)}</span>
									{#if acc.branch_name}
										<span class="block text-xs text-gray-500 mt-0.5">{acc.branch_name} Şubesi{acc.account_no ? ` — ${acc.account_no}` : ''}</span>
									{/if}
								</button>
							{/each}
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/snippet}

<svelte:head>
	<title>Banka Talimatları | Sprenses</title>
</svelte:head>

<div class="max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-6">
	<!-- Başlık -->
	<div>
		<Breadcrumb items={[
			{ label: 'Finans', href: '/dashboard/finans' },
			{ label: 'Bankalar', href: '/dashboard/finans/bankalar' },
			{ label: 'Talimatlar' }
		]} />
		<PageHeader title="Banka Talimatları" description="EFT/Havale ve döviz bozma talimatı oluşturun" />
	</div>

	<!-- Tab Bar -->
	<SegmentedControl
		options={[
			{ value: 'transfer', label: 'EFT / Havale / Transfer' },
			{ value: 'exchange', label: 'Döviz Bozma Talimatı' },
		]}
		value={activeTab}
		onchange={(v) => (activeTab = v as 'transfer' | 'exchange')}
		ariaLabel="Talimat türü"
	/>

	{#if loading}
		<TableSkeleton rows={6} columns={2} showHeader={false} />
	{:else}
		<!-- ═══ EFT / HAVALE ═══ -->
		{#if activeTab === 'transfer'}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
				<div class="flex items-center justify-between gap-3 flex-wrap">
					<h2 class="text-lg font-semibold text-gray-900">EFT / Havale / Transfer Talimatı</h2>
					{#if transferTermLabel}
						<span class="px-2.5 py-1 text-xs font-medium rounded-full
							{transferTerm === 'havale' ? 'bg-blue-50 text-blue-700 border border-blue-200' :
							 transferTerm === 'eft' ? 'bg-teal-50 text-teal-700 border border-teal-200' :
							 'bg-purple-50 text-purple-700 border border-purple-200'}">
							{transferTermLabel}
						</span>
					{/if}
				</div>

				<!-- Kaynak Hesap -->
				<div>
					<span class="block text-sm font-medium text-gray-700 mb-1">Kaynak Hesap <span class="text-red-600">*</span></span>
					{@render accountDropdown(
						'transfer-src',
						bankGroups,
						transferForm.source_account_id,
						sourceAccount,
						'Hesap seçin...',
						(id) => { transferForm.source_account_id = id; }
					)}
					{#if sourceAccount}
						<p class="mt-1 text-xs text-gray-500">
							{sourceAccount.branch_name ? `${sourceAccount.branch_name} Şubesi` : ''}
							{sourceAccount.account_no ? ` — Hesap No: ${sourceAccount.account_no}` : ''}
						</p>
					{/if}
				</div>

				<!-- Hedef Hesap -->
				<div>
					<span class="block text-sm font-medium text-gray-700 mb-1">
						Hedef Hesap <span class="text-red-600">*</span>
						{#if sourceAccount}
							<span class="text-xs font-normal text-gray-500">
								(yalnızca {CURRENCY_LABELS[sourceAccount.currency] || sourceAccount.currency} hesaplar)
							</span>
						{/if}
					</span>
					{@render accountDropdown(
						'transfer-dest',
						groupByBank(transferDestAccounts),
						transferForm.dest_account_id,
						destAccount,
						sourceAccount ? 'Hesap seçin...' : 'Önce kaynak hesap seçin',
						(id) => { transferForm.dest_account_id = id; }
					)}
					{#if sourceAccount && transferDestAccounts.length === 0}
						<p class="mt-1 text-xs text-amber-600">
							Bu para biriminde ({CURRENCY_LABELS[sourceAccount.currency] || sourceAccount.currency}) başka hesap yok. Farklı para birimine transfer için "Döviz Bozma Talimatı" sekmesini kullanın.
						</p>
					{:else if destAccount}
						<p class="mt-1 text-xs text-gray-500">
							{destAccount.branch_name ? `${destAccount.branch_name} Şubesi` : ''}
							{destAccount.account_no ? ` — Hesap No: ${destAccount.account_no}` : ''}
						</p>
					{/if}
				</div>

				<!-- Tutar + Tarih -->
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
					<div>
						<label for="transfer-amount" class="block text-sm font-medium text-gray-700 mb-1">Tutar <span class="text-red-600">*</span></label>
						<MoneyInput
							id="transfer-amount"
							bind:value={transferForm.amount}
							currency={sourceAccount?.currency}
							min={0}
							placeholder="0,00"
						/>
					</div>
					<div>
						<label for="transfer-date" class="block text-sm font-medium text-gray-700 mb-1">Tarih</label>
						<Input id="transfer-date" type="date" bind:value={transferForm.instruction_date} />
					</div>
				</div>

				<!-- Açıklama -->
				<div>
					<label for="transfer-desc" class="block text-sm font-medium text-gray-700 mb-1">Açıklama <span class="text-gray-500 font-normal">(opsiyonel)</span></label>
					<Input id="transfer-desc" type="text" bind:value={transferForm.description} placeholder="Ör: Personel maaş ödemesi" />
				</div>

				<!-- Sol İmza (Sağ imza her zaman İsmail ÖZDEN) -->
				<div>
					<span class="block text-sm font-medium text-gray-700 mb-2">Sol İmza</span>
					<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
						{#each LEFT_SIGNERS as signer}
							<label class="flex items-start gap-3 px-3 py-2.5 border rounded-xl cursor-pointer transition-colors
								{transferForm.left_signer === signer.value
									? 'border-teal-400 bg-teal-50/40 ring-2 ring-teal-500/20'
									: 'border-gray-200 hover:border-gray-300 bg-white'}">
								<input
									type="radio"
									name="transfer-left-signer"
									value={signer.value}
									checked={transferForm.left_signer === signer.value}
									onchange={() => transferForm.left_signer = signer.value as 'ugur' | 'erol'}
									class="mt-0.5 w-4 h-4 text-teal-600 focus:ring-teal-500 cursor-pointer"
								/>
								<div class="flex-1 min-w-0">
									<div class="text-sm font-medium text-gray-900 truncate">{signer.label}</div>
									<div class="text-xs text-gray-500 truncate">{signer.title}</div>
								</div>
							</label>
						{/each}
					</div>
					<p class="mt-1 text-xs text-gray-500">Sağ imza: İsmail ÖZDEN — Yön.Kur.Baş.</p>
				</div>

				<!-- Oluştur Butonu -->
				<div class="flex justify-end pt-2">
					<Button
						onclick={generateTransferPDF}
						loading={generating}
						disabled={!transferForm.source_account_id || !transferForm.dest_account_id || !transferForm.amount}
					>
						{#if !generating}<Send size={16} />{/if} PDF Oluştur
					</Button>
				</div>
			</div>
		{/if}

		<!-- ═══ DÖVİZ BOZMA ═══ -->
		{#if activeTab === 'exchange'}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
				<h2 class="text-lg font-semibold text-gray-900">Döviz Bozma / Alma Talimatı</h2>

				<!-- Kaynak Hesap -->
				<div>
					<span class="block text-sm font-medium text-gray-700 mb-1">Kaynak Hesap <span class="text-red-600">*</span></span>
					{@render accountDropdown(
						'exch-src',
						bankGroups,
						exchangeForm.source_account_id,
						exchSourceAccount,
						'Hesap seçin...',
						(id) => { exchangeForm.source_account_id = id; exchangeForm.target_currency = ''; exchangeForm.target_account_id = 0; }
					)}
					{#if exchSourceAccount}
						<p class="mt-1 text-xs text-gray-500">
							{exchSourceAccount.branch_name ? `${exchSourceAccount.branch_name} Şubesi` : ''}
							{exchSourceAccount.account_no ? ` — Hesap No: ${exchSourceAccount.account_no}` : ''}
						</p>
					{/if}
				</div>

				<!-- Hedef Para Birimi -->
				<div>
					<label for="exch-target-cur" class="block text-sm font-medium text-gray-700 mb-1">Hedef Para Birimi <span class="text-red-600">*</span></label>
					<Select id="exch-target-cur" bind:value={exchangeForm.target_currency}>
						<option value="">Seçin...</option>
						{#each availableTargetCurrencies as cur}
							<option value={cur}>{CURRENCY_LABELS[cur] || cur} ({cur})</option>
						{/each}
					</Select>
				</div>

				<!-- Tutar + Tarih -->
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
					<div>
						<label for="exch-amount" class="block text-sm font-medium text-gray-700 mb-1">Tutar <span class="text-red-600">*</span></label>
						<MoneyInput
							id="exch-amount"
							bind:value={exchangeForm.amount}
							currency={exchSourceAccount?.currency}
							min={0}
							placeholder="0,00"
						/>
					</div>
					<div>
						<label for="exch-date" class="block text-sm font-medium text-gray-700 mb-1">Tarih</label>
						<Input id="exch-date" type="date" bind:value={exchangeForm.instruction_date} />
					</div>
				</div>

				<!-- Hedef Hesap (opsiyonel) -->
				{#if exchangeForm.target_currency && targetAccounts.length > 0}
					<div>
						<span class="block text-sm font-medium text-gray-700 mb-1">Hedef Hesap <span class="text-gray-500 font-normal">(aktarılacak hesap)</span></span>
						{@render accountDropdown(
							'exch-target',
							groupByBank(targetAccounts),
							exchangeForm.target_account_id,
							accounts.find(a => a.id === exchangeForm.target_account_id),
							'Seçilmedi (sadece bozma)',
							(id) => { exchangeForm.target_account_id = id; }
						)}
					</div>
				{/if}

				<!-- Açıklama -->
				<div>
					<label for="exch-desc" class="block text-sm font-medium text-gray-700 mb-1">Açıklama <span class="text-gray-500 font-normal">(opsiyonel)</span></label>
					<Input id="exch-desc" type="text" bind:value={exchangeForm.description} />
				</div>

				<!-- Sol İmza (Sağ imza her zaman İsmail ÖZDEN) -->
				<div>
					<span class="block text-sm font-medium text-gray-700 mb-2">Sol İmza</span>
					<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
						{#each LEFT_SIGNERS as signer}
							<label class="flex items-start gap-3 px-3 py-2.5 border rounded-xl cursor-pointer transition-colors
								{exchangeForm.left_signer === signer.value
									? 'border-teal-400 bg-teal-50/40 ring-2 ring-teal-500/20'
									: 'border-gray-200 hover:border-gray-300 bg-white'}">
								<input
									type="radio"
									name="exch-left-signer"
									value={signer.value}
									checked={exchangeForm.left_signer === signer.value}
									onchange={() => exchangeForm.left_signer = signer.value as 'ugur' | 'erol'}
									class="mt-0.5 w-4 h-4 text-teal-600 focus:ring-teal-500 cursor-pointer"
								/>
								<div class="flex-1 min-w-0">
									<div class="text-sm font-medium text-gray-900 truncate">{signer.label}</div>
									<div class="text-xs text-gray-500 truncate">{signer.title}</div>
								</div>
							</label>
						{/each}
					</div>
					<p class="mt-1 text-xs text-gray-500">Sağ imza: İsmail ÖZDEN — Yön.Kur.Baş.</p>
				</div>

				<!-- Oluştur Butonu -->
				<div class="flex justify-end pt-2">
					<Button
						onclick={generateExchangePDF}
						loading={generating}
						disabled={!exchangeForm.source_account_id || !exchangeForm.target_currency || !exchangeForm.amount}
					>
						{#if !generating}<Send size={16} />{/if} PDF Oluştur
					</Button>
				</div>
			</div>
		{/if}
	{/if}
</div>

<!-- PDF Önizleme Modal (iOS Safari uyumlu — iframe, aynı origin blob) -->
{#if pdfPreview}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-[60] bg-black/70 flex items-center justify-center p-2 sm:p-4"
		onclick={(e) => { if (e.target === e.currentTarget) closePdfPreview(); }}
	>
		<div class="bg-white rounded-xl w-full max-w-5xl h-[95vh] sm:h-[90vh] flex flex-col overflow-hidden shadow-2xl">
			<div class="flex items-center justify-between gap-2 px-3 sm:px-4 py-2.5 border-b border-gray-200 bg-gray-50">
				<h3 class="text-sm font-semibold text-gray-800 truncate">{pdfPreview.filename}</h3>
				<div class="flex gap-1.5 sm:gap-2 shrink-0">
					<Button variant="secondary" size="sm" onclick={printPdf} title="Yazdır">
						<Printer size={14} />
						<span class="hidden sm:inline">Yazdır</span>
					</Button>
					<!-- İndir: Button href dalı `download` özniteliğini iletmediğinden ham <a> (teal-700 AA) -->
					<a
						href={pdfPreview.url}
						download={pdfPreview.filename}
						class="touch-target inline-flex items-center justify-center gap-1.5 px-3 py-1.5 bg-teal-700 text-white text-xs font-medium rounded-lg hover:bg-teal-800 cursor-pointer shadow-sm"
						title="İndir"
					>
						<Download size={14} />
						<span class="hidden sm:inline">İndir</span>
					</a>
					<Button variant="ghost" size="sm" onclick={closePdfPreview} title="Kapat">
						<X size={14} />
						<span class="hidden sm:inline">Kapat</span>
					</Button>
				</div>
			</div>
			<iframe
				id="pdf-preview-iframe"
				src={pdfPreview.url}
				class="flex-1 border-0 w-full"
				title={pdfPreview.filename}
			></iframe>
		</div>
	</div>
{/if}
