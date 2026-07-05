<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import LoadingOverlay from '$lib/components/LoadingOverlay.svelte';
	import PdfPreviewModal from '$lib/components/PdfPreviewModal.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import {
		CreditCard, ChevronRight, ChevronLeft, FileDown, Plus, CheckCircle2, Info,
		RotateCcw, X, CornerDownLeft, Landmark, Pencil, Trash2, CalendarDays,
	} from 'lucide-svelte';
	import type { LatestRates } from '$lib/types/exchange-rate';

	// ─── Sabitler ───────────────────────────────────────────
	const TYPE_LABELS: Record<string, string> = {
		kredi_karti: 'Kredi Kartı', kmh: 'KMH', bch: 'BCH',
		spot_kredi: 'Spot Kredi', taksitli_kredi: 'Taksitli Kredi', leasing: 'Leasing',
	};
	const PRODUCT_TYPES = Object.keys(TYPE_LABELS);

	// Tip rozeti renkleri (tasarım paleti — AA için fg koyulaştırıldı)
	const TYPE_STYLE: Record<string, { fg: string; bg: string }> = {
		spot_kredi:     { fg: '#1b3a5c', bg: '#e6edf5' },
		taksitli_kredi: { fg: '#6d571b', bg: '#f4ecd4' },
		bch:            { fg: '#2f6b52', bg: '#e8f1ec' },
		leasing:        { fg: '#584a8c', bg: '#ece9f5' },
		kmh:            { fg: '#a85f1e', bg: '#f8ecdd' },
		kredi_karti:    { fg: '#3a5573', bg: '#e9eef4' },
	};
	function typeStyle(t: string) { return TYPE_STYLE[t] || TYPE_STYLE.spot_kredi; }

	// Para-birimi vurgu renkleri (tasarım paleti). TL = brass (#bd9a45, --color-brass token);
	// EUR = tasarıma özel mavi (#5b7fa6, token setinde YOK — lacivert temayla uyumlu "doğal hedge"
	// aksanı). Koşullu kullanıldığından utility yerine sabit hex — tip rozetleri gibi bilinçli istisna.
	const CUR_BAR = (isEur: boolean) => (isEur ? '#5b7fa6' : '#bd9a45');   // vurgu çubuğu / ilerleme / nokta
	const CUR_TEXT = (isEur: boolean) => (isEur ? '#3a5573' : '#6d571b');  // tutar metni (AA: açık zeminde ≥4.5:1)

	const AY_KISA = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const AY_UZUN = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	const VIEW_OPTIONS = [
		{ value: 'krediler', label: 'Krediler', icon: CreditCard },
		{ value: 'takvim', label: 'Taksit Takvimi', icon: CalendarDays },
		{ value: 'banka', label: 'Banka Dağılımı', icon: Landmark },
	];
	const TAB_OPTIONS = [
		{ value: 'plan', label: 'Ödeme Planı' },
		{ value: 'info', label: 'Bilgiler' },
	];

	let canUse = $derived(hasPermission('finance.krediler', 'use'));

	// ─── Türetilmiş: bugün ──────────────────────────────────
	const _now = new Date();
	const TODAY_ISO = _now.toISOString().split('T')[0];
	const TODAY_LABEL = `${String(_now.getDate()).padStart(2, '0')} ${AY_KISA[_now.getMonth()]} ${_now.getFullYear()}`;

	// ─── State: veri ────────────────────────────────────────
	let products = $state<any[]>([]);
	let upcoming = $state<any[]>([]);
	let latestRates = $state<LatestRates | null>(null);
	let loading = $state(true);

	// Görünüm + seçim
	let view = $state<'krediler' | 'takvim' | 'banka'>('krediler');
	let selectedId = $state<number | null>(null);
	let detailTab = $state<'plan' | 'info'>('plan');
	let mobileShowDetail = $state(false);

	// Seçili kredi detayı
	let selPayments = $state<any[]>([]);
	let selOpenMonths = $state<Set<string>>(new Set());
	let kmhStatus = $state<any>(null);

	// Kredi kartı ekstreleri
	let allCardStmts = $state<any[]>([]);       // liste göstergesi (tüm kartların ekstreleri)
	let ccStatements = $state<any[]>([]);        // seçili kartın ekstreleri
	let ccExpandedStmtId = $state<number | null>(null);
	let ccExpandedStmt = $state<any>(null);
	let ccUploading = $state(false);
	let ccUploadError = $state('');
	let ccUploadSuccess = $state('');

	// Taksit takvimi akordiyon
	let openCalMonths = $state<Set<string>>(new Set());
	let calInitialized = $state(false);  // ilk-açılış yalnız bir kez (kullanıcı tüm ayları kapatabilsin)

	// PDF
	let pdfLoading = $state(false);
	let pdfModal: PdfPreviewModal | undefined = $state();

	// Onay diyaloğu (silme = yıkıcı kırmızı; diğer onaylar confirmText/danger ile özelleştirilir)
	let confirmState = $state<{ show: boolean; title: string; message: string; confirmText: string; danger: boolean; onConfirm: () => void | Promise<void> }>({
		show: false, title: '', message: '', confirmText: 'Sil', danger: true, onConfirm: () => {},
	});
	function askConfirm(title: string, message: string, onConfirm: () => void | Promise<void>, opts?: { confirmText?: string; danger?: boolean }) {
		confirmState = { show: true, title, message, confirmText: opts?.confirmText ?? 'Sil', danger: opts?.danger ?? true, onConfirm };
	}
	function askDelete(title: string, message: string, onConfirm: () => void | Promise<void>) {
		askConfirm(title, message, onConfirm);
	}

	// Ürün ekle/düzenle modal
	let showAddModal = $state(false);
	let editProduct = $state<any>(null);
	let form = $state<{
		type: string; name: string; bank_name: string; company: string; currency: string;
		total_amount: number | null; remaining_amount: number | null; interest_rate: number | null;
		bsmv_rate: number | null; commission_rate: number | null;
		start_date: string; end_date: string; notes: string; details: Record<string, any>;
	}>({
		type: 'kredi_karti', name: '', bank_name: '', company: '', currency: 'TRY',
		total_amount: null, remaining_amount: null, interest_rate: null,
		bsmv_rate: null, commission_rate: null, start_date: '', end_date: '', notes: '', details: {},
	});

	// Taksit oluştur modal
	let showPaymentModal = $state(false);
	let paymentProductId = $state<number | null>(null);
	let paymentForm = $state<{ count: number; start_date: string; amount: number | null; principal: number | null; interest: number | null; tax: number | null }>({
		count: 12, start_date: '', amount: null, principal: null, interest: null, tax: null,
	});

	// Kapatma modal
	let closeModal = $state<{ show: boolean; id: number | null; name: string; closedDate: string }>({
		show: false, id: null, name: '', closedDate: TODAY_ISO,
	});

	// ─── Formatlama ─────────────────────────────────────────
	function fmt(n: number | null | undefined, currency = 'TRY'): string {
		if (n == null) return '—';
		const symbols: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$' };
		const sym = symbols[currency] || currency;
		return sym + n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}
	function fmtDate(d: string | null | undefined): string {
		if (!d) return '—';
		const [y, m, day] = d.split('-');
		return `${day}.${m}.${y}`;
	}
	function shortEur(v: number | null | undefined): string {
		if (v == null) return '—';
		const a = Math.abs(v);
		if (a >= 1_000_000) return '€' + (v / 1_000_000).toFixed(2).replace('.', ',') + 'M';
		if (a >= 1_000) return '€' + Math.round(v / 1_000) + 'K';
		return '€' + Math.round(v);
	}
	// Detay KPI değeri dar panelde tek satıra sığsın diye uzunluğa göre fontu küçültür (kırpma yerine).
	function kpiSize(v: string): string {
		const n = v.length;
		return n > 18 ? 'text-xs' : n > 15 ? 'text-sm' : n > 12 ? 'text-base' : 'text-lg';
	}

	// ─── Döviz ──────────────────────────────────────────────
	let eurRate = $derived(latestRates?.rates.find(r => r.currency_code === 'EUR')?.forex_selling ?? null);
	let usdRate = $derived(latestRates?.rates.find(r => r.currency_code === 'USD')?.forex_selling ?? null);
	let gbpRate = $derived(latestRates?.rates.find(r => r.currency_code === 'GBP')?.forex_selling ?? null);

	/** Kaynak para birimindeki tutarı EUR'a çevirir. Kur yoksa null. */
	function toEur(amount: number | null | undefined, currency: string): number | null {
		if (amount == null) return null;
		if (currency === 'EUR') return amount;
		if (!eurRate) return null;
		if (currency === 'TRY') return amount / eurRate;
		if (currency === 'USD' && usdRate) return (amount * usdRate) / eurRate;
		if (currency === 'GBP' && gbpRate) return (amount * gbpRate) / eurRate;
		return null;
	}

	// ─── Vade / aciliyet yardımcıları ───────────────────────
	function nextDueDate(p: any): string | null {
		if (p.next_payment_date) return p.next_payment_date;
		if (p.type === 'kredi_karti' && p.end_date) return p.end_date;
		return null;
	}
	function daysToNext(p: any): number | null {
		const d = nextDueDate(p);
		if (!d) return null;
		const today = new Date(); today.setHours(0, 0, 0, 0);
		return Math.round((new Date(d + 'T00:00:00').getTime() - today.getTime()) / 864e5);
	}
	/** Vade rozeti (gün sayısına göre etiket + renk sınıfı). */
	function dueChip(days: number | null): { label: string; cls: string } {
		if (days == null) return { label: 'rotatif', cls: 'text-gray-600 bg-gray-100' };
		if (days < 0) return { label: `${Math.abs(days)}g gecikme`, cls: 'text-red-700 bg-red-50' };
		if (days === 0) return { label: 'bugün', cls: 'text-orange-700 bg-orange-50' };
		if (days <= 30) return { label: `${days}g kaldı`, cls: 'text-orange-700 bg-orange-50' };
		if (days <= 90) return { label: `${days}g kaldı`, cls: 'text-brass-dark bg-brass-soft' };
		return { label: `${days}g kaldı`, cls: 'text-gray-600 bg-gray-100' };
	}

	const TIER_FILL: Record<string, string> = { ok: 'bg-brass', soon: 'bg-brass', urgent: 'bg-orange-500', overdue: 'bg-red-600' };
	const TIER_FILL_EUR: Record<string, string> = { ok: 'bg-teal-500', soon: 'bg-teal-500', urgent: 'bg-orange-500', overdue: 'bg-red-600' };

	/** Kredinin açılış→vade zaman çizgisi: ilerleme oranı + vadeye kalan gün + aciliyet kademesi. */
	function creditTimeline(p: any) {
		if (!p?.end_date) return { hasVade: false, progress: 0, daysToDue: 0, tier: 'ok' };
		const end = new Date(p.end_date + 'T00:00:00');
		const today = new Date(); today.setHours(0, 0, 0, 0);
		const start = p.start_date ? new Date(p.start_date + 'T00:00:00') : new Date(end.getTime() - 365 * 864e5);
		const total = Math.max(end.getTime() - start.getTime(), 1);
		const progress = Math.min(Math.max((today.getTime() - start.getTime()) / total, 0), 1);
		const daysToDue = Math.round((end.getTime() - today.getTime()) / 864e5);
		const tier = daysToDue <= 0 ? 'overdue' : daysToDue <= 30 ? 'urgent' : daysToDue <= 90 ? 'soon' : 'ok';
		return { hasVade: true, progress, daysToDue, tier };
	}

	// ─── Türetilmiş: aktif / kapalı listeler + KPI ──────────
	let activeCredits = $derived(
		products.filter((p: any) => p.status !== 'closed').slice().sort((a: any, b: any) => {
			const da = daysToNext(a), db = daysToNext(b);
			if (da == null && db == null) return (b.remaining_amount || 0) - (a.remaining_amount || 0);
			if (da == null) return 1;
			if (db == null) return -1;
			return da - db;
		}),
	);
	let closedCredits = $derived(products.filter((p: any) => p.status === 'closed'));

	let kpis = $derived.by(() => {
		let totalEur = 0, tlEur = 0, eurEur = 0, thisMonth = 0, soon = 0, soonCount = 0;
		let missingRate = false;
		const curMonth = _now.getMonth(), curYear = _now.getFullYear();
		for (const p of activeCredits) {
			const cur = p.currency || 'TRY';
			const e = toEur(p.remaining_amount || 0, cur);
			if (e == null) { missingRate = true; } else {
				totalEur += e;
				if (p.currency === 'EUR') eurEur += e; else tlEur += e;
			}
			// Bu Ay Ödenecek: yalnız gerçek planlı taksitler (kartın tüm bakiyesi şişirmesin)
			if (p.next_payment_date && p.next_payment_amount) {
				const nde = new Date(p.next_payment_date + 'T00:00:00');
				const eAmt = toEur(p.next_payment_amount, cur);
				if (eAmt != null && nde.getMonth() === curMonth && nde.getFullYear() === curYear) thisMonth += eAmt;
			}
			// Vadesi Yaklaşan (≤30g): planlı taksit tutarı, kartta son-ödeme kalan bakiyesi
			const nd = nextDueDate(p);
			const soonAmt = p.next_payment_amount ?? (p.type === 'kredi_karti' ? p.remaining_amount : null);
			if (nd && soonAmt) {
				const eAmt = toEur(soonAmt, cur);
				const days = daysToNext(p);
				if (eAmt != null && days != null && days >= 0 && days <= 30) { soon += eAmt; soonCount++; }
			}
		}
		const pct = (v: number) => (totalEur > 0 ? Math.round((v / totalEur) * 100) : 0);
		return {
			totalEur, tlEur, eurEur, thisMonth, soon, soonCount, missingRate,
			activeCount: activeCredits.length, tlPct: pct(tlEur), eurPct: pct(eurEur),
		};
	});

	let selected = $derived(products.find((p: any) => p.id === selectedId) ?? null);
	let selTimeline = $derived(creditTimeline(selected));

	// Seçili kredinin ödeme planı — ay ay gruplama (kronolojik)
	let selPaymentMonths = $derived.by(() => {
		const groups = new Map<string, any[]>();
		for (const pay of selPayments) {
			const ym = (pay.due_date || '').slice(0, 7);
			if (!ym) continue;
			if (!groups.has(ym)) groups.set(ym, []);
			groups.get(ym)!.push(pay);
		}
		return Array.from(groups.entries())
			.sort((a, b) => a[0].localeCompare(b[0]))
			.map(([ym, pays]) => {
				const total = pays.reduce((s, p) => s + (p.amount || 0), 0);
				const paidCount = pays.filter((p) => p.is_paid).length;
				const unpaidTotal = pays.filter((p) => !p.is_paid).reduce((s, p) => s + (p.amount || 0), 0);
				const hasOverdue = pays.some((p) => !p.is_paid && p.due_date < TODAY_ISO);
				return { ym, label: `${AY_UZUN[Number(ym.slice(5)) - 1]} ${ym.slice(0, 4)}`, pays, total, paidCount, count: pays.length, unpaidTotal, hasOverdue };
			});
	});

	// Bilgiler sekmesi verileri
	let infoCost = $derived.by(() => {
		if (!selected) return [];
		return [
			{ k: 'Faiz oranı', v: selected.interest_rate ? `%${selected.interest_rate} yıllık` : '—' },
			{ k: 'BSMV', v: selected.bsmv_rate ? `%${selected.bsmv_rate}` : '—' },
			{ k: 'Komisyon', v: selected.commission_rate ? `%${selected.commission_rate}` : '—' },
			{ k: 'Toplam limit', v: fmt(selected.total_amount, selected.currency) },
		];
	});
	let infoTerms = $derived.by(() => {
		if (!selected) return [];
		return [
			{ k: 'Kullandırım', v: fmtDate(selected.start_date) },
			{ k: 'Vade', v: selected.end_date ? fmtDate(selected.end_date) : 'Vadesiz (rotatif)' },
			{ k: 'Teminat', v: selected.details?.teminat || '—' },
			{ k: 'Banka', v: selected.bank_name || selected.company || '—' },
			{ k: 'Not', v: selected.notes || '—' },
		];
	});

	// ─── Banka bazlı gruplama (EUR konsolide) ───────────────
	let bankGroups = $derived.by(() => {
		const groups: Record<string, any[]> = {};
		for (const p of activeCredits) {
			// Kredi kartları borcu 0 olsa da gösterilir (aktif banka imkânı/limiti);
			// diğer krediler yalnız kalan borcu varsa dahil olur.
			if ((p.remaining_amount || 0) <= 0 && p.type !== 'kredi_karti') continue;
			const bank = p.bank_name || p.company || 'Atanmamış';
			if (!groups[bank]) groups[bank] = [];
			groups[bank].push(p);
		}
		return Object.entries(groups)
			.map(([bank, items]) => {
				const enriched = items.map(p => ({ ...p, _eur: toEur(p.remaining_amount, p.currency || 'TRY') }));
				const totalEur = enriched.reduce((s, it) => s + (it._eur || 0), 0);
				return {
					bank, initial: bank.charAt(0).toLocaleUpperCase('tr-TR'),
					items: enriched.slice().sort((a, b) => {
						const da = daysToNext(a), db = daysToNext(b);
						if (da == null && db == null) return (b._eur || 0) - (a._eur || 0);
						if (da == null) return 1; if (db == null) return -1; return da - db;
					}),
					totalEur, count: enriched.length,
					hasMissingRate: enriched.some(it => it._eur == null),
				};
			})
			.filter(g => g.totalEur > 0 || g.items.some((it: any) => it.type === 'kredi_karti'))
			.sort((a, b) => b.totalEur - a.totalEur);
	});

	// ─── Taksit takvimi (tüm aktif krediler, ay ay) ─────────
	let calMonths = $derived.by(() => {
		const groups = new Map<string, any[]>();
		for (const u of upcoming) {
			const ym = (u.due_date || '').slice(0, 7);
			if (!ym) continue;
			if (!groups.has(ym)) groups.set(ym, []);
			groups.get(ym)!.push(u);
		}
		return Array.from(groups.entries())
			.sort((a, b) => a[0].localeCompare(b[0]))
			.map(([ym, items]) => {
				const paidTotals: Record<string, number> = {};
				const unpaidTotals: Record<string, number> = {};
				for (const it of items) {
					const cur = it.currency || 'TRY';
					const bucket = it.is_paid ? paidTotals : unpaidTotals;
					bucket[cur] = (bucket[cur] || 0) + (it.amount || 0);
				}
				const paidCount = items.filter((it) => it.is_paid).length;
				const hasOverdue = items.some((it) => !it.is_paid && it.due_date < TODAY_ISO);
				return {
					ym, label: `${AY_UZUN[Number(ym.slice(5)) - 1]} ${ym.slice(0, 4)}`,
					items: items.slice().sort((a, b) => (a.due_date || '').localeCompare(b.due_date || '')),
					paidTotals, unpaidTotals, paidCount, count: items.length, hasOverdue,
				};
			});
	});
	function monthTotalLabel(totals: Record<string, number>): string {
		const parts = Object.entries(totals).filter(([, amt]) => amt > 0);
		if (parts.length === 0) return '';
		return parts.map(([cur, amt]) => fmt(amt, cur)).join(' · ');
	}

	// ─── Veri yükleme ───────────────────────────────────────
	async function loadData() {
		loading = true;
		try {
			const [prodRes, upRes, ratesRes] = await Promise.all([
				api.get<{ items?: any[] }>('/finance/krediler/?page_size=200&status='),
				api.get<any[]>('/finance/krediler/upcoming-payments?days=365&include_paid=true'),
				api.get<LatestRates>('/finance/exchange-rates/latest').catch(() => null),
			]);
			products = prodRes.items || [];
			upcoming = upRes || [];
			latestRates = ratesRes;

			// Kart ekstre göstergesi için tüm kartların ekstrelerini yükle
			const cardIds = products.filter((p: any) => p.type === 'kredi_karti').map((p: any) => p.id);
			const stmts: any[] = [];
			for (const cid of cardIds) {
				try {
					const res = await api.get<any[]>(`/finance/krediler/kart/${cid}/statements`);
					if (res && res.length) stmts.push(...res.map((s: any) => ({ ...s, credit_product_id: cid })));
				} catch (err) { console.error('Kart ekstre yükleme hatası (id=' + cid + '):', err); }
			}
			allCardStmts = stmts;
		} catch (e) {
			console.error('Krediler yükleme hatası:', e);
			showToast('Krediler yüklenemedi', 'error');
		}
		loading = false;
		await refreshSelection();
	}

	/** Seçili krediyi geçerli tut ve detayını tazele (WS refresh sonrası da). */
	async function refreshSelection() {
		if (view !== 'krediler') return;
		const stillValid = selectedId != null && products.some((p: any) => p.id === selectedId);
		if (!stillValid) {
			const first = activeCredits[0] || products[0];
			selectedId = first ? first.id : null;
		}
		if (selectedId != null) {
			const p = products.find((pr: any) => pr.id === selectedId);
			if (p) await loadSelectedDetail(p.id, p.type);
		}
	}

	/** Seçili kredinin ödeme planı + KMH/kart detayını yükler. */
	async function loadSelectedDetail(id: number, type: string) {
		try {
			const res = await api.get<{ payments?: any[] }>(`/finance/krediler/${id}`);
			selPayments = res.payments || [];
			initSelMonths();
		} catch (e) {
			console.error('Detay yükleme hatası:', e);
			selPayments = [];
		}
		if (type === 'kredi_karti') {
			await loadCCStatements(id);
			kmhStatus = null;
		} else if (type === 'kmh') {
			ccStatements = [];
			try {
				kmhStatus = await api.get<any>(`/finance/krediler/${id}/kmh-status`);
			} catch (e: any) {
				console.error('KMH status yüklenemedi:', e);
				kmhStatus = { error: e?.message || 'Yüklenemedi' };
			}
		} else {
			ccStatements = [];
			kmhStatus = null;
		}
		ccExpandedStmtId = null;
		ccExpandedStmt = null;
	}

	// Kredi seç (kullanıcı tıklaması)
	async function selectCredit(p: any) {
		selectedId = p.id;
		detailTab = 'plan';
		mobileShowDetail = true;
		await loadSelectedDetail(p.id, p.type);
	}
	function backToList() { mobileShowDetail = false; }

	function initSelMonths() {
		const open = new Set<string>();
		const groups = new Map<string, boolean>();
		for (const pay of selPayments) {
			const ym = (pay.due_date || '').slice(0, 7);
			if (!ym) continue;
			if (!pay.is_paid) groups.set(ym, true);
			else if (!groups.has(ym)) groups.set(ym, false);
		}
		for (const [ym, hasUnpaid] of groups) if (hasUnpaid) open.add(ym);
		selOpenMonths = open;
	}
	function toggleSelMonth(ym: string) {
		const next = new Set(selOpenMonths);
		if (next.has(ym)) next.delete(ym); else next.add(ym);
		selOpenMonths = next;
	}

	// Takvim akordiyon: ilk (en yakın) ay açık başlar
	$effect(() => {
		if (view === 'takvim' && !calInitialized && upcoming.length > 0) {
			const first = calMonths[0]?.ym;
			if (first) { openCalMonths = new Set([first]); calInitialized = true; }
		}
	});
	function toggleCalMonth(ym: string) {
		const next = new Set(openCalMonths);
		if (next.has(ym)) next.delete(ym); else next.add(ym);
		openCalMonths = next;
	}

	// Görünüm değiştir — 'krediler'e dönünce seçili detayı tazele (WS başka görünümdeyken
	// güncellediyse bayat ödeme planı/KMH/ekstre göstermesin)
	async function changeView(v: string) {
		view = v as 'krediler' | 'takvim' | 'banka';
		if (v === 'krediler') await refreshSelection();
	}

	// Banka görünümünden krediye tıkla → Krediler görünümünde seç
	async function jumpToCredit(p: any) {
		view = 'krediler';
		await selectCredit(p);
	}

	// ─── Kredi kartı ekstre fonksiyonları ───────────────────
	async function loadCCStatements(productId: number) {
		try {
			ccStatements = (await api.get<any[]>(`/finance/krediler/kart/${productId}/statements`)) || [];
		} catch (e) {
			console.error('Ekstre yükleme hatası:', e);
			ccStatements = [];
		}
	}
	async function uploadCCStatement(file: File) {
		if (!file.name.toLowerCase().endsWith('.pdf')) {
			ccUploadError = 'Sadece PDF dosyaları yüklenebilir';
			showToast(ccUploadError, 'error');
			return;
		}
		ccUploading = true; ccUploadError = ''; ccUploadSuccess = '';
		try {
			const formData = new FormData();
			formData.append('file', file);
			const res: any = await api.upload('/finance/krediler/kart/auto-upload', formData);
			ccUploadSuccess = `${res.card_name || 'Kart'} — ${res.kesim_tarihi} dönemi yüklendi (${res.transaction_count} işlem)`;
			showToast(ccUploadSuccess, 'success');
			if (selectedId && selected?.type === 'kredi_karti') await loadCCStatements(selectedId);
			await loadData();
		} catch (e: any) {
			console.error('Ekstre yükleme hatası:', e);
			ccUploadError = e?.message || 'Ekstre yüklenirken bir hata oluştu';
			showToast(ccUploadError, 'error');
		}
		ccUploading = false;
	}
	function handleCCFileSelect(files: File[]) { files.forEach(f => uploadCCStatement(f)); }
	function handleCCDropError(errors: string[]) { for (const err of errors) showToast(err, 'error', 4000); }

	async function toggleCCStmtExpand(productId: number, stmtId: number) {
		if (ccExpandedStmtId === stmtId) { ccExpandedStmtId = null; ccExpandedStmt = null; return; }
		try {
			ccExpandedStmt = await api.get<any>(`/finance/krediler/kart/${productId}/statements/${stmtId}`);
			ccExpandedStmtId = stmtId;
		} catch (e) { console.error('Ekstre detay hatası:', e); }
	}
	function deleteCCStatement(productId: number, stmtId: number) {
		askDelete('Ekstreyi Sil', 'Bu ekstreyi silmek istediğinize emin misiniz?', async () => {
			try {
				await api.delete(`/finance/krediler/kart/${productId}/statements/${stmtId}`);
				ccStatements = ccStatements.filter(s => s.id !== stmtId);
				if (ccExpandedStmtId === stmtId) { ccExpandedStmtId = null; ccExpandedStmt = null; }
				await loadData();
			} catch (e: any) { console.error('Ekstre silme hatası:', e); showToast(e?.message || 'Ekstre silinemedi', 'error'); }
		});
	}
	function getStmtStatus(stmt: any): { label: string; bg: string; text: string } {
		if (stmt.is_paid) return { label: 'Ödendi', bg: 'bg-emerald-100', text: 'text-emerald-700' };
		if (stmt.son_odeme_tarihi < TODAY_ISO) return { label: 'Gecikmiş', bg: 'bg-red-100', text: 'text-red-700' };
		return { label: 'Bekliyor', bg: 'bg-amber-100', text: 'text-amber-700' };
	}
	/** Kart bu ay için ekstre bekliyor mu (kesim geçti, henüz yüklenmedi)? */
	function cardNeedsStatement(p: any): boolean {
		if (p.type !== 'kredi_karti' || !p.details?.ekstre_kesim_gunu) return false;
		const kesimGun = p.details.ekstre_kesim_gunu;
		const last = allCardStmts.find((s: any) => s.credit_product_id === p.id);
		const thisMonthKesim = new Date(_now.getFullYear(), _now.getMonth(), kesimGun);
		if (!last) return _now > thisMonthKesim;
		return new Date(last.kesim_tarihi) < thisMonthKesim && _now > thisMonthKesim;
	}

	// ─── Ürün CRUD ──────────────────────────────────────────
	function openAdd() {
		editProduct = null;
		form = {
			type: 'kredi_karti', name: '', bank_name: '', company: '', currency: 'TRY',
			total_amount: null, remaining_amount: null, interest_rate: null,
			bsmv_rate: null, commission_rate: null, start_date: '', end_date: '', notes: '', details: {},
		};
		showAddModal = true;
	}
	function openEdit(p: any) {
		editProduct = p;
		form = {
			type: p.type, name: p.name || '', bank_name: p.bank_name || '', company: p.company || '',
			currency: p.currency || 'TRY', total_amount: p.total_amount ?? null, remaining_amount: p.remaining_amount ?? null,
			interest_rate: p.interest_rate, bsmv_rate: p.bsmv_rate, commission_rate: p.commission_rate,
			start_date: p.start_date || '', end_date: p.end_date || '', notes: p.notes || '', details: { ...(p.details || {}) },
		};
		showAddModal = true;
	}
	async function saveProduct() {
		try {
			const body: any = { ...form };
			if (!body.interest_rate) body.interest_rate = null;
			if (!body.bsmv_rate && body.bsmv_rate !== 0) body.bsmv_rate = null;
			if (!body.commission_rate && body.commission_rate !== 0) body.commission_rate = null;
			if (!body.start_date) body.start_date = null;
			if (!body.end_date) body.end_date = null;
			if (body.details && !body.details.teminat) delete body.details.teminat;

			if (editProduct) await api.patch(`/finance/krediler/${editProduct.id}`, body);
			else await api.post('/finance/krediler/', body);
			showAddModal = false;
			await loadData();
		} catch (e: any) {
			console.error('Kaydetme hatası:', e);
			showToast(e?.message || 'Kaydetme hatası', 'error');
		}
	}
	function deleteProduct(id: number) {
		askDelete('Kredi Ürününü Sil', 'Bu kredi ürününü silmek istediğinize emin misiniz?', async () => {
			try {
				await api.delete(`/finance/krediler/${id}`);
				if (selectedId === id) { selectedId = null; mobileShowDetail = false; }
				await loadData();
			} catch (e: any) { console.error('Silme hatası:', e); showToast(e?.message || 'Kredi silinemedi', 'error'); }
		});
	}

	// ─── Ödeme (taksit) yönetimi ────────────────────────────
	function openPaymentModal(productId: number) {
		paymentProductId = productId;
		paymentForm = { count: 12, start_date: '', amount: null, principal: null, interest: null, tax: null };
		showPaymentModal = true;
	}
	async function generatePayments() {
		if (!paymentProductId || !paymentForm.start_date || paymentForm.count < 1) return;
		if (!paymentForm.amount || paymentForm.amount <= 0) { showToast('Taksit tutarı zorunludur', 'warning'); return; }
		const payments = [];
		const start = new Date(paymentForm.start_date);
		for (let i = 0; i < paymentForm.count; i++) {
			const d = new Date(start); d.setMonth(d.getMonth() + i);
			payments.push({
				installment_no: i + 1, due_date: d.toISOString().split('T')[0], amount: paymentForm.amount,
				principal: paymentForm.principal || null, interest: paymentForm.interest || null, tax: paymentForm.tax || null,
			});
		}
		try {
			await api.post(`/finance/krediler/${paymentProductId}/payments`, { payments });
			showPaymentModal = false;
			await loadData();
		} catch (e: any) {
			console.error('Ödeme oluşturma hatası:', e);
			showToast(e?.message || 'Ödeme oluşturulamadı', 'error');
		}
	}
	async function togglePaid(payment: any) {
		try {
			const newPaid = !payment.is_paid;
			await api.patch(`/finance/krediler/payments/${payment.id}`, {
				is_paid: newPaid, paid_date: newPaid ? TODAY_ISO : null,
			});
			payment.is_paid = newPaid;
			payment.paid_date = newPaid ? TODAY_ISO : null;
			selPayments = [...selPayments];
			if (payment.principal) {
				const product = products.find((p: any) => p.id === payment.credit_product_id);
				if (product) {
					product.remaining_amount = newPaid
						? Math.max(0, (product.remaining_amount || 0) - payment.principal)
						: (product.remaining_amount || 0) + payment.principal;
					products = [...products];
				}
			}
		} catch (e: any) { console.error('Ödeme güncelleme hatası:', e); showToast(e?.message || 'Taksit güncellenemedi', 'error'); }
	}
	function deletePayment(paymentId: number) {
		askDelete('Ödemeyi Sil', 'Bu ödemeyi silmek istediğinize emin misiniz?', async () => {
			try {
				await api.delete(`/finance/krediler/payments/${paymentId}`);
				selPayments = selPayments.filter(p => p.id !== paymentId);
				await loadData();
			} catch (e: any) { console.error('Ödeme silme hatası:', e); showToast(e?.message || 'Taksit silinemedi', 'error'); }
		});
	}

	// ─── Kapat / Yeniden Aç ─────────────────────────────────
	function openCloseModal(p: any) {
		closeModal = { show: true, id: p.id, name: p.name, closedDate: TODAY_ISO };
	}
	async function confirmClose() {
		if (closeModal.id == null) return;
		try {
			await api.post(`/finance/krediler/${closeModal.id}/close`, { closed_date: closeModal.closedDate });
			showToast('Kredi kapatıldı, ileri vadeli ödemeler nakit akımdan çıkarıldı', 'success');
			closeModal = { show: false, id: null, name: '', closedDate: TODAY_ISO };
			await loadData();
		} catch (e: any) {
			console.error('Kredi kapatma hatası:', e);
			showToast(e?.message || 'Kredi kapatılamadı', 'error');
		}
	}
	function reopenProduct(p: any) {
		askConfirm('Krediyi Yeniden Aç', `"${p.name}" yeniden açılacak ve ödenmemiş taksitler nakit akıma geri eklenecek. Devam edilsin mi?`, async () => {
			try {
				await api.post(`/finance/krediler/${p.id}/reopen`, {});
				showToast('Kredi yeniden açıldı', 'success');
				await loadData();
			} catch (e: any) {
				console.error('Yeniden açma hatası:', e);
				showToast(e?.message || 'Kredi yeniden açılamadı', 'error');
			}
		}, { confirmText: 'Yeniden Aç', danger: false });
	}

	// ─── PDF ────────────────────────────────────────────────
	async function downloadPdf() {
		pdfLoading = true;
		try {
			const res = await api.fetchRaw('/finance/krediler/export/pdf');
			if (!res.ok) throw new Error('İndirme başarısız');
			const blob = await res.blob();
			pdfModal?.open(blob, `kredi-raporu-${TODAY_ISO}.pdf`);
		} catch (err) {
			console.error('PDF indirme hatası:', err);
			showToast('PDF raporu indirilemedi', 'error');
		} finally { pdfLoading = false; }
	}

	// ─── Lifecycle ──────────────────────────────────────────
	let unsubFinance: (() => void) | null = null;
	onMount(() => {
		loadData();
		unsubFinance = onWsEvent('finance_updated', () => { loadData(); });
	});
	onDestroy(() => { unsubFinance?.(); });
</script>

<svelte:head><title>Krediler · Sprenses</title></svelte:head>

<div class="max-w-[1400px] mx-auto px-1 sm:px-2 pb-10">
	<div class="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">

		<!-- ═══ Lacivert başlık + KPI ═══ -->
		<div class="bg-teal-700 text-teal-100 px-4 sm:px-7 pt-5 pb-5">
			<div class="flex items-start justify-between gap-4 flex-wrap">
				<div class="min-w-0">
					<div class="text-[10px] tracking-[0.14em] uppercase text-teal-400 mb-1">Finans · Krediler</div>
					<h1 class="text-white text-lg sm:text-2xl leading-tight">Kredi Portföyü &amp; Ödeme Planı</h1>
					<p class="text-[11px] sm:text-xs text-teal-300 mt-1">TL + EUR karışık · EUR konsolide raporlama · spot / taksitli / BCH / leasing / KMH / kart</p>
				</div>
				<div class="flex gap-2.5 items-stretch">
					<div class="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-right">
						<div class="text-[9px] tracking-wide uppercase text-teal-400">Kur</div>
						<div class="tabular-nums text-sm font-semibold text-brass-light mt-0.5">1 € = ₺{eurRate ? eurRate.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</div>
					</div>
					<div class="text-right px-1 py-1.5 hidden sm:block">
						<div class="text-[9px] tracking-wide uppercase text-teal-400">Bugün</div>
						<div class="tabular-nums text-sm font-semibold text-white mt-0.5">{TODAY_LABEL}</div>
					</div>
				</div>
			</div>

			<!-- KPI hücreleri -->
			<div class="grid grid-cols-2 md:grid-cols-5 gap-2.5 mt-4">
				<div class="bg-white/5 border border-white/10 rounded-xl px-3.5 py-3">
					<div class="text-[9.5px] tracking-wide uppercase text-teal-400">Toplam Borç · EUR</div>
					<div class="tabular-nums text-lg sm:text-xl font-semibold text-brass-light mt-1">{shortEur(kpis.totalEur)}</div>
					<div class="text-[10.5px] text-teal-300 mt-0.5">{kpis.activeCount} aktif ürün{kpis.missingRate ? ' · bazı kurlar eksik' : ''}</div>
				</div>
				<div class="bg-white/5 border border-white/10 rounded-xl px-3.5 py-3">
					<div class="text-[9.5px] tracking-wide uppercase text-teal-400">TL Krediler</div>
					<div class="tabular-nums text-lg sm:text-xl font-semibold text-white mt-1">{shortEur(kpis.tlEur)}</div>
					<div class="text-[10.5px] text-teal-300 mt-0.5">%{kpis.tlPct} · kur riski</div>
				</div>
				<div class="bg-white/5 border border-white/10 rounded-xl px-3.5 py-3">
					<div class="text-[9.5px] tracking-wide uppercase text-teal-400">EUR Krediler</div>
					<div class="tabular-nums text-lg sm:text-xl font-semibold text-teal-200 mt-1">{shortEur(kpis.eurEur)}</div>
					<div class="text-[10.5px] text-teal-300 mt-0.5">%{kpis.eurPct} · doğal hedge</div>
				</div>
				<div class="bg-white/5 border border-white/10 rounded-xl px-3.5 py-3">
					<div class="text-[9.5px] tracking-wide uppercase text-teal-400">Bu Ay Ödenecek</div>
					<div class="tabular-nums text-lg sm:text-xl font-semibold text-white mt-1">{shortEur(kpis.thisMonth)}</div>
					<div class="text-[10.5px] text-teal-300 mt-0.5">{AY_UZUN[_now.getMonth()]} taksitleri</div>
				</div>
				<div class="rounded-xl px-3.5 py-3 border" style="background:rgba(240,165,143,.1);border-color:rgba(240,165,143,.22)">
					<div class="text-[9.5px] tracking-wide uppercase" style="color:#f0b6a5">Vadesi Yaklaşan</div>
					<div class="tabular-nums text-lg sm:text-xl font-semibold mt-1" style="color:#f0a58f">{shortEur(kpis.soon)}</div>
					<div class="text-[10.5px] mt-0.5" style="color:#d9a596">≤30 gün · {kpis.soonCount} ödeme</div>
				</div>
			</div>
		</div>

		<!-- ═══ Görünüm segmenti + aksiyonlar ═══ -->
		<div class="flex items-center justify-between gap-3 px-3 sm:px-5 py-2.5 bg-gray-50 border-b border-gray-200 flex-wrap">
			<SegmentedControl options={VIEW_OPTIONS} value={view} onchange={changeView} ariaLabel="Görünüm" />
			<div class="flex gap-2">
				<Button variant="secondary" size="sm" onclick={downloadPdf} disabled={pdfLoading} title="Kredileri PDF rapor olarak indir">
					<FileDown size={15} /> <span class="hidden sm:inline">{pdfLoading ? 'Hazırlanıyor…' : 'PDF Rapor'}</span>
				</Button>
				{#if canUse}
					<Button size="sm" onclick={openAdd}><Plus size={15} /> Yeni Kredi</Button>
				{/if}
			</div>
		</div>

		<!-- ═══ GÖRÜNÜM: KREDİLER (master-detail) ═══ -->
		{#if view === 'krediler'}
			{#if loading}
				<div class="p-4"><TableSkeleton rows={6} columns={3} showHeader={false} /></div>
			{:else if products.length === 0}
				<div class="p-8">
					<EmptyState icon={CreditCard} title="Henüz kredi ürünü yok" description={canUse ? 'Yeni kredi eklemek için yukarıdaki butonu kullanın' : ''} />
				</div>
			{:else}
				<div class="lg:flex lg:min-h-[560px]">
					<!-- SOL: kredi listesi -->
					<div class="{mobileShowDetail ? 'hidden lg:flex' : 'flex'} lg:flex flex-col w-full lg:w-[340px] lg:flex-none lg:border-r border-gray-200 bg-gray-50">
						<div class="px-4 pt-3.5 pb-2 text-[10.5px] tracking-wider uppercase text-gray-500 font-bold">Aktif Krediler · vadeye göre</div>
						<div class="flex-1 lg:overflow-y-auto px-3 pb-4 space-y-1">
							{#each activeCredits as c (c.id)}
								{@const days = daysToNext(c)}
								{@const chip = dueChip(days)}
								{@const isEur = c.currency === 'EUR'}
								{@const prog = c.payment_count ? Math.round((c.paid_count / c.payment_count) * 100) : 0}
								{@const sel = c.id === selectedId}
								<button
									onclick={() => selectCredit(c)}
									class="w-full flex gap-3 text-left px-3 py-2.5 rounded-xl cursor-pointer border transition-colors {sel ? 'border-gray-300 bg-white shadow-sm' : 'border-transparent hover:bg-white/70'}"
								>
									<div class="w-[3px] self-stretch rounded-full shrink-0" style="background:{CUR_BAR(isEur)}"></div>
									<div class="flex-1 min-w-0">
										<div class="flex items-baseline justify-between gap-2">
											<span class="text-[13.5px] font-semibold text-gray-900 truncate">{c.name}</span>
											<span class="tabular-nums text-xs font-semibold shrink-0" style="color:{CUR_TEXT(isEur)}">{fmt(c.remaining_amount, c.currency)}</span>
										</div>
										<div class="flex items-center justify-between gap-2 mt-1">
											<span class="flex items-center gap-1.5 min-w-0">
												<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap" style="color:{typeStyle(c.type).fg};background:{typeStyle(c.type).bg}">{c.type_label}</span>
												<span class="text-[11px] text-gray-500 truncate">{c.bank_name || c.company || ''}</span>
											</span>
											<span class="tabular-nums text-[10.5px] text-gray-500 shrink-0">≈{shortEur(toEur(c.remaining_amount, c.currency))}</span>
										</div>
										<div class="flex items-center gap-2 mt-1.5">
											<span class="flex-1 h-[5px] rounded-full bg-gray-200 overflow-hidden">
												<span class="block h-full rounded-full" style="width:{Math.max(3, prog)}%;background:{CUR_BAR(isEur)}"></span>
											</span>
											<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap {chip.cls}">{chip.label}</span>
											{#if cardNeedsStatement(c)}<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 whitespace-nowrap">Ekstre?</span>{/if}
										</div>
									</div>
								</button>
							{/each}

							{#if closedCredits.length > 0}
								<div class="px-1 pt-3 pb-1 text-[10.5px] tracking-wider uppercase text-gray-500 font-bold">Kapalı</div>
								{#each closedCredits as c (c.id)}
									{@const sel = c.id === selectedId}
									<button
										onclick={() => selectCredit(c)}
										class="w-full flex gap-3 text-left px-3 py-2.5 rounded-xl cursor-pointer border transition-colors {sel ? 'border-gray-300 bg-white shadow-sm' : 'border-transparent hover:bg-white/70'}"
									>
										<div class="w-[3px] self-stretch rounded-full shrink-0 bg-gray-300"></div>
										<div class="flex-1 min-w-0">
											<div class="flex items-baseline justify-between gap-2">
												<span class="text-[13px] font-medium text-gray-500 line-through truncate">{c.name}</span>
												<span class="text-[10px] font-semibold text-gray-500 bg-gray-200 px-1.5 py-0.5 rounded shrink-0">Kapalı</span>
											</div>
											<div class="text-[11px] text-gray-500 mt-1">{c.bank_name || c.company || ''}{c.closed_date ? ` · ${fmtDate(c.closed_date)} kapatıldı` : ''}</div>
										</div>
									</button>
								{/each}
							{/if}
						</div>
					</div>

					<!-- SAĞ: detay -->
					<div class="{mobileShowDetail ? 'block' : 'hidden lg:block'} flex-1 min-w-0 lg:overflow-y-auto px-4 sm:px-6 py-4 sm:py-5">
						{#if !selected}
							<div class="h-full flex items-center justify-center py-16">
								<EmptyState icon={CreditCard} title="Kredi seçin" description="Detayı görüntülemek için soldaki listeden bir kredi seçin" />
							</div>
						{:else}
							{@const p = selected}
							{@const kalanStr = fmt(p.remaining_amount, p.currency)}
							{@const sonrakiStr = p.next_payment_amount ? fmt(p.next_payment_amount, p.currency) : (p.type === 'kredi_karti' ? 'Ekstre' : '—')}
							<!-- Mobil geri -->
							<button onclick={backToList} class="lg:hidden inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-700 mb-3 cursor-pointer">
								<ChevronLeft size={15} /> Kredi listesine dön
							</button>

							<!-- Başlık + aksiyonlar -->
							<div class="flex items-start justify-between gap-3 flex-wrap">
								<div class="min-w-0">
									<div class="flex items-center gap-2 flex-wrap">
										<h2 class="text-lg sm:text-xl text-gray-900 leading-tight">{p.name}</h2>
										<span class="text-[11px] font-semibold px-2 py-0.5 rounded" style="color:{typeStyle(p.type).fg};background:{typeStyle(p.type).bg}">{p.type_label}</span>
										<span class="text-[10px] font-semibold px-2 py-0.5 rounded" style={p.currency === 'EUR' ? 'color:#3a5573;background:#e9eef4' : 'color:#6d571b;background:#f4ecd4'}>{p.currency}</span>
										{#if p.status === 'closed'}<span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-gray-200 text-gray-600">Kapalı</span>{/if}
									</div>
									<div class="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-gray-500">
										<span class="flex items-center gap-1.5"><Landmark size={13} class="text-gray-500" />{p.bank_name || p.company || '—'}</span>
										<span>Kullandırım <span class="tabular-nums text-gray-700">{fmtDate(p.start_date)}</span></span>
										<span>Vade <span class="tabular-nums text-gray-700">{p.end_date ? fmtDate(p.end_date) : 'Vadesiz'}</span></span>
									</div>
								</div>
								{#if canUse}
									<div class="flex flex-wrap gap-1.5">
										{#if p.type !== 'kredi_karti' && p.type !== 'kmh'}
											<Button variant="secondary" size="sm" onclick={() => openPaymentModal(p.id)}><Plus size={14} /> Taksit</Button>
										{/if}
										<Button variant="secondary" size="sm" onclick={() => openEdit(p)}><Pencil size={14} /> Düzenle</Button>
										{#if p.status === 'closed'}
											<Button variant="secondary" size="sm" onclick={() => reopenProduct(p)}><RotateCcw size={14} /> Yeniden Aç</Button>
										{:else if p.type !== 'kredi_karti'}
											<Button variant="secondary" size="sm" onclick={() => openCloseModal(p)}><CheckCircle2 size={14} /> Erken Kapama</Button>
										{/if}
										<Button variant="danger" size="sm" onclick={() => deleteProduct(p.id)}><Trash2 size={14} /></Button>
									</div>
								{/if}
							</div>

							<!-- Detay KPI -->
							<div class="grid grid-cols-2 xl:grid-cols-4 gap-2.5 mt-4">
								<div class="bg-teal-700 rounded-xl px-3.5 py-3 min-w-0">
									<div class="text-[9.5px] tracking-wide uppercase text-teal-400">Kalan Anapara</div>
									<div class="tabular-nums {kpiSize(kalanStr)} font-semibold text-brass-light mt-1 whitespace-nowrap overflow-hidden">{kalanStr}</div>
									<div class="text-[10.5px] text-teal-300 mt-0.5">≈{shortEur(toEur(p.remaining_amount, p.currency))}</div>
								</div>
								<div class="bg-white border border-gray-200 rounded-xl px-3.5 py-3 min-w-0">
									<div class="text-[9.5px] tracking-wide uppercase text-gray-500">Faiz Oranı</div>
									<div class="tabular-nums text-lg font-semibold text-gray-900 mt-1 whitespace-nowrap">{p.interest_rate ? `%${p.interest_rate}` : '—'}</div>
									<div class="text-[10.5px] text-gray-500 mt-0.5">{p.interest_rate ? 'yıllık' + (p.currency === 'EUR' ? ' · EUR' : '') : 'kart / rotatif'}</div>
								</div>
								<div class="bg-white border border-gray-200 rounded-xl px-3.5 py-3 min-w-0">
									<div class="text-[9.5px] tracking-wide uppercase text-gray-500">Sonraki Taksit</div>
									<div class="tabular-nums {kpiSize(sonrakiStr)} font-semibold text-gray-900 mt-1 whitespace-nowrap overflow-hidden">{sonrakiStr}</div>
									<div class="text-[10.5px] text-gray-500 mt-0.5">{p.next_payment_date ? fmtDate(p.next_payment_date) : (p.type === 'kmh' ? 'rotatif' : '—')}</div>
								</div>
								<div class="bg-white border border-gray-200 rounded-xl px-3.5 py-3 min-w-0">
									<div class="text-[9.5px] tracking-wide uppercase text-gray-500">İlerleme</div>
									<div class="tabular-nums text-lg font-semibold text-gray-900 mt-1 whitespace-nowrap">{p.payment_count ? `${p.paid_count}/${p.payment_count}` : '—'}</div>
									<div class="text-[10.5px] text-gray-500 mt-0.5">{p.payment_count ? 'taksit ödendi' : 'plansız'}</div>
								</div>
							</div>

							<!-- Zaman çizgisi -->
							{#if selTimeline.hasVade}
								<div class="mt-3.5 bg-white border border-gray-200 rounded-xl px-4 py-3">
									<div class="flex items-center justify-between text-[11px] text-gray-500 mb-2">
										<span>Kullandırım {fmtDate(p.start_date)}</span>
										<span class="tabular-nums font-semibold {selTimeline.tier === 'overdue' ? 'text-red-600' : 'text-gray-700'}">Bugüne %{Math.round(selTimeline.progress * 100)}</span>
										<span>Vade {fmtDate(p.end_date)}</span>
									</div>
									<div class="relative h-2.5 bg-gray-200 rounded-full overflow-hidden">
										<div class="absolute left-0 top-0 bottom-0 rounded-full {(p.currency === 'EUR' ? TIER_FILL_EUR : TIER_FILL)[selTimeline.tier]}" style="width:{selTimeline.progress * 100}%"></div>
									</div>
								</div>
							{/if}

							<!-- Sekmeler: Ödeme Planı / Bilgiler -->
							<div class="mt-4">
								<SegmentedControl options={TAB_OPTIONS} value={detailTab} onchange={(v) => (detailTab = v as any)} ariaLabel="Detay sekmesi" size="sm" />
							</div>

							{#if detailTab === 'plan'}
								<!-- ── KMH özel görünümü ── -->
								{#if p.type === 'kmh'}
									{@render kmhView(p)}
								<!-- ── Kredi kartı ekstre bölümü ── -->
								{:else if p.type === 'kredi_karti'}
									{@render cardView(p)}
								<!-- ── Diğer: ödeme planı akordiyon ── -->
								{:else}
									{#if p.status === 'closed'}
										<div class="mt-3 text-[11px] sm:text-xs bg-gray-100 border border-gray-200 text-gray-600 rounded-lg px-3 py-1.5">
											Bu kredi {p.closed_date ? fmtDate(p.closed_date) + ' tarihinde' : ''} kapatıldı. Ödenmemiş taksitler nakit akımdan çıkarıldı (kayıtlar referans için korunuyor).
										</div>
									{/if}
									{#if selPayments.length === 0}
										<div class="mt-3 bg-white border border-dashed border-gray-300 rounded-xl px-6 py-8 text-center text-gray-500 text-sm">Ödeme planı yok</div>
									{:else}
										<div class="mt-3 space-y-2">
											{#each selPaymentMonths as grp (grp.ym)}
												{@const open = selOpenMonths.has(grp.ym)}
												<div class="border border-gray-200 rounded-xl overflow-hidden bg-white">
													<button type="button" onclick={() => toggleSelMonth(grp.ym)} class="w-full flex items-center gap-3 px-4 py-2.5 text-left cursor-pointer hover:bg-gray-50" aria-expanded={open}>
														<ChevronRight size={13} class="shrink-0 text-brass-dark transition-transform {open ? 'rotate-90' : ''}" />
														<span class="text-[13px] font-semibold text-gray-900 flex-1">{grp.label}</span>
														{#if grp.hasOverdue}
															<span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-red-50 text-red-700">Gecikmiş</span>
														{:else if grp.unpaidTotal === 0}
															<span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700">Ödendi</span>
														{:else}
															<span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-brass-soft text-brass-dark">{grp.paidCount}/{grp.count}</span>
														{/if}
														<span class="tabular-nums text-[13px] font-semibold text-gray-900">{fmt(grp.total, p.currency)}</span>
													</button>
													{#if open}
														<div>
															{#each grp.pays as pay (pay.id)}
																{@const overdue = !pay.is_paid && pay.due_date < TODAY_ISO}
																<div class="grid grid-cols-[60px_1fr_auto] xl:grid-cols-[68px_1fr_104px_104px_120px_auto] gap-x-2 xl:gap-x-3 gap-y-0.5 items-center px-3 sm:px-4 py-2.5 border-t border-gray-100 {overdue ? 'bg-red-50/50' : pay.is_paid ? 'bg-emerald-50/40' : ''}">
																	<span class="tabular-nums text-[11.5px] text-gray-500">{fmtDate(pay.due_date)}</span>
																	<div class="min-w-0">
																			<span class="text-xs text-gray-600">Taksit {pay.installment_no || '—'}</span>
																			{#if pay.principal != null || pay.interest != null}
																				<div class="text-[10px] text-gray-500 tabular-nums xl:hidden">Anapara {fmt(pay.principal, p.currency)} · Faiz {fmt(pay.interest, p.currency)}</div>
																			{/if}
																		</div>
																	<span class="hidden xl:block text-right tabular-nums text-[11.5px] whitespace-nowrap" style="color:#2f6b52">{fmt(pay.principal, p.currency)}</span>
																	<span class="hidden xl:block text-right tabular-nums text-[11.5px] text-brass-dark whitespace-nowrap">{fmt(pay.interest, p.currency)}</span>
																	<span class="text-right tabular-nums text-[12.5px] font-semibold text-gray-900 whitespace-nowrap col-start-3 xl:col-start-auto">{fmt(pay.amount, p.currency)}</span>
																	<span class="text-right col-span-3 xl:col-span-1 flex xl:block justify-end mt-1 xl:mt-0">
																		{#if canUse && p.status !== 'closed'}
																			<button onclick={() => togglePaid(pay)} class="text-[10.5px] font-semibold px-2.5 py-1 rounded cursor-pointer {pay.is_paid ? 'text-emerald-700 bg-emerald-50' : overdue ? 'text-red-700 bg-red-50' : 'text-brass-dark bg-brass-soft'}" title={pay.is_paid ? 'Geri al' : 'Ödendi işaretle'}>
																				{pay.is_paid ? 'Ödendi' : overdue ? 'Gecikmiş' : 'Bekliyor'}
																			</button>
																			<button onclick={() => deletePayment(pay.id)} class="ml-1.5 text-red-500 hover:text-red-600 cursor-pointer align-middle" title="Sil" aria-label="Taksiti sil"><X size={13} class="inline-block" /></button>
																		{:else}
																			<span class="text-[10.5px] font-semibold px-2.5 py-1 rounded {pay.is_paid ? 'text-emerald-700 bg-emerald-50' : p.status === 'closed' ? 'text-gray-600 bg-gray-100' : overdue ? 'text-red-700 bg-red-50' : 'text-brass-dark bg-brass-soft'}">
																				{pay.is_paid ? 'Ödendi' : p.status === 'closed' ? 'Kapatıldı' : overdue ? 'Gecikmiş' : 'Bekliyor'}
																			</span>
																		{/if}
																	</span>
																</div>
															{/each}
															<div class="hidden xl:grid grid-cols-[68px_1fr_104px_104px_120px_auto] gap-x-3 px-4 pt-1.5 pb-1 text-[9px] tracking-wide uppercase text-gray-500 border-t border-gray-100">
																<span></span><span></span><span class="text-right">Anapara</span><span class="text-right">Faiz</span><span class="text-right">Taksit</span><span class="text-right">Durum</span>
															</div>
														</div>
													{/if}
												</div>
											{/each}
										</div>
									{/if}
								{/if}
							{:else}
								<!-- ── Bilgiler sekmesi ── -->
								<div class="mt-3.5 grid grid-cols-1 xl:grid-cols-2 gap-3">
									<div class="bg-white border border-gray-200 rounded-xl px-4 py-4">
										<div class="text-[10.5px] tracking-wide uppercase text-brass-dark font-bold mb-3">Maliyet &amp; Oranlar</div>
										{#each infoCost as r}
											<div class="flex items-center justify-between gap-3 py-1.5 border-b border-gray-100 last:border-0"><span class="text-[12.5px] text-gray-600 shrink-0">{r.k}</span><span class="tabular-nums text-[12.5px] text-gray-900 text-right min-w-0">{r.v}</span></div>
										{/each}
									</div>
									<div class="bg-white border border-gray-200 rounded-xl px-4 py-4">
										<div class="text-[10.5px] tracking-wide uppercase font-bold mb-3" style="color:#3a5573">Koşullar &amp; Teminat</div>
										{#each infoTerms as r}
											<div class="flex items-start justify-between gap-3 py-1.5 border-b border-gray-100 last:border-0"><span class="text-[12.5px] text-gray-600 shrink-0">{r.k}</span><span class="text-[12.5px] text-gray-900 text-right min-w-0 break-words">{r.v}</span></div>
										{/each}
									</div>
								</div>
							{/if}
						{/if}
					</div>
				</div>
			{/if}
		{/if}

		<!-- ═══ GÖRÜNÜM: TAKSİT TAKVİMİ ═══ -->
		{#if view === 'takvim'}
			<div class="px-4 sm:px-6 py-5">
				<h2 class="text-base sm:text-lg text-gray-900">Taksit Takvimi · 12 ay</h2>
				<p class="text-xs text-gray-500 mt-0.5 mb-4">Tüm aktif kredilerin taksitleri (ödenen + kalan) · ay ay · TL ve EUR ayrı toplanır</p>
				{#if loading}
					<TableSkeleton rows={6} columns={2} showHeader={false} />
				{:else if calMonths.length === 0}
					<EmptyState icon={CalendarDays} title="Yaklaşan taksit yok" description="Aktif kredilerin planlı taksiti bulunmuyor" />
				{:else}
					<div class="space-y-2">
						{#each calMonths as grp (grp.ym)}
							{@const open = openCalMonths.has(grp.ym)}
							<div class="border border-gray-200 rounded-xl overflow-hidden bg-white">
								<button type="button" onclick={() => toggleCalMonth(grp.ym)} class="w-full flex items-center gap-3 px-4 py-3 text-left cursor-pointer hover:bg-gray-50" aria-expanded={open}>
									<ChevronRight size={14} class="shrink-0 text-brass-dark transition-transform {open ? 'rotate-90' : ''}" />
									<span class="text-sm font-semibold text-gray-900 min-w-[96px]">{grp.label}</span>
									{#if grp.hasOverdue}
										<span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-red-50 text-red-700">Gecikmiş var</span>
									{:else}
										<span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-gray-100 text-gray-600">{grp.paidCount}/{grp.count} ödendi</span>
									{/if}
									<span class="flex-1"></span>
									<span class="text-right">
										{#if monthTotalLabel(grp.unpaidTotals)}
											<span class="block text-[9px] uppercase tracking-wide text-gray-500">Kalan</span>
											<span class="tabular-nums text-[13px] font-semibold text-gray-900">{monthTotalLabel(grp.unpaidTotals)}</span>
										{:else}
											<span class="tabular-nums text-[13px] font-semibold text-emerald-600">Tamamı ödendi</span>
										{/if}
									</span>
								</button>
								{#if open}
									<div>
										{#each grp.items as u (u.payment_id)}
											{@const overdue = !u.is_paid && u.due_date < TODAY_ISO}
											{@const isEur = u.currency === 'EUR'}
											<div class="grid grid-cols-[64px_1fr_auto_auto] sm:grid-cols-[72px_1.4fr_1fr_120px_96px] gap-x-3 items-center px-4 py-2.5 border-t border-gray-100 {u.is_paid ? 'bg-emerald-50/30' : ''}">
												<span class="tabular-nums text-[11.5px] text-gray-500">{fmtDate(u.due_date)}</span>
												<span class="flex items-center gap-2 min-w-0"><span class="w-2 h-2 rounded-sm shrink-0" style="background:{CUR_BAR(isEur)}"></span><span class="text-[12.5px] font-medium text-gray-900 truncate">{u.product_name}</span></span>
												<span class="text-[11.5px] text-gray-500 truncate hidden sm:block">{u.bank_name || ''}</span>
												<span class="tabular-nums text-right text-[13px] font-semibold" style="color:{CUR_TEXT(isEur)}">{fmt(u.amount, u.currency)}</span>
												<span class="text-right">
													<span class="text-[10px] font-semibold px-2 py-0.5 rounded {u.is_paid ? 'text-emerald-700 bg-emerald-50' : overdue ? 'text-red-700 bg-red-50' : 'text-brass-dark bg-brass-soft'}">{u.is_paid ? 'Ödendi' : overdue ? 'Gecikmiş' : 'Bekliyor'}</span>
												</span>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<!-- ═══ GÖRÜNÜM: BANKA DAĞILIMI ═══ -->
		{#if view === 'banka'}
			<div class="px-4 sm:px-6 py-5">
				<div class="flex items-baseline justify-between flex-wrap gap-2 mb-4">
					<div>
						<h2 class="text-base sm:text-lg text-gray-900">Banka Bazlı Kredi Dağılımı · EUR</h2>
						<p class="text-xs text-gray-500 mt-0.5">Her kredi kullandırım → vade çizgisi · vadeye yaklaştıkça kalınlaşır · tıkla → detay</p>
					</div>
					<div class="flex gap-3 text-[11px] text-gray-600">
						<span class="flex items-center gap-1.5"><span class="w-4 h-[5px] rounded-full" style="background:#bd9a45"></span>TL</span>
						<span class="flex items-center gap-1.5"><span class="w-4 h-[5px] rounded-full" style="background:#5b7fa6"></span>EUR</span>
						<span class="flex items-center gap-1.5"><span class="w-4 h-[5px] rounded-full bg-red-600"></span>Vadesi yakın</span>
					</div>
				</div>
				{#if loading}
					<TableSkeleton rows={4} columns={2} showHeader={false} />
				{:else if bankGroups.length === 0}
					<EmptyState icon={Landmark} title="Aktif kredi yok" description="Banka dağılımı için bakiyeli aktif kredi bulunmuyor" />
				{:else}
					<div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5">
						{#each bankGroups as g (g.bank)}
							<div class="bg-white border border-gray-200 rounded-2xl px-4 py-4">
								<div class="flex items-baseline justify-between mb-3.5">
									<div class="flex items-center gap-2.5 min-w-0">
										<span class="w-8 h-8 rounded-lg bg-teal-700 text-brass-light flex items-center justify-center font-serif font-semibold text-[13px] shrink-0">{g.initial}</span>
										<span class="text-sm font-semibold text-gray-900 truncate">{g.bank}</span>
									</div>
									<div class="text-right shrink-0 ml-2">
										<div class="tabular-nums text-sm font-semibold text-gray-900">{shortEur(g.totalEur)}</div>
										<div class="text-[10px] text-gray-500">{g.count} kredi{g.hasMissingRate ? ' · kur eksik' : ''}</div>
									</div>
								</div>
								<div class="space-y-3">
									{#each g.items as c (c.id)}
										{@const tl = creditTimeline(c)}
										{@const days = daysToNext(c)}
										{@const isEur = c.currency === 'EUR'}
										{@const zeroCard = c.type === 'kredi_karti' && (c.remaining_amount || 0) <= 0}
										{@const chip = zeroCard ? { label: 'borç yok', cls: 'text-gray-600 bg-gray-100' } : dueChip(days)}
										<button onclick={() => jumpToCredit(c)} class="w-full text-left cursor-pointer group">
											<div class="flex items-baseline justify-between gap-2 mb-1.5">
												<span class="text-xs text-gray-700 truncate group-hover:text-gray-900">{c.name}</span>
												<span class="tabular-nums text-[11.5px] shrink-0" style="color:{CUR_TEXT(isEur)}">{zeroCard ? fmt(c.total_amount, c.currency) : fmt(c.remaining_amount, c.currency)}{#if zeroCard}<span class="text-gray-500 font-normal"> limit</span>{/if}</span>
											</div>
											<div class="flex items-center gap-2">
												<span class="flex-1 relative h-2 bg-gray-200 rounded-full">
													{#if tl.hasVade && !zeroCard}
														<span class="absolute left-0 top-0 bottom-0 rounded-full {(isEur ? TIER_FILL_EUR : TIER_FILL)[tl.tier]}" style="width:{Math.max(4, tl.progress * 100)}%"></span>
														<span class="absolute -top-0.5 -bottom-0.5 w-0.5 rounded-full bg-gray-900" style="left:{tl.progress * 100}%"></span>
													{:else}
														<span class="absolute left-0 top-0 bottom-0 rounded-full bg-gray-300" style="width:60%"></span>
													{/if}
												</span>
												<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap {chip.cls}">{chip.label}</span>
											</div>
										</button>
									{/each}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

	</div>
</div>

<!-- ═══ Snippet: KMH görünümü ═══ -->
{#snippet kmhView(p: any)}
	{#if !kmhStatus}
		<div class="mt-4"><TableSkeleton rows={4} columns={2} showHeader={false} /></div>
	{:else if kmhStatus.error}
		<div class="mt-4 bg-red-50 border border-red-200 text-red-700 rounded-lg p-3 text-sm">
			{kmhStatus.error}
			{#if kmhStatus.error?.includes('linked_account_id')}
				<br /><span class="text-xs">→ "Düzenle" ile bu KMH'ye bağlı banka hesabını seçin.</span>
			{/if}
		</div>
	{:else}
		{@const cur = kmhStatus.current_period}
		<div class="grid grid-cols-2 xl:grid-cols-4 gap-2.5 mt-4 mb-4">
			<div class="bg-white border border-gray-200 rounded-xl p-3">
				<div class="text-[10px] text-gray-500 uppercase tracking-wide">Açık Borç</div>
				<div class="tabular-nums text-lg font-bold {kmhStatus.current_debt > 0 ? 'text-red-600' : 'text-gray-700'} mt-0.5">{fmt(kmhStatus.current_debt)}</div>
				<div class="text-[10px] text-gray-500 mt-0.5">Kullan. limit: {fmt(kmhStatus.available_limit)}</div>
			</div>
			<div class="bg-white border border-gray-200 rounded-xl p-3">
				<div class="text-[10px] text-gray-500 uppercase tracking-wide">Bu Çeyrek Adat</div>
				<div class="tabular-nums text-lg font-bold text-gray-700 mt-0.5">{cur ? fmt(cur.past_adat) : '0'}</div>
				<div class="text-[10px] text-gray-500 mt-0.5">{cur?.period_start ?? ''} → bugün</div>
			</div>
			<div class="bg-white border border-gray-200 rounded-xl p-3">
				<div class="text-[10px] text-gray-500 uppercase tracking-wide">Bu Çeyrek Birikmiş</div>
				<div class="tabular-nums text-lg font-bold text-brass-dark mt-0.5">{cur ? fmt(cur.accrued_total) : '0'}</div>
				<div class="text-[10px] text-gray-500 mt-0.5">Faiz {cur ? fmt(cur.accrued_interest) : '0'} + BSMV+Kom.</div>
			</div>
			<div class="bg-white border border-gray-200 rounded-xl p-3 border-l-4 border-l-teal-600">
				<div class="text-[10px] text-gray-500 uppercase tracking-wide">Tahmini Çeyrek Sonu</div>
				<div class="tabular-nums text-lg font-bold text-teal-700 mt-0.5">{cur ? fmt(cur.projected_total_due) : '0'}</div>
				<div class="text-[10px] text-gray-500 mt-0.5">Tüm çeyrekler: {fmt(kmhStatus.total_projected)} ₺</div>
			</div>
		</div>
		<div class="text-xs text-gray-500 mb-3 px-1">
			Yıllık faiz: <span class="font-semibold">%{kmhStatus.interest_rate}</span> · BSMV: %{kmhStatus.bsmv_rate} · Komisyon: %{kmhStatus.commission_rate} · Limit: <span class="font-semibold">{fmt(kmhStatus.limit)}</span>
		</div>
		{#if kmhStatus.periods && kmhStatus.periods.length > 0}
			<div class="bg-white border border-gray-200 rounded-xl overflow-hidden mb-4">
				<div class="px-3 py-2 border-b border-gray-100 bg-gray-50">
					<span class="text-xs font-semibold text-gray-700">Çeyreklik Tahakkuklar ({kmhStatus.periods.length} çeyrek)</span>
					<span class="text-[10px] text-gray-500 ml-2">Toplam birikmiş: <span class="font-semibold text-brass-dark">{fmt(kmhStatus.total_accrued)} ₺</span> · Toplam tahmini: <span class="font-semibold text-teal-700">{fmt(kmhStatus.total_projected)} ₺</span></span>
				</div>
				<div class="overflow-x-auto">
					<table class="w-full text-xs">
						<thead class="bg-gray-50 text-[10px] text-gray-500 uppercase tracking-wide">
							<tr>
								<th class="text-left px-3 py-1.5">Çeyrek</th><th class="text-right px-3 py-1.5">Devir Bakiye</th>
								<th class="text-right px-3 py-1.5">Adat (geçmiş)</th><th class="text-right px-3 py-1.5">Adat (proj.)</th>
								<th class="text-right px-3 py-1.5">Faiz</th><th class="text-right px-3 py-1.5">BSMV</th>
								<th class="text-right px-3 py-1.5">Komisyon</th><th class="text-right px-3 py-1.5">Toplam</th>
							</tr>
						</thead>
						<tbody>
							{#each kmhStatus.periods as pp}
								<tr class="border-t border-gray-100 {pp.is_current ? 'bg-teal-50/50 font-medium' : ''}">
									<td class="px-3 py-1.5 text-gray-700 whitespace-nowrap">{pp.month_label}{#if pp.is_current}<span class="text-[10px] text-teal-700 ml-1">[bu çeyrek]</span>{/if}</td>
									<td class="px-3 py-1.5 text-right tabular-nums {pp.carry_balance < 0 ? 'text-red-600' : 'text-gray-500'} whitespace-nowrap">{fmt(pp.carry_balance)}</td>
									<td class="px-3 py-1.5 text-right tabular-nums text-gray-700 whitespace-nowrap">{fmt(pp.past_adat)}</td>
									<td class="px-3 py-1.5 text-right tabular-nums text-gray-500 whitespace-nowrap">{pp.future_adat > 0 ? '+' + fmt(pp.future_adat) : '—'}</td>
									<td class="px-3 py-1.5 text-right tabular-nums text-brass-dark whitespace-nowrap">{fmt(pp.is_current ? pp.projected_interest : pp.accrued_interest)}</td>
									<td class="px-3 py-1.5 text-right tabular-nums text-gray-600 whitespace-nowrap">{fmt(pp.is_current ? pp.projected_bsmv : pp.accrued_bsmv)}</td>
									<td class="px-3 py-1.5 text-right tabular-nums text-gray-600 whitespace-nowrap">{fmt(pp.is_current ? pp.projected_commission : pp.accrued_commission)}</td>
									<td class="px-3 py-1.5 text-right tabular-nums font-semibold {pp.is_current ? 'text-teal-700' : 'text-gray-800'} whitespace-nowrap">{fmt(pp.is_current ? pp.projected_total_due : pp.accrued_total)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
		<div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
			<div class="px-3 py-2 border-b border-gray-100 bg-gray-50">
				<span class="text-xs font-semibold text-gray-700">{cur?.month_label} hareketleri ({cur?.movements?.length || 0}{cur?.carry_date ? ' + devir' : ''})</span>
			</div>
			<div class="overflow-x-auto">
				<table class="w-full text-xs">
					<thead class="bg-gray-50 text-[10px] text-gray-500 uppercase tracking-wide">
						<tr><th class="text-left px-3 py-1.5">Tarih</th><th class="text-left px-3 py-1.5">Açıklama</th><th class="text-right px-3 py-1.5">Tutar</th><th class="text-right px-3 py-1.5">Bakiye</th><th class="text-center px-3 py-1.5">Durum</th></tr>
					</thead>
					<tbody>
						{#if cur?.carry_date}
							<tr class="border-t border-gray-100 bg-brass-soft/40">
								<td class="px-3 py-1.5 text-gray-600 whitespace-nowrap">{fmtDate(cur.carry_date)}</td>
								<td class="px-3 py-1.5 text-gray-500 italic truncate max-w-md" title={cur.carry_description}><CornerDownLeft size={11} class="inline-block mr-1 align-middle" />Devir bakiye — {cur.carry_description}</td>
								<td class="px-3 py-1.5 text-right text-gray-500">—</td>
								<td class="px-3 py-1.5 text-right tabular-nums {cur.carry_balance < 0 ? 'text-red-600 font-semibold' : 'text-gray-600'} whitespace-nowrap">{fmt(cur.carry_balance)}</td>
								<td class="px-3 py-1.5 text-center">{#if cur.carry_balance < 0}<span class="text-[10px] font-medium bg-red-50 text-red-700 px-1.5 py-0.5 rounded">KMH Kullanım</span>{:else}<span class="text-[10px] font-medium bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">Devir</span>{/if}</td>
							</tr>
						{/if}
						{#if (!cur?.movements || cur.movements.length === 0) && !cur?.carry_date}
							<tr><td colspan="5" class="text-center text-xs text-gray-500 py-4">Bu period'da hareket yok.</td></tr>
						{/if}
						{#each (cur?.movements || []) as mv (mv.id)}
							<tr class="border-t border-gray-100">
								<td class="px-3 py-1.5 text-gray-600 whitespace-nowrap">{fmtDate(mv.date)}</td>
								<td class="px-3 py-1.5 text-gray-600 truncate max-w-md" title={mv.description}>{mv.description}</td>
								<td class="px-3 py-1.5 text-right tabular-nums font-medium {mv.amount < 0 ? 'text-red-600' : 'text-emerald-600'} whitespace-nowrap">{mv.amount > 0 ? '+' : ''}{fmt(mv.amount)}</td>
								<td class="px-3 py-1.5 text-right tabular-nums {mv.balance_after !== null && mv.balance_after < 0 ? 'text-red-600 font-semibold' : 'text-gray-600'} whitespace-nowrap">{mv.balance_after !== null ? fmt(mv.balance_after) : '—'}</td>
								<td class="px-3 py-1.5 text-center">{#if mv.kmh_state === 'negatif'}<span class="text-[10px] font-medium bg-red-50 text-red-700 px-1.5 py-0.5 rounded">KMH Kullanım</span>{:else if mv.kmh_state === 'pozitif'}<span class="text-[10px] font-medium bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded">Pozitif</span>{:else}<span class="text-[10px] text-gray-500">—</span>{/if}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if cur?.carry_balance < 0 && cur?.carry_date}
				<div class="px-3 py-2 border-t border-gray-100 bg-brass-soft text-[11px] text-brass-dark flex items-start gap-1.5">
					<Info size={14} class="shrink-0 mt-0.5" />
					<span><strong>Adat'a etki:</strong> Devir bakiye <strong>{fmt(Math.abs(cur.carry_balance))} ₺</strong> negatif olduğundan period başlangıcından (<strong>{fmtDate(cur.period_start)}</strong>) itibaren günlük adat'a eklenir.</span>
				</div>
			{/if}
		</div>
	{/if}
{/snippet}

<!-- ═══ Snippet: Kredi kartı ekstre görünümü ═══ -->
{#snippet cardView(p: any)}
	{#if canUse}
		<div class="relative mt-3.5 mb-3">
			<LoadingOverlay show={ccUploading} message="Ekstre yükleniyor..." />
			<FileDropzone accept=".pdf" maxSize={50 * 1024 * 1024} multiple={true} disabled={ccUploading}
				label="Kredi kartı ekstresini sürükleyip bırakın" hint="PDF formatında — kart otomatik algılanır"
				onSelect={handleCCFileSelect} onError={handleCCDropError} />
			{#if ccUploadError}<p class="text-xs text-red-600 mt-2">{ccUploadError}</p>{/if}
			{#if ccUploadSuccess}<p class="inline-flex items-center gap-1 text-xs text-teal-700 mt-2"><CheckCircle2 size={14} /> {ccUploadSuccess}</p>{/if}
		</div>
	{/if}
	{#if ccStatements.length === 0}
		<div class="mt-2 bg-white border border-dashed border-gray-300 rounded-xl px-6 py-8 text-center text-gray-500 text-sm">Henüz yüklenmiş ekstre yok</div>
	{:else}
		<div class="mt-2 space-y-2">
			{#each ccStatements as stmt (stmt.id)}
				{@const st = getStmtStatus(stmt)}
				<div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
					<div onclick={() => toggleCCStmtExpand(p.id, stmt.id)} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleCCStmtExpand(p.id, stmt.id); } }}
						role="button" tabindex="0" aria-expanded={ccExpandedStmtId === stmt.id}
						class="w-full flex items-center gap-2 sm:gap-3 px-3 py-2.5 hover:bg-gray-50 cursor-pointer text-sm flex-wrap sm:flex-nowrap">
						<ChevronRight size={14} class="shrink-0 text-gray-500 transition-transform {ccExpandedStmtId === stmt.id ? 'rotate-90' : ''}" />
						<span class="text-gray-600"><span class="font-medium">{fmtDate(stmt.kesim_tarihi)}</span><span class="text-xs text-gray-500 ml-1 hidden sm:inline">kesim</span></span>
						<span class="text-gray-600 hidden sm:inline"><span class="text-xs text-gray-500">son ödeme:</span><span class="font-medium ml-1">{fmtDate(stmt.son_odeme_tarihi)}</span></span>
						<span class="flex-1"></span>
						<span class="text-xs text-gray-500 hidden sm:inline">{stmt.transaction_count} işlem</span>
						<span class="tabular-nums font-bold text-gray-900 whitespace-nowrap">{fmt(stmt.toplam_borc)}</span>
						<span class="text-[10px] font-medium {st.bg} {st.text} px-2 py-0.5 rounded-full">{st.label}</span>
						{#if canUse}
							<button onclick={(e) => { e.stopPropagation(); deleteCCStatement(p.id, stmt.id); }} class="text-red-500 hover:text-red-600 cursor-pointer ml-1" title="Sil" aria-label="Ekstreyi sil"><X size={14} /></button>
						{/if}
					</div>
					{#if ccExpandedStmtId === stmt.id && ccExpandedStmt}
						<div class="border-t border-gray-100 bg-gray-50 px-3 py-3">
							<div class="grid grid-cols-2 xl:grid-cols-4 gap-3 mb-4">
								<div class="bg-white rounded-lg p-2.5 border border-gray-100"><div class="text-[10px] text-gray-500">Önceki Bakiye</div><div class="tabular-nums text-sm font-semibold text-gray-700">{fmt(ccExpandedStmt.onceki_bakiye)}</div></div>
								<div class="bg-white rounded-lg p-2.5 border border-gray-100"><div class="text-[10px] text-gray-500">Dönem Harcama</div><div class="tabular-nums text-sm font-semibold text-red-600">{fmt(ccExpandedStmt.donem_harcama)}</div></div>
								<div class="bg-white rounded-lg p-2.5 border border-gray-100"><div class="text-[10px] text-gray-500">Faiz / Ücret</div><div class="tabular-nums text-sm font-semibold text-orange-600">{fmt(ccExpandedStmt.faiz_ucret)}</div></div>
								<div class="bg-white rounded-lg p-2.5 border border-gray-100"><div class="text-[10px] text-gray-500">Dönem Ödeme</div><div class="tabular-nums text-sm font-semibold text-emerald-600">{fmt(ccExpandedStmt.donem_odeme)}</div></div>
							</div>
							{#if ccExpandedStmt.transactions && ccExpandedStmt.transactions.length > 0}
								<div class="overflow-x-auto">
									<table class="w-full text-sm">
										<thead><tr class="text-xs text-gray-500 border-b border-gray-200"><th class="text-left py-1.5 px-2">Tarih</th><th class="text-left py-1.5 px-2">Açıklama</th><th class="text-left py-1.5 px-2 hidden sm:table-cell">Kategori</th><th class="text-left py-1.5 px-2 hidden md:table-cell">Taksit</th><th class="text-right py-1.5 px-2">Tutar</th></tr></thead>
										<tbody>
											{#each ccExpandedStmt.transactions as tx (tx.id)}
												<tr class="border-b border-gray-100 hover:bg-white/60">
													<td class="py-1.5 px-2 text-gray-500 whitespace-nowrap">{tx.islem_tarihi ? fmtDate(tx.islem_tarihi) : '—'}</td>
													<td class="py-1.5 px-2 text-gray-700 max-w-[200px] truncate" title={tx.aciklama}>{tx.aciklama}</td>
													<td class="py-1.5 px-2 text-gray-500 text-xs hidden sm:table-cell">{tx.kategori || '—'}</td>
													<td class="py-1.5 px-2 text-gray-500 text-xs hidden md:table-cell max-w-[150px] truncate" title={tx.taksit_bilgi || ''}>{tx.taksit_bilgi || '—'}</td>
													<td class="py-1.5 px-2 text-right tabular-nums font-medium whitespace-nowrap {tx.is_credit ? 'text-emerald-600' : 'text-red-600'}">{tx.is_credit ? '+' : '-'}{fmt(tx.tutar)}</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{:else}
								<p class="text-sm text-gray-500 text-center py-3">İşlem bulunamadı</p>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
{/snippet}

<!-- ═══ Modallar ═══ -->
<Modal bind:show={showAddModal} title={editProduct ? 'Krediyi Düzenle' : 'Yeni Kredi Ürünü'} maxWidth="max-w-xl">
	<form onsubmit={(e) => { e.preventDefault(); saveProduct(); }} class="space-y-4">
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div>
				<label for="k-type" class="text-xs text-gray-500 mb-1 block">Tip</label>
				<Select id="k-type" bind:value={form.type} size="sm" disabled={!!editProduct}>
					{#each PRODUCT_TYPES as t}<option value={t}>{TYPE_LABELS[t]}</option>{/each}
				</Select>
			</div>
			<div>
				<label for="k-currency" class="text-xs text-gray-500 mb-1 block">Para Birimi</label>
				<Select id="k-currency" bind:value={form.currency} size="sm"><option value="TRY">TRY</option><option value="USD">USD</option><option value="EUR">EUR</option></Select>
			</div>
		</div>
		<div>
			<label for="k-name" class="text-xs text-gray-500 mb-1 block">Ürün Adı <span class="text-red-500">*</span></label>
			<Input id="k-name" bind:value={form.name} size="sm" placeholder="ör: Ziraat TL Taksitli Kredi" required />
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div>
				<label for="k-bank" class="text-xs text-gray-500 mb-1 block">Banka</label>
				<Input id="k-bank" bind:value={form.bank_name} size="sm" placeholder="Banka adı" />
			</div>
			{#if form.type === 'leasing'}
				<div>
					<label for="k-company" class="text-xs text-gray-500 mb-1 block">Kurum</label>
					<Input id="k-company" bind:value={form.company} size="sm" placeholder="Leasing şirketi" />
				</div>
			{/if}
		</div>
		<div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
			<div><label for="k-total" class="text-xs text-gray-500 mb-1 block">Toplam Tutar</label><MoneyInput id="k-total" bind:value={form.total_amount} currency={form.currency} min={0} placeholder="0,00" /></div>
			<div><label for="k-remaining" class="text-xs text-gray-500 mb-1 block">Kalan Borç</label><MoneyInput id="k-remaining" bind:value={form.remaining_amount} currency={form.currency} min={0} placeholder="0,00" /></div>
			<div><label for="k-interest" class="text-xs text-gray-500 mb-1 block">Faiz Oranı (%)</label><MoneyInput id="k-interest" bind:value={form.interest_rate} decimals={2} min={0} placeholder="ör: 2,45" /></div>
			<div><label for="k-bsmv" class="text-xs text-gray-500 mb-1 block">BSMV Oranı (%)</label><MoneyInput id="k-bsmv" bind:value={form.bsmv_rate} decimals={2} min={0} placeholder="ör: 5" /></div>
			<div><label for="k-commission" class="text-xs text-gray-500 mb-1 block">Komisyon Oranı (%)</label><MoneyInput id="k-commission" bind:value={form.commission_rate} decimals={2} min={0} placeholder="ör: 1" /></div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div><label for="k-start" class="text-xs text-gray-500 mb-1 block">Başlangıç</label><Input id="k-start" type="date" bind:value={form.start_date} size="sm" /></div>
			<div><label for="k-end" class="text-xs text-gray-500 mb-1 block">Bitiş / Vade</label><Input id="k-end" type="date" bind:value={form.end_date} size="sm" /></div>
		</div>
		<div>
			<label for="k-teminat" class="text-xs text-gray-500 mb-1 block">Teminat</label>
			<Input id="k-teminat" bind:value={form.details.teminat} size="sm" placeholder="ör: Otel A blok ipoteği" />
		</div>
		<div>
			<label for="k-notes" class="text-xs text-gray-500 mb-1 block">Notlar</label>
			<Textarea id="k-notes" bind:value={form.notes} rows={2} placeholder="Opsiyonel notlar" />
		</div>
		<div class="flex justify-end gap-2 pt-2">
			<Button type="button" variant="secondary" onclick={() => showAddModal = false}>İptal</Button>
			<Button type="submit">Kaydet</Button>
		</div>
	</form>
</Modal>

<Modal bind:show={showPaymentModal} title="Taksit Planı Oluştur" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); generatePayments(); }} class="space-y-4">
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div><label for="kp-count" class="text-xs text-gray-500 mb-1 block">Taksit Sayısı <span class="text-red-500">*</span></label><Input id="kp-count" type="number" min="1" max="120" bind:value={paymentForm.count} size="sm" required /></div>
			<div><label for="kp-start" class="text-xs text-gray-500 mb-1 block">İlk Taksit Tarihi <span class="text-red-500">*</span></label><Input id="kp-start" type="date" bind:value={paymentForm.start_date} size="sm" required /></div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div><label for="kp-amount" class="text-xs text-gray-500 mb-1 block">Taksit Tutarı <span class="text-red-500">*</span></label><MoneyInput id="kp-amount" bind:value={paymentForm.amount} currency={selected?.currency || 'TRY'} min={0} placeholder="0,00" required /></div>
			<div><label for="kp-principal" class="text-xs text-gray-500 mb-1 block">Anapara</label><MoneyInput id="kp-principal" bind:value={paymentForm.principal} currency={selected?.currency || 'TRY'} min={0} placeholder="0,00" /></div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div><label for="kp-interest" class="text-xs text-gray-500 mb-1 block">Faiz</label><MoneyInput id="kp-interest" bind:value={paymentForm.interest} currency={selected?.currency || 'TRY'} min={0} placeholder="0,00" /></div>
			<div><label for="kp-tax" class="text-xs text-gray-500 mb-1 block">Vergi (BSMV/KKDF)</label><MoneyInput id="kp-tax" bind:value={paymentForm.tax} currency={selected?.currency || 'TRY'} min={0} placeholder="0,00" /></div>
		</div>
		<div class="flex justify-end gap-2 pt-2">
			<Button type="button" variant="secondary" onclick={() => showPaymentModal = false}>İptal</Button>
			<Button type="submit">{paymentForm.count} Taksit Oluştur</Button>
		</div>
	</form>
</Modal>

<Modal bind:show={closeModal.show} title="Krediyi Kapat" maxWidth="max-w-md">
	<div class="space-y-4 text-sm">
		<div class="bg-gray-100 border border-gray-200 rounded-lg p-3 text-gray-700 text-xs leading-snug">
			<strong>{closeModal.name}</strong> kapatılacak. Ödenmemiş ileri vadeli taksitler nakit akım tablosundan çıkarılır (taksit kayıtları referans için korunur). İşlem <strong>Yeniden Aç</strong> ile geri alınabilir.
		</div>
		<div><label for="close-date" class="text-xs text-gray-500 mb-1 block">Kapanış Tarihi</label><Input id="close-date" type="date" bind:value={closeModal.closedDate} size="sm" /></div>
		<div class="flex items-center justify-end gap-2 pt-2">
			<Button variant="secondary" onclick={() => (closeModal = { show: false, id: null, name: '', closedDate: TODAY_ISO })}>Vazgeç</Button>
			<Button onclick={confirmClose}>Krediyi Kapat</Button>
		</div>
	</div>
</Modal>

<ConfirmDialog bind:show={confirmState.show} title={confirmState.title} message={confirmState.message} confirmText={confirmState.confirmText} cancelText="Vazgeç" danger={confirmState.danger} onConfirm={confirmState.onConfirm} />

<PdfPreviewModal bind:this={pdfModal} />
