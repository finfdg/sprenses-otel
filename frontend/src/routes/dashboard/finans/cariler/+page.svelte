<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import type {
		Vendor, VendorDetail, VendorTransaction, VendorUpload,
		VendorUploadResult, WeeklyPaymentGroup, RemovalCandidate, BulkDeleteResult
	} from '$lib/types/vendor';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import PaymentInstructions from '$lib/components/finance/PaymentInstructions.svelte';
	import { Users, Landmark, Star, Trash2, Plus, Search, Loader2, CreditCard, Banknote, FileText, Scroll } from 'lucide-svelte';
	import Button from '$lib/components/Button.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';

	// Generic onay state
	let confirmState = $state<{ show: boolean; title: string; message: string; onConfirm: () => void | Promise<void> }>({
		show: false, title: '', message: '', onConfirm: () => {}
	});
	function askConfirm(title: string, message: string, onConfirm: () => void | Promise<void>) {
		confirmState = { show: true, title, message, onConfirm };
	}

	// ─── State ──────────────────────────────────────────
	let activeView = $state<'upload' | 'vendors' | 'schedule' | 'instructions'>('upload');

	// Upload
	let uploading = $state(false);
	let uploadResult = $state<VendorUploadResult | null>(null);
	let showUploadResult = $state(false);
	let uploads = $state<VendorUpload[]>([]);

	// Removal candidates (Excel'de olmayan kayıtlar)
	let selectedRemovalIds = $state<Set<number>>(new Set());
	let bulkDeleting = $state(false);

	// Vendors
	let vendors = $state<Vendor[]>([]);
	let vendorsLoading = $state(false);
	let vendorSearch = $state('');
	let vendorPage = $state(1);
	let vendorTotal = $state(0);
	let vendorPages = $state(1);
	const vendorPageSize = 50;

	// Sorting & filtering
	let sortBy = $state<string | null>('hesap_adi');
	let sortDir = $state<'asc' | 'desc'>('asc');
	let hideZero = $state(false);

	// Vendor detail
	let expandedVendor = $state<number | null>(null);
	let vendorDetail = $state<VendorDetail | null>(null);
	let vendorTransactions = $state<VendorTransaction[]>([]);
	let vtxLoading = $state(false);
	let vtxPage = $state(1);
	let vtxTotal = $state(0);
	let vtxPages = $state(1);

	// Summary
	let summary = $state<{ total_borc: number; total_alacak: number; bakiye: number; vendor_count: number; negative_count: number; negative_total: number } | null>(null);

	// Vendor detail tabs
	let detailTab = $state<'transactions' | 'bank'>('transactions');

	// Bank transactions linked to vendor
	interface BankTx {
		id: number;
		date: string;
		description: string;
		amount: number;
		type: string;
		bank_name: string;
		iban: string;
		receipt_no: string | null;
		tag_note: string | null;
	}
	let bankTxs = $state<BankTx[]>([]);
	let bankTxLoading = $state(false);
	let bankTxPage = $state(1);
	let bankTxTotal = $state(0);
	let bankTxPages = $state(1);

	// Payment schedule
	let schedule = $state<WeeklyPaymentGroup[]>([]);
	let scheduleLoading = $state(false);
	let expandedMonths = $state<Record<string, boolean>>({});
	let expandedWeeks = $state<Record<string, boolean>>({});
	let eurRate = $state<number>(0);

	const MONTH_NAMES = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	interface MonthPaymentGroup {
		key: string;
		label: string;
		weeks: WeeklyPaymentGroup[];
		total_amount: number;
		item_count: number;
	}

	// Haftalık grupları aylık akordion yapısına dönüştür
	function buildMonthlySchedule(weeks: WeeklyPaymentGroup[]): MonthPaymentGroup[] {
		const monthMap: Record<string, MonthPaymentGroup> = {};
		for (const week of weeks) {
			const d = new Date(week.friday_date + 'T00:00:00');
			const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
			if (!monthMap[key]) {
				monthMap[key] = {
					key,
					label: `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`,
					weeks: [],
					total_amount: 0,
					item_count: 0,
				};
			}
			monthMap[key].weeks.push(week);
			monthMap[key].total_amount += week.total_amount;
			monthMap[key].item_count += week.items.length;
		}
		return Object.values(monthMap).sort((a, b) => a.key.localeCompare(b.key));
	}

	let monthlySchedule = $derived(buildMonthlySchedule(schedule));

	const canUse = hasPermission('finance.cariler', 'use');

	// Department assignment
	interface DeptOption {
		id: number;
		name: string;
		code: string;
		manager_name: string | null;
	}
	interface CatOption {
		id: number;
		name: string;
		type: string;
	}
	let departments = $state<DeptOption[]>([]);
	let budgetCategories = $state<CatOption[]>([]);
	let showDeptAssignModal = $state(false);
	let deptAssignTxId = $state<number | null>(null);
	let deptAssignTxDesc = $state('');
	let deptAssignTxAmount = $state('');
	let selectedDeptId = $state<number | null>(null);
	let selectedCatId = $state<number | null>(null);
	let deptAssigning = $state(false);

	// Ödeme talimatına ekleme (cari satırından hızlı ekle)
	let addToListModal = $state<{ show: boolean; vendor: Vendor | null }>({ show: false, vendor: null });
	let piLists = $state<{ id: number; name: string; item_count: number }[]>([]);
	let piSelectedListId = $state<number | ''>('');
	let piNewListName = $state('');
	let piAdding = $state(false);

	async function openAddToList(vendor: Vendor) {
		addToListModal = { show: true, vendor };
		piSelectedListId = '';
		piNewListName = '';
		try {
			piLists = await api.get('/finance/payment-instructions/');
			if (piLists.length > 0) piSelectedListId = piLists[0].id;
		} catch (e) {
			console.error('Talimat listeleri alınamadı:', e);
		}
	}

	async function confirmAddToList() {
		const vendor = addToListModal.vendor;
		if (!vendor) return;
		const newName = piNewListName.trim();
		if (!newName && !piSelectedListId) {
			showToast('Liste seçin veya yeni liste adı girin', 'warning');
			return;
		}
		// Negatif bakiye = ödeyeceğimiz tutar
		const payAmount = vendor.bakiye < 0 ? Math.abs(vendor.bakiye) : 0;
		const item = {
			vendor_id: vendor.id,
			hesap_kodu: vendor.hesap_kodu,
			hesap_adi: vendor.hesap_adi,
			amount: payAmount,
			balance_snapshot: vendor.bakiye,
		};
		piAdding = true;
		try {
			if (newName) {
				await api.post('/finance/payment-instructions/', { name: newName, items: [item] });
				showToast(`"${newName}" listesi oluşturuldu ve cari eklendi`, 'success');
			} else {
				const res = await api.post<any>(`/finance/payment-instructions/${piSelectedListId}/items`, { items: [item] });
				if (res.skipped > 0) {
					showToast('Bu cari zaten listede', 'info');
				} else {
					const listName = piLists.find((l) => l.id === piSelectedListId)?.name || 'liste';
					showToast(`"${vendor.hesap_adi}" → ${listName}`, 'success');
				}
			}
			addToListModal = { show: false, vendor: null };
		} catch (e) {
			console.error('Talimata ekleme hatası:', e);
			showToast('Cari talimata eklenemedi', 'error');
		} finally {
			piAdding = false;
		}
	}

	async function loadDepartments() {
		try {
			departments = await api.get<DeptOption[]>('/finance/departmanlar/');
		} catch (err) {
			console.error('Departmanlar yüklenemedi:', err);
		}
	}

	async function loadBudgetCategories() {
		try {
			budgetCategories = await api.get<CatOption[]>('/finance/butce/categories');
		} catch (err) {
			console.error('Bütçe kategorileri yüklenemedi:', err);
		}
	}

	function openDeptAssign(tx: VendorTransaction) {
		deptAssignTxId = tx.id;
		deptAssignTxDesc = tx.description || tx.evrak_no || '';
		deptAssignTxAmount = tx.alacak > 0
			? formatCurrency(tx.alacak)
			: formatCurrency(tx.borc);
		selectedDeptId = tx.department_id || null;
		selectedCatId = tx.budget_category_id || null;
		showDeptAssignModal = true;
		if (departments.length === 0) loadDepartments();
		if (budgetCategories.length === 0) loadBudgetCategories();
	}

	async function assignDepartment() {
		if (!deptAssignTxId || !selectedDeptId || deptAssigning) return;
		deptAssigning = true;
		try {
			const body: Record<string, number> = { department_id: selectedDeptId };
			if (selectedCatId) body.budget_category_id = selectedCatId;
			await api.post('/finance/onay/assign/' + deptAssignTxId, body);
			// Update local state
			const tx = vendorTransactions.find((t) => t.id === deptAssignTxId);
			if (tx) {
				tx.department_id = selectedDeptId;
				tx.budget_category_id = selectedCatId;
				tx.dept_status = 'pending';
				tx.department_name = departments.find((d) => d.id === selectedDeptId)?.name || null;
				tx.budget_category_name = selectedCatId ? budgetCategories.find((c) => c.id === selectedCatId)?.name || null : null;
				vendorTransactions = [...vendorTransactions];
			}
			showDeptAssignModal = false;
			showToast('Departman ataması yapıldı, onaya gönderildi', 'success');
		} catch (err: any) {
			console.error('Departman ataması başarısız:', err);
			showToast(err?.message || 'Departman atanamadı', 'error');
		} finally {
			deptAssigning = false;
		}
	}

	async function removeDeptAssignment(txId: number) {
		try {
			await api.post('/finance/onay/remove/' + txId, {});
			const tx = vendorTransactions.find((t) => t.id === txId);
			if (tx) {
				tx.department_id = null;
				tx.budget_category_id = null;
				tx.dept_status = null;
				tx.department_name = null;
				tx.budget_category_name = null;
				tx.dept_assigned_by_name = null;
				tx.dept_assigned_at = null;
				tx.dept_rejection_note = null;
				vendorTransactions = [...vendorTransactions];
			}
			showToast('Departman ataması kaldırıldı', 'success');
		} catch (err: any) {
			console.error('Atama kaldırma başarısız:', err);
			showToast(err?.message || 'Atama kaldırılamadı', 'error');
		}
	}

	// ─── Formatters ─────────────────────────────────────
	function formatCurrency(amount: number): string {
		return new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(amount);
	}

	function formatEur(tryAmount: number): string {
		if (!eurRate || eurRate <= 0) return '';
		return new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'EUR' }).format(tryAmount / eurRate);
	}

	function formatDate(dateStr: string): string {
		const d = new Date(dateStr);
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}

	function formatDateLong(dateStr: string): string {
		const d = new Date(dateStr);
		return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric', weekday: 'long' });
	}

	function formatDateTime(dateStr: string): string {
		const d = new Date(dateStr);
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	}

	// ─── Summary ────────────────────────────────────────
	async function loadSummary() {
		try {
			summary = await api.get('/finance/cariler/vendors/summary');
		} catch (err) {
			console.error('Özet alınamadı:', err);
		}
	}

	// ─── Upload ─────────────────────────────────────────
	async function loadUploads() {
		try {
			uploads = await api.get<VendorUpload[]>('/finance/cariler/uploads');
		} catch (err) {
			console.error('Yükleme geçmişi alınamadı:', err);
		}
	}

	async function handleFile(file: File) {
		const ext = file.name.split('.').pop()?.toLowerCase();
		if (ext !== 'xls' && ext !== 'xlsx') {
			showToast('Sadece .xls ve .xlsx dosyaları kabul edilir', 'error');
			return;
		}

		uploading = true;
		try {
			const formData = new FormData();
			formData.append('file', file);
			const result = await api.upload<VendorUploadResult>('/finance/cariler/upload', formData);
			uploadResult = result;
			// Aday geldi → varsayılan tüm adaylar seçili (kullanıcı checkbox ile çıkarabilir)
			selectedRemovalIds = new Set(result.removal_candidates.map(c => c.id));
			showUploadResult = true;
			await loadUploads();
			const removalMsg = result.removal_candidates.length > 0
				? ` · ${result.removal_candidates.length} kayıt artık kaynakta yok`
				: '';
			showToast(`${result.new_transactions} yeni işlem yüklendi${removalMsg}`, 'success');
		} catch (err: any) {
			console.error('Dosya yükleme hatası:', err);
			showToast(err?.message || 'Dosya yüklenirken hata oluştu', 'error');
		} finally {
			uploading = false;
		}
	}

	// Not: Sedna içe aktarma artık Topbar'daki merkezi "Sedna" butonundan yapılır.

	// ─── Removal Candidates ─────────────────────────────
	function toggleRemovalSelection(id: number) {
		const next = new Set(selectedRemovalIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedRemovalIds = next;
	}

	function toggleAllRemovals() {
		if (!uploadResult) return;
		if (selectedRemovalIds.size === uploadResult.removal_candidates.length) {
			selectedRemovalIds = new Set();
		} else {
			selectedRemovalIds = new Set(uploadResult.removal_candidates.map(c => c.id));
		}
	}

	async function executeBulkDelete() {
		if (!uploadResult || selectedRemovalIds.size === 0) return;
		const ids = Array.from(selectedRemovalIds);
		bulkDeleting = true;
		try {
			const res = await api.post<BulkDeleteResult>('/finance/cariler/transactions/bulk-delete', { ids });
			let msg = `${res.deleted} kayıt silindi`;
			if (res.skipped > 0) {
				msg += ` · ${res.skipped} atlandı (${res.skipped_reasons.join(', ')})`;
			}
			showToast(msg, res.deleted > 0 ? 'success' : 'info');
			// Modal'ı kapat ve özet/listeyi yenile
			showUploadResult = false;
			uploadResult = null;
			selectedRemovalIds = new Set();
			await loadSummary();
			if (activeView === 'vendors') await loadVendors();
		} catch (err: any) {
			console.error('Toplu silme hatası:', err);
			showToast(err?.message || 'Silme sırasında hata oluştu', 'error');
		} finally {
			bulkDeleting = false;
		}
	}

	function confirmBulkDelete() {
		const count = selectedRemovalIds.size;
		if (count === 0) {
			showToast('Silmek için kayıt seçilmedi', 'info');
			return;
		}
		askConfirm(
			'Seçili Kayıtları Sil',
			`${count} cari işlem silinecek. Bu işlem geri alınamaz. Devam etmek istiyor musunuz?`,
			executeBulkDelete,
		);
	}

	function handleFileSelect(files: File[]) {
		if (files.length > 0) handleFile(files[0]);
	}

	function handleDropError(errors: string[]) {
		for (const err of errors) showToast(err, 'error', 4000);
	}

	function deleteUpload(id: number) {
		askConfirm('Yüklemeyi Sil', 'Bu yükleme ve ilişkili tüm işlemler silinecek. Devam etmek istiyor musunuz?', async () => {
			try {
				await api.delete(`/finance/cariler/uploads/${id}`);
				await loadUploads();
				showToast('Yükleme silindi', 'success');
			} catch (err) {
				console.error('Yükleme silme hatası:', err);
				showToast('Yükleme silinemedi', 'error');
			}
		});
	}

	// ─── Vendors ────────────────────────────────────────
	async function loadVendors() {
		vendorsLoading = true;
		try {
			const params = new URLSearchParams({
				page: String(vendorPage),
				page_size: String(vendorPageSize),
			});
			if (vendorSearch) params.set('search', vendorSearch);
			if (sortBy) {
				params.set('sort_by', sortBy);
				params.set('sort_dir', sortDir);
			}
			if (hideZero) params.set('hide_zero', 'true');
			const res = await api.get<any>(`/finance/cariler/vendors?${params}`);
			vendors = res.items;
			vendorTotal = res.total;
			vendorPages = res.pages;
		} catch (err) {
			console.error('Cari listesi alınamadı:', err);
		} finally {
			vendorsLoading = false;
		}
	}

	function toggleSort(column: string) {
		if (sortBy === column) {
			if (sortDir === 'asc') {
				sortDir = 'desc';
			} else {
				sortBy = null;
				sortDir = 'asc';
			}
		} else {
			sortBy = column;
			sortDir = 'asc';
		}
		vendorPage = 1;
		loadVendors();
	}

	function toggleHideZero() {
		hideZero = !hideZero;
		vendorPage = 1;
		loadVendors();
	}

	let searchTimeout: ReturnType<typeof setTimeout>;
	function onSearchInput() {
		clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			vendorPage = 1;
			loadVendors();
		}, 300);
	}

	async function markAsDevir(vtxId: number) {
		try {
			await api.patch(`/finance/cariler/transactions/${vtxId}/devir`, {});
			showToast('Avans/devir olarak işaretlendi', 'success');
			if (expandedVendor) await loadVendorDetail(expandedVendor);
			await loadVendors();
		} catch (err: any) {
			console.error('Devir işaretleme hatası:', err);
			showToast(err?.body?.detail || 'İşaretleme başarısız', 'error');
		}
	}

	// ─── Eşleştirme Kaldırma ───────────────────────────
	function unmatchTransaction(vtxId: number, paymentMethod: string) {
		askConfirm('Eşleştirmeyi Kaldır', 'Bu eşleştirmeyi kaldırmak istediğinize emin misiniz?', async () => {
			try {
				if (paymentMethod === 'cek') {
					await api.delete(`/finance/cariler/transactions/${vtxId}/unmatch-check`);
				} else {
					await api.delete(`/finance/cariler/transactions/${vtxId}/unmatch`);
				}
				showToast('Eşleştirme kaldırıldı', 'success');
				if (expandedVendor) await loadVendorDetail(expandedVendor);
				await loadVendors();
			} catch (err: any) {
				console.error('Eşleştirme kaldırma hatası:', err);
				showToast(err?.message || 'Eşleştirme kaldırılamadı', 'error');
			}
		});
	}

	// ─── Çek Eşleştirme ────────────────────────────────
	interface CandidateCheck {
		id: number;
		check_no: string;
		vendor_name: string;
		vendor_code: string | null;
		due_date: string;
		amount_tl: number;
		currency: string;
		amount_currency: number | null;
		description: string | null;
		score: number;
	}

	let showCheckMatch = $state(false);
	let checkMatchVtxId = $state<number | null>(null);
	let checkMatchVtxAmount = $state(0);
	let candidateChecks = $state<CandidateCheck[]>([]);
	let checksLoading = $state(false);
	let checkSearch = $state('');

	let filteredChecks = $derived(() => {
		if (!checkSearch) return candidateChecks;
		const q = checkSearch.toLowerCase();
		return candidateChecks.filter(c =>
			c.check_no?.toLowerCase().includes(q) ||
			c.vendor_name?.toLowerCase().includes(q) ||
			c.description?.toLowerCase().includes(q)
		);
	});

	async function openCheckMatch(vtxId: number, amount: number) {
		checkMatchVtxId = vtxId;
		checkMatchVtxAmount = amount;
		showCheckMatch = true;
		checksLoading = true;
		checkSearch = '';
		try {
			candidateChecks = await api.get<CandidateCheck[]>(`/finance/cariler/transactions/${vtxId}/candidate-checks`);
		} catch (err) {
			console.error('Çek listesi alınamadı:', err);
			showToast('Çek listesi alınamadı', 'error');
		} finally {
			checksLoading = false;
		}
	}

	async function matchWithCheck(checkId: number) {
		if (!checkMatchVtxId) return;
		try {
			const result = await api.post<any>(`/finance/cariler/transactions/${checkMatchVtxId}/match-check/${checkId}`, {});
			showToast(`Çek #${result.check_no} ile eşleştirildi`, 'success');
			showCheckMatch = false;
			if (expandedVendor) await loadVendorDetail(expandedVendor);
			await loadVendors();
		} catch (err: any) {
			console.error('Çek eşleştirme hatası:', err);
			showToast(err?.message || 'Eşleştirme başarısız', 'error');
		}
	}

	async function toggleVendorDetail(vendorId: number) {
		if (expandedVendor === vendorId) {
			expandedVendor = null;
			vendorDetail = null;
			vendorTransactions = [];
			bankTxs = [];
			detailTab = 'transactions';
			return;
		}
		expandedVendor = vendorId;
		vtxPage = 1;
		bankTxPage = 1;
		detailTab = 'transactions';
		bankTxs = [];
		bankTxTotal = 0;
		vendorIbans = [];
		ibanForm = { bank_name: '', iban: '', account_holder: '' };
		await loadVendorDetail(vendorId);
		loadVendorIbans(vendorId);
		// Banka sayısını arka planda al (sekme badge'i için)
		loadBankTransactions(vendorId);
	}

	async function loadVendorDetail(vendorId: number) {
		vtxLoading = true;
		try {
			const res = await api.get<any>(`/finance/cariler/vendors/${vendorId}?page=${vtxPage}&page_size=50`);
			vendorDetail = res.vendor;
			vendorTransactions = res.transactions.items;
			vtxTotal = res.transactions.total;
			vtxPages = res.transactions.pages;
		} catch (err) {
			console.error('Cari detay alınamadı:', err);
		} finally {
			vtxLoading = false;
		}
	}

	// ─── Cari Banka / IBAN yönetimi ─────────────────────────
	type VIban = { id: number; bank_name: string | null; iban: string; account_holder: string | null; is_default: boolean };
	let vendorIbans = $state<VIban[]>([]);
	let ibanForm = $state({ bank_name: '', iban: '', account_holder: '' });
	let ibanSaving = $state(false);
	function fmtIbanDisplay(s: string | null): string {
		const v = (s || '').replace(/\s+/g, '');
		return v ? (v.match(/.{1,4}/g) || []).join(' ') : '';
	}
	async function loadVendorIbans(vendorId: number) {
		try { vendorIbans = await api.get<VIban[]>(`/finance/cariler/vendors/${vendorId}/bank-accounts`); }
		catch (e) { console.error('IBAN listesi alınamadı:', e); vendorIbans = []; }
	}
	async function addVendorIban(vendorId: number) {
		if (!ibanForm.iban.trim()) { showToast('IBAN girin', 'error'); return; }
		ibanSaving = true;
		try {
			await api.post(`/finance/cariler/vendors/${vendorId}/bank-accounts`, {
				bank_name: ibanForm.bank_name.trim() || null,
				iban: ibanForm.iban.trim(),
				account_holder: ibanForm.account_holder.trim() || null,
			});
			ibanForm = { bank_name: '', iban: '', account_holder: '' };
			await loadVendorIbans(vendorId);
			showToast('IBAN eklendi', 'success');
		} catch (e: any) {
			showToast(e?.message || 'IBAN eklenemedi', 'error');
		} finally { ibanSaving = false; }
	}
	async function setDefaultIban(vendorId: number, id: number) {
		try { await api.patch(`/finance/cariler/vendors/${vendorId}/bank-accounts/${id}`, { is_default: true }); await loadVendorIbans(vendorId); }
		catch (e) { console.error(e); showToast('Varsayılan yapılamadı', 'error'); }
	}
	async function deleteVendorIban(vendorId: number, id: number) {
		try { await api.delete(`/finance/cariler/vendors/${vendorId}/bank-accounts/${id}`); await loadVendorIbans(vendorId); showToast('IBAN silindi', 'success'); }
		catch (e) { console.error(e); showToast('Silinemedi', 'error'); }
	}

	// ─── Bank Transactions ─────────────────────────────
	async function loadBankTransactions(vendorId: number) {
		bankTxLoading = true;
		try {
			const res = await api.get<any>(`/finance/cariler/vendors/${vendorId}/bank-transactions?page=${bankTxPage}&page_size=50`);
			bankTxs = res.items;
			bankTxTotal = res.total;
			bankTxPages = res.pages;
		} catch (err) {
			console.error('Banka işlemleri alınamadı:', err);
			bankTxs = [];
		} finally {
			bankTxLoading = false;
		}
	}

	// ─── Payment Days Edit ─────────────────────────────
	let editingPaymentDays = $state<number | null>(null);
	let paymentDaysValue = $state(90);
	let savingPaymentDays = $state(false);

	function startEditPaymentDays(vendor: Vendor) {
		editingPaymentDays = vendor.id;
		paymentDaysValue = vendor.payment_days;
	}

	function cancelEditPaymentDays() {
		editingPaymentDays = null;
	}

	async function savePaymentDays(vendorId: number) {
		if (paymentDaysValue < 0) {
			showToast('Ödeme vadesi negatif olamaz', 'error');
			return;
		}
		savingPaymentDays = true;
		try {
			await api.patch(`/finance/cariler/vendors/${vendorId}/payment-days`, { payment_days: paymentDaysValue });
			// Listeyi güncelle
			const v = vendors.find(v => v.id === vendorId);
			if (v) v.payment_days = paymentDaysValue;
			if (vendorDetail && vendorDetail.id === vendorId) {
				vendorDetail.payment_days = paymentDaysValue;
			}
			editingPaymentDays = null;
			showToast('Ödeme vadesi güncellendi', 'success');
			// Ödeme planı cache'ini sıfırla — yeni vade tarihleri hesaplandı
			schedule = [];
			if (activeView === 'schedule') {
				loadSchedule();
			}
		} catch (err) {
			console.error('Ödeme vadesi güncellenemedi:', err);
			showToast('Ödeme vadesi güncellenemedi', 'error');
		} finally {
			savingPaymentDays = false;
		}
	}

	// ─── Firma Durumu ─────────────────────────────────
	let savingStatus = $state(false);

	function toggleVendorStatus(vendor: Vendor) {
		if (savingStatus) return;
		const newStatus = vendor.status === 'odeme_yasaklisi' ? 'normal' : 'odeme_yasaklisi';
		const label = newStatus === 'odeme_yasaklisi' ? 'Ödeme Yasaklısı' : 'Normal';
		askConfirm(
			'Firma Durumunu Değiştir',
			`${vendor.hesap_adi} firmasının durumu "${label}" olarak değiştirilecek. Devam etmek istiyor musunuz?`,
			async () => {
				savingStatus = true;
				try {
					await api.patch(`/finance/cariler/vendors/${vendor.id}/status`, { status: newStatus });
					vendor.status = newStatus;
					vendors = [...vendors];
					if (vendorDetail && vendorDetail.id === vendor.id) {
						vendorDetail.status = newStatus;
					}
					showToast(`Firma durumu "${label}" olarak güncellendi`, 'success');
					// Ödeme planı cache'ini sıfırla
					schedule = [];
					if (activeView === 'schedule') {
						loadSchedule();
					}
				} catch (err: any) {
					console.error('Firma durumu güncellenemedi:', err);
					showToast(err?.message || 'Firma durumu güncellenemedi', 'error');
				} finally {
					savingStatus = false;
				}
			}
		);
	}

	// ─── Payment Schedule ───────────────────────────────
	async function loadSchedule() {
		scheduleLoading = true;
		try {
			const [scheduleData, ratesData] = await Promise.all([
				api.get<WeeklyPaymentGroup[]>('/finance/cariler/payment-schedule'),
				api.get<any>('/finance/exchange-rates/latest'),
			]);
			schedule = scheduleData;
			const eurRateObj = ratesData?.rates?.find((r: any) => r.currency_code === 'EUR');
			eurRate = eurRateObj?.forex_selling ?? eurRateObj?.forex_buying ?? 0;
		} catch (err) {
			console.error('Ödeme planı alınamadı:', err);
		} finally {
			scheduleLoading = false;
		}
	}

	function toggleWeek(fridayDate: string) {
		expandedWeeks[fridayDate] = !expandedWeeks[fridayDate];
	}

	function toggleMonth(monthKey: string) {
		expandedMonths[monthKey] = !expandedMonths[monthKey];
	}

	// ─── Excel İndir ───────────────────────────────────
	async function downloadExcel(type: 'vendors' | 'payment-schedule') {
		try {
			const res = await api.fetchRaw(`/finance/cariler/export/${type}`);
			if (!res.ok) throw new Error('İndirme başarısız');
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = type === 'vendors' ? 'cariler.xlsx' : 'odeme-plani.xlsx';
			a.click();
			URL.revokeObjectURL(url);
		} catch (err) {
			console.error('Excel indirme hatası:', err);
			showToast('Excel dosyası indirilemedi', 'error');
		}
	}

	// Tab değişince veri yükle
	$effect(() => {
		if (activeView === 'vendors' && vendors.length === 0) {
			loadVendors();
		} else if (activeView === 'schedule' && schedule.length === 0) {
			loadSchedule();
		}
	});

	// Toplam ödeme ve kümülatif hesaplama
	let totalScheduleAmount = $derived(schedule.reduce((sum, g) => sum + g.total_amount, 0));
	let cumulativeAmounts = $derived(schedule.reduce<number[]>((acc, g, i) => {
		acc.push((acc[i - 1] || 0) + g.total_amount);
		return acc;
	}, []));

	let unsubFinance: (() => void) | null = null;

	onMount(async () => {
		loadUploads();
		loadSummary();

		// URL'den vendor parametresi varsa direkt o cariyi aç
		const vendorParam = $page.url.searchParams.get('vendor');
		if (vendorParam) {
			activeView = 'vendors';
			await loadVendors();
			const vid = parseInt(vendorParam);
			if (vid) {
				toggleVendorDetail(vid);
				// Scroll
				requestAnimationFrame(() => {
					const el = document.querySelector(`[data-vendor-id="${vid}"]`);
					el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
				});
			}
		}

		// Finans güncelleme event'ini dinle — başka kullanıcı değişiklik yapınca otomatik yenile
		unsubFinance = onWsEvent('finance_updated', () => {
			loadSummary();
			if (activeView === 'vendors') loadVendors();
			if (activeView === 'upload') loadUploads();
		});
	});

	onDestroy(() => {
		unsubFinance?.();
	});
</script>

<svelte:head>
	<title>Cariler | Sprenses</title>
</svelte:head>

<div class="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
	<!-- Başlık -->
	<PageHeader title="Cariler" description="Cari hesap yönetimi ve ödeme planı" />

	<!-- Özet Kartları -->
	{#if summary}
		<div class="flex flex-wrap gap-3 sm:gap-4">
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-3 sm:p-5 flex-1 min-w-[140px]">
				<p class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Toplam Borç</p>
				<p class="text-base sm:text-xl font-bold text-rose-600 mt-1 sm:mt-2">{formatCurrency(summary.total_borc)}</p>
			</div>
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-3 sm:p-5 flex-1 min-w-[140px]">
				<p class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Toplam Alacak</p>
				<p class="text-base sm:text-xl font-bold text-emerald-600 mt-1 sm:mt-2">{formatCurrency(summary.total_alacak)}</p>
			</div>
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-3 sm:p-5 flex-1 min-w-[140px]">
				<p class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Net Bakiye</p>
				<p class="text-base sm:text-xl font-bold mt-1 sm:mt-2 {summary.bakiye > 0 ? 'text-rose-600' : summary.bakiye < 0 ? 'text-emerald-600' : 'text-gray-500'}">{formatCurrency(summary.bakiye)}</p>
			</div>
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-3 sm:p-5 flex-1 min-w-[140px]">
				<p class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Cari Borçları</p>
				<p class="text-base sm:text-xl font-bold text-amber-600 mt-1 sm:mt-2">{formatCurrency(Math.abs(summary.negative_total))}</p>
				<p class="text-[10px] text-gray-500 mt-0.5">{summary.negative_count} cari</p>
			</div>
			<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-3 sm:p-5 flex-1 min-w-[140px]">
				<p class="text-[10px] sm:text-xs font-medium text-gray-500 uppercase tracking-wider">Cari Sayısı</p>
				<p class="text-base sm:text-xl font-bold text-gray-900 mt-1 sm:mt-2">{summary.vendor_count}</p>
			</div>
		</div>
	{/if}

	<!-- Tab Bar -->
	<div class="flex items-center justify-between">
		<div class="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
			<button
				onclick={() => activeView = 'upload'}
				class="px-4 py-2 rounded-lg text-sm font-medium transition-colors {activeView === 'upload' ? 'bg-white text-teal-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'}"
			>
				Dosya Yükle
			</button>
			<button
				onclick={() => activeView = 'vendors'}
				class="px-4 py-2 rounded-lg text-sm font-medium transition-colors {activeView === 'vendors' ? 'bg-white text-teal-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'}"
			>
				Cariler
			</button>
			<button
				onclick={() => activeView = 'schedule'}
				class="px-4 py-2 rounded-lg text-sm font-medium transition-colors {activeView === 'schedule' ? 'bg-white text-teal-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'}"
			>
				Ödeme Planı
			</button>
			<button
				onclick={() => activeView = 'instructions'}
				class="px-4 py-2 rounded-lg text-sm font-medium transition-colors {activeView === 'instructions' ? 'bg-white text-teal-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'}"
			>
				Ödeme Talimatı
			</button>
		</div>

		<!-- Excel İndir -->
		{#if activeView === 'vendors' || activeView === 'schedule'}
			<button
				onclick={() => downloadExcel(activeView === 'vendors' ? 'vendors' : 'payment-schedule')}
				class="flex items-center gap-2 px-3 py-2 text-sm font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl hover:bg-emerald-100 transition-colors"
			>
				<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
				</svg>
				Excel İndir
			</button>
		{/if}
	</div>

	<!-- ═══ DOSYA YÜKLE ═══ -->
	{#if activeView === 'upload'}
		<div class="space-y-6">

			<!-- Sürükle-Bırak Alan -->
			{#if canUse}
				<div class="relative">
					{#if uploading}
						<div class="absolute inset-0 z-10 bg-white/80 rounded-xl flex items-center justify-center">
							<div class="flex items-center gap-2 text-teal-700">
								<Loader2 size={20} class="animate-spin" />
								<span class="text-sm font-medium">Yükleniyor...</span>
							</div>
						</div>
					{/if}
					<FileDropzone
						accept=".xls,.xlsx"
						maxSize={50 * 1024 * 1024}
						disabled={uploading}
						label="Cari Excel dosyasını sürükleyin veya tıklayın"
						hint="Desteklenen formatlar: .xls, .xlsx — maks. 50 MB"
						onSelect={handleFileSelect}
						onError={handleDropError}
					/>
				</div>
			{/if}

			<!-- Yükleme Geçmişi -->
			{#if uploads.length > 0}
				<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
					<div class="px-5 py-4 border-b border-gray-100">
						<h3 class="font-semibold text-gray-900">Yükleme Geçmişi</h3>
					</div>
					<div class="divide-y divide-gray-100">
						{#each uploads as upload}
							<div class="px-5 py-4 flex items-center justify-between">
								<div class="flex-1 min-w-0">
									<p class="text-sm font-medium text-gray-900 truncate">{upload.file_name}</p>
									<div class="flex items-center gap-3 mt-1 text-xs text-gray-500">
										<span>{upload.total_vendors} cari</span>
										<span class="text-gray-500">|</span>
										<span class="text-emerald-600">{upload.new_transactions} yeni</span>
										{#if upload.skipped_transactions > 0}
											<span class="text-gray-500">|</span>
											<span class="text-amber-600">{upload.skipped_transactions} mükerrer</span>
										{/if}
										<span class="text-gray-500">|</span>
										<span>{formatDateTime(upload.uploaded_at)}</span>
										{#if upload.uploader_name}
											<span class="text-gray-500">|</span>
											<span>{upload.uploader_name}</span>
										{/if}
									</div>
								</div>
								{#if canUse}
									<button
										onclick={() => deleteUpload(upload.id)}
										class="ml-3 p-2 text-gray-500 hover:text-red-600 transition-colors rounded-lg hover:bg-red-50"
										title="Sil"
									>
										<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
											<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
										</svg>
									</button>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- ═══ CARİLER ═══ -->
	{#if activeView === 'vendors'}
		<div class="space-y-4">
			<!-- Arama + Filtre -->
			<div class="flex items-center gap-3 flex-wrap">
				<Input
					type="search"
					icon={Search}
					bind:value={vendorSearch}
					oninput={onSearchInput}
					placeholder="Hesap kodu veya cari adı ara..."
					fullWidth={false}
					class="flex-1 max-w-md"
				/>
				<button
					onclick={toggleHideZero}
					class="flex items-center gap-2 px-3 py-2.5 text-sm border rounded-xl transition-colors
						{hideZero ? 'bg-teal-50 border-teal-300 text-teal-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}"
				>
					<div class="relative w-8 h-4 rounded-full transition-colors {hideZero ? 'bg-teal-500' : 'bg-gray-300'}">
						<div class="absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform {hideZero ? 'translate-x-4' : 'translate-x-0.5'}"></div>
					</div>
					<span class="whitespace-nowrap">Sıfır bakiyeleri gizle</span>
				</button>
				<span class="text-sm text-gray-500">{vendorTotal} cari</span>
			</div>

			<!-- Tablo -->
			{#if vendorsLoading}
				<TableSkeleton rows={6} columns={4} />
			{:else if vendors.length === 0}
				<EmptyState icon={Users} title="Henüz cari kaydı bulunmuyor" description="Yukarıdan Excel dosyası yükleyerek başlayın" />
				<div class="hidden">
					<p class="text-xs mt-1">Dosya yükleyerek cari kayıtlarını oluşturabilirsiniz</p>
				</div>
			{:else}
				<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
					<!-- Desktop Header -->
					<div class="hidden lg:grid grid-cols-12 gap-2 px-5 py-3 bg-gray-50 border-b border-gray-200 text-xs font-medium text-gray-500 uppercase tracking-wider select-none">
						<div class="col-span-2">Hesap Kodu</div>
						<button class="col-span-2 flex items-center gap-1 cursor-pointer hover:text-gray-700" onclick={() => toggleSort('hesap_adi')}>
							Hesap Adı
							{#if sortBy === 'hesap_adi'}
								<svg class="w-3 h-3 {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
							{/if}
						</button>
						<div class="col-span-1 text-center">Vade</div>
						<div class="col-span-1 text-center">Durum</div>
						<button class="col-span-2 flex items-center gap-1 justify-end cursor-pointer hover:text-gray-700" onclick={() => toggleSort('total_borc')}>
							Borç
							{#if sortBy === 'total_borc'}
								<svg class="w-3 h-3 {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
							{/if}
						</button>
						<button class="col-span-2 flex items-center gap-1 justify-end cursor-pointer hover:text-gray-700" onclick={() => toggleSort('total_alacak')}>
							Alacak
							{#if sortBy === 'total_alacak'}
								<svg class="w-3 h-3 {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
							{/if}
						</button>
						<button class="col-span-2 flex items-center gap-1 justify-end cursor-pointer hover:text-gray-700" onclick={() => toggleSort('bakiye')}>
							Bakiye
							{#if sortBy === 'bakiye'}
								<svg class="w-3 h-3 {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
							{/if}
						</button>
					</div>

					<!-- Mobil Sıralama Bar -->
					<div class="flex lg:hidden items-center gap-2 px-4 py-2.5 bg-gray-50 border-b border-gray-200 overflow-x-auto">
						<span class="text-[10px] font-medium text-gray-500 uppercase shrink-0">Sırala:</span>
						{#each [{ key: 'hesap_adi', label: 'Ad' }, { key: 'total_borc', label: 'Borç' }, { key: 'total_alacak', label: 'Alacak' }, { key: 'bakiye', label: 'Bakiye' }] as col}
							<button
								onclick={() => toggleSort(col.key)}
								class="text-[10px] font-medium px-2 py-1 rounded-md whitespace-nowrap transition-colors
									{sortBy === col.key ? 'bg-teal-100 text-teal-700' : 'text-gray-500 hover:bg-gray-100'}"
							>
								{col.label}
								{#if sortBy === col.key}
									<svg class="w-2.5 h-2.5 inline {sortDir === 'desc' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" /></svg>
								{/if}
							</button>
						{/each}
					</div>

					<!-- Rows -->
					{#each vendors as vendor}
						<!-- Desktop Row -->
						{@const hasUnmatched = vendor.unmatched_count > 0}
						<div data-vendor-id={vendor.id} class="group/row hidden lg:grid grid-cols-12 gap-2 px-5 py-3 text-sm border-b border-gray-100 hover:bg-gray-50 transition-colors
							{expandedVendor === vendor.id ? 'bg-teal-50' : vendor.status === 'odeme_yasaklisi' ? 'bg-red-50' : hasUnmatched ? 'bg-amber-100/70' : ''}">
							<button
								onclick={() => toggleVendorDetail(vendor.id)}
								class="col-span-2 text-gray-600 font-mono text-xs text-left cursor-pointer"
							>{vendor.hesap_kodu}</button>
							<button
								onclick={() => toggleVendorDetail(vendor.id)}
								class="col-span-2 text-gray-900 font-medium truncate text-left cursor-pointer"
							>{vendor.hesap_adi}</button>
							<div class="col-span-1 flex items-center justify-center">
								{#if editingPaymentDays === vendor.id}
									<div class="flex items-center gap-1">
										<Input
											type="number"
											size="sm"
											fullWidth={false}
											bind:value={paymentDaysValue}
											min="0"
											max="365"
											onclick={(e) => e.stopPropagation()}
											onkeydown={(e) => { if (e.key === 'Enter') savePaymentDays(vendor.id); if (e.key === 'Escape') cancelEditPaymentDays(); }}
											class="w-14 text-center"
										/>
										<button
											onclick={(e) => { e.stopPropagation(); savePaymentDays(vendor.id); }}
											disabled={savingPaymentDays}
											class="p-0.5 text-teal-600 hover:text-teal-800 disabled:opacity-50"
											title="Kaydet"
										>
											<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
										</button>
										<button
											onclick={(e) => { e.stopPropagation(); cancelEditPaymentDays(); }}
											class="p-0.5 text-gray-500 hover:text-red-600"
											title="İptal"
										>
											<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
										</button>
									</div>
								{:else}
									<button
										onclick={(e) => { e.stopPropagation(); if (canUse) startEditPaymentDays(vendor); }}
										class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-lg transition-colors
											{vendor.payment_days !== 90
												? vendor.payment_days < 90
													? 'bg-blue-100 text-blue-700 font-semibold'
													: 'bg-amber-100 text-amber-700 font-semibold'
												: 'text-gray-600'}
											{canUse ? 'hover:bg-teal-50 hover:text-teal-700 cursor-pointer' : 'cursor-default'}"
										title={canUse ? 'Tıklayarak değiştir' : ''}
									>
										{vendor.payment_days}
										<span class="text-[10px] {vendor.payment_days !== 90 ? 'opacity-70' : 'text-gray-500'}">gün</span>
									</button>
								{/if}
							</div>
							<div class="col-span-1 flex items-center justify-center">
								<button
									onclick={(e) => { e.stopPropagation(); if (canUse) toggleVendorStatus(vendor); }}
									class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded-lg transition-colors
										{vendor.status === 'odeme_yasaklisi'
											? 'bg-red-100 text-red-700'
											: 'bg-green-100 text-green-700'}
										{canUse ? 'hover:opacity-80 cursor-pointer' : 'cursor-default'}"
									title={canUse ? 'Tıklayarak değiştir' : ''}
								>
									{vendor.status === 'odeme_yasaklisi' ? 'Yasaklı' : 'Normal'}
								</button>
							</div>
							<button
								onclick={() => toggleVendorDetail(vendor.id)}
								class="col-span-2 text-right text-rose-600 cursor-pointer"
							>{formatCurrency(vendor.total_borc)}</button>
							<button
								onclick={() => toggleVendorDetail(vendor.id)}
								class="col-span-2 text-right text-emerald-600 cursor-pointer"
							>{formatCurrency(vendor.total_alacak)}</button>
							<div class="col-span-2 flex items-center justify-end gap-1.5">
								<button
									onclick={() => toggleVendorDetail(vendor.id)}
									class="text-right font-medium cursor-pointer {vendor.bakiye < 0 ? 'text-rose-600' : vendor.bakiye > 0 ? 'text-emerald-600' : 'text-gray-500'}"
								>{formatCurrency(vendor.bakiye)}</button>
								{#if canUse}
									<button
										onclick={(e) => { e.stopPropagation(); openAddToList(vendor); }}
										class="shrink-0 p-1 rounded-md text-gray-500 hover:text-teal-600 hover:bg-teal-50 opacity-0 group-hover/row:opacity-100 transition-opacity"
										title="Ödeme talimatına ekle"
										aria-label="Ödeme talimatına ekle"
									>
										<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
									</button>
								{/if}
							</div>
						</div>

						<!-- Mobil Row (Kart) -->
						<div class="lg:hidden relative border-b border-gray-100
								{expandedVendor === vendor.id ? 'bg-teal-50' : vendor.status === 'odeme_yasaklisi' ? 'bg-red-50' : hasUnmatched ? 'bg-amber-100/70' : ''}">
							<button
								onclick={() => toggleVendorDetail(vendor.id)}
								class="w-full text-left px-4 py-3 active:bg-gray-50 transition-colors cursor-pointer"
							>
								<div class="flex items-start justify-between gap-2">
									<div class="min-w-0 flex-1">
										<p class="text-sm font-medium text-gray-900 truncate">{vendor.hesap_adi}</p>
										<div class="flex items-center gap-2 mt-0.5 flex-wrap">
											<span class="text-[10px] text-gray-500 font-mono">{vendor.hesap_kodu}</span>
											<span class="text-[10px] text-gray-500">·</span>
											<span class="text-[10px] px-1.5 py-0.5 rounded {vendor.payment_days !== 90
											? vendor.payment_days < 90
												? 'bg-blue-100 text-blue-700 font-semibold'
												: 'bg-amber-100 text-amber-700 font-semibold'
											: 'text-gray-500'}">{vendor.payment_days} gün vade</span>
											{#if vendor.status === 'odeme_yasaklisi'}
												<span class="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-semibold">Yasaklı</span>
											{/if}
										</div>
									</div>
									<span class="text-sm font-bold whitespace-nowrap {vendor.bakiye < 0 ? 'text-rose-600' : vendor.bakiye > 0 ? 'text-emerald-600' : 'text-gray-500'}">
										{formatCurrency(vendor.bakiye)}
									</span>
								</div>
								<div class="flex items-center gap-4 mt-1.5">
									<span class="text-[11px] text-rose-500">B: {formatCurrency(vendor.total_borc)}</span>
									<span class="text-[11px] text-emerald-500">A: {formatCurrency(vendor.total_alacak)}</span>
								</div>
							</button>
							{#if canUse}
								<button
									onclick={(e) => { e.stopPropagation(); openAddToList(vendor); }}
									class="absolute bottom-2.5 right-3 inline-flex items-center gap-1 px-2 py-1 rounded-md bg-teal-50 text-teal-700 text-[11px] font-medium active:bg-teal-100"
									aria-label="Ödeme talimatına ekle"
								>
									<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
									Talimat
								</button>
							{/if}
						</div>

						<!-- Detay -->
						{#if expandedVendor === vendor.id}
							<div class="bg-gray-50 border-b border-gray-200">
								{#if vtxLoading}
									<div class="flex items-center justify-center py-8 text-teal-700">
										<Loader2 size={20} class="animate-spin" />
									</div>
								{:else}
									<div class="px-3 sm:px-5 py-3 sm:py-4">
										<!-- Banka / IBAN yönetimi (ödeme talimatında kullanılır) -->
										{#if canUse}
											<div class="mb-4 bg-white rounded-lg border border-gray-200 p-3">
												<div class="flex items-center justify-between mb-2">
													<h4 class="text-xs font-semibold text-gray-700 inline-flex items-center gap-1.5"><Landmark size={14} class="text-teal-600" /> Banka / IBAN</h4>
													<span class="text-[11px] text-gray-400">Ödeme talimatında kullanılır</span>
												</div>
												{#if vendorIbans.length > 0}
													<div class="space-y-1.5 mb-2">
														{#each vendorIbans as ba (ba.id)}
															<div class="flex items-center gap-2 text-xs bg-gray-50 rounded px-2 py-1.5">
																<button onclick={() => setDefaultIban(vendor.id, ba.id)} title={ba.is_default ? 'Varsayılan' : 'Varsayılan yap'} class="shrink-0 cursor-pointer {ba.is_default ? 'text-amber-500' : 'text-gray-300 hover:text-amber-400'}"><Star size={14} fill={ba.is_default ? 'currentColor' : 'none'} /></button>
																<span class="min-w-0 flex-1 truncate">
																	<span class="font-medium text-gray-800">{ba.bank_name || 'Banka'}</span>
																	<span class="font-mono text-gray-500 ml-1">{fmtIbanDisplay(ba.iban)}</span>
																</span>
																<button onclick={() => deleteVendorIban(vendor.id, ba.id)} class="shrink-0 text-gray-300 hover:text-red-500 cursor-pointer" title="Sil"><Trash2 size={14} /></button>
															</div>
														{/each}
													</div>
												{:else}
													<p class="text-xs text-gray-400 mb-2">Kayıtlı IBAN yok. Ödeme talimatında banka/IBAN göstermek için ekleyin.</p>
												{/if}
												<div class="flex flex-col sm:flex-row gap-2">
													<Input size="sm" fullWidth={false} bind:value={ibanForm.bank_name} placeholder="Banka (ör. Yapı Kredi)" class="sm:w-44" />
													<Input size="sm" fullWidth={false} bind:value={ibanForm.iban} placeholder="TR.. IBAN" class="flex-1 font-mono" />
													<button onclick={() => addVendorIban(vendor.id)} disabled={ibanSaving} class="shrink-0 px-3 py-1.5 text-xs font-medium rounded bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-50 cursor-pointer inline-flex items-center justify-center gap-1"><Plus size={13} /> Ekle</button>
												</div>
											</div>
										{/if}

										<!-- Sayfalama -->
										{#if vtxPages > 1}
											<div class="flex items-center justify-end gap-2 mb-2">
												<button
													onclick={() => { vtxPage--; loadVendorDetail(vendor.id); }}
													disabled={vtxPage <= 1}
													class="px-2 py-1 text-xs rounded border border-gray-200 disabled:opacity-40"
												>&laquo;</button>
												<span class="text-xs text-gray-500">{vtxPage}/{vtxPages}</span>
												<button
													onclick={() => { vtxPage++; loadVendorDetail(vendor.id); }}
													disabled={vtxPage >= vtxPages}
													class="px-2 py-1 text-xs rounded border border-gray-200 disabled:opacity-40"
												>&raquo;</button>
											</div>
										{/if}

										<!-- İşlem Geçmişi — Masaüstü Tablo -->
											<div class="hidden sm:block bg-white rounded-xl border border-gray-200 overflow-x-auto">
												<table class="w-full text-xs">
													<thead class="bg-gray-50">
														<tr>
															<th class="px-3 py-2 text-left font-medium text-gray-500">Tarih</th>
															<th class="px-3 py-2 text-left font-medium text-gray-500">Evrak No</th>
															<th class="px-3 py-2 text-left font-medium text-gray-500">İşlem Tipi</th>
															<th class="px-3 py-2 text-left font-medium text-gray-500">Açıklama</th>
															<th class="px-3 py-2 text-right font-medium text-gray-500">Borç</th>
															<th class="px-3 py-2 text-right font-medium text-gray-500">Alacak</th>
															<th class="px-3 py-2 text-right font-medium text-gray-500">Bakiye</th>
															<th class="px-3 py-2 text-center font-medium text-gray-500">Eşleşme</th>
															<th class="px-3 py-2 text-center font-medium text-gray-500">Departman</th>
															<th class="px-3 py-2 text-right font-medium text-gray-500">Ödeme Tarihi</th>
														</tr>
													</thead>
													<tbody class="divide-y divide-gray-100">
														{#each vendorTransactions as tx}
															{@const isUnmatched = tx.borc > 0 && (tx.match_number === null || tx.match_number === 0)}
															<tr class="{isUnmatched ? 'bg-amber-100/50 hover:bg-amber-100' : 'hover:bg-gray-50'}">
																<td class="px-3 py-2 text-gray-600 whitespace-nowrap">{formatDate(tx.date)}</td>
																<td class="px-3 py-2 text-gray-600">{tx.evrak_no || '-'}</td>
																<td class="px-3 py-2 text-gray-600">{tx.transaction_type || '-'}</td>
																<td class="px-3 py-2 text-gray-600 max-w-[200px] truncate">{tx.description || '-'}</td>
																<td class="px-3 py-2 text-right {tx.borc > 0 ? 'text-rose-600' : 'text-gray-500'}">
																	{tx.borc > 0 ? formatCurrency(tx.borc) : '-'}
																</td>
																<td class="px-3 py-2 text-right {tx.alacak > 0 ? 'text-emerald-600' : 'text-gray-500'}">
																	{tx.alacak > 0 ? formatCurrency(tx.alacak) : '-'}
																</td>
																<td class="px-3 py-2 text-right font-medium {(tx.bakiye ?? 0) < 0 ? 'text-rose-600' : 'text-gray-700'}">
																	{tx.bakiye !== null ? formatCurrency(tx.bakiye) : '-'}
																</td>
																<td class="px-3 py-2 text-center">
																	{#if tx.match_number === -1}
																		<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-violet-50 text-violet-600 border border-violet-200">
																			Avans/Devir
																		</span>
																	{:else if tx.match_number === -2}
																		<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-rose-50 text-rose-600 border border-rose-200">
																			İade
																		</span>
																	{:else if tx.match_number === -3}
																		<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-50 text-blue-600 border border-blue-200">
																			Satış Faturası
																		</span>
																	{:else if tx.match_number}
																		<div class="flex items-center gap-1">
																			<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-teal-50 text-teal-700 border border-teal-200">
																				#{tx.match_number}
																				{#if tx.payment_method === 'havale_eft'}
																					<Landmark size={11} class="text-blue-500" />
																				{:else if tx.payment_method === 'kredi_karti'}
																					<CreditCard size={11} class="text-pink-500" />
																				{:else if tx.payment_method === 'nakit'}
																					<Banknote size={11} class="text-emerald-500" />
																				{:else if tx.payment_method === 'cek'}
																					<FileText size={11} class="text-orange-500" />
																				{:else if tx.payment_method === 'senet'}
																					<Scroll size={11} class="text-rose-500" />
																				{/if}
																			</span>
																			{#if canUse}
																				<button
																					onclick={(e) => { e.stopPropagation(); unmatchTransaction(tx.id, tx.payment_method || ''); }}
																					class="p-0.5 text-gray-500 hover:text-red-600 transition-colors cursor-pointer"
																					title="Eşleştirmeyi kaldır"
																				>
																					<svg class="w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
																				</button>
																			{/if}
																		</div>
																	{:else if tx.borc > 0}
																		{@const isDevirCandidate = tx.description?.toLowerCase().includes('açılış') || tx.description?.toLowerCase().includes('devir') || tx.transaction_type?.toLowerCase().includes('açılış') || tx.transaction_type?.toLowerCase().includes('devir')}
																		<div class="flex items-center gap-1 flex-wrap">
																			<a
																				href="/dashboard/finans/nakit-akim?date={tx.date}&amount={tx.borc}&vendor={encodeURIComponent(vendorDetail?.hesap_adi ?? '')}&vtx_id={tx.id}&vendor_id={tx.vendor_id}"
																				class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-600 border border-amber-200 hover:bg-amber-100 hover:border-amber-300 transition-colors"
																				title="Banka hareketi ile eşleştir"
																			>
																				<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
																				Eşleştir
																			</a>
																			<button
																				onclick={() => openCheckMatch(tx.id, tx.borc)}
																				class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-50 text-orange-600 border border-orange-200 hover:bg-orange-100 hover:border-orange-300 transition-colors cursor-pointer"
																				title="Verilen çek ile eşleştir"
																			>
																				<svg class="w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" /></svg>
																				Çek
																			</button>
																			{#if isDevirCandidate}
																			<button
																				onclick={() => markAsDevir(tx.id)}
																				class="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-violet-50 text-violet-500 border border-violet-200 hover:bg-violet-100 transition-colors cursor-pointer"
																				title="Avans/devir olarak işaretle"
																			>
																				Devir
																			</button>
																			{/if}
																		</div>
																	{:else}
																		<span class="text-gray-500">-</span>
																	{/if}
																</td>
																<td class="px-3 py-2 text-center">
																	{#if tx.dept_status === 'approved'}
																		<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-50 text-green-700 border border-green-200" title={tx.department_name || ''}>
																			<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
																			{tx.department_name}
																		</span>
																	{:else if tx.dept_status === 'pending'}
																		<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200" title="Onay bekliyor">
																			<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
																			{tx.department_name}
																		</span>
																	{:else if tx.dept_status === 'rejected'}
																		<div class="flex items-center gap-1">
																			<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-50 text-red-600 border border-red-200" title={tx.dept_rejection_note || 'Reddedildi'}>
																				✕ {tx.department_name}
																			</span>
																			{#if canUse}
																				<button onclick={() => removeDeptAssignment(tx.id)} class="p-0.5 text-gray-500 hover:text-red-600 cursor-pointer" title="Atamayı kaldır">
																					<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
																				</button>
																			{/if}
																		</div>
																	{:else if canUse && tx.alacak > 0}
																		<button
																			onclick={() => openDeptAssign(tx)}
																			class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-indigo-50 text-indigo-600 border border-indigo-200 hover:bg-indigo-100 transition-colors cursor-pointer"
																			title="Departmana ata"
																		>
																			<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
																			Ata
																		</button>
																	{:else}
																		<span class="text-gray-500">-</span>
																	{/if}
																</td>
																<td class="px-3 py-2 text-right">
																	{#if tx.payment_due_date}
																		<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
																			{formatDate(tx.payment_due_date)}
																		</span>
																	{:else}
																		<span class="text-gray-500">-</span>
																	{/if}
																</td>
															</tr>
														{/each}
													</tbody>
												</table>
											</div>

											<!-- İşlem Geçmişi — Mobil Kart Görünümü -->
											<div class="sm:hidden space-y-2">
												{#each vendorTransactions as tx}
													{@const isUnmatched = tx.borc > 0 && (tx.match_number === null || tx.match_number === 0)}
													{@const isDevirCandidate = tx.description?.toLowerCase().includes('açılış') || tx.description?.toLowerCase().includes('devir') || tx.transaction_type?.toLowerCase().includes('açılış') || tx.transaction_type?.toLowerCase().includes('devir')}
													<div class="bg-white rounded-xl border {isUnmatched ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'} p-3">
														<!-- Üst: Tarih + İşlem tipi + Bakiye -->
														<div class="flex items-center justify-between gap-2 mb-1.5">
															<div class="flex items-center gap-2 min-w-0">
																<span class="text-xs font-medium text-gray-600">{formatDate(tx.date)}</span>
																{#if tx.transaction_type}
																	<span class="text-[10px] text-gray-500 truncate">{tx.transaction_type}</span>
																{/if}
															</div>
															<span class="text-xs font-bold shrink-0 {(tx.bakiye ?? 0) < 0 ? 'text-rose-600' : 'text-gray-700'}">
																{tx.bakiye !== null ? formatCurrency(tx.bakiye) : ''}
															</span>
														</div>

														<!-- Evrak no + Açıklama -->
														<div class="mb-2">
															{#if tx.evrak_no}
																<span class="text-[10px] font-mono text-gray-500">{tx.evrak_no}</span>
															{/if}
															{#if tx.description}
																<p class="text-xs text-gray-600 leading-tight {tx.evrak_no ? 'mt-0.5' : ''}">{tx.description}</p>
															{/if}
														</div>

														<!-- Borç / Alacak -->
														<div class="flex items-center gap-3 mb-2">
															{#if tx.borc > 0}
																<span class="text-sm font-bold text-rose-600">{formatCurrency(tx.borc)}</span>
																<span class="text-[10px] text-rose-400">borç</span>
															{/if}
															{#if tx.alacak > 0}
																<span class="text-sm font-bold text-emerald-600">{formatCurrency(tx.alacak)}</span>
																<span class="text-[10px] text-emerald-400">alacak</span>
															{/if}
															{#if tx.payment_due_date}
																<span class="ml-auto inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
																	Vade: {formatDate(tx.payment_due_date)}
																</span>
															{/if}
														</div>

														<!-- Eşleşme durumu + aksiyonlar -->
														<div class="flex items-center gap-1.5 flex-wrap">
															{#if tx.match_number === -1}
																<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-violet-50 text-violet-600 border border-violet-200">
																	Avans/Devir
																</span>
															{:else if tx.match_number === -2}
																<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-rose-50 text-rose-600 border border-rose-200">
																	İade
																</span>
															{:else if tx.match_number === -3}
																<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-blue-50 text-blue-600 border border-blue-200">
																	Satış Faturası
																</span>
															{:else if tx.match_number}
																<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-teal-50 text-teal-700 border border-teal-200">
																	#{tx.match_number}
																	{#if tx.payment_method === 'havale_eft'}
																		<Landmark size={11} class="text-blue-500" />
																	{:else if tx.payment_method === 'kredi_karti'}
																		<CreditCard size={11} class="text-pink-500" />
																	{:else if tx.payment_method === 'nakit'}
																		<Banknote size={11} class="text-emerald-500" />
																	{:else if tx.payment_method === 'cek'}
																		<FileText size={11} class="text-orange-500" />
																	{:else if tx.payment_method === 'senet'}
																		<Scroll size={11} class="text-rose-500" />
																	{/if}
																</span>
																{#if canUse}
																	<button
																		onclick={(e) => { e.stopPropagation(); unmatchTransaction(tx.id, tx.payment_method || ''); }}
																		class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-red-50 text-red-600 border border-red-200 active:scale-95 cursor-pointer"
																	>
																		<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
																		Kaldır
																	</button>
																{/if}
															{:else if tx.borc > 0}
																<a
																	href="/dashboard/finans/nakit-akim?date={tx.date}&amount={tx.borc}&vendor={encodeURIComponent(vendorDetail?.hesap_adi ?? '')}&vtx_id={tx.id}&vendor_id={tx.vendor_id}"
																	class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-50 text-amber-700 border border-amber-300 active:scale-95 transition-transform"
																>
																	<span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
																	Banka Eşleştir
																</a>
																<button
																	onclick={() => openCheckMatch(tx.id, tx.borc)}
																	class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-orange-50 text-orange-700 border border-orange-300 active:scale-95 transition-transform cursor-pointer"
																>
																	<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" /></svg>
																	Çek Eşleştir
																</button>
																{#if isDevirCandidate}
																	<button
																		onclick={() => markAsDevir(tx.id)}
																		class="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-50 text-violet-600 border border-violet-200 active:scale-95 transition-transform cursor-pointer"
																	>
																		Devir
																	</button>
																{/if}
															{:else}
																<span class="text-[10px] text-gray-500">—</span>
															{/if}
														</div>

														<!-- Departman durumu (mobil) -->
														{#if tx.dept_status === 'approved'}
															<div class="mt-2 pt-2 border-t border-gray-100">
																<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-green-50 text-green-700 border border-green-200">
																	✓ {tx.department_name}
																</span>
															</div>
														{:else if tx.dept_status === 'pending'}
															<div class="mt-2 pt-2 border-t border-gray-100">
																<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
																	<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
																	{tx.department_name} — Onay bekliyor
																</span>
															</div>
														{:else if tx.dept_status === 'rejected'}
															<div class="mt-2 pt-2 border-t border-gray-100 flex items-center gap-2">
																<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-red-50 text-red-600 border border-red-200">
																	✕ {tx.department_name}
																</span>
																{#if canUse}
																	<button onclick={() => removeDeptAssignment(tx.id)} class="text-[10px] text-red-400 hover:text-red-600 cursor-pointer">Kaldır</button>
																{/if}
															</div>
														{:else if canUse && tx.alacak > 0}
															<div class="mt-2 pt-2 border-t border-gray-100">
																<button
																	onclick={() => openDeptAssign(tx)}
																	class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-50 text-indigo-600 border border-indigo-200 active:scale-95 transition-transform cursor-pointer"
																>
																	<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
																	Departmana Ata
																</button>
															</div>
														{/if}
													</div>
												{/each}
											</div>
									</div>
								{/if}
							</div>
						{/if}
					{/each}

					<!-- Pagination -->
					{#if vendorPages > 1}
						<div class="flex items-center justify-between px-5 py-3 bg-gray-50">
							<span class="text-xs text-gray-500">
								{(vendorPage - 1) * vendorPageSize + 1}-{Math.min(vendorPage * vendorPageSize, vendorTotal)} / {vendorTotal}
							</span>
							<div class="flex items-center gap-2">
								<button
									onclick={() => { vendorPage--; loadVendors(); }}
									disabled={vendorPage <= 1}
									class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 disabled:opacity-40 hover:bg-white"
								>Önceki</button>
								<span class="text-xs text-gray-500">{vendorPage} / {vendorPages}</span>
								<button
									onclick={() => { vendorPage++; loadVendors(); }}
									disabled={vendorPage >= vendorPages}
									class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 disabled:opacity-40 hover:bg-white"
								>Sonraki</button>
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}

	<!-- ═══ ÖDEME PLANI ═══ -->
	{#if activeView === 'schedule'}
		<div class="space-y-4">
			{#if scheduleLoading}
				<TableSkeleton rows={6} columns={4} />
			{:else if schedule.length === 0}
				<div class="text-center py-12 text-gray-500">
					<p class="text-sm">Henüz ödeme planı bulunmuyor</p>
					<p class="text-xs mt-1">Fatura içeren cari verileri yükleyerek ödeme planı oluşturabilirsiniz</p>
				</div>
			{:else}
				<!-- Özet Kart -->
				<div class="bg-white rounded-2xl border border-gray-200 shadow-sm p-5">
					<div class="flex items-center justify-between">
						<div>
							<p class="text-sm text-gray-500">Toplam Planlanan Ödeme</p>
							<p class="text-2xl font-bold text-gray-900 mt-1">{formatCurrency(totalScheduleAmount)}</p>
							{#if eurRate > 0}
								<p class="text-sm text-blue-600 mt-0.5">{formatEur(totalScheduleAmount)}</p>
							{/if}
						</div>
						<div class="text-right">
							<p class="text-sm text-gray-500">{monthlySchedule.length} ay · {schedule.length} hafta</p>
							<p class="text-sm text-gray-500 mt-1">{schedule.reduce((s, g) => s + g.items.length, 0)} fatura</p>
						</div>
					</div>
				</div>

				<!-- Aylık Akordion -->
				<div class="space-y-3">
					{#each monthlySchedule as month}
						<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
							<!-- Ay Başlığı -->
							<button
								onclick={() => toggleMonth(month.key)}
								class="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors cursor-pointer"
							>
								<div class="flex items-center gap-4">
									<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-orange-50 text-orange-600">
										<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
											<path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
										</svg>
									</div>
									<div class="text-left">
										<p class="text-sm font-semibold text-gray-900">{month.label}</p>
										<p class="text-xs text-gray-500 mt-0.5">{month.weeks.length} hafta · {month.item_count} fatura</p>
									</div>
								</div>
								<div class="flex items-center gap-6">
									<div class="text-right">
										<p class="text-sm font-bold text-orange-600">{formatCurrency(month.total_amount)}</p>
										{#if eurRate > 0}
											<p class="text-[10px] text-blue-500">{formatEur(month.total_amount)}</p>
										{/if}
									</div>
									<svg class="w-4 h-4 text-gray-500 transition-transform {expandedMonths[month.key] ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
										<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
									</svg>
								</div>
							</button>

							<!-- Haftalık Gruplar (ay açıldığında) -->
							{#if expandedMonths[month.key]}
								<div class="border-t border-gray-100 px-3 py-3 space-y-2 bg-gray-50/50">
									{#each month.weeks as week}
										<div class="bg-white rounded-xl border border-gray-100 overflow-hidden">
											<!-- Hafta Başlığı -->
											<button
												onclick={() => toggleWeek(week.friday_date)}
												class="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors cursor-pointer"
											>
												<div class="flex items-center gap-3">
													<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-teal-50 text-teal-600">
														<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
															<path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
														</svg>
													</div>
													<div class="text-left">
														<p class="text-xs font-semibold text-gray-900">{formatDateLong(week.friday_date)}</p>
														<p class="text-[10px] text-gray-500">{week.items.length} fatura</p>
													</div>
												</div>
												<div class="flex items-center gap-4">
													<p class="text-xs font-bold text-gray-900">{formatCurrency(week.total_amount)}</p>
													{#if eurRate > 0}
														<p class="text-[10px] text-blue-500">{formatEur(week.total_amount)}</p>
													{/if}
													<svg class="w-3.5 h-3.5 text-gray-500 transition-transform {expandedWeeks[week.friday_date] ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
														<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
													</svg>
												</div>
											</button>

											<!-- Fatura Detayları -->
											{#if expandedWeeks[week.friday_date]}
												<div class="border-t border-gray-100">
													<table class="w-full text-xs">
														<thead class="bg-gray-50">
															<tr>
																<th class="px-4 py-2 text-left font-medium text-gray-500">Cari</th>
																<th class="px-3 py-2 text-left font-medium text-gray-500">Evrak No</th>
																<th class="px-3 py-2 text-left font-medium text-gray-500">İşlem Tipi</th>
																<th class="px-3 py-2 text-left font-medium text-gray-500">Fatura Tarihi</th>
																<th class="px-3 py-2 text-right font-medium text-gray-500">Tutar</th>
															</tr>
														</thead>
														<tbody class="divide-y divide-gray-100">
															{#each week.items as item}
																<tr class="hover:bg-gray-50">
																	<td class="px-4 py-2.5">
																		<p class="font-medium text-gray-900">{item.hesap_adi}</p>
																		<p class="text-[10px] text-gray-500 font-mono">{item.hesap_kodu}</p>
																	</td>
																	<td class="px-3 py-2.5 text-gray-600">{item.evrak_no || '-'}</td>
																	<td class="px-3 py-2.5 text-gray-600">{item.transaction_type || '-'}</td>
																	<td class="px-3 py-2.5 text-gray-600">{formatDate(item.invoice_date)}</td>
																	<td class="px-3 py-2.5 text-right font-medium text-gray-900">{formatCurrency(item.amount)}</td>
																</tr>
															{/each}
														</tbody>
														<tfoot class="bg-gray-50">
															<tr>
																<td colspan="4" class="px-4 py-2.5 text-right font-semibold text-gray-700">Haftalık Toplam</td>
																<td class="px-3 py-2.5 text-right">
																	<p class="font-bold text-gray-900">{formatCurrency(week.total_amount)}</p>
																	{#if eurRate > 0}
																		<p class="text-[10px] text-blue-500">{formatEur(week.total_amount)}</p>
																	{/if}
																</td>
															</tr>
														</tfoot>
													</table>
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
	{/if}

	<!-- ═══ ÖDEME TALİMATI ═══ -->
	{#if activeView === 'instructions'}
		<PaymentInstructions canUse={canUse} />
	{/if}
</div>

<!-- Çek Eşleştirme Modal -->
<Modal bind:show={showCheckMatch} title="Çek ile Eşleştir" maxWidth="2xl">
	<div class="space-y-4 py-2">
		<!-- Üst bilgi -->
		<div class="bg-gray-50 rounded-xl p-3 text-sm">
			<span class="text-gray-500">Eşleştirilecek tutar:</span>
			<span class="font-bold text-gray-900 ml-1">{formatCurrency(checkMatchVtxAmount)}</span>
		</div>

		<!-- Arama -->
		<Input
			type="search"
			size="sm"
			icon={Search}
			clearable
			bind:value={checkSearch}
			placeholder="Çek no, firma adı veya açıklama ile ara..."
		/>

		<!-- Çek listesi -->
		{#if checksLoading}
			<div class="flex items-center justify-center py-8 text-teal-700">
				<Loader2 size={24} class="animate-spin" />
			</div>
		{:else if filteredChecks().length === 0}
			<div class="text-center py-8 text-gray-500">
				<p class="text-sm">Eşleştirilebilecek çek bulunamadı</p>
				<p class="text-xs mt-1">Tüm çekler zaten eşleştirilmiş veya ödenmiş</p>
			</div>
		{:else}
			<div class="max-h-[400px] overflow-y-auto space-y-2">
				{#each filteredChecks() as check}
					{@const amountMatch = Math.abs(check.amount_tl - checkMatchVtxAmount) < 0.01}
					<button
						onclick={() => matchWithCheck(check.id)}
						class="w-full text-left p-3 rounded-xl border transition-all cursor-pointer
							{amountMatch
								? 'border-teal-300 bg-teal-50/50 hover:bg-teal-50 hover:border-teal-400'
								: 'border-gray-200 bg-white hover:bg-gray-50 hover:border-gray-300'}"
					>
						<div class="flex items-center justify-between">
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2">
									<span class="text-xs font-mono font-bold text-gray-900">{check.check_no}</span>
									{#if amountMatch}
										<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-teal-100 text-teal-700">Tutar eşleşiyor</span>
									{/if}
									{#if check.score >= 50}
										<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700">Önerilen</span>
									{/if}
								</div>
								<p class="text-xs text-gray-600 mt-0.5 truncate">{check.vendor_name}</p>
								{#if check.description}
									<p class="text-[10px] text-gray-500 truncate">{check.description}</p>
								{/if}
							</div>
							<div class="text-right ml-3 shrink-0">
								<p class="text-sm font-bold {amountMatch ? 'text-teal-700' : 'text-gray-900'}">{formatCurrency(check.amount_tl)}</p>
								<p class="text-[10px] text-gray-500">Vade: {formatDate(check.due_date)}</p>
							</div>
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>
</Modal>

<!-- Upload Result Modal -->
<Modal bind:show={showUploadResult} title="Yükleme Sonucu" maxWidth={uploadResult && uploadResult.removal_candidates.length > 0 ? 'max-w-4xl' : 'max-w-md'}>
	{#if uploadResult}
		<div class="space-y-4 py-2">
			<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
				<div class="bg-gray-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-gray-900">{uploadResult.total_vendors}</p>
					<p class="text-xs text-gray-500 mt-1">Cari</p>
				</div>
				<div class="bg-gray-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-gray-900">{uploadResult.total_transactions}</p>
					<p class="text-xs text-gray-500 mt-1">Toplam İşlem</p>
				</div>
				<div class="bg-emerald-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-emerald-600">{uploadResult.new_transactions}</p>
					<p class="text-xs text-gray-500 mt-1">Yeni</p>
				</div>
				<div class="bg-amber-50 rounded-xl p-3 text-center">
					<p class="text-xl font-bold text-amber-600">{uploadResult.skipped_transactions}</p>
					<p class="text-xs text-gray-500 mt-1">Mükerrer</p>
				</div>
			</div>

			{#if uploadResult.removal_candidates.length > 0}
				<div class="border border-red-200 rounded-xl bg-red-50 p-4 space-y-3">
					<div class="flex items-start gap-3">
						<div class="flex-shrink-0 w-8 h-8 rounded-full bg-red-100 flex items-center justify-center text-red-600 font-bold">!</div>
						<div class="flex-1">
							<h3 class="text-sm font-semibold text-red-900">Kaynakta Bulunmayan Kayıtlar</h3>
							<p class="text-xs text-red-700 mt-1">
								Aşağıdaki <strong>{uploadResult.removal_candidates.length}</strong> kayıt yüklediğiniz Excel'in kapsamında (cari + tarih aralığı) olduğu halde dosyada bulunamadı. Kaynakta silindiyse bunları DB'den de silebilirsiniz. Banka/çek eşleşmesi olan veya departmana atanmış kayıtlar bu listeye dahil edilmedi.
							</p>
						</div>
					</div>

					<div class="bg-white rounded-lg border border-red-100 overflow-hidden">
						<div class="max-h-80 overflow-y-auto">
							<table class="w-full text-xs">
								<thead class="bg-gray-50 sticky top-0 z-10">
									<tr class="border-b border-gray-200">
										<th class="px-2 py-2 text-left w-8">
											<input
												type="checkbox"
												checked={selectedRemovalIds.size === uploadResult.removal_candidates.length && uploadResult.removal_candidates.length > 0}
												onchange={toggleAllRemovals}
												class="rounded border-gray-300 text-teal-600 focus:ring-teal-500"
											/>
										</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Cari</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Tarih</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Evrak No</th>
										<th class="px-2 py-2 text-left font-medium text-gray-600">Tip</th>
										<th class="px-2 py-2 text-right font-medium text-gray-600">Borç</th>
										<th class="px-2 py-2 text-right font-medium text-gray-600">Alacak</th>
									</tr>
								</thead>
								<tbody>
									{#each uploadResult.removal_candidates as c (c.id)}
										<tr class="border-b border-gray-100 hover:bg-gray-50 cursor-pointer" onclick={() => toggleRemovalSelection(c.id)}>
											<td class="px-2 py-2">
												<input
													type="checkbox"
													checked={selectedRemovalIds.has(c.id)}
													onclick={(e) => e.stopPropagation()}
													onchange={() => toggleRemovalSelection(c.id)}
													class="rounded border-gray-300 text-teal-600 focus:ring-teal-500"
												/>
											</td>
											<td class="px-2 py-2 text-gray-900 max-w-[180px] truncate" title={c.hesap_adi}>{c.hesap_adi}</td>
											<td class="px-2 py-2 text-gray-700 whitespace-nowrap">{formatDate(c.date)}</td>
											<td class="px-2 py-2 text-gray-700 whitespace-nowrap">{c.evrak_no || '—'}</td>
											<td class="px-2 py-2 text-gray-600 max-w-[140px] truncate" title={c.transaction_type || ''}>{c.transaction_type || '—'}</td>
											<td class="px-2 py-2 text-right whitespace-nowrap {c.borc > 0 ? 'text-emerald-700' : 'text-gray-500'}">{c.borc > 0 ? formatCurrency(c.borc) : '—'}</td>
											<td class="px-2 py-2 text-right whitespace-nowrap {c.alacak > 0 ? 'text-red-700' : 'text-gray-500'}">{c.alacak > 0 ? formatCurrency(c.alacak) : '—'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>

					<div class="flex items-center justify-between text-xs text-red-700">
						<span>{selectedRemovalIds.size} / {uploadResult.removal_candidates.length} seçili</span>
						<button
							onclick={toggleAllRemovals}
							class="font-medium hover:underline"
						>
							{selectedRemovalIds.size === uploadResult.removal_candidates.length ? 'Hiçbirini seçme' : 'Hepsini seç'}
						</button>
					</div>
				</div>

				<div class="flex items-center justify-end gap-3">
					<button
						onclick={() => { showUploadResult = false; uploadResult = null; selectedRemovalIds = new Set(); }}
						disabled={bulkDeleting}
						class="px-4 py-2.5 rounded-lg font-medium text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 transition-colors cursor-pointer"
					>
						Atla / Hiçbirini silme
					</button>
					<button
						onclick={confirmBulkDelete}
						disabled={bulkDeleting || selectedRemovalIds.size === 0 || !canUse}
						class="px-4 py-2.5 rounded-lg font-medium text-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
					>
						{#if bulkDeleting}
							<span class="inline-flex items-center gap-2">
								<span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
								Siliniyor...
							</span>
						{:else}
							Seçilenleri Sil ({selectedRemovalIds.size})
						{/if}
					</button>
				</div>
			{:else}
				<Button fullWidth onclick={() => showUploadResult = false}>Tamam</Button>
			{/if}
		</div>
	{/if}
</Modal>

<!-- Departman Atama Modalı -->
<Modal bind:show={showDeptAssignModal} title="Departmana Ata" maxWidth="max-w-md">
	<div class="space-y-4">
		<div class="bg-gray-50 rounded-lg p-3 text-sm">
			<p class="text-gray-600">{deptAssignTxDesc}</p>
			<p class="font-semibold text-teal-600 mt-1">{deptAssignTxAmount}</p>
		</div>

		<div>
			<label for="dept-select" class="block text-sm font-medium text-gray-700 mb-1">Departman</label>
			<Select id="dept-select" size="sm" bind:value={selectedDeptId}>
				<option value={null}>Seçiniz...</option>
				{#each departments.filter(d => d.manager_name) as dept}
					<option value={dept.id}>{dept.name} — {dept.manager_name}</option>
				{/each}
			</Select>
		</div>

		<div>
			<label for="cat-select" class="block text-sm font-medium text-gray-700 mb-1">Bütçe Kategorisi (opsiyonel)</label>
			<Select id="cat-select" size="sm" bind:value={selectedCatId}>
				<option value={null}>Seçiniz...</option>
				{#each budgetCategories.filter(c => c.type === 'expense') as cat}
					<option value={cat.id}>{cat.name}</option>
				{/each}
			</Select>
		</div>

		<div class="flex items-center justify-end gap-3 pt-2">
			<button
				onclick={() => { showDeptAssignModal = false; }}
				class="px-4 py-2.5 rounded-lg font-medium text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors cursor-pointer"
			>
				İptal
			</button>
			<button
				onclick={assignDepartment}
				disabled={!selectedDeptId || deptAssigning}
				class="px-4 py-2.5 rounded-lg font-medium text-sm bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
			>
				{#if deptAssigning}
					<span class="inline-flex items-center gap-2">
						<span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
						Atanıyor...
					</span>
				{:else}
					Departmana Ata
				{/if}
			</button>
		</div>
	</div>
</Modal>

<!-- Generic Onay Diyaloğu -->
<ConfirmDialog
	bind:show={confirmState.show}
	title={confirmState.title}
	message={confirmState.message}
	confirmText="Onayla"
	cancelText="Vazgeç"
	onConfirm={confirmState.onConfirm}
/>

<!-- Ödeme Talimatına Ekle Modal -->
<Modal bind:show={addToListModal.show} title="Ödeme Talimatına Ekle" maxWidth="max-w-md">
	{#if addToListModal.vendor}
		<div class="space-y-4 text-sm">
			<div class="bg-gray-50 rounded-lg p-3">
				<div class="font-medium text-gray-800">{addToListModal.vendor.hesap_adi}</div>
				<div class="text-xs text-gray-500 mt-0.5">{addToListModal.vendor.hesap_kodu}</div>
				<div class="text-xs mt-1.5">
					Ödenecek tutar:
					<span class="font-bold {addToListModal.vendor.bakiye < 0 ? 'text-rose-600' : 'text-gray-500'}">
						{formatCurrency(addToListModal.vendor.bakiye < 0 ? -addToListModal.vendor.bakiye : 0)}
					</span>
					<span class="text-gray-500">(bakiyeden — listede düzenlenebilir)</span>
				</div>
			</div>

			{#if piLists.length > 0}
				<div>
					<label for="pi-list-select" class="text-xs text-gray-500 mb-1 block">Mevcut Listeye Ekle</label>
					<Select id="pi-list-select" size="sm" bind:value={piSelectedListId}>
						{#each piLists as l (l.id)}
							<option value={l.id}>{l.name} ({l.item_count} cari)</option>
						{/each}
					</Select>
				</div>
				<div class="text-center text-xs text-gray-500">— veya —</div>
			{/if}

			<div>
				<label for="pi-new-name" class="text-xs text-gray-500 mb-1 block">Yeni Liste Oluştur</label>
				<Input id="pi-new-name" size="sm" bind:value={piNewListName} placeholder="ör: Haftalık Ödeme 26.05" />
				<p class="text-[11px] text-gray-500 mt-1">Ad girerseniz yeni liste oluşturulur, aksi halde seçili listeye eklenir.</p>
			</div>

			<div class="flex items-center justify-end gap-2 pt-1">
				<Button variant="secondary" onclick={() => (addToListModal = { show: false, vendor: null })}>Vazgeç</Button>
				<Button onclick={confirmAddToList} loading={piAdding}>Ekle</Button>
			</div>
		</div>
	{/if}
</Modal>
