/** Tüm ödeme yöntemleri — badge gösteriminde kullanılır */
export const PAYMENT_METHODS: Record<string, { label: string; bg: string; text: string; border: string }> = {
	havale_eft:      { label: 'Havale/EFT',      bg: 'bg-blue-50',    text: 'text-blue-700',    border: 'border-blue-200' },
	fast:            { label: 'FAST',             bg: 'bg-violet-50',  text: 'text-violet-700',  border: 'border-violet-200' },
	virman:          { label: 'Virman',           bg: 'bg-teal-50',    text: 'text-teal-700',    border: 'border-teal-200' },
	cek:             { label: 'Çek',              bg: 'bg-orange-50',  text: 'text-orange-700',  border: 'border-orange-200' },
	kredi_karti:     { label: 'Kredi Kartı',      bg: 'bg-pink-50',    text: 'text-pink-700',    border: 'border-pink-200' },
	otomatik_odeme:  { label: 'Oto. Ödeme',       bg: 'bg-cyan-50',    text: 'text-cyan-700',    border: 'border-cyan-200' },
	nakit:           { label: 'Nakit',            bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
	kredi:           { label: 'Kredi',            bg: 'bg-amber-50',   text: 'text-amber-700',   border: 'border-amber-200' },
	cari:            { label: 'Cari Ödeme',        bg: 'bg-purple-50',  text: 'text-purple-700',  border: 'border-purple-200' },
	senet:           { label: 'Senet',            bg: 'bg-rose-50',    text: 'text-rose-700',    border: 'border-rose-200' },
	diger:           { label: 'Diğer',            bg: 'bg-gray-50',    text: 'text-gray-600',    border: 'border-gray-200' },
};

/** Etiketleme sırasında seçilecek ödeme yöntemleri */
export const SELECTABLE_PAYMENT_METHODS = [
	{ code: 'havale_eft',  label: 'Havale/EFT',  icon: '🏦' },
	{ code: 'kredi_karti', label: 'Kredi Kartı', icon: '💳' },
	{ code: 'nakit',       label: 'Nakit',       icon: '💵' },
	{ code: 'cek',         label: 'Çek',         icon: '📄' },
	{ code: 'senet',       label: 'Senet',       icon: '📜' },
];

/** Ödeme yöntemi seçimi gösterilecek kategori adları */
export const CATEGORIES_WITH_PAYMENT_METHOD = new Set([
	'Cari', 'Personel', 'Vergi/SGK', 'Kira', 'Elektrik Faturası', 'Su Faturası', 'Aidat', 'İade',
]);

/** Ödeme yöntemi kodundan bilgi al (fallback: diger) */
export function getPaymentMethod(code: string | null | undefined) {
	if (!code) return null;
	return PAYMENT_METHODS[code] ?? PAYMENT_METHODS.diger;
}
