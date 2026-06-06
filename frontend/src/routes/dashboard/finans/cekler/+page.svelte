<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge, { type BadgeType } from '$lib/components/StatusBadge.svelte';
	import Button from '$lib/components/Button.svelte';
	import { ReceiptText, Landmark, FileText, Clock, CalendarX, Database } from 'lucide-svelte';

	const STATUS_LABELS: Record<string, string> = { pending: 'Bekliyor', paid: 'Ödendi', cancelled: 'İptal' };
	const STATUS_BADGE: Record<string, BadgeType> = { pending: 'warning', paid: 'success', cancelled: 'neutral' };
	function statusSelectClass(s: string): string {
		if (s === 'pending') return 'bg-amber-50 text-amber-700 border-amber-300';
		if (s === 'paid') return 'bg-emerald-50 text-emerald-700 border-emerald-300';
		return 'bg-gray-100 text-gray-600 border-gray-300';
	}

	// Generic onay state
	let confirmState = $state<{ show: boolean; title: string; message: string; onConfirm: () => void | Promise<void> }>({
		show: false, title: '', message: '', onConfirm: () => {}
	});
	function askConfirm(title: string, message: string, onConfirm: () => void | Promise<void>) {
		confirmState = { show: true, title, message, onConfirm };
	}

	interface Check {
		id: number;
		check_type: string | null;
		sequence_no: number | null;
		check_no: string;
		vendor_code: string | null;
		vendor_name: string;
		description: string | null;
		city: string | null;
		due_date: string;
		amount_tl: number;
		currency: string;
		amount_currency: number;
		transaction_type: string | null;
		status: string;
		bank_transaction_id: number | null;
		match_number: number | null;
		matched_vendor_id: number | null;
	}

	interface Summary {
		total_count: number;
		total_amount: number;
		pending_count: number;
		pending_amount: number;
		pending_amount_eur: number | null;
		overdue_count: number;
		overdue_amount: number;
	}

	interface MonthGroup {
		key: string;
		label: string;
		checks: Check[];
		totalTL: number;
		totalEUR: number;
		pendingCount: number;
		pendingEUR: number;
		paidCount: number;
		paidEUR: number;
	}

	let checks = $state<Check[]>([]);
	let summary = $state<Summary | null>(null);
	let loading = $state(true);
	let uploading = $state(false);
	let sednaConfigured = $state(false);
	let sednaImporting = $state(false);
	let statusFilter = $state<string | null>(null);
	let search = $state('');
	let matching = $state(false);
	let sortBy = $state<string | null>('due_date');
	let sortDir = $state<'asc' | 'desc'>('asc');
	let eurRate = $state(1);
	let expandedMonths = $state<Record<string, boolean>>({});

	const canUse = hasPermission('finance.checks', 'use');

	const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	function formatCurrency(val: number): string {
		return val.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	function formatCompact(val: number): string {
		if (Math.abs(val) >= 1000000) return (val / 1000000).toFixed(1).replace('.', ',') + 'M';
		if (Math.abs(val) >= 1000) return Math.round(val / 1000).toLocaleString('tr-TR') + 'K';
		return formatCurrency(val);
	}

	function formatDate(d: string): string {
		return new Date(d).toLocaleDateString('tr-TR');
	}

	function isOverdue(check: Check): boolean {
		return check.status === 'pending' && new Date(check.due_date) < new Date(new Date().toDateString());
	}

	function toEUR(check: Check): number {
		if (check.currency === 'EUR') return check.amount_currency;
		if (eurRate > 0) return check.amount_tl / eurRate;
		return 0;
	}

	const monthGroups = $derived.by(() => {
		let filtered = checks;
		if (statusFilter) filtered = filtered.filter(c => c.status === statusFilter);
		if (search.trim()) {
			const q = search.trim().toLowerCase();
			filtered = filtered.filter(c =>
				c.check_no.toLowerCase().includes(q) ||
				c.vendor_name.toLowerCase().includes(q) ||
				(c.vendor_code || '').toLowerCase().includes(q)
			);
		}

		// Sıralama
		filtered = [...filtered].sort((a, b) => {
			if (sortBy === 'due_date') return sortDir === 'asc' ? a.due_date.localeCompare(b.due_date) : b.due_date.localeCompare(a.due_date);
			if (sortBy === 'amount_tl') return sortDir === 'asc' ? a.amount_tl - b.amount_tl : b.amount_tl - a.amount_tl;
			if (sortBy === 'vendor_name') return sortDir === 'asc' ? a.vendor_name.localeCompare(b.vendor_name, 'tr') : b.vendor_name.localeCompare(a.vendor_name, 'tr');
			return 0;
		});

		// Aylık gruplama
		const groups: Record<string, MonthGroup> = {};
		for (const c of filtered) {
			const d = new Date(c.due_date);
			const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
			if (!groups[key]) {
				groups[key] = {
					key,
					label: `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`,
					checks: [],
					totalTL: 0,
					totalEUR: 0,
					pendingCount: 0,
					pendingEUR: 0,
					paidCount: 0,
					paidEUR: 0,
				};
			}
			groups[key].checks.push(c);
			groups[key].totalTL += c.amount_tl;
			const eurVal = toEUR(c);
			groups[key].totalEUR += eurVal;
			if (c.status === 'pending') { groups[key].pendingCount++; groups[key].pendingEUR += eurVal; }
			if (c.status === 'paid') { groups[key].paidCount++; groups[key].paidEUR += eurVal; }
		}

		return Object.values(groups).sort((a, b) => a.key.localeCompare(b.key));
	});

	async function loadChecks() {
		try {
			// Tüm çekleri tek seferde al
			const res = await api.get<any>('/finance/checks/?page=1&page_size=500');
			checks = res.items;
		} catch (err) {
			console.error('Çek listesi alınamadı:', err);
		}
	}

	async function loadSummary() {
		try {
			summary = await api.get<Summary>('/finance/checks/summary');
		} catch (err) {
			console.error('Çek özeti alınamadı:', err);
		}
	}

	async function loadEurRate() {
		try {
			const res = await api.get<any>('/finance/exchange-rates/latest');
			const eur = res.rates?.find((r: any) => r.currency_code === 'EUR');
			if (eur?.forex_selling) eurRate = eur.forex_selling;
		} catch (err) {
			console.error('Kur alınamadı:', err);
		}
	}

	async function loadAll() {
		loading = true;
		await Promise.all([loadChecks(), loadSummary(), loadEurRate()]);
		// İlk ayı aç
		if (monthGroups.length > 0) {
			const today = new Date();
			const currentKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
			const found = monthGroups.find(g => g.key >= currentKey);
			if (found) expandedMonths[found.key] = true;
			else if (monthGroups.length) expandedMonths[monthGroups[0].key] = true;
		}
		loading = false;
	}

	async function uploadFile(file: File) {
		if (uploading) return;
		uploading = true;
		try {
			const formData = new FormData();
			formData.append('file', file);
			const res = await api.upload<any>('/finance/checks/upload', formData);
			showToast(`${res.new_checks} yeni çek yüklendi (${res.skipped_checks} mükerrer)`, 'success');
			await loadAll();
		} catch (err: any) {
			const msg = err?.body?.detail || 'Dosya yüklenemedi';
			showToast(msg, 'error');
			console.error('Çek yükleme hatası:', err);
		} finally {
			uploading = false;
		}
	}

	function handleFileSelect(files: File[]) {
		if (files.length > 0) uploadFile(files[0]);
	}

	async function loadSednaStatus() {
		try {
			const r = await api.get<{ configured: boolean }>('/finance/checks/sedna-status');
			sednaConfigured = !!r.configured;
		} catch (e) {
			console.error('Sedna durum sorgulanamadı:', e);
			sednaConfigured = false;
		}
	}
	async function importChecksFromSedna() {
		if (sednaImporting) return;
		sednaImporting = true;
		try {
			const r = await api.post<{ new_checks: number; updated_checks: number; skipped_checks: number; matched_to_bank: number }>(
				'/finance/checks/sedna-import', {}
			);
			const m = r.matched_to_bank > 0 ? ` · ${r.matched_to_bank} banka ile eşleşti (ödendi)` : '';
			showToast(
				`Sedna'dan ${r.new_checks} yeni çek · ${r.updated_checks} durum güncellendi${m} (${r.skipped_checks} mevcut)`,
				'success'
			);
			await loadAll();
		} catch (err: any) {
			console.error('Sedna çek içe aktarma hatası:', err);
			showToast(err?.body?.detail || "Sedna'dan çek aktarılamadı (SSH tüneli kapalı olabilir)", 'error');
		} finally {
			sednaImporting = false;
		}
	}

	function handleDropError(errors: string[]) {
		for (const err of errors) showToast(err, 'error', 4000);
	}

	function updateStatus(checkId: number, newStatus: string) {
		const check = checks.find(c => c.id === checkId);
		const isMatched = check && (check.bank_transaction_id || check.status === 'paid');
		if (newStatus === 'cancelled' && isMatched) {
			askConfirm(
				'Çek İptali',
				'Bu çek eşleştirilmiş. İptal etmek eşleştirmeyi de kaldıracak. Devam etmek istiyor musunuz?',
				() => executeStatusUpdate(checkId, newStatus)
			);
			return;
		}
		executeStatusUpdate(checkId, newStatus);
	}

	async function executeStatusUpdate(checkId: number, newStatus: string) {
		try {
			await api.patch(`/finance/checks/${checkId}/status?new_status=${newStatus}`, {});
			const idx = checks.findIndex(c => c.id === checkId);
			if (idx !== -1) {
				checks[idx].status = newStatus;
				if (newStatus === 'cancelled') checks[idx].bank_transaction_id = null;
			}
			await loadSummary();
			const labels: Record<string, string> = { pending: 'Bekliyor', paid: 'Ödendi', cancelled: 'İptal' };
			showToast(`Çek durumu: ${labels[newStatus]}`, 'success');
		} catch (err) {
			console.error('Durum güncellenemedi:', err);
			showToast('Durum güncellenemedi', 'error');
		}
	}

	let unsubFinance: (() => void) | null = null;

	onMount(() => {
		loadAll();
		loadSednaStatus();
		unsubFinance = onWsEvent('finance_updated', () => {
			loadAll();
		});
	});

	onDestroy(() => { unsubFinance?.(); });

	function setFilter(s: string | null) { statusFilter = s; }

	function toggleSort(col: string) {
		if (sortBy === col) { sortDir = sortDir === 'asc' ? 'desc' : 'asc'; }
		else { sortBy = col; sortDir = 'asc'; }
	}

	function toggleMonth(key: string) {
		expandedMonths[key] = !expandedMonths[key];
	}
</script>

<svelte:head>
	<title>Verilen Çekler - Sprenses</title>
</svelte:head>

<!-- Özet Kartları -->
<div class="mb-4">
	<PageHeader title="Verilen Çekler" description="Verilen çekleri vade, durum ve banka/cari eşleşmesine göre takip edin" />
</div>

{#if summary}
	<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-4">
		<StatCard
			label="Bekleyen"
			value={`${summary.pending_count} çek`}
			accent="amber"
			icon={Clock}
			hint={summary.pending_amount_eur != null ? `€${formatCurrency(summary.pending_amount_eur)}` : `₺${formatCurrency(summary.pending_amount)}`}
		/>
		<StatCard
			label="Vadesi Geçen"
			value={`${summary.overdue_count} çek`}
			accent="red"
			icon={CalendarX}
			hint={`₺${formatCurrency(summary.overdue_amount)}`}
		/>
	</div>
{/if}

<!-- Sedna (muhasebe DB) doğrudan içe aktarma -->
{#if canUse && sednaConfigured}
	<div class="bg-gradient-to-br from-teal-50 to-white border border-teal-200 rounded-xl p-4 mb-4 flex items-center justify-between gap-3 flex-wrap">
		<div class="min-w-0">
			<p class="text-sm font-semibold text-gray-900 inline-flex items-center gap-1.5"><Database size={16} class="text-teal-600" /> Sedna'dan verilen çekleri içe aktar</p>
			<p class="text-xs text-gray-500 mt-0.5 max-w-md leading-snug">Verilen çekler doğrudan muhasebe (Sedna) veritabanından çekilir — Excel'e gerek yok. Mükerrer eklenmez; durum (ödendi / bekliyor / iptal) Sedna'dan senkronize edilir.</p>
		</div>
		<Button onclick={importChecksFromSedna} loading={sednaImporting} class="shrink-0 w-full sm:w-auto"><Database size={16} /> Sedna'dan Çek Çek</Button>
	</div>
{/if}

<!-- Sürükle-Bırak Yükleme Alanı -->
{#if canUse}
	<div class="mb-4 relative">
		{#if uploading}
			<div class="absolute inset-0 z-10 bg-white/80 rounded-xl flex items-center justify-center">
				<div class="flex items-center gap-2 text-teal-600">
					<svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
					</svg>
					<span class="text-sm font-medium">Yükleniyor...</span>
				</div>
			</div>
		{/if}
		<FileDropzone
			accept=".xls,.xlsx"
			maxSize={50 * 1024 * 1024}
			disabled={uploading}
			label="Çek dosyasını sürükleyin veya tıklayın"
			hint=".xls veya .xlsx formatında — maks. 50 MB"
			onSelect={handleFileSelect}
			onError={handleDropError}
		/>
	</div>
{/if}

<!-- Filtre Çubuğu -->
<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-3 mb-4">
	<div class="flex items-center gap-2 flex-wrap">
		<button onclick={() => setFilter(null)} class="text-xs font-medium px-3 py-1.5 rounded-full border transition-colors cursor-pointer {!statusFilter ? 'bg-blue-100 text-blue-700 border-blue-300' : 'bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100'}">
			Tümü <span class="ml-1 text-[10px] opacity-70">{checks.length}</span>
		</button>
		<button onclick={() => setFilter('pending')} class="text-xs font-medium px-3 py-1.5 rounded-full border transition-colors cursor-pointer flex items-center gap-1 {statusFilter === 'pending' ? 'bg-amber-100 text-amber-700 border-amber-300' : 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100'}">
			<span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span> Bekleyen
		</button>
		<button onclick={() => setFilter('paid')} class="text-xs font-medium px-3 py-1.5 rounded-full border transition-colors cursor-pointer flex items-center gap-1 {statusFilter === 'paid' ? 'bg-emerald-100 text-emerald-700 border-emerald-300' : 'bg-emerald-50 text-emerald-600 border-emerald-200 hover:bg-emerald-100'}">
			<span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Ödenen
		</button>
		<button onclick={() => setFilter('cancelled')} class="text-xs font-medium px-3 py-1.5 rounded-full border transition-colors cursor-pointer flex items-center gap-1 {statusFilter === 'cancelled' ? 'bg-gray-200 text-gray-700 border-gray-400' : 'bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100'}">
			<span class="w-1.5 h-1.5 rounded-full bg-gray-400"></span> İptal
		</button>
		<div class="flex-1"></div>
		<input
			type="text"
			placeholder="Çek no, cari adı ara..."
			bind:value={search}
			class="px-3 py-1.5 text-xs border border-gray-200 rounded-lg outline-none focus:border-teal-400 w-full sm:w-48"
		/>
	</div>
</div>

<!-- Aylık Gruplar -->
{#if loading}
	<TableSkeleton rows={6} columns={4} />
{:else if monthGroups.length === 0}
	<EmptyState
		icon={ReceiptText}
		title="Çek kaydı bulunamadı"
		description="Yukarıdan Excel dosyası yükleyerek başlayın"
	/>
{:else}
	<div class="space-y-2">
		{#each monthGroups as group (group.key)}
			{@const isCurrentMonth = group.key === `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`}
			{@const isExpanded = expandedMonths[group.key]}

			<!-- Ay Başlığı -->
			<div class="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
				<button
					onclick={() => toggleMonth(group.key)}
					class="w-full flex items-center gap-3 px-4 py-3 transition-colors cursor-pointer
						{isCurrentMonth ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white' : 'bg-gray-50 hover:bg-gray-100'}"
				>
					<svg class="w-4 h-4 shrink-0 transition-transform duration-200 {isExpanded ? 'rotate-90' : ''} {isCurrentMonth ? 'text-white/80' : 'text-gray-500'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
					</svg>
					<span class="font-bold text-sm {isCurrentMonth ? '' : 'text-gray-700'}">{group.label}</span>
					<span class="text-[10px] font-medium {isCurrentMonth ? 'text-white/70' : 'text-gray-500'}">{group.checks.length} çek</span>

					<div class="ml-auto flex items-center gap-2 sm:gap-3">
						{#if group.pendingCount > 0}
							<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded-lg {isCurrentMonth ? 'text-amber-100 bg-amber-500/30' : 'text-amber-600 bg-amber-50'}">
								{group.pendingCount} bekleyen · €{formatCompact(group.pendingEUR)}
							</span>
						{/if}
						{#if group.paidCount > 0}
							<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded-lg {isCurrentMonth ? 'text-emerald-100 bg-emerald-500/30' : 'text-emerald-600 bg-emerald-50'}">
								{group.paidCount} ödenen · €{formatCompact(group.paidEUR)}
							</span>
						{/if}
					</div>
				</button>

				<!-- Ay İçeriği -->
				{#if isExpanded}
					<!-- Masaüstü tablo -->
					<div class="hidden sm:block overflow-x-auto">
						<table class="w-full text-xs">
							<thead class="bg-gray-50 border-y border-gray-200">
								<tr>
									<th class="px-3 py-2 text-left font-medium text-gray-500">
										<button onclick={() => toggleSort('due_date')} class="inline-flex items-center gap-1 cursor-pointer hover:text-gray-700">
											Vade
											{#if sortBy === 'due_date'}
												<svg class="w-3 h-3 {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
											{/if}
										</button>
									</th>
									<th class="px-3 py-2 text-left font-medium text-gray-500">Çek No</th>
									<th class="px-3 py-2 text-left font-medium text-gray-500">
										<button onclick={() => toggleSort('vendor_name')} class="inline-flex items-center gap-1 cursor-pointer hover:text-gray-700">
											Alıcı
											{#if sortBy === 'vendor_name'}
												<svg class="w-3 h-3 {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
											{/if}
										</button>
									</th>
									<th class="px-3 py-2 text-left font-medium text-gray-500">Hesap Kodu</th>
									<th class="px-3 py-2 text-right font-medium text-gray-500">
										<button onclick={() => toggleSort('amount_tl')} class="inline-flex items-center gap-1 cursor-pointer hover:text-gray-700 ml-auto">
											Tutar
											{#if sortBy === 'amount_tl'}
												<svg class="w-3 h-3 {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
											{/if}
										</button>
									</th>
									<th class="px-3 py-2 text-right font-medium text-gray-500">EUR</th>
									<th class="px-3 py-2 text-center font-medium text-gray-500">Durum</th>
									<th class="px-3 py-2 text-center font-medium text-gray-500">Eşleşme</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-gray-100">
								{#each group.checks as check (check.id)}
									{@const overdue = isOverdue(check)}
									<tr class="{overdue ? 'bg-rose-50/50' : 'hover:bg-gray-50'} transition-colors">
										<td class="px-3 py-2 whitespace-nowrap {overdue ? 'text-rose-600 font-bold' : 'text-gray-600'}">
											{formatDate(check.due_date)}
											{#if overdue}
												<span class="ml-1 text-[10px] text-rose-500">GEÇMİŞ</span>
											{/if}
										</td>
										<td class="px-3 py-2 font-mono text-gray-700">{check.check_no}</td>
										<td class="px-3 py-2 text-gray-800 font-medium max-w-[200px] truncate">{check.vendor_name}</td>
										<td class="px-3 py-2 text-gray-500 font-mono text-[10px]">{check.vendor_code || '-'}</td>
										<td class="px-3 py-2 text-right font-bold text-gray-800 whitespace-nowrap">
											{check.currency === 'TL' ? '₺' : '€'}{formatCurrency(check.amount_currency)}
										</td>
										<td class="px-3 py-2 text-right text-[10px] text-gray-500">
											€{formatCurrency(toEUR(check))}
										</td>
										<td class="px-3 py-2 text-center">
										{@render statusControl(check)}
									</td>
									<td class="px-3 py-2 text-center">
										{@render matchBadge(check)}
									</td>
									</tr>
								{/each}
							</tbody>
							<tfoot class="bg-gray-50 border-t border-gray-200">
								<tr>
									<td colspan="5" class="px-3 py-2 text-xs font-bold text-gray-600">
										Ay Toplamı ({group.checks.length} çek)
									</td>
									<td class="px-3 py-2 text-right text-xs font-bold text-gray-800">
										₺{formatCurrency(group.totalTL)}
									</td>
									<td class="px-3 py-2 text-right text-xs font-bold text-amber-700">
										€{formatCurrency(group.totalEUR)}
									</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>

					<!-- Mobil kart görünümü -->
					<div class="sm:hidden divide-y divide-gray-100">
						{#each group.checks as check (check.id)}
							{@const overdue = isOverdue(check)}
							<div class="px-3 py-3 {overdue ? 'bg-rose-50/50' : ''}">
								<!-- Üst satır: Alıcı + Tutar -->
								<div class="flex items-start justify-between gap-2 mb-1.5">
									<div class="min-w-0 flex-1">
										<div class="text-sm font-medium text-gray-800 truncate">{check.vendor_name}</div>
										<div class="flex items-center gap-2 mt-0.5">
											<span class="text-[10px] font-mono text-gray-500">{check.check_no}</span>
											{#if check.vendor_code}
												<span class="text-[10px] text-gray-500">· {check.vendor_code}</span>
											{/if}
										</div>
									</div>
									<div class="text-right shrink-0">
										<div class="text-sm font-bold text-gray-800">
											{check.currency === 'TL' ? '₺' : '€'}{formatCurrency(check.amount_currency)}
										</div>
										<div class="text-[10px] text-gray-500">€{formatCurrency(toEUR(check))}</div>
									</div>
								</div>

								<!-- Alt satır: Vade + Durum + Eşleşme -->
								<div class="flex items-center gap-2 flex-wrap">
									<span class="text-xs {overdue ? 'text-rose-600 font-bold' : 'text-gray-500'}">
										{formatDate(check.due_date)}
										{#if overdue}
											<span class="text-[10px] text-rose-500 ml-0.5">GEÇMİŞ</span>
										{/if}
									</span>

									{@render statusControl(check)}
									{@render matchBadge(check)}
								</div>
							</div>
						{/each}

						<!-- Mobil ay toplamı -->
						<div class="px-3 py-2.5 bg-gray-50 flex items-center justify-between">
							<span class="text-xs font-bold text-gray-600">Toplam ({group.checks.length} çek)</span>
							<div class="text-right">
								<span class="text-xs font-bold text-gray-800">₺{formatCurrency(group.totalTL)}</span>
								<span class="text-[10px] text-amber-700 font-bold ml-2">€{formatCurrency(group.totalEUR)}</span>
							</div>
						</div>
					</div>
				{/if}
			</div>
		{/each}
	</div>
{/if}

<!-- Onay Diyaloğu -->
<ConfirmDialog
	bind:show={confirmState.show}
	title={confirmState.title}
	message={confirmState.message}
	confirmText="Onayla"
	cancelText="Vazgeç"
	onConfirm={confirmState.onConfirm}
/>

<!-- Çek durumu — açık seçim (eski "gizli 3-döngülü toggle" yerine güvenli) -->
{#snippet statusControl(check: Check)}
	{#if canUse}
		<select
			value={check.status}
			onchange={(e) => updateStatus(check.id, e.currentTarget.value)}
			aria-label="Çek durumu"
			class="text-xs font-medium px-2 py-1 rounded-lg border cursor-pointer focus:outline-none focus:ring-2 focus:ring-teal-500 {statusSelectClass(check.status)}"
		>
			<option value="pending">Bekliyor</option>
			<option value="paid">Ödendi</option>
			<option value="cancelled">İptal</option>
		</select>
	{:else}
		<StatusBadge type={STATUS_BADGE[check.status] ?? 'neutral'}>{STATUS_LABELS[check.status] ?? check.status}</StatusBadge>
	{/if}
{/snippet}

<!-- Eşleşme rozeti (emoji yerine Lucide) -->
{#snippet matchBadge(check: Check)}
	{#if check.bank_transaction_id}
		<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-600 border border-blue-200" title="Banka hareketi ile eşleşti">
			<Landmark size={12} /> #{check.match_number || 'Banka'}
		</span>
	{:else if check.match_number}
		<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-teal-50 text-teal-700 border border-teal-200" title="Cari ile eşleşti">
			<FileText size={12} /> #{check.match_number}
		</span>
	{:else}
		<span class="text-gray-500 text-xs">—</span>
	{/if}
{/snippet}
