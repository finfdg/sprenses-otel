/**
 * WebSocket event handler'ları.
 * Store'dan doğrudan import eder — deps injection yok.
 */

import { playNotificationSound, isConversationMuted } from '$lib/stores/notification.svelte';
import { emitLocal } from '$lib/stores/websocket.svelte';
import {
	msg, markAsRead, scrollToBottom, updateConversationLocally,
	loadConversationsImmediate, refreshConversationDetail,
	deselectConversation, syncData,
} from '$lib/stores/messaging.svelte';
import type { MessageItem } from '$lib/types/messaging';

let typingTimeout: ReturnType<typeof setTimeout> | null = null;

export function handleWsNewMessage(event: any) {
	const newMsg = event.message as MessageItem;
	const convId = newMsg.conversation_id;
	const isFromMe = newMsg.sender_id === msg.currentUserId;
	const convMuted = (msg.conversations.find(c => c.id === convId)?.is_muted ?? false) || isConversationMuted(convId);

	if (msg.selectedConvId && convId === msg.selectedConvId) {
		if (!msg.messages.find(m => m.id === newMsg.id)) {
			msg.messages = [...msg.messages, newMsg];
			if (!isFromMe) {
				const el = msg.messagesEl;
				if (el) {
					const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
					if (isNearBottom) { markAsRead(msg.selectedConvId!); scrollToBottom(); }
				}
			} else { scrollToBottom(); }
		}
	} else {
		if (!isFromMe && !convMuted) playNotificationSound();
	}

	const shouldIncrement = !isFromMe && convId !== msg.selectedConvId;
	const convExists = msg.conversations.some(c => c.id === convId);
	if (convExists) {
		updateConversationLocally(convId, {
			last_message: newMsg,
			unread_increment: shouldIncrement ? 1 : 0,
			moveToTop: true,
		});
	} else { loadConversationsImmediate(); }

	if (shouldIncrement) {
		emitLocal('unread_incremented');
	}

	msg.otherUserTyping = false;
}

export function handleWsMessageEdited(event: any) {
	const convId = event.conversation_id;
	if (msg.selectedConvId === convId) {
		msg.messages = msg.messages.map(m =>
			m.id === event.message_id ? { ...m, content: event.content, is_edited: true, edited_at: event.edited_at } : m
		);
	}
	const conv = msg.conversations.find(c => c.id === convId);
	if (conv && conv.last_message?.id === event.message_id) {
		updateConversationLocally(convId, { last_message: { ...conv.last_message, content: event.content, is_edited: true, edited_at: event.edited_at } as any, moveToTop: false });
	}
}

export function handleWsMessageDeleted(event: any) {
	const convId = event.conversation_id;
	if (msg.selectedConvId === convId) {
		msg.messages = msg.messages.map(m =>
			m.id === event.message_id ? { ...m, is_deleted: true, content: 'Bu mesaj silindi', file_url: null } : m
		);
	}
	const conv = msg.conversations.find(c => c.id === convId);
	if (conv && conv.last_message?.id === event.message_id) {
		updateConversationLocally(convId, { last_message: { ...conv.last_message, is_deleted: true, content: 'Bu mesaj silindi', file_url: null } as any, moveToTop: false });
	}
}

export function handleWsReadStatus(event: any) {
	if (msg.selectedConvId === event.conversation_id) msg.otherUserLastReadAt = event.last_read_at;
}

export function handleWsTyping(event: any) {
	if (msg.selectedConvId === event.conversation_id && event.user_id !== msg.currentUserId) {
		msg.otherUserTyping = event.is_typing;
		if (event.is_typing && msg.selectedConvType === 'group' && msg.selectedConvMembers) {
			const member = msg.selectedConvMembers.find(m => m.id === event.user_id);
			msg.typingUserName = member ? member.first_name : '';
		} else { msg.typingUserName = msg.selectedUser?.first_name || ''; }
		if (typingTimeout) clearTimeout(typingTimeout);
		if (event.is_typing) typingTimeout = setTimeout(() => { msg.otherUserTyping = false; }, 3000);
	}
}

export function handleWsConnected(_event: any) {
	syncData();
}

export function handleWsUserStatus(_event: any) {
	// Online durum güncellemesi WS store tarafından otomatik yapılır.
}

export function handleWsNewConversation(_event: any) { loadConversationsImmediate(); }

export function handleWsGroupUpdate(event: any) {
	loadConversationsImmediate();
	if (msg.selectedConvId === event.conversation_id) refreshConversationDetail();
}

export function handleWsGroupMemberRemoved(event: any) {
	loadConversationsImmediate();
	if (msg.selectedConvId === event.conversation_id) {
		if (event.user_id === msg.currentUserId) deselectConversation();
		else refreshConversationDetail();
	}
}

export function handleWsGroupNameChanged(event: any) {
	const convId = event.conversation_id;
	updateConversationLocally(convId, { name: event.name, moveToTop: false });
	if (msg.selectedConvId === convId) msg.selectedConvName = event.name;
}

export function cleanupWsHandlers() {
	if (typingTimeout) { clearTimeout(typingTimeout); typingTimeout = null; }
}
