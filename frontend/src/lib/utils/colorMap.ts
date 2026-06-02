/**
 * Kategori renk haritası — tüm finance bileşenlerinde ortak kullanılır.
 * Tailwind sınıfları statik olmalıdır (template literal ile oluşturulmaz).
 */

export interface ColorClasses {
	bg: string;
	text: string;
	border: string;
	bgActive: string;
}

export const categoryColorMap: Record<string, ColorClasses> = {
	purple: { bg: 'bg-purple-100', text: 'text-purple-700', border: 'border-purple-300', bgActive: 'bg-purple-200' },
	teal:   { bg: 'bg-teal-100',   text: 'text-teal-700',   border: 'border-teal-300',   bgActive: 'bg-teal-200' },
	orange: { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-300', bgActive: 'bg-orange-200' },
	cyan:   { bg: 'bg-cyan-100',   text: 'text-cyan-700',   border: 'border-cyan-300',   bgActive: 'bg-cyan-200' },
	pink:   { bg: 'bg-pink-100',   text: 'text-pink-700',   border: 'border-pink-300',   bgActive: 'bg-pink-200' },
	red:    { bg: 'bg-red-100',    text: 'text-red-700',    border: 'border-red-300',    bgActive: 'bg-red-200' },
	amber:  { bg: 'bg-amber-100',  text: 'text-amber-700',  border: 'border-amber-300',  bgActive: 'bg-amber-200' },
	indigo: { bg: 'bg-indigo-100', text: 'text-indigo-700', border: 'border-indigo-300', bgActive: 'bg-indigo-200' },
	gray:   { bg: 'bg-gray-100',   text: 'text-gray-700',   border: 'border-gray-300',   bgActive: 'bg-gray-200' },
};

/** Filtre barında pill'ler için daha açık tonlar */
export const filterColorMap: Record<string, ColorClasses> = {
	purple: { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200', bgActive: 'bg-purple-100' },
	teal:   { bg: 'bg-teal-50',   text: 'text-teal-700',   border: 'border-teal-200',   bgActive: 'bg-teal-100' },
	orange: { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200', bgActive: 'bg-orange-100' },
	cyan:   { bg: 'bg-cyan-50',   text: 'text-cyan-700',   border: 'border-cyan-200',   bgActive: 'bg-cyan-100' },
	pink:   { bg: 'bg-pink-50',   text: 'text-pink-700',   border: 'border-pink-200',   bgActive: 'bg-pink-100' },
	red:    { bg: 'bg-red-50',    text: 'text-red-700',    border: 'border-red-200',    bgActive: 'bg-red-100' },
	amber:  { bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200',  bgActive: 'bg-amber-100' },
	indigo: { bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200', bgActive: 'bg-indigo-100' },
	gray:   { bg: 'bg-gray-50',   text: 'text-gray-700',   border: 'border-gray-200',   bgActive: 'bg-gray-100' },
};

/** Kullanılabilir renk isimleri (yeni kategori oluşturma renk seçicisi) */
export const availableColors = Object.keys(categoryColorMap);

/** Güvenli renk çözümleme — bilinmeyen renk gelirse gray döner */
export function getColor(color: string | null | undefined, map = categoryColorMap): ColorClasses {
	return map[color ?? 'gray'] ?? map.gray;
}
