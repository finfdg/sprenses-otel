// Svelte 5 lazy mount yardımcısı — IntersectionObserver tabanlı
// Bir elementin viewport'a yaklaştığı anda callback tetiklenir.
// Tek seferlik (once) — ilk girişten sonra observer durdurulur.
//
// Kullanım:
//   let mounted = $state(false);
//   <div use:lazyMount={{ onEnter: () => (mounted = true), rootMargin: '300px' }}>
//     {#if mounted}<HeavyContent />{/if}
//   </div>
//
// Not: SSR ortamında IntersectionObserver yoktur — bu durumda
// callback hemen tetiklenir (graceful fallback).

export interface LazyMountOptions {
	/** Viewport'a girince tetiklenecek callback */
	onEnter: () => void;
	/** Root margin — viewport'tan ne kadar önce tetikleneceği (default: '200px') */
	rootMargin?: string;
	/** Tetikleme eşiği (default: 0 — minik bir kısmı görününce tetikler) */
	threshold?: number;
}

export function lazyMount(node: HTMLElement, options: LazyMountOptions) {
	let opts = options;

	// SSR veya eski tarayıcı koruması — anında mount
	if (typeof IntersectionObserver === 'undefined') {
		opts.onEnter();
		return {
			update(newOpts: LazyMountOptions) {
				opts = newOpts;
			},
			destroy() {
				/* no-op */
			},
		};
	}

	const observer = new IntersectionObserver(
		(entries) => {
			for (const entry of entries) {
				if (entry.isIntersecting) {
					opts.onEnter();
					observer.disconnect();
					break;
				}
			}
		},
		{
			rootMargin: opts.rootMargin ?? '200px',
			threshold: opts.threshold ?? 0,
		},
	);

	observer.observe(node);

	return {
		update(newOpts: LazyMountOptions) {
			opts = newOpts;
		},
		destroy() {
			observer.disconnect();
		},
	};
}
