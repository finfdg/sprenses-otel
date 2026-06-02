/**
 * Mesajlaşma sayfası yardımcı modülleri — typing, draft ve konuşma güncelleme.
 * +page.svelte'in karmaşıklığını azaltmak için ayrıştırılmıştır.
 */

import { sendWsEvent } from '$lib/stores/websocket.svelte';

// ─── Typing Göstergesi Yönetimi ─────────────────────────────────────

export interface TypingManager {
	handleInput: () => void;
	sendStop: () => void;
	cleanup: () => void;
}

/**
 * Typing event yönetimi oluşturur.
 * Kullanım: const tm = createTypingManager(getConvId, getConvType, getTargetUserId);
 */
export function createTypingManager(
	getConversationId: () => number | null,
	getConversationType: () => string,
	getTargetUserId: () => number | null,
): TypingManager {
	let myTypingTimeout: ReturnType<typeof setTimeout> | null = null;
	let myTypingStopTimeout: ReturnType<typeof setTimeout> | null = null;

	function send(isTyping: boolean) {
		const convId = getConversationId();
		if (!convId) return;
		const convType = getConversationType();
		const event: Record<string, unknown> = {
			type: 'typing',
			conversation_id: convId,
			is_typing: isTyping,
		};
		if (convType === 'private') {
			const targetId = getTargetUserId();
			if (targetId) event.target_user_id = targetId;
		}
		sendWsEvent(event);
	}

	function handleInput() {
		if (!getConversationId()) return;
		if (!myTypingTimeout) {
			send(true);
			myTypingTimeout = setTimeout(() => { myTypingTimeout = null; }, 2000);
		}
		if (myTypingStopTimeout) clearTimeout(myTypingStopTimeout);
		myTypingStopTimeout = setTimeout(() => {
			send(false);
			myTypingStopTimeout = null;
			if (myTypingTimeout) { clearTimeout(myTypingTimeout); myTypingTimeout = null; }
		}, 2500);
	}

	function sendStop() {
		send(false);
	}

	function cleanup() {
		if (myTypingTimeout) { clearTimeout(myTypingTimeout); myTypingTimeout = null; }
		if (myTypingStopTimeout) { clearTimeout(myTypingStopTimeout); myTypingStopTimeout = null; }
	}

	return { handleInput, sendStop, cleanup };
}


// ─── Draft (Taslak) Yönetimi ────────────────────────────────────────

export interface DraftManager {
	save: (convId: number, text: string) => void;
	load: (convId: number) => string;
	clear: (convId: number) => void;
	scheduleAutoSave: (convId: number | null, text: string) => void;
	cleanup: () => void;
}

export function createDraftManager(): DraftManager {
	let draftSaveTimeout: ReturnType<typeof setTimeout> | null = null;

	function save(convId: number, text: string) {
		try {
			if (text.trim()) localStorage.setItem(`draft-conv-${convId}`, text);
			else localStorage.removeItem(`draft-conv-${convId}`);
		} catch (err) { console.error('Taslak kaydedilemedi:', err); }
	}

	function load(convId: number): string {
		try { return localStorage.getItem(`draft-conv-${convId}`) || ''; }
		catch (err) { console.error('Taslak yüklenemedi:', err); return ''; }
	}

	function clear(convId: number) {
		try { localStorage.removeItem(`draft-conv-${convId}`); }
		catch (err) { console.error('Taslak temizlenemedi:', err); }
	}

	function scheduleAutoSave(convId: number | null, text: string) {
		if (!convId) return;
		if (draftSaveTimeout) clearTimeout(draftSaveTimeout);
		const id = convId;
		draftSaveTimeout = setTimeout(() => { save(id, text); }, 500);
	}

	function cleanup() {
		if (draftSaveTimeout) { clearTimeout(draftSaveTimeout); draftSaveTimeout = null; }
	}

	return { save, load, clear, scheduleAutoSave, cleanup };
}
