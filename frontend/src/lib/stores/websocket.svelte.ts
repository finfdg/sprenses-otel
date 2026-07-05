// WebSocket bağlantı yönetimi — Svelte 5 runes modülü

import { WS_EVENT, type WsEventType } from '$lib/constants/realtime';

type EventHandler = (event: any) => void;

export const wsState = $state({
	connected: false,
	reconnecting: false
});

// ─── Online kullanıcı takibi (global, sayfa navigasyonlarında kaybolmaz) ───
// WS connected event'i ve user_status event'leri ile güncellenir.
// NOT: Fonksiyon sarmalayıcı (isUserOnline) yerine doğrudan reactive nesne
// export ediyoruz — Svelte 5 template'lerinde {#each} içi fonksiyon çağrıları
// her zaman signal tracking'i tetiklemeyebiliyor.
export const onlinePresence = $state<{ ids: Set<number>; names: Map<number, string>; version: number }>({
	ids: new Set(),
	names: new Map(),
	version: 0,
});

let ws: WebSocket | null = null;
// İlk 'connected' mi yoksa yeniden bağlanma mı? (reconnect'te finans sayfalarını tazele)
let hasEverConnected = false;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY = 1000; // 1 saniye
let pingInterval: ReturnType<typeof setInterval> | null = null;
let visibilityChangeHandler: (() => void) | null = null;

// Event listener kayıt defteri
const listeners: Map<string, Set<EventHandler>> = new Map();

export function onWsEvent(type: WsEventType, handler: EventHandler): () => void {
	if (!listeners.has(type)) {
		listeners.set(type, new Set());
	}
	listeners.get(type)!.add(handler);

	// Unsubscribe fonksiyonu döndür
	return () => {
		listeners.get(type)?.delete(handler);
	};
}

function emit(type: string, data: any): void {
	// ─── Store-seviyesi online durum takibi (sayfa bağımsız) ───
	if (type === 'connected' && Array.isArray(data.online_user_ids)) {
		onlinePresence.ids = new Set(data.online_user_ids);
		const nameMap = new Map<number, string>();
		if (Array.isArray(data.online_users)) {
			for (const u of data.online_users) {
				nameMap.set(u.id, u.name);
			}
		}
		onlinePresence.names = nameMap;
		onlinePresence.version++;
		// Auth başarılı — mevcut görünürlük durumunu bildir
		// (sekme arka plandayken WS yeniden bağlandıysa)
		if (document.visibilityState !== 'visible' && ws && ws.readyState === WebSocket.OPEN) {
			ws.send(JSON.stringify({ type: 'visibility', visible: false }));
		}
	} else if (type === 'user_status' && typeof data.user_id === 'number') {
		const next = new Set(onlinePresence.ids);
		const nextNames = new Map(onlinePresence.names);
		if (data.is_online) {
			next.add(data.user_id);
			if (data.user_name) nextNames.set(data.user_id, data.user_name);
		} else {
			next.delete(data.user_id);
			nextNames.delete(data.user_id);
		}
		onlinePresence.ids = next;
		onlinePresence.names = nextNames;
		onlinePresence.version++;
	}

	const handlers = listeners.get(type);
	if (handlers) {
		handlers.forEach(handler => {
			try {
				handler(data);
			} catch (e) {
				console.error('WebSocket event handler hatası:', e);
			}
		});
	}

	// ─── Yeniden bağlanma sonrası veri tazeleme ───
	// WS koparken (sunucu yeniden başladı, ağ dalgalandı vb.) gönderilen `finance_updated`
	// event'leri kaçırılır → açık banka/nakit-akım/cari/çek/kredi vb. sayfası bayat kalırdı.
	// Backend her başarılı (yeniden) bağlanmada `connected` mesajı yollar; İLK bağlantı
	// DIŞINDA local `finance_updated` yeniden yayınlarız → tüm finans sayfaları (hepsi
	// modülden bağımsız saf reload) kendini tazeler. İlk 'connected'te yayınlamayız
	// (onMount zaten ilk yüklemeyi yaptı). Sales gibi payload-bağımlı event'ler
	// bilerek hariç tutulur (sentetik yeniden yayın yanlış toast/eşleşme üretebilir).
	if (type === WS_EVENT.CONNECTED) {
		if (hasEverConnected) {
			emit(WS_EVENT.FINANCE_UPDATED, { type: WS_EVENT.FINANCE_UPDATED, reconnect: true });
		}
		hasEverConnected = true;
	}
}

/**
 * Yerel event tetikle — WebSocket üzerinden değil, aynı tarayıcı içinde.
 * Sidebar gibi bileşenlere sayfa içi bildirim göndermek için kullanılır.
 */
export function emitLocal(type: WsEventType, data: any = {}): void {
	emit(type, { type, ...data });
}

export function connectWebSocket(): void {
	// Auth kontrolü: localStorage'da user bilgisi varsa kullanıcı giriş yapmış demektir
	// Token HttpOnly cookie ile otomatik gönderilir (WebSocket upgrade request'te)
	const hasUser = typeof localStorage !== 'undefined' && localStorage.getItem('user');
	if (!hasUser) return;
	if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const wsUrl = `${protocol}//${window.location.host}/api/ws`;

	ws = new WebSocket(wsUrl);

	ws.onopen = () => {
		// Cookie tabanlı auth: token HttpOnly cookie ile upgrade request'te gönderildi
		// Ek auth mesajı gerekmez — backend cookie'den okur
		wsState.connected = true;
		wsState.reconnecting = false;
		reconnectAttempts = 0;

		// Her 30 saniyede bir ping gönder (keepalive)
		pingInterval = setInterval(() => {
			if (ws && ws.readyState === WebSocket.OPEN) {
				ws.send(JSON.stringify({ type: 'ping' }));
			}
		}, 30000);

		// Sayfa görünürlük değişikliğini sunucuya bildir (arka plan push bildirimi için)
		visibilityChangeHandler = () => {
			if (ws && ws.readyState === WebSocket.OPEN) {
				ws.send(JSON.stringify({ type: 'visibility', visible: document.visibilityState === 'visible' }));
			}
		};
		document.addEventListener('visibilitychange', visibilityChangeHandler);
	};

	ws.onmessage = (event) => {
		try {
			const data = JSON.parse(event.data);
			emit(data.type, data);
		} catch (e) { console.error('WebSocket mesaj parse hatası:', e); }
	};

	ws.onclose = (event) => {
		wsState.connected = false;
		onlinePresence.ids = new Set();
		onlinePresence.names = new Map();
		onlinePresence.version++;
		cleanup();

		// Auth hatası ise reconnect yapma
		if (event.code === 4001) return;

		// Oturum sonlandırıldıysa reconnect yapma
		if (event.code === 4002) return;

		scheduleReconnect();
	};

	ws.onerror = () => {
		// onclose zaten tetiklenecek
	};
}

function cleanup(): void {
	if (pingInterval) {
		clearInterval(pingInterval);
		pingInterval = null;
	}
	if (visibilityChangeHandler) {
		document.removeEventListener('visibilitychange', visibilityChangeHandler);
		visibilityChangeHandler = null;
	}
}

function scheduleReconnect(): void {
	if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;

	wsState.reconnecting = true;
	const delay = Math.min(
		BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts),
		30000 // max 30 saniye
	);
	reconnectAttempts++;

	reconnectTimer = setTimeout(() => {
		connectWebSocket();
	}, delay);
}

export function disconnectWebSocket(): void {
	if (reconnectTimer) {
		clearTimeout(reconnectTimer);
		reconnectTimer = null;
	}
	cleanup();
	reconnectAttempts = MAX_RECONNECT_ATTEMPTS; // Auto-reconnect engelle
	if (ws) {
		ws.close(1000, 'Client disconnect');
		ws = null;
	}
	wsState.connected = false;
	wsState.reconnecting = false;
}

export function sendWsEvent(event: any): void {
	if (ws && ws.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify(event));
	}
}

/**
 * Reconnect sayacını sıfırla ve bağlantı yoksa yeniden bağlan.
 * Visibility change veya ağ geri geldiğinde çağrılır.
 */
export function resetReconnect(): void {
	reconnectAttempts = 0;
	if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
		if (reconnectTimer) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
		connectWebSocket();
	}
}
