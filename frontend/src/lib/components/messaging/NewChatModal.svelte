<script lang="ts">
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { focusTrap } from '$lib/utils/focus-trap';
	import type { ChatUser } from '$lib/types/messaging';

	let {
		show = $bindable(false),
		onStartChat,
		onOpenGroup,
	}: {
		show: boolean;
		onStartChat: (user: ChatUser) => void;
		onOpenGroup: () => void;
	} = $props();

	let chatUsers = $state<ChatUser[]>([]);
	let userSearchQuery = $state('');
	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	$effect(() => {
		if (show) {
			userSearchQuery = '';
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
			chatUsers = await api.get<ChatUser[]>(`/messages/users?search=${encodeURIComponent(userSearchQuery)}`);
		} catch (err) {
			console.error('Kullanıcı araması başarısız:', err);
			showToast('Kullanıcı araması başarısız', 'error');
		}
	}

	function handleSearchInput() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			if (userSearchQuery.trim()) searchUsers();
			else loadUsers();
		}, 300);
	}
</script>

{#if show}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4" onclick={() => show = false} onkeydown={(e) => { if (e.key === 'Escape') show = false; }} role="dialog" aria-modal="true" aria-label="Yeni Mesaj" tabindex="-1" use:focusTrap>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="bg-white rounded-2xl w-full max-w-sm shadow-xl overflow-hidden" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
				<h3 class="text-lg font-bold text-gray-900">Yeni Mesaj</h3>
				<button onclick={() => { show = false; onOpenGroup(); }} class="text-sm text-teal-600 font-medium hover:underline cursor-pointer">Grup Oluştur</button>
			</div>

			<div class="px-4 py-3 border-b border-gray-100">
				<input
					type="text"
					bind:value={userSearchQuery}
					oninput={handleSearchInput}
					placeholder="Kullanıcı ara..."
					class="w-full px-3 py-2 bg-gray-100 rounded-lg text-base md:text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-2 focus:ring-teal-100 transition-all"
				/>
			</div>

			<div class="max-h-64 overflow-y-auto">
				{#if chatUsers.length === 0}
					<p class="text-gray-500 text-sm text-center py-6">Kullanıcı bulunamadı</p>
				{:else}
					{#each chatUsers as cu}
						<button onclick={() => { show = false; onStartChat(cu); }} class="w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-50 transition-colors cursor-pointer border-b border-gray-50">
							<div class="w-9 h-9 rounded-full bg-teal-100 flex items-center justify-center shrink-0">
								<span class="text-sm font-semibold text-teal-700">{cu.first_name?.charAt(0)?.toUpperCase() || '?'}</span>
							</div>
							<div class="text-left min-w-0">
								<p class="text-sm font-semibold text-gray-900 truncate">{cu.first_name} {cu.last_name}</p>
								<p class="text-xs text-gray-500 truncate">@{cu.username}{cu.role_name ? ` · ${cu.role_name}` : ''}</p>
							</div>
						</button>
					{/each}
				{/if}
			</div>

			<div class="px-4 py-3 border-t border-gray-100">
				<button onclick={() => show = false} class="w-full py-2.5 text-sm text-gray-500 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer">İptal</button>
			</div>
		</div>
	</div>
{/if}
