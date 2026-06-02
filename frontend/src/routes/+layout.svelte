<script lang="ts">
	import { onMount } from 'svelte';
	import '../app.css';
	let { children } = $props();

	onMount(() => {
		// Yeni service worker aktifleştiğinde sayfayı otomatik yenile
		// böylece eski JavaScript kodu çalışmaya devam etmez
		if ('serviceWorker' in navigator) {
			let reloading = false;
			navigator.serviceWorker.addEventListener('controllerchange', () => {
				if (reloading) return;
				reloading = true;
				window.location.reload();
			});
		}
	});
</script>

<div class="min-h-screen bg-gray-50 text-gray-900 font-sans">
	{@render children()}
</div>
