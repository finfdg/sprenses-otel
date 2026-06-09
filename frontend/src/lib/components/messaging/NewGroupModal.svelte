<script lang="ts">
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { focusTrap } from '$lib/utils/focus-trap';
	import type { ChatUser, ConversationDetail } from '$lib/types/messaging';

	let {
		show = $bindable(false),
		onGroupCreated,
	}: {
		show: boolean;
		onGroupCreated: (detail: ConversationDetail) => void;
	} = $props();

	let chatUsers = $state<ChatUser[]>([]);
	let newGroupName = $state('');
	let selectedMembers = $state<Set<number>>(new Set());
	let groupUserSearch = $state('');

	$effect(() => {
		if (show) {
			newGroupName = '';
			selectedMembers = new Set();
			groupUserSearch = '';
			loadUsers();
		}
	});

	async function loadUsers() {
		try {
			chatUsers = await api.get<ChatUser[]>('/messages/users');
		} catch (err) {
			console.error('Kullanıcı listesi alınamadı:', err);
			showToast('Kullanıcı listesi alınamadı', 'error');
		}
	}

	async function searchUsers() {
		try {
			chatUsers = await api.get<ChatUser[]>(`/messages/users?search=${encodeURIComponent(groupUserSearch)}`);
		} catch (err) {
			console.error('Kullanıcı araması başarısız:', err);
			showToast('Kullanıcı araması başarısız', 'error');
		}
	}

	let searchTimeout: ReturnType<typeof setTimeout> | null = null;
	function handleSearchInput() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			if (groupUserSearch.trim()) searchUsers();
			else loadUsers();
		}, 300);
	}

	function toggleMember(userId: number) {
		const next = new Set(selectedMembers);
		if (next.has(userId)) next.delete(userId); else next.add(userId);
		selectedMembers = next;
	}

	async function createGroup() {
		if (!newGroupName.trim() || selectedMembers.size === 0) return;
		try {
			const detail = await api.post<ConversationDetail>('/messages/conversations/group', {
				name: newGroupName.trim(),
				member_ids: Array.from(selectedMembers),
			});
			show = false;
			onGroupCreated(detail);
		} catch (err) {
			console.error('Grup oluşturulamadı:', err);
			showToast('Grup oluşturulurken bir hata oluştu', 'error');
		}
	}
</script>

{#if show}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4" onclick={() => show = false} onkeydown={(e) => { if (e.key === 'Escape') show = false; }} role="dialog" aria-modal="true" aria-label="Yeni Grup" tabindex="-1" use:focusTrap>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="bg-white rounded-2xl w-full max-w-sm shadow-xl overflow-hidden" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<div class="px-5 py-4 border-b border-gray-200">
				<h3 class="text-lg font-bold text-gray-900">Yeni Grup</h3>
			</div>

			<div class="px-4 py-3 border-b border-gray-100">
				<input
					type="text"
					bind:value={newGroupName}
					placeholder="Grup adı..."
					class="w-full px-3 py-2 bg-gray-100 rounded-lg text-base md:text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-2 focus:ring-teal-100 transition-all"
				/>
			</div>

			<div class="px-4 py-2 border-b border-gray-100">
				<input
					type="text"
					bind:value={groupUserSearch}
					oninput={handleSearchInput}
					placeholder="Üye ara..."
					class="w-full px-3 py-2 bg-gray-100 rounded-lg text-base md:text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-2 focus:ring-teal-100 transition-all"
				/>
			</div>

			{#if selectedMembers.size > 0}
				<div class="px-4 py-2 border-b border-gray-100">
					<span class="text-xs text-teal-600 font-medium">{selectedMembers.size} üye seçildi</span>
				</div>
			{/if}

			<div class="max-h-48 overflow-y-auto">
				{#each chatUsers as cu}
					<button onclick={() => toggleMember(cu.id)} class="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-gray-50 transition-colors cursor-pointer border-b border-gray-50">
						<div class="w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 {selectedMembers.has(cu.id) ? 'border-teal-500 bg-teal-500' : 'border-gray-300'}">
							{#if selectedMembers.has(cu.id)}
								<svg class="w-3 h-3 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
							{/if}
						</div>
						<div class="text-left min-w-0">
							<p class="text-sm text-gray-900 truncate">{cu.first_name} {cu.last_name}</p>
							<p class="text-xs text-gray-500 truncate">@{cu.username}</p>
						</div>
					</button>
				{/each}
			</div>

			<div class="px-4 py-3 border-t border-gray-100 flex gap-2">
				<button onclick={() => show = false} class="flex-1 py-2.5 text-sm text-gray-500 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer">İptal</button>
				<button onclick={createGroup} disabled={!newGroupName.trim() || selectedMembers.size === 0} class="flex-1 py-2.5 text-sm text-white bg-teal-700 rounded-lg hover:bg-teal-800 transition-colors cursor-pointer disabled:opacity-40 font-medium">Oluştur</button>
			</div>
		</div>
	</div>
{/if}
