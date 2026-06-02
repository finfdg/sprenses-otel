import { describe, it, expect, beforeEach } from 'vitest';
import {
	mutedConversationIds,
	setMutedConversations,
	updateMutedConversation,
	isConversationMuted,
	notificationSettings,
	toggleSound,
} from './notification.svelte';

beforeEach(() => {
	mutedConversationIds.ids = new Set();
	localStorage.clear();
});

// ─── setMutedConversations ───────────────────────────────────

describe('setMutedConversations', () => {
	it('ID listesini Set olarak ayarlar', () => {
		setMutedConversations([1, 2, 3]);
		expect(mutedConversationIds.ids.size).toBe(3);
		expect(mutedConversationIds.ids.has(1)).toBe(true);
		expect(mutedConversationIds.ids.has(2)).toBe(true);
		expect(mutedConversationIds.ids.has(3)).toBe(true);
	});

	it('boş dizi ile çağrılırsa boş Set olur', () => {
		setMutedConversations([1, 2]);
		setMutedConversations([]);
		expect(mutedConversationIds.ids.size).toBe(0);
	});

	it('önceki değerleri sıfırlar', () => {
		setMutedConversations([10, 20]);
		setMutedConversations([30]);
		expect(mutedConversationIds.ids.has(10)).toBe(false);
		expect(mutedConversationIds.ids.has(30)).toBe(true);
	});
});

// ─── updateMutedConversation ─────────────────────────────────

describe('updateMutedConversation', () => {
	it('isMuted=true ile ekler', () => {
		updateMutedConversation(5, true);
		expect(mutedConversationIds.ids.has(5)).toBe(true);
	});

	it('isMuted=false ile kaldırır', () => {
		setMutedConversations([5, 10]);
		updateMutedConversation(5, false);
		expect(mutedConversationIds.ids.has(5)).toBe(false);
		expect(mutedConversationIds.ids.has(10)).toBe(true);
	});

	it('olmayan ID kaldırmaya çalışırsa hata vermez', () => {
		expect(() => updateMutedConversation(999, false)).not.toThrow();
	});
});

// ─── isConversationMuted ─────────────────────────────────────

describe('isConversationMuted', () => {
	it('sessiz konuşma için true döner', () => {
		setMutedConversations([7]);
		expect(isConversationMuted(7)).toBe(true);
	});

	it('sessiz olmayan konuşma için false döner', () => {
		setMutedConversations([7]);
		expect(isConversationMuted(8)).toBe(false);
	});

	it('boş Set için false döner', () => {
		expect(isConversationMuted(1)).toBe(false);
	});
});

// ─── toggleSound ─────────────────────────────────────────────

describe('toggleSound', () => {
	it('sesi kapatır', () => {
		toggleSound(false);
		expect(notificationSettings.soundEnabled).toBe(false);
		expect(localStorage.getItem('notification_sound')).toBe('false');
	});

	it('sesi açar', () => {
		toggleSound(false);
		toggleSound(true);
		expect(notificationSettings.soundEnabled).toBe(true);
		expect(localStorage.getItem('notification_sound')).toBe('true');
	});
});
