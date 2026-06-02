/**
 * BulkActionsBar bileşeni testleri.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import BulkActionsBar from './BulkActionsBar.svelte';

afterEach(() => cleanup());

describe('BulkActionsBar', () => {
	it('count=0 iken hiçbir şey render etmez', () => {
		const { container } = render(BulkActionsBar, {
			count: 0,
			onClear: () => {},
			children: (() => '') as any
		});
		expect(container.querySelector('[role="toolbar"]')).toBeNull();
	});

	it('count>0 iken toolbar render eder ve sayıyı gösterir', () => {
		render(BulkActionsBar, {
			count: 3,
			onClear: () => {},
			children: (() => '') as any
		});
		expect(screen.getByRole('toolbar')).toBeTruthy();
		expect(screen.getByText('3 kayıt seçildi')).toBeTruthy();
	});

	it('temizle butonuna tıklayınca onClear çağrılır', async () => {
		const clear = vi.fn();
		render(BulkActionsBar, {
			count: 5,
			onClear: clear,
			children: (() => '') as any
		});
		await fireEvent.click(screen.getByLabelText('Seçimi temizle'));
		expect(clear).toHaveBeenCalledTimes(1);
	});

	it('teal renk şeması uygular (bg-teal-50, border-teal-200)', () => {
		render(BulkActionsBar, {
			count: 1,
			onClear: () => {},
			children: (() => '') as any
		});
		const toolbar = screen.getByRole('toolbar');
		expect(toolbar.className).toContain('bg-teal-50');
		expect(toolbar.className).toContain('border-teal-200');
	});

	it('aria-label="Toplu işlem barı" taşır (a11y)', () => {
		render(BulkActionsBar, {
			count: 2,
			onClear: () => {},
			children: (() => '') as any
		});
		const toolbar = screen.getByRole('toolbar');
		expect(toolbar.getAttribute('aria-label')).toBe('Toplu işlem barı');
	});
});
