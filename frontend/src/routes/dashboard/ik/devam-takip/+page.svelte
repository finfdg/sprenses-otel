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
	import {
		UserPlus, Pencil, Trash2, QrCode, Monitor, History, Clock, Users,
		LogIn, Printer, Copy, Fingerprint, Settings,
	} from 'lucide-svelte';

	type Personnel = {
		id: number; full_name: string; employee_code: string;
		department: string | null; phone: string | null; is_active: boolean; created_at: string;
	};
	type InsideRow = { personnel_id: number; full_name: string; department: string | null; since: string };
	type LogRow = {
		id: number; personnel_id: number; full_name: string; department: string | null;
		type: string; punched_at: string; source: string; note: string | null;
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
	let form = $state({ full_name: '', employee_code: '', department: '', phone: '' });
	let saving = $state(false);
	let formError = $state('');

	let confirmDel = $state<{ show: boolean; target: Personnel | null }>({ show: false, target: null });

	// QR kart modalı
	let qrCard = $state<Personnel | null>(null);

	// Kiosk linki modalı
	let showKiosk = $state(false);
	let kioskUrl = $state('');

	// Elle giriş modalı
	let showManual = $state(false);
	let manualForm = $state({ personnel_id: 0, type: 'in', note: '' });
	let manualSaving = $state(false);

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
		} catch (e) { console.error('Durum alınamadı:', e); }
	}
	async function loadPersonnel() {
		try {
			const r = await api.get<{ items: Personnel[] }>('/attendance/personnel?page_size=200');
			personnel = r.items;
		} catch (e) { console.error('Personel listesi alınamadı:', e); }
	}
	async function loadLogs() {
		try {
			const r = await api.get<{ items: LogRow[] }>('/attendance/logs?page_size=200');
			logs = r.items;
			logsLoaded = true;
		} catch (e) { console.error('Loglar alınamadı:', e); }
	}
	async function loadSummary() {
		try {
			const r = await api.get<{ personnel: SummaryRow[] }>(`/attendance/summary?month=${summaryMonth}`);
			summary = r.personnel;
		} catch (e) { console.error('Puantaj alınamadı:', e); }
	}

	async function refreshAll() {
		loading = true;
		await Promise.all([loadStatus(), loadPersonnel(), loadSummary()]);
		loading = false;
	}

	function switchTab(t: typeof tab) {
		tab = t;
		if (t === 'logs' && !logsLoaded) loadLogs();
	}

	// ── Personel CRUD ──
	function openCreate() {
		editing = null;
		form = { full_name: '', employee_code: '', department: '', phone: '' };
		formError = '';
		showPersonnelModal = true;
	}
	function openEdit(p: Personnel) {
		editing = p;
		form = { full_name: p.full_name, employee_code: p.employee_code, department: p.department ?? '', phone: p.phone ?? '' };
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

	function openManual() {
		manualForm = { personnel_id: personnel[0]?.id ?? 0, type: 'in', note: '' };
		showManual = true;
	}
	async function doManual() {
		if (!manualForm.personnel_id) { showToast('Personel seçin', 'warning'); return; }
		manualSaving = true;
		try {
			await api.post('/attendance/manual', manualForm);
			showToast('Kayıt eklendi', 'success');
			showManual = false;
			await Promise.all([loadStatus(), loadLogs()]);
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'Kayıt başarısız', 'error');
		} finally {
			manualSaving = false;
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
		const unsub = onWsEvent(WS_EVENT.ATTENDANCE_UPDATED, () => {
			loadStatus();
			loadSummary();
			if (logsLoaded) loadLogs();
		});
		return unsub;
	});
</script>

<div class="max-w-6xl mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-5">
	<PageHeader title="Devam Takip" description="Personel giriş/çıkış izleme ve yönetimi (karekod ile)">
		{#snippet actions()}
			{#if canUse}
				<Button variant="secondary" onclick={openManual}><LogIn size={16} /> Elle Giriş</Button>
				<Button variant="secondary" onclick={openKiosk}><Monitor size={16} /> Kiosk Linki</Button>
				<Button variant="secondary" onclick={openSettings}><Settings size={16} /> Ayarlar</Button>
				<Button onclick={openCreate}><UserPlus size={16} /> Yeni Personel</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
		<StatCard label="Şu An İçeride" value={`${inside.length} kişi`} icon={Clock} accent="emerald" hint="Aktif personel" />
		<StatCard label="Toplam Personel" value={`${personnel.length}`} icon={Users} accent="teal" hint="Kayıtlı çalışan" />
		<StatCard label="Bu Ay Çalışan" value={`${summary.length}`} icon={History} accent="blue" hint={summaryMonth} />
	</div>

	<!-- Sekmeler -->
	<div class="flex gap-1 border-b border-gray-200 overflow-x-auto">
		{#each [['inside', 'İçeride'], ['personnel', 'Personel'], ['logs', 'Geçmiş'], ['summary', 'Puantaj']] as [key, label]}
			<button
				onclick={() => switchTab(key as typeof tab)}
				class="px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer whitespace-nowrap {tab === key ? 'border-teal-600 text-teal-700' : 'border-transparent text-gray-500 hover:text-gray-700'}"
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
					<div class="overflow-x-auto">
						<table class="w-full text-sm">
							<thead class="bg-gray-50 border-b border-gray-200">
								<tr>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Ad Soyad</th>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Sicil</th>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs hidden sm:table-cell">Departman</th>
									<th class="px-4 py-3 text-center font-medium text-gray-500 text-xs">Durum</th>
									<th class="px-4 py-3 text-right font-medium text-gray-500 text-xs">İşlem</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-gray-100">
								{#each personnel as p (p.id)}
									<tr class="hover:bg-gray-50">
										<td class="px-4 py-3 text-gray-900">{p.full_name}</td>
										<td class="px-4 py-3 font-mono text-xs text-gray-600">{p.employee_code}</td>
										<td class="px-4 py-3 text-gray-600 hidden sm:table-cell">{p.department ?? '—'}</td>
										<td class="px-4 py-3 text-center">
											{#if p.is_active}<StatusBadge type="success">Aktif</StatusBadge>{:else}<StatusBadge type="neutral">Pasif</StatusBadge>{/if}
										</td>
										<td class="px-4 py-3">
											<div class="flex items-center justify-end gap-1">
												<button onclick={() => qrCard = p} class="p-1.5 text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded cursor-pointer" title="QR Kart">
													<QrCode size={16} />
												</button>
												{#if canUse}
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
				{/if}

			<!-- GEÇMİŞ -->
			{:else if tab === 'logs'}
				{#if logs.length === 0}
					<EmptyState icon={History} title="Kayıt yok" />
				{:else}
					<div class="overflow-x-auto">
						<table class="w-full text-sm">
							<thead class="bg-gray-50 border-b border-gray-200">
								<tr>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Personel</th>
									<th class="px-4 py-3 text-center font-medium text-gray-500 text-xs">Hareket</th>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Zaman</th>
									<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs hidden sm:table-cell">Kaynak</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-gray-100">
								{#each logs as lg (lg.id)}
									<tr class="hover:bg-gray-50">
										<td class="px-4 py-3 text-gray-900">{lg.full_name}</td>
										<td class="px-4 py-3 text-center">
											{#if lg.type === 'in'}<StatusBadge type="success">Giriş</StatusBadge>{:else}<StatusBadge type="warning">Çıkış</StatusBadge>{/if}
										</td>
										<td class="px-4 py-3 text-gray-600 text-xs whitespace-nowrap">{fmtDateTime(lg.punched_at)}</td>
										<td class="px-4 py-3 text-gray-500 text-xs hidden sm:table-cell">
											{lg.source === 'manual' ? 'Elle' : 'Karekod'}{lg.note ? ` · ${lg.note}` : ''}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}

			<!-- PUANTAJ -->
			{:else if tab === 'summary'}
				<div class="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
					<label for="ay" class="text-xs text-gray-500">Ay:</label>
					<input id="ay" type="month" bind:value={summaryMonth} onchange={loadSummary} class="text-sm border border-gray-200 rounded-lg px-2 py-1" />
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
			<input id="pf-name" type="text" bind:value={form.full_name} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
		</div>
		<div class="grid grid-cols-2 gap-3">
			<div>
				<label for="pf-code" class="block text-sm font-medium text-gray-700 mb-1">Sicil No <span class="text-red-600">*</span></label>
				<input id="pf-code" type="text" bind:value={form.employee_code} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-teal-500 outline-none" />
			</div>
			<div>
				<label for="pf-dept" class="block text-sm font-medium text-gray-700 mb-1">Departman</label>
				<input id="pf-dept" type="text" bind:value={form.department} placeholder="Mutfak, Kat, Resepsiyon…" class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
			</div>
		</div>
		<div>
			<label for="pf-phone" class="block text-sm font-medium text-gray-700 mb-1">Telefon</label>
			<input id="pf-phone" type="text" bind:value={form.phone} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
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
			<div class="text-xs font-mono text-gray-500">{qrCard.employee_code}{qrCard.department ? ` · ${qrCard.department}` : ''}</div>
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
			⚠️ Bu link gizli bir anahtar içerir — yalnızca giriş cihazında açın, paylaşmayın.
		</div>
		<div class="flex items-center gap-2">
			<input readonly value={kioskUrl} class="flex-1 text-xs font-mono border border-gray-200 rounded-lg px-2 py-2 bg-gray-50 truncate" />
			<Button variant="secondary" onclick={copyKiosk}><Copy size={14} /> Kopyala</Button>
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
			<input
				id="set-refresh"
				type="number"
				min={settingsMeta.min}
				max={settingsMeta.max}
				step="1"
				bind:value={settingsForm.refresh_sec}
				class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm tabular-nums focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
			/>
			<p class="text-xs text-gray-400 mt-1">{settingsMeta.min}-{settingsMeta.max} sn arası · öneri: 10-15 sn (sakin), 5-7 sn (güvenli)</p>
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
			<select id="mf-p" bind:value={manualForm.personnel_id} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white">
				{#each personnel as p (p.id)}<option value={p.id}>{p.full_name} ({p.employee_code})</option>{/each}
			</select>
		</div>
		<div>
			<span class="block text-sm font-medium text-gray-700 mb-1">Hareket</span>
			<div class="flex gap-2">
				<button onclick={() => manualForm.type = 'in'} class="flex-1 py-2 rounded-lg border text-sm font-medium cursor-pointer {manualForm.type === 'in' ? 'bg-emerald-50 border-emerald-300 text-emerald-700' : 'border-gray-200 text-gray-500'}">Giriş</button>
				<button onclick={() => manualForm.type = 'out'} class="flex-1 py-2 rounded-lg border text-sm font-medium cursor-pointer {manualForm.type === 'out' ? 'bg-amber-50 border-amber-300 text-amber-700' : 'border-gray-200 text-gray-500'}">Çıkış</button>
			</div>
		</div>
		<div>
			<label for="mf-note" class="block text-sm font-medium text-gray-700 mb-1">Not (opsiyonel)</label>
			<input id="mf-note" type="text" bind:value={manualForm.note} placeholder="ör. telefonu yoktu" class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" />
		</div>
		<div class="flex justify-end gap-2 pt-1">
			<Button type="button" variant="secondary" onclick={() => (showManual = false)}>İptal</Button>
			<Button onclick={doManual} loading={manualSaving}>Kaydet</Button>
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
