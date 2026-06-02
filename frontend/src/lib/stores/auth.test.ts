import { describe, it, expect, beforeEach, vi } from 'vitest';
import { authState, setAuth, loadAuth, hasPermission } from './auth.svelte';
import type { User } from './auth.svelte';

// ─── Yardımcı: test kullanıcısı ─────────────────────────────

function createTestUser(overrides: Partial<User> = {}): User {
	return {
		id: 1,
		username: 'testuser',
		email: 'test@example.com',
		first_name: 'Test',
		last_name: 'User',
		role_id: 1,
		role: { id: 1, name: 'Admin' },
		is_active: true,
		permissions: [
			{ module_code: 'finance.banks', module_name: 'Bankalar', can_view: true, can_use: true },
			{ module_code: 'finance.cariler', module_name: 'Cariler', can_view: true, can_use: false },
			{ module_code: 'system.users', module_name: 'Kullanıcılar', can_view: false, can_use: false },
		],
		...overrides,
	};
}

beforeEach(() => {
	authState.user = null;
	localStorage.clear();
});

// ─── setAuth ─────────────────────────────────────────────────

describe('setAuth', () => {
	it('authState.user değerini günceller', () => {
		const user = createTestUser();
		setAuth(user);
		expect(authState.user).toEqual(user);
	});

	it('localStorage\'a kaydeder', () => {
		const user = createTestUser();
		setAuth(user);
		const stored = localStorage.getItem('user');
		expect(stored).toBeTruthy();
		expect(JSON.parse(stored!).email).toBe('test@example.com');
	});
});

// ─── loadAuth ────────────────────────────────────────────────

describe('loadAuth', () => {
	it('localStorage\'dan kullanıcı yükler', () => {
		const user = createTestUser();
		localStorage.setItem('user', JSON.stringify(user));

		const result = loadAuth();

		expect(result).toBe(true);
		expect(authState.user).toEqual(user);
	});

	it('localStorage boşsa false döner', () => {
		const result = loadAuth();
		expect(result).toBe(false);
		expect(authState.user).toBeNull();
	});

	it('geçersiz JSON olursa false döner ve localStorage temizler', () => {
		localStorage.setItem('user', '{invalid-json}');
		const result = loadAuth();
		expect(result).toBe(false);
		expect(localStorage.getItem('user')).toBeNull();
	});

	it('username eksikse false döner', () => {
		localStorage.setItem('user', JSON.stringify({ email: 'test@test.com', first_name: 'Test' }));
		const result = loadAuth();
		expect(result).toBe(false);
	});

	it('first_name eksikse false döner', () => {
		localStorage.setItem('user', JSON.stringify({ username: 'test', email: 'test@test.com' }));
		const result = loadAuth();
		expect(result).toBe(false);
	});
});

// ─── hasPermission ───────────────────────────────────────────

describe('hasPermission', () => {
	it('kullanıcı yoksa false döner', () => {
		expect(hasPermission('finance.banks')).toBe(false);
	});

	it('can_view izni olan modül için true döner', () => {
		setAuth(createTestUser());
		expect(hasPermission('finance.banks', 'view')).toBe(true);
	});

	it('can_use izni olan modül için true döner', () => {
		setAuth(createTestUser());
		expect(hasPermission('finance.banks', 'use')).toBe(true);
	});

	it('can_view=true ama can_use=false modül için use false döner', () => {
		setAuth(createTestUser());
		expect(hasPermission('finance.cariler', 'view')).toBe(true);
		expect(hasPermission('finance.cariler', 'use')).toBe(false);
	});

	it('can_view=false modül için view false döner', () => {
		setAuth(createTestUser());
		expect(hasPermission('system.users', 'view')).toBe(false);
	});

	it('olmayan modül kodu için false döner', () => {
		setAuth(createTestUser());
		expect(hasPermission('nonexistent.module')).toBe(false);
	});

	it('varsayılan action "view" dir', () => {
		setAuth(createTestUser());
		expect(hasPermission('finance.banks')).toBe(true); // view default
	});

	it('permissions eksik kullanıcı için false döner', () => {
		setAuth(createTestUser({ permissions: undefined as any }));
		expect(hasPermission('finance.banks')).toBe(false);
	});
});
