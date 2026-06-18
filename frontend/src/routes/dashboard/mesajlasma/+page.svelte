<script lang="ts">
	import { onMount } from 'svelte';
	import { authState } from '$lib/stores/auth.svelte';
	import { onWsEvent, resetReconnect, onlinePresence, wsState } from '$lib/stores/websocket.svelte';
	import { createTypingManager, createDraftManager } from '$lib/utils/messaging-helpers.svelte';
	import {
		msg, syncData, loadConversationsImmediate, selectConversation,
		deselectConversation, refreshConversationDetail, handleMessagesScroll,
		scrollToBottom, setDraftManager, resolveConfirm, resetState,
	} from '$lib/stores/messaging.svelte';
	import {
		handleWsNewMessage, handleWsMessageEdited, handleWsMessageDeleted,
		handleWsReadStatus, handleWsTyping, handleWsNewConversation,
		handleWsGroupUpdate, handleWsGroupMemberRemoved, handleWsGroupNameChanged,
		handleWsUserStatus, handleWsConnected, cleanupWsHandlers,
	} from '$lib/utils/messaging-ws-handlers.svelte';
	import {
		sendMessage, handleSendFile, startEdit, cancelEdit, saveEdit,
		deleteMessage, isMessageRead,
	} from '$lib/utils/messaging-messages.svelte';
	import {
		handleTouchStart, handleTouchEnd, toggleActionMenu, closeMenus,
		handleMessageSearchInput, scrollToMessage, toggleMessageSearch,
		handleStartChat, handleGroupCreated, handleGroupNameUpdated,
		toggleMute, deleteConversation, cleanupUiHandlers,
	} from '$lib/utils/messaging-ui.svelte';
	import { focusTrap } from '$lib/utils/focus-trap';

	// Bileşenler
	import ConversationList from '$lib/components/messaging/ConversationList.svelte';
	import ChatHeader from '$lib/components/messaging/ChatHeader.svelte';
	import MessageBubble from '$lib/components/messaging/MessageBubble.svelte';
	import MessageInput from '$lib/components/messaging/MessageInput.svelte';
	import GroupInfoPanel from '$lib/components/messaging/GroupInfoPanel.svelte';
	import NewChatModal from '$lib/components/messaging/NewChatModal.svelte';
	import NewGroupModal from '$lib/components/messaging/NewGroupModal.svelte';
	import AddMemberModal from '$lib/components/messaging/AddMemberModal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Input from '$lib/components/Input.svelte';
	import { Search } from 'lucide-svelte';
	import { formatMsgTime, formatDateSeparator, shouldShowDateSeparator } from '$lib/types/messaging';

	// ─── Derived ──────────────────────────────────────────────────────

	const currentUserId = $derived(authState.user?.id);
	$effect(() => { msg.currentUserId = currentUserId; });

	let otherUnreadCount = $derived(
		msg.conversations
			.filter(c => c.id !== msg.selectedConvId)
			.reduce((sum, c) => sum + (c.unread_count || 0), 0)
	);

	let _v = $derived(onlinePresence.version);
	function checkOnline(userId: number): boolean {
		void _v;
		return onlinePresence.ids.has(userId);
	}

	// ─── Composable'lar ───────────────────────────────────────────────

	const typingManager = createTypingManager(
		() => msg.selectedConvId,
		() => msg.selectedConvType,
		() => msg.selectedUser?.id ?? null,
	);

	const draftManager = createDraftManager();
	setDraftManager(draftManager);

	function handleTypingInput() { typingManager.handleInput(); }
	function handleDraftSave() { draftManager.scheduleAutoSave(msg.selectedConvId, msg.messageInput); }

	// ─── Lifecycle ────────────────────────────────────────────────────

	onMount(() => {
		const mainEl = document.querySelector('main');
		if (mainEl) {
			mainEl.style.overflow = 'hidden';
			mainEl.style.padding = '0';
		}

		loadConversationsImmediate().then(() => { msg.loading = false; });

		const wsUnsubscribers = [
			onWsEvent('new_message', handleWsNewMessage),
			onWsEvent('message_edited', handleWsMessageEdited),
			onWsEvent('message_deleted', handleWsMessageDeleted),
			onWsEvent('read_status', handleWsReadStatus),
			onWsEvent('typing', handleWsTyping),
			onWsEvent('new_conversation', handleWsNewConversation),
			onWsEvent('group_member_added', handleWsGroupUpdate),
			onWsEvent('group_member_removed', handleWsGroupMemberRemoved),
			onWsEvent('group_admin_changed', handleWsGroupUpdate),
			onWsEvent('group_name_changed', handleWsGroupNameChanged),
			onWsEvent('user_status', handleWsUserStatus),
			onWsEvent('connected', handleWsConnected),
		];

		const handleVisibilityChange = () => {
			if (!document.hidden) {
				resetReconnect();
				syncData();
			}
		};
		document.addEventListener('visibilitychange', handleVisibilityChange);

		return () => {
			if (mainEl) { mainEl.style.overflow = ''; mainEl.style.padding = ''; }
			wsUnsubscribers.forEach(unsub => unsub());
			cleanupWsHandlers();
			typingManager.cleanup();
			cleanupUiHandlers();
			draftManager.cleanup();
			if (msg.selectedConvId && msg.messageInput.trim()) draftManager.save(msg.selectedConvId, msg.messageInput);
			document.removeEventListener('visibilitychange', handleVisibilityChange);
			resetState();
		};
	});
</script>

<svelte:head><title>Sprenses - Mesajlaşma</title></svelte:head>

<div class="messaging-container h-full w-full flex bg-white md:rounded-xl overflow-hidden md:border md:border-gray-200 md:shadow-sm">
	<!-- Sol Panel: Konuşma Listesi -->
	<ConversationList
		conversations={msg.conversations}
		selectedConvId={msg.selectedConvId}
		currentUserId={currentUserId ?? 0}
		loading={msg.loading}
		bind:searchQuery={msg.searchQuery}
		onSelectConversation={selectConversation}
		onNewChat={() => msg.showNewChatModal = true}
		onDeleteConversation={deleteConversation}
		onToggleMute={toggleMute}
	/>

	<!-- Sağ Panel -->
	<div class="{msg.selectedConvId ? 'flex' : 'hidden md:flex'} flex-1 min-w-0 flex-col bg-gray-50 relative overflow-hidden">
		{#if !msg.selectedConvId}
			<div class="flex-1 flex flex-col items-center justify-center text-gray-500">
				<svg class="w-16 h-16 mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" /></svg>
				<p class="text-sm">Bir konuşma seçin veya yeni bir mesaj başlatın</p>
			</div>
		{:else}
			<!-- WS Bağlantı Durumu Banner'ı -->
			{#if wsState.reconnecting}
				<div class="bg-amber-50 border-b border-amber-200 px-4 py-2 text-center shrink-0">
					<div class="flex items-center justify-center gap-2">
						<div class="w-3.5 h-3.5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin"></div>
						<span class="text-xs text-amber-700 font-medium">Bağlantı yeniden kuruluyor...</span>
					</div>
				</div>
			{:else if !wsState.connected}
				<div class="bg-red-50 border-b border-red-200 px-4 py-2 text-center shrink-0">
					<span class="text-xs text-red-600 font-medium">Bağlantı kesildi</span>
					<button onclick={() => resetReconnect()} class="ml-2 text-xs text-red-700 underline hover:text-red-800 cursor-pointer">Yeniden bağlan</button>
				</div>
			{/if}

			<!-- Başlık -->
			<ChatHeader
				convType={msg.selectedConvType}
				convName={msg.selectedConvName}
				members={msg.selectedConvMembers}
				selectedUser={msg.selectedUser}
				isOnline={msg.selectedUser ? checkOnline(msg.selectedUser.id) : false}
				isMuted={msg.conversations.find(c => c.id === msg.selectedConvId)?.is_muted ?? false}
				{otherUnreadCount}
				bind:showMessageSearch={msg.showMessageSearch}
				bind:showGroupInfoPanel={msg.showGroupInfoPanel}
				onBack={deselectConversation}
				onSearchToggle={toggleMessageSearch}
				onToggleMute={() => { const conv = msg.conversations.find(c => c.id === msg.selectedConvId); if (conv) toggleMute(conv); }}
			/>

			<!-- Mesaj Arama Paneli -->
			{#if msg.showMessageSearch}
				<div class="bg-white border-b border-gray-200 px-3 py-2 shrink-0">
					<div class="relative">
						<Input type="search" icon={Search} size="sm" bind:value={msg.messageSearchQuery} oninput={handleMessageSearchInput} placeholder="Mesajlarda ara..." style="padding-right:2rem" />
						<button onclick={() => { msg.showMessageSearch = false; msg.messageSearchQuery = ''; msg.messageSearchResults = []; }} class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-600 cursor-pointer z-10" aria-label="Mesaj aramayı kapat">
							<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
						</button>
					</div>
					{#if msg.searchingMessages}
						<p class="text-xs text-gray-500 mt-1.5 px-1">Aranıyor...</p>
					{:else if msg.messageSearchQuery.trim() && msg.messageSearchResults.length === 0}
						<p class="text-xs text-gray-500 mt-1.5 px-1">Sonuç bulunamadı</p>
					{:else if msg.messageSearchResults.length > 0}
						<div class="mt-1.5 max-h-48 overflow-y-auto space-y-1">
							{#each msg.messageSearchResults as result}
								<button onclick={() => scrollToMessage(result.id)} class="w-full text-left px-2 py-1.5 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer">
									<p class="text-xs text-gray-500">{result.sender_name || ''} · {formatMsgTime(result.created_at)}</p>
									<p class="text-sm text-gray-900 truncate">{result.content}</p>
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<!-- Mesajlar -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div bind:this={msg.messagesEl} class="flex-1 overflow-y-auto p-3 md:p-4 space-y-2" onclick={closeMenus} onkeydown={() => {}} onscroll={handleMessagesScroll}>
				{#if msg.loadingMore}
					<div class="flex justify-center py-2"><div class="w-5 h-5 border-2 border-teal-500 border-t-transparent rounded-full animate-spin"></div></div>
				{/if}
				{#if msg.messages.length === 0}
					<div class="text-center text-gray-500 text-sm py-8">Henüz mesaj yok. İlk mesajınızı gönderin!</div>
				{:else}
					{#each msg.messages as message, i (message.id)}
						{#if shouldShowDateSeparator(message, i > 0 ? msg.messages[i - 1] : null)}
							<div class="flex justify-center my-3">
								<span class="bg-gray-200/80 text-gray-500 text-[11px] px-3 py-1 rounded-full font-medium">{formatDateSeparator(message.created_at)}</span>
							</div>
						{/if}
						<MessageBubble
							msg={message}
							isMine={message.sender_id === currentUserId}
							isGroupChat={msg.selectedConvType === 'group'}
							isPrivate={msg.selectedConvType === 'private'}
							isRead={isMessageRead(message)}
							editingMsgId={msg.editingMsgId}
							swipedMsgId={msg.swipedMsgId}
							actionMenuMsgId={msg.actionMenuMsgId}
							onStartEdit={startEdit}
							onDelete={deleteMessage}
							onToggleActionMenu={toggleActionMenu}
							onTouchStart={handleTouchStart}
							onTouchEnd={handleTouchEnd}
							onLightbox={(url) => msg.lightboxUrl = url}
						/>
					{/each}
				{/if}
			</div>

			<!-- Mesaj Girişi -->
			<MessageInput
				bind:messageInput={msg.messageInput}
				editingMsgId={msg.editingMsgId}
				bind:editContent={msg.editContent}
				sendingMessage={msg.sendingMessage}
				typingUserName={msg.typingUserName}
				otherUserTyping={msg.otherUserTyping}
				onSendMessage={sendMessage}
				onSaveEdit={saveEdit}
				onCancelEdit={cancelEdit}
				onTypingInput={handleTypingInput}
				onDraftSave={handleDraftSave}
				onSendFile={handleSendFile}
			/>

			<!-- Grup Bilgi Paneli -->
			{#if msg.selectedConvType === 'group'}
				<GroupInfoPanel
					bind:show={msg.showGroupInfoPanel}
					conversationId={msg.selectedConvId ?? 0}
					name={msg.selectedConvName ?? ''}
					members={msg.selectedConvMembers ?? []}
					createdBy={msg.selectedConvCreatedBy}
					currentUserId={currentUserId ?? 0}
					onAddMember={() => msg.showAddMemberModal = true}
					onMemberRemoved={async () => { await refreshConversationDetail(); await loadConversationsImmediate(); }}
					onLeftGroup={deselectConversation}
					onRefresh={refreshConversationDetail}
					onNameUpdated={handleGroupNameUpdated}
				/>
			{/if}
		{/if}
	</div>
</div>

<!-- Modallar -->
<NewChatModal
	bind:show={msg.showNewChatModal}
	onStartChat={handleStartChat}
	onOpenGroup={() => msg.showNewGroupModal = true}
/>

<NewGroupModal
	bind:show={msg.showNewGroupModal}
	onGroupCreated={handleGroupCreated}
/>

<AddMemberModal
	bind:show={msg.showAddMemberModal}
	conversationId={msg.selectedConvId ?? 0}
	existingMembers={msg.selectedConvMembers ?? []}
	onMembersAdded={async () => { await refreshConversationDetail(); await loadConversationsImmediate(); }}
/>

<!-- Lightbox -->
{#if msg.lightboxUrl}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4" onclick={() => msg.lightboxUrl = null} onkeydown={(e) => { if (e.key === 'Escape') msg.lightboxUrl = null; }} role="dialog" aria-modal="true" aria-label="Görüntü önizleme" tabindex="-1" use:focusTrap>
		<button class="absolute top-4 right-4 text-white/80 hover:text-white cursor-pointer" onclick={() => msg.lightboxUrl = null} aria-label="Görüntü önizlemeyi kapat">
			<svg class="w-8 h-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
		</button>
		<img src={msg.lightboxUrl} alt="Büyük görüntü" class="max-w-full max-h-full object-contain rounded-lg" />
	</div>
{/if}

<!-- Confirm Dialog -->
<ConfirmDialog
	bind:show={msg.showConfirmDialog}
	message={msg.confirmDialogMessage}
	danger
	onConfirm={() => resolveConfirm(true)}
	onCancel={() => resolveConfirm(false)}
/>

<style>
	:global(main:has(.messaging-container)) {
		overflow: hidden !important;
		padding: 0 !important;
	}
</style>
