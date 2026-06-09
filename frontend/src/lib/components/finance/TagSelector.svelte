<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import type { TransactionCategory } from '$lib/types/finance';
	import { categoryColorMap, availableColors as colorOptions, getColor } from '$lib/utils/colorMap';
	import { SELECTABLE_PAYMENT_METHODS, CATEGORIES_WITH_PAYMENT_METHOD } from '$lib/utils/paymentMethods';

	let {
		categories,
		currentCategoryId = null,
		currentNote = null,
		currentVendorId = null,
		currentVendorName = null,
		anchorX = 0,
		anchorY = 0,
		onAssign,
		onClose,
		onCreateCategory,
	}: {
		categories: TransactionCategory[];
		currentCategoryId?: number | null;
		currentNote?: string | null;
		currentVendorId?: number | null;
		currentVendorName?: string | null;
		anchorX?: number;
		anchorY?: number;
		onAssign: (categoryId: number | null, note: string | null, vendorId?: number | null, paymentMethod?: string | null, ccStatementId?: number | null) => void;
		onClose: () => void;
		onCreateCategory?: (name: string, color: string) => Promise<TransactionCategory | null>;
	} = $props();

	let note = $state(currentNote ?? '');
	let showNote = $state(!!currentNote);
	let showNewCategory = $state(false);
	let newCategoryName = $state('');
	let selectedColor = $state('gray');
	let creating = $state(false);
	let selectedCatId = $state<number | null>(currentCategoryId ?? null);

	// Cari seçimi
	let vendorSearch = $state(currentVendorName ?? '');
	let vendorResults = $state<Array<{ id: number; hesap_kodu: string; hesap_adi: string }>>([]);
	let selectedVendorId = $state<number | null>(currentVendorId ?? null);
	let selectedVendorName = $state<string | null>(currentVendorName ?? null);
	let vendorSearching = $state(false);
	let vendorSearchTimer: ReturnType<typeof setTimeout> | null = null;

	// Ödeme yöntemi seçimi
	let selectedPaymentMethod = $state<string | null>(null);

	// Kredi kartı ekstre seçimi
	let ccStatements = $state<Array<{
		id: number; card_name: string; bank_name: string;
		kesim_tarihi: string; son_odeme_tarihi: string;
		toplam_borc: number; paid_amount: number; remaining: number;
	}>>([]);
	let selectedCCStatementId = $state<number | null>(null);
	let ccLoading = $state(false);

	// Kredi taksit seçimi
	let creditPayments = $state<Array<{
		id: number; product_name: string; product_type: string; bank_name: string;
		currency: string; due_date: string; amount: number; installment_no: number;
	}>>([]);
	let selectedCreditPaymentId = $state<number | null>(null);
	let creditLoading = $state(false);

	// "Cari" kategorisi mi seçili?
	const isCariSelected = $derived(() => {
		if (!selectedCatId) return false;
		const cat = categories.find(c => c.id === selectedCatId);
		return cat?.name === 'Cari' || cat?.name === 'İade';
	});

	// "Kredi Kartı Borç Ödeme" kategorisi mi seçili?
	const isCCPaymentSelected = $derived(() => {
		if (!selectedCatId) return false;
		const cat = categories.find(c => c.id === selectedCatId);
		return cat?.name === 'Kredi Kartı Borç Ödeme';
	});

	// "Kredi Geri Ödeme" kategorisi mi seçili?
	const isCreditPaymentSelected = $derived(() => {
		if (!selectedCatId) return false;
		const cat = categories.find(c => c.id === selectedCatId);
		return cat?.name === 'Kredi Geri Ödeme';
	});

	// Bu kategori ödeme yöntemi seçimi gerektiriyor mu?
	const needsPaymentMethod = $derived(() => {
		if (!selectedCatId) return false;
		const cat = categories.find(c => c.id === selectedCatId);
		if (cat?.name === 'Kredi Kartı Borç Ödeme') return false; // KK ödemede ayrı akış
		return cat ? CATEGORIES_WITH_PAYMENT_METHOD.has(cat.name) : false;
	});

	// Dropdown pozisyonunu viewport'a sığdır
	let dropdownEl: HTMLDivElement | undefined = $state();
	let posX = $state(anchorX);
	let posY = $state(anchorY);

	function recalcPosition() {
		if (!dropdownEl) return;
		const rect = dropdownEl.getBoundingClientRect();
		const vw = window.innerWidth;
		const vh = window.innerHeight;

		let newX = anchorX;
		let newY = anchorY;

		// Sağa taşıyorsa sola kaydır
		if (newX + rect.width > vw - 8) {
			newX = vw - rect.width - 8;
		}
		// Alta taşıyorsa yukarı aç
		if (newY + rect.height > vh - 8) {
			newY = Math.max(8, vh - rect.height - 8);
		}

		posX = newX;
		posY = newY;
	}

	onMount(() => {
		recalcPosition();
	});

	// İçerik değişince pozisyonu yeniden hesapla
	$effect(() => {
		// eslint-disable-next-line no-unused-expressions
		isCariSelected();
		// eslint-disable-next-line no-unused-expressions
		isCCPaymentSelected();
		// eslint-disable-next-line no-unused-expressions
		isCreditPaymentSelected();
		// eslint-disable-next-line no-unused-expressions
		vendorResults.length;
		// eslint-disable-next-line no-unused-expressions
		selectedVendorId;
		// eslint-disable-next-line no-unused-expressions
		creditPayments.length;
		// eslint-disable-next-line no-unused-expressions
		ccStatements.length;
		// Tick sonrası DOM güncellendikten sonra yeniden hesapla
		requestAnimationFrame(() => recalcPosition());
	});

	const colorMap = categoryColorMap;

	function selectCategory(catId: number) {
		const cat = categories.find(c => c.id === catId);
		selectedCatId = catId;
		selectedPaymentMethod = null;
		selectedCCStatementId = null;

		// KK Borç Ödeme seçildi → CC ekstrelerini yükle
		if (cat?.name === 'Kredi Kartı Borç Ödeme') {
			loadCCStatements();
			return;
		}

		// Kredi Geri Ödeme seçildi → taksit listesini yükle
		if (cat?.name === 'Kredi Geri Ödeme') {
			loadCreditPayments();
			return;
		}

		// Ödeme yöntemi veya Cari seçimi gerektiren kategorilerde hemen atama yapma
		if (cat && (CATEGORIES_WITH_PAYMENT_METHOD.has(cat.name) || cat.name === 'Cari' || cat.name === 'İade')) {
			return;
		}

		if (showNote) {
			onAssign(catId, note.trim() || null);
		} else {
			onAssign(catId, null);
		}
	}

	async function loadCreditPayments() {
		creditLoading = true;
		try {
			creditPayments = await api.get<any>('/finance/cash-flow/credit-payments-unpaid');
		} catch (err) {
			console.error('Kredi taksit yükleme hatası:', err);
			creditPayments = [];
		}
		creditLoading = false;
	}

	async function loadCCStatements() {
		ccLoading = true;
		try {
			ccStatements = await api.get<any>('/finance/cash-flow/cc-statements-unpaid');
		} catch (err) {
			console.error('CC ekstre yükleme hatası:', err);
			ccStatements = [];
		}
		ccLoading = false;
	}

	function confirmAssignWithPayment() {
		const noteVal = note.trim() || selectedVendorName || null;
		onAssign(selectedCatId, noteVal, selectedVendorId, selectedPaymentMethod);
	}

	function clearTag() {
		onAssign(null, null, null);
	}

	async function handleCreateCategory() {
		const name = newCategoryName.trim();
		if (!name || !onCreateCategory) return;

		creating = true;
		const newCat = await onCreateCategory(name, selectedColor);
		creating = false;

		if (newCat) {
			showNewCategory = false;
			newCategoryName = '';
			selectCategory(newCat.id);
		}
	}

	// Cari arama
	function handleVendorSearch(query: string) {
		vendorSearch = query;
		selectedVendorId = null;
		selectedVendorName = null;

		if (vendorSearchTimer) clearTimeout(vendorSearchTimer);

		if (query.trim().length < 2) {
			vendorResults = [];
			return;
		}

		vendorSearchTimer = setTimeout(async () => {
			vendorSearching = true;
			try {
				const res = await api.get<any>(`/finance/cariler/vendors?search=${encodeURIComponent(query.trim())}&page_size=10`);
				vendorResults = (res.items ?? []).map((v: any) => ({
					id: v.id,
					hesap_kodu: v.hesap_kodu,
					hesap_adi: v.hesap_adi,
				}));
			} catch (err) {
				console.error('Cari arama hatası:', err);
				vendorResults = [];
			}
			vendorSearching = false;
		}, 300);
	}

	function selectVendor(vendor: { id: number; hesap_kodu: string; hesap_adi: string }) {
		selectedVendorId = vendor.id;
		selectedVendorName = vendor.hesap_adi;
		vendorSearch = vendor.hesap_adi;
		vendorResults = [];
	}
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<!-- Arka plan overlay — dışarı tıklanınca kapat (Escape ile de kapanır, dropdown odaktayken) -->
<div class="fixed inset-0 z-[9998]" onclick={onClose}></div>
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	bind:this={dropdownEl}
	class="fixed z-[9999] bg-white border border-gray-200 rounded-xl shadow-2xl p-2 w-64 max-h-[70vh] overflow-y-auto"
	style="left: {posX}px; top: {posY}px;"
	onclick={(e) => e.stopPropagation()}
	onkeydown={(e) => { if (e.key === 'Escape') onClose(); }}
>
	<div class="text-[10px] font-semibold text-gray-500 uppercase mb-1.5 px-1">Etiket Seç</div>
	<div class="space-y-0.5 max-h-52 overflow-y-auto">
		{#each categories as cat}
			{@const c = colorMap[cat.color] ?? colorMap.gray}
			<button
				onclick={() => selectCategory(cat.id)}
				class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left hover:bg-gray-50 active:bg-gray-100 transition-colors cursor-pointer {cat.id === selectedCatId ? 'ring-2 ring-blue-400' : ''}"
			>
				<span class="w-2.5 h-2.5 rounded-full {c.bg} {c.border} border shrink-0"></span>
				<span class="text-xs font-medium text-gray-700">{cat.name}</span>
				{#if cat.id === selectedCatId}
					<svg class="w-3 h-3 text-blue-500 ml-auto" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
					</svg>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Ödeme Yöntemi seçimi — belirli kategorilerde göster -->
	{#if needsPaymentMethod()}
		<div class="mt-2 border-t border-gray-100 pt-2">
			<div class="text-[10px] font-semibold text-gray-500 uppercase mb-1.5 px-1">Ödeme Yöntemi</div>
			<div class="flex items-center gap-1.5">
				{#each SELECTABLE_PAYMENT_METHODS as pm}
					<button
						onclick={() => { selectedPaymentMethod = pm.code; }}
						class="flex-1 text-center text-[10px] font-medium py-1.5 rounded-lg border transition-all cursor-pointer {selectedPaymentMethod === pm.code ? 'bg-blue-100 text-blue-700 border-blue-300 ring-1 ring-blue-400' : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'}"
					>
						{pm.icon} {pm.label}
					</button>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Cari seçimi — sadece "Cari" kategorisi seçiliyken göster -->
	{#if isCariSelected()}
		<div class="mt-2 border-t border-gray-100 pt-2">
			<div class="text-[10px] font-semibold text-gray-500 uppercase mb-1 px-1">Cari Seç</div>
			<div class="relative">
				<input
					type="text"
					value={vendorSearch}
					oninput={(e) => handleVendorSearch(e.currentTarget.value)}
					placeholder="Cari adı veya kodu ara..."
					class="w-full px-2 py-1.5 border border-gray-200 rounded-lg text-xs outline-none focus:border-teal-500"
				/>
				{#if vendorSearching}
					<div class="absolute right-2 top-1/2 -translate-y-1/2">
						<svg class="animate-spin h-3 w-3 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
							<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
							<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
						</svg>
					</div>
				{/if}
			</div>
			{#if selectedVendorId}
				<div class="mt-1 flex items-center gap-1 text-[10px] text-cyan-700 bg-cyan-50 border border-cyan-200 px-2 py-1 rounded-lg">
					<svg class="w-3 h-3 shrink-0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
					</svg>
					<span class="font-medium truncate">{selectedVendorName}</span>
					<button
						onclick={() => { selectedVendorId = null; selectedVendorName = null; vendorSearch = ''; }}
						class="ml-auto text-cyan-500 hover:text-cyan-700 cursor-pointer"
						aria-label="Cari seçimini temizle"
					>
						<svg class="w-3 h-3" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
							<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
						</svg>
					</button>
				</div>
			{/if}
			{#if vendorResults.length > 0 && !selectedVendorId}
				<div class="mt-1 max-h-32 overflow-y-auto border border-gray-100 rounded-lg">
					{#each vendorResults as vendor}
						<button
							onclick={() => selectVendor(vendor)}
							class="w-full text-left px-2 py-1.5 hover:bg-gray-50 cursor-pointer transition-colors text-xs"
						>
							<span class="font-medium text-gray-700">{vendor.hesap_adi}</span>
							<span class="text-[10px] text-gray-500 ml-1">({vendor.hesap_kodu})</span>
						</button>
					{/each}
				</div>
			{/if}
			</div>
	{/if}

	<!-- Kredi Kartı Borç Ödeme — ekstre seçimi -->
	{#if isCCPaymentSelected()}
		<div class="mt-2 border-t border-gray-100 pt-2">
			<div class="text-[10px] font-semibold text-gray-500 uppercase mb-1.5 px-1">Ekstre Seç</div>
			{#if ccLoading}
				<div class="text-[10px] text-gray-500 text-center py-2">Yükleniyor...</div>
			{:else if ccStatements.length === 0}
				<div class="text-[10px] text-gray-500 text-center py-2">Ödenmemiş ekstre yok</div>
			{:else}
				<div class="space-y-1 max-h-40 overflow-y-auto">
					{#each ccStatements as stmt}
						<button
							onclick={() => { selectedCCStatementId = stmt.id; }}
							class="w-full text-left px-2 py-1.5 rounded-lg border transition-all cursor-pointer {selectedCCStatementId === stmt.id ? 'bg-pink-50 border-pink-300 ring-1 ring-pink-400' : 'bg-gray-50 border-gray-200 hover:bg-gray-100'}"
						>
							<div class="text-[10px] font-medium text-gray-700">{stmt.card_name}</div>
							<div class="flex items-center justify-between mt-0.5">
								<span class="text-[10px] text-gray-500">{stmt.kesim_tarihi}</span>
								<span class="text-[10px] font-semibold text-rose-600">₺{stmt.remaining.toLocaleString('tr-TR', {minimumFractionDigits: 2})}</span>
							</div>
						</button>
					{/each}
				</div>
			{/if}
			{#if selectedCCStatementId}
				<button
					onclick={() => { onAssign(selectedCatId, null, null, 'kredi_karti', selectedCCStatementId); }}
					class="w-full mt-2 text-[11px] font-medium px-2 py-1.5 rounded-lg bg-pink-600 text-white hover:bg-pink-700 cursor-pointer transition-colors"
				>
					Ödemeyi Eşleştir
				</button>
			{/if}
		</div>
	{/if}

	<!-- Kredi Geri Ödeme — taksit seçimi -->
	{#if isCreditPaymentSelected()}
		<div class="mt-2 border-t border-gray-100 pt-2">
			<div class="text-[10px] font-semibold text-gray-500 uppercase mb-1.5 px-1">Taksit Seç</div>
			{#if creditLoading}
				<div class="text-[10px] text-gray-500 text-center py-2">Yükleniyor...</div>
			{:else if creditPayments.length === 0}
				<div class="text-[10px] text-gray-500 text-center py-2">Ödenmemiş taksit yok</div>
			{:else}
				<div class="space-y-1 max-h-48 overflow-y-auto">
					{#each creditPayments as cp}
						<button
							onclick={() => { selectedCreditPaymentId = cp.id; }}
							class="w-full text-left px-2 py-1.5 rounded-lg border transition-all cursor-pointer {selectedCreditPaymentId === cp.id ? 'bg-orange-50 border-orange-300 ring-1 ring-orange-400' : 'bg-gray-50 border-gray-200 hover:bg-gray-100'}"
						>
							<div class="text-[10px] font-medium text-gray-700 truncate">{cp.product_name}</div>
							<div class="flex items-center justify-between mt-0.5">
								<span class="text-[10px] text-gray-500">{cp.due_date} • #{cp.installment_no}</span>
								<span class="text-[10px] font-semibold {cp.currency === 'EUR' ? 'text-blue-600' : 'text-rose-600'}">
									{cp.currency === 'EUR' ? '€' : '₺'}{cp.amount.toLocaleString('tr-TR', {minimumFractionDigits: 2})}
								</span>
							</div>
						</button>
					{/each}
				</div>
			{/if}
			{#if selectedCreditPaymentId}
				<button
					onclick={() => { onAssign(selectedCatId, null, null, 'kredi', selectedCreditPaymentId); }}
					class="w-full mt-2 text-[11px] font-medium px-2 py-1.5 rounded-lg bg-orange-600 text-white hover:bg-orange-700 cursor-pointer transition-colors"
				>
					Taksiti Eşleştir
				</button>
			{/if}
		</div>
	{/if}

	<!-- Kaydet butonu — ödeme yöntemi veya cari seçimi gerektiren kategorilerde göster -->
	{#if needsPaymentMethod()}
		<div class="mt-2 border-t border-gray-100 pt-2">
			<button
				onclick={confirmAssignWithPayment}
				disabled={needsPaymentMethod() && !selectedPaymentMethod}
				class="w-full text-[11px] font-medium px-2 py-1.5 rounded-lg bg-teal-700 text-white hover:bg-teal-800 cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
			>
				Kaydet
			</button>
		</div>
	{/if}

	<!-- Yeni kategori ekleme -->
	<div class="mt-2 border-t border-gray-100 pt-2">
		{#if !showNewCategory}
			<button
				onclick={() => { showNewCategory = true; }}
				class="text-[10px] text-emerald-600 hover:text-emerald-700 cursor-pointer font-medium flex items-center gap-1"
			>
				<svg class="w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
				</svg>
				Yeni etiket ekle
			</button>
		{:else}
			<div class="space-y-1.5">
				<input
					type="text"
					bind:value={newCategoryName}
					placeholder="Etiket adı"
					class="w-full px-2 py-1.5 border border-gray-200 rounded-lg text-xs outline-none focus:border-emerald-400"
					onkeydown={(e) => { if (e.key === 'Enter') handleCreateCategory(); }}
				/>
				<!-- Renk seçici -->
				<div class="flex items-center gap-1 flex-wrap">
					{#each colorOptions as color}
						{@const c = colorMap[color]}
						<button
							onclick={() => { selectedColor = color; }}
							class="w-4 h-4 rounded-full {c.bg} {c.border} border cursor-pointer transition-transform {selectedColor === color ? 'ring-2 ring-blue-400 scale-110' : 'hover:scale-110'}"
							aria-label="Renk seç: {color}"
						></button>
					{/each}
				</div>
				<div class="flex items-center gap-1">
					<button
						onclick={handleCreateCategory}
						disabled={!newCategoryName.trim() || creating}
						class="flex-1 text-[10px] font-medium px-2 py-1 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
					>
						{creating ? 'Oluşturuluyor...' : 'Ekle'}
					</button>
					<button
						onclick={() => { showNewCategory = false; newCategoryName = ''; }}
						class="text-[10px] font-medium px-2 py-1 rounded-lg bg-gray-100 text-gray-500 hover:bg-gray-200 cursor-pointer transition-colors"
					>
						İptal
					</button>
				</div>
			</div>
		{/if}
	</div>

	<!-- Not alanı (Cari seçili değilken göster) -->
	{#if !isCariSelected()}
		<div class="mt-2 border-t border-gray-100 pt-2">
			{#if !showNote}
				<button
					onclick={() => { showNote = true; }}
					class="text-[10px] text-blue-500 hover:text-blue-700 cursor-pointer"
				>
					+ Açıklama ekle
				</button>
			{:else}
				<input
					type="text"
					bind:value={note}
					placeholder="ör: ABC İnşaat"
					class="w-full px-2 py-1.5 border border-gray-200 rounded-lg text-xs outline-none focus:border-teal-500"
					onkeydown={(e) => { if (e.key === 'Enter' && selectedCatId) selectCategory(selectedCatId); }}
				/>
			{/if}
		</div>
	{/if}

	<!-- Temizle -->
	{#if currentCategoryId}
		<button
			onclick={clearTag}
			class="w-full mt-1.5 text-[10px] text-rose-500 hover:text-rose-700 text-center py-1 cursor-pointer"
		>
			Etiketi kaldır
		</button>
	{/if}
</div>
