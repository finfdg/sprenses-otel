/**
 * Svelte action: Modal içinde Tab ile odak döngüsü sağlar.
 * Kullanım: <div use:focusTrap>...</div>
 *
 * Yalnızca klavye Tab navigasyonunu yönetir — modal açılışında
 * otomatik odaklama veya kapanışında odak geri yükleme YAPMAZ.
 * Bu, Safari'de "ghost click" / odak yarış koşullarını engeller.
 */
export function focusTrap(node: HTMLElement) {
	const FOCUSABLE =
		'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

	function handleKeydown(e: KeyboardEvent) {
		if (e.key !== 'Tab') return;

		const focusable = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
		if (focusable.length === 0) return;

		const first = focusable[0];
		const last = focusable[focusable.length - 1];

		if (e.shiftKey) {
			if (document.activeElement === first) {
				e.preventDefault();
				try { last.focus(); } catch { /* yoksay */ }
			}
		} else {
			if (document.activeElement === last) {
				e.preventDefault();
				try { first.focus(); } catch { /* yoksay */ }
			}
		}
	}

	node.addEventListener('keydown', handleKeydown);

	return {
		destroy() {
			node.removeEventListener('keydown', handleKeydown);
			// Bilinçli olarak odak geri yükleme YOK — Svelte'in doğal davranışına bırak.
		},
	};
}
