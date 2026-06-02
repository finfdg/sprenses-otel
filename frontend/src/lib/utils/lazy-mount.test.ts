import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { lazyMount } from './lazy-mount';

// ─── IntersectionObserver mock altyapısı ──────────────────────

interface MockObserver {
	callback: IntersectionObserverCallback;
	options: IntersectionObserverInit;
	observed: Element[];
	disconnected: boolean;
}

let currentObserver: MockObserver | null = null;

function setupMockObserver() {
	currentObserver = null;
	const MockIO = vi.fn(function (
		this: any,
		callback: IntersectionObserverCallback,
		options: IntersectionObserverInit,
	) {
		const instance: MockObserver = {
			callback,
			options,
			observed: [],
			disconnected: false,
		};
		currentObserver = instance;
		this.observe = (el: Element) => instance.observed.push(el);
		this.disconnect = () => {
			instance.disconnected = true;
		};
		this.unobserve = () => {};
		this.takeRecords = () => [];
	});
	vi.stubGlobal('IntersectionObserver', MockIO);
}

function triggerIntersection(isIntersecting: boolean) {
	if (!currentObserver) throw new Error('Observer not initialized');
	// Gerçek IntersectionObserver disconnect sonrası callback'i çağırmaz —
	// mock'ta da bu davranışı simüle et.
	if (currentObserver.disconnected) return;
	const entries = currentObserver.observed.map((el) => ({
		isIntersecting,
		target: el,
		intersectionRatio: isIntersecting ? 1 : 0,
		boundingClientRect: {} as DOMRectReadOnly,
		intersectionRect: {} as DOMRectReadOnly,
		rootBounds: null,
		time: Date.now(),
	}));
	currentObserver.callback(entries as IntersectionObserverEntry[], currentObserver as any);
}

// ─── Testler ─────────────────────────────────────────────────

describe('lazyMount', () => {
	beforeEach(() => {
		setupMockObserver();
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('viewport\'a girince onEnter çağrılır', () => {
		const node = document.createElement('div');
		const onEnter = vi.fn();
		lazyMount(node, { onEnter });

		expect(onEnter).not.toHaveBeenCalled();
		triggerIntersection(true);
		expect(onEnter).toHaveBeenCalledTimes(1);
	});

	it('viewport\'a girmediği sürece onEnter çağrılmaz', () => {
		const node = document.createElement('div');
		const onEnter = vi.fn();
		lazyMount(node, { onEnter });

		triggerIntersection(false);
		expect(onEnter).not.toHaveBeenCalled();
	});

	it('ilk girişten sonra observer disconnect olur (tek seferlik)', () => {
		const node = document.createElement('div');
		const onEnter = vi.fn();
		lazyMount(node, { onEnter });

		triggerIntersection(true);
		expect(currentObserver?.disconnected).toBe(true);

		// Disconnect sonrası tekrar tetiklemenin etkisi yok
		triggerIntersection(true);
		expect(onEnter).toHaveBeenCalledTimes(1);
	});

	it('destroy çağrıldığında observer disconnect olur', () => {
		const node = document.createElement('div');
		const onEnter = vi.fn();
		const action = lazyMount(node, { onEnter });

		action.destroy();
		expect(currentObserver?.disconnected).toBe(true);
		expect(onEnter).not.toHaveBeenCalled();
	});

	it('varsayılan rootMargin "200px" kullanılır', () => {
		const node = document.createElement('div');
		lazyMount(node, { onEnter: () => {} });
		expect(currentObserver?.options.rootMargin).toBe('200px');
	});

	it('özel rootMargin geçirilebilir', () => {
		const node = document.createElement('div');
		lazyMount(node, { onEnter: () => {}, rootMargin: '500px' });
		expect(currentObserver?.options.rootMargin).toBe('500px');
	});

	it('IntersectionObserver yoksa onEnter anında çağrılır (SSR fallback)', () => {
		vi.stubGlobal('IntersectionObserver', undefined);
		const node = document.createElement('div');
		const onEnter = vi.fn();
		lazyMount(node, { onEnter });
		expect(onEnter).toHaveBeenCalledTimes(1);
	});
});
