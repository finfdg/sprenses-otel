/**
 * Nakit Akım (T-Hesap) tarih/kategori görünümü satır birleştirme yardımcıları.
 *
 * Cari ödemelerinde aynı firmaya aynı gün birden çok ödeme olabilir → tek "toplu" satır
 * (kullanıcı isteği 2026-07-06: "bir firmanın birden fazla ödemesi varsa toplu göster").
 * Kredi/çek gibi diğer türlerde her ödeme AYRI kalır ("bir bankanın ayrı taksitleri /
 * bir firmanın ayrı çekleri ayrı görünsün").
 */

/**
 * Firma bazında toplanacak (aynı ada birden çok ödeme → tek satır) kategori etiketleri.
 * Backend `SOURCE_LABELS["vendor_payment"]` = "Cari Ödemeleri" (sabit Türkçe etiket; banka
 * "Cari" kategorisinden farklı → çakışmaz). Başka tür de toplanacaksa buraya eklenir.
 */
export const AGGREGATE_LABELS = new Set<string>(['Cari Ödemeleri']);

export type CashItem = { name: string; amount_eur: number; amount_native: number; currency: string };

export type CashRow = {
	name: string;
	amount_eur: number;
	amount_native: number;
	/** Tekil para birimi; toplu satırda birden çok para birimi karışıksa null (→ çağıran EUR gösterir). */
	currency: string | null;
	/** Bu satıra kaç kalem katıldı (>1 ise "N ödeme" rozeti gösterilir). */
	count: number;
};

/**
 * Kalemleri gösterim satırlarına dönüştür.
 * @param aggregate true → aynı `name` (firma) tek satırda toplanır (EUR azalan sıralı, native
 *   yalnız para birimi tekse taşınır); false → her kalem ayrı (giriş sırası korunur).
 */
export function aggregateRows(items: CashItem[], aggregate: boolean): CashRow[] {
	if (!aggregate) {
		return items.map((it) => ({
			name: it.name,
			amount_eur: it.amount_eur,
			amount_native: it.amount_native,
			currency: it.currency,
			count: 1,
		}));
	}
	const map = new Map<string, { name: string; eur: number; native: number; currencies: Set<string>; count: number }>();
	const order: string[] = [];
	for (const it of items) {
		let r = map.get(it.name);
		if (!r) {
			r = { name: it.name, eur: 0, native: 0, currencies: new Set<string>(), count: 0 };
			map.set(it.name, r);
			order.push(it.name);
		}
		r.eur += it.amount_eur;
		r.native += it.amount_native;
		r.currencies.add(it.currency);
		r.count++;
	}
	return order
		.map((n) => map.get(n)!)
		.sort((a, b) => b.eur - a.eur)
		.map((r) => ({
			name: r.name,
			amount_eur: r.eur,
			amount_native: r.native,
			currency: r.currencies.size === 1 ? [...r.currencies][0] : null,
			count: r.count,
		}));
}
