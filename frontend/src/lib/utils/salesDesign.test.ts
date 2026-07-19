import { describe, expect, it } from 'vitest';
import {
	eurCompact,
	monthKeyLabel,
	rollupAgencyGroups,
	spreadStayMonths,
	stayRangeLabel,
	trInt,
} from './salesDesign';

describe('trInt', () => {
	it('TR binlik ayraçlı tam sayı üretir', () => {
		expect(trInt(12345)).toBe('12.345');
		expect(trInt(0)).toBe('0');
		expect(trInt(NaN as unknown as number)).toBe('0');
	});
});

describe('eurCompact', () => {
	it('milyonları "M €" ile kısaltır (virgüllü)', () => {
		expect(eurCompact(1_234_567)).toBe('1,23 M €');
	});
	it('binleri "K €" ile kısaltır', () => {
		expect(eurCompact(45_600)).toBe('45,6 K €');
	});
	it('binin altını tam sayı bırakır', () => {
		expect(eurCompact(950)).toBe('950 €');
		expect(eurCompact(0)).toBe('0 €');
	});
	it('negatif değerde işareti korur', () => {
		expect(eurCompact(-2_500_000)).toBe('-2,50 M €');
	});
});

describe('monthKeyLabel', () => {
	it("'YYYY-MM' anahtarını Türkçe ay etiketine çevirir", () => {
		expect(monthKeyLabel('2026-03')).toBe('Mar 2026');
		expect(monthKeyLabel('2025-12')).toBe('Ara 2025');
	});
	it('bozuk/boş anahtarda tire döner', () => {
		expect(monthKeyLabel(null)).toBe('—');
		expect(monthKeyLabel('2026')).toBe('—');
		expect(monthKeyLabel('2026-99')).toBe('—');
	});
});

describe('stayRangeLabel', () => {
	it('aynı ay içindeki konaklamayı tek ay adıyla yazar', () => {
		expect(stayRangeLabel('2026-07-05', '2026-07-12')).toBe('5–12 Tem');
	});
	it('ay aşan konaklamada iki ay adı yazar', () => {
		expect(stayRangeLabel('2026-07-28', '2026-08-04')).toBe('28 Tem – 4 Ağu');
	});
	it('eksik tarihte tire döner', () => {
		expect(stayRangeLabel(null, '2026-08-04')).toBe('—');
	});
});

describe('rollupAgencyGroups', () => {
	const byAgency = [
		{ name: 'ALLTOURS D', eur: 500, rez: 5, pct: 50 },
		{ name: 'BYEBYE D', eur: 300, rez: 3, pct: 30 },
		{ name: 'PEGAS', eur: 200, rez: 2, pct: 20 },
	];
	const groups = [{ name: 'ALLTOURS', members: ['alltours d', 'BYEBYE D'] }];

	it('üyeleri grup satırında toplar, gruplanmamışı müstakil bırakır', () => {
		const rows = rollupAgencyGroups(byAgency, groups);
		expect(rows).toHaveLength(2);
		expect(rows[0]).toMatchObject({ name: 'ALLTOURS', isGroup: true, eur: 800, rez: 8, pct: 80 });
		expect(rows[0].members.map((m) => m.name)).toEqual(['ALLTOURS D', 'BYEBYE D']);
		expect(rows[1]).toMatchObject({ name: 'PEGAS', isGroup: false, eur: 200 });
	});

	it('üye adı eşleşmesi büyük/küçük harf ve kenar boşluğuna duyarsızdır', () => {
		const rows = rollupAgencyGroups(
			[{ name: '  byebye d ', eur: 100, rez: 1, pct: 100 }],
			groups,
		);
		expect(rows[0].isGroup).toBe(true);
		expect(rows[0].name).toBe('ALLTOURS');
	});

	it('ciroya göre azalan sıralar', () => {
		const rows = rollupAgencyGroups(
			[
				{ name: 'KÜÇÜK', eur: 10, rez: 1, pct: 5 },
				{ name: 'BÜYÜK', eur: 90, rez: 2, pct: 95 },
			],
			[],
		);
		expect(rows.map((r) => r.name)).toEqual(['BÜYÜK', 'KÜÇÜK']);
	});
});

describe('spreadStayMonths', () => {
	it('konaklama gecelerini aylara yayar (checkout günü hariç)', () => {
		const eff = spreadStayMonths([
			{ checkin_date: '2026-07-30', checkout_date: '2026-08-02', is_cancelled: false },
		]);
		// 30 Tem, 31 Tem → Temmuz 2 gece · 1 Ağu → Ağustos 1 gece
		expect(eff).toEqual([
			{ key: '2026-07', y: 2026, m: 7, gelen: 2, iptal: 0 },
			{ key: '2026-08', y: 2026, m: 8, gelen: 1, iptal: 0 },
		]);
	});

	it('iptalleri ayrı sayaçta toplar ve ay sırasına dizer', () => {
		const eff = spreadStayMonths([
			{ checkin_date: '2026-09-01', checkout_date: '2026-09-03', is_cancelled: true },
			{ checkin_date: '2026-08-10', checkout_date: '2026-08-12', is_cancelled: false },
		]);
		expect(eff.map((e) => e.key)).toEqual(['2026-08', '2026-09']);
		expect(eff[1]).toMatchObject({ gelen: 0, iptal: 2 });
	});

	it('geçersiz/ters tarihli kayıtları atlar', () => {
		expect(
			spreadStayMonths([
				{ checkin_date: null, checkout_date: '2026-08-02' },
				{ checkin_date: '2026-08-05', checkout_date: '2026-08-05' },
			]),
		).toEqual([]);
	});
});
