/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

import { build, files, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;

// Unique cache name based on build version
const CACHE_NAME = `sprenses-cache-${version}`;

// Kullanıcı ID'si kalıcı depolama (Cache API) — SW sonlandırılsa bile korunur
const USER_ID_CACHE = 'sprenses-user-session';
const USER_ID_KEY = '/_internal/user-id';

async function saveCurrentUserId(userId: number | null): Promise<void> {
	const cache = await caches.open(USER_ID_CACHE);
	await cache.put(USER_ID_KEY, new Response(JSON.stringify({ userId })));
}

async function loadCurrentUserId(): Promise<number | null> {
	try {
		const cache = await caches.open(USER_ID_CACHE);
		const response = await cache.match(USER_ID_KEY);
		if (response) {
			const data = await response.json();
			return data.userId ?? null;
		}
	} catch (e) { console.error('[SW] user id cache okunamadı:', e); }
	return null;
}

// Assets to cache: build files (JS/CSS) + static files (icons, images)
const ASSETS = [...build, ...files];

// Install: cache all static assets
sw.addEventListener('install', (event: ExtendableEvent) => {
	event.waitUntil(
		caches
			.open(CACHE_NAME)
			.then((cache) => cache.addAll(ASSETS))
			.then(() => sw.skipWaiting())
	);
});

// Activate: clean up old caches & reload all open tabs to pick up new code
sw.addEventListener('activate', (event: ExtendableEvent) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(
					keys
						.filter((key) => key !== CACHE_NAME && key !== USER_ID_CACHE)
						.map((key) => caches.delete(key))
				)
			)
			.then(() => sw.clients.claim())
			.then(() => sw.clients.matchAll({ type: 'window' }))
			.then((windowClients) => {
				// Yeni versiyon aktifleştiğinde tüm açık sekmeleri yenile
				// böylece eski JavaScript kodu çalışmaya devam etmez
				for (const client of windowClients) {
					(client as WindowClient).navigate(client.url);
				}
			})
	);
});

// Fetch: network-first for navigation and API, cache-first for assets
sw.addEventListener('fetch', (event: FetchEvent) => {
	const url = new URL(event.request.url);

	// Skip non-GET requests
	if (event.request.method !== 'GET') return;

	// Skip API requests — always go to network
	if (url.pathname.startsWith('/api/')) return;

	// Skip chrome-extension and other non-http
	if (!url.protocol.startsWith('http')) return;

	// For navigation requests (HTML pages): network-first
	if (event.request.mode === 'navigate') {
		event.respondWith(
			fetch(event.request)
				.then((response) => {
					// Cache a copy of the page
					const clone = response.clone();
					caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
					return response;
				})
				.catch(() => {
					// Offline: try to serve from cache
					return caches.match(event.request).then((cached) => {
						return cached || caches.match('/') || new Response('Çevrimdışısınız', {
							status: 503,
							headers: { 'Content-Type': 'text/html; charset=utf-8' }
						});
					});
				})
		);
		return;
	}

	// For static assets (JS, CSS, images, fonts): cache-first
	if (ASSETS.includes(url.pathname)) {
		event.respondWith(
			caches.match(event.request).then((cached) => {
				return cached || fetch(event.request).then((response) => {
					const clone = response.clone();
					caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
					return response;
				});
			})
		);
		return;
	}

	// For other requests: network-first with cache fallback
	event.respondWith(
		fetch(event.request)
			.then((response) => {
				if (response.ok) {
					const clone = response.clone();
					caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
				}
				return response;
			})
			.catch(() => {
				return caches.match(event.request).then((cached) => {
					return cached || new Response('', { status: 503 });
				});
			})
	);
});

// --- Kullanıcı ID Senkronizasyonu (kalıcı depolama) ---
sw.addEventListener('message', (event: ExtendableMessageEvent) => {
	if (event.data?.type === 'SET_USER_ID') {
		const userId = event.data.userId ?? null;
		event.waitUntil(saveCurrentUserId(userId));
	}
});

// --- Push Notification ---
sw.addEventListener('push', (event: PushEvent) => {
	let payload: any;

	if (event.data) {
		try {
			payload = event.data.json();
		} catch (e) {
			console.error('[SW] push payload JSON parse edilemedi, text fallback:', e);
			payload = {
				title: 'Sprenses',
				body: event.data.text(),
				url: '/dashboard/mesajlasma',
				icon: '/icon-192.png'
			};
		}
	} else {
		payload = {
			title: 'Sprenses',
			body: 'Yeni bildiriminiz var',
			url: '/dashboard/mesajlasma',
			icon: '/icon-192.png'
		};
	}

	const options: NotificationOptions = {
		body: payload.body || '',
		icon: payload.icon || '/icon-192.png',
		badge: payload.badge || '/icon-192.png',
		tag: payload.tag || 'sprenses-notification',
		data: {
			url: payload.url || '/dashboard/mesajlasma'
		},
		renotify: true,
		requireInteraction: false,
	};

	// waitUntil her zaman çağrılmalı — aksi halde tarayıcı SW'yi sonlandırabilir
	event.waitUntil(
		Promise.all([
			loadCurrentUserId(),
			sw.clients.matchAll({ type: 'window', includeUncontrolled: true })
		]).then(([storedUserId, clients]) => {
			// Push payload'undaki user_id, bu tarayıcıda oturum açmış kullanıcıyla eşleşmiyorsa
			// bildirimi gösterme (aynı bilgisayarda farklı hesaplar için)
			if (payload.user_id && storedUserId && payload.user_id !== storedUserId) {
				return;
			}

			// Görünür (visible) uygulama penceresi varsa push bildirimi gösterme
			// — uygulama içi WS bildirim sesi zaten çalacak
			const hasVisibleClient = clients.some(
				(client) => (client as WindowClient).visibilityState === 'visible'
			);
			if (hasVisibleClient) {
				return;
			}
			return sw.registration.showNotification(payload.title || 'Sprenses', options);
		})
	);
});

// --- Push Subscription Değişikliği ---
// Abonelik süresi dolduğunda veya tarayıcı tarafından yenilendiğinde tetiklenir
sw.addEventListener('pushsubscriptionchange', ((event: any) => {
	// Eski aboneliği yeni abonelikle değiştir
	event.waitUntil(
		sw.registration.pushManager.subscribe(event.oldSubscription?.options || {
			userVisibleOnly: true,
		}).then((newSubscription) => {
			const subJson = newSubscription.toJSON();
			return fetch('/api/push/subscribe', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					endpoint: newSubscription.endpoint,
					keys: {
						p256dh: subJson.keys?.p256dh || '',
						auth: subJson.keys?.auth || '',
					},
					user_agent: 'ServiceWorker-Auto-Renew'
				})
			});
		}).catch((err) => {
			console.error('Push aboneliği yenilenemedi:', err);
		})
	);
}) as EventListener);

// --- Bildirime Tıklama ---
sw.addEventListener('notificationclick', (event: NotificationEvent) => {
	event.notification.close();

	const targetUrl = event.notification.data?.url || '/dashboard/mesajlasma';

	event.waitUntil(
		sw.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
			// Mevcut pencere varsa odaklan
			for (const client of clients) {
				if (client.url.includes('/dashboard') && 'focus' in client) {
					(client as WindowClient).focus();
					(client as WindowClient).navigate(targetUrl);
					return;
				}
			}
			// Mevcut pencere yoksa yeni aç
			if (sw.clients.openWindow) {
				return sw.clients.openWindow(targetUrl);
			}
		})
	);
});
