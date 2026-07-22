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
	import PdfPreviewModal from '$lib/components/PdfPreviewModal.svelte';
	import {
		AlertTriangle, Ban, Check, ChevronDown, CircleCheck, Coins, Eye, FileDown, Hourglass,
		Landmark, Link2, Lock, RefreshCw, RotateCcw, Scale, Search, ShieldAlert, Unplug, Users, X,
	} from 'lucide-svelte';

	// Sabitler
	const STATUS_LABELS: Record<string, string> = {
		[RECON_STATUS.MATCHED]: 'Mutabık',
		[RECON_STATUS.SEDNA_PENDING]: 'Sedna Bekliyor',
		[RECON_STATUS.SEDNA_MISSING]: "Sedna'da Eksik",
		[RECON_STATUS.SEDNA_EXTRA]: "Sedna'da Fazla",
		[RECON_STATUS.DIRECTION_FLIP]: 'Yön Ters',
		[RECON_STATUS.DUPLICATE_SUSPECT]: 'Mükerrer Şüphesi',
		[RECON_STATUS.SEDNA_DIFF]: 'Sedna Sapması',
		[RECON_STATUS.BALANCE_DIFF]: 'Bakiye Farkı',
	};
	const STATUS_BADGE: Record<string, BadgeType> = {
		[RECON_STATUS.MATCHED]: 'success',
		[RECON_STATUS.SEDNA_PENDING]: 'warning',
		[RECON_STATUS.SEDNA_MISSING]: 'error',
		[RECON_STATUS.SEDNA_EXTRA]: 'error',
		[RECON_STATUS.DIRECTION_FLIP]: 'error',
		[RECON_STATUS.DUPLICATE_SUSPECT]: 'error',
		[RECON_STATUS.SEDNA_DIFF]: 'error',
		[RECON_STATUS.BALANCE_DIFF]: 'error',
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
	const ENTITY_TYPE_OPTIONS: { value: string; label: string }[] = [
		{ value: '', label: 'Tüm Türler' },
		{ value: 'bank', label: 'Banka' },
		{ value: 'check', label: 'Çek' },
		{ value: 'vendor_tx', label: 'Cari' },
		{ value: 'vendor_balance', label: 'Cari Bakiye' },
	];
	const FX_STATUS_LABELS: Record<string, string> = {
		mutabik: 'Mutabık',
		sapma: 'Sapma',
		sedna_bekliyor: 'Sedna fişi bekleniyor',
		veri_eksik: 'Veri eksik',
	};
	const FX_STATUS_BADGE: Record<string, BadgeType> = {
		mutabik: 'success',
		sapma: 'error',
		sedna_bekliyor: 'warning',
		veri_eksik: 'neutral',
	};
	const FX_SOURCE_LABELS: Record<string, string> = {
		match: 'Eşleşme',
		revaluation: 'Değerleme',
	};
	const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	// Türetilmiş
	let canUse = $derived(hasPermission('accounting.mutabakat', 'use'));

	// Veri state — özet
	let summary = $state<any>(null);

	// Veri state — son taramanın bakiye-zinciri kırılmaları (yalnız POST /run yanıtında gelir)
	let chainBreaks = $state<any[]>([]);

	// Veri state — uyuşmazlık listesi
	let items = $state<any[]>([]);
	let itemsLoading = $state(true);
	let total = $state(0);
	let page = $state(1);
	let pageSize = $state(50);

	// Veri state — hesap eşleme (banka ↔ 102)
	let mappings = $state<{ accounts: any[]; unmatched_sedna: any[] } | null>(null);
	let mappingsLoading = $state(false);
	let mappingsError = $state('');
	let mapInputs = $state<Record<number, string>>({});
	let mapSaving = $state<Record<number, boolean>>({});

	// Veri state — kredi eşleme (krediler ↔ 300) — bağımsız yüklenir (banka 503 olsa da çalışır)
	let creditMaps = $state<{ products: any[]; unmatched_sedna: any[] } | null>(null);
	let creditLoading = $state(false);
	let creditError = $state('');
	let creditInputs = $state<Record<number, string>>({});
	let creditSaving = $state<Record<number, boolean>>({});

	// Veri state — acente avans eşleme (gruplar ↔ 340) — bağımsız yüklenir
	let agencyMaps = $state<{ groups: any[] } | null>(null);
	let agencyLoading = $state(false);
	let agencyError = $state('');
	let agencySelected = $state<Record<number, string[]>>({}); // grup → seçili öneri kodları (PB başına ayrı hesap)
	let agencySaving = $state<Record<number, boolean>>({});

	// Veri state — hesap filtresi seçenekleri (finance.banks izni varsa canlı liste)
	let bankAccounts = $state<{ id: number; name: string }[]>([]);

	// Veri state — kur değerlemesi (Değerleme sekmesi; varsayılan dönem = geçen ay)
	const _lastMonth = (() => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d; })();
	let fxYear = $state(_lastMonth.getFullYear());
	let fxMonth = $state(_lastMonth.getMonth() + 1);
	let fxData = $state<any>(null);
	let fxLoading = $state(false);
	let fxError = $state('');

	// Veri state — kur farkı kayıtları (Değerleme sekmesi alt bölümü)
	let fxDiffs = $state<any>(null);
	let fxDiffsLoading = $state(false);
	let fxDiffPage = $state(1);
	let fxDiffPageSize = $state(25);

	// UI state
	let activeTab = $state('items');
	let scanning = $state(false);
	let pdfModal: PdfPreviewModal | undefined = $state();
	let pdfLoading = $state(false);
	let showUnmatched = $state(false);
	let showCreditUnmatched = $state(false);
	let lastLoadAt = 0; // WS yankı guard'ı (CashFlowTAccount deseni)

	// Filtre state
	let statusFilter = $state('');
	let accountFilter = $state('');
	let entityFilter = $state(''); // '' | 'bank' | 'check' | 'vendor_tx'
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

	// Kredi/acente eşleme aksiyon state
	let creditAcceptTarget = $state<any>(null);
	let showCreditAcceptConfirm = $state(false);
	let creditClearTarget = $state<any>(null);
	let showCreditClearConfirm = $state(false);
	let agencyClearTarget = $state<any>(null);
	let showAgencyClearConfirm = $state(false);

	// Dönem kilidi state
	let showLockModal = $state(false);
	let lockDateInput = $state('');
	let lockSaving = $state(false);
	let showLockRemoveConfirm = $state(false);

	// Türetilmiş — özet kartları + sekmeler + hesap seçenekleri
	let criticalCount = $derived.by(() => {
		const s = summary?.open_by_status || {};
		return (s[RECON_STATUS.SEDNA_MISSING] || 0) + (s[RECON_STATUS.SEDNA_EXTRA] || 0)
			+ (s[RECON_STATUS.DIRECTION_FLIP] || 0) + (s[RECON_STATUS.DUPLICATE_SUSPECT] || 0);
	});
	let tabOptions = $derived([
		{ value: 'items', label: 'Uyuşmazlıklar', count: summary?.open_total },
		{ value: 'mappings', label: 'Hesap Eşleme' },
		{ value: 'fx', label: 'Değerleme' },
	]);
	let fxYearOptions = $derived.by(() => {
		const current = new Date().getFullYear();
		const years: number[] = [];
		for (let y = current; y >= current - 4; y--) years.push(y);
		return years;
	});
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
	let hasFilters = $derived(Boolean(statusFilter || accountFilter || entityFilter || search || includeClosed));

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
	function fmtNum(n: number | null | undefined, digits = 2): string {
		if (n == null) return '—';
		return n.toLocaleString('tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
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
			if (entityFilter) params.set('entity_type', entityFilter);
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

	async function loadCreditMappings() {
		creditLoading = true;
		creditError = '';
		try {
			const data = await api.get<any>('/accounting/mutabakat/credit-mappings');
			creditMaps = data;
			const inputs: Record<number, string> = {};
			for (const p of data.products) inputs[p.product_id] = p.current_code || '';
			creditInputs = inputs;
		} catch (err: any) {
			console.error('Kredi eşleme verisi yüklenemedi:', err);
			creditMaps = null;
			creditError = err?.message && err.message !== 'Bir hata oluştu' ? err.message : SEDNA_DOWN_MSG;
		} finally {
			creditLoading = false;
		}
	}

	async function loadAgencyMappings() {
		agencyLoading = true;
		agencyError = '';
		try {
			const data = await api.get<any>('/accounting/mutabakat/agency-mappings');
			agencyMaps = data;
			const sel: Record<number, string[]> = {};
			for (const g of data.groups) sel[g.group_id] = [];
			agencySelected = sel;
		} catch (err: any) {
			console.error('Acente eşleme verisi yüklenemedi:', err);
			agencyMaps = null;
			agencyError = err?.message && err.message !== 'Bir hata oluştu' ? err.message : SEDNA_DOWN_MSG;
		} finally {
			agencyLoading = false;
		}
	}

	function loadAllMappings() {
		// Üç bölüm bağımsız yüklenir — biri 503 dönerse diğerleri çalışmaya devam eder
		loadMappings();
		loadCreditMappings();
		loadAgencyMappings();
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

	async function loadFxRevaluation() {
		fxLoading = true;
		fxError = '';
		try {
			fxData = await api.get<any>(`/accounting/mutabakat/fx-revaluation?year=${fxYear}&month=${fxMonth}`);
		} catch (err: any) {
			console.error('Kur değerlemesi yüklenemedi:', err);
			fxData = null;
			fxError = err?.message && err.message !== 'Bir hata oluştu' ? err.message : SEDNA_DOWN_MSG;
		} finally {
			fxLoading = false;
		}
	}

	async function loadFxDiffs() {
		fxDiffsLoading = true;
		try {
			fxDiffs = await api.get<any>(`/accounting/mutabakat/fx-differences?page=${fxDiffPage}&page_size=${fxDiffPageSize}`);
		} catch (err) {
			console.error('Kur farkı kayıtları yüklenemedi:', err);
			showToast('Kur farkı kayıtları yüklenemedi', 'error');
		} finally {
			fxDiffsLoading = false;
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
				let msg = `${r.accounts_scanned} hesap tarandı · ${r['new']} yeni uyuşmazlık · ${r.auto_closed} otomatik kapandı`;
				if (r.balance_diffs != null) msg += ` · ${r.balance_diffs} cari bakiye farkı`;
				showToast(msg, 'success');
			}
			if (r?.vendor_error) showToast(r.vendor_error, 'warning');
			if (Array.isArray(r?.negative_balances) && r.negative_balances.length > 0) {
				const parts = r.negative_balances.slice(0, 3).map((n: any) => `${n.bank_name} ${fmtAmount(n.balance, n.currency)}`);
				showToast(`Ters bakiye: ${parts.join(' · ')}`, 'warning');
			}
			// Faz 3 #22a: bakiye-zinciri kırılmaları — kopyada eksik/atlanmış ekstre satırı sinyali
			chainBreaks = Array.isArray(r?.balance_chain_breaks) ? r.balance_chain_breaks : [];
			if (chainBreaks.length > 0) {
				const parts = chainBreaks.slice(0, 2).map((b: any) => `${b.bank_name} ${fmtDate(b.date)} boşluk ${fmtAmount(b.gap, b.currency)}`);
				showToast(`Bakiye zinciri kırık: ${parts.join(' · ')}`, 'warning', 6000);
			}
			await Promise.all([loadSummary(), loadItems()]);
		} catch (err: any) {
			console.error('Mutabakat taraması başarısız:', err);
			showToast(err?.message && err.message !== 'Bir hata oluştu' ? err.message : SEDNA_DOWN_MSG, 'error');
		} finally {
			scanning = false;
		}
	}

	// PDF raporu — ekrandaki filtrelerle aynı kayıt kümesi (GET /items/pdf)
	async function downloadItemsPdf() {
		if (pdfLoading) return;
		pdfLoading = true;
		try {
			const params = new URLSearchParams();
			if (statusFilter) params.set('status', statusFilter);
			if (accountFilter) params.set('account_id', accountFilter);
			if (entityFilter) params.set('entity_type', entityFilter);
			if (includeClosed) params.set('include_closed', 'true');
			if (search.trim()) params.set('q', search.trim());
			const qs = params.toString();

			const res = await api.fetchRaw(`/accounting/mutabakat/items/pdf${qs ? '?' + qs : ''}`);
			if (!res.ok) throw new Error('İndirme başarısız');
			const blob = await res.blob();
			// iOS Safari blob'u doğrudan indiremiyor (WebKitBlobResource hatası 1) →
			// paylaşılan önizleme modalında göster (Yazdır/İndir oradan)
			pdfModal?.open(blob, `sedna-mutabakat-uyusmazliklar-${new Date().toISOString().slice(0, 10)}.pdf`);
		} catch (err) {
			console.error('Mutabakat PDF raporu indirilemedi:', err);
			showToast('PDF raporu indirilemedi', 'error');
		} finally {
			pdfLoading = false;
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

	// Kredi eşleme aksiyonları (banka bölümündeki desenle aynı)
	async function saveCreditMapping(productId: number, code: string | null, successMsg: string) {
		creditSaving[productId] = true;
		try {
			const resp = await api.patch<any>(`/accounting/mutabakat/credit-mappings/${productId}`, {
				sedna_account_code: code,
			});
			if (resp?.requires_approval || resp?.request_id) {
				showToast('İşlem onaya gönderildi', 'info');
				return;
			}
			showToast(successMsg, 'success');
			await loadCreditMappings();
		} catch (err: any) {
			console.error('Kredi eşleme kaydedilemedi:', err);
			showToast(err?.message || 'Kredi eşleme kaydedilemedi', 'error');
		} finally {
			creditSaving[productId] = false;
		}
	}

	function openCreditAccept(prod: any) { creditAcceptTarget = prod; showCreditAcceptConfirm = true; }
	function openCreditClear(prod: any) { creditClearTarget = prod; showCreditClearConfirm = true; }
	async function confirmCreditAccept() {
		if (creditAcceptTarget?.suggestion) {
			await saveCreditMapping(creditAcceptTarget.product_id, creditAcceptTarget.suggestion.code, 'Öneri onaylandı — kredi eşlendi');
		}
	}
	async function confirmCreditClear() {
		if (creditClearTarget) await saveCreditMapping(creditClearTarget.product_id, null, 'Eşleme temizlendi');
	}
	async function saveCreditManual(prod: any) {
		const code = (creditInputs[prod.product_id] || '').trim();
		await saveCreditMapping(prod.product_id, code || null, code ? 'Sedna kodu kaydedildi' : 'Eşleme temizlendi');
	}

	// Acente avans eşleme aksiyonları (öneri çipleri çoklu seçilebilir — PB başına ayrı hesap)
	function toggleAgencyCode(groupId: number, code: string) {
		const cur = agencySelected[groupId] || [];
		agencySelected[groupId] = cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code];
	}
	async function saveAgencyMapping(groupId: number, codes: string[] | null, successMsg: string) {
		agencySaving[groupId] = true;
		try {
			const resp = await api.patch<any>(`/accounting/mutabakat/agency-mappings/${groupId}`, {
				sedna_account_codes: codes,
			});
			if (resp?.requires_approval || resp?.request_id) {
				showToast('İşlem onaya gönderildi', 'info');
				return;
			}
			showToast(successMsg, 'success');
			await loadAgencyMappings();
		} catch (err: any) {
			console.error('Acente eşleme kaydedilemedi:', err);
			showToast(err?.message || 'Acente eşleme kaydedilemedi', 'error');
		} finally {
			agencySaving[groupId] = false;
		}
	}
	async function saveAgencySelection(g: any) {
		const codes = agencySelected[g.group_id] || [];
		if (codes.length === 0) return;
		await saveAgencyMapping(g.group_id, codes, `${codes.length} hesap eşlendi`);
	}
	function openAgencyClear(g: any) { agencyClearTarget = g; showAgencyClearConfirm = true; }
	async function confirmAgencyClear() {
		if (agencyClearTarget) await saveAgencyMapping(agencyClearTarget.group_id, null, 'Eşleme temizlendi');
	}

	// Dönem kilidi aksiyonları (uyarı modu — senkronu durdurmaz)
	function openLockModal() {
		lockDateInput = summary?.lock_date || '';
		showLockModal = true;
	}
	async function saveLockDate(value: string | null) {
		lockSaving = true;
		try {
			const resp = await api.patch<any>('/accounting/mutabakat/period-lock', { lock_date: value });
			if (resp?.requires_approval || resp?.request_id) {
				showToast('İşlem onaya gönderildi', 'info');
				showLockModal = false;
				return;
			}
			showToast(value ? `Dönem kilidi ${fmtDate(resp?.lock_date ?? value)} olarak ayarlandı` : 'Dönem kilidi kaldırıldı', 'success');
			showLockModal = false;
			await loadSummary();
		} catch (err: any) {
			console.error('Dönem kilidi kaydedilemedi:', err);
			showToast(err?.message || 'Dönem kilidi kaydedilemedi', 'error');
		} finally {
			lockSaving = false;
		}
	}
	async function submitLock() {
		if (!lockDateInput) return;
		await saveLockDate(lockDateInput);
	}
	async function confirmLockRemove() { await saveLockDate(null); }

	// UI yardımcıları
	function setTab(v: string) {
		activeTab = v;
		if (v === 'mappings') {
			// Her bölüm kendi endpoint'inden bağımsız yüklenir (biri 503 ise diğerleri çalışır)
			if (!mappings && !mappingsLoading) loadMappings();
			if (!creditMaps && !creditLoading) loadCreditMappings();
			if (!agencyMaps && !agencyLoading) loadAgencyMappings();
		}
		if (v === 'fx') {
			if (!fxData && !fxLoading && !fxError) loadFxRevaluation();
			if (!fxDiffs && !fxDiffsLoading) loadFxDiffs();
		}
	}
	function changePage(p: number) { page = p; loadItems(); }
	function changePageSize(s: number) { pageSize = s; page = 1; loadItems(); }
	function changeFxDiffPage(p: number) { fxDiffPage = p; loadFxDiffs(); }
	function changeFxDiffPageSize(s: number) { fxDiffPageSize = s; fxDiffPage = 1; loadFxDiffs(); }

	// Arama debounce (300ms): searchInput → search
	let searchTimer: ReturnType<typeof setTimeout>;
	$effect(() => {
		const v = searchInput;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { search = v.trim(); }, 300);
		return () => clearTimeout(searchTimer);
	});

	// Filtre değişiminde sayfayı 1'e al ve yeniden yükle (ilk yüklemede tetiklenmez)
	let filterKey = $derived(`${statusFilter}|${accountFilter}|${entityFilter}|${includeClosed}|${search}`);
	let prevFilterKey = '';
	$effect(() => {
		const fk = filterKey;
		if (prevFilterKey && fk !== prevFilterKey) { page = 1; loadItems(); }
		prevFilterKey = fk;
	});

	// Değerleme dönemi (yıl/ay) değişince yeniden yükle — yükle butonu yok (ilk yüklemede tetiklenmez)
	let fxPeriodKey = $derived(`${fxYear}-${fxMonth}`);
	let prevFxPeriodKey = '';
	$effect(() => {
		const fk = fxPeriodKey;
		if (prevFxPeriodKey && fk !== prevFxPeriodKey) loadFxRevaluation();
		prevFxPeriodKey = fk;
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
			if (activeTab === 'mappings') loadAllMappings();
			if (activeTab === 'fx') loadFxDiffs(); // değerleme canlı Sedna sorgusu — WS'te tetiklenmez, yalnız kur farkı listesi tazelenir
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

		<!-- Dönem kilidi şeridi (uyarı modu) -->
		<div class="flex items-center gap-2 flex-wrap">
			{#if chainBreaks.length > 0}
				<span
					class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-50 border border-red-200 text-red-700 text-xs font-semibold tabular-nums"
					title="Son taramada {chainBreaks.length} bakiye zinciri kırılması bulundu — ardışık ekstre satırları arasında bakiye boşluğu var; eksik/atlanmış ekstre satırı olabilir"
				>
					<AlertTriangle size={12} /> {chainBreaks.length} bakiye zinciri kırığı
				</span>
			{/if}
			{#if summary.lock_date}
				<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-800 text-xs font-semibold">
					<Lock size={12} /> Dönem kilidi: {fmtDate(summary.lock_date)}
				</span>
				{#if canUse}
					<Button size="sm" variant="ghost" onclick={openLockModal}>Düzenle</Button>
				{/if}
			{:else}
				<span class="inline-flex items-center gap-1.5 text-sm text-gray-500">
					<Lock size={14} /> Dönem kilidi yok
				</span>
				{#if canUse}
					<Button size="sm" variant="secondary" onclick={openLockModal}><Lock size={14} /> Kilitle</Button>
				{/if}
			{/if}
			<span class="text-xs text-gray-500">Uyarı modu — senkronu durdurmaz; kilit öncesi döneme ait yeni uyuşmazlıkta bildirim gönderilir.</span>
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
			<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={entityFilter} aria-label="Kayıt türüne göre filtrele">
				{#each ENTITY_TYPE_OPTIONS as opt (opt.value)}
					<option value={opt.value}>{opt.label}</option>
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
			<div class="flex items-center gap-2 sm:ml-auto">
				<span class="text-sm text-gray-500">{total} kayıt</span>
				<Button size="sm" variant="secondary" onclick={downloadItemsPdf} loading={pdfLoading} disabled={itemsLoading || total === 0} title="Listeyi PDF olarak yazdır/indir">
					<FileDown size={14} /> PDF
				</Button>
			</div>
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
	{:else if activeTab === 'mappings'}
		<!-- Hesap Eşleme sekmesi — üç bağımsız bölüm: banka (102) · kredi (300) · acente avans (340) -->
		<h2 class="flex items-center gap-2 text-sm font-semibold text-gray-700"><Landmark size={16} class="text-gray-500" /> Banka Hesapları ↔ Sedna (102)</h2>
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

		<!-- Krediler ↔ Sedna (300) -->
		<h2 class="flex items-center gap-2 text-sm font-semibold text-gray-700 pt-2"><Coins size={16} class="text-gray-500" /> Krediler ↔ Sedna (300)</h2>
		{#if creditLoading}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				<TableSkeleton rows={4} columns={5} />
			</div>
		{:else if !creditMaps}
			<div class="bg-amber-50 border border-amber-200 rounded-2xl p-6 sm:p-8 text-center">
				<div class="flex justify-center mb-3 text-amber-600"><Unplug size={40} /></div>
				<h3 class="text-base font-semibold text-amber-800 mb-1">Sedna bağlantısı yok</h3>
				<p class="text-sm text-amber-700 mb-1">Kredi eşleme önerileri canlı Sedna sorgusu gerektirir — tünel kapalı olabilir.</p>
				{#if creditError && creditError !== SEDNA_DOWN_MSG}
					<p class="text-xs text-amber-700 mb-4">{creditError}</p>
				{:else}
					<p class="text-xs text-amber-700 mb-4">Tünel açıldıktan sonra tekrar deneyin.</p>
				{/if}
				<Button variant="secondary" onclick={loadCreditMappings}><RefreshCw size={15} /> Tekrar Dene</Button>
			</div>
		{:else}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				{#if creditMaps.products.length === 0}
					<EmptyState icon={Coins} title="Aktif kredi ürünü yok" description="Eşlenecek aktif kredi ürünü bulunamadı. Önce Krediler modülünden ürün ekleyin." />
				{:else}
					<!-- Masaüstü tablo -->
					<div class="hidden md:block overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-gray-200 bg-gray-50 text-left">
									<th class="px-4 py-3 font-medium text-gray-600">Kredi</th>
									<th class="px-4 py-3 font-medium text-gray-600">PB</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-right">Tutar</th>
									<th class="px-4 py-3 font-medium text-gray-600">Sedna Kodu</th>
									<th class="px-4 py-3 font-medium text-gray-600">Öneri</th>
									{#if canUse}<th class="px-4 py-3 font-medium text-gray-600 text-right">İşlemler</th>{/if}
								</tr>
							</thead>
							<tbody>
								{#each creditMaps.products as prod (prod.product_id)}
									<tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors align-top">
										<td class="px-4 py-3">
											<div class="font-medium text-gray-900 truncate max-w-[200px]" title={prod.name}>{prod.name}</div>
											<div class="text-xs text-gray-500 mt-0.5">{prod.bank_name || '—'}{#if prod.type}&nbsp;· {prod.type.toUpperCase()}{/if}</div>
										</td>
										<td class="px-4 py-3 text-gray-700">{prod.currency || '—'}</td>
										<td class="px-4 py-3 text-right tabular-nums text-gray-900 whitespace-nowrap">{fmtNum(prod.total_amount)}</td>
										<td class="px-4 py-3">
											{#if prod.current_code}
												<div class="flex items-center gap-2 flex-wrap">
													<span class="font-mono tabular-nums text-gray-900">{prod.current_code}</span>
													<StatusBadge type="success">Eşlendi</StatusBadge>
												</div>
											{:else}
												<StatusBadge type="neutral">Eşlenmedi</StatusBadge>
											{/if}
										</td>
										<td class="px-4 py-3">
											{#if prod.suggestion}
												<div class="flex items-center gap-1.5">
													<span class="font-mono tabular-nums text-teal-700 font-medium">{prod.suggestion.code}</span>
													<span class="text-xs text-gray-500 tabular-nums">%{prod.suggestion.score}</span>
												</div>
												<div class="text-xs text-gray-500 mt-0.5 truncate max-w-[220px]" title={prod.suggestion.remark}>{prod.suggestion.remark || '—'}</div>
												{#if prod.suggestion.reason}<div class="text-xs text-gray-500 mt-0.5">{prod.suggestion.reason}</div>{/if}
											{:else}
												<span class="text-gray-500">—</span>
											{/if}
										</td>
										{#if canUse}
											<td class="px-4 py-3">
												<div class="flex items-center justify-end gap-1.5 flex-wrap">
													{#if prod.suggestion}
														<Button size="sm" onclick={() => openCreditAccept(prod)} loading={creditSaving[prod.product_id]}><Check size={14} /> Onayla</Button>
													{/if}
													<Input size="sm" fullWidth={false} class="w-36" bind:value={creditInputs[prod.product_id]} placeholder="300.xx.xx.xxxx" aria-label={`${prod.name} için Sedna kodu`} />
													<Button size="sm" variant="secondary" onclick={() => saveCreditManual(prod)} loading={creditSaving[prod.product_id]}>Kaydet</Button>
													{#if prod.current_code}
														<Button size="sm" variant="ghost" onclick={() => openCreditClear(prod)} title="Eşlemeyi temizle"><X size={14} /> Temizle</Button>
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
						{#each creditMaps.products as prod (prod.product_id)}
							<div class="p-3 space-y-2">
								<div class="flex items-start justify-between gap-2">
									<div class="min-w-0 flex-1">
										<div class="font-medium text-gray-900 truncate">{prod.name}</div>
										<div class="text-xs text-gray-500 mt-0.5">{prod.bank_name || '—'} · {prod.currency || '—'} · <span class="tabular-nums">{fmtNum(prod.total_amount)}</span></div>
									</div>
									{#if prod.current_code}
										<StatusBadge type="success">Eşlendi</StatusBadge>
									{:else}
										<StatusBadge type="neutral">Eşlenmedi</StatusBadge>
									{/if}
								</div>
								{#if prod.current_code}
									<div class="text-sm font-mono tabular-nums text-gray-900">{prod.current_code}</div>
								{/if}
								{#if prod.suggestion}
									<div class="text-xs text-gray-600 bg-teal-50 border border-teal-100 rounded-lg p-2">
										Öneri: <span class="font-mono tabular-nums text-teal-700 font-medium">{prod.suggestion.code}</span>
										<span class="tabular-nums">(%{prod.suggestion.score})</span>
										{#if prod.suggestion.remark}<span class="block mt-0.5 text-gray-500">{prod.suggestion.remark}</span>{/if}
										{#if prod.suggestion.reason}<span class="block mt-0.5 text-gray-500">{prod.suggestion.reason}</span>{/if}
									</div>
								{/if}
								{#if canUse}
									<div class="flex items-center gap-1.5 flex-wrap">
										{#if prod.suggestion}
											<Button size="sm" onclick={() => openCreditAccept(prod)} loading={creditSaving[prod.product_id]}><Check size={14} /> Onayla</Button>
										{/if}
										<Input size="sm" fullWidth={false} class="w-32 flex-1" bind:value={creditInputs[prod.product_id]} placeholder="300.xx.xx.xxxx" aria-label={`${prod.name} için Sedna kodu`} />
										<Button size="sm" variant="secondary" onclick={() => saveCreditManual(prod)} loading={creditSaving[prod.product_id]}>Kaydet</Button>
										{#if prod.current_code}
											<Button size="sm" variant="ghost" onclick={() => openCreditClear(prod)} title="Eşlemeyi temizle"><X size={14} /> Temizle</Button>
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Sedna tarafında eşlenmemiş 300 hesapları (bilgi amaçlı, açılır/kapanır) -->
			{#if creditMaps.unmatched_sedna.length > 0}
				<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
					<button
						onclick={() => (showCreditUnmatched = !showCreditUnmatched)}
						aria-expanded={showCreditUnmatched}
						class="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50 transition-colors cursor-pointer"
					>
						<span>Sedna tarafında eşlenmemiş kredi hesapları <span class="font-normal text-gray-500">({creditMaps.unmatched_sedna.length})</span></span>
						<ChevronDown size={16} class="text-gray-500 transition-transform {showCreditUnmatched ? 'rotate-180' : ''}" />
					</button>
					{#if showCreditUnmatched}
						<div class="border-t border-gray-100">
							<p class="px-4 py-2 text-xs text-gray-500 bg-gray-50 border-b border-gray-100">Bilgi amaçlı — bu Sedna 300 hesapları hiçbir kredi ürünüyle eşlenmemiş.</p>
							<div class="divide-y divide-gray-50">
								{#each creditMaps.unmatched_sedna as leaf (leaf.code)}
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

		<!-- Acente Avans Hesapları ↔ Sedna (340) -->
		<h2 class="flex items-center gap-2 text-sm font-semibold text-gray-700 pt-2"><Users size={16} class="text-gray-500" /> Acente Avans Hesapları ↔ Sedna (340)</h2>
		{#if agencyLoading}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				<TableSkeleton rows={4} columns={4} />
			</div>
		{:else if !agencyMaps}
			<div class="bg-amber-50 border border-amber-200 rounded-2xl p-6 sm:p-8 text-center">
				<div class="flex justify-center mb-3 text-amber-600"><Unplug size={40} /></div>
				<h3 class="text-base font-semibold text-amber-800 mb-1">Sedna bağlantısı yok</h3>
				<p class="text-sm text-amber-700 mb-1">Acente avans hesabı önerileri canlı Sedna sorgusu gerektirir — tünel kapalı olabilir.</p>
				{#if agencyError && agencyError !== SEDNA_DOWN_MSG}
					<p class="text-xs text-amber-700 mb-4">{agencyError}</p>
				{:else}
					<p class="text-xs text-amber-700 mb-4">Tünel açıldıktan sonra tekrar deneyin.</p>
				{/if}
				<Button variant="secondary" onclick={loadAgencyMappings}><RefreshCw size={15} /> Tekrar Dene</Button>
			</div>
		{:else}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				{#if agencyMaps.groups.length === 0}
					<EmptyState icon={Users} title="Acente grubu yok" description="Eşlenecek acente grubu bulunamadı. Önce Satış modülünden acente grubu tanımlayın." />
				{:else}
					<!-- Masaüstü tablo -->
					<div class="hidden md:block overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-gray-200 bg-gray-50 text-left">
									<th class="px-4 py-3 font-medium text-gray-600">Grup</th>
									<th class="px-4 py-3 font-medium text-gray-600">Mevcut Kodlar</th>
									<th class="px-4 py-3 font-medium text-gray-600">Öneriler</th>
									{#if canUse}<th class="px-4 py-3 font-medium text-gray-600 text-right">İşlemler</th>{/if}
								</tr>
							</thead>
							<tbody>
								{#each agencyMaps.groups as g (g.group_id)}
									<tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors align-top">
										<td class="px-4 py-3">
											<div class="font-medium text-gray-900 truncate max-w-[180px]" title={g.name}>{g.name}</div>
										</td>
										<td class="px-4 py-3">
											{#if (g.current_codes || []).length > 0}
												<div class="flex items-center gap-1.5 flex-wrap">
													{#each g.current_codes as c (c)}
														<span class="inline-flex px-2 py-0.5 rounded-full bg-gray-100 text-gray-800 font-mono tabular-nums text-xs">{c}</span>
													{/each}
												</div>
											{:else}
												<StatusBadge type="neutral">Eşlenmedi</StatusBadge>
											{/if}
										</td>
										<td class="px-4 py-3">
											{#if (g.suggestions || []).length > 0}
												<div class="flex items-center gap-1.5 flex-wrap">
													{#each g.suggestions as s (s.code)}
														{@const sel = (agencySelected[g.group_id] || []).includes(s.code)}
														<button
															type="button"
															disabled={!canUse}
															onclick={() => toggleAgencyCode(g.group_id, s.code)}
															aria-pressed={sel}
															title={s.name}
															class="inline-flex items-center gap-1.5 px-2 py-1 rounded-full border text-xs transition-colors {sel ? 'bg-teal-700 border-teal-700 text-white' : 'bg-white border-gray-300 text-gray-700'} {canUse ? 'cursor-pointer hover:border-teal-700' : 'cursor-default'}"
														>
															<span class="font-mono tabular-nums">{s.code}</span>
															<span class="truncate max-w-[140px]">{s.name}</span>
															<span class={sel ? 'text-teal-100' : 'text-gray-500'}>{s.currency}</span>
														</button>
													{/each}
												</div>
												<p class="text-xs text-gray-500 mt-1">Birden fazla seçilebilir — para birimi başına ayrı hesap.</p>
											{:else}
												<span class="text-gray-500">—</span>
											{/if}
										</td>
										{#if canUse}
											<td class="px-4 py-3">
												<div class="flex items-center justify-end gap-1.5 flex-wrap">
													{#if (g.suggestions || []).length > 0}
														<Button size="sm" onclick={() => saveAgencySelection(g)} loading={agencySaving[g.group_id]} disabled={(agencySelected[g.group_id] || []).length === 0}><Check size={14} /> Kaydet</Button>
													{/if}
													{#if (g.current_codes || []).length > 0}
														<Button size="sm" variant="ghost" onclick={() => openAgencyClear(g)} title="Eşlemeyi temizle"><X size={14} /> Temizle</Button>
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
						{#each agencyMaps.groups as g (g.group_id)}
							<div class="p-3 space-y-2">
								<div class="flex items-start justify-between gap-2">
									<div class="font-medium text-gray-900 truncate min-w-0 flex-1">{g.name}</div>
									{#if (g.current_codes || []).length === 0}
										<StatusBadge type="neutral">Eşlenmedi</StatusBadge>
									{/if}
								</div>
								{#if (g.current_codes || []).length > 0}
									<div class="flex items-center gap-1.5 flex-wrap">
										{#each g.current_codes as c (c)}
											<span class="inline-flex px-2 py-0.5 rounded-full bg-gray-100 text-gray-800 font-mono tabular-nums text-xs">{c}</span>
										{/each}
									</div>
								{/if}
								{#if (g.suggestions || []).length > 0}
									<div class="flex items-center gap-1.5 flex-wrap">
										{#each g.suggestions as s (s.code)}
											{@const sel = (agencySelected[g.group_id] || []).includes(s.code)}
											<button
												type="button"
												disabled={!canUse}
												onclick={() => toggleAgencyCode(g.group_id, s.code)}
												aria-pressed={sel}
												title={s.name}
												class="inline-flex items-center gap-1.5 px-2 py-1 rounded-full border text-xs transition-colors {sel ? 'bg-teal-700 border-teal-700 text-white' : 'bg-white border-gray-300 text-gray-700'} {canUse ? 'cursor-pointer' : 'cursor-default'}"
											>
												<span class="font-mono tabular-nums">{s.code}</span>
												<span class="truncate max-w-[120px]">{s.name}</span>
												<span class={sel ? 'text-teal-100' : 'text-gray-500'}>{s.currency}</span>
											</button>
										{/each}
									</div>
									<p class="text-xs text-gray-500">Birden fazla seçilebilir — para birimi başına ayrı hesap.</p>
								{/if}
								{#if canUse && ((g.suggestions || []).length > 0 || (g.current_codes || []).length > 0)}
									<div class="flex items-center gap-1.5 flex-wrap">
										{#if (g.suggestions || []).length > 0}
											<Button size="sm" onclick={() => saveAgencySelection(g)} loading={agencySaving[g.group_id]} disabled={(agencySelected[g.group_id] || []).length === 0}><Check size={14} /> Kaydet</Button>
										{/if}
										{#if (g.current_codes || []).length > 0}
											<Button size="sm" variant="ghost" onclick={() => openAgencyClear(g)} title="Eşlemeyi temizle"><X size={14} /> Temizle</Button>
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	{:else}
		<!-- Değerleme sekmesi -->
		<div class="flex flex-col sm:flex-row gap-2 sm:gap-3 sm:items-center sm:flex-wrap">
			<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={fxMonth} aria-label="Değerleme ayı">
				{#each MONTH_NAMES as name, i (i)}
					<option value={i + 1}>{name}</option>
				{/each}
			</Select>
			<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={fxYear} aria-label="Değerleme yılı">
				{#each fxYearOptions as y (y)}
					<option value={y}>{y}</option>
				{/each}
			</Select>
			{#if fxData?.month_end}
				<span class="text-sm text-gray-500 sm:ml-auto">Ay sonu: {fmtDate(fxData.month_end)}</span>
			{/if}
		</div>
		<p class="text-xs text-gray-500">Formül: döviz bakiye × ay sonu TCMB alış − TL defter değeri (Sedna Type=4 fişiyle karşılaştırılır; deftere yazılmaz).</p>

		{#if fxLoading}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				<TableSkeleton rows={4} columns={9} />
			</div>
		{:else if fxError}
			<div class="bg-amber-50 border border-amber-200 rounded-2xl p-6 sm:p-8 text-center">
				<div class="flex justify-center mb-3 text-amber-600"><Unplug size={40} /></div>
				<h3 class="text-base font-semibold text-amber-800 mb-1">Sedna bağlantısı yok</h3>
				<p class="text-sm text-amber-700 mb-1">Kur değerlemesi canlı Sedna sorgusu gerektirir — tünel kapalı olabilir.</p>
				{#if fxError !== SEDNA_DOWN_MSG}
					<p class="text-xs text-amber-700 mb-4">{fxError}</p>
				{:else}
					<p class="text-xs text-amber-700 mb-4">Tünel açıldıktan sonra tekrar deneyin.</p>
				{/if}
				<Button variant="secondary" onclick={loadFxRevaluation}><RefreshCw size={15} /> Tekrar Dene</Button>
			</div>
		{:else if fxData}
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
				{#if fxData.items.length === 0}
					<EmptyState
						icon={Scale}
						title="Değerleme verisi yok"
						description={fxData.note || 'Bu dönem için eşlenmiş döviz hesabı bulunamadı. Önce Hesap Eşleme sekmesinden döviz hesaplarını eşleyin.'}
					/>
				{:else}
					<!-- Masaüstü tablo -->
					<div class="hidden md:block overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-gray-200 bg-gray-50 text-left">
									<th class="px-4 py-3 font-medium text-gray-600">Hesap</th>
									<th class="px-4 py-3 font-medium text-gray-600">PB</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-right">Döviz Bakiye (bizim)</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-right">Sedna Döviz</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-right">Kur (alış)</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-right">Beklenen TL</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-right">Sedna TL Defter</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-right">Sedna Değerleme Fişi</th>
									<th class="px-4 py-3 font-medium text-gray-600 text-center">Durum</th>
								</tr>
							</thead>
							<tbody>
								{#each fxData.items as it (it.account_id)}
									<tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors">
										<td class="px-4 py-3">
											<div class="font-medium text-gray-900 truncate max-w-[160px]" title={it.bank_name}>{it.bank_name}</div>
											<div class="text-xs text-gray-500 font-mono tabular-nums">{it.sedna_code || '—'}</div>
										</td>
										<td class="px-4 py-3 text-gray-700">{it.currency}</td>
										<td class="px-4 py-3 text-right tabular-nums text-gray-900">{fmtNum(it.our_fx_balance)}</td>
										<td class="px-4 py-3 text-right tabular-nums text-gray-700">{fmtNum(it.sedna_fx_balance)}</td>
										<td class="px-4 py-3 text-right tabular-nums text-gray-700">{fmtNum(it.rate, 4)}</td>
										<td class="px-4 py-3 text-right tabular-nums font-semibold text-gray-900">{fmtNum(it.expected_try)}</td>
										<td class="px-4 py-3 text-right tabular-nums text-gray-700">{fmtNum(it.sedna_tl_balance)}</td>
										<td class="px-4 py-3 text-right tabular-nums text-gray-700">{fmtNum(it.sedna_valuation_tl)}</td>
										<td class="px-4 py-3 text-center">
											<StatusBadge type={FX_STATUS_BADGE[it.status] ?? 'neutral'}>{FX_STATUS_LABELS[it.status] ?? it.status}</StatusBadge>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>

					<!-- Mobil kart görünümü -->
					<div class="md:hidden divide-y divide-gray-100">
						{#each fxData.items as it (it.account_id)}
							<div class="p-3 space-y-1.5">
								<div class="flex items-start justify-between gap-2">
									<div class="min-w-0 flex-1">
										<div class="font-medium text-gray-900 truncate">{it.bank_name} · {it.currency}</div>
										<div class="text-xs text-gray-500 font-mono tabular-nums mt-0.5">{it.sedna_code || '—'}</div>
									</div>
									<StatusBadge type={FX_STATUS_BADGE[it.status] ?? 'neutral'}>{FX_STATUS_LABELS[it.status] ?? it.status}</StatusBadge>
								</div>
								<div class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
									<div class="text-gray-500">Döviz Bakiye (bizim)</div><div class="text-right tabular-nums text-gray-900">{fmtNum(it.our_fx_balance)}</div>
									<div class="text-gray-500">Sedna Döviz</div><div class="text-right tabular-nums text-gray-700">{fmtNum(it.sedna_fx_balance)}</div>
									<div class="text-gray-500">Kur (alış)</div><div class="text-right tabular-nums text-gray-700">{fmtNum(it.rate, 4)}</div>
									<div class="text-gray-500">Beklenen TL</div><div class="text-right tabular-nums font-semibold text-gray-900">{fmtNum(it.expected_try)}</div>
									<div class="text-gray-500">Sedna TL Defter</div><div class="text-right tabular-nums text-gray-700">{fmtNum(it.sedna_tl_balance)}</div>
									<div class="text-gray-500">Sedna Değerleme Fişi</div><div class="text-right tabular-nums text-gray-700">{fmtNum(it.sedna_valuation_tl)}</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<!-- Kur Farkı Kayıtları -->
		<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
			<div class="flex items-center justify-between gap-2 flex-wrap px-4 py-3 border-b border-gray-100">
				<h2 class="text-sm font-semibold text-gray-700">Kur Farkı Kayıtları</h2>
				{#if fxDiffs && fxDiffs.total > 0}
					{@const net = fxDiffs.total_amount_try ?? 0}
					<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold tabular-nums {net >= 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}">
						{net >= 0 ? 'Net Kambiyo Karı' : 'Net Kambiyo Zararı'} · {fmtAmount(net, 'TRY')}
					</span>
				{/if}
			</div>
			{#if fxDiffsLoading && !fxDiffs}
				<TableSkeleton rows={3} columns={6} />
			{:else if !fxDiffs || fxDiffs.items.length === 0}
				<EmptyState
					icon={Coins}
					title="Henüz kur farkı kaydı yok"
					description="Çapraz-para eşleşmelerinde otomatik birikir."
				/>
			{:else}
				<!-- Masaüstü tablo -->
				<div class="hidden md:block overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-gray-200 bg-gray-50 text-left">
								<th class="px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Tarih</th>
								<th class="px-4 py-3 font-medium text-gray-600 text-right">Tutar TL</th>
								<th class="px-4 py-3 font-medium text-gray-600 text-right">Tahmin Kuru</th>
								<th class="px-4 py-3 font-medium text-gray-600 text-right">Gerçekleşen Kur</th>
								<th class="px-4 py-3 font-medium text-gray-600">Kaynak</th>
								<th class="px-4 py-3 font-medium text-gray-600">Açıklama</th>
							</tr>
						</thead>
						<tbody>
							{#each fxDiffs.items as r (r.id)}
								<tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors">
									<td class="px-4 py-3 text-gray-600 whitespace-nowrap">{fmtDate(r.period)}</td>
									<td class="px-4 py-3 text-right font-semibold tabular-nums whitespace-nowrap {amountCls(r.amount_try)}">{fmtAmount(r.amount_try, 'TRY')}</td>
									<td class="px-4 py-3 text-right tabular-nums text-gray-700">{fmtNum(r.rate_estimate, 4)}</td>
									<td class="px-4 py-3 text-right tabular-nums text-gray-700">{fmtNum(r.rate_realized, 4)}</td>
									<td class="px-4 py-3 text-gray-700">{FX_SOURCE_LABELS[r.source] ?? r.source ?? '—'}</td>
									<td class="px-4 py-3 text-gray-600">
										<div class="truncate max-w-[280px]" title={r.description || ''}>{r.description || '—'}</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- Mobil kart görünümü -->
				<div class="md:hidden divide-y divide-gray-100">
					{#each fxDiffs.items as r (r.id)}
						<div class="p-3">
							<div class="flex items-start justify-between gap-2 mb-1">
								<div class="min-w-0 flex-1">
									<div class="text-xs text-gray-500">{fmtDate(r.period)} · {FX_SOURCE_LABELS[r.source] ?? r.source ?? '—'}</div>
									{#if r.description}<p class="text-xs text-gray-500 mt-0.5 line-clamp-2">{r.description}</p>{/if}
								</div>
								<div class="text-sm font-bold tabular-nums shrink-0 {amountCls(r.amount_try)}">{fmtAmount(r.amount_try, 'TRY')}</div>
							</div>
							<div class="text-xs text-gray-500 tabular-nums">Tahmin: {fmtNum(r.rate_estimate, 4)} · Gerçekleşen: {fmtNum(r.rate_realized, 4)}</div>
						</div>
					{/each}
				</div>

				<!-- Sayfalama -->
				{#if fxDiffs.total > fxDiffPageSize || fxDiffPage > 1}
					<div class="px-4 border-t border-gray-100">
						<Pagination page={fxDiffPage} pageSize={fxDiffPageSize} total={fxDiffs.total} onPageChange={changeFxDiffPage} onPageSizeChange={changeFxDiffPageSize} />
					</div>
				{/if}
			{/if}
		</div>
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
					<h3 class="text-xs font-semibold text-gray-600 uppercase tracking-wider">{detailItem.entity_type ? 'Yerel Kayıt' : 'Banka Kaydı'}</h3>
					<div class="text-sm text-gray-700"><span class="text-gray-500">Hesap:</span> {detailItem.account_name || '—'}</div>
					<div class="text-sm text-gray-700"><span class="text-gray-500">Tarih:</span> {fmtDate(detailItem.event_date)}</div>
					<div class="text-sm font-semibold tabular-nums {amountCls(detailItem.amount)}">{fmtAmount(detailItem.amount, detailItem.currency)}</div>
					<p class="text-sm text-gray-600 break-words">{detailItem.description || '—'}</p>
				</div>
				<div class="p-3 bg-gray-50 rounded-lg space-y-1.5">
					<h3 class="text-xs font-semibold text-gray-600 uppercase tracking-wider">{detailItem.entity_type ? 'Sedna' : 'Sedna Kaydı'}</h3>
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

<!-- Kredi Öneri Onayı -->
<ConfirmDialog
	bind:show={showCreditAcceptConfirm}
	title="Öneriyi Onayla"
	message={creditAcceptTarget?.suggestion ? `${creditAcceptTarget.name} kredisine Sedna ${creditAcceptTarget.suggestion.code} kodu atanacak. Devam edilsin mi?` : ''}
	confirmText="Onayla"
	cancelText="Vazgeç"
	onConfirm={confirmCreditAccept}
/>

<!-- Kredi Eşleme Temizleme Onayı -->
<ConfirmDialog
	bind:show={showCreditClearConfirm}
	title="Eşlemeyi Temizle"
	message={creditClearTarget ? `${creditClearTarget.name} kredisinin Sedna kodu (${creditClearTarget.current_code}) kaldırılacak. Devam edilsin mi?` : ''}
	confirmText="Temizle"
	cancelText="Vazgeç"
	danger
	onConfirm={confirmCreditClear}
/>

<!-- Acente Eşleme Temizleme Onayı -->
<ConfirmDialog
	bind:show={showAgencyClearConfirm}
	title="Eşlemeyi Temizle"
	message={agencyClearTarget ? `${agencyClearTarget.name} grubunun Sedna avans hesabı eşlemesi (${(agencyClearTarget.current_codes || []).join(', ')}) kaldırılacak. Devam edilsin mi?` : ''}
	confirmText="Temizle"
	cancelText="Vazgeç"
	danger
	onConfirm={confirmAgencyClear}
/>

<!-- Dönem Kilidi Modalı -->
<Modal bind:show={showLockModal} title="Dönem Kilidi" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); submitLock(); }} class="space-y-4">
		<p class="text-sm text-gray-500">Uyarı modu — senkronu durdurmaz; kilit öncesi döneme ait yeni uyuşmazlıkta bildirim gönderilir.</p>
		<Field label="Kilit tarihi (bu tarih dahil öncesi kapalı dönem)" for="lock_date" required>
			{#snippet children({ id })}
				<Input {id} type="date" bind:value={lockDateInput} required />
			{/snippet}
		</Field>
		<div class="flex items-center justify-between gap-2 pt-2 flex-wrap">
			{#if summary?.lock_date}
				<Button variant="danger" onclick={() => (showLockRemoveConfirm = true)} loading={lockSaving}><X size={16} /> Kaldır</Button>
			{:else}
				<span></span>
			{/if}
			<div class="flex gap-2 ml-auto">
				<Button variant="secondary" onclick={() => (showLockModal = false)}>Vazgeç</Button>
				<Button type="submit" loading={lockSaving} disabled={!lockDateInput}><Lock size={16} /> Kaydet</Button>
			</div>
		</div>
	</form>
</Modal>

<!-- Dönem Kilidi Kaldırma Onayı -->
<ConfirmDialog
	bind:show={showLockRemoveConfirm}
	title="Dönem Kilidini Kaldır"
	message={summary?.lock_date ? `${fmtDate(summary.lock_date)} tarihli dönem kilidi kaldırılacak; kapalı dönem uyarıları devre dışı kalır. Devam edilsin mi?` : ''}
	confirmText="Kaldır"
	cancelText="Vazgeç"
	danger
	onConfirm={confirmLockRemove}
/>

<!-- PDF Önizleme (Yazdır/İndir) -->
<PdfPreviewModal bind:this={pdfModal} />
