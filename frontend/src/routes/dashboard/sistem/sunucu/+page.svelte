<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import Button from '$lib/components/Button.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Select from '$lib/components/Select.svelte';
	import { RefreshCw, RotateCw, FileText, Cpu, MemoryStick, HardDrive, Clock, Mail, Trash2, Info } from 'lucide-svelte';

	interface ServiceInfo {
		name: string;
		active: boolean;
		memory_bytes: number;
		memory_mb: number;
		main_pid: number;
	}

	interface ServerInfo {
		cpu: { percent: number; cores: number; load_avg_1m: number; load_avg_5m: number; load_avg_15m: number };
		memory: { total_mb: number; used_mb: number; free_mb: number; percent: number; swap_total_mb: number; swap_used_mb: number };
		disk: { total_gb: number; used_gb: number; free_gb: number; percent: number };
		uptime_seconds: number;
		services: ServiceInfo[];
		storage: { db_size_mb: number | null; uploads_mb: number; logs_mb: number };
		fetched_at: string;
	}

	interface DiskCategory {
		key: string;
		label: string;
		path: string;
		description: string;
		cleanable: boolean;
		size_bytes: number;
		cleanable_bytes: number;
	}

	interface DiskDetail {
		filesystem: { mount: string; total_bytes: number; used_bytes: number; free_bytes: number; percent: number };
		categories: DiskCategory[];
		other_bytes: number;
		total_cleanable_bytes: number;
		cleanable_keys: string[];
		scanned_at: string;
	}

	const REFRESH_MS = 30000;
	const SERVICE_LABELS: Record<string, string> = {
		'sprenses-api': 'Backend API',
		'sprenses-frontend': 'Frontend',
		'sprenses-exchange-rates': 'Döviz Kuru Cron',
		'postgresql': 'PostgreSQL',
		'nginx': 'Nginx',
	};

	const canView = hasPermission('system.server', 'view');
	const canUse = hasPermission('system.server', 'use');

	let info = $state<ServerInfo | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let refreshing = $state(false);
	let refreshTimer: ReturnType<typeof setInterval> | null = null;

	// Restart onayı
	let confirmRestart = $state<{ show: boolean; service: string }>({ show: false, service: '' });
	let restartingService = $state<string | null>(null);

	// Log modal
	let logModal = $state<{ show: boolean; service: string; content: string; loading: boolean }>({
		show: false, service: '', content: '', loading: false,
	});

	// Disk detay modalı (Disk kartına tıklanınca) — `du` ile ölçüldüğü için ayrı endpoint,
	// 30 sn'lik otomatik yenilemeye dahil DEĞİL.
	let diskModal = $state<{ show: boolean; loading: boolean; cleaning: boolean; data: DiskDetail | null }>({
		show: false, loading: false, cleaning: false, data: null,
	});
	let confirmCleanup = $state(false);

	let diskCleanableCats = $derived(
		(diskModal.data?.categories ?? [])
			.filter((c) => c.cleanable)
			.sort((a, b) => b.cleanable_bytes - a.cleanable_bytes),
	);
	let diskKeepCats = $derived(
		(diskModal.data?.categories ?? [])
			.filter((c) => !c.cleanable)
			.sort((a, b) => b.size_bytes - a.size_bytes),
	);

	// SMTP deneme e-postası
	interface TestRecipient { id: number; name: string; email: string }
	let sendingTest = $state(false);
	let recipients = $state<TestRecipient[]>([]);
	let selectedRecipient = $state<string>(''); // '' = sistem kutusu

	async function loadRecipients() {
		try {
			recipients = await api.get<TestRecipient[]>('/notifications/test-email/recipients');
		} catch (e: any) {
			console.error('Alıcı listesi alınamadı:', e);
			// Liste alınamazsa dropdown yalnız sistem kutusu ile çalışır
		}
	}

	async function sendTestEmail() {
		sendingTest = true;
		try {
			const res = await api.post<{ success: boolean; sent_to: string }>(
				'/notifications/test-email',
				{ user_id: selectedRecipient === '' ? null : Number(selectedRecipient) },
			);
			showToast(`Deneme e-postası gönderildi: ${res.sent_to}`, 'success');
		} catch (e: any) {
			console.error('Deneme e-postası gönderilemedi:', e);
			showToast(e?.message || 'Deneme e-postası gönderilemedi', 'error');
		} finally {
			sendingTest = false;
		}
	}

	function formatUptime(sec: number): string {
		const d = Math.floor(sec / 86400);
		const h = Math.floor((sec % 86400) / 3600);
		const m = Math.floor((sec % 3600) / 60);
		if (d > 0) return `${d} gün ${h} saat`;
		if (h > 0) return `${h} saat ${m} dk`;
		return `${m} dk`;
	}

	function fmtMb(mb: number): string {
		if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
		return `${Math.round(mb)} MB`;
	}

	function fmtBytes(b: number): string {
		if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(1)} GB`;
		if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(0)} MB`;
		if (b >= 1024) return `${(b / 1024).toFixed(0)} KB`;
		return `${b} B`;
	}

	function percentAccent(p: number): 'red' | 'amber' | 'teal' {
		if (p >= 90) return 'red';
		if (p >= 75) return 'amber';
		return 'teal';
	}

	async function loadInfo() {
		refreshing = true;
		error = null;
		try {
			const data = await api.get<ServerInfo>('/system/server/info');
			info = data;
		} catch (e: any) {
			console.error('Sunucu bilgisi alınamadı:', e);
			error = e?.message || 'Sunucu bilgisi alınamadı';
		} finally {
			refreshing = false;
			loading = false;
		}
	}

	async function openDiskDetail() {
		diskModal = { ...diskModal, show: true, loading: true };
		try {
			const data = await api.get<DiskDetail>('/system/server/disk');
			diskModal = { ...diskModal, data, loading: false };
		} catch (e: any) {
			console.error('Disk detayı alınamadı:', e);
			showToast(e?.message || 'Disk detayı alınamadı', 'error');
			diskModal = { ...diskModal, loading: false };
		}
	}

	async function doCleanup() {
		confirmCleanup = false;
		diskModal = { ...diskModal, cleaning: true };
		try {
			const res = await api.post<{ freed_bytes: number }>('/system/server/disk/cleanup', {});
			showToast(`Temizlik tamamlandı — ${fmtBytes(res.freed_bytes)} serbest bırakıldı`, 'success');
			// Hem modal dökümünü hem üstteki Disk kartını tazele
			const data = await api.get<DiskDetail>('/system/server/disk');
			diskModal = { ...diskModal, data, cleaning: false };
			loadInfo();
		} catch (e: any) {
			console.error('Disk temizliği başarısız:', e);
			showToast(e?.message || 'Disk temizliği başarısız', 'error');
			diskModal = { ...diskModal, cleaning: false };
		}
	}

	function askRestart(serviceName: string) {
		confirmRestart = { show: true, service: serviceName };
	}

	async function doRestart() {
		const svc = confirmRestart.service;
		confirmRestart = { show: false, service: '' };
		restartingService = svc;
		try {
			await api.post(`/system/server/services/${svc}/restart`, {});
			showToast(`${SERVICE_LABELS[svc] || svc} yeniden başlatıldı`, 'success');
			// 2 sn sonra info yeniden çek (servis tekrar ayağa kalksın)
			setTimeout(loadInfo, 2000);
		} catch (e: any) {
			console.error('Restart başarısız:', e);
			showToast(e?.message || 'Restart başarısız', 'error');
		} finally {
			restartingService = null;
		}
	}

	async function openLog(serviceName: string) {
		logModal = { show: true, service: serviceName, content: '', loading: true };
		try {
			const res = await api.get<{ log: string }>(`/system/server/services/${serviceName}/logs?lines=100`);
			logModal = { ...logModal, content: res.log || '(log boş)', loading: false };
		} catch (e: any) {
			console.error('Log alınamadı:', e);
			logModal = { ...logModal, content: `Log alınamadı: ${e?.message || 'bilinmeyen hata'}`, loading: false };
		}
	}

	onMount(() => {
		if (!canView) return;
		loadInfo();
		if (canUse) loadRecipients();
		// Sayfa boyunca 30 sn'de bir otomatik yenile (sayfa kapanınca durur)
		refreshTimer = setInterval(loadInfo, REFRESH_MS);
	});

	onDestroy(() => {
		if (refreshTimer) clearInterval(refreshTimer);
	});
</script>

<svelte:head>
	<title>Sunucu — Sprenses</title>
</svelte:head>

{#if !canView}
	<div class="text-center py-20 text-gray-500">
		Bu sayfayı görüntüleme yetkiniz yok.
	</div>
{:else}
	<div class="space-y-6">
		<!-- Başlık + Yenile -->
		<PageHeader
			title="Sunucu"
			description={info
				? `Son güncelleme: ${new Date(info.fetched_at).toLocaleTimeString('tr-TR')} · 30 sn'de bir otomatik yenilenir`
				: "Sistem metrikleri 30 sn'de bir otomatik yenilenir"}
		>
			{#snippet actions()}
				<Button onclick={loadInfo} disabled={refreshing}>
					<RefreshCw size={16} class={refreshing ? 'animate-spin' : ''} />
					Yenile
				</Button>
			{/snippet}
		</PageHeader>

		{#if loading}
			<TableSkeleton rows={5} columns={4} />
		{:else if error && !info}
			<div class="bg-red-50 border border-red-200 text-red-700 rounded-xl p-4">
				{error}
			</div>
		{:else if info}
			<!-- ─── Stat Cards ──────────────────────────────────────── -->
			<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
				<StatCard
					label="CPU"
					value="{info.cpu.percent.toFixed(1)}%"
					icon={Cpu}
					accent={percentAccent(info.cpu.percent)}
					hint="{info.cpu.cores} core · load {info.cpu.load_avg_1m} / {info.cpu.load_avg_5m} / {info.cpu.load_avg_15m}"
				/>
				<StatCard
					label="RAM"
					value="{info.memory.percent.toFixed(0)}%"
					icon={MemoryStick}
					accent={percentAccent(info.memory.percent)}
					hint="{fmtMb(info.memory.used_mb)} / {fmtMb(info.memory.total_mb)}{info.memory.swap_total_mb === 0 ? ' · swap yok (OOM riski)' : ''}"
				/>
				<StatCard
					label="Disk"
					value="{info.disk.percent.toFixed(0)}%"
					icon={HardDrive}
					accent={percentAccent(info.disk.percent)}
					hint="{info.disk.used_gb} GB / {info.disk.total_gb} GB · {info.disk.free_gb} GB boş — detay için tıklayın"
					onclick={openDiskDetail}
				/>
				<StatCard
					label="Uptime"
					value={formatUptime(info.uptime_seconds)}
					icon={Clock}
					accent="teal"
					hint="Son yeniden başlatma"
				/>
			</div>

			<!-- ─── Servisler Tablosu ──────────────────────────────── -->
			<div class="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
				<div class="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
					<h2 class="font-semibold text-gray-800">Servisler</h2>
					<span class="text-xs text-gray-500">{info.services.filter((s) => s.active).length}/{info.services.length} aktif</span>
				</div>
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead class="bg-gray-50 text-xs text-gray-500 uppercase tracking-wider">
							<tr>
								<th class="text-left px-5 py-2.5">Servis</th>
								<th class="text-left px-5 py-2.5">Durum</th>
								<th class="text-right px-5 py-2.5">RAM</th>
								<th class="text-right px-5 py-2.5">PID</th>
								<th class="text-right px-5 py-2.5">İşlem</th>
							</tr>
						</thead>
						<tbody>
							{#each info.services as svc (svc.name)}
								<tr class="border-t border-gray-100 hover:bg-gray-50">
									<td class="px-5 py-3">
										<div class="font-medium text-gray-800">{SERVICE_LABELS[svc.name] || svc.name}</div>
										<div class="text-xs text-gray-500 font-mono">{svc.name}</div>
									</td>
									<td class="px-5 py-3">
										{#if svc.active}
											<StatusBadge type="success">Aktif</StatusBadge>
										{:else}
											<StatusBadge type="neutral">Pasif</StatusBadge>
										{/if}
									</td>
									<td class="px-5 py-3 text-right text-gray-700">
										{svc.active ? fmtMb(svc.memory_mb) : '—'}
									</td>
									<td class="px-5 py-3 text-right text-gray-500 font-mono text-xs">
										{svc.main_pid > 0 ? svc.main_pid : '—'}
									</td>
									<td class="px-5 py-3 text-right">
										<div class="inline-flex items-center gap-1">
											<button
												onclick={() => openLog(svc.name)}
												class="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg cursor-pointer"
												title="Logları görüntüle"
												aria-label="{svc.name} loglarını görüntüle"
											>
												<FileText class="w-4 h-4" />
											</button>
											{#if canUse}
												<button
													onclick={() => askRestart(svc.name)}
													disabled={restartingService === svc.name}
													class="p-1.5 text-orange-500 hover:text-orange-700 hover:bg-orange-50 rounded-lg cursor-pointer disabled:opacity-50"
													title="Yeniden başlat"
													aria-label="{svc.name} servisini yeniden başlat"
												>
													<RotateCw class="w-4 h-4 {restartingService === svc.name ? 'animate-spin' : ''}" />
												</button>
											{/if}
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<!-- ─── Depolama Detayı ─────────────────────────────── -->
			<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-5">
				<h2 class="font-semibold text-gray-800 mb-4">Depolama Dağılımı</h2>
				<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
					<div>
						<div class="text-xs text-gray-500 uppercase tracking-wider">PostgreSQL DB</div>
						<div class="text-2xl font-bold text-gray-800 mt-1">
							{info.storage.db_size_mb !== null ? fmtMb(info.storage.db_size_mb) : '—'}
						</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 uppercase tracking-wider">Uploads (müşteri dosyaları)</div>
						<div class="text-2xl font-bold text-gray-800 mt-1">{fmtMb(info.storage.uploads_mb)}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 uppercase tracking-wider">Loglar</div>
						<div class="text-2xl font-bold text-gray-800 mt-1">{fmtMb(info.storage.logs_mb)}</div>
					</div>
				</div>
			</div>
		{/if}

		<!-- ─── E-posta (SMTP) Testi ──────────────────────────── -->
		{#if canUse}
			<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-5">
				<div class="mb-4">
					<h2 class="font-semibold text-gray-800 flex items-center gap-2">
						<Mail class="w-4 h-4 text-gray-500" /> E-posta (SMTP)
					</h2>
					<p class="text-sm text-gray-500 mt-1">
						Giden e-posta bildiriminin çalıştığını doğrulamak için bir alıcı seçip deneme
						e-postası gönderin. Kullanıcı seçerseniz o kişinin tanımlı adresine gider —
						böylece adresin gerçekten teslim aldığını da test edersiniz.
					</p>
				</div>
				<div class="flex flex-col sm:flex-row sm:items-end gap-3">
					<label class="flex-1 min-w-0">
						<span class="block text-xs text-gray-500 mb-1">Alıcı</span>
						<Select bind:value={selectedRecipient} aria-label="Deneme e-postası alıcısı">
							<option value="">Sistem kutusu (bilgi@sprenses.com)</option>
							{#each recipients as r (r.id)}
								<option value={String(r.id)}>{r.name} — {r.email}</option>
							{/each}
						</Select>
					</label>
					<Button onclick={sendTestEmail} loading={sendingTest} class="w-full sm:w-auto shrink-0">
						<Mail size={16} /> Deneme e-postası gönder
					</Button>
				</div>
			</div>
		{/if}
	</div>
{/if}

<!-- Restart onay diyalogu -->
<ConfirmDialog
	bind:show={confirmRestart.show}
	title="Servisi Yeniden Başlat"
	message="{SERVICE_LABELS[confirmRestart.service] || confirmRestart.service} servisini yeniden başlatmak istediğinize emin misiniz? 1-3 saniye kesintiye yol açar."
	confirmText="Yeniden Başlat"
	danger={true}
	onConfirm={doRestart}
/>

<!-- Disk detay modalı -->
<Modal
	bind:show={diskModal.show}
	title="Disk Kullanımı — Döküm ve Temizlik"
	maxWidth="max-w-3xl"
	onclose={() => (diskModal = { ...diskModal, show: false })}
>
	{#if diskModal.loading && !diskModal.data}
		<TableSkeleton rows={8} columns={3} />
	{:else if diskModal.data}
		{@const fs = diskModal.data.filesystem}
		<div class="space-y-5">
			<!-- Doluluk çubuğu -->
			<div>
				<div class="flex items-baseline justify-between text-sm">
					<span class="font-medium text-gray-800">{fs.mount} bölümü</span>
					<span class="text-gray-600 tabular-nums">
						{fmtBytes(fs.used_bytes)} / {fmtBytes(fs.total_bytes)} · {fmtBytes(fs.free_bytes)} boş
					</span>
				</div>
				<div class="mt-2 h-3 w-full rounded-full bg-gray-100 overflow-hidden">
					<div
						class="h-full rounded-full {fs.percent >= 90 ? 'bg-red-600' : fs.percent >= 75 ? 'bg-amber-500' : 'bg-teal-700'}"
						style="width: {Math.min(100, fs.percent)}%"
					></div>
				</div>
				<div class="mt-1 text-xs text-gray-500">%{fs.percent.toFixed(1)} dolu</div>
			</div>

			<!-- Temizlenebilir özet + aksiyon -->
			<div class="rounded-xl border border-gray-200 bg-gray-50 p-4 flex flex-col sm:flex-row sm:items-center gap-3">
				<div class="flex-1 min-w-0">
					<div class="text-sm font-medium text-gray-800">
						Şu anda temizlenebilir: <span class="tabular-nums">{fmtBytes(diskModal.data.total_cleanable_bytes)}</span>
					</div>
					<p class="text-xs text-gray-500 mt-1">
						Yalnızca yeniden üretilebilen veriler (önbellek + eski loglar) silinir. Müşteri dosyaları,
						yedekler ve bağımlılıklar korunur. Bu temizlik her gün 04:30'da otomatik de çalışır.
					</p>
				</div>
				{#if canUse}
					<Button
						variant="danger"
						onclick={() => (confirmCleanup = true)}
						loading={diskModal.cleaning}
						disabled={diskModal.data.total_cleanable_bytes === 0}
						class="shrink-0"
					>
						<Trash2 size={16} /> Şimdi Temizle
					</Button>
				{/if}
			</div>

			<!-- Temizlenebilir kategoriler -->
			<div>
				<h3 class="text-sm font-semibold text-gray-800 mb-2">Temizlenebilir</h3>
				<div class="overflow-x-auto border border-gray-200 rounded-xl">
					<table class="w-full text-sm">
						<thead class="bg-gray-50 text-xs text-gray-600 uppercase tracking-wider">
							<tr>
								<th class="text-left px-4 py-2">Kategori</th>
								<th class="text-right px-4 py-2">Toplam</th>
								<th class="text-right px-4 py-2">Temizlenebilir</th>
							</tr>
						</thead>
						<tbody>
							{#each diskCleanableCats as cat (cat.key)}
								<tr class="border-t border-gray-100">
									<td class="px-4 py-2.5">
										<div class="font-medium text-gray-800">{cat.label}</div>
										<div class="text-xs text-gray-500">{cat.description}</div>
									</td>
									<td class="px-4 py-2.5 text-right text-gray-700 tabular-nums whitespace-nowrap">{fmtBytes(cat.size_bytes)}</td>
									<td class="px-4 py-2.5 text-right tabular-nums whitespace-nowrap {cat.cleanable_bytes > 0 ? 'font-semibold text-teal-700' : 'text-gray-400'}">
										{cat.cleanable_bytes > 0 ? fmtBytes(cat.cleanable_bytes) : '—'}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Korunan kategoriler -->
			<div>
				<h3 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5">
					<Info class="w-4 h-4 text-gray-500" /> Korunan (silinmez)
				</h3>
				<div class="overflow-x-auto border border-gray-200 rounded-xl">
					<table class="w-full text-sm">
						<tbody>
							{#each diskKeepCats as cat (cat.key)}
								<tr class="border-b border-gray-100 last:border-b-0">
									<td class="px-4 py-2.5">
										<div class="font-medium text-gray-800">{cat.label}</div>
										<div class="text-xs text-gray-500">{cat.description}</div>
									</td>
									<td class="px-4 py-2.5 text-right text-gray-700 tabular-nums whitespace-nowrap">{fmtBytes(cat.size_bytes)}</td>
								</tr>
							{/each}
							<tr class="border-t border-gray-100 bg-gray-50">
								<td class="px-4 py-2.5">
									<div class="font-medium text-gray-800">Diğer</div>
									<div class="text-xs text-gray-500">İşletim sistemi, kurulu paketler ve ölçülmeyen dizinler.</div>
								</td>
								<td class="px-4 py-2.5 text-right text-gray-700 tabular-nums whitespace-nowrap">{fmtBytes(diskModal.data.other_bytes)}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<p class="text-xs text-gray-500">
				Ölçüm: {new Date(diskModal.data.scanned_at).toLocaleString('tr-TR')}
			</p>
		</div>
	{/if}
</Modal>

<!-- Temizlik onay diyalogu -->
<ConfirmDialog
	bind:show={confirmCleanup}
	title="Diski Temizle"
	message="Önbellek dosyaları ve eski loglar silinecek ({diskModal.data ? fmtBytes(diskModal.data.total_cleanable_bytes) : '—'}). Müşteri dosyaları, yedekler ve bağımlılıklar etkilenmez. Devam edilsin mi?"
	confirmText="Temizle"
	danger={true}
	onConfirm={doCleanup}
/>

<!-- Log modal -->
<Modal
	bind:show={logModal.show}
	title="{SERVICE_LABELS[logModal.service] || logModal.service} — Son 100 satır log"
	maxWidth="max-w-3xl"
	onclose={() => (logModal = { show: false, service: '', content: '', loading: false })}
>
	{#if logModal.loading}
		<TableSkeleton rows={6} columns={1} showHeader={false} />
	{:else}
		<pre class="bg-gray-900 text-gray-100 text-xs font-mono p-4 rounded-lg overflow-auto max-h-[60vh] whitespace-pre-wrap">{logModal.content}</pre>
	{/if}
</Modal>
