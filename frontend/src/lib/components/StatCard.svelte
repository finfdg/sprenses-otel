<!--
	StatCard.svelte — Özet/istatistik kartı (tasarım sistemi primitive'i).

	Neden: 14 sayfa kendi inline stat kartını yazıyordu (farklı boyut/renk/kontrast).
	Bu bileşen tek bir tutarlı kart verir: opsiyonel ikon + semantik aksan rengi + alt-ipucu.
	Metin kontrastları WCAG AA uyumludur (label/hint gray-500, gray-400 değil).

	Kullanım:
		<StatCard label="EUR Bekleyen" value="€12.500,00" accent="amber" icon={Hourglass} hint="3 kayıt" />
-->
<script lang="ts" module>
	export type StatAccent = 'teal' | 'emerald' | 'amber' | 'red' | 'blue' | 'gray';
</script>

<script lang="ts">
	import { ArrowUp, ArrowDown, Minus } from 'lucide-svelte';

	// icon tipini gevşetiyoruz (any) — Lucide'ın kendi Component tipleri katı
	// Component<...> ile uyuşmuyor. EmptyState.svelte de aynı yaklaşımı kullanır.
	let {
		value,
		label,
		icon = undefined,
		accent = 'teal',
		hint = undefined,
		href = undefined,
		delta = undefined,
		deltaText = undefined,
		deltaLabel = undefined,
		deltaInvert = false,
		class: extraClass = '',
	}: {
		value: string | number;
		label: string;
		icon?: any;
		accent?: StatAccent;
		hint?: string;
		/** Verilirse kart tıklanabilir bağlantı (<a>) olur — hover affordance + cursor. */
		href?: string;
		/** İşaretli değişim (YoY/dönem karşılaştırma). İşareti ok yönünü + rengi belirler. null/undefined → rozet gizli. */
		delta?: number | null;
		/** Rozette gösterilecek metin (ör. "+%12,5", "+8 puan"). Yoksa delta sayısı kullanılır. TR format çağırandan gelir. */
		deltaText?: string;
		/** Rozet sonrası bağlam metni (ör. "geçen yıla göre"). */
		deltaLabel?: string;
		/** true → negatif iyi (maliyet düşüşü yeşil). Varsayılan: pozitif iyi. */
		deltaInvert?: boolean;
		/** Yalnızca layout (genişlik/boşluk) için ek sınıf. */
		class?: string;
	} = $props();

	const ACCENT: Record<StatAccent, { value: string; iconBg: string; iconText: string }> = {
		teal: { value: 'text-teal-700', iconBg: 'bg-teal-50', iconText: 'text-teal-600' },
		emerald: { value: 'text-emerald-700', iconBg: 'bg-emerald-50', iconText: 'text-emerald-600' },
		amber: { value: 'text-amber-700', iconBg: 'bg-amber-50', iconText: 'text-amber-600' },
		red: { value: 'text-red-600', iconBg: 'bg-red-50', iconText: 'text-red-600' },
		blue: { value: 'text-blue-600', iconBg: 'bg-blue-50', iconText: 'text-blue-600' },
		gray: { value: 'text-gray-700', iconBg: 'bg-gray-100', iconText: 'text-gray-500' },
	};
	let a = $derived(ACCENT[accent]);
	let Icon = $derived(icon);

	// Uzun para değerleri (ör. ₺154.073.001,86) text-xl'de taşıyordu → uzunluğa göre fontu küçült.
	let valLen = $derived(String(value).length);
	let valSize = $derived(valLen > 18 ? 'text-base' : valLen > 14 ? 'text-lg' : 'text-xl');

	// Delta: işaret → ok yönü + AA-uyumlu renk (deltaInvert ile anlam tersine çevrilebilir).
	let hasDelta = $derived(delta !== undefined && delta !== null);
	let deltaUp = $derived(hasDelta && (delta as number) > 0);
	let deltaDown = $derived(hasDelta && (delta as number) < 0);
	let deltaGood = $derived(deltaInvert ? deltaDown : deltaUp);
	let deltaBad = $derived(deltaInvert ? deltaUp : deltaDown);
	let DeltaIcon = $derived(deltaUp ? ArrowUp : deltaDown ? ArrowDown : Minus);
	let deltaColor = $derived(deltaGood ? 'text-emerald-700' : deltaBad ? 'text-red-600' : 'text-gray-500');
</script>

<svelte:element
	this={href ? 'a' : 'div'}
	href={href}
	class="block bg-white border border-gray-200 rounded-2xl p-4 sm:p-5 shadow-sm {href ? 'hover:border-teal-300 hover:shadow-md transition-all cursor-pointer' : ''} {extraClass}"
>
	<!-- Üst satır: etiket (en fazla 2 satır) + ikon. Değer ALT satırda tam genişlikte → uzun
	     para tutarları ikonla yarışmaz, taşmaz. -->
	<div class="flex items-start justify-between gap-3">
		<div class="text-xs font-medium text-gray-500 uppercase tracking-wider leading-tight min-w-0 line-clamp-2" title={label}>{label}</div>
		{#if Icon}
			<div class="shrink-0 w-10 h-10 rounded-xl {a.iconBg} {a.iconText} flex items-center justify-center" aria-hidden="true">
				<Icon size={20} />
			</div>
		{/if}
	</div>
	<div class="mt-1.5 font-bold tabular-nums leading-tight break-words {valSize} {a.value}" title={String(value)}>{value}</div>
	{#if hasDelta}
		<div class="text-xs mt-1 flex items-center gap-1 flex-wrap">
			<span class="inline-flex items-center gap-0.5 font-medium {deltaColor}">
				<DeltaIcon size={12} aria-hidden="true" />{deltaText ?? delta}
			</span>
			{#if deltaLabel}<span class="text-gray-500">{deltaLabel}</span>{/if}
		</div>
	{/if}
	{#if hint}
		<div class="text-xs text-gray-500 mt-1">{hint}</div>
	{/if}
</svelte:element>
