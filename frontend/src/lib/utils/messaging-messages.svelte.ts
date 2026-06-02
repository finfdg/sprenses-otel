/**
 * Mesaj CRUD işlemleri.
 * Store'dan doğrudan import eder — deps injection yok.
 */

import { api } from '$lib/api';
import { showToast } from '$lib/stores/toast.svelte';
import {
	msg, scrollToBottom, updateConversationLocally, requestConfirm, clearDraft,
} from '$lib/stores/messaging.svelte';
import type { MessageItem } from '$lib/types/messaging';

export async function sendMessage() {
	if (!msg.messageInput.trim() || !msg.selectedConvId || msg.sendingMessage) return;
	msg.sendingMessage = true;
	const convId = msg.selectedConvId;
	try {
		const newMsg = await api.post<MessageItem>(`/messages/conversations/${convId}`, { content: msg.messageInput.trim() });
		try {
			msg.messages = [...msg.messages, newMsg];
			msg.messageInput = '';
			clearDraft(convId);
			scrollToBottom();
			updateConversationLocally(convId, { last_message: newMsg, moveToTop: true });
		} catch (uiErr) {
			console.error('Mesaj gönderildi ama UI güncellemesi başarısız:', uiErr);
		}
	} catch (err) {
		console.error('Mesaj gönderilemedi:', err);
		showToast(`Mesaj gönderilemedi: ${(err as Error)?.message || 'Bilinmeyen hata'}`, 'error');
	}
	msg.sendingMessage = false;
}

export async function handleSendFile(file: File, caption: string) {
	if (!msg.selectedConvId) return;
	const convId = msg.selectedConvId;
	try {
		const formData = new FormData();
		formData.append('file', file);
		if (caption) formData.append('caption', caption);
		const newMsg = await api.upload<MessageItem>(`/messages/conversations/${convId}/upload`, formData);
		if (msg.selectedConvId !== convId) return;
		try {
			msg.messages = [...msg.messages, newMsg];
			scrollToBottom();
			updateConversationLocally(convId, { last_message: newMsg, moveToTop: true });
		} catch (uiErr) {
			console.error('Dosya gönderildi ama UI güncellemesi başarısız:', uiErr);
		}
	} catch (err) {
		console.error('Dosya gönderilemedi:', err);
		showToast(`Dosya gönderilemedi: ${(err as Error)?.message || 'Bilinmeyen hata'}`, 'error');
	}
}

export function startEdit(message: MessageItem) {
	msg.editingMsgId = message.id;
	msg.editContent = message.content;
	msg.swipedMsgId = null;
	msg.actionMenuMsgId = null;
}

export function cancelEdit() {
	msg.editingMsgId = null;
	msg.editContent = '';
}

export async function saveEdit() {
	if (!msg.editingMsgId || !msg.editContent.trim() || !msg.selectedConvId) return;
	const convId = msg.selectedConvId;
	const msgId = msg.editingMsgId;
	try {
		const updated = await api.patch<MessageItem>(`/messages/conversations/${convId}/messages/${msgId}`, { content: msg.editContent.trim() });
		msg.messages = msg.messages.map(m => m.id === msgId ? updated : m);
		msg.editingMsgId = null;
		msg.editContent = '';
		const conv = msg.conversations.find(c => c.id === convId);
		if (conv?.last_message?.id === msgId) updateConversationLocally(convId, { last_message: updated, moveToTop: false });
	} catch (err) {
		console.error('Mesaj düzenlenemedi:', err);
		showToast('Mesaj düzenlenirken bir hata oluştu', 'error');
	}
}

export async function deleteMessage(msgId: number) {
	if (!msg.selectedConvId) return;
	const confirmed = await requestConfirm('Bu mesajı silmek istediğinize emin misiniz?');
	if (!confirmed) return;
	const convId = msg.selectedConvId;
	try {
		const updated = await api.delete<MessageItem>(`/messages/conversations/${convId}/messages/${msgId}`);
		msg.messages = msg.messages.map(m => m.id === msgId ? updated : m);
		msg.swipedMsgId = null;
		msg.actionMenuMsgId = null;
		const conv = msg.conversations.find(c => c.id === convId);
		if (conv?.last_message?.id === msgId) updateConversationLocally(convId, { last_message: updated, moveToTop: false });
	} catch (err) {
		console.error('Mesaj silinemedi:', err);
		showToast('Mesaj silinirken bir hata oluştu', 'error');
	}
}

let _cachedReadAt: string | null = null;
let _cachedReadDate: Date | null = null;

export function isMessageRead(message: MessageItem): boolean {
	const readAt = msg.otherUserLastReadAt;
	if (!readAt) return false;
	if (readAt !== _cachedReadAt) {
		_cachedReadAt = readAt;
		_cachedReadDate = new Date(readAt);
	}
	return new Date(message.created_at) <= _cachedReadDate!;
}
