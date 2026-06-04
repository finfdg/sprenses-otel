<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import ListPage from '$lib/components/ListPage.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Button from '$lib/components/Button.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { UploadCloud, History, CheckCircle2, Clock, Cloud, RotateCcw } from 'lucide-svelte';

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

	const canUse = hasPermission('system.backup', 'use');

	let status = $state<Status | null>(null);
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

	async function load() {
		loading = true;
		try {
			status = await api.get<Status>('/system/backup/status');
		} catch (err) {
			console.error('Yedek durumu alınamadı:', err);
			showToast('Yedek durumu alınamadı', 'error');
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

	<!-- Yedek geçmişi (commit listesi) -->
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
