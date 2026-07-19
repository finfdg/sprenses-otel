// Acente Mahsup & Nakit Akım — basit tasarım (2026-07-19) paylaşılan saf yardımcıları.
// Tasarım kaynağı: repo yedeğindeki "Acente Mahsup ve Nakit Akım.zip" (finfdg yüklemesi).
// Panel bileşenleri (Occupancy/AgencyDistribution/DailyMoves/SalesCashFlow) ortak kullanır.

// ── Type / interface tanımları ───────────────────────────
export interface AgencyShareRow {
	name: string;
	eur: number;
	rez: number;
	pct: number;
}

export interface AgencyGroupRollup {
	name: string;
	isGroup: boolean;
	eur: number;
	rez: number;
	pct: number;
	members: AgencyShareRow[];
}

export interface StayMonthEffect {
	key: string; // 'YYYY-MM'
	y: number;
	m: number; // 1-12
	gelen: number; // gelen oda-gece (1 oda/rezervasyon varsayımı — Sedna satırında oda sayısı yok)
	iptal: number; // iptal oda-gece
}

// ── Sabitler ─────────────────────────────────────────────
export const MONTHS_TR = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
export const MONTHS_FULL_TR = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
export const WEEKDAYS_TR = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt']; // Date.getDay() sırası

// İleri rezervasyon / bekleyen-vadeli çubuk dokusu (tasarımın çizgili pirinç deseni).
// #d3b567 brass ile brass-light arası ara ton — salt dekoratif, üzerinde metin yok.
export const FUTURE_STRIPE = 'repeating-linear-gradient(45deg,#bd9a45,#bd9a45 7px,#d3b567 7px,#d3b567 14px)';

// ── Formatlama ───────────────────────────────────────────
/** Tam sayı TR biçimi: 12345 → "12.345" */
export function trInt(n: number): string {
	return Math.round(n || 0).toLocaleString('tr-TR');
}

/** Kompakt EUR: 1.234.567 → "1,23 M €" · 45.600 → "45,6 K €" · 950 → "950 €" (tasarım biçimi) */
export function eurCompact(n: number): string {
	const v = n || 0;
	const abs = Math.abs(v);
	if (abs >= 1e6) return (v / 1e6).toFixed(2).replace('.', ',') + ' M €';
	if (abs >= 1000) return (v / 1000).toFixed(1).replace('.', ',') + ' K €';
	return Math.round(v) + ' €';
}

/** 'YYYY-MM' → "Mar 2026" (vade ayı etiketi) */
export function monthKeyLabel(key: string | null | undefined): string {
	if (!key || key.length < 7) return '—';
	const y = Number(key.slice(0, 4));
	const m = Number(key.slice(5, 7));
	if (!y || !m || m < 1 || m > 12) return '—';
	return `${MONTHS_TR[m - 1]} ${y}`;
}

/** Konaklama aralığı etiketi: aynı ay "5–12 Tem", farklı ay "28 Tem – 4 Ağu" */
export function stayRangeLabel(checkin: string | null, checkout: string | null): string {
	if (!checkin || !checkout) return '—';
	const ci = new Date(checkin + 'T00:00:00');
	const co = new Date(checkout + 'T00:00:00');
	if (isNaN(ci.getTime()) || isNaN(co.getTime())) return '—';
	if (ci.getMonth() === co.getMonth() && ci.getFullYear() === co.getFullYear()) {
		return `${ci.getDate()}–${co.getDate()} ${MONTHS_TR[co.getMonth()]}`;
	}
	return `${ci.getDate()} ${MONTHS_TR[ci.getMonth()]} – ${co.getDate()} ${MONTHS_TR[co.getMonth()]}`;
}

// ── Acente dağılımı rollup'ı ─────────────────────────────
/** Backend `_norm` ile aynı ad normalizasyonu: kenar boşluğu kırp + büyük harf (iç boşluk korunur). */
function normName(s: string | null | undefined): string {
	return (s || '').trim().toUpperCase();
}

/**
 * Acente dağılımını grup görünümüne katlar (Gruplu segmenti).
 * Gruba üye acenteler tek grup satırında toplanır (üyeler açılabilir);
 * gruplanmamış acenteler müstakil satır olur. Ciroya göre azalan sıralı.
 */
export function rollupAgencyGroups(
	byAgency: AgencyShareRow[],
	groups: { name: string; members?: string[] | null }[],
): AgencyGroupRollup[] {
	const memberToGroup = new Map<string, string>();
	for (const g of groups) {
		for (const m of g.members || []) memberToGroup.set(normName(m), g.name);
	}
	const grouped = new Map<string, AgencyGroupRollup>();
	const standalone: AgencyGroupRollup[] = [];
	for (const a of byAgency) {
		const gname = memberToGroup.get(normName(a.name));
		if (!gname) {
			standalone.push({ name: a.name, isGroup: false, eur: a.eur, rez: a.rez, pct: a.pct, members: [] });
			continue;
		}
		let row = grouped.get(gname);
		if (!row) {
			row = { name: gname, isGroup: true, eur: 0, rez: 0, pct: 0, members: [] };
			grouped.set(gname, row);
		}
		row.eur += a.eur;
		row.rez += a.rez;
		row.pct += a.pct;
		row.members.push(a);
	}
	const rows = [...grouped.values(), ...standalone];
	for (const r of rows) {
		r.eur = Math.round(r.eur * 100) / 100;
		r.pct = Math.round(r.pct * 10) / 10;
		r.members.sort((a, b) => b.eur - a.eur);
	}
	rows.sort((a, b) => b.eur - a.eur);
	return rows;
}

// ── Günlük hareketlerin aylık doluluk etkisi ─────────────
/**
 * Bir günün gelen/iptal rezervasyonlarını konaklama gecelerine yayar (gece bazlı,
 * MonthlyOccupancyChart ile aynı yöntem; oda sayısı Sedna satırında olmadığından
 * 1 oda/rezervasyon varsayılır). Ay anahtarına göre artan sıralı döner.
 */
export function spreadStayMonths(
	items: { checkin_date: string | null; checkout_date: string | null; is_cancelled?: boolean; cancelled?: boolean }[],
): StayMonthEffect[] {
	const map = new Map<string, StayMonthEffect>();
	for (const it of items) {
		if (!it.checkin_date || !it.checkout_date) continue;
		const ci = new Date(it.checkin_date + 'T00:00:00');
		const co = new Date(it.checkout_date + 'T00:00:00');
		if (isNaN(ci.getTime()) || isNaN(co.getTime()) || co <= ci) continue;
		const cancelled = Boolean(it.is_cancelled ?? it.cancelled);
		const d = new Date(ci);
		while (d < co) {
			const y = d.getFullYear();
			const m = d.getMonth() + 1;
			const key = `${y}-${String(m).padStart(2, '0')}`;
			let e = map.get(key);
			if (!e) {
				e = { key, y, m, gelen: 0, iptal: 0 };
				map.set(key, e);
			}
			if (cancelled) e.iptal += 1;
			else e.gelen += 1;
			d.setDate(d.getDate() + 1);
		}
	}
	return [...map.values()].sort((a, b) => a.key.localeCompare(b.key));
}
