/**
 * StatusBadge bileşeni testleri — tip→renk eşlemesi ve görsel tutarlılık.
 */
import { describe, it, expect } from 'vitest';
import { BADGE_STYLES, type BadgeType } from './StatusBadge.svelte';

describe('StatusBadge — BADGE_STYLES', () => {
	it('5 tip tanımlıdır: success, error, warning, info, neutral', () => {
		const types: BadgeType[] = ['success', 'error', 'warning', 'info', 'neutral'];
		for (const t of types) {
			expect(BADGE_STYLES[t]).toBeTruthy();
		}
		expect(Object.keys(BADGE_STYLES).length).toBe(5);
	});

	it('success yeşil tonları kullanır', () => {
		expect(BADGE_STYLES.success).toContain('emerald');
	});

	it('error kırmızı tonları kullanır', () => {
		expect(BADGE_STYLES.error).toContain('red');
	});

	it('warning sarı/amber tonları kullanır', () => {
		expect(BADGE_STYLES.warning).toContain('amber');
	});

	it('info mavi tonları kullanır', () => {
		expect(BADGE_STYLES.info).toContain('blue');
	});

	it('neutral gri tonları kullanır', () => {
		expect(BADGE_STYLES.neutral).toContain('gray');
	});

	it('her tip bg, text ve border sınıflarını içerir', () => {
		for (const key of Object.keys(BADGE_STYLES) as BadgeType[]) {
			const classes = BADGE_STYLES[key];
			expect(classes).toMatch(/bg-\w+-\d+/);
			expect(classes).toMatch(/text-\w+-\d+/);
			expect(classes).toMatch(/border-\w+-\d+/);
		}
	});

	it('semantik renkler proje genelinde tekildir (duplicate yok)', () => {
		const all = Object.values(BADGE_STYLES);
		const unique = new Set(all);
		expect(unique.size).toBe(all.length);
	});
});
