/**
 * Runway (nakit projeksiyon) PAYLAŞIMLI veri deposu + biçimlendirme yardımcıları.
 *
 * Panel Nakit Akım kartında GRAFİK (`RunwayChart`) ve VADESİ GEÇENLER (`OverdueList`) ayrı
 * konumlarda render edilir → veri TEK sefer çekilir (ref-count'lu abonelik + WS tazeleme).
 * Eski `NakitKoruma` bileşeni kullanıcı isteğiyle (2026-07-06) kaldırıldı: grafik + vadesi
 * geçenler bu iki küçük bileşene taşındı, "Ödeme Erteleme" planlama gövdesi (bankadaki nakit
 * durum kartının altındaki tahsilat/planlı-ödeme/ay-sonu listeleri) tamamen çıkarıldı.
 * defer-batch yalnız "Vadesi Geçenler"i ötelemek için korunur.
 */
import { api } from '$lib/api';
import { showToast } from '$lib/stores/toast.svelte';
import { onWsEvent } from '$lib/stores/websocket.svelte';
import { WS_EVENT } from '$lib/constants/realtime';

export type Flow = {
	id: string; date: string; name: string; amount_eur: number;
	amount_native?: number; currency?: string; source_type?: string;
	deferred?: boolean; original_date?: string; projected?: boolean;
};
export type RunwayData = {
	month_label: string; month_start: string; month_end: string; today: string;
	start_eur: number; inflows: Flow[]; outs: Flow[];
	overdue: Flow[]; overdue_income?: Flow[]; held?: Flow[]; skipped_no_rate: number;
};
export type SourceRef = { source_type: string; source_id: number };

export const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
export const SRC_LABELS: Record<string, string> = {
	vendor_payment: 'Cari Ödemeleri', credit: 'Kredi / Leasing Taksitleri',
	cc_payment: 'KK Borç Ödemeleri', check: 'Verilen Çekler', salary: 'Maaş Ödemeleri',
	sgk: 'SGK', tax: 'Vergiler', recurring: 'Düzenli Ödemeler', withholding: 'Stopajlar',
	dividend: 'Temettü', rent_expense: 'Verilen Kiralar', advance: 'Avanslar',
};

const CUR_SYM: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$', GBP: '£' };
export function fmtEur(n: number): string {
	return '€' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(Math.abs(n)));
}
export function signed(n: number): string {
	return (n >= 0 ? '+' : '−') + fmtEur(n);
}
export function fmtNative(n: number, currency?: string): string {
	const sym = CUR_SYM[currency ?? 'TRY'] || (currency + ' ');
	return sym + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(Math.abs(n)));
}
export function labelDate(iso: string): string {
	const [, m, d] = iso.split('-').map(Number);
	return `${d} ${MONTHS_SHORT[m - 1]}`;
}
export function dayNum(iso: string): number {
	return Number(iso.split('-')[2]);
}
export function cleanName(name: string): string {
	return name.replace(/^\[[^\]]*\]\s*/, '');
}

// ── Paylaşımlı reaktif state ──────────────────────────────────
let _data = $state<RunwayData | null>(null);
let _loading = $state(true);
let started = false;
let refCount = 0;
let wsUnsub: (() => void) | null = null;

// Beklet (hold) modu — Panel Nakit Akım kartındaki "Beklet" option butonu açıkken true.
// CashFlowTAccount (bekleyen satır tıklaması) + HeldList (bekleme listesi geri-al) ORTAK okur;
// pasifken (false) mevcut bekletmeler korunur ama düzenlenemez (salt gösterim).
let _holdMode = $state(false);

export const runwayStore = {
	get data() { return _data; },
	get loading() { return _loading; },
	get holdMode() { return _holdMode; },
};

export function setHoldMode(v: boolean): void {
	_holdMode = v;
}

export async function loadRunway(): Promise<void> {
	try {
		_data = await api.get<RunwayData>('/finance/cash-flow/runway');
	} catch (err) {
		console.error('Nakit projeksiyon verisi yüklenemedi:', err);
		showToast('Nakit akım projeksiyonu yüklenemedi', 'error');
	} finally {
		_loading = false;
	}
}

/** İlk tüketici mount olunca TEK sefer yükle + WS aboneliği; son tüketici gidince temizle. */
export function subscribeRunway(): () => void {
	refCount++;
	if (!started) {
		started = true;
		loadRunway();
		wsUnsub = onWsEvent(WS_EVENT.FINANCE_UPDATED, () => loadRunway());
	}
	return () => {
		if (--refCount <= 0) {
			wsUnsub?.();
			wsUnsub = null;
			started = false;
		}
	};
}

function parseId(id: string): { source_type: string; source_id: number } {
	const i = id.lastIndexOf(':');
	return { source_type: id.slice(0, i), source_id: Number(id.slice(i + 1)) };
}

/** Vadesi geçen grubu KALICI ötele (deferredTo) veya geri al (null) — TEK batch isteği, sonra tazele. */
export async function deferBatch(memberIds: string[], deferredTo: string | null): Promise<void> {
	const items = memberIds.map(parseId);
	await api.post('/finance/cash-flow/defer-batch', { items, deferred_to: deferredTo });
	await loadRunway();
}

/** Kalemleri beklemeye al (held=true) veya bekletmeyi kaldır (held=false) — TEK batch isteği, sonra tazele.
 *  Endpoint CASH_FLOW broadcast'i yayar → T-Hesap + runway tüketicileri WS ile de tazelenir. */
export async function holdBatch(items: SourceRef[], held: boolean): Promise<void> {
	if (items.length === 0) return;
	await api.post('/finance/cash-flow/hold-batch', { items, held });
	await loadRunway();
}
