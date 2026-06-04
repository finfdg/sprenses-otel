<script lang="ts">
	// Kiosk ekranı — girişteki tablet/TV'de açılır. Dönen QR gösterir.
	// KIOSK_KEY ?key= ile gelir. QR ~10sn'de bir yenilenir (kiosk display istisnası).
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';

	let key = $state('');
	let tick = $state(0);
	let clock = $state('');
	let qrTimer: ReturnType<typeof setInterval> | null = null;
	let clockTimer: ReturnType<typeof setInterval> | null = null;

	function updateClock() {
		clock = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	onMount(() => {
		key = $page.url.searchParams.get('key') ?? '';
		updateClock();
		// QR'ı 10sn'de bir yenile (token 15sn'de döner, payı bırakıyoruz)
		qrTimer = setInterval(() => (tick = Date.now()), 10000);
		clockTimer = setInterval(updateClock, 1000);
		tick = Date.now();
	});
	onDestroy(() => {
		if (qrTimer) clearInterval(qrTimer);
		if (clockTimer) clearInterval(clockTimer);
	});
</script>

<svelte:head><title>Personel Giriş/Çıkış</title></svelte:head>

<div class="min-h-screen bg-gradient-to-br from-teal-700 to-teal-900 flex flex-col items-center justify-center text-white p-6">
	{#if !key}
		<div class="text-center">
			<h1 class="text-2xl font-bold mb-2">Geçersiz Kiosk Linki</h1>
			<p class="text-teal-100">Yönetici panelinden "Kiosk Linki"ni alıp bu cihazda açın.</p>
		</div>
	{:else}
		<div class="text-center mb-6">
			<h1 class="text-3xl sm:text-4xl font-bold tracking-tight">Personel Giriş / Çıkış</h1>
			<p class="text-teal-100 mt-2 text-lg">Kişisel <strong>uygulamanızı</strong> açıp <strong>"Tara"</strong> ile bu karekodu okutun</p>
			<p class="text-teal-200/80 mt-1 text-sm">(Telefonun kendi kamera uygulamasıyla değil — kendi uygulamanızdaki Tara ile)</p>
		</div>

		<div class="bg-white rounded-3xl p-5 sm:p-6 shadow-2xl">
			<img
				src={`/api/attendance/kiosk/qr?key=${encodeURIComponent(key)}&_=${tick}`}
				alt="Giriş/Çıkış karekodu"
				class="w-64 h-64 sm:w-80 sm:h-80 block"
			/>
		</div>

		<div class="mt-6 text-center">
			<div class="text-5xl sm:text-6xl font-bold tabular-nums">{clock}</div>
			<p class="text-teal-200 text-sm mt-2">Kod güvenlik için sürekli yenilenir</p>
		</div>
	{/if}
</div>
