import { describe, it, expect } from 'vitest';
import {
	PAYMENT_METHODS,
	SELECTABLE_PAYMENT_METHODS,
	CATEGORIES_WITH_PAYMENT_METHOD,
	getPaymentMethod,
} from './paymentMethods';

// ─── PAYMENT_METHODS ─────────────────────────────────────────

describe('PAYMENT_METHODS', () => {
	it('11 ödeme yöntemi tanımlıdır', () => {
		expect(Object.keys(PAYMENT_METHODS)).toHaveLength(11);
	});

	it('her yöntem label, bg, text, border içerir', () => {
		for (const [code, method] of Object.entries(PAYMENT_METHODS)) {
			expect(method.label, `${code} label eksik`).toBeTruthy();
			expect(method.bg, `${code} bg eksik`).toMatch(/^bg-/);
			expect(method.text, `${code} text eksik`).toMatch(/^text-/);
			expect(method.border, `${code} border eksik`).toMatch(/^border-/);
		}
	});

	it('bilinen kodları içerir', () => {
		const codes = Object.keys(PAYMENT_METHODS);
		expect(codes).toContain('havale_eft');
		expect(codes).toContain('nakit');
		expect(codes).toContain('cek');
		expect(codes).toContain('kredi_karti');
		expect(codes).toContain('diger');
	});

	it('Türkçe label değerlerini doğru yazar', () => {
		expect(PAYMENT_METHODS.havale_eft.label).toBe('Havale/EFT');
		expect(PAYMENT_METHODS.cek.label).toBe('Çek');
		expect(PAYMENT_METHODS.kredi_karti.label).toBe('Kredi Kartı');
		expect(PAYMENT_METHODS.diger.label).toBe('Diğer');
	});
});

// ─── SELECTABLE_PAYMENT_METHODS ──────────────────────────────

describe('SELECTABLE_PAYMENT_METHODS', () => {
	it('5 seçilebilir yöntem var', () => {
		expect(SELECTABLE_PAYMENT_METHODS).toHaveLength(5);
	});

	it('her eleman code, label, icon içerir', () => {
		for (const method of SELECTABLE_PAYMENT_METHODS) {
			expect(method.code).toBeTruthy();
			expect(method.label).toBeTruthy();
			expect(method.icon).toBeTruthy();
		}
	});

	it('tüm kodlar PAYMENT_METHODS içinde bulunur', () => {
		for (const method of SELECTABLE_PAYMENT_METHODS) {
			expect(PAYMENT_METHODS[method.code], `${method.code} ana haritada yok`).toBeTruthy();
		}
	});
});

// ─── CATEGORIES_WITH_PAYMENT_METHOD ──────────────────────────

describe('CATEGORIES_WITH_PAYMENT_METHOD', () => {
	it('Set türünde ve boş değil', () => {
		expect(CATEGORIES_WITH_PAYMENT_METHOD).toBeInstanceOf(Set);
		expect(CATEGORIES_WITH_PAYMENT_METHOD.size).toBeGreaterThan(0);
	});

	it('bilinen kategorileri içerir', () => {
		expect(CATEGORIES_WITH_PAYMENT_METHOD.has('Cari')).toBe(true);
		expect(CATEGORIES_WITH_PAYMENT_METHOD.has('Personel')).toBe(true);
		expect(CATEGORIES_WITH_PAYMENT_METHOD.has('Vergi/SGK')).toBe(true);
	});

	it('bilinmeyen kategori içermez', () => {
		expect(CATEGORIES_WITH_PAYMENT_METHOD.has('BilinmeyenKategori')).toBe(false);
	});
});

// ─── getPaymentMethod ────────────────────────────────────────

describe('getPaymentMethod', () => {
	it('geçerli kod için doğru yöntem döner', () => {
		const result = getPaymentMethod('nakit');
		expect(result).not.toBeNull();
		expect(result!.label).toBe('Nakit');
	});

	it('null için null döner', () => {
		expect(getPaymentMethod(null)).toBeNull();
	});

	it('undefined için null döner', () => {
		expect(getPaymentMethod(undefined)).toBeNull();
	});

	it('boş string için null döner', () => {
		expect(getPaymentMethod('')).toBeNull();
	});

	it('bilinmeyen kod için "diger" fallback döner', () => {
		const result = getPaymentMethod('bilinmeyen_kod');
		expect(result).not.toBeNull();
		expect(result!.label).toBe('Diğer');
	});

	it('tüm tanımlı kodlar için doğru sonuç döner', () => {
		for (const code of Object.keys(PAYMENT_METHODS)) {
			const result = getPaymentMethod(code);
			expect(result).not.toBeNull();
			expect(result!.label).toBe(PAYMENT_METHODS[code].label);
		}
	});
});
