<script lang="ts">
	// Personel kişisel kurulum sayfası — kişisel QR karttan açılır (?t=access_token).
	// Çerezi (pdks_token) set eder; sonrasında personel girişteki ekranı okutarak basar.
	import { onMount } from 'svelte';
	import { page } from '$app/stores';

	let phase = $state<'loading' | 'ok' | 'error'>('loading');
	let name = $state('');
	let errMsg = $state('');

	onMount(async () => {
		const t = $page.url.searchParams.get('t') ?? '';
		if (!t) { phase = 'error'; errMsg = 'Geçersiz kurulum linki.'; return; }
		try {
			const res = await fetch('/api/attendance/setup', {
				method: 'POST',
				credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ token: t }),
			});
			const data = await res.json().catch(() => ({}));
			if (res.ok) {
				// Kimliği localStorage'da da sakla (iOS'ta çerezden daha güvenilir taşınır)
				try { localStorage.setItem('pdks_token', t); } catch (e) { console.error('localStorage yazılamadı:', e); }
				name = data.full_name ?? '';
				phase = 'ok';
			} else {
				phase = 'error';
				errMsg = data.detail ?? 'Kurulum başarısız.';
			}
		} catch (e) {
			console.error('Kurulum hatası:', e);
			phase = 'error';
			errMsg = 'Bağlantı hatası.';
		}
	});
</script>

<svelte:head><title>Kurulum — Personel Giriş/Çıkış</title></svelte:head>

<div class="min-h-screen flex items-center justify-center p-6 bg-gray-50">
	<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 max-w-sm w-full text-center space-y-4">
		{#if phase === 'loading'}
			<div class="w-10 h-10 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin mx-auto"></div>
			<p class="text-gray-500">Kuruluyor…</p>
		{:else if phase === 'ok'}
			<div class="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto">
				<svg class="w-9 h-9 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
			</div>
			<h1 class="text-xl font-bold text-gray-900">Hoş geldin{name ? `, ${name.split(' ')[0]}` : ''}! 👋</h1>
			<p class="text-sm text-gray-600 leading-relaxed">
				Telefonun tanımlandı. Bundan sonra <strong>girişteki ekrandaki karekodu</strong>
				telefonunun kamerasıyla okutarak <strong>giriş ve çıkış</strong> yapabilirsin.
			</p>
			<div class="bg-teal-50 border border-teal-200 rounded-lg p-3 text-xs text-teal-800 leading-snug text-left">
				💡 İpucu: Bu sayfayı telefonun <strong>ana ekranına ekle</strong> — her seferinde hızlıca aç,
				kamerayı ekrandaki koda tut, gerisi otomatik.
			</div>
		{:else}
			<div class="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto">
				<svg class="w-9 h-9 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
			</div>
			<h1 class="text-lg font-bold text-gray-900">Kurulum yapılamadı</h1>
			<p class="text-sm text-gray-600">{errMsg}</p>
			<p class="text-xs text-gray-400">Yöneticinizden güncel QR kartınızı isteyin.</p>
		{/if}
	</div>
</div>
