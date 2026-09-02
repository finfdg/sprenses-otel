/**
 * "Acente Bazında Kişi Başı Fiyat" kartı — ay değişince satır metinleri tazelenir (regresyon,
 * canlı bulgu 2026-09-02: ALLTOURS Ekim→Kasım geçişinde çubuk güncellenip fiyat metni 59,24'te
 * kalmıştı). Gerçek bileşen, API ve store'lar taklit edilerek jsdom'da çalıştırılır.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ReservationsPanel from './ReservationsPanel.svelte';

const kpi = {
	total_rez: 10, total_eur: 1000, total_room_nights: 20, total_guest_nights: 40, total_pax: 40,
	total_adult: 30, total_child_paid: 5, total_child_free: 5, total_baby: 0,
	adr: 50, avg_los: 2, definite_count: 10, option_count: 0,
	total_capacity: 100, date_range_days: 365, occupancy_pct: 10,
};
const summary = {
	kpi, monthly: [], by_agency: [], by_nation: [], by_room_type: [], by_board: [], pickup: [],
	los_buckets: [], lead_time: { avg: 10, median: 8, min: 1, max: 30 },
};
const row = (key: string, name: string, pp: number, pax: number) => ({
	key, name, color: '#123456', is_group: true, member_count: 1,
	pp_night: pp, pax_nights: pax, revenue: Math.round(pp * pax * 100) / 100, rez: 3, prev_pp_night: null,
});
const bucket = (agencies: any[]) => ({
	agencies, pp_night: 50, pax_nights: agencies.reduce((s, a) => s + a.pax_nights, 0),
	revenue: agencies.reduce((s, a) => s + a.revenue, 0), rez: 9, agency_count: agencies.length, prev_pp_night: null,
});
const months = Array.from({ length: 12 }, (_, i) => ({ month: i + 1, ...bucket([]) }));
months[9] = { month: 10, ...bucket([
	row('g:8', 'AKAY', 102.82, 43), row('g:14', 'DERTOUR', 89.06, 6), row('g:18', 'ROKET', 88.2, 6),
	row('g:6', 'MUNFERIT', 82.79, 54), row('g:9', 'FUN & SUN', 78.84, 128), row('g:7', 'LIBERO', 78.4, 16),
	row('g:10', 'W2M', 71.93, 326), row('g:13', 'NORDIC', 65.66, 374), row('g:11', 'OTS', 64.39, 52),
	row('g:4', 'ODEON', 62.88, 802), row('g:12', 'PEGAS', 60.77, 218), row('g:1', 'ALLTOURS', 59.24, 7511),
]) };
months[10] = { month: 11, ...bucket([
	row('g:6', 'MUNFERIT', 84.38, 9), row('g:4', 'ODEON', 62.61, 66), row('g:10', 'W2M', 45.04, 766),
	row('g:8', 'AKAY', 41.71, 38), row('g:1', 'ALLTOURS', 34.79, 6413),
]) };
const ppData = { year: 2026, prev_year: 2025, today: '2026-09-02', months, year_totals: bucket([]) };

vi.mock('$lib/api', () => ({
	api: {
		get: vi.fn(async (url: string) => {
			if (url.includes('/agency-pp-prices')) return JSON.parse(JSON.stringify(ppData));
			if (url.includes('/reservations/summary')) return JSON.parse(JSON.stringify(summary));
			if (url.includes('/reservations/uploads')) return [];
			if (url.includes('/reservations/years')) return { years: [2026, 2025] };
			if (url.includes('/agency-groups')) return [];
			return {};
		}),
		post: vi.fn(async () => ({})), patch: vi.fn(async () => ({})), delete: vi.fn(async () => undefined),
		upload: vi.fn(async () => ({})),
	},
	ApiError: class ApiError extends Error {},
}));
vi.mock('$lib/stores/auth.svelte', () => ({ hasPermission: () => true }));
vi.mock('$lib/stores/websocket.svelte', () => ({ onWsEvent: () => () => {} }));
vi.mock('$lib/stores/toast.svelte', () => ({ showToast: vi.fn() }));

describe('Acente Bazında Kişi Başı Fiyat kartı', () => {
	it('Ekim → Kasım geçişinde aynı acentenin fiyat metni yeni aya göre güncellenir', { timeout: 60000 }, async () => {
		render(ReservationsPanel);
		try {
			await waitFor(() => expect(screen.getByText('Acente Bazında Kişi Başı Fiyat')).toBeTruthy(), { timeout: 8000 });
		} catch (e) {
			console.log('BODY:', document.body.textContent?.replace(/\s+/g, ' ').slice(0, 1200));
			throw e;
		}

		await fireEvent.click(screen.getByRole('tab', { name: 'Eki' }));
		await waitFor(() => expect(screen.getByTitle('ALLTOURS')).toBeTruthy());
		const octRow = screen.getByTitle('ALLTOURS').closest('li')!;
		expect(octRow.textContent).toContain('59,24 €');
		expect(screen.getAllByTitle(/./).filter((el) => el.closest('ol')).length).toBeGreaterThanOrEqual(12);

		await fireEvent.click(screen.getByRole('tab', { name: 'Kas' }));
		await waitFor(() => {
			const novRow = screen.getByTitle('ALLTOURS').closest('li')!;
			expect(novRow.textContent).toContain('6.413 kişi-gece');
		});
		const novRow = screen.getByTitle('ALLTOURS').closest('li')!;
		expect(novRow.textContent).toContain('34,79 €');
		expect(novRow.textContent).not.toContain('59,24');
		expect(screen.getByTitle('MUNFERIT').closest('li')!.textContent).toContain('84,38 €');
	});
});
