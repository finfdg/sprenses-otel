/**
 * FormSkeleton bileşeni testleri.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import FormSkeleton from './FormSkeleton.svelte';

afterEach(() => cleanup());

describe('FormSkeleton', () => {
	it('varsayılan: 4 alan + submit butonlar render eder', () => {
		const { container } = render(FormSkeleton, {});
		const pulses = container.querySelectorAll('.animate-pulse');
		// 4 field × 2 (label + input) + 2 submit buttons = 10
		expect(pulses.length).toBe(4 * 2 + 2);
	});

	it('fields prop alan sayısını ayarlar', () => {
		const { container } = render(FormSkeleton, { fields: 2, showSubmit: false });
		expect(container.querySelectorAll('.animate-pulse').length).toBe(2 * 2);
	});

	it('showSubmit=false iken submit buton skeleton\'ları render edilmez', () => {
		const { container } = render(FormSkeleton, { fields: 3, showSubmit: false });
		expect(container.querySelectorAll('.animate-pulse').length).toBe(3 * 2);
	});

	it('role="status" + aria-label + sr-only içerir (a11y)', () => {
		const { container } = render(FormSkeleton, {});
		const status = container.querySelector('[role="status"]');
		expect(status).toBeTruthy();
		expect(status?.getAttribute('aria-label')).toBe('Form yükleniyor');
		expect(container.querySelector('.sr-only')?.textContent).toBe('Yükleniyor...');
	});

	it('sıfır/negatif alan sayısı en az 1\'e yuvarlanır', () => {
		const { container } = render(FormSkeleton, { fields: 0, showSubmit: false });
		expect(container.querySelectorAll('.animate-pulse').length).toBe(1 * 2);
	});
});
