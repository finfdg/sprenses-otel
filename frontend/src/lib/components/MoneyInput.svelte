<!--
	MoneyInput.svelte — Tüm formlarda ortak para girişi bileşeni.

	Özellikler:
	- Türkçe format: binlik ayırıcı "." (nokta), ondalık ayırıcı "," (virgül)
	- **Canlı formatlama:** Yazarken binlik ayırıcı otomatik eklenir ("1234567" → "1.234.567")
	- **İmleç konumu korunur:** Format değişse bile imleç sağdan aynı mesafede kalır
	- Varsayılan 2 ondalık basamak (decimals prop ile değiştirilebilir)
	- **Kalıcı highlight:** Tıklandığında tüm metin seçilir; mousedown event'i ile browser'ın
	  normal click→caret yerleşimi engellenir, böylece seçim kaybolmaz
	- Yeni rakam yazınca önceki değer silinir (seçili olduğu için)
	- Blur'da min/max clamp + decimals yuvarlama
	- Opsiyonel para birimi rozeti (sağda) — "TRY" → ₺, "EUR" → €, "USD" → $, "GBP" → £

	Kullanım:
		<MoneyInput bind:value={amount} currency="TRY" placeholder="0,00" />
		<MoneyInput bind:value={amount} currency="EUR" min={0} required />

	value tipi: number | null (null → boş input)
-->
<script lang="ts">
	interface Props {
		value: number | null;
		id?: string;
		name?: string;
		placeholder?: string;
		currency?: string;
		decimals?: number;
		min?: number;
		max?: number;
		disabled?: boolean;
		required?: boolean;
		allowNegative?: boolean;
		/** Ek tailwind sınıfları — varsayılan stilin üzerine eklenir */
		class?: string;
		onchange?: (v: number | null) => void;
		/** Form erişilebilirliği: hata durumunu ekran okuyucuya bildirir */
		ariaInvalid?: boolean;
		ariaDescribedby?: string;
	}

	let {
		value = $bindable(),
		id,
		name,
		placeholder = '0,00',
		currency,
		decimals = 2,
		min,
		max,
		disabled = false,
		required = false,
		allowNegative = false,
		class: klass = '',
		onchange,
		ariaInvalid = false,
		ariaDescribedby = undefined,
	}: Props = $props();

	const CURRENCY_LABELS: Record<string, string> = {
		TRY: '₺',
		EUR: '€',
		USD: '$',
		GBP: '£',
	};

	// ─── Format / Parse ──────────────────────────────────

	/** Blur/statik formatlama — 1234.56 → "1.234,56" (tam decimals basamak) */
	function formatTR(n: number | null | undefined, d: number): string {
		if (n === null || n === undefined || !Number.isFinite(n)) return '';
		return n.toLocaleString('tr-TR', {
			minimumFractionDigits: d,
			maximumFractionDigits: d,
		});
	}

	/** Canlı formatlama — kullanıcı yazarken binlik ekler, kısmi ondalık kalır.
	 *  "1234567" → "1.234.567"
	 *  "1234,5"  → "1.234,5"  (eksik ondalık korunur)
	 *  "1.234,5" → "1.234,5"  (zaten formatlı)
	 *  ","       → ","        (kullanıcı virgüle basmış ama henüz rakam yok)
	 */
	function formatLiveTR(raw: string, d: number, allowNeg: boolean): string {
		let s = raw;
		// 1) İzinli karakterler
		s = allowNeg ? s.replace(/[^0-9.,-]/g, '') : s.replace(/[^0-9.,]/g, '');
		// 2) Eksi yalnızca başta
		const neg = allowNeg && s.startsWith('-');
		s = s.replace(/-/g, '');
		// 3) Virgülü yalnızca ilk sırada tut → intPart / decPart
		const commaIdx = s.indexOf(',');
		let intPart: string;
		let decPart = '';
		let hasComma = false;
		if (commaIdx !== -1) {
			hasComma = true;
			intPart = s.slice(0, commaIdx);
			decPart = s.slice(commaIdx + 1).replace(/[.,]/g, '').slice(0, d);
		} else {
			intPart = s;
		}
		// 4) intPart'taki noktaları kaldır (binlik'ler yeniden eklenecek)
		intPart = intPart.replace(/\./g, '');
		// 5) Baştaki gereksiz 0'ları kaldır (ama tek "0" kalsın)
		if (intPart.length > 1) {
			intPart = intPart.replace(/^0+/, '');
			if (intPart === '') intPart = '0';
		}
		// 6) Binlik ayırıcı ekle
		if (intPart.length > 3) {
			intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
		}
		// 7) Birleştir
		let result = intPart;
		if (hasComma) result += ',' + decPart;
		if (neg) result = '-' + result;
		return result;
	}

	/** Formatlı string'i sayıya çevir */
	function parseTR(raw: string, allowNeg: boolean): number | null {
		if (!raw) return null;
		let s = raw.replace(/\s/g, '');
		s = s.replace(/\./g, '').replace(/,/g, '.');
		const negative = s.startsWith('-');
		s = s.replace(/[^0-9.]/g, '');
		const firstDot = s.indexOf('.');
		if (firstDot !== -1) {
			s = s.slice(0, firstDot + 1) + s.slice(firstDot + 1).replace(/\./g, '');
		}
		if (!s || s === '.' || s === '-') return null;
		const n = parseFloat(s);
		if (!Number.isFinite(n)) return null;
		return negative && allowNeg ? -n : Math.abs(n);
	}

	// ─── State ───────────────────────────────────────────
	let inputEl: HTMLInputElement;
	let focused = $state(false);

	const currencyLabel = $derived(currency ? (CURRENCY_LABELS[currency] || currency) : null);

	// Dışarıdan value değişirse input.value'yu senkronla (yalnızca focus dışında).
	// Focus içindeyken handleInput manuel senkron eder; effect inaktif olmalı ki
	// kullanıcı "1,5" yazarken "1,50" zorlanmasın.
	$effect(() => {
		if (!inputEl) return;
		// dependency: value + decimals
		const want = formatTR(value, decimals);
		if (!focused && inputEl.value !== want) {
			inputEl.value = want;
		}
	});

	// ─── Event Handlers ──────────────────────────────────
	function handleInput(e: Event) {
		const target = e.target as HTMLInputElement;
		const rawInput = target.value;
		const caretBefore = target.selectionStart ?? rawInput.length;
		const rightLen = rawInput.length - caretBefore;

		const formatted = formatLiveTR(rawInput, decimals, allowNegative);

		// DOM'a doğrudan yaz (Svelte bind kullanmıyoruz — imleç yönetimi manuel)
		if (target.value !== formatted) {
			target.value = formatted;
		}
		// İmleci sağdan aynı mesafede koru
		const newCaret = Math.max(0, formatted.length - rightLen);
		try {
			target.setSelectionRange(newCaret, newCaret);
		} catch {
			// Bazı tarayıcılar (iOS) bu tipte hata atabilir; sessizce geç
		}

		const parsed = parseTR(formatted, allowNegative);
		if (parsed !== value) {
			value = parsed;
			onchange?.(parsed);
		}
	}

	function handleMouseDown(e: MouseEvent) {
		// Input henüz focus almadıysa browser'ın normal click→caret yerleşimini engelle.
		// Aksi halde focus handler'ın select() çağrısı, tarayıcının sonraki
		// "cursor'u click pozisyonuna yerleştir" davranışı tarafından iptal edilir.
		if (inputEl && document.activeElement !== inputEl) {
			e.preventDefault();
			inputEl.focus();
			// handleFocus zaten select() yapacak
		}
	}

	function handleFocus() {
		focused = true;
		if (inputEl) {
			// Focus anında mevcut değeri formatlı göster (binlik nokta + virgül)
			inputEl.value = formatTR(value, decimals);
			// DOM güncellendikten sonra tümünü seç (rAF ile bir frame bekle)
			requestAnimationFrame(() => {
				if (inputEl && document.activeElement === inputEl) {
					inputEl.select();
				}
			});
		}
	}

	function handleBlur() {
		focused = false;
		// min/max clamp + decimals yuvarlama
		if (value !== null && Number.isFinite(value)) {
			let v = value as number;
			if (typeof min === 'number' && v < min) v = min;
			if (typeof max === 'number' && v > max) v = max;
			const factor = Math.pow(10, decimals);
			v = Math.round(v * factor) / factor;
			if (v !== value) {
				value = v;
				onchange?.(v);
			}
		}
		// $effect formatlanmış değeri input'a yazacak
		if (inputEl) {
			inputEl.value = formatTR(value, decimals);
		}
	}
</script>

<div class="relative">
	<input
		bind:this={inputEl}
		{id}
		{name}
		{disabled}
		{required}
		{placeholder}
		type="text"
		inputmode="decimal"
		autocomplete="off"
		aria-invalid={ariaInvalid || undefined}
		aria-describedby={ariaDescribedby}
		oninput={handleInput}
		onmousedown={handleMouseDown}
		onfocus={handleFocus}
		onblur={handleBlur}
		class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl bg-white outline-none
			focus:border-teal-400 focus:ring-2 focus:ring-teal-500/20
			disabled:bg-gray-50 disabled:text-gray-400 disabled:cursor-not-allowed
			text-right tabular-nums
			{currencyLabel ? 'pr-10' : ''}
			{klass}"
	/>
	{#if currencyLabel}
		<span class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none select-none">
			{currencyLabel}
		</span>
	{/if}
</div>
