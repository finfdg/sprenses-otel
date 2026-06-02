const BASE = '/api';

let redirecting = false;

// Aktif AbortController'ları takip et — sayfa geçişlerinde iptal için
const activeControllers = new Set<AbortController>();

/** Doğrulama hatalarında alan bilgisini de taşıyan hata sınıfı. */
export class ApiError extends Error {
	fields: string[];
	constructor(message: string, fields: string[] = []) {
		super(message);
		this.fields = fields;
	}
}

/** API hata yanıtından okunabilir Türkçe mesaj çıkar. */
function buildApiError(body: unknown, fallback: string): ApiError {
	if (!body || typeof body !== 'object') return new ApiError(fallback);
	const detail = (body as Record<string, unknown>).detail;
	if (typeof detail === 'string') return new ApiError(detail);
	if (Array.isArray(detail) && detail.length > 0) {
		const fields: string[] = [];
		const messages = detail.map((e: Record<string, unknown>) => {
			let msg = typeof e.msg === 'string' ? e.msg : String(e.msg);
			msg = msg.replace(/^Value error,\s*/i, '');
			if (Array.isArray(e.loc) && e.loc.length > 0) {
				fields.push(String(e.loc[e.loc.length - 1]));
			}
			return msg;
		});
		return new ApiError(messages.join(', '), fields);
	}
	return new ApiError(fallback);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
	const isFormData = options.body instanceof FormData;
	const headers: Record<string, string> = {
		...(isFormData ? {} : { 'Content-Type': 'application/json' }),
		...(options.headers as Record<string, string>)
	};

	// AbortController: dışarıdan verilmediyse oluştur
	const controller = new AbortController();
	activeControllers.add(controller);

	try {
		const res = await fetch(`${BASE}${path}`, {
			...options,
			headers,
			credentials: 'include',
			signal: options.signal || controller.signal,
		});

		if (res.status === 401) {
			// Login/register endpoint'lerinde 401 → sadece hata fırlat, redirect yapma
			if (path.startsWith('/auth/')) {
				const err = await res.json().catch(() => ({ detail: 'Yetkisiz' }));
				throw buildApiError(err, 'Yetkisiz');
			}
			// Diğer endpoint'lerde 401 → login'e yönlendir (sadece bir kez)
			if (!redirecting && typeof window !== 'undefined') {
				redirecting = true;
				localStorage.removeItem('user');
				// Oturum sonlandırma kontrolü
				const errBody = await res.clone().json().catch(() => ({ detail: '' }));
				const isSessionExpired = errBody.detail === 'Oturumunuz başka bir cihazdan sonlandırıldı';
				window.location.href = isSessionExpired ? '/?session_expired=1' : '/';
			}
			throw new Error('Unauthorized');
		}

		if (res.status === 403) {
			const err = await res.json().catch(() => ({ detail: 'Bu işlem için yetkiniz yok' }));
			throw buildApiError(err, 'Bu işlem için yetkiniz yok');
		}

		if (!res.ok) {
			const err = await res.json().catch(() => ({ detail: 'Bir hata oluştu' }));
			throw buildApiError(err, 'Bir hata oluştu');
		}

		if (res.status === 204) return undefined as T;
		return res.json();
	} finally {
		activeControllers.delete(controller);
	}
}

/**
 * Tüm aktif API isteklerini iptal et.
 * Sayfa geçişlerinde (onDestroy) çağrılabilir.
 */
export function abortAllRequests(): void {
	activeControllers.forEach((controller) => {
		controller.abort();
	});
	activeControllers.clear();
}

export const api = {
	get: <T>(path: string, signal?: AbortSignal) =>
		request<T>(path, signal ? { signal } : {}),
	post: <T>(path: string, body: unknown, signal?: AbortSignal) =>
		request<T>(path, { method: 'POST', body: JSON.stringify(body), ...(signal ? { signal } : {}) }),
	patch: <T>(path: string, body: unknown, signal?: AbortSignal) =>
		request<T>(path, { method: 'PATCH', body: JSON.stringify(body), ...(signal ? { signal } : {}) }),
	delete: <T = void>(path: string, signal?: AbortSignal) =>
		request<T>(path, { method: 'DELETE', ...(signal ? { signal } : {}) }),
	/** FormData ile dosya yükleme (Content-Type otomatik ayarlanır) */
	upload: <T>(path: string, formData: FormData, signal?: AbortSignal) =>
		request<T>(path, { method: 'POST', body: formData, ...(signal ? { signal } : {}) }),
	/** Ham Response döndürür (dosya indirme vb. için) */
	fetchRaw: (path: string, options: RequestInit = {}): Promise<Response> => {
		const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
		return fetch(`${BASE}${path}`, { ...options, headers, credentials: 'include' });
	},
};
