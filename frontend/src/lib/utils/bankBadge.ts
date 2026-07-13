/**
 * Banka amblemi (satır başı rozeti) — banka adı → kısaltma + marka rengi.
 *
 * Gerçek logo varlığı bulundurmuyoruz; amblem = marka renkli yuvarlak rozet içinde
 * kısaltma (T-Hesap satırları 12px yoğunluğunda — küçük ve okunur tek doğru biçim).
 * Renkler bankaların kurumsal ana renklerinin yaklaşık hex karşılıklarıdır; tema
 * token'larından bağımsız (markayı temsil eder, inline style ile uygulanır).
 * Tüm bg/fg çiftleri WCAG AA (≥4.5:1) sağlar — marka tonu AA'yı geçmiyorsa
 * koyulaştırılmış varyant kullanılır (TEB, DenizBank).
 * Bilinmeyen banka → baş harfler + nötr gri.
 */

export interface BankBadge {
	/** Rozet içi kısaltma (1-3 karakter) */
	code: string;
	/** Arka plan rengi (hex) */
	bg: string;
	/** Metin rengi (hex) */
	fg: string;
}

/** Anahtar: normalize edilmiş banka adında aranan parça (ilk eşleşen kazanır). */
const BANK_BADGES: { match: string; badge: BankBadge }[] = [
	{ match: 'yapi kredi', badge: { code: 'YK', bg: '#00296B', fg: '#FFFFFF' } },
	{ match: 'yapikredi', badge: { code: 'YK', bg: '#00296B', fg: '#FFFFFF' } },
	{ match: 'vakif', badge: { code: 'VB', bg: '#FDB913', fg: '#1F2937' } },
	{ match: 'halk', badge: { code: 'HB', bg: '#005EB8', fg: '#FFFFFF' } },
	{ match: 'qnb', badge: { code: 'QNB', bg: '#5F259F', fg: '#FFFFFF' } },
	{ match: 'garanti', badge: { code: 'G', bg: '#007A33', fg: '#FFFFFF' } },
	{ match: 'teb', badge: { code: 'TEB', bg: '#2E7D32', fg: '#FFFFFF' } },
	{ match: 'eximbank', badge: { code: 'EX', bg: '#0F4C81', fg: '#FFFFFF' } },
	{ match: 'ziraat', badge: { code: 'ZB', bg: '#E4002B', fg: '#FFFFFF' } },
	{ match: 'akbank', badge: { code: 'AK', bg: '#E30613', fg: '#FFFFFF' } },
	{ match: 'is bank', badge: { code: 'İŞ', bg: '#205BAA', fg: '#FFFFFF' } },
	{ match: 'isbank', badge: { code: 'İŞ', bg: '#205BAA', fg: '#FFFFFF' } },
	{ match: 'deniz', badge: { code: 'DZ', bg: '#00639B', fg: '#FFFFFF' } },
	{ match: 'kuveyt', badge: { code: 'KT', bg: '#00885A', fg: '#FFFFFF' } },
	{ match: 'finansbank', badge: { code: 'FB', bg: '#5F259F', fg: '#FFFFFF' } },
];

const TR_MAP: Record<string, string> = {
	ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u',
	Ç: 'c', Ğ: 'g', İ: 'i', I: 'i', Ö: 'o', Ş: 's', Ü: 'u',
};

function normalize(name: string): string {
	return name
		.split('')
		.map((ch) => TR_MAP[ch] ?? ch.toLowerCase())
		.join('')
		.replace(/\s+/g, ' ')
		.trim();
}

/** Bilinmeyen banka için baş harflerden kısaltma üret (en çok 2 karakter). */
function initials(name: string): string {
	const words = name.trim().split(/\s+/).filter(Boolean);
	if (words.length === 0) return '?';
	if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
	return (words[0][0] + words[1][0]).toUpperCase();
}

/**
 * Banka adından amblem çöz; ad boş/null ise null (rozet çizilmez).
 */
export function bankBadge(bankName: string | null | undefined): BankBadge | null {
	if (!bankName || !bankName.trim()) return null;
	const norm = normalize(bankName);
	for (const { match, badge } of BANK_BADGES) {
		if (norm.includes(match)) return badge;
	}
	return { code: initials(bankName), bg: '#6B7280', fg: '#FFFFFF' };
}
