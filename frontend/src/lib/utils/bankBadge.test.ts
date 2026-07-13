import { describe, expect, it } from 'vitest';
import { bankBadge } from './bankBadge';

describe('bankBadge', () => {
	it('boş/null banka adında null döner (rozet çizilmez)', () => {
		expect(bankBadge(null)).toBeNull();
		expect(bankBadge(undefined)).toBeNull();
		expect(bankBadge('')).toBeNull();
		expect(bankBadge('   ')).toBeNull();
	});

	it('bilinen bankaları marka rengiyle çözer', () => {
		expect(bankBadge('Yapı Kredi')).toEqual({ code: 'YK', bg: '#00296B', fg: '#FFFFFF' });
		expect(bankBadge('VakıfBank')).toEqual({ code: 'VB', bg: '#FDB913', fg: '#1F2937' });
		expect(bankBadge('Halkbank')).toEqual({ code: 'HB', bg: '#005EB8', fg: '#FFFFFF' });
		expect(bankBadge('QNB')).toEqual({ code: 'QNB', bg: '#5F259F', fg: '#FFFFFF' });
		expect(bankBadge('Garanti BBVA')?.code).toBe('G');
		expect(bankBadge('TEB')?.code).toBe('TEB');
		expect(bankBadge('Türk Eximbank')?.code).toBe('EX');
		expect(bankBadge('Ziraat Bankası')?.code).toBe('ZB');
	});

	it('Türkçe karakter ve büyük/küçük harf duyarsızdır', () => {
		expect(bankBadge('YAPI KREDİ')?.code).toBe('YK');
		expect(bankBadge('vakıfbank')?.code).toBe('VB');
	});

	it('ardışık boşlukları daraltır — canlı "YAPI  KREDİ" (çift boşluk) markaya çözülür', () => {
		expect(bankBadge('YAPI  KREDİ')).toEqual({ code: 'YK', bg: '#00296B', fg: '#FFFFFF' });
		expect(bankBadge('  Halkbank  ')?.code).toBe('HB');
	});

	it('bilinmeyen banka baş harfleriyle gri rozete düşer', () => {
		const b = bankBadge('Örnek Banka');
		expect(b).toEqual({ code: 'ÖB', bg: '#6B7280', fg: '#FFFFFF' });
		expect(bankBadge('Monobanka')?.code).toBe('MO');
	});
});
