import { describe, it, expect } from 'vitest';
import {
	SOURCE_BANK, SOURCE_CHECK, SOURCE_CREDIT, SOURCE_CC_PAYMENT,
	SOURCE_ADVANCE, SOURCE_VENDOR_PAYMENT, SOURCE_CASH_FLOW,
	TYPE_INCOME, TYPE_EXPENSE,
	TRANSFER_CATEGORIES,
	PM_HAVALE_EFT, PM_FAST, PM_VIRMAN, PM_CEK, PM_KREDI_KARTI,
	PM_OTOMATIK_ODEME, PM_NAKIT, PM_KREDI, PM_CARI, PM_SENET,
	PM_DIGER, PM_DEVIR,
	PAYMENT_METHOD_LABELS,
	TAG_AUTO, TAG_MANUAL,
	STATUS_PENDING, STATUS_RECEIVED, STATUS_CANCELLED, STATUS_PAID,
	STATUS_ACTIVE, STATUS_CLOSED,
	CREDIT_KREDI_KARTI, CREDIT_KMH, CREDIT_BCH, CREDIT_SPOT,
	CREDIT_TAKSITLI, CREDIT_LEASING,
	CREDIT_TYPE_LABELS,
	CURRENCY_TRY, CURRENCY_EUR, CURRENCY_USD, CURRENCY_GBP,
} from './finance';

// ─── Kaynak Tipleri ──────────────────────────────────────────

describe('kaynak tipleri', () => {
	it('7 kaynak tipi tanımlıdır', () => {
		const sources = [SOURCE_BANK, SOURCE_CHECK, SOURCE_CREDIT, SOURCE_CC_PAYMENT,
			SOURCE_ADVANCE, SOURCE_VENDOR_PAYMENT, SOURCE_CASH_FLOW];
		expect(sources).toHaveLength(7);
		// Hepsi benzersiz olmalı
		expect(new Set(sources).size).toBe(7);
	});

	it('değerler string türünde', () => {
		expect(typeof SOURCE_BANK).toBe('string');
		expect(SOURCE_BANK).toBe('bank');
		expect(SOURCE_CHECK).toBe('check');
		expect(SOURCE_CASH_FLOW).toBe('cash_flow');
	});
});

// ─── İşlem Yönü ─────────────────────────────────────────────

describe('işlem yönü', () => {
	it('income ve expense tanımlıdır', () => {
		expect(TYPE_INCOME).toBe('income');
		expect(TYPE_EXPENSE).toBe('expense');
	});
});

// ─── Transfer Kategorileri ───────────────────────────────────

describe('TRANSFER_CATEGORIES', () => {
	it('Set türünde ve 3 eleman içerir', () => {
		expect(TRANSFER_CATEGORIES).toBeInstanceOf(Set);
		expect(TRANSFER_CATEGORIES.size).toBe(3);
	});

	it('doğru kategorileri içerir', () => {
		expect(TRANSFER_CATEGORIES.has('Virman')).toBe(true);
		expect(TRANSFER_CATEGORIES.has('Döviz Satım')).toBe(true);
		expect(TRANSFER_CATEGORIES.has('İade')).toBe(true);
	});

	it('olmayan kategoriyi içermez', () => {
		expect(TRANSFER_CATEGORIES.has('Fatura')).toBe(false);
	});
});

// ─── Ödeme Yöntemleri ────────────────────────────────────────

describe('ödeme yöntemleri', () => {
	it('12 ödeme yöntemi tanımlıdır', () => {
		const methods = [PM_HAVALE_EFT, PM_FAST, PM_VIRMAN, PM_CEK, PM_KREDI_KARTI,
			PM_OTOMATIK_ODEME, PM_NAKIT, PM_KREDI, PM_CARI, PM_SENET, PM_DIGER, PM_DEVIR];
		expect(methods).toHaveLength(12);
		expect(new Set(methods).size).toBe(12);
	});

	it('PAYMENT_METHOD_LABELS her yöntem için etiket içerir', () => {
		const methods = [PM_HAVALE_EFT, PM_FAST, PM_VIRMAN, PM_CEK, PM_KREDI_KARTI,
			PM_OTOMATIK_ODEME, PM_NAKIT, PM_KREDI, PM_CARI, PM_SENET, PM_DIGER, PM_DEVIR];
		for (const method of methods) {
			expect(PAYMENT_METHOD_LABELS[method], `${method} etiketi eksik`).toBeTruthy();
		}
	});

	it('etiketler Türkçe karakter içerir', () => {
		expect(PAYMENT_METHOD_LABELS[PM_CEK]).toBe('Çek');
		expect(PAYMENT_METHOD_LABELS[PM_DIGER]).toBe('Diğer');
		expect(PAYMENT_METHOD_LABELS[PM_KREDI_KARTI]).toBe('Kredi Kartı');
	});
});

// ─── Etiket Kaynağı ─────────────────────────────────────────

describe('etiket kaynağı', () => {
	it('auto ve manual tanımlıdır', () => {
		expect(TAG_AUTO).toBe('auto');
		expect(TAG_MANUAL).toBe('manual');
	});
});

// ─── Avans Durumları ─────────────────────────────────────────

describe('avans durumları', () => {
	it('6 durum tanımlıdır', () => {
		const statuses = [STATUS_PENDING, STATUS_RECEIVED, STATUS_CANCELLED,
			STATUS_PAID, STATUS_ACTIVE, STATUS_CLOSED];
		expect(statuses).toHaveLength(6);
		expect(new Set(statuses).size).toBe(6);
	});
});

// ─── Kredi Ürün Tipleri ──────────────────────────────────────

describe('kredi ürün tipleri', () => {
	it('6 kredi tipi tanımlıdır', () => {
		const types = [CREDIT_KREDI_KARTI, CREDIT_KMH, CREDIT_BCH,
			CREDIT_SPOT, CREDIT_TAKSITLI, CREDIT_LEASING];
		expect(types).toHaveLength(6);
		expect(new Set(types).size).toBe(6);
	});

	it('CREDIT_TYPE_LABELS her tip için etiket içerir', () => {
		const types = [CREDIT_KREDI_KARTI, CREDIT_KMH, CREDIT_BCH,
			CREDIT_SPOT, CREDIT_TAKSITLI, CREDIT_LEASING];
		for (const type of types) {
			expect(CREDIT_TYPE_LABELS[type], `${type} etiketi eksik`).toBeTruthy();
		}
	});

	it('etiketler doğru', () => {
		expect(CREDIT_TYPE_LABELS[CREDIT_LEASING]).toBe('Leasing');
		expect(CREDIT_TYPE_LABELS[CREDIT_KMH]).toBe('KMH');
	});
});

// ─── Para Birimleri ──────────────────────────────────────────

describe('para birimleri', () => {
	it('4 para birimi tanımlıdır', () => {
		expect(CURRENCY_TRY).toBe('TRY');
		expect(CURRENCY_EUR).toBe('EUR');
		expect(CURRENCY_USD).toBe('USD');
		expect(CURRENCY_GBP).toBe('GBP');
	});
});
