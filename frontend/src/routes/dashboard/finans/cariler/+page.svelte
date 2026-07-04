<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import type {
		Vendor, VendorDetail, VendorTransaction, VendorUpload,
		VendorUploadResult, WeeklyPaymentGroup, RemovalCandidate, BulkDeleteResult, VendorNote
	} from '$lib/types/vendor';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import FileDropzone from '$lib/components/FileDropzone.svelte';
	import LoadingOverlay from '$lib/components/LoadingOverlay.svelte';
	import PaymentInstructions from '$lib/components/finance/PaymentInstructions.svelte';
	import CheckMatchModal from '$lib/components/finance/cariler/CheckMatchModal.svelte';
	import UploadResultModal from '$lib/components/finance/cariler/UploadResultModal.svelte';
	import DeptAssignModal from '$lib/components/finance/cariler/DeptAssignModal.svelte';
	import AddToListModal from '$lib/components/finance/cariler/AddToListModal.svelte';
	import { Users, Landmark, Star, Trash2, Plus, Search, Loader2, CreditCard, Banknote, FileText, Scroll, TrendingDown, TrendingUp, Scale, Wallet, ChevronDown, ChevronUp, Check, X, Calendar, Download, Pencil, Copy, User, Phone, Mail, Building2, MessageSquarePlus, StickyNote, ArrowLeft } from 'lucide-svelte';
	import Button from '$lib/components/Button.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';

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
	// Master-detail sol liste filtresi (tasarım çipleri)
	let listFilter = $state<'all' | 'overdue' | 'balance'>('all');

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

	// Vendor detail tabs (tasarım: Hesap Hareketleri / Notlar / Firma Bilgileri)
	let detailTab = $state<'transactions' | 'notes' | 'contact'>('transactions');

	// Notlar
	let vendorNotes = $state<VendorNote[]>([]);
	let notesLoading = $state(false);
	let noteDraft = $state('');
	let noteSaving = $state(false);
	let editingNoteId = $state<number | null>(null);
	let editingNoteText = $state('');

	// Firma iletişim bilgileri
	let contactForm = $state({ contact_person: '', phone: '', email: '' });
	let contactSaving = $state(false);
	let copiedIban = $state<string | null>(null);

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
			if (listFilter === 'balance') params.set('hide_zero', 'true');
			else if (listFilter === 'overdue') params.set('overdue_only', 'true');
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

	// Master-detail: sol liste filtre çipleri (Tümü / Vadesi Geçmiş / Bakiyeli)
	function setListFilter(f: 'all' | 'overdue' | 'balance') {
		listFilter = f;
		vendorPage = 1;
		loadVendors();
	}
	// Master-detail: sağ panelde gösterilecek cariyi seç (null → seçimi temizle)
	function selectVendor(id: number | null) {
		if (id === null) {
			expandedVendor = null;
			vendorDetail = null;
			vendorTransactions = [];
			vendorNotes = [];
			detailTab = 'transactions';
			return;
		}
		if (expandedVendor !== id) toggleVendorDetail(id);
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
			vendorNotes = [];
			detailTab = 'transactions';
			return;
		}
		expandedVendor = vendorId;
		vtxPage = 1;
		detailTab = 'transactions';
		vendorIbans = [];
		vendorNotes = [];
		noteDraft = '';
		editingNoteId = null;
		copiedIban = null;
		ibanForm = { bank_name: '', iban: '', account_holder: '' };
		await loadVendorDetail(vendorId);
		loadVendorIbans(vendorId);
		loadVendorNotes(vendorId);
	}

	async function loadVendorDetail(vendorId: number) {
		vtxLoading = true;
		try {
			const res = await api.get<any>(`/finance/cariler/vendors/${vendorId}?page=${vtxPage}&page_size=50`);
			vendorDetail = res.vendor;
			vendorTransactions = res.transactions.items;
			vtxTotal = res.transactions.total;
			vtxPages = res.transactions.pages;
			// İletişim formunu detaydan doldur
			contactForm = {
				contact_person: res.vendor.contact_person || '',
				phone: res.vendor.phone || '',
				email: res.vendor.email || '',
			};
		} catch (err) {
			console.error('Cari detay alınamadı:', err);
		} finally {
			vtxLoading = false;
		}
	}

	// ─── Cari Notları ──────────────────────────────────
	async function loadVendorNotes(vendorId: number) {
		notesLoading = true;
		try {
			vendorNotes = await api.get<VendorNote[]>(`/finance/cariler/vendors/${vendorId}/notes`);
		} catch (err) {
			console.error('Cari notları alınamadı:', err);
			vendorNotes = [];
		} finally {
			notesLoading = false;
		}
	}

	async function addVendorNote(vendorId: number) {
		const text = noteDraft.trim();
		if (!text) return;
		noteSaving = true;
		try {
			const note = await api.post<VendorNote>(`/finance/cariler/vendors/${vendorId}/notes`, { text });
			vendorNotes = [note, ...vendorNotes];
			noteDraft = '';
		} catch (err: any) {
			console.error('Not eklenemedi:', err);
			showToast(err?.message || 'Not eklenemedi', 'error');
		} finally {
			noteSaving = false;
		}
	}

	function startEditNote(note: VendorNote) {
		editingNoteId = note.id;
		editingNoteText = note.text;
	}
	function cancelEditNote() {
		editingNoteId = null;
		editingNoteText = '';
	}
	async function saveNoteEdit(vendorId: number, noteId: number) {
		const text = editingNoteText.trim();
		if (!text) return;
		try {
			const updated = await api.patch<VendorNote>(`/finance/cariler/vendors/${vendorId}/notes/${noteId}`, { text });
			vendorNotes = vendorNotes.map(n => n.id === noteId ? updated : n);
			editingNoteId = null;
		} catch (err) {
			console.error('Not güncellenemedi:', err);
			showToast('Not güncellenemedi', 'error');
		}
	}
	async function toggleNoteDone(vendorId: number, note: VendorNote) {
		try {
			const updated = await api.patch<VendorNote>(`/finance/cariler/vendors/${vendorId}/notes/${note.id}`, { done: !note.done });
			vendorNotes = vendorNotes.map(n => n.id === note.id ? updated : n);
		} catch (err) {
			console.error('Not güncellenemedi:', err);
			showToast('Not güncellenemedi', 'error');
		}
	}
	function confirmDeleteNote(vendorId: number, noteId: number) {
		askConfirm('Notu Sil', 'Bu not kalıcı olarak silinecek. Devam edilsin mi?', async () => {
			try {
				await api.delete(`/finance/cariler/vendors/${vendorId}/notes/${noteId}`);
				vendorNotes = vendorNotes.filter(n => n.id !== noteId);
				showToast('Not silindi', 'success');
			} catch (err) {
				console.error('Not silinemedi:', err);
				showToast('Not silinemedi', 'error');
			}
		});
	}

	// ─── Firma İletişim Bilgileri ──────────────────────
	async function saveContact(vendorId: number) {
		contactSaving = true;
		try {
			await api.patch(`/finance/cariler/vendors/${vendorId}/contact`, {
				contact_person: contactForm.contact_person.trim() || null,
				phone: contactForm.phone.trim() || null,
				email: contactForm.email.trim() || null,
			});
			if (vendorDetail && vendorDetail!.id === vendorId) {
				vendorDetail.contact_person = contactForm.contact_person.trim() || null;
				vendorDetail.phone = contactForm.phone.trim() || null;
				vendorDetail.email = contactForm.email.trim() || null;
			}
			showToast('İletişim bilgileri kaydedildi', 'success');
		} catch (err: any) {
			console.error('İletişim bilgileri kaydedilemedi:', err);
			showToast(err?.message || 'Kaydedilemedi', 'error');
		} finally {
			contactSaving = false;
		}
	}

	async function copyIban(iban: string) {
		const clean = (iban || '').replace(/\s+/g, '');
		try {
			if (navigator.clipboard) await navigator.clipboard.writeText(clean);
			copiedIban = clean;
			setTimeout(() => { if (copiedIban === clean) copiedIban = null; }, 1600);
		} catch (err) {
			console.error('IBAN kopyalanamadı:', err);
			showToast('IBAN kopyalanamadı', 'error');
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
	function ibanClean(s: string | null): string {
		return (s || '').replace(/\s+/g, '');
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
			if (vendorDetail && vendorDetail!.id === vendorId) {
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
					if (vendorDetail && vendorDetail!.id === vendor.id) {
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
		<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4">
			<StatCard label="Toplam Borç" value={formatCurrency(summary.total_borc)} accent="red" icon={TrendingDown} />
			<StatCard label="Toplam Alacak" value={formatCurrency(summary.total_alacak)} accent="emerald" icon={TrendingUp} />
			<StatCard
				label="Net Bakiye"
				value={formatCurrency(summary.bakiye)}
				accent={summary.bakiye > 0 ? 'red' : summary.bakiye < 0 ? 'emerald' : 'gray'}
				icon={Scale}
			/>
			<StatCard label="Cari Borçları" value={formatCurrency(Math.abs(summary.negative_total))} accent="amber" icon={Wallet} hint={`${summary.negative_count} cari`} />
			<StatCard label="Cari Sayısı" value={summary.vendor_count} accent="gray" icon={Users} />
		</div>
	{/if}

	<!-- Tab Bar -->
	<div class="flex items-center justify-between">
		<SegmentedControl
			options={[
				{ value: 'upload', label: 'Dosya Yükle' },
				{ value: 'vendors', label: 'Cariler' },
				{ value: 'schedule', label: 'Ödeme Planı' },
				{ value: 'instructions', label: 'Ödeme Talimatı' },
			]}
			value={activeView}
			onchange={(v) => (activeView = v as typeof activeView)}
			ariaLabel="Cari görünümü"
		/>

		<!-- Excel İndir -->
		{#if activeView === 'vendors' || activeView === 'schedule'}
			<Button variant="secondary" onclick={() => downloadExcel(activeView === 'vendors' ? 'vendors' : 'payment-schedule')}>
				<Download size={16} />
				Excel İndir
			</Button>
		{/if}
	</div>

	<!-- ═══ DOSYA YÜKLE ═══ -->
	{#if activeView === 'upload'}
		<div class="space-y-6">

			<!-- Sürükle-Bırak Alan -->
			{#if canUse}
				<div class="relative">
					<LoadingOverlay show={uploading} />
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
										<Trash2 size={16} />
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
		<div class="flex flex-col lg:flex-row gap-4 lg:items-start">

			<!-- SOL: cari listesi (master-detail) -->
			<div class="lg:w-[370px] lg:flex-none flex flex-col bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden {expandedVendor !== null ? 'hidden lg:flex' : 'flex'}">
				<div class="p-3 sm:p-4 border-b border-gray-100 space-y-3">
					<Input type="search" icon={Search} bind:value={vendorSearch} oninput={onSearchInput} placeholder="Tedarikçi ara..." />
					<div class="flex items-center gap-1.5 flex-wrap">
						{#each [{ k: 'all', label: 'Tümü' }, { k: 'overdue', label: 'Vadesi Geçmiş' }, { k: 'balance', label: 'Bakiyeli' }] as f (f.k)}
							<button onclick={() => setListFilter(f.k as any)} class="px-2.5 py-1 rounded-lg text-xs border transition-colors cursor-pointer {listFilter === f.k ? 'bg-teal-700 border-teal-700 text-white font-semibold' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}">{f.label}</button>
						{/each}
						<span class="ml-auto text-xs text-gray-500 tabular-nums">{vendorTotal} cari</span>
					</div>
				</div>
				<div class="flex-1 overflow-y-auto lg:max-h-[calc(100vh-360px)] p-2">
					{#if vendorsLoading}
						<div class="p-2"><TableSkeleton rows={8} columns={1} /></div>
					{:else if vendors.length === 0}
						<EmptyState icon={Users} title="Cari bulunamadı" description="Arama veya filtreyi değiştirin." />
					{:else}
						{#each vendors as vendor (vendor.id)}
							{@const owe = vendor.bakiye < 0}
							{@const hasUnmatched = vendor.unmatched_count > 0}
							<button data-vendor-id={vendor.id} onclick={() => selectVendor(vendor.id)} class="w-full flex gap-2.5 text-left px-2.5 py-2.5 rounded-xl mb-1 border transition-colors cursor-pointer {expandedVendor === vendor.id ? 'bg-teal-50 border-teal-200' : 'border-transparent hover:bg-gray-50'}">
								<div class="w-1 self-stretch rounded-full shrink-0 {vendor.status === 'odeme_yasaklisi' ? 'bg-red-400' : hasUnmatched ? 'bg-amber-400' : owe ? 'bg-brass' : 'bg-emerald-300'}"></div>
								<div class="flex-1 min-w-0">
									<div class="flex items-baseline justify-between gap-2">
										<span class="text-[13px] font-semibold text-gray-900 truncate">{vendor.hesap_adi}</span>
										<span class="tabular-nums text-[13px] font-semibold shrink-0 {owe ? 'text-rose-600' : 'text-emerald-600'}">{formatCurrency(vendor.bakiye)}</span>
									</div>
									<div class="flex items-center justify-between gap-2 mt-1">
										<span class="font-mono text-[10px] text-gray-500 truncate">{vendor.hesap_kodu}</span>
										<span class="text-[11px] shrink-0 {vendor.status === 'odeme_yasaklisi' ? 'text-red-600 font-medium' : hasUnmatched ? 'text-amber-600 font-medium' : 'text-gray-500'}">{vendor.status === 'odeme_yasaklisi' ? 'Ödeme yasaklı' : hasUnmatched ? vendor.unmatched_count + ' eşleşmemiş' : 'Vade ' + vendor.payment_days + ' gün'}</span>
									</div>
								</div>
							</button>
						{/each}
					{/if}
				</div>
				{#if vendorPages > 1}
					<div class="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 text-xs text-gray-500">
						<button onclick={() => { vendorPage--; loadVendors(); }} disabled={vendorPage <= 1} class="px-2 py-1 rounded border border-gray-200 disabled:opacity-40 cursor-pointer">‹ Önceki</button>
						<span class="tabular-nums">{vendorPage} / {vendorPages}</span>
						<button onclick={() => { vendorPage++; loadVendors(); }} disabled={vendorPage >= vendorPages} class="px-2 py-1 rounded border border-gray-200 disabled:opacity-40 cursor-pointer">Sonraki ›</button>
					</div>
				{/if}
			</div>

			<!-- SAĞ: seçili cari detayı -->
			<div class="flex-1 min-w-0 {expandedVendor === null ? 'hidden lg:block' : 'block'}">
				{#if vendorDetail}
					<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
					<div class="p-4 sm:p-5 border-b border-gray-100">
						<button onclick={() => selectVendor(null)} class="lg:hidden mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-teal-700 cursor-pointer"><ArrowLeft size={16} /> Cari listesine dön</button>
						<div class="flex items-start justify-between gap-3 flex-wrap">
							<div class="min-w-0">
								<h2 class="text-xl font-semibold text-gray-900 truncate">{vendorDetail.hesap_adi}</h2>
								<div class="text-xs text-gray-500 mt-1">Cari kodu <span class="font-mono text-gray-700">{vendorDetail.hesap_kodu}</span></div>
							</div>
							<div class="flex items-center gap-2 flex-wrap">
								<button onclick={() => { if (canUse) toggleVendorStatus(vendorDetail as any); }} disabled={!canUse || savingStatus} class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border {vendorDetail.status === 'odeme_yasaklisi' ? 'bg-red-50 border-red-200 text-red-700' : 'bg-emerald-50 border-emerald-200 text-emerald-700'} {canUse ? 'cursor-pointer' : 'cursor-default'}">{vendorDetail.status === 'odeme_yasaklisi' ? 'Ödeme Yasaklısı' : 'Normal'}</button>
								{#if editingPaymentDays === vendorDetail!.id}
									<div class="flex items-center gap-1">
										<Input type="number" size="sm" fullWidth={false} bind:value={paymentDaysValue} min="0" max="365" onkeydown={(e) => { if (e.key === 'Enter') savePaymentDays(vendorDetail!.id); if (e.key === 'Escape') cancelEditPaymentDays(); }} class="w-16 text-center" />
										<button onclick={() => savePaymentDays(vendorDetail!.id)} disabled={savingPaymentDays} class="touch-target p-1 text-teal-600 hover:text-teal-800 cursor-pointer" title="Kaydet"><Check size={15} /></button>
										<button onclick={cancelEditPaymentDays} class="touch-target p-1 text-gray-500 hover:text-red-600 cursor-pointer" title="İptal"><X size={15} /></button>
									</div>
								{:else}
									<button onclick={() => { if (canUse) startEditPaymentDays(vendorDetail as any); }} class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border {vendorDetail.payment_days !== 90 ? (vendorDetail.payment_days < 90 ? 'bg-blue-50 border-blue-200 text-blue-700' : 'bg-amber-50 border-amber-200 text-amber-700') : 'bg-gray-50 border-gray-200 text-gray-600'} {canUse ? 'cursor-pointer' : 'cursor-default'}"><Calendar size={13} /> Vade {vendorDetail.payment_days} gün</button>
								{/if}
							</div>
						</div>
					</div>
								{#if vtxLoading}
									<div class="flex items-center justify-center py-8 text-teal-700">
										<Loader2 size={20} class="animate-spin" />
									</div>
								{:else}
									<div class="px-3 sm:px-5 py-3 sm:py-4">
										<!-- Özet kartlar (tasarım: Güncel Bakiye / Vadesi Geçmiş / Son Ödeme) -->
										<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
											<div class="bg-teal-700 rounded-xl p-3.5 text-white">
												<div class="text-[10px] uppercase tracking-wide text-teal-100/70">Güncel Bakiye</div>
												<div class="mt-1 text-lg font-bold tabular-nums {(vendorDetail?.bakiye ?? 0) < 0 ? 'text-amber-300' : 'text-emerald-300'}">{formatCurrency(vendorDetail?.bakiye ?? 0)}</div>
												<div class="text-[11px] text-teal-100/70 mt-0.5">{(vendorDetail?.bakiye ?? 0) < 0 ? 'ödenecek tutar' : 'hesap güncel'}</div>
											</div>
											<div class="bg-white rounded-xl border border-gray-200 p-3.5">
												<div class="text-[10px] uppercase tracking-wide text-gray-500">Vadesi Geçmiş</div>
												<div class="mt-1 text-lg font-bold tabular-nums {(vendorDetail?.overdue ?? 0) > 0 ? 'text-amber-600' : 'text-emerald-600'}">{formatCurrency(vendorDetail?.overdue ?? 0)}</div>
												<div class="text-[11px] text-gray-500 mt-0.5">{(vendorDetail?.overdue ?? 0) > 0 ? `${vendorDetail?.overdue_count} fatura · acil takip` : 'gecikme yok'}</div>
											</div>
											<div class="bg-white rounded-xl border border-gray-200 p-3.5">
												<div class="text-[10px] uppercase tracking-wide text-gray-500">Son Ödeme</div>
												<div class="mt-1 text-lg font-bold tabular-nums text-emerald-600">{vendorDetail?.last_payment_amount != null ? formatCurrency(vendorDetail.last_payment_amount) : '—'}</div>
												<div class="text-[11px] text-gray-500 mt-0.5">{vendorDetail?.last_payment_date ? formatDate(vendorDetail.last_payment_date) : 'kayıt yok'}</div>
											</div>
										</div>

										<!-- Detay sekmeleri (tasarım: Hesap Hareketleri / Notlar / Firma Bilgileri) -->
										<div class="flex items-center gap-1 border-b border-gray-200 mb-4 overflow-x-auto">
											<button onclick={() => detailTab = 'transactions'} class="whitespace-nowrap inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer {detailTab === 'transactions' ? 'border-brass text-gray-900 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700'}">Hesap Hareketleri <span class="text-[11px] tabular-nums opacity-70">{vtxTotal}</span></button>
											<button onclick={() => detailTab = 'notes'} class="whitespace-nowrap inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer {detailTab === 'notes' ? 'border-brass text-gray-900 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700'}">Notlar <span class="text-[11px] tabular-nums opacity-70">{vendorNotes.length}</span></button>
											<button onclick={() => detailTab = 'contact'} class="whitespace-nowrap inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer {detailTab === 'contact' ? 'border-brass text-gray-900 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700'}">Firma Bilgileri</button>
										</div>

										{#if detailTab === 'contact'}
										<!-- İletişim Bilgileri -->
										<div class="mb-4 bg-white rounded-xl border border-gray-200 p-4">
											<h4 class="text-xs font-semibold uppercase tracking-wide text-teal-700 inline-flex items-center gap-1.5 mb-3"><User size={14} /> İletişim Bilgileri</h4>
											{#if canUse}
												<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
													<div>
														<span class="block text-[11px] text-gray-500 mb-1">Yetkili Kişi</span>
														<Input size="sm" bind:value={contactForm.contact_person} placeholder="Ad Soyad" />
													</div>
													<div>
														<span class="block text-[11px] text-gray-500 mb-1">Telefon</span>
														<Input size="sm" bind:value={contactForm.phone} placeholder="0212 000 00 00" />
													</div>
													<div>
														<span class="block text-[11px] text-gray-500 mb-1">E-posta</span>
														<Input size="sm" bind:value={contactForm.email} placeholder="ornek@firma.com" />
													</div>
												</div>
												<div class="flex justify-end mt-3">
													<Button size="sm" onclick={() => saveContact(vendorDetail!.id)} loading={contactSaving} disabled={contactSaving}><Check size={14} /> Kaydet</Button>
												</div>
											{:else}
												<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
													<div><div class="text-[11px] text-gray-500">Yetkili Kişi</div><div class="text-gray-900 mt-0.5">{vendorDetail?.contact_person || '—'}</div></div>
													<div><div class="text-[11px] text-gray-500">Telefon</div><div class="text-gray-900 mt-0.5 font-mono">{vendorDetail?.phone || '—'}</div></div>
													<div><div class="text-[11px] text-gray-500">E-posta</div><div class="text-gray-900 mt-0.5 break-all">{vendorDetail?.email || '—'}</div></div>
												</div>
											{/if}
										</div>

										<!-- Banka / IBAN yönetimi (ödeme talimatında kullanılır) -->
										{#if canUse}
											<div class="mb-4 bg-white rounded-lg border border-gray-200 p-3">
												<div class="flex items-center justify-between mb-2">
													<h4 class="text-xs font-semibold text-gray-700 inline-flex items-center gap-1.5"><Landmark size={14} class="text-teal-600" /> Banka / IBAN</h4>
													<span class="text-[11px] text-gray-500">Ödeme talimatında kullanılır</span>
												</div>
												{#if vendorIbans.length > 0}
													<div class="space-y-1.5 mb-2">
														{#each vendorIbans as ba (ba.id)}
															<div class="flex items-center gap-2 text-xs bg-gray-50 rounded px-2 py-1.5">
																<button onclick={() => setDefaultIban(vendorDetail!.id, ba.id)} title={ba.is_default ? 'Varsayılan' : 'Varsayılan yap'} class="touch-target inline-flex items-center justify-center shrink-0 cursor-pointer {ba.is_default ? 'text-amber-500' : 'text-gray-400 hover:text-amber-400'}"><Star size={14} fill={ba.is_default ? 'currentColor' : 'none'} /></button>
																<span class="min-w-0 flex-1 truncate">
																	<span class="font-medium text-gray-800">{ba.bank_name || 'Banka'}</span>
																	<span class="font-mono text-gray-500 ml-1">{fmtIbanDisplay(ba.iban)}</span>
																</span>
																<button onclick={() => copyIban(ba.iban)} class="touch-target inline-flex items-center justify-center shrink-0 {copiedIban === ibanClean(ba.iban) ? 'text-emerald-600' : 'text-gray-400 hover:text-teal-600'} cursor-pointer" title="IBAN kopyala">{#if copiedIban === ibanClean(ba.iban)}<Check size={14} />{:else}<Copy size={14} />{/if}</button>
																<button onclick={() => deleteVendorIban(vendorDetail!.id, ba.id)} class="touch-target inline-flex items-center justify-center shrink-0 text-gray-400 hover:text-red-500 cursor-pointer" title="Sil"><Trash2 size={14} /></button>
															</div>
														{/each}
													</div>
												{:else}
													<p class="text-xs text-gray-500 mb-2">Kayıtlı IBAN yok. Ödeme talimatında banka/IBAN göstermek için ekleyin.</p>
												{/if}
												<div class="flex flex-col sm:flex-row gap-2">
													<Input size="sm" fullWidth={false} bind:value={ibanForm.bank_name} placeholder="Banka (ör. Yapı Kredi)" class="sm:w-44" />
													<Input size="sm" fullWidth={false} bind:value={ibanForm.iban} placeholder="TR.. IBAN" class="flex-1 font-mono" />
													<Button size="sm" onclick={() => addVendorIban(vendorDetail!.id)} loading={ibanSaving} disabled={ibanSaving} class="shrink-0"><Plus size={13} /> Ekle</Button>
												</div>
											</div>
										{/if}
										{/if}

										{#if detailTab === 'notes'}
										<div class="bg-white rounded-xl border border-gray-200 p-4">
											{#if canUse}
												<div class="flex gap-2 items-start mb-4">
													<textarea bind:value={noteDraft} rows="2" placeholder="Bu cari hakkında görüşme notu ekle… (ödeme sözü, mutabakat, itiraz)" class="flex-1 resize-y min-h-[44px] rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-brass focus:ring-1 focus:ring-brass/40"></textarea>
													<Button size="sm" onclick={() => addVendorNote(vendorDetail!.id)} loading={noteSaving} disabled={noteSaving || !noteDraft.trim()} class="shrink-0"><Plus size={14} /> Not Ekle</Button>
												</div>
											{/if}
											{#if notesLoading}
												<div class="flex justify-center py-6 text-teal-700"><Loader2 size={18} class="animate-spin" /></div>
											{:else if vendorNotes.length === 0}
												<div class="text-center py-8 text-gray-500"><StickyNote size={28} class="mx-auto mb-2 text-gray-300" /><p class="text-sm">Henüz not yok. Görüşme sonrası buraya ekleyin.</p></div>
											{:else}
												<div class="divide-y divide-gray-100">
													{#each vendorNotes as n (n.id)}
														<div class="flex gap-3 py-3">
															<button onclick={() => toggleNoteDone(vendorDetail!.id, n)} disabled={!canUse} title="Yapıldı işaretle" class="shrink-0 mt-0.5 w-5 h-5 rounded-md border flex items-center justify-center transition-colors {n.done ? 'bg-emerald-600 border-emerald-600 text-white' : 'bg-white border-gray-300 hover:border-brass'} {canUse ? 'cursor-pointer' : 'cursor-default'}">{#if n.done}<Check size={13} />{/if}</button>
															<div class="flex-1 min-w-0">
																{#if editingNoteId === n.id}
																	<textarea bind:value={editingNoteText} rows="2" class="w-full resize-y rounded-lg border border-brass px-3 py-2 text-sm text-gray-900 outline-none"></textarea>
																	<div class="flex gap-2 mt-2">
																		<Button size="sm" onclick={() => saveNoteEdit(vendorDetail!.id, n.id)}>Kaydet</Button>
																		<Button size="sm" variant="secondary" onclick={cancelEditNote}>İptal</Button>
																	</div>
																{:else}
																	<div class="text-sm leading-relaxed whitespace-pre-wrap {n.done ? 'text-gray-400 line-through' : 'text-gray-800'}">{n.text}</div>
																	<div class="flex items-center gap-2 mt-1 text-[11px] text-gray-500 flex-wrap">
																		{#if n.author_name}<span class="font-medium text-gray-600">{n.author_name}</span><span>·</span>{/if}
																		<span class="font-mono">{formatDateTime(n.created_at)}</span>
																		{#if n.done}<span class="text-emerald-600 font-medium">· Yapıldı</span>{/if}
																	</div>
																{/if}
															</div>
															{#if canUse && editingNoteId !== n.id}
																<div class="flex gap-1 shrink-0">
																	<button onclick={() => startEditNote(n)} title="Düzenle" class="touch-target inline-flex items-center justify-center w-8 h-8 rounded-lg border border-gray-200 text-gray-500 hover:text-teal-700 hover:border-gray-300 cursor-pointer"><Pencil size={14} /></button>
																	<button onclick={() => confirmDeleteNote(vendorDetail!.id, n.id)} title="Sil" class="touch-target inline-flex items-center justify-center w-8 h-8 rounded-lg border border-gray-200 text-gray-500 hover:text-red-600 hover:border-red-200 cursor-pointer"><Trash2 size={14} /></button>
																</div>
															{/if}
														</div>
													{/each}
												</div>
											{/if}
										</div>
										{/if}

										{#if detailTab === 'transactions'}

										<!-- Sayfalama -->
										{#if vtxPages > 1}
											<div class="flex items-center justify-end gap-2 mb-2">
												<button
													onclick={() => { vtxPage--; loadVendorDetail(vendorDetail!.id); }}
													disabled={vtxPage <= 1}
													class="px-2 py-1 text-xs rounded border border-gray-200 disabled:opacity-40"
												>&laquo;</button>
												<span class="text-xs text-gray-500">{vtxPage}/{vtxPages}</span>
												<button
													onclick={() => { vtxPage++; loadVendorDetail(vendorDetail!.id); }}
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
																					<X size={12} />
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
																				<FileText size={12} />
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
																			<Check size={12} />
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
																					<X size={12} />
																				</button>
																			{/if}
																		</div>
																	{:else if canUse && tx.alacak > 0}
																		<button
																			onclick={() => openDeptAssign(tx)}
																			class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-indigo-50 text-indigo-600 border border-indigo-200 hover:bg-indigo-100 transition-colors cursor-pointer"
																			title="Departmana ata"
																		>
																			<Plus size={12} />
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
																		<X size={14} />
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
																	<FileText size={14} />
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
																	<Plus size={14} />
																	Departmana Ata
																</button>
															</div>
														{/if}
													</div>
												{/each}
											</div>
										{/if}
									</div>
								{/if}
					</div>
				{:else}
					<div class="hidden lg:flex items-center justify-center bg-white rounded-2xl border border-gray-200 shadow-sm p-12 min-h-[420px]">
						<EmptyState icon={Users} title="Bir cari seçin" description="Hesap hareketleri, notlar ve firma bilgileri için soldan bir cari seçin." />
					</div>
				{/if}
			</div>

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
										<Calendar size={20} />
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
									<ChevronDown size={16} class="text-gray-500 transition-transform {expandedMonths[month.key] ? 'rotate-180' : ''}" />
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
														<Calendar size={16} />
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
													<ChevronDown size={14} class="text-gray-500 transition-transform {expandedWeeks[week.friday_date] ? 'rotate-180' : ''}" />
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
<CheckMatchModal
	bind:show={showCheckMatch}
	vtxAmount={checkMatchVtxAmount}
	loading={checksLoading}
	checks={candidateChecks}
	bind:search={checkSearch}
	onMatch={matchWithCheck}
/>

<!-- Upload Result Modal -->
<UploadResultModal
	bind:show={showUploadResult}
	result={uploadResult}
	bind:selectedIds={selectedRemovalIds}
	{bulkDeleting}
	{canUse}
	onConfirmDelete={confirmBulkDelete}
	onSkip={() => { showUploadResult = false; uploadResult = null; selectedRemovalIds = new Set(); }}
/>

<!-- Departman Atama Modalı -->
<DeptAssignModal
	bind:show={showDeptAssignModal}
	txDesc={deptAssignTxDesc}
	txAmount={deptAssignTxAmount}
	{departments}
	{budgetCategories}
	bind:selectedDeptId
	bind:selectedCatId
	assigning={deptAssigning}
	onAssign={assignDepartment}
/>

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
<AddToListModal
	bind:show={addToListModal.show}
	vendor={addToListModal.vendor}
	lists={piLists}
	bind:selectedListId={piSelectedListId}
	bind:newName={piNewListName}
	adding={piAdding}
	onConfirm={confirmAddToList}
/>
