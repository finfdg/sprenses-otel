/**
 * Mesajlaşma modülü merkezi store.
 * Tüm state ve core fonksiyonlar burada tanımlanır.
 * Utility dosyaları (ws-handlers, messages, ui) bu store'dan import eder.
 */

import { api } from '$lib/api';
import { emitLocal } from '$lib/stores/websocket.svelte';
import { setMutedConversations } from '$lib/stores/notification.svelte';
import { showToast } from '$lib/stores/toast.svelte';
import type {
	OtherUser, GroupMember, MessageItem,
	ConversationItem, ConversationDetail,
} from '$lib/types/messaging';

// ─── State ──────────────────────────────────────────────────────────

export const msg = $state({
	// Kullanıcı
	currentUserId: undefined as number | undefined,

	// Konuşma listesi
	conversations: [] as ConversationItem[],
	loading: true,

	// Seçili konuşma
	selectedConvId: null as number | null,
	selectedConvType: 'private' as string,
	selectedConvName: null as string | null,
	selectedConvMembers: null as GroupMember[] | null,
	selectedConvCreatedBy: null as number | null,
	selectedUser: null as OtherUser | null,

	// Mesajlar
	messages: [] as MessageItem[],
	hasMore: false,
	loadingMore: false,

	// Giriş
	messageInput: '',
	sendingMessage: false,
	editingMsgId: null as number | null,
	editContent: '',

	// Durum
	otherUserLastReadAt: null as string | null,
	otherUserTyping: false,
	typingUserName: '',

	// UI
	searchQuery: '',
	swipedMsgId: null as number | null,
	actionMenuMsgId: null as number | null,
	showNewChatModal: false,
	showNewGroupModal: false,
	showGroupInfoPanel: false,
	showAddMemberModal: false,
	showMessageSearch: false,
	messageSearchQuery: '',
	messageSearchResults: [] as MessageItem[],
	searchingMessages: false,
	lightboxUrl: null as string | null,
	showConfirmDialog: false,
	confirmDialogMessage: '',

	// DOM referansı
	messagesEl: undefined as HTMLDivElement | undefined,
});

// ─── Confirm Dialog ─────────────────────────────────────────────────

let _confirmResolve: ((v: boolean) => void) | null = null;

export function requestConfirm(message: string): Promise<boolean> {
	msg.confirmDialogMessage = message;
	msg.showConfirmDialog = true;
	return new Promise(resolve => { _confirmResolve = resolve; });
}

export function resolveConfirm(value: boolean): void {
	_confirmResolve?.(value);
	_confirmResolve = null;
}

// ─── Konuşma Listesi Yerel Güncelleme ───────────────────────────────

export function updateConversationLocally(convId: number, updates: {
	last_message?: MessageItem | null;
	unread_increment?: number;
	name?: string;
	moveToTop?: boolean;
}) {
	const idx = msg.conversations.findIndex(c => c.id === convId);
	if (idx < 0) return;
	let conv: ConversationItem;
	try {
		conv = structuredClone(msg.conversations[idx]);
	} catch (e) {
		console.error('structuredClone başarısız — JSON fallback kullanılıyor:', e);
		conv = JSON.parse(JSON.stringify(msg.conversations[idx]));
	}
	if (updates.last_message !== undefined) conv.last_message = updates.last_message;
	if (updates.unread_increment) conv.unread_count += updates.unread_increment;
	if (updates.name !== undefined) conv.name = updates.name;
	conv.updated_at = new Date().toISOString();
	const next = msg.conversations.filter(c => c.id !== convId);
	if (updates.moveToTop !== false) next.unshift(conv);
	else next.splice(idx, 0, conv);
	msg.conversations = next;
}

// ─── Veri Yükleme ───────────────────────────────────────────────────

let _syncInProgress = false;

export async function syncData() {
	if (_syncInProgress) return;
	_syncInProgress = true;
	try {
		const convs = await api.get<ConversationItem[]>('/messages/conversations');
		if (msg.selectedConvId) {
			const idx = convs.findIndex(c => c.id === msg.selectedConvId);
			if (idx >= 0) convs[idx].unread_count = 0;
		}
		msg.conversations = convs;
		setMutedConversations(convs.filter(c => c.is_muted).map(c => c.id));
		const totalUnread = convs.reduce((sum, c) => sum + (c.unread_count || 0), 0);
		emitLocal('unread_updated', { total_unread: totalUnread });
		if (msg.selectedConvId && !convs.some(c => c.id === msg.selectedConvId)) {
			deselectConversation();
		} else if (msg.selectedConvId) {
			await refreshConversationDetail();
		}
	} catch (err) {
		console.error('Mesaj verileri alınamadı:', err);
	} finally {
		_syncInProgress = false;
	}
}

let _loadImmedInProgress = false;
let _loadImmedPending = false;

export async function loadConversationsImmediate() {
	// Dedup: eşzamanlı çağrıları birleştir
	if (_loadImmedInProgress) { _loadImmedPending = true; return; }
	_loadImmedInProgress = true;
	try {
		const convs = await api.get<ConversationItem[]>('/messages/conversations');
		if (msg.selectedConvId) {
			const idx = convs.findIndex(c => c.id === msg.selectedConvId);
			if (idx >= 0) convs[idx].unread_count = 0;
		}
		msg.conversations = convs;
		setMutedConversations(convs.filter(c => c.is_muted).map(c => c.id));
		const totalUnread = convs.reduce((sum, c) => sum + (c.unread_count || 0), 0);
		emitLocal('unread_updated', { total_unread: totalUnread });
	} catch (err) {
		console.error('Konuşmalar yüklenemedi:', err);
	} finally {
		_loadImmedInProgress = false;
		if (_loadImmedPending) {
			_loadImmedPending = false;
			loadConversationsImmediate();
		}
	}
}

export async function loadMoreMessages() {
	if (!msg.selectedConvId || msg.loadingMore || !msg.hasMore || msg.messages.length === 0) return;
	msg.loadingMore = true;
	const oldestId = msg.messages[0].id;
	try {
		const detail = await api.get<ConversationDetail>(`/messages/conversations/${msg.selectedConvId}?before_id=${oldestId}&limit=50`);
		msg.hasMore = detail.has_more;
		if (detail.messages.length > 0) {
			const prevScrollHeight = msg.messagesEl?.scrollHeight ?? 0;
			msg.messages = [...detail.messages, ...msg.messages];
			requestAnimationFrame(() => { if (msg.messagesEl) msg.messagesEl.scrollTop = msg.messagesEl.scrollHeight - prevScrollHeight; });
		}
	} catch (err) {
		console.error('Eski mesajlar yüklenemedi:', err);
		showToast('Eski mesajlar yüklenirken bir hata oluştu', 'error');
	}
	msg.loadingMore = false;
}

export function handleMessagesScroll() {
	if (!msg.messagesEl || msg.loadingMore || !msg.hasMore) return;
	if (msg.messagesEl.scrollTop < 100) loadMoreMessages();
}

export async function refreshConversationDetail() {
	if (!msg.selectedConvId) return;
	const convId = msg.selectedConvId;
	try {
		const detail = await api.get<ConversationDetail>(`/messages/conversations/${convId}`);
		if (msg.selectedConvId !== convId) return;
		if (detail.type === 'group') {
			msg.selectedConvMembers = detail.members;
			msg.selectedConvName = detail.name;
			msg.selectedConvCreatedBy = detail.created_by;
		} else { msg.otherUserLastReadAt = detail.other_user_last_read_at; }

		const freshMsgs = detail.messages;
		if (msg.messages.length > 0 && freshMsgs.length > 0) {
			const freshMinId = freshMsgs[0].id;
			const olderMessages = msg.messages.filter(m => m.id < freshMinId);
			const merged = [...olderMessages, ...freshMsgs];
			const hasChanged = merged.length !== msg.messages.length
				|| merged[merged.length - 1]?.id !== msg.messages[msg.messages.length - 1]?.id
				|| merged.some((m, i) => i < msg.messages.length && (
					m.id !== msg.messages[i].id || m.is_edited !== msg.messages[i].is_edited || m.is_deleted !== msg.messages[i].is_deleted
				));
			if (hasChanged) {
				msg.messages = merged;
				if (msg.messagesEl) {
					const isNearBottom = msg.messagesEl.scrollHeight - msg.messagesEl.scrollTop - msg.messagesEl.clientHeight < 100;
					if (isNearBottom) { await markAsRead(msg.selectedConvId); scrollToBottom(); }
				}
			}
		} else { msg.messages = freshMsgs; }
	} catch (err) {
		console.error('Konuşma detayı alınamadı:', err);
		if (msg.selectedConvId === convId) {
			const stillInList = msg.conversations.some(c => c.id === convId);
			if (!stillInList) {
				deselectConversation();
			} else {
				showToast('Konuşma detayları yüklenirken bir hata oluştu', 'error');
			}
		}
	}
}

// ─── Konuşma Seçimi ─────────────────────────────────────────────────

// draftManager referansı — page tarafından init sırasında atanır
let _draftManager: { save: (id: number, text: string) => void; load: (id: number) => string; clear: (id: number) => void } | null = null;

export function setDraftManager(dm: typeof _draftManager) {
	_draftManager = dm;
}

export function clearDraft(convId: number) {
	_draftManager?.clear(convId);
}

export async function selectConversation(conv: ConversationItem) {
	if (msg.selectedConvId && msg.messageInput.trim()) _draftManager?.save(msg.selectedConvId, msg.messageInput);
	msg.selectedConvId = conv.id;
	msg.selectedConvType = conv.type;
	msg.selectedConvName = conv.name;
	msg.selectedConvMembers = conv.members;
	msg.selectedUser = conv.other_user;
	msg.messages = [];
	msg.editingMsgId = null;
	msg.swipedMsgId = null;
	msg.actionMenuMsgId = null;
	msg.showGroupInfoPanel = false;
	msg.showMessageSearch = false;
	msg.hasMore = false;
	msg.messageInput = _draftManager?.load(conv.id) ?? '';
	const targetConvId = conv.id;
	try {
		const detail = await api.get<ConversationDetail>(`/messages/conversations/${conv.id}`);
		if (msg.selectedConvId !== targetConvId) return;
		msg.messages = detail.messages;
		msg.hasMore = detail.has_more;
		if (detail.type === 'group') {
			msg.selectedConvMembers = detail.members;
			msg.selectedConvCreatedBy = detail.created_by;
		} else { msg.otherUserLastReadAt = detail.other_user_last_read_at; }
		await markAsRead(conv.id);
		setTimeout(scrollToBottom, 50);
	} catch (err) {
		console.error('Mesajlar yüklenemedi:', err);
		showToast('Mesajlar yüklenirken bir hata oluştu', 'error');
	}
}

export function deselectConversation() {
	if (msg.selectedConvId && msg.messageInput.trim()) _draftManager?.save(msg.selectedConvId, msg.messageInput);
	msg.selectedConvId = null;
	msg.selectedConvType = 'private';
	msg.selectedConvName = null;
	msg.selectedConvMembers = null;
	msg.selectedConvCreatedBy = null;
	msg.selectedUser = null;
	msg.messages = [];
	msg.messageInput = '';
	msg.hasMore = false;
	msg.otherUserLastReadAt = null;
	msg.editingMsgId = null;
	msg.swipedMsgId = null;
	msg.actionMenuMsgId = null;
	msg.showGroupInfoPanel = false;
	msg.showMessageSearch = false;
}

// ─── Okundu İşaretle ────────────────────────────────────────────────

export async function markAsRead(convId: number) {
	// Optimistik güncelleme: önce UI'ı hemen güncelle
	const idx = msg.conversations.findIndex(c => c.id === convId);
	if (idx >= 0 && msg.conversations[idx].unread_count > 0) {
		try {
			const clone = structuredClone(msg.conversations[idx]);
			msg.conversations = msg.conversations.map((c, i) =>
				i === idx ? { ...clone, unread_count: 0 } : c
			);
		} catch (e) {
			// structuredClone proxy'de başarısız olabilir — fallback
			console.error('structuredClone başarısız (markAsRead) — JSON fallback kullanılıyor:', e);
			msg.conversations = msg.conversations.map((c, i) =>
				i === idx ? { ...JSON.parse(JSON.stringify(c)), unread_count: 0 } : c
			);
		}
	}
	const totalUnread = msg.conversations.reduce((sum, c) => sum + (c.unread_count || 0), 0);
	emitLocal('unread_updated', { total_unread: totalUnread });

	// API çağrısı arka planda — optimistik güncellemeyi engellemesin
	api.patch(`/messages/conversations/${convId}/read`, {}).catch(err => {
		console.error('Okundu olarak işaretlenemedi:', err);
	});
}

// ─── Yardımcı ───────────────────────────────────────────────────────

export function scrollToBottom() {
	if (msg.messagesEl) setTimeout(() => { if (msg.messagesEl) msg.messagesEl.scrollTop = msg.messagesEl.scrollHeight; }, 20);
}

export function resetState() {
	msg.conversations = [];
	msg.loading = true;
	msg.selectedConvId = null;
	msg.selectedConvType = 'private';
	msg.selectedConvName = null;
	msg.selectedConvMembers = null;
	msg.selectedConvCreatedBy = null;
	msg.selectedUser = null;
	msg.messages = [];
	msg.hasMore = false;
	msg.loadingMore = false;
	msg.messageInput = '';
	msg.sendingMessage = false;
	msg.editingMsgId = null;
	msg.editContent = '';
	msg.otherUserLastReadAt = null;
	msg.otherUserTyping = false;
	msg.typingUserName = '';
	msg.searchQuery = '';
	msg.swipedMsgId = null;
	msg.actionMenuMsgId = null;
	msg.showNewChatModal = false;
	msg.showNewGroupModal = false;
	msg.showGroupInfoPanel = false;
	msg.showAddMemberModal = false;
	msg.showMessageSearch = false;
	msg.messageSearchQuery = '';
	msg.messageSearchResults = [];
	msg.searchingMessages = false;
	msg.lightboxUrl = null;
	msg.showConfirmDialog = false;
	msg.confirmDialogMessage = '';
	msg.messagesEl = undefined;
	_draftManager = null;
	_syncInProgress = false;
}
