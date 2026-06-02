import { describe, it, expect } from 'vitest';
import { validateEmail, validatePassword, validateRequired, validateModuleCode } from './validation';

describe('validateEmail', () => {
	it('null döndürür boş email için', () => {
		expect(validateEmail('')).toBeNull();
	});
	it('null döndürür geçerli email için', () => {
		expect(validateEmail('test@example.com')).toBeNull();
	});
	it('hata döndürür geçersiz email için', () => {
		expect(validateEmail('notanemail')).not.toBeNull();
	});
});

describe('validatePassword', () => {
	it('hata döndürür boş şifre için (required)', () => {
		expect(validatePassword('', true)).not.toBeNull();
	});
	it('null döndürür boş şifre için (not required)', () => {
		expect(validatePassword('', false)).toBeNull();
	});
	it('hata döndürür kısa şifre için', () => {
		expect(validatePassword('abc')).not.toBeNull();
	});
	it('null döndürür geçerli şifre için', () => {
		expect(validatePassword('password123')).toBeNull();
	});
});

describe('validateRequired', () => {
	it('hata döndürür boş değer için', () => {
		expect(validateRequired('', 'Alan')).not.toBeNull();
	});
	it('null döndürür dolu değer için', () => {
		expect(validateRequired('değer', 'Alan')).toBeNull();
	});
});

describe('validateModuleCode', () => {
	it('hata döndürür boş kod için', () => {
		expect(validateModuleCode('')).not.toBeNull();
	});
	it('null döndürür geçerli kod için', () => {
		expect(validateModuleCode('system.users')).toBeNull();
	});
	it('hata döndürür büyük harf içeren kod için', () => {
		expect(validateModuleCode('System')).not.toBeNull();
	});
});
