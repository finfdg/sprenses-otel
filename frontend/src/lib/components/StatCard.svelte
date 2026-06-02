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
	// icon tipini gevşetiyoruz (any) — Lucide'ın kendi Component tipleri katı
	// Component<...> ile uyuşmuyor. EmptyState.svelte de aynı yaklaşımı kullanır.
	let {
		value,
		label,
		icon = undefined,
		accent = 'teal',
		hint = undefined,
	}: {
		value: string | number;
		label: string;
		icon?: any;
		accent?: StatAccent;
		hint?: string;
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
</script>

<div class="bg-white border border-gray-200 rounded-2xl p-4 sm:p-5 shadow-sm">
	<div class="flex items-start justify-between gap-3">
		<div class="min-w-0">
			<div class="text-xs font-medium text-gray-500 uppercase tracking-wider truncate">{label}</div>
			<div class="mt-1.5 text-xl font-bold tabular-nums leading-tight {a.value}" title={String(value)}>{value}</div>
			{#if hint}
				<div class="text-xs text-gray-500 mt-1">{hint}</div>
			{/if}
		</div>
		{#if Icon}
			<div class="shrink-0 w-10 h-10 rounded-xl {a.iconBg} {a.iconText} flex items-center justify-center" aria-hidden="true">
				<Icon size={20} />
			</div>
		{/if}
	</div>
</div>
