<script lang="ts">
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { focusTrap } from '$lib/utils/focus-trap';
	import type { ChatUser, GroupMember } from '$lib/types/messaging';

	let {
		show = $bindable(false),
		conversationId,
		existingMembers = [],
		onMembersAdded,
	}: {
		show: boolean;
		conversationId: number;
		existingMembers: GroupMember[];
		onMembersAdded: () => void;
	} = $props();

	let availableUsers = $state<ChatUser[]>([]);
	let selectedIds = $state<Set<number>>(new Set());
	let searchQuery = $state('');
	let loading = $state(false);
	let adding = $state(false);

	$effect(() => {
		if (show) {
			selectedIds = new Set();
			searchQuery = '';
			loadAvailableUsers();
		}
	});

	async function loadAvailableUsers() {
		loading = true;
		try {
			const allUsers = await api.get<ChatUser[]>('/messages/users');
			const existingIds = new Set(existingMembers.map(m => m.id));
			availableUsers = allUsers.filter(u => !existingIds.has(u.id));
		} catch (err) {
			console.error('Kullanıcı listesi alınamadı:', err);
			showToast('Kullanıcı listesi alınamadı', 'error');
		}
		loading = false;
	}

	async function searchUsers() {
		try {
			const allUsers = await api.get<ChatUser[]>(`/messages/users?search=${encodeURIComponent(searchQuery)}`);
			const existingIds = new Set(existingMembers.map(m => m.id));
			availableUsers = allUsers.filter(u => !existingIds.has(u.id));
		} catch (err) {
			console.error('Kullanıcı araması başarısız:', err);
			showToast('Kullanıcı araması başarısız', 'error');
		}
	}

	function toggleUser(userId: number) {
		const next = new Set(selectedIds);
		if (next.has(userId)) next.delete(userId); else next.add(userId);
		selectedIds = next;
	}

	async function addMembers() {
		if (selectedIds.size === 0 || adding) return;
		adding = true;
		try {
			await api.post(`/messages/conversations/${conversationId}/members`, {
				user_ids: Array.from(selectedIds),
			});
			show = false;
			onMembersAdded();
		} catch (err) {
			console.error('Üye eklenemedi:', err);
			showToast(err instanceof Error ? err.message : 'Üye eklenirken bir hata oluştu', 'error');
		}
		adding = false;
	}

	let searchTimeout: ReturnType<typeof setTimeout> | null = null;
	function handleSearchInput() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			if (searchQuery.trim()) searchUsers();
			else loadAvailableUsers();
		}, 300);
	}
</script>

{#if show}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4" onclick={() => show = false} onkeydown={(e) => { if (e.key === 'Escape') show = false; }} role="dialog" aria-modal="true" aria-label="Üye Ekle" tabindex="-1" use:focusTrap>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="bg-white rounded-2xl w-full max-w-sm shadow-xl overflow-hidden" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<div class="px-5 py-4 border-b border-gray-200">
				<h3 class="text-lg font-bold text-gray-900">Üye Ekle</h3>
			</div>

			<div class="px-4 py-3 border-b border-gray-100">
				<input
					type="text"
					bind:value={searchQuery}
					oninput={handleSearchInput}
					placeholder="Kullanıcı ara..."
					class="w-full px-3 py-2 bg-gray-100 rounded-lg text-base md:text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-2 focus:ring-teal-100 transition-all"
				/>
			</div>

			{#if selectedIds.size > 0}
				<div class="px-4 py-2 border-b border-gray-100">
					<span class="text-xs text-teal-600 font-medium">{selectedIds.size} kullanıcı seçildi</span>
				</div>
			{/if}

			<div class="max-h-64 overflow-y-auto">
				{#if loading}
					<p class="text-gray-500 text-sm text-center py-6">Yükleniyor...</p>
				{:else if availableUsers.length === 0}
					<p class="text-gray-500 text-sm text-center py-6">Eklenecek kullanıcı bulunamadı</p>
				{:else}
					{#each availableUsers as u}
						<button
							onclick={() => toggleUser(u.id)}
							class="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-gray-50 transition-colors cursor-pointer border-b border-gray-50"
						>
							<div class="w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 {selectedIds.has(u.id) ? 'border-teal-500 bg-teal-500' : 'border-gray-300'}">
								{#if selectedIds.has(u.id)}
									<svg class="w-3 h-3 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
										<path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
									</svg>
								{/if}
							</div>
							<div class="w-8 h-8 rounded-full bg-teal-100 flex items-center justify-center shrink-0">
								<span class="text-xs font-semibold text-teal-700">{u.first_name?.charAt(0)?.toUpperCase() || '?'}</span>
							</div>
							<div class="text-left min-w-0">
								<p class="text-sm text-gray-900 truncate">{u.first_name} {u.last_name}</p>
								<p class="text-xs text-gray-500 truncate">@{u.username}{u.role_name ? ` · ${u.role_name}` : ''}</p>
							</div>
						</button>
					{/each}
				{/if}
			</div>

			<div class="px-4 py-3 border-t border-gray-100 flex gap-2">
				<button onclick={() => show = false} class="flex-1 py-2.5 text-sm text-gray-500 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer">
					İptal
				</button>
				<button
					onclick={addMembers}
					disabled={selectedIds.size === 0 || adding}
					class="flex-1 py-2.5 text-sm text-white bg-teal-700 rounded-lg hover:bg-teal-800 transition-colors cursor-pointer disabled:opacity-40 font-medium"
				>
					{#if adding}Ekleniyor...{:else}Ekle ({selectedIds.size}){/if}
				</button>
			</div>
		</div>
	</div>
{/if}
