/**
 * Breadcrumb bileşeni testleri.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/svelte';
import Breadcrumb from './Breadcrumb.svelte';

afterEach(() => cleanup());

describe('Breadcrumb', () => {
	it('boş items ile hiçbir şey render etmez', () => {
		const { container } = render(Breadcrumb, { items: [] });
		expect(container.querySelector('nav')).toBeNull();
	});

	it('tek item ile label gösterir, link oluşturmaz (current page)', () => {
		render(Breadcrumb, { items: [{ label: 'Ana Sayfa' }] });
		const span = screen.getByText('Ana Sayfa');
		expect(span.tagName).toBe('SPAN');
		expect(span.getAttribute('aria-current')).toBe('page');
	});

	it('çoklu item: son item span, öncekiler link (href varsa)', () => {
		render(Breadcrumb, {
			items: [
				{ label: 'Finans', href: '/dashboard/finans' },
				{ label: 'Bankalar', href: '/dashboard/finans/bankalar' },
				{ label: 'Talimatlar' }
			]
		});
		const finansEl = screen.getByText('Finans');
		expect(finansEl.tagName).toBe('A');
		expect(finansEl.getAttribute('href')).toBe('/dashboard/finans');

		const bankalarEl = screen.getByText('Bankalar');
		expect(bankalarEl.tagName).toBe('A');

		const talimatlarEl = screen.getByText('Talimatlar');
		expect(talimatlarEl.tagName).toBe('SPAN');
		expect(talimatlarEl.getAttribute('aria-current')).toBe('page');
	});

	it('href yoksa ara item da span olarak render edilir', () => {
		render(Breadcrumb, {
			items: [
				{ label: 'Üst' }, // href yok
				{ label: 'Şimdi' }
			]
		});
		const ustEl = screen.getByText('Üst');
		expect(ustEl.tagName).toBe('SPAN');
	});

	it('nav elementi aria-label="Yol göstergesi" taşır (a11y)', () => {
		const { container } = render(Breadcrumb, { items: [{ label: 'X' }] });
		const nav = container.querySelector('nav');
		expect(nav?.getAttribute('aria-label')).toBe('Yol göstergesi');
	});

	it('itemler arasına ayrıcı ikon yerleşir (items.length - 1 adet)', () => {
		const { container } = render(Breadcrumb, {
			items: [
				{ label: 'A', href: '/a' },
				{ label: 'B', href: '/b' },
				{ label: 'C' }
			]
		});
		// 3 item → 2 ayrıcı
		const separators = container.querySelectorAll('nav > svg');
		expect(separators.length).toBe(2);
	});
});
