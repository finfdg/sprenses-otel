<script lang="ts">
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import ListPage from '$lib/components/ListPage.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import { onMount } from 'svelte';
	import { CheckCircle2 } from 'lucide-svelte';

	interface ErrorLog {
		id: number;
		level: string;
		source: string;
		message: string;
		traceback: string | null;
		method: string | null;
		path: string | null;
		user_id: number | null;
		ip_address: string | null;
		created_at: string;
	}

	let logs = $state<ErrorLog[]>([]);
	let loading = $state(false);
	let page = $state(1);
	let total = $state(0);
	let pages = $state(1);
	const pageSize = 50;

	let filterLevel = $state('');
	let filterSearch = $state('');

	let selectedLog = $state<ErrorLog | null>(null);
	let showClearConfirm = $state(false);

	const canUse = hasPermission('system.error_logs', 'use');

	const LEVEL_COLORS: Record<string, string> = {
		ERROR: 'bg-red-50 text-red-700 border-red-200',
		CRITICAL: 'bg-red-100 text-red-800 border-red-300',
		WARNING: 'bg-amber-50 text-amber-700 border-amber-200',
	};

	function formatDate(dateStr: string): string {
		const d = new Date(dateStr);
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	function formatRelative(dateStr: string): string {
		const d = new Date(dateStr);
		const now = new Date();
		const diff = Math.floor((now.getTime() - d.getTime()) / 1000);
		if (diff < 60) return `${diff} sn önce`;
		if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
		if (diff < 86400) return `${Math.floor(diff / 3600)} saat önce`;
		if (diff < 604800) return `${Math.floor(diff / 86400)} gün önce`;
		return formatDate(dateStr);
	}

	async function loadLogs() {
		loading = true;
		try {
			let url = `/system/error-logs/?page=${page}&page_size=${pageSize}`;
			if (filterLevel) url += `&level=${filterLevel}`;
			if (filterSearch) url += `&search=${encodeURIComponent(filterSearch)}`;
			const res = await api.get<{ items: ErrorLog[]; total: number; pages: number }>(url);
			logs = res.items;
			total = res.total;
			pages = res.pages;
		} catch (err) {
			console.error('Hata logları yüklenemedi:', err);
		} finally {
			loading = false;
		}
	}

	async function deleteLog(id: number) {
		try {
			await api.delete('/system/error-logs/' + id);
			logs = logs.filter(l => l.id !== id);
			total--;
			selectedLog = null;
			showToast('Hata kaydı silindi', 'success');
		} catch (err) {
			console.error('Silme hatası:', err);
			showToast('Silinemedi', 'error');
		}
	}

	async function clearAll() {
		try {
			const res = await api.delete<{ deleted: number }>('/system/error-logs/');
			showClearConfirm = false;
			showToast(`${res.deleted} hata kaydı temizlendi`, 'success');
			page = 1;
			loadLogs();
		} catch (err) {
			console.error('Temizleme hatası:', err);
			showToast('Temizlenemedi', 'error');
		}
	}

	function applyFilter() {
		page = 1;
		loadLogs();
	}

	onMount(() => { loadLogs(); });
</script>

<ListPage
	title="Hata Logları"
	description={`Sunucu hata kayıtları — ${total} kayıt`}
	{loading}
	isEmpty={logs.length === 0}
	emptyIcon={CheckCircle2}
	emptyTitle="Hata kaydı bulunmuyor"
	emptyMessage="Sistem sorunsuz çalışıyor"
	bind:search={filterSearch}
	searchPlaceholder="Hata mesajında ara..."
	onSearch={() => applyFilter()}
	{page}
	{pages}
	{total}
	{pageSize}
	skeletonRows={5}
	onPageChange={(p: number) => { page = p; loadLogs(); }}
>
	{#snippet actions()}
		{#if canUse && total > 0}
			<button
				onclick={() => showClearConfirm = true}
				class="px-3 py-2 text-xs sm:text-sm font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors cursor-pointer"
			>
				Tümünü Temizle
			</button>
		{/if}
	{/snippet}

	{#snippet filters()}
		<div class="min-w-[120px]">
			<label for="hl-level" class="block text-xs font-medium text-gray-500 mb-1">Seviye</label>
			<select id="hl-level" bind:value={filterLevel} onchange={applyFilter} class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white">
				<option value="">Tümü</option>
				<option value="ERROR">ERROR</option>
				<option value="CRITICAL">CRITICAL</option>
				<option value="WARNING">WARNING</option>
			</select>
		</div>
	{/snippet}

	<div class="divide-y divide-gray-100">
		{#each logs as log}
			<button
				class="w-full text-left p-3 sm:p-4 hover:bg-red-50/30 transition-colors cursor-pointer"
				onclick={() => selectedLog = log}
			>
				<div class="flex items-start justify-between gap-3">
					<div class="flex-1 min-w-0">
						<div class="flex items-center gap-2 mb-1">
							<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold border {LEVEL_COLORS[log.level] || 'bg-gray-50 text-gray-600 border-gray-200'}">
								{log.level}
							</span>
							{#if log.method && log.path}
								<span class="text-[10px] font-mono text-gray-500">{log.method} {log.path}</span>
							{/if}
							<span class="text-[10px] text-gray-500 ml-auto shrink-0" title={formatDate(log.created_at)}>{formatRelative(log.created_at)}</span>
						</div>
						<p class="text-sm text-gray-800 font-medium truncate">{log.message}</p>
						<p class="text-xs text-gray-500 mt-0.5">{log.source}</p>
					</div>
				</div>
			</button>
		{/each}
	</div>
</ListPage>

<!-- Detay Modalı -->
{#if selectedLog}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
		onclick={() => selectedLog = null}
		onkeydown={(e) => { if (e.key === 'Escape') selectedLog = null; }}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions a11y_no_noninteractive_element_interactions -->
		<div
			class="bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[85vh] overflow-y-auto"
			onclick={(e) => e.stopPropagation()}
			role="document"
		>
			<div class="p-5 border-b border-gray-100 flex items-center justify-between">
				<div class="flex items-center gap-2">
					<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border {LEVEL_COLORS[selectedLog.level] || 'bg-gray-50 text-gray-600 border-gray-200'}">
						{selectedLog.level}
					</span>
					<h3 class="text-lg font-bold text-gray-800">Hata Detayı</h3>
				</div>
				<div class="flex items-center gap-2">
					{#if canUse}
						<button
							onclick={() => deleteLog(selectedLog!.id)}
							class="px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors cursor-pointer"
						>Sil</button>
					{/if}
					<button onclick={() => selectedLog = null} class="p-1 text-gray-500 hover:text-gray-600 cursor-pointer" aria-label="Detayı kapat">
						<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
					</button>
				</div>
			</div>
			<div class="p-5 space-y-4">
				<div class="grid grid-cols-2 gap-3">
					<div>
						<span class="text-xs text-gray-500 block">Tarih</span>
						<span class="text-sm font-medium text-gray-800">{formatDate(selectedLog.created_at)}</span>
					</div>
					<div>
						<span class="text-xs text-gray-500 block">Kaynak</span>
						<span class="text-sm font-mono text-gray-700">{selectedLog.source}</span>
					</div>
					{#if selectedLog.method && selectedLog.path}
						<div class="col-span-2">
							<span class="text-xs text-gray-500 block">İstek</span>
							<span class="text-sm font-mono text-gray-700">{selectedLog.method} {selectedLog.path}</span>
						</div>
					{/if}
					{#if selectedLog.ip_address}
						<div>
							<span class="text-xs text-gray-500 block">IP Adresi</span>
							<span class="text-sm font-mono text-gray-600">{selectedLog.ip_address}</span>
						</div>
					{/if}
				</div>

				<div>
					<span class="text-xs text-gray-500 block mb-1">Hata Mesajı</span>
					<div class="bg-red-50 rounded-lg p-3 text-sm text-red-800 font-mono break-words">{selectedLog.message}</div>
				</div>

				{#if selectedLog.traceback}
					<div>
						<span class="text-xs text-gray-500 block mb-1">Traceback</span>
						<pre class="bg-gray-900 text-green-400 rounded-lg p-4 text-xs font-mono overflow-x-auto whitespace-pre-wrap break-words max-h-[300px] overflow-y-auto">{selectedLog.traceback}</pre>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- Temizleme Onayı -->
<Modal bind:show={showClearConfirm} title="Tüm Hata Loglarını Temizle" maxWidth="max-w-sm">
	<div class="space-y-4">
		<p class="text-sm text-gray-600">Tüm hata kayıtları kalıcı olarak silinecektir. Bu işlem geri alınamaz.</p>
		<div class="flex items-center justify-end gap-3">
			<button
				onclick={() => showClearConfirm = false}
				class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 cursor-pointer"
			>İptal</button>
			<button
				onclick={clearAll}
				class="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 cursor-pointer"
			>Tümünü Sil</button>
		</div>
	</div>
</Modal>
