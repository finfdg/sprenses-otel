<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import '../app.css';
	let { children } = $props();

	// Global yönetim PWA manifest'i (start_url="/") yalnızca /devam DIŞINDA eklenir.
	// /devam personel uygulaması kendi kişisel manifest'ini verir (token'lı start_url) —
	// böylece "Ana Ekrana Ekle" login yerine kişisel basış sayfasını açar.
	let isDevam = $derived($page.url.pathname.startsWith('/devam'));

	onMount(() => {
		// Yeni service worker aktifleştiğinde sayfayı TEK SEFER yenile (eski JS çalışmasın).
		// `hadController` guard'ı: sayfa hiç SW kontrolünde değilken (ilk kurulum, null→SW
		// devri) reload YAPMAZ — o an zaten en yeni kod yüklüdür, gereksiz reload girişte
		// titreme yaratır. Yalnız GERÇEK güncellemede (kontrolör varken değişince) reload.
		// SW `activate`'te artık ayrıca `navigate()` yapmıyor → çift-reload/blink giderildi.
		if ('serviceWorker' in navigator) {
			let reloading = false;
			const hadController = !!navigator.serviceWorker.controller;
			navigator.serviceWorker.addEventListener('controllerchange', () => {
				if (reloading || !hadController) return;
				reloading = true;
				window.location.reload();
			});
		}
	});
</script>

<svelte:head>
	{#if !isDevam}
		<link rel="manifest" href="/manifest.json" />
	{/if}
</svelte:head>

<div class="min-h-screen bg-gray-50 text-gray-900 font-sans">
	{@render children()}
</div>
