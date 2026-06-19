<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { WS_EVENT } from '$lib/constants/realtime';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Button from '$lib/components/Button.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import SortableHeader, { type SortOrder } from '$lib/components/SortableHeader.svelte';
	import {
		UserPlus, Pencil, Trash2, QrCode, Monitor, History, Clock, Users,
		LogIn, Printer, Copy, Fingerprint, Settings, Hourglass, Ban, Upload, RotateCcw, MoreHorizontal, Loader2,
		AlertTriangle,
	} from 'lucide-svelte';

	type Personnel = {
		id: number; full_name: string; employee_code: string;
		department: string | null; title: string | null; phone: string | null; is_active: boolean; created_at: string;
		device_bound: boolean; device_bound_at: string | null;
	};
	type InsideRow = { personnel_id: number; full_name: string; department: string | null; since: string };
	type LogRow = {
		id: number; personnel_id: number; full_name: string; department: string | null;
		type: string; punched_at: string; source: string; note: string | null;
		edited_at: string | null; deleted_at: string | null;
	};
	type SummaryRow = {
		personnel_id: number; full_name: string; department: string | null;
		total_minutes: number; total_hours: number; days_worked: number;
	};

	const canUse = hasPermission('hr.attendance', 'use');

	let tab = $state<'inside' | 'personnel' | 'logs' | 'summary'>('inside');
	let loading = $state(true);

	let inside = $state<InsideRow[]>([]);
	let personnel = $state<Personnel[]>([]);
	let logs = $state<LogRow[]>([]);
	let logsLoaded = $state(false);
	let summary = $state<SummaryRow[]>([]);
	let summaryMonth = $state(new Date().toISOString().slice(0, 7));

	// Personel modalı
	let showPersonnelModal = $state(false);
	let editing = $state<Personnel | null>(null);
	let form = $state({ full_name: '', employee_code: '', department: '', title: '', phone: '' });
	let saving = $state(false);
	let formError = $state('');

	let confirmDel = $state<{ show: boolean; target: Personnel | null }>({ show: false, target: null });

	// QR kart modalı
	let qrCard = $state<Personnel | null>(null);

	// Kiosk linki modalı
	let showKiosk = $state(false);
	let toolsMenu = $state(false);  // mobil "Araçlar" açılır menüsü
	let kioskUrl = $state('');

	// Elle giriş modalı
	let showManual = $state(false);
	let manualForm = $state({ personnel_id: 0, type: 'in', punched_at: '', note: '' });
	let manualSaving = $state(false);

	// Kayıt düzenle / sil
	let showEditLog = $state(false);
	let editForm = $state({ id: 0, type: 'in', punched_at: '', note: '' });
	let editSaving = $state(false);
	let confirmDelLog = $state<{ show: boolean; target: LogRow | null }>({ show: false, target: null });

	// Onay bekleyenler + filtre + tarihçe
	let pending = $state<any[]>([]);
	let logFilter = $state<'all' | 'pending' | 'edited' | 'deleted'>('all');
	let showHistory = $state(false);
	let historyData = $state<any>(null);
	let historyTitle = $state('');
	// entity_id (log) → bekleyen update/delete talebi
	let pendingByEntity = $derived(
		new Map(pending.filter((p) => p.entity_id && p.action_type !== 'create').map((p) => [p.entity_id, p]))
	);
	let pendingCreates = $derived(pending.filter((p) => p.action_type === 'create'));

	// Personel listesi sıralama (istemci-taraflı — liste tek seferde yüklenir)
	let psortKey = $state<string | null>(null);
	let psortOrder = $state<SortOrder>(null);
	function onPersonnelSort(key: string | null, order: SortOrder) {
		psortKey = key;
		psortOrder = order;
	}
	function _pcmp(a: Personnel, b: Personnel, key: string): number {
		if (key === 'is_active') return a.is_active === b.is_active ? 0 : a.is_active ? -1 : 1;
		const av = (a as any)[key] ?? '';
		const bv = (b as any)[key] ?? '';
		return String(av).localeCompare(String(bv), 'tr', { numeric: true, sensitivity: 'base' });
	}
	let sortedPersonnel = $derived.by(() => {
		if (!psortKey || !psortOrder) return personnel;
		const dir = psortOrder === 'asc' ? 1 : -1;
		return [...personnel].sort((a, b) => dir * _pcmp(a, b, psortKey as string));
	});
	let showCreates = $derived(logFilter === 'all' || logFilter === 'pending');
	let displayLogs = $derived(
		logFilter === 'edited'
			? logs.filter((l) => l.edited_at && !l.deleted_at)
			: logFilter === 'pending'
				? logs.filter((l) => pendingByEntity.has(l.id) && !l.deleted_at)
				: logFilter === 'deleted'
					? logs.filter((l) => l.deleted_at)
					: logs
	);

	// Ayarlar modalı (QR yenileme süresi)
	let showSettings = $state(false);
	let settingsForm = $state({ refresh_sec: 7 });
	let settingsMeta = $state({ ttl_sec: 10, min: 2, max: 120 });
	let settingsSaving = $state(false);
	let settingsError = $state('');
	// Güvenlik geçerliliği = yenileme + 3sn (grace) — canlı önizleme
	let derivedTtl = $derived((Number(settingsForm.refresh_sec) || 0) + 3);

	function fmtTime(iso: string): string {
		return new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
	}
	// Date → datetime-local input değeri ("YYYY-MM-DDTHH:MM", yerel saat)
	function toLocalInput(d: Date): string {
		const p = (n: number) => String(n).padStart(2, '0');
		return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
	}
	function fmtDateTime(iso: string): string {
		return new Date(iso).toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
	}
	function fmtMinutes(m: number): string {
		const h = Math.floor(m / 60);
		const mm = m % 60;
		if (h > 0 && mm > 0) return `${h} sa ${mm} dk`;
		if (h > 0) return `${h} sa`;
		return `${mm} dk`;
	}
	function sinceLabel(iso: string): string {
		const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
		if (diff < 60) return `${diff} dk`;
		return `${Math.floor(diff / 60)}s ${diff % 60}dk`;
	}

	async function loadStatus() {
		try {
			const r = await api.get<{ inside: InsideRow[] }>('/attendance/status');
			inside = r.inside;
		} catch (e) {
			console.error('Durum alınamadı:', e);
			showToast('İçerideki personel bilgisi yüklenemedi', 'error');
		}
	}
	async function loadPersonnel() {
		try {
			const r = await api.get<{ items: Personnel[] }>('/attendance/personnel?page_size=1000');
			personnel = r.items;
		} catch (e) {
			console.error('Personel listesi alınamadı:', e);
			showToast('Personel listesi yüklenemedi', 'error');
		}
	}
	async function loadLogs() {
		try {
			const r = await api.get<{ items: LogRow[] }>('/attendance/logs?page_size=200');
			logs = r.items;
			logsLoaded = true;
		} catch (e) {
			console.error('Loglar alınamadı:', e);
			showToast('Geçmiş kayıtları yüklenemedi', 'error');
		}
	}
	async function loadSummary() {
		try {
			const r = await api.get<{ personnel: SummaryRow[] }>(`/attendance/summary?month=${summaryMonth}`);
			summary = r.personnel;
		} catch (e) {
			console.error('Puantaj alınamadı:', e);
			showToast('Puantaj özeti yüklenemedi', 'error');
		}
	}
	async function loadPending() {
		try {
			const r = await api.get<{ items: any[] }>('/attendance/pending');
			pending = r.items;
		} catch (e) {
			console.error('Onay bekleyenler alınamadı:', e);
			showToast('Onay bekleyenler yüklenemedi', 'error');
		}
	}

	function actionLabel(a: string): string {
		return a === 'create' ? 'ekleme' : a === 'update' ? 'düzenleme' : a === 'delete' ? 'silme' : a;
	}
	async function cancelPending(requestId: number) {
		try {
			await api.post(`/attendance/pending/${requestId}/cancel`, {});
			showToast('Onay talebi iptal edildi', 'success');
			await Promise.all([loadPending(), loadLogs()]);
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'İptal edilemedi', 'error');
		}
	}
	async function openHistory(lg: LogRow) {
		historyTitle = `${lg.full_name} — ${lg.type === 'in' ? 'Giriş' : 'Çıkış'} ${fmtDateTime(lg.punched_at)}`;
		historyData = null;
		showHistory = true;
		try {
			historyData = await api.get<any>(`/attendance/logs/${lg.id}/history`);
		} catch (e) {
			console.error('Tarihçe alınamadı:', e);
			showToast('Tarihçe alınamadı', 'error');
		}
	}

	async function refreshAll() {
		loading = true;
		await Promise.all([loadStatus(), loadPersonnel(), loadSummary(), loadPending()]);
		loading = false;
	}

	function switchTab(t: typeof tab) {
		tab = t;
		if (t === 'logs' && !logsLoaded) loadLogs();
	}

	// ── Personel CRUD ──
	function openCreate() {
		editing = null;
		form = { full_name: '', employee_code: '', department: '', title: '', phone: '' };
		formError = '';
		showPersonnelModal = true;
	}
	function openEdit(p: Personnel) {
		editing = p;
		form = { full_name: p.full_name, employee_code: p.employee_code, department: p.department ?? '', title: p.title ?? '', phone: p.phone ?? '' };
		formError = '';
		showPersonnelModal = true;
	}
	async function savePersonnel() {
		formError = '';
		if (!form.full_name.trim() || !form.employee_code.trim()) {
			formError = 'Ad ve sicil no zorunlu';
			return;
		}
		saving = true;
		try {
			if (editing) {
				await api.patch(`/attendance/personnel/${editing.id}`, form);
				showToast('Personel güncellendi', 'success');
			} else {
				await api.post('/attendance/personnel', form);
				showToast('Personel eklendi', 'success');
			}
			showPersonnelModal = false;
			await loadPersonnel();
		} catch (e) {
			formError = e instanceof ApiError ? e.message : 'Kayıt başarısız';
		} finally {
			saving = false;
		}
	}
	function askDelete(p: Personnel) { confirmDel = { show: true, target: p }; }
	async function doDelete() {
		if (!confirmDel.target) return;
		try {
			await api.delete(`/attendance/personnel/${confirmDel.target.id}`);
			showToast('Personel silindi', 'success');
			await Promise.all([loadPersonnel(), loadStatus()]);
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'Silinemedi', 'error');
		}
		confirmDel = { show: false, target: null };
	}

	// ── Cihaz sıfırlama (anti-buddy-punch: bağlı cihazı çöz → yeni telefon bağlanabilsin) ──
	let confirmReset = $state<{ show: boolean; target: Personnel | null }>({ show: false, target: null });
	function askResetDevice(p: Personnel) { confirmReset = { show: true, target: p }; }
	async function doResetDevice() {
		if (!confirmReset.target) return;
		try {
			await api.post(`/attendance/personnel/${confirmReset.target.id}/reset-device`, {});
			showToast('Cihaz sıfırlandı — personel kartını tekrar okutarak yeni telefonu bağlayabilir', 'success');
			await loadPersonnel();
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'Sıfırlanamadı', 'error');
		}
		confirmReset = { show: false, target: null };
	}

	// ── Excel içe aktarma (sicil listesi) + QR kartları ──
	let showImport = $state(false);
	let importing = $state(false);
	let importFile = $state<File | null>(null);
	let replaceExisting = $state(false);
	let importResult = $state<{ created: number; updated: number; deleted: number; total: number } | null>(null);
	let importError = $state('');
	function openImport() {
		importFile = null; importResult = null; importError = ''; replaceExisting = false; showImport = true;
	}
	function onImportFile(e: Event) {
		const t = e.target as HTMLInputElement;
		importFile = t.files && t.files.length ? t.files[0] : null;
	}
	async function doImport() {
		if (!importFile) { importError = 'Lütfen bir Excel dosyası seçin'; return; }
		importing = true; importError = '';
		try {
			const fd = new FormData();
			fd.append('file', importFile);
			fd.append('replace', replaceExisting ? 'true' : 'false');
			const r = await api.upload<{ created: number; updated: number; deleted: number; total: number }>('/attendance/personnel/import', fd);
			importResult = r;
			await Promise.all([loadPersonnel(), loadStatus(), loadSummary(), loadPending()]);
			showToast(`İçe aktarıldı: ${r.created} yeni, ${r.updated} güncel`, 'success');
		} catch (e) {
			importError = e instanceof ApiError ? e.message : 'İçe aktarılamadı';
		} finally {
			importing = false;
		}
	}
	function openCards() {
		window.open('/api/attendance/personnel/cards.pdf', '_blank');
	}

	async function openKiosk() {
		try {
			const r = await api.get<{ url: string }>('/attendance/kiosk-link');
			kioskUrl = r.url;
			showKiosk = true;
		} catch (e) { showToast('Kiosk linki alınamadı', 'error'); }
	}
	function copyKiosk() {
		navigator.clipboard?.writeText(kioskUrl).then(
			() => showToast('Link kopyalandı', 'success'),
			() => showToast('Kopyalanamadı', 'error')
		);
	}

	// Seçili personelin son hareketine göre önerilen tip: içerideyse (son=giriş) → çıkış, değilse → giriş
	function defaultTypeFor(pid: number): 'in' | 'out' {
		return inside.some((i) => i.personnel_id === pid) ? 'out' : 'in';
	}
	function openManual() {
		const pid = personnel[0]?.id ?? 0;
		manualForm = { personnel_id: pid, type: defaultTypeFor(pid), punched_at: toLocalInput(new Date()), note: '' };
		showManual = true;
	}
	async function doManual() {
		if (!manualForm.personnel_id) { showToast('Personel seçin', 'warning'); return; }
		manualSaving = true;
		try {
			const res: any = await api.post('/attendance/manual', manualForm);
			showManual = false;
			if (res?.requires_approval) {
				// Onay akışına düştü — bekleyenler listesi + badge anında görünsün
				showToast('İşlem onaya gönderildi', 'info');
				loadPending();
			} else {
				showToast('Kayıt eklendi', 'success');
				await Promise.all([loadStatus(), loadLogs()]);
			}
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'Kayıt başarısız', 'error');
		} finally {
			manualSaving = false;
		}
	}

	// ── Kayıt düzenle / sil (elle düzeltme; audit + onay akışına tabi) ──
	function openEditLog(lg: LogRow) {
		editForm = { id: lg.id, type: lg.type, punched_at: toLocalInput(new Date(lg.punched_at)), note: lg.note ?? '' };
		showEditLog = true;
	}
	async function saveEditLog() {
		editSaving = true;
		try {
			const res: any = await api.patch(`/attendance/logs/${editForm.id}`, {
				type: editForm.type,
				punched_at: editForm.punched_at,
				note: editForm.note,
			});
			showEditLog = false;
			if (res?.requires_approval) {
				showToast('Düzenleme onaya gönderildi', 'info');
				loadPending();
			} else {
				showToast('Kayıt güncellendi', 'success');
				await Promise.all([loadStatus(), loadSummary(), loadLogs()]);
			}
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'Güncellenemedi', 'error');
		} finally {
			editSaving = false;
		}
	}
	function confirmDeleteLog(lg: LogRow) {
		confirmDelLog = { show: true, target: lg };
	}
	async function doDeleteLog() {
		const lg = confirmDelLog.target;
		if (!lg) return;
		try {
			const res: any = await api.delete(`/attendance/logs/${lg.id}`);
			confirmDelLog = { show: false, target: null };
			if (res?.requires_approval) {
				showToast('Silme onaya gönderildi', 'info');
				loadPending();
			} else {
				showToast('Kayıt silindi', 'success');
				await Promise.all([loadStatus(), loadSummary(), loadLogs()]);
			}
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'Silinemedi', 'error');
		}
	}

	// ── Ayarlar (QR geçerlilik süresi) ──
	type SettingsResp = { refresh_sec: number; ttl_sec: number; min: number; max: number };
	async function openSettings() {
		settingsError = '';
		try {
			const r = await api.get<SettingsResp>('/attendance/settings');
			settingsForm.refresh_sec = r.refresh_sec;
			settingsMeta = { ttl_sec: r.ttl_sec, min: r.min, max: r.max };
		} catch (e) {
			console.error('Ayarlar alınamadı:', e);
			showToast('Ayarlar alınamadı', 'error');
		}
		showSettings = true;
	}
	async function saveSettings() {
		const v = Math.round(Number(settingsForm.refresh_sec));
		if (!Number.isFinite(v) || v < settingsMeta.min || v > settingsMeta.max) {
			settingsError = `Süre ${settingsMeta.min}-${settingsMeta.max} saniye arasında olmalı`;
			return;
		}
		settingsSaving = true;
		settingsError = '';
		try {
			const r = await api.patch<SettingsResp>('/attendance/settings', { refresh_sec: v });
			settingsForm.refresh_sec = r.refresh_sec;
			settingsMeta = { ttl_sec: r.ttl_sec, min: r.min, max: r.max };
			showSettings = false;
			showToast(`QR yenileme süresi ${r.refresh_sec} sn olarak kaydedildi`, 'success');
		} catch (e) {
			settingsError = e instanceof ApiError ? e.message : 'Kaydedilemedi';
			console.error('Ayar kaydedilemedi:', e);
		} finally {
			settingsSaving = false;
		}
	}

	onMount(() => {
		refreshAll();
		// Canlı pano — başka biri (telefon/elle) basınca panel ANINDA tazelenir (polling yok).
		// Sinyal PII içermez; veriyi izin-korumalı uçtan sessizce (skeleton flash'sız) çekeriz.
		const refresh = () => {
			loadStatus();
			loadSummary();
			loadPending();
			if (logsLoaded) loadLogs();
		};
		const unsubs = [
			onWsEvent(WS_EVENT.ATTENDANCE_UPDATED, refresh),
			// Elle giriş/çıkış ONAYLANINCA: executor kaydı oluşturup commit ettikten SONRA
			// approval_status_changed yayınlanır → panel anında tazelensin (yalnızca hr.attendance).
			onWsEvent(WS_EVENT.APPROVAL_STATUS_CHANGED, (e) => {
				if (e?.module_code === 'hr.attendance') refresh();
			}),
		];
		return () => unsubs.forEach((u) => u());
	});
</script>

<div class="max-w-6xl mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-5">
	<PageHeader title="Devam Takip" description="Personel giriş/çıkış izleme ve yönetimi (karekod ile)">
		{#snippet actions()}
			{#if canUse}
				<!-- Mobil: Araçlar menüsü + Yeni -->
				<div class="flex items-center gap-2 sm:hidden">
					<div class="relative">
						<Button variant="secondary" onclick={() => (toolsMenu = !toolsMenu)}><MoreHorizontal size={16} /> Araçlar</Button>
						{#if toolsMenu}
							<button class="fixed inset-0 z-10 cursor-default" aria-label="Menüyü kapat" onclick={() => (toolsMenu = false)}></button>
							<div class="absolute right-0 mt-1 w-52 bg-white border border-gray-200 rounded-xl shadow-lg z-20 py-1.5">
								<button onclick={() => { toolsMenu = false; openManual(); }} class="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer"><LogIn size={16} class="text-gray-400" /> Elle Giriş</button>
								<button onclick={() => { toolsMenu = false; openKiosk(); }} class="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer"><Monitor size={16} class="text-gray-400" /> Kiosk Linki</button>
								<button onclick={() => { toolsMenu = false; openCards(); }} class="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer"><QrCode size={16} class="text-gray-400" /> QR Kartları</button>
								<button onclick={() => { toolsMenu = false; openImport(); }} class="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer"><Upload size={16} class="text-gray-400" /> Excel İçe Aktar</button>
								<button onclick={() => { toolsMenu = false; openSettings(); }} class="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer"><Settings size={16} class="text-gray-400" /> Ayarlar</button>
							</div>
						{/if}
					</div>
					<Button onclick={openCreate}><UserPlus size={16} /> Yeni</Button>
				</div>
				<!-- Masaüstü: tüm butonlar -->
				<div class="hidden sm:flex items-center gap-2 flex-wrap justify-end">
					<Button variant="secondary" onclick={openManual}><LogIn size={16} /> Elle Giriş</Button>
					<Button variant="secondary" onclick={openKiosk}><Monitor size={16} /> Kiosk Linki</Button>
					<Button variant="secondary" onclick={openCards}><QrCode size={16} /> QR Kartları</Button>
					<Button variant="secondary" onclick={openImport}><Upload size={16} /> Excel İçe Aktar</Button>
					<Button variant="secondary" onclick={openSettings}><Settings size={16} /> Ayarlar</Button>
					<Button onclick={openCreate}><UserPlus size={16} /> Yeni Personel</Button>
				</div>
			{/if}
		{/snippet}
	</PageHeader>

	<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
		<StatCard label="Şu An İçeride" value={`${inside.length} kişi`} icon={Clock} accent="emerald" hint="Aktif personel" />
		<StatCard label="Toplam Personel" value={`${personnel.length}`} icon={Users} accent="teal" hint="Kayıtlı çalışan" />
		<StatCard label="Bu Ay Çalışan" value={`${summary.length}`} icon={History} accent="blue" hint={summaryMonth} />
		<StatCard label="Onay Bekleyen" value={`${pending.length}`} icon={Hourglass} accent="amber" hint="Elle işlem talebi" />
	</div>

	<!-- Sekmeler -->
	<div class="flex gap-1 border-b border-gray-200 overflow-x-auto">
		{#each [['inside', 'İçeride'], ['personnel', 'Personel'], ['logs', 'Geçmiş'], ['summary', 'Puantaj']] as [key, label]}
			<button
				onclick={() => switchTab(key as typeof tab)}
				class="px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer whitespace-nowrap {tab === key ? 'border-teal-700 text-teal-700' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>{label}</button>
		{/each}
	</div>

	{#if loading}
		<TableSkeleton rows={6} columns={4} />
	{:else}
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			<!-- ŞU AN İÇERİDE -->
			{#if tab === 'inside'}
				{#if inside.length === 0}
					<EmptyState icon={Clock} title="Şu an içeride personel yok" />
				{:else}
					<div class="divide-y divide-gray-100">
						{#each inside as r (r.personnel_id)}
							<div class="flex items-center justify-between px-4 py-3">
								<div>
									<div class="font-medium text-gray-900">{r.full_name}</div>
									<div class="text-xs text-gray-500">{r.department ?? '—'}</div>
								</div>
								<div class="text-right">
									<StatusBadge type="success">İçeride</StatusBadge>
									<div class="text-[11px] text-gray-500 mt-0.5">{fmtTime(r.since)}'den beri ({sinceLabel(r.since)})</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}

			<!-- PERSONEL -->
			{:else if tab === 'personnel'}
				{#if personnel.length === 0}
					<EmptyState icon={Users} title="Henüz personel yok" description="Yeni Personel ile başlayın" ctaText={canUse ? 'Yeni Personel' : ''} onCta={canUse ? openCreate : null} />
				{:else}
					<div class="hidden md:block overflow-x-auto">
						<table class="w-full text-sm">
							<thead class="bg-gray-50 border-b border-gray-200">
								<tr>
									<th class="px-4 py-3 text-left"><SortableHeader column="full_name" sortKey={psortKey} sortOrder={psortOrder} onSort={onPersonnelSort}>Ad Soyad</SortableHeader></th>
									<th class="px-4 py-3 text-left"><SortableHeader column="employee_code" sortKey={psortKey} sortOrder={psortOrder} onSort={onPersonnelSort}>Sicil</SortableHeader></th>
									<th class="px-4 py-3 text-left hidden sm:table-cell"><SortableHeader column="department" sortKey={psortKey} sortOrder={psortOrder} onSort={onPersonnelSort}>Departman</SortableHeader></th>
									<th class="px-4 py-3 text-left hidden md:table-cell"><SortableHeader column="title" sortKey={psortKey} sortOrder={psortOrder} onSort={onPersonnelSort}>Görev</SortableHeader></th>
									<th class="px-4 py-3"><SortableHeader column="is_active" align="center" sortKey={psortKey} sortOrder={psortOrder} onSort={onPersonnelSort}>Durum</SortableHeader></th>
									<th class="px-4 py-3 text-center font-medium text-gray-500 text-xs hidden lg:table-cell">Cihaz</th>
									<th class="px-4 py-3 text-right font-medium text-gray-500 text-xs">İşlem</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-gray-100">
								{#each sortedPersonnel as p (p.id)}
									<tr class="hover:bg-gray-50">
										<td class="px-4 py-3 text-gray-900">{p.full_name}</td>
										<td class="px-4 py-3 font-mono text-xs text-gray-600">{p.employee_code}</td>
										<td class="px-4 py-3 text-gray-600 hidden sm:table-cell">{p.department ?? '—'}</td>
										<td class="px-4 py-3 text-gray-600 text-xs hidden md:table-cell">{p.title ?? '—'}</td>
										<td class="px-4 py-3 text-center">
											{#if p.is_active}<StatusBadge type="success">Aktif</StatusBadge>{:else}<StatusBadge type="neutral">Pasif</StatusBadge>{/if}
										</td>
										<td class="px-4 py-3 text-center hidden lg:table-cell">
											{#if p.device_bound}
												<span class="inline-flex items-center gap-1" title={p.device_bound_at ? `Bağlandı: ${new Date(p.device_bound_at).toLocaleString('tr-TR')}` : ''}>
													<StatusBadge type="info">Bağlı</StatusBadge>
												</span>
											{:else}
												<StatusBadge type="neutral">Yok</StatusBadge>
											{/if}
										</td>
										<td class="px-4 py-3">
											<div class="flex items-center justify-end gap-1">
												<button onclick={() => qrCard = p} class="p-1.5 text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded cursor-pointer" title="QR Kart">
													<QrCode size={16} />
												</button>
												{#if canUse}
													{#if p.device_bound}
														<button onclick={() => askResetDevice(p)} class="p-1.5 text-gray-500 hover:text-amber-600 hover:bg-amber-50 rounded cursor-pointer" title="Cihaz Sıfırla (yeni telefon bağlamak için)">
															<RotateCcw size={16} />
														</button>
													{/if}
													<button onclick={() => openEdit(p)} class="p-1.5 text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded cursor-pointer" title="Düzenle">
														<Pencil size={16} />
													</button>
													<button onclick={() => askDelete(p)} class="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded cursor-pointer" title="Sil">
														<Trash2 size={16} />
													</button>
												{/if}
											</div>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					<!-- Mobil: kart listesi (md+ tablo kalır) -->
					<div class="md:hidden divide-y divide-gray-100">
						{#each sortedPersonnel as p (p.id)}
							<div class="px-4 py-3 flex items-start justify-between gap-3">
								<div class="min-w-0">
									<div class="font-medium text-gray-900 truncate">{p.full_name}</div>
									<div class="text-xs text-gray-500 truncate mt-0.5">
										<span class="font-mono">{p.employee_code}</span>{p.department ? ` · ${p.department}` : ''}{p.title ? ` · ${p.title}` : ''}
									</div>
									<div class="flex flex-wrap items-center gap-1.5 mt-1.5">
										{#if p.is_active}<StatusBadge type="success">Aktif</StatusBadge>{:else}<StatusBadge type="neutral">Pasif</StatusBadge>{/if}
										{#if p.device_bound}<StatusBadge type="info">Cihaz bağlı</StatusBadge>{/if}
									</div>
								</div>
								<div class="flex items-center gap-1 shrink-0">
									<button onclick={() => qrCard = p} class="p-1.5 text-gray-500 hover:text-teal-700 hover:bg-teal-50 rounded cursor-pointer" title="QR Kart" aria-label="QR Kart">
										<QrCode size={16} />
									</button>
									{#if canUse}
										{#if p.device_bound}
											<button onclick={() => askResetDevice(p)} class="p-1.5 text-gray-500 hover:text-amber-600 hover:bg-amber-50 rounded cursor-pointer" title="Cihaz Sıfırla (yeni telefon bağlamak için)" aria-label="Cihaz Sıfırla">
												<RotateCcw size={16} />
											</button>
										{/if}
										<button onclick={() => openEdit(p)} class="p-1.5 text-gray-500 hover:text-teal-700 hover:bg-teal-50 rounded cursor-pointer" title="Düzenle" aria-label="Düzenle">
											<Pencil size={16} />
										</button>
										<button onclick={() => askDelete(p)} class="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded cursor-pointer" title="Sil" aria-label="Sil">
											<Trash2 size={16} />
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				{/if}

			<!-- GEÇMİŞ -->
			{:else if tab === 'logs'}
				<!-- Filtre: Tümü / Onay bekleyen / Düzenlenmiş -->
				<div class="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
					{#each [['all', 'Tümü'], ['pending', 'Onay bekleyen'], ['edited', 'Düzenlenmiş'], ['deleted', 'Silinmiş']] as opt (opt[0])}
						<button onclick={() => (logFilter = opt[0] as 'all' | 'pending' | 'edited' | 'deleted')}
							class="px-3 py-1.5 rounded-full text-xs font-medium cursor-pointer transition-colors {logFilter === opt[0] ? 'bg-teal-700 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}">
							{opt[1]}{opt[0] === 'pending' && pending.length ? ` (${pending.length})` : ''}
						</button>
					{/each}
				</div>

				{#if displayLogs.length === 0 && !(showCreates && pendingCreates.length)}
					<EmptyState icon={History} title={logFilter === 'pending' ? 'Onay bekleyen kayıt yok' : logFilter === 'edited' ? 'Düzenlenmiş kayıt yok' : logFilter === 'deleted' ? 'Silinmiş kayıt yok' : 'Kayıt yok'} />
				{:else}
					<div class="hidden md:block overflow-x-auto">
						<table class="w-full text-sm">
							<thead class="bg-gray-50 border-b border-gray-200">
								<tr>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Personel</th>
									<th class="px-4 py-3 text-center font-medium text-gray-500 text-xs">Hareket</th>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Zaman</th>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs hidden sm:table-cell">Kaynak / Durum</th>
									{#if canUse}<th class="px-4 py-3 text-right font-medium text-gray-500 text-xs">İşlem</th>{/if}
								</tr>
							</thead>
							<tbody class="divide-y divide-gray-100">
								<!-- Onaya gönderilmiş EKLEME talepleri (henüz kayıt yok → sanal satır) -->
								{#if showCreates}
									{#each pendingCreates as pc (pc.request_id)}
										<tr class="bg-amber-50">
											<td class="px-4 py-3 text-gray-900">{pc.personnel_name ?? '—'}</td>
											<td class="px-4 py-3 text-center">
												{#if pc.type === 'in'}<StatusBadge type="success">Giriş</StatusBadge>{:else}<StatusBadge type="warning">Çıkış</StatusBadge>{/if}
											</td>
											<td class="px-4 py-3 text-gray-600 text-xs whitespace-nowrap">{pc.punched_at ? fmtDateTime(pc.punched_at) : '—'}</td>
											<td class="px-4 py-3 hidden sm:table-cell"><StatusBadge type="warning">Onay bekliyor · ekleme</StatusBadge></td>
											{#if canUse}
												<td class="px-4 py-3">
													<div class="flex items-center justify-end gap-1">
														{#if pc.can_cancel}
															<button onclick={() => cancelPending(pc.request_id)} class="p-1.5 text-amber-600 hover:text-amber-700 hover:bg-amber-100 rounded cursor-pointer" title="Onay talebini iptal et"><Ban size={16} /></button>
														{/if}
													</div>
												</td>
											{/if}
										</tr>
									{/each}
								{/if}
								<!-- Gerçek kayıtlar -->
								{#each displayLogs as lg (lg.id)}
									{@const pend = pendingByEntity.get(lg.id)}
									<tr class={lg.deleted_at ? 'opacity-60 bg-gray-50' : pend ? 'bg-amber-50' : lg.edited_at ? 'bg-blue-50' : 'hover:bg-gray-50'}>
										<td class="px-4 py-3 text-gray-900 {lg.deleted_at ? 'line-through' : ''}">{lg.full_name}</td>
										<td class="px-4 py-3 text-center">
											{#if lg.type === 'in'}<StatusBadge type="success">Giriş</StatusBadge>{:else}<StatusBadge type="warning">Çıkış</StatusBadge>{/if}
										</td>
										<td class="px-4 py-3 text-gray-600 text-xs whitespace-nowrap {lg.deleted_at ? 'line-through' : ''}">{fmtDateTime(lg.punched_at)}</td>
										<td class="px-4 py-3 hidden sm:table-cell">
											<div class="flex flex-col gap-1 items-start">
												<span class="text-gray-500 text-xs">{lg.source === 'manual' ? 'Elle' : 'Karekod'}{lg.note ? ` · ${lg.note}` : ''}</span>
												{#if lg.deleted_at}<StatusBadge type="error">Silindi</StatusBadge>
												{:else if pend}<StatusBadge type="warning">Onay bekliyor · {actionLabel(pend.action_type)}</StatusBadge>
												{:else if lg.edited_at}<StatusBadge type="info">düzenlendi</StatusBadge>{/if}
											</div>
										</td>
										{#if canUse}
											<td class="px-4 py-3">
												<div class="flex items-center justify-end gap-1">
													<button onclick={() => openHistory(lg)} class="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded cursor-pointer" title="Tarihçe"><History size={16} /></button>
													{#if !lg.deleted_at}
														{#if pend}
															{#if pend.can_cancel}
																<button onclick={() => cancelPending(pend.request_id)} class="p-1.5 text-amber-600 hover:text-amber-700 hover:bg-amber-100 rounded cursor-pointer" title="Onay talebini iptal et"><Ban size={16} /></button>
															{/if}
														{:else}
															<button onclick={() => openEditLog(lg)} class="p-1.5 text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded cursor-pointer" title="Düzenle"><Pencil size={16} /></button>
															<button onclick={() => confirmDeleteLog(lg)} class="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded cursor-pointer" title="Sil"><Trash2 size={16} /></button>
														{/if}
													{/if}
												</div>
											</td>
										{/if}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					<!-- Mobil: kart listesi (md+ tablo kalır) -->
					<div class="md:hidden divide-y divide-gray-100">
						{#if showCreates}
							{#each pendingCreates as pc (pc.request_id)}
								<div class="px-4 py-3 bg-amber-50 flex items-start justify-between gap-3">
									<div class="min-w-0">
										<div class="font-medium text-gray-900 truncate">{pc.personnel_name ?? '—'}</div>
										<div class="text-xs text-gray-600 mt-0.5 tabular-nums">{pc.punched_at ? fmtDateTime(pc.punched_at) : '—'}</div>
										<div class="flex flex-wrap items-center gap-1.5 mt-1.5">
											{#if pc.type === 'in'}<StatusBadge type="success">Giriş</StatusBadge>{:else}<StatusBadge type="warning">Çıkış</StatusBadge>{/if}
											<StatusBadge type="warning">Onay bekliyor · ekleme</StatusBadge>
										</div>
									</div>
									{#if canUse && pc.can_cancel}
										<button onclick={() => cancelPending(pc.request_id)} class="p-1.5 text-amber-600 hover:text-amber-700 hover:bg-amber-100 rounded cursor-pointer shrink-0" title="Onay talebini iptal et" aria-label="Onay talebini iptal et"><Ban size={16} /></button>
									{/if}
								</div>
							{/each}
						{/if}
						{#each displayLogs as lg (lg.id)}
							{@const pend = pendingByEntity.get(lg.id)}
							<div class="px-4 py-3 flex items-start justify-between gap-3 {lg.deleted_at ? 'opacity-60 bg-gray-50' : pend ? 'bg-amber-50' : lg.edited_at ? 'bg-blue-50' : ''}">
								<div class="min-w-0">
									<div class="font-medium text-gray-900 truncate {lg.deleted_at ? 'line-through' : ''}">{lg.full_name}</div>
									<div class="text-xs text-gray-600 mt-0.5 tabular-nums {lg.deleted_at ? 'line-through' : ''}">
										{fmtDateTime(lg.punched_at)} · {lg.source === 'manual' ? 'Elle' : 'Karekod'}{lg.note ? ` · ${lg.note}` : ''}
									</div>
									<div class="flex flex-wrap items-center gap-1.5 mt-1.5">
										{#if lg.type === 'in'}<StatusBadge type="success">Giriş</StatusBadge>{:else}<StatusBadge type="warning">Çıkış</StatusBadge>{/if}
										{#if lg.deleted_at}<StatusBadge type="error">Silindi</StatusBadge>
										{:else if pend}<StatusBadge type="warning">Onay bekliyor · {actionLabel(pend.action_type)}</StatusBadge>
										{:else if lg.edited_at}<StatusBadge type="info">düzenlendi</StatusBadge>{/if}
									</div>
								</div>
								{#if canUse}
									<div class="flex items-center gap-1 shrink-0">
										<button onclick={() => openHistory(lg)} class="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded cursor-pointer" title="Tarihçe" aria-label="Tarihçe"><History size={16} /></button>
										{#if !lg.deleted_at}
											{#if pend}
												{#if pend.can_cancel}
													<button onclick={() => cancelPending(pend.request_id)} class="p-1.5 text-amber-600 hover:text-amber-700 hover:bg-amber-100 rounded cursor-pointer" title="Onay talebini iptal et" aria-label="Onay talebini iptal et"><Ban size={16} /></button>
												{/if}
											{:else}
												<button onclick={() => openEditLog(lg)} class="p-1.5 text-gray-500 hover:text-teal-700 hover:bg-teal-50 rounded cursor-pointer" title="Düzenle" aria-label="Düzenle"><Pencil size={16} /></button>
												<button onclick={() => confirmDeleteLog(lg)} class="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded cursor-pointer" title="Sil" aria-label="Sil"><Trash2 size={16} /></button>
											{/if}
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}

			<!-- PUANTAJ -->
			{:else if tab === 'summary'}
				<div class="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
					<label for="ay" class="text-xs text-gray-500">Ay:</label>
					<Input id="ay" type="month" size="sm" fullWidth={false} bind:value={summaryMonth} onchange={loadSummary} />
				</div>
				{#if summary.length === 0}
					<EmptyState icon={History} title="Bu ay kayıt yok" />
				{:else}
					<div class="overflow-x-auto">
						<table class="w-full text-sm">
							<thead class="bg-gray-50 border-b border-gray-200">
								<tr>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Personel</th>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs hidden sm:table-cell">Departman</th>
									<th class="px-4 py-3 text-right font-medium text-gray-500 text-xs">Gün</th>
									<th class="px-4 py-3 text-right font-medium text-gray-500 text-xs">Toplam Süre</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-gray-100">
								{#each summary as s (s.personnel_id)}
									<tr class="hover:bg-gray-50">
										<td class="px-4 py-3 text-gray-900">{s.full_name}</td>
										<td class="px-4 py-3 text-gray-600 hidden sm:table-cell">{s.department ?? '—'}</td>
										<td class="px-4 py-3 text-right tabular-nums">{s.days_worked}</td>
										<td class="px-4 py-3 text-right tabular-nums font-medium text-teal-700">{fmtMinutes(s.total_minutes)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<!-- Personel ekle/düzenle -->
<Modal bind:show={showPersonnelModal} title={editing ? 'Personeli Düzenle' : 'Yeni Personel'} maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); savePersonnel(); }} class="space-y-4">
		<div>
			<label for="pf-name" class="block text-sm font-medium text-gray-700 mb-1">Ad Soyad <span class="text-red-600">*</span></label>
			<Input id="pf-name" size="sm" bind:value={form.full_name} />
		</div>
		<div class="grid grid-cols-2 gap-3">
			<div>
				<label for="pf-code" class="block text-sm font-medium text-gray-700 mb-1">Sicil No <span class="text-red-600">*</span></label>
				<Input id="pf-code" size="sm" bind:value={form.employee_code} class="font-mono" />
			</div>
			<div>
				<label for="pf-dept" class="block text-sm font-medium text-gray-700 mb-1">Departman</label>
				<Input id="pf-dept" size="sm" bind:value={form.department} placeholder="Mutfak, Kat, Resepsiyon…" />
			</div>
		</div>
		<div>
			<label for="pf-title" class="block text-sm font-medium text-gray-700 mb-1">Görev</label>
			<Input id="pf-title" size="sm" bind:value={form.title} placeholder="Elektrikçi, Teknik Müdür…" />
		</div>
		<div>
			<label for="pf-phone" class="block text-sm font-medium text-gray-700 mb-1">Telefon</label>
			<Input id="pf-phone" size="sm" bind:value={form.phone} />
		</div>
		{#if formError}<div class="px-3 py-2 bg-red-50 text-red-700 text-sm rounded-lg border border-red-200">{formError}</div>{/if}
		<div class="flex justify-end gap-2 pt-2">
			<Button type="button" variant="secondary" onclick={() => (showPersonnelModal = false)}>İptal</Button>
			<Button type="submit" loading={saving}>{editing ? 'Güncelle' : 'Kaydet'}</Button>
		</div>
	</form>
</Modal>

<!-- QR Kart -->
<Modal show={qrCard !== null} title="Personel QR Kartı" maxWidth="max-w-sm" onclose={() => qrCard = null}>
	{#if qrCard}
		<div class="text-center space-y-3">
			<div class="font-semibold text-gray-900">{qrCard.full_name}</div>
			<div class="text-xs font-mono text-gray-500">{qrCard.employee_code}{qrCard.department ? ` · ${qrCard.department}` : ''}{qrCard.title ? ` · ${qrCard.title}` : ''}</div>
			<div class="flex justify-center">
				<img src={`/api/attendance/personnel/${qrCard.id}/qr`} alt="Kurulum QR" class="w-56 h-56 border border-gray-200 rounded-lg" />
			</div>
			<p class="text-xs text-gray-500 leading-snug">
				Personel bu kartı telefonuyla okutsun → açılan sayfayı <strong>"Ana Ekrana Ekle"</strong> ile kaydetsin.
				Her gün o sayfayı açıp <strong>"Tara"</strong> ile girişteki ekrandaki karekodu okutarak giriş/çıkış yapar.
			</p>
			<Button fullWidth variant="secondary" onclick={() => window.print()}><Printer size={16} /> Yazdır</Button>
		</div>
	{/if}
</Modal>

<!-- Kiosk Linki -->
<Modal bind:show={showKiosk} title="Giriş Ekranı (Kiosk) Linki" maxWidth="max-w-md">
	<div class="space-y-3 text-sm">
		<p class="text-gray-600 leading-snug">
			Bu linki girişteki bir <strong>tablet / TV / ekran</strong> tarayıcısında açın. Ekran sürekli dönen
			bir karekod gösterir; personel kendi telefonuyla bunu okutarak giriş/çıkış yapar.
		</p>
		<div class="bg-amber-50 border border-amber-200 rounded-lg p-2.5 text-xs text-amber-900 leading-snug">
			<AlertTriangle size={14} class="inline align-text-bottom" /> Bu link gizli bir anahtar içerir — yalnızca giriş cihazında açın, paylaşmayın.
		</div>
		<div class="flex items-center gap-2">
			<Input readonly value={kioskUrl} fullWidth={false} class="flex-1 text-xs font-mono truncate" />
			<Button variant="secondary" onclick={copyKiosk}><Copy size={14} /> Kopyala</Button>
		</div>
	</div>
</Modal>

<!-- Excel'den personel içe aktar (sicil listesi) -->
<Modal bind:show={showImport} title="Excel'den Personel İçe Aktar" maxWidth="max-w-md">
	<div class="space-y-4 text-sm">
		<p class="text-gray-600 leading-snug">
			Sicil listesi Excel'ini (<strong>.xls</strong> / <strong>.xlsx</strong>) yükleyin. Beklenen başlıklar:
			<strong>Sicil No</strong>, <strong>Ad Soyad</strong>, <strong>Departman</strong>, <strong>Görev</strong>
			(sıra önemsiz). Var olan sicil güncellenir, yeni sicil eklenir.
		</p>
		<input
			type="file"
			accept=".xls,.xlsx"
			onchange={onImportFile}
			class="block w-full text-sm text-gray-600 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-teal-50 file:text-teal-700 file:font-medium hover:file:bg-teal-100 cursor-pointer"
		/>
		<label class="flex items-start gap-2 cursor-pointer">
			<input type="checkbox" bind:checked={replaceExisting} class="mt-0.5 rounded border-gray-300 text-teal-700 focus:ring-teal-500" />
			<span class="text-xs text-gray-700 leading-snug">
				İçe aktarmadan önce <strong>mevcut tüm personeli sil</strong>
				<span class="block text-red-600 mt-0.5"><AlertTriangle size={13} class="inline align-text-bottom" /> Tüm personel + giriş/çıkış geçmişi silinir (geri alınamaz). Temiz sicil listesi için işaretle.</span>
			</span>
		</label>
		{#if importError}
			<div class="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">{importError}</div>
		{/if}
		{#if importResult}
			<div class="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-xs text-emerald-800 leading-snug">
				✅ <strong>{importResult.created}</strong> yeni · <strong>{importResult.updated}</strong> güncel{importResult.deleted > 0 ? ` · ${importResult.deleted} silindi` : ''} · toplam {importResult.total} satır.
			</div>
		{/if}
		<div class="flex justify-end gap-2 pt-1">
			<Button type="button" variant="secondary" onclick={() => (showImport = false)}>Kapat</Button>
			<Button onclick={doImport} loading={importing}>İçe Aktar</Button>
		</div>
	</div>
</Modal>

<!-- Ayarlar: QR yenileme süresi -->
<Modal bind:show={showSettings} title="Karekod Ayarları" maxWidth="max-w-md">
	<div class="space-y-4 text-sm">
		<p class="text-gray-600 leading-snug">
			Girişteki ekrandaki karekodun <strong>ne sıklıkta değişeceği</strong>. Kısaldıkça ekran
			görüntüsü/paylaşımla sahte basış zorlaşır (daha güvenli); uzadıkça ekran daha sakin durur.
		</p>
		<div>
			<label for="set-refresh" class="block text-sm font-medium text-gray-700 mb-1">
				QR yenileme süresi (saniye) <span class="text-red-500">*</span>
			</label>
			<Input
				id="set-refresh"
				type="number"
				size="sm"
				min={settingsMeta.min}
				max={settingsMeta.max}
				step="1"
				bind:value={settingsForm.refresh_sec}
				class="tabular-nums"
			/>
			<p class="text-xs text-gray-500 mt-1">{settingsMeta.min}-{settingsMeta.max} sn arası · öneri: 10-15 sn (sakin), 5-7 sn (güvenli)</p>
		</div>
		<div class="bg-teal-50 border border-teal-200 rounded-lg p-3 text-xs text-teal-800 leading-snug">
			⏱️ Karekod ekranda <strong>{settingsForm.refresh_sec} sn</strong>'de bir değişir ·
			güvenlik geçerliliği <strong>{derivedTtl} sn</strong> (yenileme + 3 sn tarama payı).
		</div>
		{#if settingsError}
			<div class="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">{settingsError}</div>
		{/if}
		<div class="flex justify-end gap-2 pt-1">
			<Button type="button" variant="secondary" onclick={() => (showSettings = false)}>İptal</Button>
			<Button onclick={saveSettings} loading={settingsSaving}>Kaydet</Button>
		</div>
	</div>
</Modal>

<!-- Elle Giriş/Çıkış -->
<Modal bind:show={showManual} title="Elle Giriş / Çıkış" maxWidth="max-w-md">
	<div class="space-y-4">
		<p class="text-xs text-gray-500 leading-snug">Telefonu olmayan / unutan personel için yöneticinin manuel kaydı.</p>
		<div>
			<label for="mf-p" class="block text-sm font-medium text-gray-700 mb-1">Personel</label>
			<Select id="mf-p" size="sm" bind:value={manualForm.personnel_id} onchange={() => (manualForm.type = defaultTypeFor(manualForm.personnel_id))}>
				{#each personnel as p (p.id)}<option value={p.id}>{p.full_name} ({p.employee_code})</option>{/each}
			</Select>
		</div>
		<div>
			<span class="block text-sm font-medium text-gray-700 mb-1">Hareket</span>
			<div class="flex gap-2">
				<button onclick={() => manualForm.type = 'in'} class="flex-1 py-2 rounded-lg border text-sm font-medium cursor-pointer {manualForm.type === 'in' ? 'bg-emerald-50 border-emerald-300 text-emerald-700' : 'border-gray-200 text-gray-500'}">Giriş</button>
				<button onclick={() => manualForm.type = 'out'} class="flex-1 py-2 rounded-lg border text-sm font-medium cursor-pointer {manualForm.type === 'out' ? 'bg-amber-50 border-amber-300 text-amber-700' : 'border-gray-200 text-gray-500'}">Çıkış</button>
			</div>
		</div>
		<div>
			<label for="mf-time" class="block text-sm font-medium text-gray-700 mb-1">Zaman</label>
			<Input id="mf-time" type="datetime-local" size="sm" bind:value={manualForm.punched_at} class="tabular-nums" />
			<p class="text-xs text-gray-500 mt-1">Varsayılan: şimdi. Geçmiş bir an için değiştirebilirsiniz.</p>
		</div>
		<div>
			<label for="mf-note" class="block text-sm font-medium text-gray-700 mb-1">Not (opsiyonel)</label>
			<Input id="mf-note" size="sm" bind:value={manualForm.note} placeholder="ör. telefonu yoktu" />
		</div>
		<div class="flex justify-end gap-2 pt-1">
			<Button type="button" variant="secondary" onclick={() => (showManual = false)}>İptal</Button>
			<Button onclick={doManual} loading={manualSaving}>Kaydet</Button>
		</div>
	</div>
</Modal>

<!-- Kaydı Düzenle (tip / zaman / not) -->
<Modal bind:show={showEditLog} title="Kaydı Düzenle" maxWidth="max-w-md">
	<div class="space-y-4">
		<p class="text-xs text-gray-500 leading-snug">Giriş/çıkış kaydını düzelt. Değişiklik audit'lenir ve onay akışına tabidir.</p>
		<div>
			<span class="block text-sm font-medium text-gray-700 mb-1">Hareket</span>
			<div class="flex gap-2">
				<button onclick={() => editForm.type = 'in'} class="flex-1 py-2 rounded-lg border text-sm font-medium cursor-pointer {editForm.type === 'in' ? 'bg-emerald-50 border-emerald-300 text-emerald-700' : 'border-gray-200 text-gray-500'}">Giriş</button>
				<button onclick={() => editForm.type = 'out'} class="flex-1 py-2 rounded-lg border text-sm font-medium cursor-pointer {editForm.type === 'out' ? 'bg-amber-50 border-amber-300 text-amber-700' : 'border-gray-200 text-gray-500'}">Çıkış</button>
			</div>
		</div>
		<div>
			<label for="ef-time" class="block text-sm font-medium text-gray-700 mb-1">Zaman</label>
			<Input id="ef-time" type="datetime-local" size="sm" bind:value={editForm.punched_at} class="tabular-nums" />
		</div>
		<div>
			<label for="ef-note" class="block text-sm font-medium text-gray-700 mb-1">Not (opsiyonel)</label>
			<Input id="ef-note" size="sm" bind:value={editForm.note} placeholder="ör. düzeltme nedeni" />
		</div>
		<div class="flex justify-end gap-2 pt-1">
			<Button type="button" variant="secondary" onclick={() => (showEditLog = false)}>İptal</Button>
			<Button onclick={saveEditLog} loading={editSaving}>Kaydet</Button>
		</div>
	</div>
</Modal>

<ConfirmDialog
	bind:show={confirmDelLog.show}
	danger
	title="Kaydı Sil"
	message={confirmDelLog.target ? `${confirmDelLog.target.full_name} — ${confirmDelLog.target.type === 'in' ? 'Giriş' : 'Çıkış'} (${fmtDateTime(confirmDelLog.target.punched_at)}) kaydı silinecek. Devam edilsin mi?` : ''}
	confirmText="Sil"
	onCancel={() => (confirmDelLog = { show: false, target: null })}
	onConfirm={doDeleteLog}
/>

<!-- Kayıt Tarihçesi -->
<Modal bind:show={showHistory} title="Kayıt Tarihçesi" maxWidth="max-w-lg">
	<div class="space-y-3 text-sm">
		<p class="text-xs text-gray-500">{historyTitle}</p>
		{#if !historyData}
			<div class="py-8 flex justify-center" role="status" aria-label="Yükleniyor"><Loader2 size={32} class="animate-spin text-teal-700" /></div>
		{:else if historyData.history.length === 0 && !historyData.pending_action}
			<EmptyState icon={History} title="Bu kayıt için değişiklik kaydı yok" />
		{:else}
			{#if historyData.pending_action}
				<div class="bg-amber-50 border border-amber-200 rounded-lg p-2.5 text-xs text-amber-800">
					⏳ Bu kayıt için <strong>{actionLabel(historyData.pending_action)}</strong> onayı bekliyor.
				</div>
			{/if}
			<ol class="relative border-l-2 border-gray-100 ml-2 space-y-4 pt-1">
				{#each historyData.history as h (h.created_at)}
					<li class="ml-4">
						<span class="absolute -left-[7px] w-3 h-3 rounded-full {h.action === 'delete' ? 'bg-red-400' : h.action === 'update' ? 'bg-blue-400' : 'bg-emerald-400'}"></span>
						<div class="text-gray-800 font-medium">
							{h.action === 'manual_punch' ? 'Elle oluşturuldu' : h.action === 'update' ? 'Düzenlendi' : h.action === 'delete' ? 'Silindi' : h.action}
						</div>
						{#if h.details}<div class="text-xs text-gray-500">{h.details}</div>{/if}
						<div class="text-[11px] text-gray-500 mt-0.5">{h.user_name ?? 'Sistem'} · {fmtDateTime(h.created_at)}</div>
					</li>
				{/each}
			</ol>
		{/if}
		<div class="flex justify-end pt-1">
			<Button type="button" variant="secondary" onclick={() => (showHistory = false)}>Kapat</Button>
		</div>
	</div>
</Modal>

<ConfirmDialog
	bind:show={confirmDel.show}
	danger
	title="Personeli Sil"
	message={confirmDel.target ? `${confirmDel.target.full_name} silinecek. Tüm giriş/çıkış geçmişi de silinir. Devam edilsin mi?` : ''}
	confirmText="Sil"
	onCancel={() => (confirmDel = { show: false, target: null })}
	onConfirm={doDelete}
/>

<ConfirmDialog
	bind:show={confirmReset.show}
	title="Cihazı Sıfırla"
	message={confirmReset.target ? `${confirmReset.target.full_name} için bağlı cihaz çözülecek. Mevcut telefonu basış yapamaz; personel kişisel QR kartını tekrar okutarak yeni telefonunu bağlar. Devam edilsin mi?` : ''}
	confirmText="Sıfırla"
	onCancel={() => (confirmReset = { show: false, target: null })}
	onConfirm={doResetDevice}
/>
