<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { Info } from 'lucide-svelte';

	const canView = hasPermission('sales.flight', 'view');

	// Travelpayouts (Aviasales) Search Form Widget — gerçek zamanlı arama, otomatik affiliate.
	// shmarker=722928 → bizim affiliate ID (komisyon takibi)
	// promo_id=7879 + campaign_id=100 → Aviasales arama formu
	// color_*=0d9488 → teal tema (sitemizle uyum)
	const WIDGET_SRC =
		'https://tp.media/content?' +
		'shmarker=722928' +
		'&promo_id=7879' +
		'&campaign_id=100' +
		'&locale=tr' +
		'&currency=try' +
		'&color_button=%230d9488' +
		'&color_icons=%230d9488' +
		'&color_focused=%230d9488' +
		'&color_button_text=%23ffffff' +
		'&border_radius=8' +
		'&powered_by=true' +
		'&searchUrl=www.aviasales.com';

	let widgetEl = $state<HTMLDivElement | null>(null);
	let widgetScript: HTMLScriptElement | null = null;
	let loadFailed = $state(false);

	onMount(() => {
		if (!canView || !widgetEl) return;

		widgetScript = document.createElement('script');
		widgetScript.async = true;
		widgetScript.charset = 'utf-8';
		widgetScript.src = WIDGET_SRC;
		widgetScript.onerror = () => {
			loadFailed = true;
			console.error('Travelpayouts widget yüklenemedi');
		};
		widgetEl.appendChild(widgetScript);
	});

	onDestroy(() => {
		// Sayfa terk edilirken script'i de kaldır (memory leak önler)
		if (widgetScript && widgetScript.parentNode) {
			widgetScript.parentNode.removeChild(widgetScript);
		}
	});
</script>

<svelte:head>
	<title>Uçak Rezervasyon — Sprenses</title>
</svelte:head>

{#if !canView}
	<div class="text-center py-20 text-gray-500">Bu sayfayı görüntüleme yetkiniz yok.</div>
{:else}
	<div class="space-y-6">
		<!-- Başlık -->
		<PageHeader
			title="Uçak Rezervasyon"
			description="Aviasales arama motoru — gerçek zamanlı uçuş ve fiyat bilgisi"
		/>

		<!-- Bilgi notu -->
		<div class="bg-blue-50 border border-blue-200 text-blue-800 rounded-lg p-3 text-xs flex items-start gap-2">
			<Info class="w-4 h-4 shrink-0 mt-0.5" />
			<div>
				Aşağıdaki form Aviasales'in canlı arama motoruyla bağlantılı — Skyscanner kalitesinde tüm büyük havayollarını (THY, Pegasus, AnadoluJet, SunExpress vb.) gerçek zamanlı tarar. Sorgu sonucunda Aviasales'te uçuş listesi açılır; oradaki tüm fiyatlar gerçek tek yön / paket fiyatlarıdır.
			</div>
		</div>

		<!-- Widget container -->
		<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 md:p-6">
			<div bind:this={widgetEl} class="w-full min-h-[200px]"></div>

			{#if loadFailed}
				<div class="text-center py-8 text-red-600 text-sm">
					Widget yüklenemedi — internet bağlantısını kontrol edin veya birkaç dakika sonra tekrar deneyin.
				</div>
			{/if}
		</div>

		<!-- Alt bilgi -->
		<div class="text-[10px] text-gray-500 text-center pt-2">
			Veri kaynağı: Travelpayouts / Aviasales · Affiliate ID: 722928
		</div>
	</div>
{/if}
