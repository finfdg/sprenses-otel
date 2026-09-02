<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import ListPage from '$lib/components/ui/ListPage.svelte';
	import StatCard from '$lib/components/ui/StatCard.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
	import {
		UploadCloud, History, CheckCircle2, Clock, Cloud, RotateCcw,
		Database, FileArchive, ShieldAlert, ShieldCheck
	} from 'lucide-svelte';

	interface Commit {
		short: string;
		subject: string;
		date: string;
		author: string;
	}
	interface Status {
		branch: string;
		last_commit: Commit | null;
		pending_changes: number;
		ahead: number;
		behind: number;
		in_sync: boolean;
		remote_url: string | null;
		history: Commit[];
	}
	interface DataStatus {
		db: { count: number; age_hours: number | null; stale: boolean; last_file: string; bytes: number };
		uploads: { snapshots: number; age_hours: number | null; files: number };
		offsite: {
			configured: boolean;
			ok: boolean;
			target: string;
			last_ok: string | null;
			age_hours: number | null;
			error: string;
			level: 'ok' | 'warning' | 'critical';
			message: string;
		};
		last_run: string | null;
		stale_threshold_hours: number;
	}

	const canUse = hasPermission('system.backup', 'use');

	let status = $state<Status | null>(null);
	let dataStatus = $state<DataStatus | null>(null);
	let loading = $state(true);
	let backing = $state(false);
	let restoring = $state(false);

	let restoreTarget = $state<Commit | null>(null);
	let showRestoreConfirm = $state(false);

	function fmtDate(iso: string): string {
		const d = new Date(iso);
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	}

	function fmtRelative(iso: string): string {
		const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
		if (diff < 60) return `${diff} sn önce`;
		if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
		if (diff < 86400) return `${Math.floor(diff / 3600)} saat önce`;
		if (diff < 604800) return `${Math.floor(diff / 86400)} gün önce`;
		return fmtDate(iso);
	}

	function isAuto(subject: string): boolean {
		return subject.startsWith('Otomatik yedek') || subject.startsWith('Manuel yedek') || subject.startsWith('Geri yükleme');
	}

	function fmtAge(hours: number | null): string {
		if (hours === null || hours === undefined) return '—';
		if (hours < 1) return `${Math.round(hours * 60)} dk önce`;
		if (hours < 48) return `${Math.round(hours)} saat önce`;
		return `${Math.round(hours / 24)} gün önce`;
	}

	function fmtSize(bytes: number): string {
		if (!bytes) return '—';
		const mb = bytes / (1024 * 1024);
		return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
	}

	async function load() {
		loading = true;
		try {
			// İki durum bağımsız: veri yedeği okunamazsa kod yedeği yine gösterilsin
			// (ve tersi) — biri diğerini karartmamalı.
			const [git, data] = await Promise.allSettled([
				api.get<Status>('/system/backup/status'),
				api.get<DataStatus>('/system/backup/data-status')
			]);
			if (git.status === 'fulfilled') {
				status = git.value;
			} else {
				console.error('Kod yedeği durumu alınamadı:', git.reason);
				showToast('Kod yedeği durumu alınamadı', 'error');
			}
			if (data.status === 'fulfilled') {
				dataStatus = data.value;
			} else {
				console.error('Veri yedeği durumu alınamadı:', data.reason);
				showToast('Veri yedeği durumu alınamadı', 'error');
			}
		} finally {
			loading = false;
		}
	}

	async function backupNow() {
		if (backing) return;
		backing = true;
		try {
			const r = await api.post<{ changed_files: number; pushed: boolean; message: string }>('/system/backup/run', {});
			if (r.pushed) {
				showToast(r.changed_files > 0 ? `${r.changed_files} değişiklik yedeklendi` : 'Zaten günceldi, yedek senkronlandı', 'success');
			} else {
				showToast(r.message || 'Push başarısız', 'error', 5000);
			}
			await load();
		} catch (err) {
			const msg = err instanceof ApiError ? err.message : 'Yedekleme başarısız';
			showToast(msg, 'error', 5000);
		} finally {
			backing = false;
		}
	}

	function askRestore(c: Commit) {
		restoreTarget = c;
		showRestoreConfirm = true;
	}

	async function doRestore() {
		if (!restoreTarget || restoring) return;
		restoring = true;
		try {
			const r = await api.post<{ restored: boolean; redeploy_needed: boolean; message: string }>(
				'/system/backup/restore',
				{ commit: restoreTarget.short }
			);
			showToast(r.message, r.restored ? 'warning' : 'info', 8000);
			showRestoreConfirm = false;
			restoreTarget = null;
			await load();
		} catch (err) {
			const msg = err instanceof ApiError ? err.message : 'Geri yükleme başarısız';
			showToast(msg, 'error', 6000);
		} finally {
			restoring = false;
		}
	}

	onMount(load);
</script>

<ListPage
	title="Yedekleme"
	description="Kodun GitHub'daki yedek durumu — izleme, manuel yedek ve geri yükleme"
	{loading}
	isEmpty={!loading && (!status || status.history.length === 0)}
	emptyIcon={Cloud}
	emptyTitle="Yedek bilgisi bulunamadı"
	maxWidth="max-w-5xl"
	skeletonRows={6}
>
	{#snippet actions()}
		{#if canUse}
			<Button onclick={backupNow} loading={backing}>
				<UploadCloud size={16} /> Şimdi Yedekle
			</Button>
		{/if}
	{/snippet}

	{#snippet stats()}
		{#if status}
			<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
				<StatCard
					label="Son Yedek"
					value={status.last_commit ? fmtRelative(status.last_commit.date) : '—'}
					hint={status.last_commit?.subject ?? ''}
					icon={History}
					accent="teal"
				/>
				<StatCard
					label="Senkron Durumu"
					value={status.in_sync ? 'Güncel' : 'Bekliyor'}
					hint={status.in_sync
						? 'Tüm değişiklikler GitHub\'da'
						: `${status.pending_changes} bekleyen değişiklik${status.ahead > 0 ? `, ${status.ahead} gönderilmemiş commit` : ''}`}
					icon={status.in_sync ? CheckCircle2 : Clock}
					accent={status.in_sync ? 'emerald' : 'amber'}
				/>
				<StatCard
					label="Yedek Deposu"
					value="GitHub · Private"
					hint={status.remote_url ?? ''}
					icon={Cloud}
					accent="blue"
				/>
			</div>
		{/if}
	{/snippet}

	<!-- Veri yedeği (DB · uploads · off-site) — kod yedeğinden AYRI.
	     Denetim DR-002: off-site eksikliği hiçbir ekranda görünmediği için iki denetim
	     boyunca açık kaldı. Buradaki kart, kurulana kadar kırmızı durur. -->
	{#if dataStatus}
		<div class="mb-6">
			<div class="flex items-baseline justify-between mb-3">
				<h2 class="text-base font-semibold text-gray-900">Veri Yedeği</h2>
				<span class="text-xs text-gray-500">
					Veritabanı ve yüklenen belgeler — kod yedeğinden ayrıdır
				</span>
			</div>

			<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4 mb-4">
				<StatCard
					label="Veritabanı Yedeği"
					value={fmtAge(dataStatus.db.age_hours)}
					hint={`${dataStatus.db.count} yedek · ${fmtSize(dataStatus.db.bytes)}`}
					icon={Database}
					accent={dataStatus.db.stale ? 'red' : 'emerald'}
				/>
				<StatCard
					label="Belge Yedeği"
					value={fmtAge(dataStatus.uploads.age_hours)}
					hint={`${dataStatus.uploads.snapshots} snapshot · ${dataStatus.uploads.files} dosya`}
					icon={FileArchive}
					accent={dataStatus.uploads.snapshots === 0 ? 'red' : 'emerald'}
				/>
				<StatCard
					label="Off-site Kopya"
					value={dataStatus.offsite.configured
						? (dataStatus.offsite.ok ? fmtAge(dataStatus.offsite.age_hours) : 'Başarısız')
						: 'YOK'}
					hint={dataStatus.offsite.target || 'Farklı bölgede S3 kurulmadı'}
					icon={dataStatus.offsite.level === 'ok' ? ShieldCheck : ShieldAlert}
					accent={dataStatus.offsite.level === 'ok'
						? 'emerald'
						: dataStatus.offsite.level === 'warning' ? 'amber' : 'red'}
				/>
			</div>

			{#if dataStatus.offsite.level !== 'ok'}
				<div
					class="rounded-xl border p-4 {dataStatus.offsite.level === 'critical'
						? 'border-red-200 bg-red-50'
						: 'border-amber-200 bg-amber-50'}"
					role="alert"
				>
					<div class="flex gap-3">
						<ShieldAlert
							size={18}
							class={dataStatus.offsite.level === 'critical' ? 'text-red-600 shrink-0 mt-0.5' : 'text-amber-600 shrink-0 mt-0.5'}
						/>
						<div class="text-sm">
							<p class={dataStatus.offsite.level === 'critical' ? 'font-medium text-red-900' : 'font-medium text-amber-900'}>
								{dataStatus.offsite.message}
							</p>
							{#if !dataStatus.offsite.configured}
								<p class="text-gray-700 mt-1">
									Kurulum (sunucuda, bir kez):
									<code class="bg-white/70 px-1.5 py-0.5 rounded text-xs font-mono"
										>scripts/provision-offsite-backup.sh &lt;bucket&gt; eu-west-1</code
									>
									sonra
									<code class="bg-white/70 px-1.5 py-0.5 rounded text-xs font-mono"
										>scripts/enable-offsite-backup.sh s3://&lt;bucket&gt;/sprenses</code
									>
								</p>
							{:else if dataStatus.offsite.error}
								<p class="text-gray-700 mt-1">Hata: {dataStatus.offsite.error}</p>
							{/if}
						</div>
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Yedek geçmişi (commit listesi) -->
	<h2 class="text-base font-semibold text-gray-900 mb-3">Kod Yedeği Geçmişi</h2>
	<div class="overflow-x-auto">
		<table class="w-full text-sm">
			<thead class="bg-gray-50 border-b border-gray-200">
				<tr>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Yedek</th>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs hidden sm:table-cell">Tarih</th>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs hidden md:table-cell">Kim</th>
					<th class="px-4 py-3 text-right font-medium text-gray-500 text-xs">İşlem</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100">
				{#each status?.history ?? [] as c, i (c.short)}
					<tr class="hover:bg-gray-50 transition-colors">
						<td class="px-4 py-3">
							<div class="flex items-center gap-2">
								{#if i === 0}
									<StatusBadge type="success">Güncel</StatusBadge>
								{:else if isAuto(c.subject)}
									<StatusBadge type="neutral">Yedek</StatusBadge>
								{/if}
								<span class="text-gray-900 truncate max-w-[280px]" title={c.subject}>{c.subject}</span>
							</div>
							<span class="text-[10px] text-gray-400 font-mono">{c.short}</span>
						</td>
						<td class="px-4 py-3 text-gray-600 text-xs whitespace-nowrap hidden sm:table-cell" title={fmtDate(c.date)}>
							{fmtRelative(c.date)}
						</td>
						<td class="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">{c.author}</td>
						<td class="px-4 py-3 text-right">
							{#if canUse && i !== 0}
								<Button variant="secondary" size="sm" onclick={() => askRestore(c)}>
									<RotateCcw size={14} /> Geri Yükle
								</Button>
							{:else if i === 0}
								<span class="text-[11px] text-gray-400">mevcut</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</ListPage>

<ConfirmDialog
	bind:show={showRestoreConfirm}
	danger
	title="Bu yedeğe geri dön"
	message={restoreTarget
		? `Kod, "${restoreTarget.subject}" (${restoreTarget.short}) durumuna döndürülecek. Mevcut durum önce otomatik yedeklenir (kayıp olmaz, geri alınabilir). Geri yükleme sonrası değişikliklerin çalışması için yeniden deploy (build + restart) gerekir. Devam edilsin mi?`
		: ''}
	confirmText="Evet, Geri Yükle"
	cancelText="Vazgeç"
	onConfirm={doRestore}
/>
