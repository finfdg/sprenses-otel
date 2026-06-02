/**
 * MoneyInput bileşeni — format/parse yardımcı fonksiyon testleri.
 *
 * Not: Tam DOM etkileşim testi için @testing-library/svelte gerekli.
 * Bu dosya yalnızca saf fonksiyonel birimleri (TR format, parse, sanitize) test eder
 * — bileşen içindeki aynı mantığı birebir yansıtan referans implementasyonlarla.
 */
import { describe, it, expect } from 'vitest';

// Bileşen içindeki fonksiyonların referans davranışı (export edilmediği için
// aynı algoritma burada tekrarlanır — değişiklik olursa test güncellenmelidir).

function formatTR(n: number | null | undefined, d = 2): string {
	if (n === null || n === undefined || !Number.isFinite(n)) return '';
	return n.toLocaleString('tr-TR', {
		minimumFractionDigits: d,
		maximumFractionDigits: d,
	});
}

function parseTR(raw: string, allowNegative = false): number | null {
	if (!raw) return null;
	let s = raw.replace(/\s/g, '');
	s = s.replace(/\./g, '');
	s = s.replace(/,/g, '.');
	const negative = s.startsWith('-');
	s = s.replace(/[^0-9.]/g, '');
	const firstDot = s.indexOf('.');
	if (firstDot !== -1) {
		s = s.slice(0, firstDot + 1) + s.slice(firstDot + 1).replace(/\./g, '');
	}
	if (!s || s === '.' || s === '-') return null;
	const n = parseFloat(s);
	if (!Number.isFinite(n)) return null;
	return negative && allowNegative ? -n : Math.abs(n);
}

function formatLiveTR(raw: string, d = 2, allowNeg = false): string {
	let s = raw;
	s = allowNeg ? s.replace(/[^0-9.,-]/g, '') : s.replace(/[^0-9.,]/g, '');
	const neg = allowNeg && s.startsWith('-');
	s = s.replace(/-/g, '');
	const commaIdx = s.indexOf(',');
	let intPart: string;
	let decPart = '';
	let hasComma = false;
	if (commaIdx !== -1) {
		hasComma = true;
		intPart = s.slice(0, commaIdx);
		decPart = s.slice(commaIdx + 1).replace(/[.,]/g, '').slice(0, d);
	} else {
		intPart = s;
	}
	intPart = intPart.replace(/\./g, '');
	if (intPart.length > 1) {
		intPart = intPart.replace(/^0+/, '');
		if (intPart === '') intPart = '0';
	}
	if (intPart.length > 3) {
		intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
	}
	let result = intPart;
	if (hasComma) result += ',' + decPart;
	if (neg) result = '-' + result;
	return result;
}

describe('MoneyInput — formatTR (TR binlik + 2 ondalık)', () => {
	it('1234.56 → "1.234,56"', () => {
		expect(formatTR(1234.56)).toBe('1.234,56');
	});
	it('1000000 → "1.000.000,00"', () => {
		expect(formatTR(1000000)).toBe('1.000.000,00');
	});
	it('0 → "0,00"', () => {
		expect(formatTR(0)).toBe('0,00');
	});
	it('null → ""', () => {
		expect(formatTR(null)).toBe('');
	});
	it('NaN → ""', () => {
		expect(formatTR(NaN)).toBe('');
	});
	it('0.1 ondalık hassasiyet (3 decimal) korunur', () => {
		expect(formatTR(0.125, 3)).toBe('0,125');
	});
});

describe('MoneyInput — parseTR (TR format → number)', () => {
	it('"1.234,56" → 1234.56', () => {
		expect(parseTR('1.234,56')).toBe(1234.56);
	});
	it('"1.000.000,00" → 1000000', () => {
		expect(parseTR('1.000.000,00')).toBe(1000000);
	});
	it('"300000" → 300000', () => {
		expect(parseTR('300000')).toBe(300000);
	});
	it('"0,5" → 0.5', () => {
		expect(parseTR('0,5')).toBe(0.5);
	});
	it('"" → null', () => {
		expect(parseTR('')).toBeNull();
	});
	it('"abc" → null', () => {
		expect(parseTR('abc')).toBeNull();
	});
	it('negatif yasak (default): "-100" → 100', () => {
		expect(parseTR('-100', false)).toBe(100);
	});
	it('negatif serbest: "-100" → -100', () => {
		expect(parseTR('-100', true)).toBe(-100);
	});
	it('birden fazla virgül → sadece ilki ondalık', () => {
		expect(parseTR('1,23,45')).toBe(1.2345);
	});
});

describe('MoneyInput — formatLiveTR (canlı binlik formatı)', () => {
	it('4 rakam → binlik eklenir', () => {
		expect(formatLiveTR('1234')).toBe('1.234');
	});
	it('7 rakam → iki binlik eklenir', () => {
		expect(formatLiveTR('1234567')).toBe('1.234.567');
	});
	it('kısmi ondalık korunur: "1234,5"', () => {
		expect(formatLiveTR('1234,5')).toBe('1.234,5');
	});
	it('tam ondalık: "1234,56"', () => {
		expect(formatLiveTR('1234,56')).toBe('1.234,56');
	});
	it('zaten formatlı input idempotent', () => {
		expect(formatLiveTR('1.234.567,89')).toBe('1.234.567,89');
	});
	it('mevcut noktalar kaldırılıp yeniden hesaplanır: "12.345.6" → "123.456"', () => {
		expect(formatLiveTR('12.345.6')).toBe('123.456');
	});
	it('sadece virgül yazılırsa korunur', () => {
		expect(formatLiveTR(',')).toBe(',');
	});
	it('sadece "0,5" → "0,5"', () => {
		expect(formatLiveTR('0,5')).toBe('0,5');
	});
	it('baştaki 0\'lar tekleştirilir: "0012" → "12"', () => {
		expect(formatLiveTR('0012')).toBe('12');
	});
	it('decimals=2 aşılmaz: "1,2345" → "1,23"', () => {
		expect(formatLiveTR('1,2345', 2)).toBe('1,23');
	});
	it('decimals=4 sınırı: "1,23456" → "1,2345"', () => {
		expect(formatLiveTR('1,23456', 4)).toBe('1,2345');
	});
	it('harf filtrelenir: "12a34" → "1.234"', () => {
		expect(formatLiveTR('12a34')).toBe('1.234');
	});
	it('birden fazla virgül: ilki kalır, sonrakiler ondalığa eklenir', () => {
		expect(formatLiveTR('1,2,3')).toBe('1,23');
	});
	it('negatif yasak → eksi düşer', () => {
		expect(formatLiveTR('-1234', 2, false)).toBe('1.234');
	});
	it('negatif serbest → eksi başta kalır', () => {
		expect(formatLiveTR('-1234', 2, true)).toBe('-1.234');
	});
	it('negatif serbest, ortadaki eksi düşer', () => {
		expect(formatLiveTR('-12-34', 2, true)).toBe('-1.234');
	});
	it('boş string → ""', () => {
		expect(formatLiveTR('')).toBe('');
	});
});

describe('MoneyInput — round-trip (format → parse)', () => {
	it('formatlama sonrası parse geri yükler', () => {
		const vals = [0, 1, 12.34, 1234.56, 1_000_000, 999_999.99];
		for (const v of vals) {
			expect(parseTR(formatTR(v))).toBeCloseTo(v, 2);
		}
	});
});
