<script lang="ts">
	import { api } from '$lib/api';
	import { onMount } from 'svelte';
	import ListPage from '$lib/components/ListPage.svelte';
	import { ClipboardList } from 'lucide-svelte';

	interface AuditLog {
		id: number;
		user_id: number | null;
		username: string | null;
		user_full_name: string | null;
		action: string;
		entity_type: string;
		entity_id: number | null;
		details: string | null;
		ip_address: string | null;
		created_at: string;
	}

	let logs = $state<AuditLog[]>([]);
	let loading = $state(false);
	let page = $state(1);
	let total = $state(0);
	let pages = $state(1);
	const pageSize = 50;

	// Filtreler
	let filterAction = $state('');
	let filterEntity = $state('');
	let filterUserId = $state('');

	// Detay modalı
	let selectedLog = $state<AuditLog | null>(null);

	const ACTION_LABELS: Record<string, string> = {
		login: 'Giriş',
		login_failed: 'Başarısız Giriş',
		logout: 'Çıkış',
		register: 'Kayıt',
		create: 'Oluşturma',
		update: 'Güncelleme',
		delete: 'Silme',
		change_password: 'Şifre Değiştirme',
		reset_password: 'Şifre Sıfırlama',
		session_invalidated: 'Oturum Sonlandırma',
	};

	const ACTION_COLORS: Record<string, string> = {
		login: 'bg-green-50 text-green-700 border-green-200',
		login_failed: 'bg-red-50 text-red-700 border-red-200',
		create: 'bg-blue-50 text-blue-700 border-blue-200',
		update: 'bg-amber-50 text-amber-700 border-amber-200',
		delete: 'bg-red-50 text-red-700 border-red-200',
		change_password: 'bg-purple-50 text-purple-700 border-purple-200',
		reset_password: 'bg-purple-50 text-purple-700 border-purple-200',
		session_invalidated: 'bg-gray-50 text-gray-700 border-gray-200',
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
			let url = `/system/audit-logs/?page=${page}&page_size=${pageSize}`;
			if (filterAction) url += `&action=${filterAction}`;
			if (filterEntity) url += `&entity_type=${filterEntity}`;
			if (filterUserId) url += `&user_id=${filterUserId}`;
			const res = await api.get<{ items: AuditLog[]; total: number; pages: number }>(url);
			logs = res.items;
			total = res.total;
			pages = res.pages;
		} catch (err) {
			console.error('Audit logları yüklenemedi:', err);
		} finally {
			loading = false;
		}
	}

	function applyFilter() {
		page = 1;
		loadLogs();
	}

	function resetFilters() {
		filterAction = '';
		filterEntity = '';
		filterUserId = '';
		page = 1;
		loadLogs();
	}

	onMount(() => { loadLogs(); });
</script>

<ListPage
	title="Audit Logları"
	description={`Sistem etkinlik kayıtları — ${total} kayıt`}
	{loading}
	isEmpty={logs.length === 0}
	emptyIcon={ClipboardList}
	emptyTitle="Kayıt bulunamadı"
	{page}
	{pages}
	{total}
	{pageSize}
	skeletonColumns={6}
	onPageChange={(p: number) => { page = p; loadLogs(); }}
>
	{#snippet filters()}
		<div class="flex-1 min-w-[120px]">
			<label for="au-action" class="block text-xs font-medium text-gray-500 mb-1">Eylem</label>
			<select id="au-action" bind:value={filterAction} onchange={applyFilter} class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white">
				<option value="">Tümü</option>
				{#each Object.entries(ACTION_LABELS) as [key, label]}
					<option value={key}>{label}</option>
				{/each}
			</select>
		</div>
		<div class="flex-1 min-w-[120px]">
			<label for="au-entity" class="block text-xs font-medium text-gray-500 mb-1">Varlık Tipi</label>
			<select id="au-entity" bind:value={filterEntity} onchange={applyFilter} class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white">
				<option value="">Tümü</option>
				<option value="auth">Kimlik Doğrulama</option>
				<option value="user">Kullanıcı</option>
				<option value="role">Rol</option>
				<option value="module">Modül</option>
				<option value="conversation">Konuşma</option>
				<option value="message">Mesaj</option>
				<option value="cash_flow">Nakit Akım</option>
				<option value="credit_product">Kredi</option>
				<option value="vendor">Cari</option>
				<option value="department">Departman</option>
				<option value="budget">Bütçe</option>
			</select>
		</div>
		<button
			onclick={resetFilters}
			class="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"
		>
			Temizle
		</button>
	{/snippet}

	<!-- Masaüstü Tablo -->
	<div class="hidden sm:block overflow-x-auto">
		<table class="w-full text-sm">
			<thead class="bg-gray-50 border-b border-gray-200">
				<tr>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Tarih</th>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Kullanıcı</th>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Eylem</th>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Varlık</th>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">Detay</th>
					<th class="px-4 py-3 text-left font-medium text-gray-500 text-xs">IP</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100">
				{#each logs as log}
					<tr
						class="hover:bg-gray-50 cursor-pointer transition-colors"
						onclick={() => selectedLog = log}
					>
						<td class="px-4 py-3 text-gray-600 whitespace-nowrap text-xs">
							<span title={formatDate(log.created_at)}>{formatRelative(log.created_at)}</span>
						</td>
						<td class="px-4 py-3">
							{#if log.user_full_name}
								<span class="font-medium text-gray-800">{log.user_full_name}</span>
							{:else}
								<span class="text-gray-500">Sistem</span>
							{/if}
						</td>
						<td class="px-4 py-3">
							<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border {ACTION_COLORS[log.action] || 'bg-gray-50 text-gray-600 border-gray-200'}">
								{ACTION_LABELS[log.action] || log.action}
							</span>
						</td>
						<td class="px-4 py-3 text-gray-600">
							<span class="text-xs">{log.entity_type}</span>
							{#if log.entity_id}
								<span class="text-gray-500 text-xs ml-1">#{log.entity_id}</span>
							{/if}
						</td>
						<td class="px-4 py-3 text-gray-500 text-xs max-w-[300px] truncate">{log.details || '-'}</td>
						<td class="px-4 py-3 text-gray-500 text-xs font-mono">{log.ip_address || '-'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Mobil Kart -->
	<div class="sm:hidden divide-y divide-gray-100">
		{#each logs as log}
			<button
				class="w-full text-left p-3 hover:bg-gray-50 transition-colors cursor-pointer"
				onclick={() => selectedLog = log}
			>
				<div class="flex items-center justify-between mb-1.5">
					<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border {ACTION_COLORS[log.action] || 'bg-gray-50 text-gray-600 border-gray-200'}">
						{ACTION_LABELS[log.action] || log.action}
					</span>
					<span class="text-[10px] text-gray-500">{formatRelative(log.created_at)}</span>
				</div>
				<div class="flex items-center gap-2">
					<span class="text-xs font-medium text-gray-800">{log.user_full_name || 'Sistem'}</span>
					<span class="text-[10px] text-gray-500">{log.entity_type}{log.entity_id ? ` #${log.entity_id}` : ''}</span>
				</div>
				{#if log.details}
					<p class="text-[11px] text-gray-500 mt-1 truncate">{log.details}</p>
				{/if}
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
			class="bg-white rounded-2xl shadow-xl max-w-lg w-full max-h-[80vh] overflow-y-auto"
			onclick={(e) => e.stopPropagation()}
			role="document"
		>
			<div class="p-5 border-b border-gray-100 flex items-center justify-between">
				<h3 class="text-lg font-bold text-gray-800">Log Detayı</h3>
				<button onclick={() => selectedLog = null} class="p-1 text-gray-500 hover:text-gray-600 cursor-pointer" aria-label="Detayı kapat">
					<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
				</button>
			</div>
			<div class="p-5 space-y-3">
				<div class="grid grid-cols-2 gap-3">
					<div>
						<span class="text-xs text-gray-500 block">Tarih</span>
						<span class="text-sm font-medium text-gray-800">{formatDate(selectedLog.created_at)}</span>
					</div>
					<div>
						<span class="text-xs text-gray-500 block">Kullanıcı</span>
						<span class="text-sm font-medium text-gray-800">{selectedLog.user_full_name || 'Sistem'}</span>
					</div>
					<div>
						<span class="text-xs text-gray-500 block">Eylem</span>
						<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border {ACTION_COLORS[selectedLog.action] || 'bg-gray-50 text-gray-600 border-gray-200'}">
							{ACTION_LABELS[selectedLog.action] || selectedLog.action}
						</span>
					</div>
					<div>
						<span class="text-xs text-gray-500 block">Varlık</span>
						<span class="text-sm text-gray-800">{selectedLog.entity_type}{selectedLog.entity_id ? ` #${selectedLog.entity_id}` : ''}</span>
					</div>
					<div>
						<span class="text-xs text-gray-500 block">IP Adresi</span>
						<span class="text-sm font-mono text-gray-600">{selectedLog.ip_address || '-'}</span>
					</div>
				</div>
				{#if selectedLog.details}
					<div>
						<span class="text-xs text-gray-500 block mb-1">Detay</span>
						<div class="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 whitespace-pre-wrap break-words font-mono text-xs">{selectedLog.details}</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
