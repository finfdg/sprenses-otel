<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import Button from '$lib/components/Button.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { RefreshCw, RotateCw, FileText, Cpu, MemoryStick, HardDrive, Clock } from 'lucide-svelte';

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

	const REFRESH_MS = 30000;
	const SERVICE_LABELS: Record<string, string> = {
		'sprenses-api': 'Backend API',
		'sprenses-frontend': 'Frontend',
		'sprenses-exchange-rates': 'Döviz Kuru Cron',
		'sprenses-quality-forms': 'Kalite Form Cron',
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

	function percentColor(p: number): string {
		if (p >= 90) return 'text-red-600';
		if (p >= 75) return 'text-orange-600';
		if (p >= 50) return 'text-amber-600';
		return 'text-teal-600';
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
			<div class="text-center py-20 text-gray-500">Yükleniyor…</div>
		{:else if error && !info}
			<div class="bg-red-50 border border-red-200 text-red-700 rounded-xl p-4">
				{error}
			</div>
		{:else if info}
			<!-- ─── Stat Cards ──────────────────────────────────────── -->
			<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
				<div class="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
					<div class="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wider mb-1">
						<Cpu class="w-4 h-4" />
						CPU
					</div>
					<div class="text-3xl font-bold {percentColor(info.cpu.percent)}">{info.cpu.percent.toFixed(1)}%</div>
					<div class="text-xs text-gray-500 mt-1">
						{info.cpu.cores} core · load {info.cpu.load_avg_1m} / {info.cpu.load_avg_5m} / {info.cpu.load_avg_15m}
					</div>
				</div>

				<div class="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
					<div class="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wider mb-1">
						<MemoryStick class="w-4 h-4" />
						RAM
					</div>
					<div class="text-3xl font-bold {percentColor(info.memory.percent)}">{info.memory.percent.toFixed(0)}%</div>
					<div class="text-xs text-gray-500 mt-1">
						{fmtMb(info.memory.used_mb)} / {fmtMb(info.memory.total_mb)}
						{#if info.memory.swap_total_mb === 0}
							<span class="text-orange-500" title="Swap yok — OOM riski">· swap yok</span>
						{/if}
					</div>
				</div>

				<div class="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
					<div class="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wider mb-1">
						<HardDrive class="w-4 h-4" />
						Disk
					</div>
					<div class="text-3xl font-bold {percentColor(info.disk.percent)}">{info.disk.percent.toFixed(0)}%</div>
					<div class="text-xs text-gray-500 mt-1">
						{info.disk.used_gb} GB / {info.disk.total_gb} GB · {info.disk.free_gb} GB boş
					</div>
				</div>

				<div class="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
					<div class="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wider mb-1">
						<Clock class="w-4 h-4" />
						Uptime
					</div>
					<div class="text-2xl font-bold text-teal-600">{formatUptime(info.uptime_seconds)}</div>
					<div class="text-xs text-gray-500 mt-1">Son yeniden başlatma</div>
				</div>
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

<!-- Log modal -->
<Modal
	bind:show={logModal.show}
	title="{SERVICE_LABELS[logModal.service] || logModal.service} — Son 100 satır log"
	maxWidth="max-w-3xl"
	onclose={() => (logModal = { show: false, service: '', content: '', loading: false })}
>
	{#if logModal.loading}
		<div class="text-center py-10 text-gray-500">Log alınıyor…</div>
	{:else}
		<pre class="bg-gray-900 text-gray-100 text-xs font-mono p-4 rounded-lg overflow-auto max-h-[60vh] whitespace-pre-wrap">{logModal.content}</pre>
	{/if}
</Modal>
