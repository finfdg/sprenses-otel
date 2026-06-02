/**
 * EmptyState bileşeni testleri — render koşullu mantığı + callback davranışı.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import EmptyState from './EmptyState.svelte';

afterEach(() => cleanup());

describe('EmptyState', () => {
	it('varsayılan başlığı "Henüz kayıt yok" olarak gösterir', () => {
		render(EmptyState, {});
		expect(screen.getByText('Henüz kayıt yok')).toBeTruthy();
	});

	it('özel başlık prop\'unu gösterir', () => {
		render(EmptyState, { title: 'Aramaya uygun kayıt bulunamadı' });
		expect(screen.getByText('Aramaya uygun kayıt bulunamadı')).toBeTruthy();
	});

	it('açıklama verilirse gösterir', () => {
		render(EmptyState, {
			title: 'Başlık',
			description: 'Yardımcı açıklama metni'
		});
		expect(screen.getByText('Yardımcı açıklama metni')).toBeTruthy();
	});

	it('açıklama verilmezse paragraf render edilmez', () => {
		const { container } = render(EmptyState, { title: 'Başlık' });
		expect(container.querySelector('p')).toBeNull();
	});

	it('ctaText ve onCta ikisi birden verilirse buton gösterilir', () => {
		render(EmptyState, {
			title: 'Boş',
			ctaText: 'Yeni Ekle',
			onCta: () => {}
		});
		expect(screen.getByRole('button', { name: 'Yeni Ekle' })).toBeTruthy();
	});

	it('sadece ctaText verilirse (onCta yoksa) buton gösterilmez', () => {
		render(EmptyState, { title: 'Boş', ctaText: 'Yeni Ekle' });
		expect(screen.queryByRole('button')).toBeNull();
	});

	it('sadece onCta verilirse (ctaText yoksa) buton gösterilmez', () => {
		render(EmptyState, { title: 'Boş', onCta: () => {} });
		expect(screen.queryByRole('button')).toBeNull();
	});

	it('CTA butonuna tıklayınca onCta callback çağrılır', async () => {
		const handler = vi.fn();
		render(EmptyState, {
			title: 'Boş',
			ctaText: 'Yeni Ekle',
			onCta: handler
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Yeni Ekle' }));
		expect(handler).toHaveBeenCalledTimes(1);
	});

	it('beyaz kart stili uygular (bg-white, border, rounded)', () => {
		const { container } = render(EmptyState, { title: 'T' });
		const card = container.querySelector('div');
		expect(card?.className).toContain('bg-white');
		expect(card?.className).toContain('border');
		expect(card?.className).toContain('rounded-2xl');
	});
});
