/**
 * UI etkileşim handler'ları.
 * Store'dan doğrudan import eder — deps injection yok.
 */

import { api } from '$lib/api';
import { showToast } from '$lib/stores/toast.svelte';
import { updateMutedConversation } from '$lib/stores/notification.svelte';
import { emitLocal } from '$lib/stores/websocket.svelte';
import {
	msg, selectConversation, deselectConversation, updateConversationLocally,
	loadConversationsImmediate, loadMoreMessages, scrollToBottom, requestConfirm,
} from '$lib/stores/messaging.svelte';
import type { MessageItem, ConversationItem, ConversationDetail, ChatUser } from '$lib/types/messaging';

let touchStartX = 0;
let touchStartY = 0;
let messageSearchTimeout: ReturnType<typeof setTimeout> | null = null;

// ─── Touch / Swipe ───────────────────────────────────────────────

export function handleTouchStart(e: TouchEvent, message: MessageItem) {
	if (message.is_deleted || message.sender_id !== msg.currentUserId) return;
	touchStartX = e.touches[0].clientX;
	touchStartY = e.touches[0].clientY;
}

export function handleTouchEnd(e: TouchEvent, message: MessageItem) {
	if (message.is_deleted || message.sender_id !== msg.currentUserId) return;
	const deltaX = e.changedTouches[0].clientX - touchStartX;
	const deltaY = e.changedTouches[0].clientY - touchStartY;
	if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 50) {
		if (deltaX < -50) msg.swipedMsgId = msg.swipedMsgId === message.id ? null : message.id;
		else if (deltaX > 30 && msg.swipedMsgId === message.id) msg.swipedMsgId = null;
	}
}

export function toggleActionMenu(e: MouseEvent, msgId: number) {
	e.stopPropagation();
	msg.actionMenuMsgId = msg.actionMenuMsgId === msgId ? null : msgId;
}

export function closeMenus() {
	msg.swipedMsgId = null;
	msg.actionMenuMsgId = null;
}

// ─── Mesaj Arama ─────────────────────────────────────────────────

export async function searchMessagesInConv() {
	if (!msg.selectedConvId || !msg.messageSearchQuery.trim()) { msg.messageSearchResults = []; return; }
	msg.searchingMessages = true;
	try {
		const results = await api.get<MessageItem[]>(
			`/messages/conversations/${msg.selectedConvId}/search?q=${encodeURIComponent(msg.messageSearchQuery.trim())}`
		);
		msg.messageSearchResults = results;
	} catch (err) { console.error('Mesaj araması başarısız:', err); }
	msg.searchingMessages = false;
}

export function handleMessageSearchInput() {
	if (messageSearchTimeout) clearTimeout(messageSearchTimeout);
	messageSearchTimeout = setTimeout(searchMessagesInConv, 400);
}

export async function scrollToMessage(msgId: number) {
	msg.showMessageSearch = false;
	msg.messageSearchQuery = '';
	msg.messageSearchResults = [];
	const el = msg.messagesEl;
	let target = el?.querySelector(`[data-msg-id="${msgId}"]`) as HTMLElement | null;
	if (!target && msg.selectedConvId && msg.hasMore) {
		let attempts = 0;
		while (!target && msg.hasMore && attempts < 10) {
			await loadMoreMessages();
			await new Promise(r => setTimeout(r, 100));
			target = el?.querySelector(`[data-msg-id="${msgId}"]`) as HTMLElement | null;
			attempts++;
		}
	}
	if (target) {
		target.scrollIntoView({ behavior: 'smooth', block: 'center' });
		target.classList.add('ring-2', 'ring-teal-400');
		setTimeout(() => target!.classList.remove('ring-2', 'ring-teal-400'), 2000);
	}
}

export function toggleMessageSearch() {
	const current = msg.showMessageSearch;
	msg.showMessageSearch = !current;
	if (current) { msg.messageSearchQuery = ''; msg.messageSearchResults = []; }
}

// ─── Modal İşlemleri ─────────────────────────────────────────────

export async function handleStartChat(chatUser: ChatUser) {
	if (chatUser.has_existing_conversation && chatUser.conversation_id) {
		const conv = msg.conversations.find(c => c.id === chatUser.conversation_id);
		if (conv) { await selectConversation(conv); return; }
	}
	try {
		const detail = await api.post<ConversationDetail>('/messages/conversations', { user_id: chatUser.id });
		msg.selectedConvId = detail.id;
		msg.selectedConvType = detail.type;
		msg.selectedUser = detail.other_user;
		msg.messages = detail.messages;
		msg.hasMore = detail.has_more;
		msg.otherUserLastReadAt = detail.other_user_last_read_at;
		await loadConversationsImmediate();
		setTimeout(scrollToBottom, 50);
	} catch (err) {
		console.error('Yeni konuşma başlatılamadı:', err);
		showToast('Konuşma başlatılırken bir hata oluştu', 'error');
	}
}

export function handleGroupCreated(detail: ConversationDetail) {
	msg.selectedConvId = detail.id;
	msg.selectedConvType = detail.type;
	msg.selectedConvName = detail.name;
	msg.selectedConvMembers = detail.members;
	msg.selectedConvCreatedBy = detail.created_by;
	msg.messages = detail.messages;
	msg.hasMore = detail.has_more;
	loadConversationsImmediate();
	setTimeout(scrollToBottom, 50);
}

export function handleGroupNameUpdated(newName: string) {
	msg.selectedConvName = newName;
	const convId = msg.selectedConvId;
	if (convId) updateConversationLocally(convId, { name: newName, moveToTop: false });
}

// ─── Konuşma Aksiyonları ─────────────────────────────────────────

export async function toggleMute(conv: ConversationItem) {
	const newMuted = !conv.is_muted;
	try {
		await api.patch(`/messages/conversations/${conv.id}/mute`, { is_muted: newMuted });
		msg.conversations = msg.conversations.map(c =>
			c.id === conv.id ? { ...c, is_muted: newMuted } : c
		);
		updateMutedConversation(conv.id, newMuted);
		showToast(newMuted ? 'Konuşma sessize alındı' : 'Konuşma sesi açıldı', 'success');
	} catch (err) {
		console.error('Sessiz ayarı değiştirilemedi:', err);
		showToast('Sessiz ayarı değiştirilirken bir hata oluştu', 'error');
	}
}

export async function deleteConversation(conv: ConversationItem) {
	const confirmed = await requestConfirm('Bu konuşmayı silmek istediğinize emin misiniz?');
	if (!confirmed) return;
	try {
		await api.delete(`/messages/conversations/${conv.id}`);
		msg.conversations = msg.conversations.filter(c => c.id !== conv.id);
		if (msg.selectedConvId === conv.id) deselectConversation();
		showToast('Konuşma silindi', 'success');
		emitLocal('unread_updated');
	} catch (err) {
		console.error('Konuşma silinemedi:', err);
		showToast('Konuşma silinirken bir hata oluştu', 'error');
	}
}

export function cleanupUiHandlers() {
	if (messageSearchTimeout) { clearTimeout(messageSearchTimeout); messageSearchTimeout = null; }
}
