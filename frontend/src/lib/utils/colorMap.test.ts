import { describe, it, expect } from 'vitest';
import { categoryColorMap, filterColorMap, availableColors, getColor } from './colorMap';
import type { ColorClasses } from './colorMap';

// ─── categoryColorMap ────────────────────────────────────────

describe('categoryColorMap', () => {
	it('9 renk tanımlıdır', () => {
		expect(Object.keys(categoryColorMap)).toHaveLength(9);
	});

	it('her renk bg, text, border, bgActive içerir', () => {
		for (const [name, color] of Object.entries(categoryColorMap)) {
			expect(color.bg, `${name} bg eksik`).toMatch(/^bg-/);
			expect(color.text, `${name} text eksik`).toMatch(/^text-/);
			expect(color.border, `${name} border eksik`).toMatch(/^border-/);
			expect(color.bgActive, `${name} bgActive eksik`).toMatch(/^bg-/);
		}
	});

	it('bilinen renkleri içerir', () => {
		expect(categoryColorMap).toHaveProperty('purple');
		expect(categoryColorMap).toHaveProperty('teal');
		expect(categoryColorMap).toHaveProperty('gray');
		expect(categoryColorMap).toHaveProperty('red');
	});

	it('gray fallback rengi mevcuttur', () => {
		expect(categoryColorMap.gray).toBeDefined();
		expect(categoryColorMap.gray.bg).toBe('bg-gray-100');
	});
});

// ─── filterColorMap ──────────────────────────────────────────

describe('filterColorMap', () => {
	it('categoryColorMap ile aynı renk isimlerini içerir', () => {
		const catKeys = Object.keys(categoryColorMap).sort();
		const filterKeys = Object.keys(filterColorMap).sort();
		expect(filterKeys).toEqual(catKeys);
	});

	it('daha açık tonlar kullanır (50 vs 100)', () => {
		// filterColorMap bg-xxx-50, categoryColorMap bg-xxx-100
		expect(filterColorMap.purple.bg).toBe('bg-purple-50');
		expect(categoryColorMap.purple.bg).toBe('bg-purple-100');
	});

	it('her renk doğru yapıda', () => {
		for (const [name, color] of Object.entries(filterColorMap)) {
			expect(color.bg, `${name} bg`).toBeTruthy();
			expect(color.text, `${name} text`).toBeTruthy();
			expect(color.border, `${name} border`).toBeTruthy();
			expect(color.bgActive, `${name} bgActive`).toBeTruthy();
		}
	});
});

// ─── availableColors ─────────────────────────────────────────

describe('availableColors', () => {
	it('categoryColorMap anahtarları ile eşleşir', () => {
		expect(availableColors).toEqual(Object.keys(categoryColorMap));
	});

	it('dizi türündedir', () => {
		expect(Array.isArray(availableColors)).toBe(true);
	});
});

// ─── getColor ────────────────────────────────────────────────

describe('getColor', () => {
	it('geçerli renk için doğru sonuç döner', () => {
		const result = getColor('purple');
		expect(result).toBe(categoryColorMap.purple);
	});

	it('null için gray döner', () => {
		const result = getColor(null);
		expect(result).toBe(categoryColorMap.gray);
	});

	it('undefined için gray döner', () => {
		const result = getColor(undefined);
		expect(result).toBe(categoryColorMap.gray);
	});

	it('bilinmeyen renk için gray döner', () => {
		const result = getColor('bilinmeyen');
		expect(result).toBe(categoryColorMap.gray);
	});

	it('ikinci parametre ile filterColorMap kullanılabilir', () => {
		const result = getColor('teal', filterColorMap);
		expect(result).toBe(filterColorMap.teal);
	});

	it('filterColorMap ile bilinmeyen renk gray döner', () => {
		const result = getColor('yok', filterColorMap);
		expect(result).toBe(filterColorMap.gray);
	});

	it('tüm tanımlı renkler için doğru sonuç döner', () => {
		for (const color of availableColors) {
			const result = getColor(color);
			expect(result).toBe(categoryColorMap[color]);
		}
	});
});
