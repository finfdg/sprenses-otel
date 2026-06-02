import { api } from '$lib/api';
import { authState } from '$lib/stores/auth.svelte';

/**
 * Base64 VAPID anahtarını Push API için Uint8Array'e dönüştür.
 */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
	const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
	const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
	const rawData = window.atob(base64);
	const outputArray = new Uint8Array(rawData.length);
	for (let i = 0; i < rawData.length; ++i) {
		outputArray[i] = rawData.charCodeAt(i);
	}
	return outputArray;
}

export async function requestPushPermission(): Promise<boolean> {
	if (!('Notification' in window)) return false;
	if (!('serviceWorker' in navigator)) return false;
	if (!('PushManager' in window)) return false;

	const permission = await Notification.requestPermission();
	return permission === 'granted';
}

export async function subscribeToPush(): Promise<boolean> {
	try {
		// Backend'den VAPID public key al
		const { public_key } = await api.get<{ public_key: string }>('/push/vapid-key');

		const registration = await navigator.serviceWorker.ready;

		// Mevcut aboneliği kontrol et
		let subscription = await registration.pushManager.getSubscription();

		if (!subscription) {
			subscription = await registration.pushManager.subscribe({
				userVisibleOnly: true,
				applicationServerKey: urlBase64ToUint8Array(public_key) as BufferSource
			});
		}

		// Her açılışta aboneliği backend'e kaydet/güncelle (upsert)
		// Bu sayede eski endpoint'ler de otomatik güncellenir
		const subscriptionJson = subscription.toJSON();
		await api.post('/push/subscribe', {
			endpoint: subscription.endpoint,
			keys: {
				p256dh: subscriptionJson.keys?.p256dh || '',
				auth: subscriptionJson.keys?.auth || ''
			},
			user_agent: navigator.userAgent
		});

		// Service worker'a mevcut kullanıcı ID'sini bildir
		// Push geldiğinde yalnızca bu kullanıcıya ait bildirimleri gösterecek
		const currentUser = authState.user;
		if (currentUser) {
			const reg = await navigator.serviceWorker.ready;
			reg.active?.postMessage({
				type: 'SET_USER_ID',
				userId: currentUser.id
			});
		}

		return true;
	} catch (err) {
		console.error('Push aboneliği başarısız:', err);
		return false;
	}
}

export async function unsubscribeFromPush(): Promise<void> {
	try {
		const registration = await navigator.serviceWorker.ready;
		const subscription = await registration.pushManager.getSubscription();
		if (subscription) {
			await subscription.unsubscribe();
			await api.delete(`/push/unsubscribe?endpoint=${encodeURIComponent(subscription.endpoint)}`);
		}
	} catch (err) {
		console.error('Push aboneliği iptali başarısız:', err);
	}
}

export function isPushSupported(): boolean {
	return 'Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window;
}

export function getPushPermissionState(): NotificationPermission | 'unsupported' {
	if (!('Notification' in window)) return 'unsupported';
	return Notification.permission;
}
