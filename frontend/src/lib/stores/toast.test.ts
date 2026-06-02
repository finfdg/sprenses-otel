import { describe, it, expect, beforeEach, vi } from 'vitest';
import { toasts, showToast, removeToast } from './toast.svelte';

beforeEach(() => {
	// Her testten önce toast listesini temizle
	toasts.splice(0, toasts.length);
	vi.useFakeTimers();
});

// ─── showToast ───────────────────────────────────────────────

describe('showToast', () => {
	it('toast listesine ekler', () => {
		showToast('Başarılı');
		expect(toasts).toHaveLength(1);
		expect(toasts[0].message).toBe('Başarılı');
		expect(toasts[0].type).toBe('success');
	});

	it('varsayılan tip success', () => {
		showToast('Test');
		expect(toasts[0].type).toBe('success');
	});

	it('farklı tip belirlenebilir', () => {
		showToast('Hata oluştu', 'error');
		expect(toasts[0].type).toBe('error');
	});

	it('warning tipi', () => {
		showToast('Dikkat', 'warning');
		expect(toasts[0].type).toBe('warning');
	});

	it('info tipi', () => {
		showToast('Bilgi', 'info');
		expect(toasts[0].type).toBe('info');
	});

	it('süre sonunda otomatik kaldırılır', () => {
		showToast('Geçici', 'success', 2000);
		expect(toasts).toHaveLength(1);

		vi.advanceTimersByTime(2000);
		expect(toasts).toHaveLength(0);
	});

	it('varsayılan süre 3000ms', () => {
		showToast('Varsayılan');
		expect(toasts).toHaveLength(1);

		vi.advanceTimersByTime(2999);
		expect(toasts).toHaveLength(1);

		vi.advanceTimersByTime(1);
		expect(toasts).toHaveLength(0);
	});

	it('birden fazla toast eklenebilir', () => {
		showToast('Birinci');
		showToast('İkinci', 'error');
		showToast('Üçüncü', 'warning');
		expect(toasts).toHaveLength(3);
	});

	it('her toast benzersiz id alır', () => {
		showToast('A');
		showToast('B');
		expect(toasts[0].id).not.toBe(toasts[1].id);
	});
});

// ─── removeToast ─────────────────────────────────────────────

describe('removeToast', () => {
	it('id ile toast kaldırır', () => {
		showToast('Silinecek');
		const id = toasts[0].id;

		removeToast(id);
		expect(toasts).toHaveLength(0);
	});

	it('olmayan id ile çağrılırsa hata vermez', () => {
		expect(() => removeToast(999999)).not.toThrow();
	});

	it('sadece belirtilen toast\'ı kaldırır', () => {
		showToast('Kalacak');
		showToast('Silinecek');
		const deleteId = toasts[1].id;

		removeToast(deleteId);

		expect(toasts).toHaveLength(1);
		expect(toasts[0].message).toBe('Kalacak');
	});
});
