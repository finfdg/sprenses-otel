/**
 * TableSkeleton bileşeni testleri.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import TableSkeleton from './TableSkeleton.svelte';

afterEach(() => cleanup());

describe('TableSkeleton', () => {
	it('varsayılan: 5 satır + 4 kolon + header render eder', () => {
		const { container } = render(TableSkeleton, {});
		const rows = container.querySelectorAll('.animate-pulse');
		// header (4) + 5*4 row cells = 24 animate-pulse divs
		expect(rows.length).toBe(4 + 5 * 4);
	});

	it('rows prop\'una göre satır sayısı ayarlanır', () => {
		const { container } = render(TableSkeleton, { rows: 3, columns: 2, showHeader: false });
		expect(container.querySelectorAll('.animate-pulse').length).toBe(3 * 2);
	});

	it('showHeader=false iken header render edilmez', () => {
		const { container } = render(TableSkeleton, { rows: 2, columns: 3, showHeader: false });
		expect(container.querySelectorAll('.animate-pulse').length).toBe(2 * 3);
	});

	it('role="status" + sr-only "Yükleniyor" mesajı içerir (a11y)', () => {
		const { container } = render(TableSkeleton, {});
		const status = container.querySelector('[role="status"]');
		expect(status).toBeTruthy();
		expect(status?.getAttribute('aria-label')).toBe('Yükleniyor');
		expect(container.querySelector('.sr-only')?.textContent).toBe('Yükleniyor...');
	});

	it('sıfır/negatif değerler en az 1\'e yuvarlanır', () => {
		const { container } = render(TableSkeleton, { rows: 0, columns: 0, showHeader: false });
		expect(container.querySelectorAll('.animate-pulse').length).toBe(1 * 1);
	});

	it('beyaz kart stili uygular', () => {
		const { container } = render(TableSkeleton, {});
		const card = container.querySelector('[role="status"]');
		expect(card?.className).toContain('bg-white');
		expect(card?.className).toContain('border');
		expect(card?.className).toContain('rounded-2xl');
	});
});
