<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { CreditCard, ChevronRight, FileDown, Plus, Loader2, CheckCircle2, Info, RotateCcw, Check, X, CornerDownLeft } from 'lucide-svelte';
	import Button from '$lib/components/Button.svelte';
	import StatCard, { type StatAccent } from '$lib/components/StatCard.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import type { LatestRates } from '$lib/types/exchange-rate';

	// Generic silme onayı state
	let confirmState = $state<{ show: boolean; title: string; message: string; onConfirm: () => void | Promise<void> }>({
		show: false, title: '', message: '', onConfirm: () => {}
	});
	function askDelete(title: string, message: string, onConfirm: () => void | Promise<void>) {
		confirmState = { show: true, title, message, onConfirm };
	}

	const TYPE_LABELS: Record<string, string> = {
		kredi_karti: 'Kredi Kartı',
		kmh: 'KMH',
		bch: 'BCH',
		spot_kredi: 'Spot Kredi',
		taksitli_kredi: 'Taksitli Kredi',
		leasing: 'Leasing',
	};
	const TYPE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
		kredi_karti: { bg: 'bg-pink-50', text: 'text-pink-700', border: 'border-pink-200' },
		kmh: { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' },
		bch: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
		spot_kredi: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
		taksitli_kredi: { bg: 'bg-teal-50', text: 'text-teal-700', border: 'border-teal-200' },
		leasing: { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
	};
	const PRODUCT_TYPES = Object.keys(TYPE_LABELS);

	// Tip → StatCard aksan rengi (StatCard paleti: teal/emerald/amber/red/blue/gray)
	const TYPE_ACCENT: Record<string, StatAccent> = {
		kredi_karti: 'red',
		kmh: 'amber',
		bch: 'amber',
		spot_kredi: 'blue',
		taksitli_kredi: 'teal',
		leasing: 'blue',
	};

	let canUse = $derived(hasPermission('finance.krediler', 'use'));

	// State
	let products = $state<any[]>([]);
	let summary = $state<any[]>([]);
	let upcoming = $state<any[]>([]);
	let latestRates = $state<LatestRates | null>(null);
	let loading = $state(true);
	let expandedId = $state<number | null>(null);
	let expandedPayments = $state<any[]>([]);
	let expandedMonths = $state<Set<string>>(new Set());  // Ödeme planı akordiyonunda açık aylar (YYYY-MM)

	// Ödeme planı popup (banka kartından krediye tıklanınca açılır)
	let planModal = $state<{ show: boolean; product: any | null; payments: any[]; loading: boolean }>({
		show: false, product: null, payments: [], loading: false,
	});
	let typeFilter = $state('');
	let statusFilter = $state('active');
	let pdfLoading = $state(false);

	// Kapatma modal state
	let closeModal = $state<{ show: boolean; id: number | null; name: string; closedDate: string }>({
		show: false, id: null, name: '', closedDate: new Date().toISOString().split('T')[0],
	});

	// CC Statement state
	let ccStatements = $state<any[]>([]);
	let ccExpandedStmtId = $state<number | null>(null);
	let ccExpandedStmt = $state<any>(null);
	let ccUploading = $state(false);
	let ccUploadError = $state('');
	let ccUploadSuccess = $state('');

	// Modal state
	let showAddModal = $state(false);
	let editProduct = $state<any>(null);
	let form = $state<{
		type: string;
		name: string;
		bank_name: string;
		company: string;
		currency: string;
		total_amount: number | null;
		remaining_amount: number | null;
		interest_rate: number | null;
		bsmv_rate: number | null;
		commission_rate: number | null;
		start_date: string;
		end_date: string;
		notes: string;
		details: Record<string, any>;
	}>({
		type: 'kredi_karti',
		name: '',
		bank_name: '',
		company: '',
		currency: 'TRY',
		total_amount: null,
		remaining_amount: null,
		interest_rate: null,
		bsmv_rate: null,
		commission_rate: null,
		start_date: '',
		end_date: '',
		notes: '',
		details: {},
	});

	// Payment modal
	let showPaymentModal = $state(false);
	let paymentProductId = $state<number | null>(null);
	let paymentForm = $state<{
		count: number;
		start_date: string;
		amount: number | null;
		principal: number | null;
		interest: number | null;
		tax: number | null;
	}>({
		count: 12,
		start_date: '',
		amount: null,
		principal: null,
		interest: null,
		tax: null,
	});

	function fmt(n: number | null | undefined, currency = 'TRY'): string {
		if (n == null) return '-';
		const symbols: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$' };
		const sym = symbols[currency] || currency;
		return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ' + sym;
	}

	function fmtDate(d: string | null): string {
		if (!d) return '-';
		const [y, m, day] = d.split('-');
		return `${day}.${m}.${y}`;
	}

	function fmtCompact(n: number | null | undefined, currency = 'TRY'): string {
		if (n == null) return '-';
		const symbols: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$' };
		const sym = symbols[currency] || currency;
		const abs = Math.abs(n);
		if (abs >= 1_000_000) return (n / 1_000_000).toFixed(3).replace('.', ',') + 'M ' + sym;
		if (abs >= 1_000) return (n / 1_000).toFixed(3).replace('.', ',') + 'K ' + sym;
		return n.toFixed(0) + ' ' + sym;
	}

	// Döviz kurları (EUR'a çevirmek için)
	let eurRate = $derived(latestRates?.rates.find(r => r.currency_code === 'EUR')?.forex_selling ?? null);
	let usdRate = $derived(latestRates?.rates.find(r => r.currency_code === 'USD')?.forex_selling ?? null);
	let gbpRate = $derived(latestRates?.rates.find(r => r.currency_code === 'GBP')?.forex_selling ?? null);

	/** Kaynak para birimindeki tutarı EUR'a çevirir. Kur yoksa null döner. */
	function toEur(amount: number | null | undefined, currency: string): number | null {
		if (amount == null || !amount) return null;
		if (currency === 'EUR') return amount;
		if (!eurRate) return null;
		if (currency === 'TRY') return amount / eurRate;
		if (currency === 'USD' && usdRate) return (amount * usdRate) / eurRate;
		if (currency === 'GBP' && gbpRate) return (amount * gbpRate) / eurRate;
		return null;
	}

	// Banka bazlı gruplama — tüm para birimleri birlikte, toplam EUR cinsinden
	let bankGroups = $derived.by(() => {
		const groups: Record<string, any[]> = {};
		for (const p of products) {
			const amount = p.remaining_amount || 0;
			if (amount <= 0) continue;
			const bank = p.bank_name || p.company || 'Atanmamış';
			if (!groups[bank]) groups[bank] = [];
			groups[bank].push(p);
		}
		return Object.entries(groups)
			.map(([bank, items]) => {
				const enriched = items.map(p => ({
					...p,
					_eur: toEur(p.remaining_amount, p.currency || 'TRY'),
				}));
				const totalEur = enriched.reduce((s, it) => s + (it._eur || 0), 0);
				return {
					bank,
					// Vadesi yaklaşan en üstte (end_date artan); vadesizler (kredi kartı/rotatif) en sonda, tutara göre
					items: enriched.sort((a, b) => {
						const ae = a.end_date || '9999-12-31';
						const be = b.end_date || '9999-12-31';
						if (ae !== be) return ae < be ? -1 : 1;
						return (b._eur || 0) - (a._eur || 0);
					}),
					totalEur,
					hasMissingRate: enriched.some(it => it._eur == null),
				};
			})
			.filter(g => g.totalEur > 0)
			.sort((a, b) => b.totalEur - a.totalEur);
	});

	// Vade yakınlığına göre çizgi stili (vadeye yaklaştıkça daha kalın + kontrast).
	// TRY kredileri: teal→amber→turuncu→kırmızı rampa. EUR kredileri: mavi rampa (döviz ayrımı).
	const TIER_FILL: Record<string, string> = {
		ok: 'bg-teal-400 h-[3px]',
		soon: 'bg-amber-400 h-[5px]',
		urgent: 'bg-orange-500 h-[7px]',
		overdue: 'bg-red-600 h-[8px]',
	};
	const TIER_DOT: Record<string, string> = {
		ok: 'bg-teal-500', soon: 'bg-amber-500', urgent: 'bg-orange-600', overdue: 'bg-red-700',
	};
	const TIER_TEXT: Record<string, string> = {
		ok: 'text-teal-600', soon: 'text-amber-600', urgent: 'text-orange-600', overdue: 'text-red-700',
	};
	// EUR kredileri mavi gösterilir (kalınlık yine aciliyete göre artar)
	const TIER_FILL_EUR: Record<string, string> = {
		ok: 'bg-blue-400 h-[3px]',
		soon: 'bg-blue-500 h-[5px]',
		urgent: 'bg-blue-600 h-[7px]',
		overdue: 'bg-blue-700 h-[8px]',
	};
	const TIER_DOT_EUR: Record<string, string> = {
		ok: 'bg-blue-500', soon: 'bg-blue-600', urgent: 'bg-blue-700', overdue: 'bg-blue-800',
	};
	const TIER_TEXT_EUR: Record<string, string> = {
		ok: 'text-blue-600', soon: 'text-blue-600', urgent: 'text-blue-700', overdue: 'text-blue-800',
	};

	/** Kredinin açılış→vade zaman çizgisi: ilerleme oranı (bugüne kadar) + vadeye kalan gün + aciliyet kademesi. */
	function creditTimeline(p: any) {
		if (!p.end_date) return { hasVade: false, progress: 0, daysToDue: 0, tier: 'ok' };
		const end = new Date(p.end_date + 'T00:00:00');
		const today = new Date(); today.setHours(0, 0, 0, 0);
		const start = p.start_date ? new Date(p.start_date + 'T00:00:00') : new Date(end.getTime() - 365 * 864e5);
		const total = Math.max(end.getTime() - start.getTime(), 1);
		const progress = Math.min(Math.max((today.getTime() - start.getTime()) / total, 0), 1);
		const daysToDue = Math.round((end.getTime() - today.getTime()) / 864e5);
		const tier = daysToDue <= 0 ? 'overdue' : daysToDue <= 30 ? 'urgent' : daysToDue <= 90 ? 'soon' : 'ok';
		return { hasVade: true, progress, daysToDue, tier };
	}

	// Banka kartındaki krediye tıklanınca ödeme planını popup olarak aç
	async function openPlanModal(p: any) {
		planModal.product = p;
		planModal.payments = [];
		planModal.loading = true;
		planModal.show = true;
		try {
			const res = await api.get<{ payments?: any[] }>(`/finance/krediler/${p.id}`);
			planModal.payments = (res.payments || []).slice()
				.sort((a, b) => (a.due_date || '').localeCompare(b.due_date || ''));
		} catch (e) {
			console.error('Ödeme planı yüklenemedi:', e);
			showToast('Ödeme planı yüklenemedi', 'error');
		} finally {
			planModal.loading = false;
		}
	}

	// Popup içinde taksiti ödendi/ödenmedi olarak işaretle (kalan borcu da tazeler)
	async function togglePaymentInModal(pay: any) {
		if (!canUse) return;
		await togglePaid(pay);
		const fresh = products.find((pr: any) => pr.id === planModal.product?.id);
		if (fresh) planModal.product = { ...planModal.product, remaining_amount: fresh.remaining_amount };
	}

	async function loadData() {
		loading = true;
		try {
			const params = new URLSearchParams();
			params.set('page_size', '200');
			if (typeFilter) params.set('type_filter', typeFilter);
			if (statusFilter) params.set('status', statusFilter);

			const [prodRes, sumRes, upRes, ratesRes] = await Promise.all([
				api.get<{ items?: any[] }>(`/finance/krediler/?${params}`),
				api.get<any[]>('/finance/krediler/summary/by-type'),
				api.get<any[]>('/finance/krediler/upcoming-payments?days=365&include_paid=true'),
				api.get<LatestRates>('/finance/exchange-rates/latest').catch(() => null),
			]);
			products = prodRes.items || [];
			summary = sumRes || [];
			upcoming = upRes || [];
			latestRates = ratesRes;

			// Tüm kredi kartlarının son ekstrelerini yükle (gri arka plan kontrolü için)
			const cardIds = products.filter((p: any) => p.type === 'kredi_karti').map((p: any) => p.id);
			const allStmts: any[] = [];
			for (const cid of cardIds) {
				try {
					const stmts = await api.get<any[]>(`/finance/krediler/kart/${cid}/statements`);
					if (stmts && stmts.length > 0) {
						allStmts.push(...stmts.map((s: any) => ({ ...s, credit_product_id: cid })));
					}
				} catch (err) { console.error('Kredi kartı ekstre yükleme hatası (id=' + cid + '):', err); }
			}
			ccStatements = allStmts;
		} catch (e) {
			console.error('Krediler yükleme hatası:', e);
		}
		loading = false;
	}

	let kmhStatus = $state<any>(null);

	async function toggleExpand(id: number, productType: string) {
		if (expandedId === id) {
			expandedId = null;
			ccStatements = [];
			ccExpandedStmtId = null;
			ccExpandedStmt = null;
			kmhStatus = null;
			return;
		}
		try {
			const res = await api.get<{ payments?: any[] }>(`/finance/krediler/${id}`);
			expandedPayments = res.payments || [];
			expandedId = id;
			initExpandedMonths();

			// Kredi kartı ise ekstreleri de yükle
			if (productType === 'kredi_karti') {
				await loadCCStatements(id);
				kmhStatus = null;
			} else if (productType === 'kmh') {
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
		} catch (e) {
			console.error('Detay yükleme hatası:', e);
		}
	}

	// ─── CC Statement functions ─────────────────────────────

	async function loadCCStatements(productId: number) {
		try {
			const res = await api.get<any[]>(`/finance/krediler/kart/${productId}/statements`);
			ccStatements = res || [];
		} catch (e) {
			console.error('Ekstre yükleme hatası:', e);
			ccStatements = [];
		}
	}

	async function uploadCCStatement(productId: number, file: File) {
		if (!file.name.toLowerCase().endsWith('.pdf')) {
			ccUploadError = 'Sadece PDF dosyaları yüklenebilir';
			showToast(ccUploadError, 'error');
			return;
		}
		ccUploading = true;
		ccUploadError = '';
		ccUploadSuccess = '';
		try {
			const formData = new FormData();
			formData.append('file', file);
			const res: any = await api.upload('/finance/krediler/kart/auto-upload', formData);
			ccUploadSuccess = `${res.card_name || 'Kart'} — ${res.kesim_tarihi} dönemi yüklendi (${res.transaction_count} işlem)`;
			showToast(ccUploadSuccess, 'success');
			// İlgili kartın ekstrelerini yenile
			if (expandedId) await loadCCStatements(expandedId);
			await loadData();
		} catch (e: any) {
			console.error('Ekstre yükleme hatası:', e);
			ccUploadError = e?.message || 'Ekstre yüklenirken bir hata oluştu';
			showToast(ccUploadError, 'error');
		}
		ccUploading = false;
	}

	function handleCCFileSelect(files: File[]) {
		// Birden fazla dosya sırayla yükle
		files.forEach(f => uploadCCStatement(0, f));
	}

	function handleCCDropError(errors: string[]) {
		for (const err of errors) showToast(err, 'error', 4000);
	}

	async function toggleCCStmtExpand(productId: number, stmtId: number) {
		if (ccExpandedStmtId === stmtId) {
			ccExpandedStmtId = null;
			ccExpandedStmt = null;
			return;
		}
		try {
			const res = await api.get<any>(`/finance/krediler/kart/${productId}/statements/${stmtId}`);
			ccExpandedStmt = res;
			ccExpandedStmtId = stmtId;
		} catch (e) {
			console.error('Ekstre detay hatası:', e);
		}
	}

	function deleteCCStatement(productId: number, stmtId: number) {
		askDelete('Ekstreyi Sil', 'Bu ekstreyi silmek istediğinize emin misiniz?', async () => {
			try {
				await api.delete(`/finance/krediler/kart/${productId}/statements/${stmtId}`);
				ccStatements = ccStatements.filter(s => s.id !== stmtId);
				if (ccExpandedStmtId === stmtId) {
					ccExpandedStmtId = null;
					ccExpandedStmt = null;
				}
				await loadData();
			} catch (e) {
				console.error('Ekstre silme hatası:', e);
			}
		});
	}

	function getStmtStatus(stmt: any): { label: string; bg: string; text: string } {
		if (stmt.is_paid) return { label: 'Ödendi', bg: 'bg-green-100', text: 'text-green-700' };
		const today = new Date().toISOString().split('T')[0];
		if (stmt.son_odeme_tarihi < today) return { label: 'Gecikmiş', bg: 'bg-red-100', text: 'text-red-700' };
		return { label: 'Bekliyor', bg: 'bg-amber-100', text: 'text-amber-700' };
	}

	// ─── Existing functions ─────────────────────────────────

	function openAdd() {
		editProduct = null;
		form = {
			type: 'kredi_karti', name: '', bank_name: '', company: '', currency: 'TRY',
			total_amount: null, remaining_amount: null, interest_rate: null,
			bsmv_rate: null, commission_rate: null,
			start_date: '', end_date: '', notes: '', details: {},
		};
		showAddModal = true;
	}

	// Kredileri PDF rapor olarak indir (ekrandaki tip/durum filtresiyle eşleşir; açılış+vade dahil)
	async function downloadPdf() {
		pdfLoading = true;
		try {
			const params = new URLSearchParams();
			if (typeFilter) params.set('type_filter', typeFilter);
			if (statusFilter) params.set('status', statusFilter);
			const qs = params.toString();
			const res = await api.fetchRaw(`/finance/krediler/export/pdf${qs ? '?' + qs : ''}`);
			if (!res.ok) throw new Error('İndirme başarısız');
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `kredi-raporu-${new Date().toISOString().slice(0, 10)}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (err) {
			console.error('PDF indirme hatası:', err);
			showToast('PDF raporu indirilemedi', 'error');
		} finally {
			pdfLoading = false;
		}
	}

	function openEdit(p: any) {
		editProduct = p;
		form = {
			type: p.type,
			name: p.name || '',
			bank_name: p.bank_name || '',
			company: p.company || '',
			currency: p.currency || 'TRY',
			total_amount: p.total_amount ?? null,
			remaining_amount: p.remaining_amount ?? null,
			interest_rate: p.interest_rate,
			bsmv_rate: p.bsmv_rate,
			commission_rate: p.commission_rate,
			start_date: p.start_date || '',
			end_date: p.end_date || '',
			notes: p.notes || '',
			details: p.details || {},
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

			if (editProduct) {
				await api.patch(`/finance/krediler/${editProduct.id}`, body);
			} else {
				await api.post('/finance/krediler/', body);
			}
			showAddModal = false;
			await loadData();
			// BCH güncellendiyse ödeme planını da yenile
			if (editProduct && expandedId === editProduct.id) {
				const res = await api.get<{ payments?: any[] }>(`/finance/krediler/${editProduct.id}`);
				expandedPayments = res.payments || [];
			}
		} catch (e: any) {
			console.error('Kaydetme hatası:', e);
			showToast(e?.message || 'Kaydetme hatası', 'error');
		}
	}

	function deleteProduct(id: number) {
		askDelete('Kredi Ürününü Sil', 'Bu kredi ürününü silmek istediğinize emin misiniz?', async () => {
			try {
				await api.delete(`/finance/krediler/${id}`);
				await loadData();
			} catch (e) {
				console.error('Silme hatası:', e);
			}
		});
	}

	function openPaymentModal(productId: number) {
		paymentProductId = productId;
		paymentForm = { count: 12, start_date: '', amount: null, principal: null, interest: null, tax: null };
		showPaymentModal = true;
	}

	async function generatePayments() {
		if (!paymentProductId || !paymentForm.start_date || paymentForm.count < 1) return;
		if (!paymentForm.amount || paymentForm.amount <= 0) {
			showToast('Taksit tutarı zorunludur', 'warning');
			return;
		}

		const payments = [];
		const start = new Date(paymentForm.start_date);

		for (let i = 0; i < paymentForm.count; i++) {
			const d = new Date(start);
			d.setMonth(d.getMonth() + i);
			payments.push({
				installment_no: i + 1,
				due_date: d.toISOString().split('T')[0],
				amount: paymentForm.amount,
				principal: paymentForm.principal || null,
				interest: paymentForm.interest || null,
				tax: paymentForm.tax || null,
			});
		}

		try {
			await api.post(`/finance/krediler/${paymentProductId}/payments`, { payments });
			showPaymentModal = false;
			if (expandedId === paymentProductId) {
				const res = await api.get<{ payments?: any[] }>(`/finance/krediler/${paymentProductId}`);
				expandedPayments = res.payments || [];
			}
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
				is_paid: newPaid,
				paid_date: newPaid ? new Date().toISOString().split('T')[0] : null,
			});
			payment.is_paid = newPaid;
			payment.paid_date = newPaid ? new Date().toISOString().split('T')[0] : null;

			// Anapara (principal) bilgisi varsa kalan borcu güncelle
			if (payment.principal) {
				const product = products.find((p: any) => p.id === payment.credit_product_id);
				if (product) {
					if (newPaid) {
						product.remaining_amount = Math.max(0, (product.remaining_amount || 0) - payment.principal);
					} else {
						product.remaining_amount = (product.remaining_amount || 0) + payment.principal;
					}
				}
			}
		} catch (e) {
			console.error('Ödeme güncelleme hatası:', e);
		}
	}

	function deletePayment(paymentId: number) {
		askDelete('Ödemeyi Sil', 'Bu ödemeyi silmek istediğinize emin misiniz?', async () => {
			try {
				await api.delete(`/finance/krediler/payments/${paymentId}`);
				expandedPayments = expandedPayments.filter(p => p.id !== paymentId);
				await loadData();
			} catch (e) {
				console.error('Ödeme silme hatası:', e);
			}
		});
	}

	// ─── Ödeme Planı Akordiyon (ay ay gruplama) ─────────────
	const AY_KISA = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];

	function monthLabel(ym: string): string {
		const [y, m] = ym.split('-');
		return `${AY_KISA[Number(m) - 1]} ${y}`;
	}

	// expandedPayments → ay gruplarına böl (YYYY-MM), kronolojik sıralı
	const paymentMonths = $derived.by(() => {
		const groups = new Map<string, any[]>();
		for (const pay of expandedPayments) {
			const ym = (pay.due_date || '').slice(0, 7);  // YYYY-MM
			if (!ym) continue;
			if (!groups.has(ym)) groups.set(ym, []);
			groups.get(ym)!.push(pay);
		}
		const today = new Date().toISOString().split('T')[0];
		return Array.from(groups.entries())
			.sort((a, b) => a[0].localeCompare(b[0]))
			.map(([ym, pays]) => {
				const total = pays.reduce((s, p) => s + (p.amount || 0), 0);
				const paidCount = pays.filter((p) => p.is_paid).length;
				const unpaidTotal = pays.filter((p) => !p.is_paid).reduce((s, p) => s + (p.amount || 0), 0);
				const hasOverdue = pays.some((p) => !p.is_paid && p.due_date < today);
				return { ym, label: monthLabel(ym), pays, total, paidCount, count: pays.length, unpaidTotal, hasOverdue };
			});
	});

	function initExpandedMonths() {
		// Ödenmemiş taksiti olan ayları varsayılan açık başlat
		const open = new Set<string>();
		const groups = new Map<string, boolean>();  // ym → hasUnpaid
		for (const pay of expandedPayments) {
			const ym = (pay.due_date || '').slice(0, 7);
			if (!ym) continue;
			if (!pay.is_paid) groups.set(ym, true);
			else if (!groups.has(ym)) groups.set(ym, false);
		}
		for (const [ym, hasUnpaid] of groups) {
			if (hasUnpaid) open.add(ym);
		}
		expandedMonths = open;
	}

	function toggleMonth(ym: string) {
		const next = new Set(expandedMonths);
		if (next.has(ym)) next.delete(ym);
		else next.add(ym);
		expandedMonths = next;
	}

	// ─── Yaklaşan Ödemeler — ay ay akordiyon (tüm krediler birleşik) ─────
	let expandedUpcomingMonths = $state<Set<string>>(new Set());

	const upcomingMonths = $derived.by(() => {
		const groups = new Map<string, any[]>();
		for (const u of upcoming) {
			const ym = (u.due_date || '').slice(0, 7);
			if (!ym) continue;
			if (!groups.has(ym)) groups.set(ym, []);
			groups.get(ym)!.push(u);
		}
		const today = new Date().toISOString().split('T')[0];
		return Array.from(groups.entries())
			.sort((a, b) => a[0].localeCompare(b[0]))
			.map(([ym, items]) => {
				// Para birimi bazında ödenen / kalan toplamlar (EUR + TL karışık olabilir)
				const paidTotals: Record<string, number> = {};
				const unpaidTotals: Record<string, number> = {};
				for (const it of items) {
					const cur = it.currency || 'TRY';
					const bucket = it.is_paid ? paidTotals : unpaidTotals;
					bucket[cur] = (bucket[cur] || 0) + (it.amount || 0);
				}
				const paidCount = items.filter((it) => it.is_paid).length;
				const hasOverdue = items.some((it) => !it.is_paid && it.due_date < today);
				return {
					ym, label: monthLabel(ym), items,
					paidTotals, unpaidTotals, paidCount, count: items.length, hasOverdue,
				};
			});
	});

	// upcoming yüklenince ilk (en yakın) ayı açık başlat
	$effect(() => {
		if (upcoming.length > 0 && expandedUpcomingMonths.size === 0) {
			const first = upcomingMonths[0]?.ym;
			if (first) expandedUpcomingMonths = new Set([first]);
		}
	});

	function toggleUpcomingMonth(ym: string) {
		const next = new Set(expandedUpcomingMonths);
		if (next.has(ym)) next.delete(ym);
		else next.add(ym);
		expandedUpcomingMonths = next;
	}

	function monthTotalLabel(totals: Record<string, number>): string {
		const parts = Object.entries(totals).filter(([, amt]) => amt > 0);
		if (parts.length === 0) return '';
		return parts.map(([cur, amt]) => fmt(amt, cur)).join(' + ');
	}

	// ─── Kredi Kapat / Yeniden Aç ───────────────────────────
	function openCloseModal(p: any) {
		closeModal = {
			show: true, id: p.id, name: p.name,
			closedDate: new Date().toISOString().split('T')[0],
		};
	}

	async function confirmClose() {
		if (closeModal.id == null) return;
		try {
			await api.post(`/finance/krediler/${closeModal.id}/close`, { closed_date: closeModal.closedDate });
			showToast('Kredi kapatıldı, ileri vadeli ödemeler nakit akımdan çıkarıldı', 'success');
			closeModal = { show: false, id: null, name: '', closedDate: new Date().toISOString().split('T')[0] };
			await loadData();
			if (expandedId) {
				const res = await api.get<{ payments?: any[] }>(`/finance/krediler/${expandedId}`);
				expandedPayments = res.payments || [];
			}
		} catch (e: any) {
			console.error('Kredi kapatma hatası:', e);
			showToast(e?.message || 'Kredi kapatılamadı', 'error');
		}
	}

	function reopenProduct(p: any) {
		askDelete(
			'Krediyi Yeniden Aç',
			`"${p.name}" yeniden açılacak ve ödenmemiş taksitler nakit akıma geri eklenecek. Devam edilsin mi?`,
			async () => {
				try {
					await api.post(`/finance/krediler/${p.id}/reopen`, {});
					showToast('Kredi yeniden açıldı', 'success');
					await loadData();
					if (expandedId) {
						const res = await api.get<{ payments?: any[] }>(`/finance/krediler/${expandedId}`);
						expandedPayments = res.payments || [];
					}
				} catch (e: any) {
					console.error('Yeniden açma hatası:', e);
					showToast(e?.message || 'Kredi yeniden açılamadı', 'error');
				}
			},
		);
	}

	let unsubFinance: (() => void) | null = null;

	onMount(() => {
		loadData();
		unsubFinance = onWsEvent('finance_updated', () => {
			loadData();
		});
	});

	onDestroy(() => { unsubFinance?.(); });
</script>

<div class="max-w-7xl mx-auto px-1 sm:px-0">
	<!-- Başlık -->
	<div class="mb-4 sm:mb-6">
		<PageHeader title="Krediler" description="Kredi ürünleri, taksit takvimi ve kredi kartı ekstreleri">
			{#snippet actions()}
				<Button variant="secondary" onclick={downloadPdf} disabled={pdfLoading} title="Kredileri PDF rapor olarak indir (açılış + vade tarihleri dahil)">
					<FileDown size={16} /> <span class="hidden sm:inline">{pdfLoading ? 'Hazırlanıyor…' : 'PDF Rapor'}</span>
				</Button>
				{#if canUse}
					<Button onclick={openAdd}><Plus size={16} /> <span class="hidden sm:inline">Yeni</span> Ürün</Button>
				{/if}
			{/snippet}
		</PageHeader>
	</div>

	<!-- Özet Kartları -->
	{#if summary.length > 0}
		<div class="flex flex-wrap gap-2 sm:gap-3 mb-4 sm:mb-6">
			{#each summary as s}
				<StatCard
					class="flex-1 min-w-[150px]"
					label={s.type_label}
					value={s.remaining_amount_eur != null ? fmt(s.remaining_amount_eur, 'EUR') : fmt(s.remaining_amount)}
					accent={TYPE_ACCENT[s.type] ?? 'blue'}
					icon={CreditCard}
					hint="{s.count} ürün"
				/>
			{/each}
		</div>
	{/if}

	<!-- Banka Bazlı Kredi Dağılımı (Simit Grafik — EUR Konsolide) -->
	{#if !loading && bankGroups.length > 0}
		<div class="mb-4 sm:mb-6">
			<div class="flex items-center justify-between mb-2 sm:mb-3 gap-2">
				<h3 class="text-xs sm:text-sm font-bold text-gray-700">Banka Bazlı Kredi Dağılımı (EUR)</h3>
				{#if eurRate}
					<span class="text-[10px] text-gray-500">1 € = {eurRate.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺</span>
				{/if}
			</div>
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
				{#each bankGroups as group (group.bank)}
					<div class="bg-white border border-gray-200 rounded-xl p-3 sm:p-4 shadow-sm">
						<div class="flex items-start justify-between mb-3 gap-2">
							<div class="min-w-0 flex-1">
								<h4 class="text-sm font-semibold text-gray-800 truncate" title={group.bank}>{group.bank}</h4>
								<span class="text-[10px] text-gray-500">
									{group.items.length} kredi
									{#if group.hasMissingRate}· <span class="text-amber-500">bazı kurlar eksik</span>{/if}
								</span>
							</div>
							<div class="text-right shrink-0">
								<div class="text-[10px] text-gray-400 leading-none">Toplam</div>
								<div class="text-sm font-bold text-gray-800 mt-0.5 whitespace-nowrap">{fmtCompact(group.totalEur, 'EUR')}</div>
							</div>
						</div>
						<!-- Kredi zaman çizgileri: sol açılış · sağ vade · vadeye yaklaştıkça kalın/kontrast dolgu · vadesi yaklaşan üstte · tıkla → ödeme planı -->
						<div class="space-y-2">
							{#each group.items as p (p.id)}
								{@const tl = creditTimeline(p)}
								{@const isEur = p.currency === 'EUR'}
								<button
									onclick={() => openPlanModal(p)}
									class="w-full text-left rounded-lg px-2 py-1.5 transition-colors cursor-pointer {isEur ? 'bg-blue-50/40 hover:bg-blue-50' : 'hover:bg-gray-50'}"
									title="{p.name} — ödeme planını aç"
								>
									<div class="flex items-center justify-between gap-2">
										<span class="text-xs font-medium text-gray-700 truncate">{p.name}</span>
										<span class="text-xs font-semibold whitespace-nowrap {isEur ? 'text-blue-700' : 'text-gray-800'}">{fmtCompact(p.remaining_amount, p.currency)}</span>
									</div>
									{#if tl.hasVade}
										<div class="flex items-center gap-1.5 mt-1.5">
											<span class="text-[9px] text-gray-400 tabular-nums w-[54px] shrink-0">{fmtDate(p.start_date)}</span>
											<div class="relative flex-1 h-2 flex items-center">
												<div class="absolute inset-x-0 h-px bg-gray-200 rounded-full"></div>
												<div class="absolute left-0 rounded-full transition-all {(isEur ? TIER_FILL_EUR : TIER_FILL)[tl.tier]}" style="width: {tl.progress * 100}%"></div>
												<div class="absolute w-2 h-2 rounded-full border border-white shadow-sm {(isEur ? TIER_DOT_EUR : TIER_DOT)[tl.tier]} -translate-x-1/2" style="left: {tl.progress * 100}%"></div>
											</div>
											<span class="text-[9px] text-gray-400 tabular-nums w-[54px] shrink-0 text-right">{fmtDate(p.end_date)}</span>
										</div>
										<div class="text-right mt-0.5">
											<span class="text-[9px] font-semibold {(isEur ? TIER_TEXT_EUR : TIER_TEXT)[tl.tier]}">{tl.tier === 'overdue' ? 'Vadesi geçti' : `${tl.daysToDue} gün kaldı`}</span>
										</div>
									{:else}
										<div class="mt-1 text-[9px] text-gray-400">Vadesiz · rotatif</div>
									{/if}
								</button>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Filtreler -->
	<div class="flex flex-wrap gap-2 mb-3 sm:mb-4">
		<Select size="sm" fullWidth={false} bind:value={typeFilter} onchange={loadData} class="flex-1 sm:flex-none">
			<option value="">Tüm Tipler</option>
			{#each PRODUCT_TYPES as t}
				<option value={t}>{TYPE_LABELS[t]}</option>
			{/each}
		</Select>
		<Select size="sm" fullWidth={false} bind:value={statusFilter} onchange={loadData} class="flex-1 sm:flex-none">
			<option value="active">Aktif</option>
			<option value="closed">Kapalı</option>
			<option value="">Tümü</option>
		</Select>
	</div>

	<!-- Kredi Kartı Ekstre Sürükle-Bırak (ortak) -->
	{#if canUse && products.some((p: any) => p.type === 'kredi_karti')}
		<div class="relative mb-4">
			{#if ccUploading}
				<div class="absolute inset-0 z-10 bg-white/80 rounded-xl flex items-center justify-center">
					<div class="flex items-center gap-2 text-teal-700">
						<Loader2 size={20} class="animate-spin" />
						<span class="text-sm font-medium">Ekstre yükleniyor...</span>
					</div>
				</div>
			{/if}
			<FileDropzone
				accept=".pdf"
				maxSize={50 * 1024 * 1024}
				multiple={true}
				disabled={ccUploading}
				label="Kredi kartı ekstrelerini sürükleyip bırakın"
				hint="PDF formatında — kart otomatik algılanır"
				onSelect={handleCCFileSelect}
				onError={handleCCDropError}
			/>
			{#if ccUploadError}
				<p class="text-xs text-red-600 mt-2">{ccUploadError}</p>
			{/if}
			{#if ccUploadSuccess}
				<p class="inline-flex items-center gap-1 text-xs text-teal-700 mt-2"><CheckCircle2 size={14} /> {ccUploadSuccess}</p>
			{/if}
		</div>
	{/if}

	<!-- Yaklaşan Ödemeler — ay ay akordiyon -->
	{#if upcoming.length > 0}
		<div class="bg-amber-50 border border-amber-200 rounded-xl p-3 sm:p-4 mb-4 sm:mb-6">
			<h3 class="text-xs sm:text-sm font-bold text-amber-700 mb-2.5">Taksit Takvimi — Aylık (ödenen + kalan)</h3>
			<div class="space-y-1.5">
				{#each upcomingMonths as grp (grp.ym)}
					{@const open = expandedUpcomingMonths.has(grp.ym)}
					<div class="bg-white border border-amber-100 rounded-lg overflow-hidden">
						<!-- Ay başlığı -->
						<button
							type="button"
							onclick={() => toggleUpcomingMonth(grp.ym)}
							class="w-full flex items-center gap-2 px-2.5 sm:px-3 py-2 text-left hover:bg-amber-50/60 cursor-pointer"
							aria-expanded={open}
						>
							<ChevronRight size={14} class="shrink-0 text-amber-500 transition-transform {open ? 'rotate-90' : ''}" />
							<span class="font-semibold text-xs sm:text-sm text-gray-700 w-16 sm:w-20 shrink-0">{grp.label}</span>
							<span class="text-[10px] sm:text-xs text-gray-500 shrink-0">{grp.paidCount}/{grp.count}</span>
							{#if grp.hasOverdue}
								<span class="text-[10px] font-medium bg-red-100 text-red-700 px-1.5 py-0.5 rounded-full shrink-0">Gecikmiş</span>
							{/if}
							<!-- Ödenen / Kalan toplam (para birimi bazında) -->
							<span class="ml-auto text-right whitespace-nowrap leading-tight">
								{#if monthTotalLabel(grp.unpaidTotals)}
									<span class="block text-xs sm:text-sm font-bold text-amber-700">Kalan: {monthTotalLabel(grp.unpaidTotals)}</span>
								{/if}
								{#if monthTotalLabel(grp.paidTotals)}
									<span class="block text-[10px] sm:text-xs font-medium text-emerald-600">Ödenen: {monthTotalLabel(grp.paidTotals)}</span>
								{/if}
							</span>
						</button>
						<!-- Ay taksitleri -->
						{#if open}
							<div class="border-t border-amber-100 divide-y divide-amber-50">
								{#each grp.items as u (u.payment_id)}
									{@const overdue = !u.is_paid && u.due_date < new Date().toISOString().split('T')[0]}
									<div class="flex items-center justify-between gap-2 px-3 py-1.5 text-xs sm:text-sm {u.is_paid ? 'bg-emerald-50/40' : ''}">
										<span class="text-gray-700 truncate min-w-0 flex items-center gap-1.5">
											<span class="truncate">{u.product_name}</span>
											<span class="text-[10px] text-gray-500 shrink-0">#{u.installment_no || ''}</span>
											{#if u.is_paid}
												<span class="text-[10px] font-medium bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded-full shrink-0">Ödendi</span>
											{:else if overdue}
												<span class="text-[10px] font-medium bg-red-100 text-red-700 px-1.5 py-0.5 rounded-full shrink-0">Gecikmiş</span>
											{/if}
										</span>
										<span class="whitespace-nowrap shrink-0 text-right flex items-center gap-2">
											<span class="{overdue ? 'text-red-600 font-medium' : 'text-gray-500'}">{fmtDate(u.due_date)}</span>
											<span class="font-semibold w-24 sm:w-28 text-right inline-block {u.is_paid ? 'text-emerald-600 line-through opacity-70' : 'text-amber-700'}">{fmt(u.amount, u.currency)}</span>
										</span>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Ürün Listesi -->
	{#if loading}
		<TableSkeleton rows={4} columns={3} showHeader={false} />
	{:else if products.length === 0}
		<EmptyState
			icon={CreditCard}
			title="Henüz kredi ürünü yok"
			description={canUse ? 'Yeni ürün eklemek için yukarıdaki butonu kullanın' : ''}
		/>
	{:else}
		<div class="space-y-2">
			{#each products as p (p.id)}
				{@const c = TYPE_COLORS[p.type] || TYPE_COLORS.spot_kredi}
				{@const needsStatement = p.type === 'kredi_karti' && p.details?.ekstre_kesim_gunu && (() => {
					const today = new Date();
					const kesimGun = p.details.ekstre_kesim_gunu;
					const lastStmt = ccStatements.find((s: any) => s.credit_product_id === p.id);
					if (!lastStmt) return true;
					const lastKesim = new Date(lastStmt.kesim_tarihi);
					const thisMonthKesim = new Date(today.getFullYear(), today.getMonth(), kesimGun);
					return lastKesim < thisMonthKesim && today > thisMonthKesim;
				})()}
				<div id="credit-{p.id}" class="{needsStatement ? 'bg-gray-200' : 'bg-white'} border border-gray-200 rounded-xl overflow-hidden shadow-sm scroll-mt-20">
					<!-- Başlık satırı -->
					<button
						onclick={() => toggleExpand(p.id, p.type)}
						class="w-full flex items-center gap-1.5 sm:gap-3 px-2.5 sm:px-4 py-2.5 sm:py-3 hover:bg-gray-50 cursor-pointer text-left"
					>
						<ChevronRight class="w-3.5 h-3.5 sm:w-4 sm:h-4 shrink-0 text-gray-500 transition-transform {expandedId === p.id ? 'rotate-90' : ''}" />
						<span class="text-[10px] sm:text-xs font-medium {c.bg} {c.text} {c.border} border px-1.5 sm:px-2 py-0.5 rounded-full shrink-0">{p.type_label}</span>
						{#if p.status === 'closed'}
							<span class="text-[10px] sm:text-[10px] font-semibold bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded-full shrink-0">Kapalı</span>
						{/if}
						<span class="font-medium text-xs sm:text-sm {p.status === 'closed' ? 'text-gray-500 line-through' : 'text-gray-800'} flex-1 truncate min-w-0">{p.name}</span>
						<span class="text-xs text-gray-500 hidden sm:inline">{p.bank_name || p.company || ''}</span>
						{#if p.interest_rate != null}
							<span class="text-xs text-gray-500 hidden sm:inline">%{p.interest_rate}</span>
						{/if}
						{#if p.commission_rate}
							<span class="text-[10px] text-gray-500 hidden sm:inline">Kom:%{p.commission_rate}</span>
						{/if}
						<span class="font-bold text-xs sm:text-sm text-gray-800 whitespace-nowrap shrink-0">{fmt(p.remaining_amount, p.currency)}</span>
						{#if p.next_payment_date}
							<span class="text-[10px] text-amber-600 hidden sm:inline">{fmtDate(p.next_payment_date)}</span>
						{/if}
						<span class="text-[10px] sm:text-xs {p.status === 'active' ? 'text-green-600' : 'text-gray-500'} shrink-0">{p.paid_count}/{p.payment_count}</span>
					</button>

					<!-- Genişletilmiş detay -->
					{#if expandedId === p.id}
						<div class="border-t border-gray-100 bg-gray-50 px-2.5 sm:px-4 py-2.5 sm:py-3">
							<div class="flex items-center justify-between mb-3 flex-wrap gap-2">
								<h4 class="text-xs sm:text-sm font-bold text-gray-600">{p.type === 'kredi_karti' ? 'Kredi Kartı Detayı' : p.type === 'kmh' ? 'KMH Durumu' : 'Ödeme Planı'}</h4>
								<div class="flex gap-1.5 sm:gap-2 flex-wrap">
									{#if canUse}
										{#if p.type !== 'kredi_karti' && p.type !== 'kmh'}
											<Button size="sm" onclick={() => openPaymentModal(p.id)}><Plus size={14} /> Taksit</Button>
										{/if}
										<Button variant="secondary" size="sm" onclick={() => openEdit(p)}>Düzenle</Button>
										{#if p.status === 'closed'}
											<Button variant="secondary" size="sm" onclick={() => reopenProduct(p)}><RotateCcw size={14} /> Yeniden Aç</Button>
										{:else if p.type !== 'kredi_karti'}
											<Button variant="secondary" size="sm" onclick={() => openCloseModal(p)}>Kapat</Button>
										{/if}
										<Button variant="danger" size="sm" onclick={() => deleteProduct(p.id)}>Sil</Button>
									{/if}
								</div>
							</div>

							<!-- KMH özel görünüm -->
							{#if p.type === 'kmh'}
								{#if !kmhStatus}
									<p class="text-sm text-gray-500 py-4 text-center">KMH durumu yükleniyor…</p>
								{:else if kmhStatus.error}
									<div class="bg-red-50 border border-red-200 text-red-700 rounded-lg p-3 text-sm">
										{kmhStatus.error}
										{#if kmhStatus.error?.includes('linked_account_id')}
											<br /><span class="text-xs">→ "Düzenle" ile bu KMH'ye bağlı banka hesabını seçin.</span>
										{/if}
									</div>
								{:else}
									{@const cur = kmhStatus.current_period}
									<!-- 4 stat kart (mevcut ay + tüm aylar toplamı) -->
									<div class="grid grid-cols-2 md:grid-cols-4 gap-2 sm:gap-3 mb-4">
										<div class="bg-white border border-gray-200 rounded-xl p-3">
											<div class="text-[10px] text-gray-500 uppercase tracking-wider">Açık Borç</div>
											<div class="text-lg sm:text-xl font-bold {kmhStatus.current_debt > 0 ? 'text-red-600' : 'text-gray-700'} mt-0.5">{fmt(kmhStatus.current_debt)}</div>
											<div class="text-[10px] text-gray-500 mt-0.5">Kullan. limit: {fmt(kmhStatus.available_limit)}</div>
										</div>
										<div class="bg-white border border-gray-200 rounded-xl p-3">
											<div class="text-[10px] text-gray-500 uppercase tracking-wider">Bu Ay Adat</div>
											<div class="text-lg sm:text-xl font-bold text-gray-700 mt-0.5">{cur ? fmt(cur.past_adat) : '0'}</div>
											<div class="text-[10px] text-gray-500 mt-0.5">{cur?.period_start ?? ''} → bugün</div>
										</div>
										<div class="bg-white border border-gray-200 rounded-xl p-3">
											<div class="text-[10px] text-gray-500 uppercase tracking-wider">Bu Ay Birikmiş</div>
											<div class="text-lg sm:text-xl font-bold text-amber-600 mt-0.5">{cur ? fmt(cur.accrued_total) : '0'}</div>
											<div class="text-[10px] text-gray-500 mt-0.5">Faiz {cur ? fmt(cur.accrued_interest) : '0'} + BSMV+Kom.</div>
										</div>
										<div class="bg-white border border-gray-200 rounded-xl p-3 border-l-4 border-l-teal-500">
											<div class="text-[10px] text-gray-500 uppercase tracking-wider">Tahmini Ay Sonu</div>
											<div class="text-lg sm:text-xl font-bold text-teal-700 mt-0.5">{cur ? fmt(cur.projected_total_due) : '0'}</div>
											<div class="text-[10px] text-gray-500 mt-0.5">Tüm aylar: {fmt(kmhStatus.total_projected)} ₺</div>
										</div>
									</div>

									<!-- Faiz oranı bilgisi -->
									<div class="text-xs text-gray-500 mb-3 px-1">
										Yıllık faiz: <span class="font-semibold">%{kmhStatus.interest_rate}</span> ·
										BSMV: %{kmhStatus.bsmv_rate} ·
										Komisyon: %{kmhStatus.commission_rate} ·
										Limit: <span class="font-semibold">{fmt(kmhStatus.limit)}</span>
									</div>

									<!-- Aylık Tahakkuklar tablosu -->
									{#if kmhStatus.periods && kmhStatus.periods.length > 0}
										<div class="bg-white border border-gray-200 rounded-xl overflow-hidden mb-4">
											<div class="px-3 py-2 border-b border-gray-100 bg-gray-50">
												<span class="text-xs font-semibold text-gray-700">Aylık Tahakkuklar ({kmhStatus.periods.length} ay)</span>
												<span class="text-[10px] text-gray-500 ml-2">Toplam birikmiş: <span class="font-semibold text-amber-600">{fmt(kmhStatus.total_accrued)} ₺</span> · Toplam tahmini: <span class="font-semibold text-teal-700">{fmt(kmhStatus.total_projected)} ₺</span></span>
											</div>
											<div class="overflow-x-auto">
												<table class="w-full text-xs">
													<thead class="bg-gray-50 text-[10px] text-gray-500 uppercase tracking-wider">
														<tr>
															<th class="text-left px-3 py-1.5">Ay</th>
															<th class="text-right px-3 py-1.5">Devir Bakiye</th>
															<th class="text-right px-3 py-1.5">Adat (geçmiş)</th>
															<th class="text-right px-3 py-1.5">Adat (proj.)</th>
															<th class="text-right px-3 py-1.5">Faiz</th>
															<th class="text-right px-3 py-1.5">BSMV</th>
															<th class="text-right px-3 py-1.5">Komisyon</th>
															<th class="text-right px-3 py-1.5">Toplam</th>
														</tr>
													</thead>
													<tbody>
														{#each kmhStatus.periods as pp}
															<tr class="border-t border-gray-100 {pp.is_current ? 'bg-teal-50/40 font-medium' : ''}">
																<td class="px-3 py-1.5 text-gray-700 whitespace-nowrap">
																	{pp.month_label}
																	{#if pp.is_current}<span class="text-[10px] text-teal-700 ml-1">[bu ay]</span>{/if}
																</td>
																<td class="px-3 py-1.5 text-right {pp.carry_balance < 0 ? 'text-red-600' : 'text-gray-500'} whitespace-nowrap">{fmt(pp.carry_balance)}</td>
																<td class="px-3 py-1.5 text-right text-gray-700 whitespace-nowrap">{fmt(pp.past_adat)}</td>
																<td class="px-3 py-1.5 text-right text-gray-500 whitespace-nowrap">{pp.future_adat > 0 ? '+' + fmt(pp.future_adat) : '—'}</td>
																<td class="px-3 py-1.5 text-right text-amber-700 whitespace-nowrap">{fmt(pp.is_current ? pp.projected_interest : pp.accrued_interest)}</td>
																<td class="px-3 py-1.5 text-right text-gray-600 whitespace-nowrap">{fmt(pp.is_current ? pp.projected_bsmv : pp.accrued_bsmv)}</td>
																<td class="px-3 py-1.5 text-right text-gray-600 whitespace-nowrap">{fmt(pp.is_current ? pp.projected_commission : pp.accrued_commission)}</td>
																<td class="px-3 py-1.5 text-right font-semibold {pp.is_current ? 'text-teal-700' : 'text-gray-800'} whitespace-nowrap">{fmt(pp.is_current ? pp.projected_total_due : pp.accrued_total)}</td>
															</tr>
														{/each}
													</tbody>
												</table>
											</div>
										</div>
									{/if}

									<!-- Hareketler tablosu -->
									<div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
										<div class="px-3 py-2 border-b border-gray-100 bg-gray-50">
											<span class="text-xs font-semibold text-gray-700">{cur?.month_label} hareketleri ({cur.movements?.length || 0}{cur.carry_date ? ' + devir' : ''})</span>
										</div>
										<div class="overflow-x-auto">
											<table class="w-full text-xs">
												<thead class="bg-gray-50 text-[10px] text-gray-500 uppercase tracking-wider">
													<tr>
														<th class="text-left px-3 py-1.5">Tarih</th>
														<th class="text-left px-3 py-1.5">Açıklama</th>
														<th class="text-right px-3 py-1.5">Tutar</th>
														<th class="text-right px-3 py-1.5">Bakiye</th>
														<th class="text-center px-3 py-1.5">Durum</th>
													</tr>
												</thead>
												<tbody>
													{#if cur.carry_date}
														<tr class="border-t border-gray-100 bg-amber-50/40">
															<td class="px-3 py-1.5 text-gray-600 whitespace-nowrap">{fmtDate(cur.carry_date)}</td>
															<td class="px-3 py-1.5 text-gray-500 italic truncate max-w-md" title={cur.carry_description}><CornerDownLeft size={11} class="inline-block mr-1 align-middle" />Devir bakiye (period öncesi son işlem) — {cur.carry_description}</td>
															<td class="px-3 py-1.5 text-right text-gray-500">—</td>
															<td class="px-3 py-1.5 text-right {cur.carry_balance < 0 ? 'text-red-600 font-semibold' : 'text-gray-600'} whitespace-nowrap">{fmt(cur.carry_balance)}</td>
															<td class="px-3 py-1.5 text-center">
																{#if cur.carry_balance < 0}
																	<span class="inline-block text-[10px] font-medium bg-red-50 text-red-700 px-1.5 py-0.5 rounded">KMH Kullanım</span>
																{:else}
																	<span class="inline-block text-[10px] font-medium bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">Devir</span>
																{/if}
															</td>
														</tr>
													{/if}
													{#if (!cur.movements || cur.movements.length === 0) && !cur.carry_date}
														<tr><td colspan="5" class="text-center text-xs text-gray-500 py-4">Bu period'da hareket yok.</td></tr>
													{/if}
													{#each (cur.movements || []) as mv (mv.id)}
															<tr class="border-t border-gray-100">
																<td class="px-3 py-1.5 text-gray-600 whitespace-nowrap">{fmtDate(mv.date)}</td>
																<td class="px-3 py-1.5 text-gray-600 truncate max-w-md" title={mv.description}>{mv.description}</td>
																<td class="px-3 py-1.5 text-right font-medium {mv.amount < 0 ? 'text-red-600' : 'text-emerald-600'} whitespace-nowrap">{mv.amount > 0 ? '+' : ''}{fmt(mv.amount)}</td>
																<td class="px-3 py-1.5 text-right {mv.balance_after !== null && mv.balance_after < 0 ? 'text-red-600 font-semibold' : 'text-gray-600'} whitespace-nowrap">{mv.balance_after !== null ? fmt(mv.balance_after) : '—'}</td>
																<td class="px-3 py-1.5 text-center">
																	{#if mv.kmh_state === 'negatif'}
																		<span class="inline-block text-[10px] font-medium bg-red-50 text-red-700 px-1.5 py-0.5 rounded">KMH Kullanım</span>
																	{:else if mv.kmh_state === 'pozitif'}
																		<span class="inline-block text-[10px] font-medium bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded">Pozitif</span>
																	{:else}
																		<span class="text-[10px] text-gray-500">—</span>
																	{/if}
																</td>
															</tr>
													{/each}
												</tbody>
											</table>
										</div>
										{#if cur.carry_balance < 0 && cur.carry_date}
											<div class="px-3 py-2 border-t border-gray-100 bg-amber-50 text-[11px] text-amber-700 flex items-start gap-1.5">
												<Info size={14} class="shrink-0 mt-0.5" />
												<span><strong>Adat'a etki:</strong> Devir bakiye <strong>{fmt(Math.abs(cur.carry_balance))} ₺</strong> negatif olduğundan period başlangıcından (<strong>{fmtDate(cur.period_start)}</strong>) itibaren günlük adat'a eklenir.</span>
											</div>
										{/if}
									</div>
								{/if}
							{:else}

							<!-- Kredi Kartı: Ekstre Bölümü -->
							{#if p.type === 'kredi_karti'}
								<!-- Ekstre Listesi -->
								{#if ccStatements.length === 0}
									<p class="text-sm text-gray-500 py-4 text-center">Henüz yüklenmiş ekstre yok</p>
								{:else}
									<div class="space-y-2">
										{#each ccStatements as stmt (stmt.id)}
											{@const stmtStatus = getStmtStatus(stmt)}
											<div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
												<!-- Ekstre satırı (div role=button — iç sil butonu nested olamaz) -->
												<div
													onclick={() => toggleCCStmtExpand(p.id, stmt.id)}
													onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleCCStmtExpand(p.id, stmt.id); } }}
													role="button"
													tabindex="0"
													aria-expanded={ccExpandedStmtId === stmt.id}
													class="w-full flex items-center gap-2 sm:gap-3 px-3 py-2.5 hover:bg-gray-50 cursor-pointer text-left text-sm flex-wrap sm:flex-nowrap"
												>
													<ChevronRight size={14} class="shrink-0 text-gray-500 transition-transform {ccExpandedStmtId === stmt.id ? 'rotate-90' : ''}" />
													<span class="text-gray-600">
														<span class="font-medium">{fmtDate(stmt.kesim_tarihi)}</span>
														<span class="text-xs text-gray-500 ml-1 hidden sm:inline">kesim</span>
													</span>
													<span class="text-gray-600 hidden sm:inline">
														<span class="text-xs text-gray-500">son ödeme:</span>
														<span class="font-medium ml-1">{fmtDate(stmt.son_odeme_tarihi)}</span>
													</span>
													<span class="flex-1"></span>
													<span class="text-xs text-gray-500 hidden sm:inline">{stmt.transaction_count} işlem</span>
													<span class="font-bold text-gray-800 whitespace-nowrap">{fmt(stmt.toplam_borc)}</span>
													<span class="text-[10px] text-gray-500 hidden sm:inline">asgari: {fmt(stmt.asgari_odeme)}</span>
													<span class="text-[10px] font-medium {stmtStatus.bg} {stmtStatus.text} px-2 py-0.5 rounded-full">{stmtStatus.label}</span>
													{#if canUse}
														<button
															onclick={(e) => { e.stopPropagation(); deleteCCStatement(p.id, stmt.id); }}
															class="text-red-500 hover:text-red-600 cursor-pointer ml-1"
															title="Sil"
															aria-label="Sil"
														>
															<X size={14} />
														</button>
													{/if}
												</div>

												<!-- Ekstre detay: Özet + İşlemler -->
												{#if ccExpandedStmtId === stmt.id && ccExpandedStmt}
													<div class="border-t border-gray-100 bg-gray-50 px-3 py-3">
														<!-- Özet bilgiler -->
														<div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
															<div class="bg-white rounded-lg p-2.5 border border-gray-100">
																<div class="text-[10px] text-gray-500">Önceki Bakiye</div>
																<div class="text-sm font-semibold text-gray-700">{fmt(ccExpandedStmt.onceki_bakiye)}</div>
															</div>
															<div class="bg-white rounded-lg p-2.5 border border-gray-100">
																<div class="text-[10px] text-gray-500">Dönem Harcama</div>
																<div class="text-sm font-semibold text-red-600">{fmt(ccExpandedStmt.donem_harcama)}</div>
															</div>
															<div class="bg-white rounded-lg p-2.5 border border-gray-100">
																<div class="text-[10px] text-gray-500">Faiz / Ücret</div>
																<div class="text-sm font-semibold text-orange-600">{fmt(ccExpandedStmt.faiz_ucret)}</div>
															</div>
															<div class="bg-white rounded-lg p-2.5 border border-gray-100">
																<div class="text-[10px] text-gray-500">Dönem Ödeme</div>
																<div class="text-sm font-semibold text-green-600">{fmt(ccExpandedStmt.donem_odeme)}</div>
															</div>
														</div>

														<!-- İşlem tablosu -->
														{#if ccExpandedStmt.transactions && ccExpandedStmt.transactions.length > 0}
															<div class="overflow-x-auto">
																<table class="w-full text-sm">
																	<thead>
																		<tr class="text-xs text-gray-500 border-b border-gray-200">
																			<th class="text-left py-1.5 px-2">Tarih</th>
																			<th class="text-left py-1.5 px-2">Açıklama</th>
																			<th class="text-left py-1.5 px-2 hidden sm:table-cell">Kategori</th>
																			<th class="text-left py-1.5 px-2 hidden md:table-cell">Taksit</th>
																			<th class="text-right py-1.5 px-2">Tutar</th>
																		</tr>
																	</thead>
																	<tbody>
																		{#each ccExpandedStmt.transactions as tx (tx.id)}
																			<tr class="border-b border-gray-100 hover:bg-white/60">
																				<td class="py-1.5 px-2 text-gray-500 whitespace-nowrap">{tx.islem_tarihi ? fmtDate(tx.islem_tarihi) : '-'}</td>
																				<td class="py-1.5 px-2 text-gray-700 max-w-[200px] truncate" title={tx.aciklama}>{tx.aciklama}</td>
																				<td class="py-1.5 px-2 text-gray-500 text-xs hidden sm:table-cell">{tx.kategori || '-'}</td>
																				<td class="py-1.5 px-2 text-gray-500 text-xs hidden md:table-cell max-w-[150px] truncate" title={tx.taksit_bilgi || ''}>{tx.taksit_bilgi || '-'}</td>
																				<td class="py-1.5 px-2 text-right font-medium whitespace-nowrap {tx.is_credit ? 'text-green-600' : 'text-red-600'}">
																					{tx.is_credit ? '+' : '-'}{fmt(tx.tutar)}
																				</td>
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

							{:else}
								<!-- Diğer ürün tipleri: Ödeme planı (ay ay akordiyon) -->
								{#if expandedPayments.length === 0}
									<p class="text-sm text-gray-500 py-4 text-center">Ödeme planı yok</p>
								{:else}
									{#if p.status === 'closed'}
										<div class="mb-2 text-[11px] sm:text-xs bg-indigo-50 border border-indigo-200 text-indigo-700 rounded-lg px-3 py-1.5">
											Bu kredi {p.closed_date ? fmtDate(p.closed_date) + ' tarihinde' : ''} kapatıldı.
											Ödenmemiş taksitler nakit akım tablosundan çıkarıldı (kayıtlar referans için korunuyor).
										</div>
									{/if}
									{@const today = new Date().toISOString().split('T')[0]}
									<div class="space-y-1.5">
										{#each paymentMonths as grp (grp.ym)}
											{@const open = expandedMonths.has(grp.ym)}
											<div class="border border-gray-200 rounded-lg overflow-hidden bg-white">
												<!-- Ay başlığı -->
												<button
													type="button"
													onclick={() => toggleMonth(grp.ym)}
													class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 cursor-pointer"
													aria-expanded={open}
												>
													<ChevronRight size={14} class="shrink-0 text-gray-500 transition-transform {open ? 'rotate-90' : ''}" />
													<span class="font-semibold text-xs sm:text-sm text-gray-700 w-20 sm:w-24 shrink-0">{grp.label}</span>
													<span class="text-[10px] sm:text-xs text-gray-500 shrink-0">{grp.paidCount}/{grp.count}</span>
													{#if grp.hasOverdue}
														<span class="text-[10px] font-medium bg-red-100 text-red-700 px-1.5 py-0.5 rounded-full shrink-0">Gecikmiş</span>
													{:else if grp.unpaidTotal === 0}
														<span class="text-[10px] font-medium bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full shrink-0">Tamam</span>
													{/if}
													<span class="ml-auto text-xs sm:text-sm font-bold text-gray-800 whitespace-nowrap">{fmt(grp.total, p.currency)}</span>
												</button>
												<!-- Ay taksitleri -->
												{#if open}
													<div class="overflow-x-auto border-t border-gray-100">
														<table class="w-full text-sm">
															<thead>
																<tr class="text-xs text-gray-500 border-b bg-gray-50/60">
																	<th class="text-left py-1.5 px-2">#</th>
																	<th class="text-left py-1.5 px-2">Vade</th>
																	<th class="text-right py-1.5 px-2">Taksit</th>
																	<th class="text-right py-1.5 px-2 hidden sm:table-cell">Anapara</th>
																	<th class="text-right py-1.5 px-2 hidden sm:table-cell">Faiz</th>
																	<th class="text-right py-1.5 px-2 hidden sm:table-cell">BSMV</th>
																	<th class="text-right py-1.5 px-2 hidden sm:table-cell">Komisyon</th>
																	<th class="text-center py-1.5 px-2">Durum</th>
																	{#if canUse}<th class="text-center py-1.5 px-2 w-16"></th>{/if}
																</tr>
															</thead>
															<tbody>
																{#each grp.pays as pay (pay.id)}
																	{@const overdue = !pay.is_paid && pay.due_date < today}
																	<tr class="border-b border-gray-100 {overdue ? 'bg-red-50' : pay.is_paid ? 'bg-green-50/40' : ''}">
																		<td class="py-1.5 px-2 text-gray-500">{pay.installment_no || '-'}</td>
																		<td class="py-1.5 px-2 {overdue ? 'text-red-600 font-medium' : ''}">{fmtDate(pay.due_date)}</td>
																		<td class="py-1.5 px-2 text-right font-medium">{fmt(pay.amount, p.currency)}</td>
																		<td class="py-1.5 px-2 text-right text-gray-500 hidden sm:table-cell">{fmt(pay.principal, p.currency)}</td>
																		<td class="py-1.5 px-2 text-right text-gray-500 hidden sm:table-cell">{fmt(pay.interest, p.currency)}</td>
																		<td class="py-1.5 px-2 text-right text-gray-500 hidden sm:table-cell">{fmt(pay.bsmv, p.currency)}</td>
																		<td class="py-1.5 px-2 text-right text-gray-500 hidden sm:table-cell">{fmt(pay.commission, p.currency)}</td>
																		<td class="py-1.5 px-2 text-center">
																			{#if pay.is_paid}
																				<span class="text-[10px] font-medium bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Ödendi</span>
																			{:else if p.status === 'closed'}
																				<span class="text-[10px] font-medium bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">Kapatıldı</span>
																			{:else if overdue}
																				<span class="text-[10px] font-medium bg-red-100 text-red-700 px-2 py-0.5 rounded-full">Gecikmiş</span>
																			{:else}
																				<span class="text-[10px] font-medium bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">Bekliyor</span>
																			{/if}
																		</td>
																		{#if canUse}
																			<td class="py-1.5 px-2 text-center">
																				<button onclick={() => togglePaid(pay)} class="text-teal-700 hover:text-teal-800 cursor-pointer align-middle" title={pay.is_paid ? 'Geri al' : 'Ödendi'} aria-label={pay.is_paid ? 'Geri al' : 'Ödendi'}>
																					{#if pay.is_paid}<RotateCcw size={14} class="inline-block" />{:else}<Check size={14} class="inline-block" />{/if}
																				</button>
																				<button onclick={() => deletePayment(pay.id)} class="text-red-500 hover:text-red-600 cursor-pointer ml-1.5 align-middle" title="Sil" aria-label="Sil"><X size={14} class="inline-block" /></button>
																			</td>
																		{/if}
																	</tr>
																{/each}
															</tbody>
														</table>
													</div>
												{/if}
											</div>
										{/each}
									</div>
								{/if}
							{/if}
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Ürün Ekle/Düzenle Modal -->
<Modal bind:show={showAddModal} title={editProduct ? 'Ürünü Düzenle' : 'Yeni Kredi Ürünü'} maxWidth="max-w-xl">
	<form onsubmit={(e) => { e.preventDefault(); saveProduct(); }} class="space-y-4">
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div>
				<label for="k-type" class="text-xs text-gray-500 mb-1 block">Tip</label>
				<Select id="k-type" bind:value={form.type} size="sm" disabled={!!editProduct}>
					{#each PRODUCT_TYPES as t}
						<option value={t}>{TYPE_LABELS[t]}</option>
					{/each}
				</Select>
			</div>
			<div>
				<label for="k-currency" class="text-xs text-gray-500 mb-1 block">Para Birimi</label>
				<Select id="k-currency" bind:value={form.currency} size="sm">
					<option value="TRY">TRY</option>
					<option value="USD">USD</option>
					<option value="EUR">EUR</option>
				</Select>
			</div>
		</div>
		<div>
			<label for="k-name" class="text-xs text-gray-500 mb-1 block">Ürün Adı</label>
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
			<div>
				<label for="k-total" class="text-xs text-gray-500 mb-1 block">Toplam Tutar</label>
				<MoneyInput id="k-total" bind:value={form.total_amount} currency={form.currency} min={0} placeholder="0,00" />
			</div>
			<div>
				<label for="k-remaining" class="text-xs text-gray-500 mb-1 block">Kalan Borç</label>
				<MoneyInput id="k-remaining" bind:value={form.remaining_amount} currency={form.currency} min={0} placeholder="0,00" />
			</div>
			<div>
				<label for="k-interest" class="text-xs text-gray-500 mb-1 block">Faiz Oranı (%)</label>
				<MoneyInput id="k-interest" bind:value={form.interest_rate} decimals={2} min={0} placeholder="ör: 2,45" />
			</div>
			<div>
				<label for="k-bsmv" class="text-xs text-gray-500 mb-1 block">BSMV Oranı (%)</label>
				<MoneyInput id="k-bsmv" bind:value={form.bsmv_rate} decimals={2} min={0} placeholder="ör: 5" />
			</div>
			<div>
				<label for="k-commission" class="text-xs text-gray-500 mb-1 block">Komisyon Oranı (%)</label>
				<MoneyInput id="k-commission" bind:value={form.commission_rate} decimals={2} min={0} placeholder="ör: 1" />
			</div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div>
				<label for="k-start" class="text-xs text-gray-500 mb-1 block">Başlangıç</label>
				<Input id="k-start" type="date" bind:value={form.start_date} size="sm" />
			</div>
			<div>
				<label for="k-end" class="text-xs text-gray-500 mb-1 block">Bitiş / Vade</label>
				<Input id="k-end" type="date" bind:value={form.end_date} size="sm" />
			</div>
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

<!-- Taksit Oluştur Modal -->
<Modal bind:show={showPaymentModal} title="Taksit Planı Oluştur" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); generatePayments(); }} class="space-y-4">
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div>
				<label for="kp-count" class="text-xs text-gray-500 mb-1 block">Taksit Sayısı</label>
				<Input id="kp-count" type="number" min="1" max="120" bind:value={paymentForm.count} size="sm" required />
			</div>
			<div>
				<label for="kp-start" class="text-xs text-gray-500 mb-1 block">İlk Taksit Tarihi</label>
				<Input id="kp-start" type="date" bind:value={paymentForm.start_date} size="sm" required />
			</div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div>
				<label for="kp-amount" class="text-xs text-gray-500 mb-1 block">Taksit Tutarı</label>
				<MoneyInput id="kp-amount" bind:value={paymentForm.amount} currency={form.currency} min={0} placeholder="0,00" required />
			</div>
			<div>
				<label for="kp-principal" class="text-xs text-gray-500 mb-1 block">Anapara</label>
				<MoneyInput id="kp-principal" bind:value={paymentForm.principal} currency={form.currency} min={0} placeholder="0,00" />
			</div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
			<div>
				<label for="kp-interest" class="text-xs text-gray-500 mb-1 block">Faiz</label>
				<MoneyInput id="kp-interest" bind:value={paymentForm.interest} currency={form.currency} min={0} placeholder="0,00" />
			</div>
			<div>
				<label for="kp-tax" class="text-xs text-gray-500 mb-1 block">Vergi (BSMV/KKDF)</label>
				<MoneyInput id="kp-tax" bind:value={paymentForm.tax} currency={form.currency} min={0} placeholder="0,00" />
			</div>
		</div>
		<div class="flex justify-end gap-2 pt-2">
			<Button type="button" variant="secondary" onclick={() => showPaymentModal = false}>İptal</Button>
			<Button type="submit">{paymentForm.count} Taksit Oluştur</Button>
		</div>
	</form>
</Modal>

<!-- Generic Silme Onayı -->
<ConfirmDialog
	bind:show={confirmState.show}
	title={confirmState.title}
	message={confirmState.message}
	confirmText="Sil"
	cancelText="Vazgeç"
	danger={true}
	onConfirm={confirmState.onConfirm}
/>

<!-- Kredi Kapatma Modal -->
<Modal bind:show={closeModal.show} title="Krediyi Kapat" maxWidth="max-w-md">
	<div class="space-y-4 text-sm">
		<div class="bg-indigo-50 border border-indigo-200 rounded-lg p-3 text-indigo-900 text-xs leading-snug">
			<strong>{closeModal.name}</strong> kapatılacak. Ödenmemiş ileri vadeli taksitler
			nakit akım tablosundan çıkarılır (taksit kayıtları referans için korunur).
			İşlem <strong>Yeniden Aç</strong> ile geri alınabilir.
		</div>
		<div>
			<label for="close-date" class="text-xs text-gray-500 mb-1 block">Kapanış Tarihi</label>
			<Input
				id="close-date"
				type="date"
				bind:value={closeModal.closedDate}
				size="sm"
			/>
		</div>
		<div class="flex items-center justify-end gap-2 pt-2">
			<Button variant="secondary" onclick={() => (closeModal = { show: false, id: null, name: '', closedDate: new Date().toISOString().split('T')[0] })}>Vazgeç</Button>
			<Button onclick={confirmClose}>Krediyi Kapat</Button>
		</div>
	</div>
</Modal>

<!-- Ödeme Planı Popup (banka kartından krediye tıklanınca) — sade: tarih · tutar · ödendi/ödenmedi -->
<Modal bind:show={planModal.show} title="Ödeme Planı" maxWidth="max-w-md">
	{#if planModal.product}
		{@const cur = planModal.product.currency}
		{@const isEurP = cur === 'EUR'}
		<div class="space-y-3">
			<div class="flex items-start justify-between gap-3 pb-3 border-b border-gray-100">
				<div class="min-w-0">
					<h3 class="font-semibold text-gray-800 leading-tight truncate">{planModal.product.name}</h3>
					<p class="text-xs text-gray-500 mt-0.5">{planModal.product.bank_name || planModal.product.company || ''}</p>
				</div>
				<div class="text-right shrink-0">
					<div class="text-[10px] text-gray-400 uppercase tracking-wide">Kalan</div>
					<div class="text-sm font-bold {isEurP ? 'text-blue-700' : 'text-gray-800'}">{fmt(planModal.product.remaining_amount, cur)}</div>
				</div>
			</div>

			{#if planModal.loading}
				<TableSkeleton rows={5} columns={4} showHeader={false} />
			{:else if planModal.payments.length === 0}
				<div class="py-10 text-center text-gray-500 text-sm">Bu kredi için taksit planı bulunmuyor.</div>
			{:else}
				{@const todayS = new Date().toISOString().split('T')[0]}
				{@const paidCount = planModal.payments.filter((p: any) => p.is_paid).length}
				<div class="flex items-center justify-between text-xs text-gray-500">
					<span>{planModal.payments.length} taksit</span>
					<span><span class="text-emerald-600 font-medium">{paidCount} ödendi</span> · {planModal.payments.length - paidCount} kalan</span>
				</div>
				<div class="max-h-[55vh] overflow-y-auto divide-y divide-gray-100 border border-gray-100 rounded-lg">
					{#each planModal.payments as pay (pay.id)}
						{@const overdue = !pay.is_paid && (pay.due_date || '') < todayS}
						<div class="flex items-center gap-3 px-3 py-2 {pay.is_paid ? 'bg-gray-50/40' : ''}">
							<span class="text-sm text-gray-600 tabular-nums w-[88px] shrink-0">{fmtDate(pay.due_date)}</span>
							<span class="text-sm font-semibold text-gray-800 tabular-nums flex-1 text-right">{fmt(pay.amount, cur)}</span>
							<div class="shrink-0 w-[84px] flex justify-end">
								{#if canUse}
									<button onclick={() => togglePaymentInModal(pay)} class="cursor-pointer" title={pay.is_paid ? 'Ödenmedi olarak işaretle' : 'Ödendi olarak işaretle'}>
										{#if pay.is_paid}<StatusBadge type="success">Ödendi</StatusBadge>{:else if overdue}<StatusBadge type="error">Gecikmiş</StatusBadge>{:else}<StatusBadge type="warning">Bekliyor</StatusBadge>{/if}
									</button>
								{:else if pay.is_paid}
									<StatusBadge type="success">Ödendi</StatusBadge>
								{:else if overdue}
									<StatusBadge type="error">Gecikmiş</StatusBadge>
								{:else}
									<StatusBadge type="warning">Bekliyor</StatusBadge>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</Modal>
