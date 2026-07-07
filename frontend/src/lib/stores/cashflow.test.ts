import { describe, it, expect, beforeEach } from 'vitest';
import { cashFlowCache, isEurBalancesStale, invalidateCashFlowCache } from './cashflow.svelte';
import { emitLocal } from './websocket.svelte';
import { WS_EVENT } from '$lib/constants/realtime';

const STALE_MS = 5 * 60 * 1000;

beforeEach(() => {
	invalidateCashFlowCache();
});

// ─── isEurBalancesStale ──────────────────────────────────────

describe('isEurBalancesStale', () => {
	it('hiç yüklenmemişse (null) bayattır', () => {
		expect(cashFlowCache.eurBalances).toBeNull();
		expect(isEurBalancesStale()).toBe(true);
	});

	it('taze yüklenmişse bayat değildir', () => {
		cashFlowCache.eurBalances = { total_balance_eur: 100 };
		cashFlowCache.eurBalancesFetchedAt = Date.now();
		expect(isEurBalancesStale()).toBe(false);
	});

	it('TTL (5 dk) aşılmışsa bayattır', () => {
		cashFlowCache.eurBalances = { total_balance_eur: 100 };
		cashFlowCache.eurBalancesFetchedAt = Date.now() - STALE_MS - 1000;
		expect(isEurBalancesStale()).toBe(true);
	});

	it('damga sıfırlanmışsa dolu cache bile bayattır (WS geçersizlemesi)', () => {
		cashFlowCache.eurBalances = { total_balance_eur: 100 };
		cashFlowCache.eurBalancesFetchedAt = 0;
		expect(isEurBalancesStale()).toBe(true);
	});
});

// ─── WS finance_updated → store-seviyesi geçersizleme ────────

describe('finance_updated geçersizlemesi', () => {
	it('event gelince tazelik damgalarını sıfırlar (fetch etmeden)', () => {
		cashFlowCache.eurBalances = { total_balance_eur: 100 };
		cashFlowCache.eurBalancesFetchedAt = Date.now();
		cashFlowCache.lastFetchedAt = Date.now();

		emitLocal(WS_EVENT.FINANCE_UPDATED, { module: 'banks' });

		expect(cashFlowCache.eurBalancesFetchedAt).toBe(0);
		expect(cashFlowCache.lastFetchedAt).toBe(0);
		// Veri silinmez — mount'a kadar eski değer gösterilebilir, yalnız bayat sayılır
		expect(cashFlowCache.eurBalances).toEqual({ total_balance_eur: 100 });
		expect(isEurBalancesStale()).toBe(true);
	});

	it('ilgisiz event damgalara dokunmaz', () => {
		cashFlowCache.eurBalances = { total_balance_eur: 100 };
		const t = Date.now();
		cashFlowCache.eurBalancesFetchedAt = t;

		emitLocal(WS_EVENT.NEW_MESSAGE, {});

		expect(cashFlowCache.eurBalancesFetchedAt).toBe(t);
	});
});

// ─── invalidateCashFlowCache ─────────────────────────────────

describe('invalidateCashFlowCache', () => {
	it('eurBalances verisini ve damgasını sıfırlar', () => {
		cashFlowCache.eurBalances = { total_balance_eur: 100 };
		cashFlowCache.eurBalancesFetchedAt = Date.now();

		invalidateCashFlowCache();

		expect(cashFlowCache.eurBalances).toBeNull();
		expect(cashFlowCache.eurBalancesFetchedAt).toBe(0);
		expect(isEurBalancesStale()).toBe(true);
	});
});
