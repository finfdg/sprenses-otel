import { describe, it, expect } from 'vitest';
import { aggregateRows, AGGREGATE_LABELS, daySourceRank, type CashItem } from './cashflow';

const mk = (name: string, eur: number, native: number, currency = 'TRY'): CashItem => ({
	name,
	amount_eur: eur,
	amount_native: native,
	currency,
});

const mkSrc = (name: string, eur: number, native: number, source_type: string | null, source_id: number | null, currency = 'TRY'): CashItem => ({
	name,
	amount_eur: eur,
	amount_native: native,
	currency,
	source_type,
	source_id,
});

describe('AGGREGATE_LABELS', () => {
	it('yalnız Cari Ödemeleri toplanır; kredi/çek toplanmaz', () => {
		expect(AGGREGATE_LABELS.has('Cari Ödemeleri')).toBe(true);
		expect(AGGREGATE_LABELS.has('Kredi / Leasing Taksitleri')).toBe(false);
		expect(AGGREGATE_LABELS.has('Verilen Çekler')).toBe(false);
	});
});

describe('daySourceRank — gün içi ödeme önceliği (2026-07-07)', () => {
	it('sıra: çek → kredi → KK → vergi → SGK → diğer → fatura → cari', () => {
		const order = ['check', 'credit', 'cc_payment', 'tax', 'sgk', 'salary', 'recurring', 'vendor_payment'];
		const ranks = order.map((s) => daySourceRank(s));
		expect([...ranks].sort((a, b) => a - b)).toEqual(ranks); // verilen dizi artan sıralı
	});

	it('cari ödemeleri her zaman en sonda', () => {
		for (const s of ['check', 'credit', 'cc_payment', 'tax', 'sgk', 'salary', 'withholding', 'rent_expense', 'recurring']) {
			expect(daySourceRank(s)).toBeLessThan(daySourceRank('vendor_payment'));
		}
	});

	it('listelenmeyen türler (maaş, stopaj, kira…) SGK ile fatura arasına düşer', () => {
		for (const s of ['salary', 'withholding', 'rent_expense', 'dividend', 'bilinmeyen']) {
			expect(daySourceRank(s)).toBeGreaterThan(daySourceRank('sgk'));
			expect(daySourceRank(s)).toBeLessThan(daySourceRank('recurring'));
		}
	});

	it('null/undefined kaynak da varsayılan (orta) önceliği alır', () => {
		expect(daySourceRank(null)).toBe(daySourceRank('salary'));
		expect(daySourceRank(undefined)).toBe(daySourceRank('salary'));
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

describe('aggregateRows — members (bekletme kimliği)', () => {
	it('aggregate=false: her satır kendi kaynak kimliğini members olarak taşır', () => {
		const rows = aggregateRows([mkSrc('Çek A', 10, 100, 'check', 5), mkSrc('Çek B', 20, 200, 'check', 6)], false);
		expect(rows[0].members).toEqual([{ source_type: 'check', source_id: 5 }]);
		expect(rows[1].members).toEqual([{ source_type: 'check', source_id: 6 }]);
	});

	it('aggregate=true: toplu satır TÜM üye kimliklerini toplar', () => {
		const rows = aggregateRows([
			mkSrc('OTED', 4, 400, 'vendor_payment', 11),
			mkSrc('OTED', 6, 600, 'vendor_payment', 12),
		], true);
		const oted = rows.find((r) => r.name === 'OTED')!;
		expect(oted.members).toHaveLength(2);
		expect(oted.members).toEqual([
			{ source_type: 'vendor_payment', source_id: 11 },
			{ source_type: 'vendor_payment', source_id: 12 },
		]);
	});

	it('kaynak kimliği olmayan (projeksiyon) kalem members\'a girmez', () => {
		const rows = aggregateRows([mkSrc('Tahmini KK (Tahmini)', 8, 800, null, null)], false);
		expect(rows[0].members).toEqual([]);
	});
});

describe('aggregateRows — bank_name taşıma (banka amblemi, 2026-07-13)', () => {
	it('tekil satır kalemin bankasını aynen taşır; yoksa null', () => {
		const rows = aggregateRows(
			[
				{ name: 'Çek A', amount_eur: 10, amount_native: 500, currency: 'TRY', bank_name: 'Yapı Kredi' },
				{ name: 'Çek B', amount_eur: 5, amount_native: 250, currency: 'TRY' },
			],
			false
		);
		expect(rows[0].bank_name).toBe('Yapı Kredi');
		expect(rows[1].bank_name).toBeNull();
	});

	it('toplu satırda tüm kalemler aynı bankaysa taşınır, karışıksa null', () => {
		const same = aggregateRows(
			[
				{ name: 'Firma X', amount_eur: 10, amount_native: 500, currency: 'TRY', bank_name: 'Halkbank' },
				{ name: 'Firma X', amount_eur: 5, amount_native: 250, currency: 'TRY', bank_name: 'Halkbank' },
			],
			true
		);
		expect(same[0].bank_name).toBe('Halkbank');

		const mixed = aggregateRows(
			[
				{ name: 'Firma Y', amount_eur: 10, amount_native: 500, currency: 'TRY', bank_name: 'Halkbank' },
				{ name: 'Firma Y', amount_eur: 5, amount_native: 250, currency: 'TRY', bank_name: 'VakıfBank' },
			],
			true
		);
		expect(mixed[0].bank_name).toBeNull();
	});
});
