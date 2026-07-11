<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { WS_EVENT, BROADCAST_MODULE, RECON_STATUS } from '$lib/constants/realtime';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge, { type BadgeType } from '$lib/components/StatusBadge.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import Field from '$lib/components/Field.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import {
		AlertTriangle, Ban, Check, ChevronDown, CircleCheck, Eye, Hourglass,
		Link2, RefreshCw, RotateCcw, Search, ShieldAlert, Unplug, X,
	} from 'lucide-svelte';

	// Sabitler
	const STATUS_LABELS: Record<string, string> = {
		[RECON_STATUS.MATCHED]: 'Mutabık',
		[RECON_STATUS.SEDNA_PENDING]: 'Sedna Bekliyor',
		[RECON_STATUS.SEDNA_MISSING]: "Sedna'da Eksik",
		[RECON_STATUS.SEDNA_EXTRA]: "Sedna'da Fazla",
		[RECON_STATUS.DIRECTION_FLIP]: 'Yön Ters',
		[RECON_STATUS.DUPLICATE_SUSPECT]: 'Mükerrer Şüphesi',
	};
	const STATUS_BADGE: Record<string, BadgeType> = {
		[RECON_STATUS.MATCHED]: 'success',
		[RECON_STATUS.SEDNA_PENDING]: 'warning',
		[RECON_STATUS.SEDNA_MISSING]: 'error',
		[RECON_STATUS.SEDNA_EXTRA]: 'error',
		[RECON_STATUS.DIRECTION_FLIP]: 'error',
		[RECON_STATUS.DUPLICATE_SUSPECT]: 'error',
	};
	const RESOLUTION_LABELS: Record<string, string> = {
		manual: 'Elle çözüldü',
		ignored: 'Yoksayıldı',
		auto: 'Otomatik kapandı',
	};
	const ACTION_SUCCESS: Record<string, string> = {
		resolve: 'Kayıt çözüldü olarak işaretlendi',
		ignore: 'Kayıt yoksayıldı',
		reopen: 'Kayıt yeniden açıldı',
	};
	const CURRENCY_SYMBOLS: Record<string, string> = { EUR: '€', USD: '$', GBP: '£', TRY: '₺' };
	const SEDNA_DOWN_MSG = 'Sedna bağlantısı yok — tünel kapalı olabilir';
	const WS_ECHO_MS = 1500; // sunucu broadcast debounce (500ms) + iletim gecikmesi payı

	// Türetilmiş
	let canUse = $derived(hasPermission('accounting.mutabakat', 'use'));

	// Veri state — özet
	let summary = $state<any>(null);

	// Veri state — uyuşmazlık listesi
	let items = $state<any[]>([]);
	let itemsLoading = $state(true);
	let total = $state(0);
	let page = $state(1);
	let pageSize = $state(50);

	// Veri state — hesap eşleme
	let mappings = $state<{ accounts: any[]; unmatched_sedna: any[] } | null>(null);
	let mappingsLoading = $state(false);
	let mappingsError = $state('');
	let mapInputs = $state<Record<number, string>>({});
	let mapSaving = $state<Record<number, boolean>>({});

	// Veri state — hesap filtresi seçenekleri (finance.banks izni varsa canlı liste)
	let bankAccounts = $state<{ id: number; name: string }[]>([]);

	// UI state
	let activeTab = $state('items');
	let scanning = $state(false);
	let showUnmatched = $state(false);
	let lastLoadAt = 0; // WS yankı guard'ı (CashFlowTAccount deseni)

	// Filtre state
	let statusFilter = $state('');
	let accountFilter = $state('');
	let includeClosed = $state(false);
	let searchInput = $state(''); // input'a bağlı ham değer
	let search = $state(''); // 300ms debounce sonrası sorguya giden değer

	// Detay modalı
	let detailItem = $state<any>(null);
	let showDetail = $state(false);

	// Aksiyon state (çözüldü / yoksay / geri aç)
	let actionTarget = $state<any>(null);
	let actionSaving = $state(false);
	let showResolveConfirm = $state(false);
	let showReopenConfirm = $state(false);
	let showIgnoreModal = $state(false);
	let ignoreNote = $state('');

	// Eşleme aksiyon state
	let acceptTarget = $state<any>(null);
	let showAcceptConfirm = $state(false);
	let clearTarget = $state<any>(null);
	let showClearConfirm = $state(false);

	// Türetilmiş — özet kartları + sekmeler + hesap seçenekleri
	let criticalCount = $derived.by(() => {
		const s = summary?.open_by_status || {};
		return (s[RECON_STATUS.SEDNA_MISSING] || 0) + (s[RECON_STATUS.SEDNA_EXTRA] || 0)
			+ (s[RECON_STATUS.DIRECTION_FLIP] || 0) + (s[RECON_STATUS.DUPLICATE_SUSPECT] || 0);
	});
	let tabOptions = $derived([
		{ value: 'items', label: 'Uyuşmazlıklar', count: summary?.open_total },
		{ value: 'mappings', label: 'Hesap Eşleme' },
	]);
	let accountOptions = $derived.by(() => {
		if (bankAccounts.length > 0) return bankAccounts;
		// finance.banks izni yoksa mevcut listeden türet
		const m = new Map<number, string>();
		for (const it of items) {
			if (it.bank_account_id && !m.has(it.bank_account_id)) {
				m.set(it.bank_account_id, it.account_name || `Hesap #${it.bank_account_id}`);
			}
		}
		return [...m.entries()].map(([id, name]) => ({ id, name }));
	});
	let hasFilters = $derived(Boolean(statusFilter || accountFilter || search || includeClosed));

	// Formatlama
	function fmtDate(d: string | null): string {
		if (!d) return '—';
		return new Date(d + 'T00:00:00').toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}
	function fmtDateTime(d: string | null): string {
		if (!d) return '—';
		return new Date(d).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	}
	function fmtAmount(n: number | null | undefined, currency: string | null): string {
		if (n == null) return '—';
		const cur = currency || '';
		const sym = CURRENCY_SYMBOLS[cur] || (cur ? cur + ' ' : '');
		const v = Math.abs(n).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
		return `${n < 0 ? '-' : '+'}${sym}${v}`;
	}
	function amountCls(n: number | null | undefined): string {
		return (n ?? 0) < 0 ? 'text-red-600' : 'text-emerald-700';
	}
	function ibanTail(iban: string | null): string {
		if (!iban) return '—';
		return '…' + iban.replace(/\s/g, '').slice(-6);
	}

	// Veri fonksiyonları
	async function loadSummary() {
		try {
			summary = await api.get<any>('/accounting/mutabakat/summary');
		} catch (err) {
			console.error('Mutabakat özeti yüklenemedi:', err);
			showToast('Mutabakat özeti yüklenemedi', 'error');
		}
	}

	async function loadItems() {
		itemsLoading = true;
		try {
			const params = new URLSearchParams();
			params.set('page', String(page));
			params.set('page_size', String(pageSize));
			if (statusFilter) params.set('status', statusFilter);
			if (accountFilter) params.set('account_id', accountFilter);
			if (includeClosed) params.set('include_closed', 'true');
			if (search.trim()) params.set('q', search.trim());

			const data = await api.get<any>(`/accounting/mutabakat/items?${params}`);
			items = data.items;
			total = data.total;
		} catch (err) {
			console.error('Uyuşmazlık listesi yüklenemedi:', err);
			showToast('Uyuşmazlık listesi yüklenemedi', 'error');
		} finally {
			itemsLoading = false;
			lastLoadAt = Date.now();
		}
	}

	async function loadMappings() {
		mappingsLoading = true;
		mappingsError = '';
		try {
			const data = await api.get<any>('/accounting/mutabakat/account-mappings');
			mappings = data;
			const inputs: Record<number, string> = {};
			for (const a of data.accounts) inputs[a.account_id] = a.current_code || '';
			mapInputs = inputs;
		} catch (err: any) {
			console.error('Hesap eşleme verisi yüklenemedi:', err);
			mappings = null;
			mappingsError = err?.message && err.message !== 'Bir hata oluştu' ? err.message : SEDNA_DOWN_MSG;
		} finally {
			mappingsLoading = false;
		}
	}

	async function loadBankAccounts() {
		// Dropdown için banka hesap listesi — finance.banks izni gerekir; yoksa items'tan türetilir
		if (!hasPermission('finance.banks', 'view')) return;
		try {
			const list = await api.get<any[]>('/finance/banks/accounts/');
			bankAccounts = list.map((a) => ({ id: a.id, name: `${a.bank_name} (${a.currency})` }));
		} catch (err) {
			console.error('Banka hesap listesi yüklenemedi:', err);
			showToast('Banka hesap listesi yüklenemedi — filtre mevcut kayıtlardan türetilecek', 'error');
		}
	}

	// Tarama (POST /run)
	async function runScan() {
		if (scanning) return;
		scanning = true;
		try {
			const r = await api.post<any>('/accounting/mutabakat/run', { window_days: 45 });
			if ((r?.accounts_scanned ?? 0) === 0) {
				showToast('Eşlenmiş (onaylı) hesap yok — önce Hesap Eşleme sekmesinden hesapları eşleyin', 'info');
			} else {
				showToast(`${r.accounts_scanned} hesap tarandı · ${r['new']} yeni uyuşmazlık · ${r.auto_closed} otomatik kapandı`, 'success');
			}
			await Promise.all([loadSummary(), loadItems()]);
		} catch (err: any) {
			console.error('Mutabakat taraması başarısız:', err);
			showToast(err?.message && err.message !== 'Bir hata oluştu' ? err.message : SEDNA_DOWN_MSG, 'error');
		} finally {
			scanning = false;
		}
	}

	// Kayıt aksiyonları (çözüldü / yoksay / geri aç)
	async function applyItemAction(item: any, action: 'resolve' | 'ignore' | 'reopen', note: string | null): Promise<boolean> {
		actionSaving = true;
		try {
			const resp = await api.patch<any>(`/accounting/mutabakat/items/${item.id}`, { action, note });
			if (resp?.requires_approval || resp?.request_id) {
				showToast('İşlem onaya gönderildi', 'info');
				return true;
			}
			showToast(ACTION_SUCCESS[action], 'success');
			await Promise.all([loadSummary(), loadItems()]);
			return true;
		} catch (err: any) {
			console.error('Mutabakat kaydı güncellenemedi:', err);
			showToast(err?.message || 'İşlem sırasında hata oluştu', 'error');
			return false;
		} finally {
			actionSaving = false;
		}
	}

	function openDetail(item: any) { detailItem = item; showDetail = true; }
	function openResolve(item: any) { actionTarget = item; showResolveConfirm = true; }
	function openReopen(item: any) { actionTarget = item; showReopenConfirm = true; }
	function openIgnore(item: any) { actionTarget = item; ignoreNote = ''; showIgnoreModal = true; }

	async function confirmResolve() { if (actionTarget) await applyItemAction(actionTarget, 'resolve', null); }
	async function confirmReopen() { if (actionTarget) await applyItemAction(actionTarget, 'reopen', null); }
	async function submitIgnore() {
		if (!actionTarget) return;
		const ok = await applyItemAction(actionTarget, 'ignore', ignoreNote.trim() || null);
		if (ok) showIgnoreModal = false;
	}

	// Hesap eşleme aksiyonları
	async function saveMapping(accountId: number, code: string | null, confirmed: boolean, successMsg: string) {
		mapSaving[accountId] = true;
		try {
			const resp = await api.patch<any>(`/accounting/mutabakat/account-mappings/${accountId}`, {
				sedna_account_code: code,
				confirmed,
			});
			if (resp?.requires_approval || resp?.request_id) {
				showToast('İşlem onaya gönderildi', 'info');
				return;
			}
			showToast(successMsg, 'success');
			await Promise.all([loadMappings(), loadSummary()]);
		} catch (err: any) {
			console.error('Hesap eşleme kaydedilemedi:', err);
			showToast(err?.message || 'Hesap eşleme kaydedilemedi', 'error');
		} finally {
			mapSaving[accountId] = false;
		}
	}

	function openAccept(acc: any) { acceptTarget = acc; showAcceptConfirm = true; }
	function openClear(acc: any) { clearTarget = acc; showClearConfirm = true; }
	async function confirmAccept() {
		if (acceptTarget?.suggestion) {
			await saveMapping(acceptTarget.account_id, acceptTarget.suggestion.code, true, 'Öneri onaylandı — hesap eşlendi');
		}
	}
	async function confirmClear() {
		if (clearTarget) await saveMapping(clearTarget.account_id, null, false, 'Eşleme temizlendi');
	}
	async function saveManualMapping(acc: any) {
		const code = (mapInputs[acc.account_id] || '').trim();
		await saveMapping(acc.account_id, code || null, Boolean(code), code ? 'Sedna kodu kaydedildi' : 'Eşleme temizlendi');
	}

	// UI yardımcıları
	function setTab(v: string) {
		activeTab = v;
		if (v === 'mappings' && !mappings && !mappingsLoading) loadMappings();
	}
	function changePage(p: number) { page = p; loadItems(); }
	function changePageSize(s: number) { pageSize = s; page = 1; loadItems(); }

	// Arama debounce (300ms): searchInput → search
	let searchTimer: ReturnType<typeof setTimeout>;
	$effect(() => {
		const v = searchInput;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { search = v.trim(); }, 300);
		return () => clearTimeout(searchTimer);
	});

	// Filtre değişiminde sayfayı 1'e al ve yeniden yükle (ilk yüklemede tetiklenmez)
	let filterKey = $derived(`${statusFilter}|${accountFilter}|${includeClosed}|${search}`);
	let prevFilterKey = '';
	$effect(() => {
		const fk = filterKey;
		if (prevFilterKey && fk !== prevFilterKey) { page = 1; loadItems(); }
		prevFilterKey = fk;
	});

	// Lifecycle
	let unsubFinance: (() => void) | null = null;
	onMount(() => {
		loadSummary();
		loadItems();
		loadBankAccounts();
		unsubFinance = onWsEvent(WS_EVENT.FINANCE_UPDATED, (msg: any) => {
			if (msg?.module && msg.module !== BROADCAST_MODULE.RECON) return;
			// Kendi mutasyonumuzun yankısı: son yüklemeden hemen sonra gelen event'i atla
			if (Date.now() - lastLoadAt < WS_ECHO_MS) return;
			loadSummary();
			loadItems();
			if (activeTab === 'mappings') loadMappings();
		});
	});
	onDestroy(() => { unsubFinance?.(); });
</script>

<svelte:head><title>Sedna Mutabakat · Sprenses</title></svelte:head>

<div class="space-y-5 sm:space-y-6">
	<!-- Başlık -->
	<PageHeader title="Sedna Mutabakat" description="Banka ekstresi ↔ Sedna muhasebe defteri uyuşmazlık takibi — banka verisi esastır">
		{#snippet actions()}
			{#if canUse}
				<Button onclick={runScan} loading={scanning}><RefreshCw size={16} /> Şimdi Tara</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<!-- Özet kartları -->
	{#if summary}
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
			<StatCard
				label="Açık Uyuşmazlık"
				value={summary.open_total}
				accent={summary.open_total > 0 ? 'red' : 'emerald'}
				icon={AlertTriangle}
				hint={summary.oldest_open_date ? `En eski: ${fmtDate(summary.oldest_open_date)}` : 'Açık kayıt yok'}
			/>
			<StatCard
				label="Sedna Bekleyen"
				value={summary.open_by_status?.[RECON_STATUS.SEDNA_PENDING] ?? 0}
				accent="amber"
				icon={Hourglass}
				hint="Gecikmeli giriş — uyuşmazlık değil"
			/>
			<StatCard
				label="Kritik"
				value={criticalCount}
				accent={criticalCount > 0 ? 'red' : 'gray'}
				icon={ShieldAlert}
				hint="Eksik · fazla · yön ters · mükerrer"
			/>
			<StatCard
				label="Eşlenen Hesap"
				value={`${summary.mapped_accounts}/${summary.total_accounts}`}
				accent="teal"
				icon={Link2}
				hint={summary.last_run?.run_at ? `Son tarama: ${fmtDateTime(summary.last_run.run_at)}` : 'Henüz tarama yapılmadı'}
			/>
		</div>
	{/if}

	<!-- Sekmeler -->
	<SegmentedControl options={tabOptions} value={activeTab} onchange={setTab} ariaLabel="Mutabakat görünümü" />

	{#if activeTab === 'items'}
		<!-- Filtreler -->
		<div class="flex flex-col sm:flex-row gap-2 sm:gap-3 sm:items-center sm:flex-wrap">
			<Input
				type="search"
				size="sm"
				icon={Search}
				clearable
				bind:value={searchInput}
				aria-label="Açıklamalarda ara"
				placeholder="Banka veya Sedna açıklamasında ara…"
				class="sm:w-72"
			/>
			<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={statusFilter} aria-label="Duruma göre filtrele">
				<option value="">Tüm Durumlar</option>
				{#each Object.entries(STATUS_LABELS) as [val, label] (val)}
					<option value={val}>{label}</option>
				{/each}
			</Select>
			<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={accountFilter} aria-label="Hesaba göre filtrele">
				<option value="">Tüm Hesaplar</option>
				{#each accountOptions as acc (acc.id)}
					<option value={String(acc.id)}>{acc.name}</option>
				{/each}
			</Select>
			<label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
				<input type="checkbox" bind:checked={includeClosed} class="w-4 h-4 accent-teal-700 focus:ring-teal-500" />
				Kapalıları da göster
			</label>
			<span class="text-sm text-gray-500 sm:ml-auto">{total} kayıt</span>
		</div>

		<!-- Uyuşmazlık listesi -->
		<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
			{#if itemsLoading}
				<TableSkeleton rows={6} columns={7} />
			{:else if items.length === 0}
				<EmptyState
					icon={CircleCheck}
					title="Uyuşmazlık yok — her şey mutabık"
					description={hasFilters ? 'Filtrelere uygun kayıt bulunamadı.' : 'Banka ve Sedna kayıtları arasında açık uyuşmazlık bulunmuyor. Güncel durumu görmek için tarama yapabilirsiniz.'}
					ctaText={canUse && !hasFilters ? 'Şimdi Tara' : ''}
					onCta={canUse && !hasFilters ? runScan : null}
				/>
			{:else}
				<!-- Masaüstü tablo -->
				<div class="hidden md:block overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-gray-200 bg-gray-50 text-left">
								<th class="px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Tarih</th>
								<th class="px-4 py-3 font-medium text-gray-600">Hesap</th>
								<th class="px-4 py-3 font-medium text-gray-600">Banka Açıklaması</th>
								<th class="px-4 py-3 font-medium text-gray-600 text-right">Tutar</th>
								<th class="px-4 py-3 font-medium text-gray-600">Sedna</th>
								<th class="px-4 py-3 font-medium text-gray-600 hidden xl:table-cell">Sedna Kullanıcı</th>
								<th class="px-4 py-3 font-medium text-gray-600 text-center">Durum</th>
								<th class="px-4 py-3 font-medium text-gray-600 text-right">İşlemler</th>
							</tr>
						</thead>
						<tbody>
							{#each items as it (it.id)}
								<tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors">
									<td class="px-4 py-3 text-gray-600 whitespace-nowrap">{fmtDate(it.event_date)}</td>
									<td class="px-4 py-3 text-gray-700">
										<div class="truncate max-w-[140px]" title={it.account_name || ''}>{it.account_name || '—'}</div>
									</td>
									<td class="px-4 py-3 text-gray-700">
										<div class="truncate max-w-[240px]" title={it.description || ''}>{it.description || '—'}</div>
									</td>
									<td class="px-4 py-3 text-right font-semibold tabular-nums whitespace-nowrap {amountCls(it.amount)}">{fmtAmount(it.amount, it.currency)}</td>
									<td class="px-4 py-3 text-gray-700">
										{#if it.sedna_voucher || it.sedna_description}
											{#if it.sedna_voucher}<div class="font-medium text-gray-900">{it.sedna_voucher}</div>{/if}
											{#if it.sedna_description}<div class="text-xs text-gray-500 truncate max-w-[180px]" title={it.sedna_description}>{it.sedna_description}</div>{/if}
										{:else}
											<span class="text-gray-500">—</span>
										{/if}
									</td>
									<td class="px-4 py-3 text-gray-600 hidden xl:table-cell">
										<div class="truncate max-w-[120px]" title={it.sedna_record_user || ''}>{it.sedna_record_user || '—'}</div>
									</td>
									<td class="px-4 py-3 text-center">
										<StatusBadge type={STATUS_BADGE[it.status] ?? 'neutral'}>{STATUS_LABELS[it.status] ?? it.status}</StatusBadge>
										{#if it.resolved_at}
											<div class="text-xs text-gray-500 mt-0.5">{RESOLUTION_LABELS[it.resolution] ?? it.resolution}</div>
										{/if}
									</td>
									<td class="px-4 py-3">
										<div class="flex items-center justify-end gap-1">
											<button onclick={() => openDetail(it)} aria-label="Detay" title="Detay" class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"><Eye size={16} /></button>
											{#if canUse}
												{#if !it.resolved_at}
													<button onclick={() => openResolve(it)} aria-label="Çözüldü olarak işaretle" title="Çözüldü olarak işaretle" class="p-2 text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors cursor-pointer"><Check size={16} /></button>
													<button onclick={() => openIgnore(it)} aria-label="Yoksay" title="Yoksay" class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"><Ban size={16} /></button>
												{:else}
													<button onclick={() => openReopen(it)} aria-label="Geri aç" title="Geri aç" class="p-2 text-amber-600 hover:bg-amber-50 rounded-lg transition-colors cursor-pointer"><RotateCcw size={16} /></button>
												{/if}
											{/if}
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- Mobil kart görünümü -->
				<div class="md:hidden divide-y divide-gray-100">
					{#each items as it (it.id)}
						<div class="p-3">
							<div class="flex items-start justify-between gap-2 mb-1.5">
								<div class="min-w-0 flex-1">
									<div class="font-medium text-gray-900 truncate">{it.account_name || '—'}</div>
									<div class="text-xs text-gray-500 mt-0.5">{fmtDate(it.event_date)}</div>
								</div>
								<StatusBadge type={STATUS_BADGE[it.status] ?? 'neutral'}>{STATUS_LABELS[it.status] ?? it.status}</StatusBadge>
							</div>
							{#if it.description}<p class="text-xs text-gray-500 mb-1 line-clamp-2">{it.description}</p>{/if}
							{#if it.sedna_voucher || it.sedna_record_user}
								<p class="text-xs text-gray-500 mb-1.5">
									Sedna: {it.sedna_voucher || '—'}{#if it.sedna_record_user}&nbsp;· {it.sedna_record_user}{/if}
								</p>
							{/if}
							<div class="flex items-end justify-between gap-2">
								<div class="text-base font-bold tabular-nums {amountCls(it.amount)}">{fmtAmount(it.amount, it.currency)}</div>
								<div class="flex items-center gap-1.5 shrink-0">
									<button onclick={() => openDetail(it)} aria-label="Detay" class="p-2.5 text-gray-600 bg-gray-100 rounded-lg active:scale-95 cursor-pointer"><Eye size={16} /></button>
									{#if canUse}
										{#if !it.resolved_at}
											<button onclick={() => openResolve(it)} aria-label="Çözüldü olarak işaretle" class="p-2.5 text-emerald-700 bg-emerald-50 rounded-lg active:scale-95 cursor-pointer"><Check size={16} /></button>
											<button onclick={() => openIgnore(it)} aria-label="Yoksay" class="p-2.5 text-gray-600 bg-gray-100 rounded-lg active:scale-95 cursor-pointer"><Ban size={16} /></button>
										{:else}
											<button onclick={() => openReopen(it)} aria-label="Geri aç" class="p-2.5 text-amber-700 bg-amber-50 rounded-lg active:scale-95 cursor-pointer"><RotateCcw size={16} /></button>
										{/if}
									{/if}
								</div>
							</div>
						</div>
					{/each}
				</div>

				<!-- Sayfalama -->
				{#if total > pageSize || page > 1}
					<div class="px-4 border-t border-gray-100">
						<Pagination {page} {pageSize} {total} onPageChange={changePage} onPageSizeChange={changePageSize} />
					</div>
				{/if}
			{/if}
		</div>
	{:else}
		<!-- Hesap Eşleme sekmesi -->
		{#if mappingsLoading}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				<TableSkeleton rows={5} columns={4} />
			</div>
		{:else if !mappings}
			<div class="bg-amber-50 border border-amber-200 rounded-2xl p-6 sm:p-8 text-center">
				<div class="flex justify-center mb-3 text-amber-600"><Unplug size={40} /></div>
				<h3 class="text-base font-semibold text-amber-800 mb-1">Sedna bağlantısı yok</h3>
				<p class="text-sm text-amber-700 mb-1">Hesap eşleme önerileri canlı Sedna sorgusu gerektirir — tünel kapalı olabilir.</p>
				{#if mappingsError && mappingsError !== SEDNA_DOWN_MSG}
					<p class="text-xs text-amber-700 mb-4">{mappingsError}</p>
				{:else}
					<p class="text-xs text-amber-700 mb-4">Tünel açıldıktan sonra tekrar deneyin.</p>
				{/if}
				<Button variant="secondary" onclick={loadMappings}><RefreshCw size={15} /> Tekrar Dene</Button>
			</div>
		{:else}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				{#if mappings.accounts.length === 0}
					<EmptyState icon={Link2} title="Aktif banka hesabı yok" description="Eşlenecek aktif banka hesabı bulunamadı. Önce Bankalar modülünden hesap ekleyin." />
				{:else}
					<!-- Masaüstü tablo -->
					<div class="hidden md:block overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-gray-200 bg-gray-50 text-left">
									<th class="px-4 py-3 font-medium text-gray-600">Bizim Hesap</th>
									<th class="px-4 py-3 font-medium text-gray-600">Sedna Kodu</th>
									<th class="px-4 py-3 font-medium text-gray-600">Öneri</th>
									{#if canUse}<th class="px-4 py-3 font-medium text-gray-600 text-right">İşlemler</th>{/if}
								</tr>
							</thead>
							<tbody>
								{#each mappings.accounts as acc (acc.account_id)}
									<tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors align-top">
										<td class="px-4 py-3">
											<div class="font-medium text-gray-900">{acc.bank_name}</div>
											<div class="text-xs text-gray-500 mt-0.5 tabular-nums">{ibanTail(acc.iban)} · {acc.currency || '—'}</div>
										</td>
										<td class="px-4 py-3">
											{#if acc.current_code}
												<div class="flex items-center gap-2 flex-wrap">
													<span class="font-mono tabular-nums text-gray-900">{acc.current_code}</span>
													<StatusBadge type={acc.confirmed ? 'success' : 'warning'}>{acc.confirmed ? 'Onaylı' : 'Onaysız'}</StatusBadge>
												</div>
											{:else}
												<StatusBadge type="neutral">Eşlenmedi</StatusBadge>
											{/if}
										</td>
										<td class="px-4 py-3">
											{#if acc.suggestion}
												<div class="flex items-center gap-1.5">
													<span class="font-mono tabular-nums text-teal-700 font-medium">{acc.suggestion.code}</span>
													<span class="text-xs text-gray-500 tabular-nums">%{acc.suggestion.score}</span>
												</div>
												<div class="text-xs text-gray-500 mt-0.5 truncate max-w-[220px]" title={acc.suggestion.remark}>{acc.suggestion.remark || '—'}</div>
												{#if acc.suggestion.reason}<div class="text-xs text-gray-500 mt-0.5">{acc.suggestion.reason}</div>{/if}
											{:else}
												<span class="text-gray-500">—</span>
											{/if}
										</td>
										{#if canUse}
											<td class="px-4 py-3">
												<div class="flex items-center justify-end gap-1.5 flex-wrap">
													{#if acc.suggestion}
														<Button size="sm" onclick={() => openAccept(acc)} loading={mapSaving[acc.account_id]}><Check size={14} /> Onayla</Button>
													{/if}
													<Input size="sm" fullWidth={false} class="w-36" bind:value={mapInputs[acc.account_id]} placeholder="102.xx.xx.xxxx" aria-label={`${acc.bank_name} için Sedna kodu`} />
													<Button size="sm" variant="secondary" onclick={() => saveManualMapping(acc)} loading={mapSaving[acc.account_id]}>Kaydet</Button>
													{#if acc.current_code}
														<Button size="sm" variant="ghost" onclick={() => openClear(acc)} title="Eşlemeyi temizle"><X size={14} /> Temizle</Button>
													{/if}
												</div>
											</td>
										{/if}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>

					<!-- Mobil kart görünümü -->
					<div class="md:hidden divide-y divide-gray-100">
						{#each mappings.accounts as acc (acc.account_id)}
							<div class="p-3 space-y-2">
								<div class="flex items-start justify-between gap-2">
									<div class="min-w-0 flex-1">
										<div class="font-medium text-gray-900 truncate">{acc.bank_name}</div>
										<div class="text-xs text-gray-500 mt-0.5 tabular-nums">{ibanTail(acc.iban)} · {acc.currency || '—'}</div>
									</div>
									{#if acc.current_code}
										<StatusBadge type={acc.confirmed ? 'success' : 'warning'}>{acc.confirmed ? 'Onaylı' : 'Onaysız'}</StatusBadge>
									{:else}
										<StatusBadge type="neutral">Eşlenmedi</StatusBadge>
									{/if}
								</div>
								{#if acc.current_code}
									<div class="text-sm font-mono tabular-nums text-gray-900">{acc.current_code}</div>
								{/if}
								{#if acc.suggestion}
									<div class="text-xs text-gray-600 bg-teal-50 border border-teal-100 rounded-lg p-2">
										Öneri: <span class="font-mono tabular-nums text-teal-700 font-medium">{acc.suggestion.code}</span>
										<span class="tabular-nums">(%{acc.suggestion.score})</span>
										{#if acc.suggestion.remark}<span class="block mt-0.5 text-gray-500">{acc.suggestion.remark}</span>{/if}
										{#if acc.suggestion.reason}<span class="block mt-0.5 text-gray-500">{acc.suggestion.reason}</span>{/if}
									</div>
								{/if}
								{#if canUse}
									<div class="flex items-center gap-1.5 flex-wrap">
										{#if acc.suggestion}
											<Button size="sm" onclick={() => openAccept(acc)} loading={mapSaving[acc.account_id]}><Check size={14} /> Onayla</Button>
										{/if}
										<Input size="sm" fullWidth={false} class="w-32 flex-1" bind:value={mapInputs[acc.account_id]} placeholder="102.xx.xx.xxxx" aria-label={`${acc.bank_name} için Sedna kodu`} />
										<Button size="sm" variant="secondary" onclick={() => saveManualMapping(acc)} loading={mapSaving[acc.account_id]}>Kaydet</Button>
										{#if acc.current_code}
											<Button size="sm" variant="ghost" onclick={() => openClear(acc)} title="Eşlemeyi temizle"><X size={14} /> Temizle</Button>
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Sedna tarafında eşlenmemiş hesaplar (bilgi amaçlı, açılır/kapanır) -->
			{#if mappings.unmatched_sedna.length > 0}
				<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
					<button
						onclick={() => (showUnmatched = !showUnmatched)}
						aria-expanded={showUnmatched}
						class="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50 transition-colors cursor-pointer"
					>
						<span>Sedna tarafında eşlenmemiş hesaplar <span class="font-normal text-gray-500">({mappings.unmatched_sedna.length})</span></span>
						<ChevronDown size={16} class="text-gray-500 transition-transform {showUnmatched ? 'rotate-180' : ''}" />
					</button>
					{#if showUnmatched}
						<div class="border-t border-gray-100">
							<p class="px-4 py-2 text-xs text-gray-500 bg-gray-50 border-b border-gray-100">Bilgi amaçlı — bu Sedna 102 hesapları hiçbir banka hesabıyla eşlenmemiş.</p>
							<div class="divide-y divide-gray-50">
								{#each mappings.unmatched_sedna as leaf (leaf.code)}
									<div class="px-4 py-2 flex items-center gap-3 text-sm">
										<span class="font-mono tabular-nums text-gray-700 shrink-0">{leaf.code}</span>
										<span class="text-gray-500 truncate flex-1" title={leaf.remark || ''}>{leaf.remark || '—'}</span>
										<span class="text-xs text-gray-500 shrink-0">{leaf.curr || ''}</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/if}
		{/if}
	{/if}
</div>

<!-- Detay Modalı -->
<Modal bind:show={showDetail} title="Uyuşmazlık Detayı">
	{#if detailItem}
		<div class="space-y-4">
			<div class="flex items-center justify-between gap-2 flex-wrap">
				<StatusBadge type={STATUS_BADGE[detailItem.status] ?? 'neutral'}>{STATUS_LABELS[detailItem.status] ?? detailItem.status}</StatusBadge>
				<span class="text-xs text-gray-500">Tespit: {fmtDateTime(detailItem.detected_at)}</span>
			</div>
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
				<div class="p-3 bg-gray-50 rounded-lg space-y-1.5">
					<h3 class="text-xs font-semibold text-gray-600 uppercase tracking-wider">Banka Kaydı</h3>
					<div class="text-sm text-gray-700"><span class="text-gray-500">Hesap:</span> {detailItem.account_name || '—'}</div>
					<div class="text-sm text-gray-700"><span class="text-gray-500">Tarih:</span> {fmtDate(detailItem.event_date)}</div>
					<div class="text-sm font-semibold tabular-nums {amountCls(detailItem.amount)}">{fmtAmount(detailItem.amount, detailItem.currency)}</div>
					<p class="text-sm text-gray-600 break-words">{detailItem.description || '—'}</p>
				</div>
				<div class="p-3 bg-gray-50 rounded-lg space-y-1.5">
					<h3 class="text-xs font-semibold text-gray-600 uppercase tracking-wider">Sedna Kaydı</h3>
					<div class="text-sm text-gray-700"><span class="text-gray-500">Fiş No:</span> {detailItem.sedna_voucher || '—'}</div>
					<p class="text-sm text-gray-600 break-words">{detailItem.sedna_description || '—'}</p>
					<div class="text-sm text-gray-700"><span class="text-gray-500">Kaydeden:</span> {detailItem.sedna_record_user || '—'}</div>
				</div>
			</div>
			{#if detailItem.resolved_at}
				<div class="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-sm">
					<div class="font-medium text-emerald-800">{RESOLUTION_LABELS[detailItem.resolution] ?? detailItem.resolution} · {fmtDateTime(detailItem.resolved_at)}</div>
					{#if detailItem.resolution_note}<p class="text-emerald-700 mt-1 break-words">{detailItem.resolution_note}</p>{/if}
				</div>
			{/if}
		</div>
	{/if}
</Modal>

<!-- Yoksay Modalı (opsiyonel not girişi) -->
<Modal bind:show={showIgnoreModal} title="Uyuşmazlığı Yoksay" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); submitIgnore(); }} class="space-y-4">
		{#if actionTarget}
			<div class="p-3 bg-gray-50 rounded-lg text-sm">
				<div class="font-medium text-gray-900">{fmtDate(actionTarget.event_date)} · <span class="tabular-nums {amountCls(actionTarget.amount)}">{fmtAmount(actionTarget.amount, actionTarget.currency)}</span></div>
				{#if actionTarget.description}<div class="text-gray-500 mt-1 line-clamp-2">{actionTarget.description}</div>{/if}
			</div>
		{/if}
		<p class="text-sm text-gray-500">Kayıt bilinçli fark olarak kapatılacak; sonraki taramalarda yeniden açılmaz. Geri Aç ile tekrar açabilirsiniz.</p>
		<Field label="Not (opsiyonel)" for="ignore_note">
			{#snippet children({ id })}
				<Textarea {id} bind:value={ignoreNote} rows={2} maxlength={500} placeholder="Yoksayma gerekçesi" />
			{/snippet}
		</Field>
		<div class="flex justify-end gap-2 pt-2">
			<Button variant="secondary" onclick={() => (showIgnoreModal = false)}>Vazgeç</Button>
			<Button type="submit" loading={actionSaving}><Ban size={16} /> Yoksay</Button>
		</div>
	</form>
</Modal>

<!-- Çözüldü Onayı -->
<ConfirmDialog
	bind:show={showResolveConfirm}
	title="Çözüldü Olarak İşaretle"
	message={actionTarget ? `${fmtDate(actionTarget.event_date)} tarihli ${fmtAmount(actionTarget.amount, actionTarget.currency)} tutarındaki kayıt çözüldü olarak kapatılacak. Devam edilsin mi?` : ''}
	confirmText="Çözüldü"
	cancelText="Vazgeç"
	onConfirm={confirmResolve}
/>

<!-- Geri Aç Onayı -->
<ConfirmDialog
	bind:show={showReopenConfirm}
	title="Kaydı Geri Aç"
	message={actionTarget ? `${fmtDate(actionTarget.event_date)} tarihli ${fmtAmount(actionTarget.amount, actionTarget.currency)} tutarındaki kapalı kayıt yeniden açılacak. Devam edilsin mi?` : ''}
	confirmText="Geri Aç"
	cancelText="Vazgeç"
	onConfirm={confirmReopen}
/>

<!-- Öneri Onayı -->
<ConfirmDialog
	bind:show={showAcceptConfirm}
	title="Öneriyi Onayla"
	message={acceptTarget?.suggestion ? `${acceptTarget.bank_name} hesabına Sedna ${acceptTarget.suggestion.code} kodu atanacak ve onaylanacak. Devam edilsin mi?` : ''}
	confirmText="Onayla"
	cancelText="Vazgeç"
	onConfirm={confirmAccept}
/>

<!-- Eşleme Temizleme Onayı -->
<ConfirmDialog
	bind:show={showClearConfirm}
	title="Eşlemeyi Temizle"
	message={clearTarget ? `${clearTarget.bank_name} hesabının Sedna kodu (${clearTarget.current_code}) kaldırılacak; hesap taramalara dahil edilmez. Devam edilsin mi?` : ''}
	confirmText="Temizle"
	cancelText="Vazgeç"
	danger
	onConfirm={confirmClear}
/>
