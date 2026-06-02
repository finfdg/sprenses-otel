import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api, abortAllRequests } from './api';

// ─── fetch mock ──────────────────────────────────────────────

const mockFetch = vi.fn();

beforeEach(() => {
	vi.stubGlobal('fetch', mockFetch);
	mockFetch.mockReset();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

function jsonResponse(data: unknown, status = 200) {
	return Promise.resolve({
		ok: status >= 200 && status < 300,
		status,
		json: () => Promise.resolve(data),
		clone: function () { return this; },
	});
}

function emptyResponse(status = 204) {
	return Promise.resolve({
		ok: true,
		status,
		json: () => Promise.resolve(undefined),
		clone: function () { return this; },
	});
}

// ─── api.get ─────────────────────────────────────────────────

describe('api.get', () => {
	it('doğru URL ile GET isteği yapar', async () => {
		mockFetch.mockReturnValue(jsonResponse({ items: [] }));

		await api.get('/finance/cash-flow/');

		expect(mockFetch).toHaveBeenCalledTimes(1);
		const [url, options] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/finance/cash-flow/');
		expect(options.method).toBeUndefined(); // GET default
		expect(options.credentials).toBe('include');
	});

	it('JSON body döner', async () => {
		mockFetch.mockReturnValue(jsonResponse({ total: 42 }));

		const result = await api.get<{ total: number }>('/test');
		expect(result.total).toBe(42);
	});

	it('Content-Type: application/json header ekler', async () => {
		mockFetch.mockReturnValue(jsonResponse({}));

		await api.get('/test');

		const headers = mockFetch.mock.calls[0][1].headers;
		expect(headers['Content-Type']).toBe('application/json');
	});
});

// ─── api.post ────────────────────────────────────────────────

describe('api.post', () => {
	it('POST metodu ile gönderir', async () => {
		mockFetch.mockReturnValue(jsonResponse({ id: 1 }));

		await api.post('/items', { name: 'Test' });

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('POST');
	});

	it('body JSON olarak serialize edilir', async () => {
		mockFetch.mockReturnValue(jsonResponse({ id: 1 }));

		const body = { name: 'Test', amount: 100 };
		await api.post('/items', body);

		const [, options] = mockFetch.mock.calls[0];
		expect(options.body).toBe(JSON.stringify(body));
	});
});

// ─── api.patch ───────────────────────────────────────────────

describe('api.patch', () => {
	it('PATCH metodu ile gönderir', async () => {
		mockFetch.mockReturnValue(jsonResponse({ ok: true }));

		await api.patch('/items/1', { name: 'Updated' });

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('PATCH');
	});
});

// ─── api.delete ──────────────────────────────────────────────

describe('api.delete', () => {
	it('DELETE metodu ile gönderir', async () => {
		mockFetch.mockReturnValue(emptyResponse(204));

		await api.delete('/items/1');

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('DELETE');
	});

	it('204 yanıtında undefined döner', async () => {
		mockFetch.mockReturnValue(emptyResponse(204));

		const result = await api.delete('/items/1');
		expect(result).toBeUndefined();
	});
});

// ─── api.upload ──────────────────────────────────────────────

describe('api.upload', () => {
	it('FormData gönderir ve Content-Type header eklemez', async () => {
		mockFetch.mockReturnValue(jsonResponse({ file_url: '/uploads/test.xlsx' }));

		const formData = new FormData();
		formData.append('file', new Blob(['test']), 'test.xlsx');

		await api.upload('/upload', formData);

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('POST');
		expect(options.body).toBe(formData);
		// FormData gönderiminde Content-Type browser tarafından ayarlanır
		expect(options.headers['Content-Type']).toBeUndefined();
	});
});

// ─── Hata Yönetimi ───────────────────────────────────────────

describe('hata yönetimi', () => {
	it('403 yanıtında yetki hatası fırlatır', async () => {
		mockFetch.mockReturnValue(jsonResponse({ detail: 'Bu işlem için yetkiniz yok' }, 403));

		await expect(api.get('/admin-only')).rejects.toThrow('Bu işlem için yetkiniz yok');
	});

	it('403 yanıtında detail yoksa varsayılan mesaj döner', async () => {
		mockFetch.mockReturnValue(
			Promise.resolve({
				ok: false,
				status: 403,
				json: () => Promise.reject(new Error('parse error')),
				clone: function () { return this; },
			})
		);

		await expect(api.get('/admin-only')).rejects.toThrow('Bu işlem için yetkiniz yok');
	});

	it('500 hatası için genel mesaj fırlatır', async () => {
		mockFetch.mockReturnValue(jsonResponse({ detail: 'Internal server error' }, 500));

		await expect(api.get('/broken')).rejects.toThrow('Internal server error');
	});

	it('422 validasyon hatası yakalar', async () => {
		mockFetch.mockReturnValue(jsonResponse({ detail: 'Geçersiz veri' }, 422));

		await expect(api.post('/items', {})).rejects.toThrow('Geçersiz veri');
	});

	it('JSON parse hatası durumunda varsayılan mesaj döner', async () => {
		mockFetch.mockReturnValue(
			Promise.resolve({
				ok: false,
				status: 400,
				json: () => Promise.reject(new Error('invalid json')),
				clone: function () { return this; },
			})
		);

		await expect(api.get('/bad')).rejects.toThrow('Bir hata oluştu');
	});
});

// ─── 401 Yönetimi ────────────────────────────────────────────

describe('401 yönetimi', () => {
	it('/auth/ yolunda 401 → redirect yapmaz, hata fırlatır', async () => {
		mockFetch.mockReturnValue(jsonResponse({ detail: 'Hatalı şifre' }, 401));

		await expect(api.post('/auth/login', { email: 'a@b.com', password: 'wrong' }))
			.rejects.toThrow('Hatalı şifre');
	});

	it('/auth/ yolunda 401 ve JSON parse hatası → varsayılan mesaj', async () => {
		mockFetch.mockReturnValue(
			Promise.resolve({
				ok: false,
				status: 401,
				json: () => Promise.reject(new Error('bad json')),
				clone: function () { return this; },
			})
		);

		await expect(api.post('/auth/login', {})).rejects.toThrow('Yetkisiz');
	});
});

// ─── AbortController ─────────────────────────────────────────

describe('abortAllRequests', () => {
	it('fonksiyon mevcut ve çağrılabilir', () => {
		expect(typeof abortAllRequests).toBe('function');
		// Aktif istek olmasa bile hata vermemeli
		expect(() => abortAllRequests()).not.toThrow();
	});
});

// ─── api.fetchRaw ────────────────────────────────────────────

describe('api.fetchRaw', () => {
	it('ham Response döndürür', async () => {
		const rawResponse = { ok: true, status: 200 };
		mockFetch.mockReturnValue(Promise.resolve(rawResponse));

		const result = await api.fetchRaw('/export/file.xlsx');

		expect(result).toBe(rawResponse);
		expect(mockFetch.mock.calls[0][0]).toBe('/api/export/file.xlsx');
	});

	it('credentials: include ile gönderir', async () => {
		mockFetch.mockReturnValue(Promise.resolve({ ok: true }));

		await api.fetchRaw('/download');

		const [, options] = mockFetch.mock.calls[0];
		expect(options.credentials).toBe('include');
	});
});

// ─── Signal Parametresi ──────────────────────────────────────

describe('signal parametresi', () => {
	it('api.get signal kabul eder', async () => {
		mockFetch.mockReturnValue(jsonResponse({}));
		const controller = new AbortController();

		await api.get('/test', controller.signal);

		const [, options] = mockFetch.mock.calls[0];
		expect(options.signal).toBe(controller.signal);
	});

	it('api.post signal kabul eder', async () => {
		mockFetch.mockReturnValue(jsonResponse({}));
		const controller = new AbortController();

		await api.post('/test', {}, controller.signal);

		const [, options] = mockFetch.mock.calls[0];
		expect(options.signal).toBe(controller.signal);
	});

	it('api.delete signal kabul eder', async () => {
		mockFetch.mockReturnValue(emptyResponse(204));
		const controller = new AbortController();

		await api.delete('/test', controller.signal);

		const [, options] = mockFetch.mock.calls[0];
		expect(options.signal).toBe(controller.signal);
	});
});
