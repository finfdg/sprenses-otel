/**
 * FileDropzone bileşeni testleri — saf fonksiyonlar + DOM davranışı.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/svelte';
import FileDropzone, { formatSize, validateFiles } from './FileDropzone.svelte';

afterEach(() => cleanup());

describe('formatSize', () => {
	it('bytes', () => {
		expect(formatSize(0)).toBe('0 B');
		expect(formatSize(512)).toBe('512 B');
		expect(formatSize(1023)).toBe('1023 B');
	});

	it('kilobytes', () => {
		expect(formatSize(1024)).toBe('1.0 KB');
		expect(formatSize(1536)).toBe('1.5 KB');
	});

	it('megabytes', () => {
		expect(formatSize(1024 * 1024)).toBe('1.0 MB');
		expect(formatSize(1024 * 1024 * 5.5)).toBe('5.5 MB');
	});

	it('gigabytes', () => {
		expect(formatSize(1024 * 1024 * 1024)).toBe('1.00 GB');
		expect(formatSize(1024 * 1024 * 1024 * 2.5)).toBe('2.50 GB');
	});
});

function makeFile(name: string, size: number, type: string): File {
	const f = new File(['x'.repeat(size > 1000 ? 100 : size)], name, { type });
	Object.defineProperty(f, 'size', { value: size });
	return f;
}

describe('validateFiles', () => {
	it('accept boş + maxSize 0 → tüm dosyalar geçer', () => {
		const files = [makeFile('a.txt', 100, 'text/plain'), makeFile('b.pdf', 500, 'application/pdf')];
		const r = validateFiles(files, '', 0);
		expect(r.valid.length).toBe(2);
		expect(r.errors).toEqual([]);
	});

	it('maxSize aşan dosya reddedilir', () => {
		const files = [makeFile('big.pdf', 10_000, 'application/pdf')];
		const r = validateFiles(files, '', 5000);
		expect(r.valid.length).toBe(0);
		expect(r.errors.length).toBe(1);
		expect(r.errors[0]).toContain('big.pdf');
		expect(r.errors[0]).toContain('sınır');
	});

	it('uzantı bazlı accept (.pdf, .xlsx) çalışır', () => {
		const files = [
			makeFile('doc.pdf', 100, 'application/pdf'),
			makeFile('sheet.xlsx', 100, 'application/xlsx'),
			makeFile('image.png', 100, 'image/png')
		];
		const r = validateFiles(files, '.pdf,.xlsx', 0);
		expect(r.valid.length).toBe(2);
		expect(r.errors.length).toBe(1);
		expect(r.errors[0]).toContain('image.png');
	});

	it('MIME bazlı accept (image/*) çalışır', () => {
		const files = [
			makeFile('p.png', 100, 'image/png'),
			makeFile('q.jpg', 100, 'image/jpeg'),
			makeFile('d.pdf', 100, 'application/pdf')
		];
		const r = validateFiles(files, 'image/*', 0);
		expect(r.valid.length).toBe(2);
		expect(r.errors.length).toBe(1);
	});

	it('karma accept (.pdf + image/*) çalışır', () => {
		const files = [
			makeFile('d.pdf', 100, 'application/pdf'),
			makeFile('p.png', 100, 'image/png'),
			makeFile('t.txt', 100, 'text/plain')
		];
		const r = validateFiles(files, '.pdf,image/*', 0);
		expect(r.valid.length).toBe(2);
		expect(r.errors.length).toBe(1);
	});

	it('büyük harf uzantı duyarsız', () => {
		const files = [makeFile('DOC.PDF', 100, 'application/pdf')];
		const r = validateFiles(files, '.pdf', 0);
		expect(r.valid.length).toBe(1);
	});
});

describe('FileDropzone bileşeni', () => {
	it('label prop\'unu gösterir', () => {
		render(FileDropzone, {
			label: 'Özel etiket',
			onSelect: () => {}
		});
		expect(screen.getByText('Özel etiket')).toBeTruthy();
	});

	it('hint verilirse gösterir', () => {
		render(FileDropzone, {
			hint: 'PDF/Excel, max 10MB',
			onSelect: () => {}
		});
		expect(screen.getByText('PDF/Excel, max 10MB')).toBeTruthy();
	});

	it('Göz at butonu render eder', () => {
		render(FileDropzone, { onSelect: () => {} });
		expect(screen.getByRole('button', { name: 'Göz at' })).toBeTruthy();
	});

	it('disabled iken input ve buton disabled', () => {
		render(FileDropzone, { disabled: true, onSelect: () => {} });
		const btn = screen.getByRole('button', { name: 'Göz at' }) as HTMLButtonElement;
		expect(btn.disabled).toBe(true);
	});
});
