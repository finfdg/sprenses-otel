/**
 * Pagination bileşeni — getPageNumbers() saf fonksiyon testleri + DOM davranış testleri.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import Pagination, { getPageNumbers, DEFAULT_PAGE_SIZES } from './Pagination.svelte';

afterEach(() => cleanup());

describe('getPageNumbers', () => {
	it('0 sayfa için boş dizi döner', () => {
		expect(getPageNumbers(1, 0)).toEqual([]);
	});

	it('1 sayfa için [1] döner', () => {
		expect(getPageNumbers(1, 1)).toEqual([1]);
	});

	it('≤7 sayfa için hepsini listeler', () => {
		expect(getPageNumbers(1, 5)).toEqual([1, 2, 3, 4, 5]);
		expect(getPageNumbers(4, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
	});

	it('>7 sayfa, başta: 1 2 3 ... N pattern', () => {
		expect(getPageNumbers(1, 10)).toEqual([1, 2, '...', 10]);
		expect(getPageNumbers(2, 10)).toEqual([1, 2, 3, '...', 10]);
	});

	it('>7 sayfa, ortada: 1 ... X-1 X X+1 ... N pattern', () => {
		expect(getPageNumbers(5, 10)).toEqual([1, '...', 4, 5, 6, '...', 10]);
		expect(getPageNumbers(6, 12)).toEqual([1, '...', 5, 6, 7, '...', 12]);
	});

	it('>7 sayfa, sonda: 1 ... N-2 N-1 N pattern', () => {
		expect(getPageNumbers(10, 10)).toEqual([1, '...', 9, 10]);
		expect(getPageNumbers(9, 10)).toEqual([1, '...', 8, 9, 10]);
	});

	it('current sayfa her zaman listede yer alır', () => {
		for (let total = 1; total <= 20; total++) {
			for (let cur = 1; cur <= total; cur++) {
				expect(getPageNumbers(cur, total)).toContain(cur);
			}
		}
	});

	it('ilk ve son sayfa her zaman listede', () => {
		for (let total = 1; total <= 20; total++) {
			const pages = getPageNumbers(Math.ceil(total / 2), total);
			expect(pages[0]).toBe(1);
			expect(pages[pages.length - 1]).toBe(total);
		}
	});
});

describe('DEFAULT_PAGE_SIZES', () => {
	it('spec ile uyumlu değerler: 25, 50, 100, 200', () => {
		expect(DEFAULT_PAGE_SIZES).toEqual([25, 50, 100, 200]);
	});
});

describe('Pagination bileşeni', () => {
	const noop = () => {};

	it('toplam ve sayfa boyutu gösterilir', () => {
		render(Pagination, {
			page: 1,
			pageSize: 50,
			total: 100,
			onPageChange: noop,
			onPageSizeChange: noop
		});
		expect(screen.getByText(/Toplam 100/)).toBeTruthy();
	});

	it('önceki buton page=1 iken disabled', () => {
		render(Pagination, {
			page: 1,
			pageSize: 50,
			total: 200,
			onPageChange: noop,
			onPageSizeChange: noop
		});
		const prev = screen.getByLabelText('Önceki sayfa') as HTMLButtonElement;
		expect(prev.disabled).toBe(true);
	});

	it('sonraki buton son sayfada disabled', () => {
		render(Pagination, {
			page: 4,
			pageSize: 50,
			total: 200,
			onPageChange: noop,
			onPageSizeChange: noop
		});
		const next = screen.getByLabelText('Sonraki sayfa') as HTMLButtonElement;
		expect(next.disabled).toBe(true);
	});

	it('sayfa numarasına tıklayınca onPageChange çağrılır', async () => {
		const handler = vi.fn();
		render(Pagination, {
			page: 1,
			pageSize: 50,
			total: 200,
			onPageChange: handler,
			onPageSizeChange: noop
		});
		await fireEvent.click(screen.getByLabelText('Sayfa 3'));
		expect(handler).toHaveBeenCalledWith(3);
	});

	it('sonraki butona tıklayınca onPageChange(page+1) çağrılır', async () => {
		const handler = vi.fn();
		render(Pagination, {
			page: 2,
			pageSize: 50,
			total: 200,
			onPageChange: handler,
			onPageSizeChange: noop
		});
		await fireEvent.click(screen.getByLabelText('Sonraki sayfa'));
		expect(handler).toHaveBeenCalledWith(3);
	});

	it('sayfa boyutu değişince onPageSizeChange çağrılır', async () => {
		const handler = vi.fn();
		render(Pagination, {
			page: 1,
			pageSize: 50,
			total: 500,
			onPageChange: noop,
			onPageSizeChange: handler
		});
		const select = screen.getByRole('combobox') as HTMLSelectElement;
		await fireEvent.change(select, { target: { value: '100' } });
		expect(handler).toHaveBeenCalledWith(100);
	});

	it('aktif sayfa aria-current="page" taşır', () => {
		render(Pagination, {
			page: 2,
			pageSize: 50,
			total: 200,
			onPageChange: noop,
			onPageSizeChange: noop
		});
		const active = screen.getByLabelText('Sayfa 2');
		expect(active.getAttribute('aria-current')).toBe('page');
	});
});
