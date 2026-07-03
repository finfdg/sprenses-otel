/**
 * PdfPreviewModal bileşeni testleri — açma/kapama, blob URL yaşam döngüsü, Esc.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import PdfPreviewModal from './PdfPreviewModal.svelte';

// jsdom URL.createObjectURL/revokeObjectURL sağlamaz — mock'lanır
let urlCounter = 0;
const createSpy = vi.fn(() => `blob:mock-${++urlCounter}`);
const revokeSpy = vi.fn();

beforeEach(() => {
	urlCounter = 0;
	createSpy.mockClear();
	revokeSpy.mockClear();
	URL.createObjectURL = createSpy as unknown as typeof URL.createObjectURL;
	URL.revokeObjectURL = revokeSpy as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => cleanup());

function makeBlob(): Blob {
	return new Blob(['%PDF-1.4'], { type: 'application/pdf' });
}

describe('PdfPreviewModal', () => {
	it('başlangıçta hiçbir şey render etmez', () => {
		const { container } = render(PdfPreviewModal);
		expect(container.querySelector('iframe')).toBeNull();
	});

	it('open() modalı dosya adı + iframe + İndir linkiyle gösterir', async () => {
		const { container, component, getByText } = render(PdfPreviewModal);
		component.open(makeBlob(), 'rapor.pdf');
		await tick();

		expect(getByText('rapor.pdf')).toBeTruthy();
		const iframe = container.querySelector('iframe');
		expect(iframe?.getAttribute('src')).toBe('blob:mock-1');
		const link = container.querySelector('a[download]');
		expect(link?.getAttribute('download')).toBe('rapor.pdf');
		expect(link?.getAttribute('href')).toBe('blob:mock-1');
	});

	it('ikinci open() önceki blob URL\'ini serbest bırakır', async () => {
		const { component } = render(PdfPreviewModal);
		component.open(makeBlob(), 'a.pdf');
		await tick();
		component.open(makeBlob(), 'b.pdf');
		await tick();

		expect(revokeSpy).toHaveBeenCalledWith('blob:mock-1');
	});

	it('close() modalı kapatır ve URL\'i serbest bırakır', async () => {
		const { container, component } = render(PdfPreviewModal);
		component.open(makeBlob(), 'rapor.pdf');
		await tick();
		component.close();
		await tick();

		expect(container.querySelector('iframe')).toBeNull();
		expect(revokeSpy).toHaveBeenCalledWith('blob:mock-1');
	});

	it('Esc tuşu modalı kapatır', async () => {
		const { container, component } = render(PdfPreviewModal);
		component.open(makeBlob(), 'rapor.pdf');
		await tick();
		await fireEvent.keyDown(window, { key: 'Escape' });
		await tick();

		expect(container.querySelector('iframe')).toBeNull();
		expect(revokeSpy).toHaveBeenCalledWith('blob:mock-1');
	});

	it('backdrop tıklaması modalı kapatır (içerik tıklaması kapatmaz)', async () => {
		const { container, component } = render(PdfPreviewModal);
		component.open(makeBlob(), 'rapor.pdf');
		await tick();

		const backdrop = container.querySelector('.fixed.inset-0') as HTMLElement;
		const content = backdrop.querySelector('.bg-white') as HTMLElement;
		await fireEvent.click(content);
		await tick();
		expect(container.querySelector('iframe')).toBeTruthy();

		await fireEvent.click(backdrop);
		await tick();
		expect(container.querySelector('iframe')).toBeNull();
	});
});
