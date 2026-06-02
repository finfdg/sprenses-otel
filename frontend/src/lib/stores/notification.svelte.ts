// Bildirim sesi yönetimi — Svelte 5 runes modülü

export const notificationSettings = $state({
	soundEnabled: typeof localStorage !== 'undefined'
		? localStorage.getItem('notification_sound') !== 'false'
		: true
});

// Sessiz konuşma ID'leri — mesajlaşma sayfası ve Sidebar arasında paylaşılır
export const mutedConversationIds = $state<{ ids: Set<number> }>({ ids: new Set() });

export function setMutedConversations(convIds: number[]): void {
	mutedConversationIds.ids = new Set(convIds);
}

export function updateMutedConversation(convId: number, isMuted: boolean): void {
	if (isMuted) {
		mutedConversationIds.ids.add(convId);
	} else {
		mutedConversationIds.ids.delete(convId);
	}
	// Svelte 5 reaktivitesi için yeni Set oluştur
	mutedConversationIds.ids = new Set(mutedConversationIds.ids);
}

export function isConversationMuted(convId: number): boolean {
	return mutedConversationIds.ids.has(convId);
}

let audioInstance: HTMLAudioElement | null = null;
let audioUnlocked = false;

function getAudio(): HTMLAudioElement {
	if (!audioInstance) {
		audioInstance = new Audio('/sounds/notification.wav');
		audioInstance.volume = 0.5;
		audioInstance.preload = 'auto';
	}
	return audioInstance;
}

/**
 * iOS/Safari ses kısıtlaması için ilk kullanıcı etkileşiminde çağrılır.
 * Sessiz bir play yaparak audio context'i açar.
 */
export function unlockAudio(): void {
	if (audioUnlocked) return;
	const audio = getAudio();
	audio.muted = true;
	audio.play().then(() => {
		audio.pause();
		audio.muted = false;
		audio.currentTime = 0;
		audioUnlocked = true;
	}).catch((e) => {
		console.error('Ses kilidi açılamadı, sonraki etkileşimde tekrar denenecek:', e);
	});
}

export function playNotificationSound(): void {
	if (!notificationSettings.soundEnabled) return;
	try {
		const audio = getAudio();
		// iOS Safari: önceki çalma hâlâ devam ediyorsa durdur, sonra baştan çal
		if (!audio.paused) {
			audio.pause();
		}
		audio.currentTime = 0;
		audio.play().catch(() => {
			// iOS autoplay kısıtlaması — sessizce geç, kullanıcıyı rahatsız etme
		});
	} catch (e) {
		// Audio nesnesi erişilemez — kullanıcıyı rahatsız etme ama log düşür
		console.error('Bildirim sesi çalınamadı:', e);
	}
}

export function toggleSound(enabled: boolean): void {
	notificationSettings.soundEnabled = enabled;
	if (typeof localStorage !== 'undefined') {
		localStorage.setItem('notification_sound', String(enabled));
	}
}
