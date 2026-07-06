import { describe, it, expect } from 'vitest';
import { aggregateRows, AGGREGATE_LABELS, type CashItem } from './cashflow';

const mk = (name: string, eur: number, native: number, currency = 'TRY'): CashItem => ({
	name,
	amount_eur: eur,
	amount_native: native,
	currency,
});

describe('AGGREGATE_LABELS', () => {
	it('yalnız Cari Ödemeleri toplanır; kredi/çek toplanmaz', () => {
		expect(AGGREGATE_LABELS.has('Cari Ödemeleri')).toBe(true);
		expect(AGGREGATE_LABELS.has('Kredi / Leasing Taksitleri')).toBe(false);
		expect(AGGREGATE_LABELS.has('Verilen Çekler')).toBe(false);
	});
});

describe('aggregateRows — aggregate=false (kredi/çek: her kalem ayrı)', () => {
	it('kalemleri giriş sırasında, count=1 ile aynen döner', () => {
		const items = [mk('Taksit #4', 100, 4100), mk('Taksit #5', 90, 3700)];
		const rows = aggregateRows(items, false);
		expect(rows).toHaveLength(2);
		expect(rows.map((r) => r.name)).toEqual(['Taksit #4', 'Taksit #5']);
		expect(rows.every((r) => r.count === 1)).toBe(true);
		expect(rows[0].currency).toBe('TRY');
		expect(rows[0].amount_native).toBe(4100);
	});

	it('aynı ad tekrarı bile ayrı satır kalır (bir bankanın ayrı taksitleri)', () => {
		const items = [mk('VakıfBank leasing', 50, 2000), mk('VakıfBank leasing', 30, 1200)];
		const rows = aggregateRows(items, false);
		expect(rows).toHaveLength(2);
	});
});

describe('aggregateRows — aggregate=true (cari: firma bazında toplu)', () => {
	it('aynı firmanın çok ödemesi tek satırda toplanır (native + eur + count)', () => {
		const items = [
			mk('OTED GIDA', 4, 4242),
			mk('OTED GIDA', 10, 10706),
			mk('OTED GIDA', 88, 88350),
			mk('TALYA', 210, 210000),
		];
		const rows = aggregateRows(items, true);
		const oted = rows.find((r) => r.name === 'OTED GIDA')!;
		expect(oted.count).toBe(3);
		expect(oted.amount_native).toBe(4242 + 10706 + 88350);
		expect(oted.amount_eur).toBe(102);
		expect(oted.currency).toBe('TRY');
		const talya = rows.find((r) => r.name === 'TALYA')!;
		expect(talya.count).toBe(1);
	});

	it('EUR azalan sıralanır', () => {
		const items = [mk('Küçük', 5, 200), mk('Büyük', 500, 20000), mk('Orta', 50, 2000)];
		const rows = aggregateRows(items, true);
		expect(rows.map((r) => r.name)).toEqual(['Büyük', 'Orta', 'Küçük']);
	});

	it('firma karışık para birimliyse currency=null (çağıran EUR gösterir)', () => {
		const items = [mk('Marmara', 19, 19000, 'EUR'), mk('Marmara', 11, 440000, 'TRY')];
		const rows = aggregateRows(items, true);
		const m = rows.find((r) => r.name === 'Marmara')!;
		expect(m.count).toBe(2);
		expect(m.currency).toBeNull();
		expect(m.amount_eur).toBe(30);
	});

	it('tek para birimliyse currency korunur', () => {
		const rows = aggregateRows([mk('Deniz', 11, 11500, 'EUR'), mk('Deniz', 5, 5000, 'EUR')], true);
		expect(rows[0].currency).toBe('EUR');
		expect(rows[0].amount_native).toBe(16500);
	});

	it('boş liste → boş dizi', () => {
		expect(aggregateRows([], true)).toEqual([]);
	});
});
