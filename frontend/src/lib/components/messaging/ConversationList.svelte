<script lang="ts">
	import type { ConversationItem } from '$lib/types/messaging';
	import { formatTime, getConvDisplayName, getConvInitial } from '$lib/types/messaging';
	import { onlinePresence } from '$lib/stores/websocket.svelte';
	import Input from '$lib/components/Input.svelte';
	import { Search } from 'lucide-svelte';

	let {
		conversations,
		selectedConvId = null,
		currentUserId,
		loading = false,
		searchQuery = $bindable(''),
		onSelectConversation,
		onNewChat,
		onDeleteConversation,
		onToggleMute,
	}: {
		conversations: ConversationItem[];
		selectedConvId?: number | null;
		currentUserId: number;
		loading?: boolean;
		searchQuery: string;
		onSelectConversation: (conv: ConversationItem) => void;
		onNewChat: () => void;
		onDeleteConversation: (conv: ConversationItem) => void;
		onToggleMute: (conv: ConversationItem) => void;
	} = $props();

	// Her zaman yeni array oluştur — $derived memoization'ı referans eşitliğiyle çalıştığından
	// aynı proxy referansını döndürmek deep property değişikliklerinin kaçırılmasına neden olabilir.
	let filteredConversations = $derived.by(() => {
		if (!searchQuery.trim()) return conversations.slice();
		const q = searchQuery.toLowerCase();
		return conversations.filter(c => getConvDisplayName(c).toLowerCase().includes(q));
	});

	// onlinePresence.version'ı okuyarak Svelte 5 reaktivitesini garanti altına al
	// (Set.has() fonksiyon çağrısı her zaman signal tracking tetiklemiyor)
	let _v = $derived(onlinePresence.version);
	function isOnline(userId: number): boolean {
		void _v; // version okunarak dependency tracking tetiklenir
		return onlinePresence.ids.has(userId);
	}

	// ─── Swipe-to-Delete (Mobil) ─────────────────────────────────────
	let swipedConvId = $state<number | null>(null);
	let touchStartX = 0;
	let touchStartY = 0;
	let touchCurrentX = 0;
	let isSwiping = false;

	function handleTouchStart(e: TouchEvent, conv: ConversationItem) {
		touchStartX = e.touches[0].clientX;
		touchStartY = e.touches[0].clientY;
		touchCurrentX = touchStartX;
		isSwiping = false;
	}

	function handleTouchMove(e: TouchEvent) {
		if (!touchStartX) return;
		touchCurrentX = e.touches[0].clientX;
		const deltaX = touchCurrentX - touchStartX;
		const deltaY = e.touches[0].clientY - touchStartY;
		// Yatay hareket dikeyden fazlaysa swipe olarak kabul et
		if (Math.abs(deltaX) > 10 && Math.abs(deltaX) > Math.abs(deltaY)) {
			isSwiping = true;
		}
	}

	function handleTouchEnd(e: TouchEvent, conv: ConversationItem) {
		const deltaX = e.changedTouches[0].clientX - touchStartX;
		const deltaY = e.changedTouches[0].clientY - touchStartY;

		if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 50) {
			if (deltaX < -50) {
				// Sola kaydır → sil butonunu göster
				swipedConvId = swipedConvId === conv.id ? null : conv.id;
			} else if (deltaX > 30 && swipedConvId === conv.id) {
				// Sağa kaydır → sil butonunu kapat
				swipedConvId = null;
			}
		}

		touchStartX = 0;
		touchStartY = 0;
		isSwiping = false;
	}

	function handleConvClick(conv: ConversationItem) {
		if (isSwiping) return;
		if (swipedConvId) { swipedConvId = null; return; }
		onSelectConversation(conv);
	}

	function handleDeleteClick(e: Event, conv: ConversationItem) {
		e.stopPropagation();
		swipedConvId = null;
		onDeleteConversation(conv);
	}

	function handleMuteClick(e: Event, conv: ConversationItem) {
		e.stopPropagation();
		swipedConvId = null;
		onToggleMute(conv);
	}
</script>

<div class="{selectedConvId ? 'hidden md:flex' : 'flex'} w-full md:w-80 border-r border-gray-200 flex-col shrink-0 bg-white">
	<div class="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
		<h2 class="text-lg font-bold text-gray-900">Mesajlar</h2>
		<button onclick={onNewChat} class="w-8 h-8 rounded-full bg-teal-700 text-white flex items-center justify-center hover:bg-teal-800 transition-colors cursor-pointer" title="Yeni Mesaj">
			<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" /></svg>
		</button>
	</div>

	<div class="px-3 py-2 border-b border-gray-100">
		<Input type="search" icon={Search} clearable size="sm" bind:value={searchQuery} placeholder="Konuşma ara..." />
	</div>

	<div class="flex-1 overflow-y-auto">
		{#if loading}
			<p class="text-gray-500 text-sm text-center py-8">Yükleniyor...</p>
		{:else if filteredConversations.length === 0}
			<div class="text-center py-8">
				<p class="text-gray-500 text-sm">{searchQuery ? 'Sonuç bulunamadı' : 'Henüz konuşma yok'}</p>
				{#if !searchQuery}<button onclick={onNewChat} class="text-teal-600 text-sm mt-2 hover:underline cursor-pointer">Yeni mesaj başlat</button>{/if}
			</div>
		{:else}
			{#each filteredConversations as conv (conv.id)}
				<div class="group/conv relative overflow-hidden border-b border-gray-50">
					<!-- Arka plan: Sessiz + Sil alanı — mobil swipe (sağ taraf) -->
					<div class="absolute inset-y-0 right-0 w-[120px] flex items-stretch transition-opacity md:hidden {swipedConvId === conv.id ? 'opacity-100' : 'opacity-0'}">
						<button
							onclick={(e) => handleMuteClick(e, conv)}
							class="w-[60px] flex items-center justify-center cursor-pointer bg-gray-500"
							title={conv.is_muted ? 'Sesi aç' : 'Sessize al'}
						>
							{#if conv.is_muted}
								<svg class="w-5 h-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" /></svg>
							{:else}
								<svg class="w-5 h-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" /></svg>
							{/if}
						</button>
						<button
							onclick={(e) => handleDeleteClick(e, conv)}
							class="w-[60px] flex items-center justify-center cursor-pointer bg-red-500"
							title="Sil"
						>
							<svg class="w-5 h-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
							</svg>
						</button>
					</div>

					<!-- Konuşma içeriği -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="relative bg-white transition-transform duration-200 ease-out md:translate-x-0 {swipedConvId === conv.id ? '-translate-x-[120px]' : 'translate-x-0'}"
						ontouchstart={(e) => handleTouchStart(e, conv)}
						ontouchmove={(e) => handleTouchMove(e)}
						ontouchend={(e) => handleTouchEnd(e, conv)}
					>
						<button
							onclick={() => handleConvClick(conv)}
							class="w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-50 transition-colors cursor-pointer {selectedConvId === conv.id ? 'bg-teal-50' : ''}"
						>
							<div class="relative shrink-0">
								<div class="w-10 h-10 rounded-full {conv.type === 'group' ? 'bg-indigo-100' : 'bg-teal-100'} flex items-center justify-center">
									<span class="text-sm font-semibold {conv.type === 'group' ? 'text-indigo-700' : 'text-teal-700'}">{getConvInitial(conv)}</span>
								</div>
								{#if conv.type === 'private' && conv.other_user && isOnline(conv.other_user.id)}
									<div class="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 bg-green-500 rounded-full border-2 border-white"></div>
								{/if}
							</div>
							<div class="flex-1 min-w-0 text-left">
								<div class="flex items-center justify-between">
									<span class="text-sm font-semibold text-gray-900 truncate">{getConvDisplayName(conv)}</span>
									<span class="flex items-center gap-1 shrink-0 ml-2">
										{#if conv.is_muted}
											<svg class="w-3.5 h-3.5 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" /></svg>
										{/if}
										{#if conv.last_message}<span class="text-xs text-gray-500">{formatTime(conv.last_message.created_at)}</span>{/if}
									</span>
								</div>
								<div class="flex items-center justify-between gap-2 mt-0.5">
									<p class="text-xs text-gray-500 truncate min-w-0 flex-1">
										{#if conv.last_message}
											{#if conv.last_message.is_deleted}<span class="italic">Bu mesaj silindi</span>
											{:else if conv.last_message.message_type === 'system'}<span class="italic">{conv.last_message.content}</span>
											{:else if conv.last_message.message_type === 'image'}{conv.last_message.sender_id === currentUserId ? 'Siz: ' : (conv.type === 'group' && conv.last_message.sender_name ? conv.last_message.sender_name + ': ' : '')}📷 Fotoğraf
											{:else if conv.last_message.message_type === 'video'}{conv.last_message.sender_id === currentUserId ? 'Siz: ' : (conv.type === 'group' && conv.last_message.sender_name ? conv.last_message.sender_name + ': ' : '')}🎬 Video
											{:else if conv.last_message.message_type === 'file'}{conv.last_message.sender_id === currentUserId ? 'Siz: ' : (conv.type === 'group' && conv.last_message.sender_name ? conv.last_message.sender_name + ': ' : '')}📎 Dosya
											{:else}{conv.last_message.sender_id === currentUserId ? 'Siz: ' : (conv.type === 'group' && conv.last_message.sender_name ? conv.last_message.sender_name + ': ' : '')}{conv.last_message.content}{/if}
										{:else}Henüz mesaj yok{/if}
									</p>
									{#if conv.unread_count > 0}<span class="w-5 h-5 rounded-full bg-teal-500 text-white text-[10px] flex items-center justify-center font-bold shrink-0 ml-2">{conv.unread_count > 9 ? '9+' : conv.unread_count}</span>{/if}
								</div>
							</div>
						</button>
					</div>

					<!-- Masaüstü: Hover'da sessiz + silme butonları -->
					<div class="hidden md:group-hover/conv:flex items-center gap-1 absolute right-2 top-1/2 -translate-y-1/2 z-10">
						<button
							onclick={(e) => handleMuteClick(e, conv)}
							class="flex items-center justify-center w-8 h-8 rounded-full bg-gray-100 text-gray-500 hover:bg-gray-500 hover:text-white transition-all cursor-pointer"
							title={conv.is_muted ? 'Sesi aç' : 'Sessize al'}
						>
							{#if conv.is_muted}
								<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" /></svg>
							{:else}
								<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" /></svg>
							{/if}
						</button>
						<button
							onclick={(e) => handleDeleteClick(e, conv)}
							class="flex items-center justify-center w-8 h-8 rounded-full bg-red-50 text-red-400 hover:bg-red-500 hover:text-white transition-all cursor-pointer"
							title="Konuşmayı sil"
						>
							<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
							</svg>
						</button>
					</div>
				</div>
			{/each}
		{/if}
	</div>
</div>
