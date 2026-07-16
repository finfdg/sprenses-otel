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

/**
 * Gün içi ödeme grubu öncelik sırası (kullanıcı kararı 2026-07-07): aynı güne denk gelen
 * ödemelerde önce çekler, sonra kredi/leasing taksitleri, KK borcu, vergi, SGK,
 * [listelenmeyen türler: maaş, stopaj, kira, temettü…], fatura (düzenli ödemeler) ve
 * EN SONDA cari ödemeleri. T-Hesap tarih görünümü bu sırayı hem render'da hem "ilk açık
 * ödeme" nakit yürüyüşünde kullanır → gün içi nakit önce yüksek öncelikli ödemelere ayrılır.
 */
const DAY_SOURCE_RANK: Record<string, number> = {
	check: 10,
	credit: 20,
	cc_payment: 25,
	tax: 30,
	sgk: 40,
	recurring: 60,
	vendor_payment: 70,
};
const DAY_SOURCE_DEFAULT_RANK = 50;

/** Gün içi grup önceliği — haritada olmayan türler (maaş, stopaj, kira…) SGK ile fatura arasına (50) düşer. */
export function daySourceRank(sourceType?: string | null): number {
	if (!sourceType) return DAY_SOURCE_DEFAULT_RANK;
	return DAY_SOURCE_RANK[sourceType] ?? DAY_SOURCE_DEFAULT_RANK;
}

export type SourceRef = { source_type: string; source_id: number };
export type CashItem = {
	name: string;
	amount_eur: number;
	amount_native: number;
	currency: string;
	/** Bekletme kimliği (varsa) — projeksiyon/sentetik kalemlerde null. */
	source_type?: string | null;
	source_id?: number | null;
	/** Hareketin bankası (varsa) — satır başı banka amblemi için. */
	bank_name?: string | null;
};

export type CashRow = {
	name: string;
	amount_eur: number;
	amount_native: number;
	/** Tekil para birimi; toplu satırda birden çok para birimi karışıksa null (→ çağıran EUR gösterir). */
	currency: string | null;
	/** Bu satıra kaç kalem katıldı (>1 ise "N ödeme" rozeti gösterilir). */
	count: number;
	/** Bu satırı oluşturan bekletilebilir kaynak kalemleri (toplu satırda tümü) — hold-batch için. */
	members: SourceRef[];
	/** Tekil banka adı; toplu satırda bankalar karışıksa/boşsa null (→ amblem çizilmez). */
	bank_name: string | null;
};

/** Bir kalemin bekletilebilir kaynak kimliğini döner (yoksa null). */
function _sourceRef(it: CashItem): SourceRef | null {
	if (it.source_type && it.source_id != null) return { source_type: it.source_type, source_id: it.source_id };
	return null;
}

/**
 * Kalemleri gösterim satırlarına dönüştür.
 * @param aggregate true → aynı `name` (firma) tek satırda toplanır (EUR azalan sıralı, native
 *   yalnız para birimi tekse taşınır); false → her kalem ayrı (giriş sırası korunur).
 */
export function aggregateRows(items: CashItem[], aggregate: boolean): CashRow[] {
	if (!aggregate) {
		return items.map((it) => {
			const ref = _sourceRef(it);
			return {
				name: it.name,
				amount_eur: it.amount_eur,
				amount_native: it.amount_native,
				currency: it.currency,
				count: 1,
				members: ref ? [ref] : [],
				bank_name: it.bank_name ?? null,
			};
		});
	}
	const map = new Map<string, { name: string; eur: number; native: number; currencies: Set<string>; count: number; members: SourceRef[]; banks: Set<string | null> }>();
	const order: string[] = [];
	for (const it of items) {
		let r = map.get(it.name);
		if (!r) {
			r = { name: it.name, eur: 0, native: 0, currencies: new Set<string>(), count: 0, members: [], banks: new Set<string | null>() };
			map.set(it.name, r);
			order.push(it.name);
		}
		r.eur += it.amount_eur;
		r.native += it.amount_native;
		r.currencies.add(it.currency);
		r.count++;
		r.banks.add(it.bank_name ?? null);
		const ref = _sourceRef(it);
		if (ref) r.members.push(ref);
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
			members: r.members,
			bank_name: r.banks.size === 1 ? [...r.banks][0] : null,
		}));
}

// ── "Nakit buraya yetmiyor" yürüyüşü (T-Hesap tarih görünümü, ÇIKIŞ sütunu) ──

/** Tipping yürüyüşü için gerekli minimal gün yapısı (dateBuckets çıktısıyla yapısal uyumlu). */
export type TippingDay = { date: string; cats: { label: string; rows: { amount_eur: number }[] }[] };
export type TippingHit = { date: string; catLabel: string; rowIdx: number };

/**
 * BUGÜNKÜ SAF banka nakdinden (`startCash` = runway `start_eur` = `_compute_start_eur`) başlayıp
 * bekleyen çıkışları kronolojik yürütür; bakiyeyi ilk kez negatife düşüren ödemenin konumunu döner
 * (o TEK satır kırmızı "nakit yetmiyor" işaretlenir). Her günün bekleyen girişi o günün ödemelerinden
 * ÖNCE nakde eklenir.
 *
 * KRİTİK — `startCash` SAF banka nakdi olmalı (bugünkü bekleyen ödemeler DÜŞÜLMEMİŞ). Eskiden
 * `eur_balances.total_balance_eur` kullanılıyordu; o değer bugün son banka ekstresinden sonraysa
 * bugünün ödenmemiş ödemesini ZATEN düşmüş oluyordu → yürüyüş aynı ödemeyi tekrar düşünce ödeme
 * ÇİFT sayılıp erken "yetmiyor" damgası basıyordu (kullanıcı bulgusu 2026-07-16). Saf nakitten
 * başlayınca her ödeme tam bir kez düşülür ve son-of-bugün bakiyesi projeksiyon eğrisiyle hizalanır.
 */
export function firstTippingRow(
	startCash: number,
	inflowByDate: Map<string, number>,
	days: TippingDay[],
): TippingHit | null {
	let avail = startCash;
	for (const day of days) {
		avail += inflowByDate.get(day.date) ?? 0;
		for (const cat of day.cats) {
			for (let i = 0; i < cat.rows.length; i++) {
				avail -= cat.rows[i].amount_eur;
				if (avail < 0) return { date: day.date, catLabel: cat.label, rowIdx: i };
			}
		}
	}
	return null; // dönem boyunca nakit yetiyor
}
