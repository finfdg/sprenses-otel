import { describe, it, expect, vi, beforeEach } from 'vitest';
import { isPushSupported, getPushPermissionState } from './push';

// ─── isPushSupported ─────────────────────────────────────────

describe('isPushSupported', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	it('tüm API\'ler mevcutsa true döner', () => {
		// jsdom varsayılanı Notification yok, mock edelim
		vi.stubGlobal('Notification', { permission: 'default' });
		vi.stubGlobal('navigator', {
			...navigator,
			serviceWorker: {},
		});
		vi.stubGlobal('PushManager', {});

		// window üzerinden kontrol
		expect(isPushSupported()).toBe(true);
	});

	it('Notification yoksa false döner', () => {
		// @ts-ignore
		delete (window as any).Notification;
		expect(isPushSupported()).toBe(false);
	});
});

// ─── getPushPermissionState ──────────────────────────────────

describe('getPushPermissionState', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	it('Notification yoksa "unsupported" döner', () => {
		// @ts-ignore
		delete (window as any).Notification;
		expect(getPushPermissionState()).toBe('unsupported');
	});

	it('izin verilmişse "granted" döner', () => {
		vi.stubGlobal('Notification', { permission: 'granted' });
		expect(getPushPermissionState()).toBe('granted');
	});

	it('izin reddedilmişse "denied" döner', () => {
		vi.stubGlobal('Notification', { permission: 'denied' });
		expect(getPushPermissionState()).toBe('denied');
	});

	it('henüz sorulmamışsa "default" döner', () => {
		vi.stubGlobal('Notification', { permission: 'default' });
		expect(getPushPermissionState()).toBe('default');
	});
});
