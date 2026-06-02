/**
 * SortableHeader — getNextSort cycle testleri + DOM davranışı.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import SortableHeader, { getNextSort } from './SortableHeader.svelte';

afterEach(() => cleanup());

describe('getNextSort', () => {
	it('pasif kolona tıklama → (column, asc)', () => {
		expect(getNextSort('name', null, null)).toEqual({ key: 'name', order: 'asc' });
		expect(getNextSort('name', 'date', 'desc')).toEqual({ key: 'name', order: 'asc' });
	});

	it('aktif + asc → desc', () => {
		expect(getNextSort('name', 'name', 'asc')).toEqual({ key: 'name', order: 'desc' });
	});

	it('aktif + desc → temizle (null/null)', () => {
		expect(getNextSort('name', 'name', 'desc')).toEqual({ key: null, order: null });
	});

	it('aktif + null → asc (güvenlik)', () => {
		expect(getNextSort('name', 'name', null)).toEqual({ key: 'name', order: 'asc' });
	});

	it('tek kolonda tam döngü: null → asc → desc → null', () => {
		let state: { key: string | null; order: 'asc' | 'desc' | null } = { key: null, order: null };
		state = getNextSort('name', state.key, state.order);
		expect(state).toEqual({ key: 'name', order: 'asc' });
		state = getNextSort('name', state.key, state.order);
		expect(state).toEqual({ key: 'name', order: 'desc' });
		state = getNextSort('name', state.key, state.order);
		expect(state).toEqual({ key: null, order: null });
	});
});

describe('SortableHeader bileşeni', () => {
	it('tıklayınca onSort çağrılır: pasif → asc', async () => {
		const handler = vi.fn();
		render(SortableHeader, {
			column: 'name',
			sortKey: null,
			sortOrder: null,
			onSort: handler,
			children: (() => 'Ad') as any
		});
		await fireEvent.click(screen.getByRole('button'));
		expect(handler).toHaveBeenCalledWith('name', 'asc');
	});

	it('aktif+asc → desc geçişi', async () => {
		const handler = vi.fn();
		render(SortableHeader, {
			column: 'name',
			sortKey: 'name',
			sortOrder: 'asc',
			onSort: handler,
			children: (() => 'Ad') as any
		});
		await fireEvent.click(screen.getByRole('button'));
		expect(handler).toHaveBeenCalledWith('name', 'desc');
	});

	it('aktif+desc → temizle (null/null)', async () => {
		const handler = vi.fn();
		render(SortableHeader, {
			column: 'name',
			sortKey: 'name',
			sortOrder: 'desc',
			onSort: handler,
			children: (() => 'Ad') as any
		});
		await fireEvent.click(screen.getByRole('button'));
		expect(handler).toHaveBeenCalledWith(null, null);
	});

	it('aktif+asc durumda data-sort-order="asc" + teal renk', () => {
		render(SortableHeader, {
			column: 'name',
			sortKey: 'name',
			sortOrder: 'asc',
			onSort: () => {},
			children: (() => 'Ad') as any
		});
		const btn = screen.getByRole('button');
		expect(btn.getAttribute('data-sort-order')).toBe('asc');
		expect(btn.className).toContain('text-teal-600');
	});

	it('aktif+desc durumda data-sort-order="desc"', () => {
		render(SortableHeader, {
			column: 'name',
			sortKey: 'name',
			sortOrder: 'desc',
			onSort: () => {},
			children: (() => 'Ad') as any
		});
		expect(screen.getByRole('button').getAttribute('data-sort-order')).toBe('desc');
	});

	it('pasif durumda data-sort-order="none" + gri renk', () => {
		render(SortableHeader, {
			column: 'name',
			sortKey: 'other',
			sortOrder: 'asc',
			onSort: () => {},
			children: (() => 'Ad') as any
		});
		const btn = screen.getByRole('button');
		expect(btn.getAttribute('data-sort-order')).toBe('none');
		expect(btn.className).toContain('text-gray-500');
	});
});
