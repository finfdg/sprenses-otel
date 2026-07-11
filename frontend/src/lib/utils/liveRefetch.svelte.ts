/**
 * useLiveRefetch — ortak canlı-yenileme yardımcısı (WS event → sayfa reload).
 *
 * KURAL: Yeni bir liste/özet sayfası canlı olacaksa (WS `finance_updated` /
 * `sales_updated` yayınına göre kendini tazeleyecekse) elle `onWsEvent` aboneliği
 * yazma — bu helper'ı kullan. Modül filtresi, echo-guard ve onDestroy temizliği
 * tek yerde çözülür.
 *
 * Kullanım (bileşen init'inde, script gövdesinde çağrılır — onMount İÇİNDE DEĞİL;
 * onDestroy kaydı için component-init bağlamı gerekir):
 *
 * ```ts
 * const { markReload } = useLiveRefetch({
 *   modules: [BROADCAST_MODULE.CASH_FLOW, BROADCAST_MODULE.CARILER],
 *   reload: () => { loadSummary(); loadList(); },
 * });
 * // Sayfanın KENDİ mutasyonu sonrası (endpoint broadcast yankısı çift yükleme
 * // yapmasın diye) doğrudan yükleme yapmadan önce markReload() çağır.
 * ```
 *
 * Davranış:
 * - `modules` verildiyse `finance_updated` dinlenir; `payload.module` listedeyse
 *   (veya liste BOŞSA her event'te) `reload()` çağrılır. `modules` hiç verilmezse
 *   `finance_updated` dinlenmez.
 * - `salesModules` verildiyse aynı kural `sales_updated` için uygulanır.
 * - WS reconnect sentetik yayını (`payload.reconnect === true`, modül bilgisi yok)
 *   filtreden MUAF — kopukluk sırasında kaçan event'lerin telafisi için her zaman
 *   reload tetikler.
 * - Echo-guard: son `markReload()` çağrısından `echoMs` (varsayılan 1500ms) içinde
 *   gelen event kendi mutasyonumuzun broadcast YANKISI sayılıp atlanır
 *   (kanıtlanmış desen: `lib/stores/runway.svelte.ts` — sunucu debounce 500ms +
 *   iletim gecikmesi payı).
 * - Abonelikler `onDestroy`'da otomatik bırakılır.
 */
import { onDestroy } from 'svelte';
import { onWsEvent } from '$lib/stores/websocket.svelte';
import { WS_EVENT, type BroadcastModuleType } from '$lib/constants/realtime';

export type LiveRefetchOptions = {
	/** finance_updated modül filtresi — [] = her finance event'i; verilmezse dinlenmez */
	modules?: BroadcastModuleType[];
	/** sales_updated modül filtresi — [] = her sales event'i; verilmezse dinlenmez */
	salesModules?: BroadcastModuleType[];
	/** Sayfanın mevcut yükleme fonksiyon(lar)ını çağıran callback */
	reload: () => void | Promise<void>;
	/** Kendi mutasyonumuzun WS yankısını atlama penceresi (ms) */
	echoMs?: number;
};

export type LiveRefetchHandle = {
	/** Sayfanın kendi mutasyonundan hemen sonra çağır — echo-guard penceresi başlar */
	markReload: () => void;
};

export function useLiveRefetch({
	modules,
	salesModules,
	reload,
	echoMs = 1500,
}: LiveRefetchOptions): LiveRefetchHandle {
	let lastMarkedAt = 0;

	function makeHandler(allowed: BroadcastModuleType[]) {
		return (data: any) => {
			// Reconnect sentetik yayını modül taşımaz → filtre uygulanmaz (kaçan event telafisi)
			if (!data?.reconnect && allowed.length > 0 && !allowed.includes(data?.module)) return;
			if (Date.now() - lastMarkedAt < echoMs) return; // kendi broadcast yankımız
			void reload();
		};
	}

	const unsubs: (() => void)[] = [];
	if (modules) unsubs.push(onWsEvent(WS_EVENT.FINANCE_UPDATED, makeHandler(modules)));
	if (salesModules) unsubs.push(onWsEvent(WS_EVENT.SALES_UPDATED, makeHandler(salesModules)));

	onDestroy(() => {
		for (const u of unsubs) u();
	});

	return {
		markReload() {
			lastMarkedAt = Date.now();
		},
	};
}
