<script lang="ts">
	// Native-scan landing — iOS kamerasıyla girişteki ekranın QR'ı okutulunca açılır.
	// Bu bağlam İZOLE olduğundan kimlik (localStorage/çerez) YOKtur → buradan basış YAPILAMAZ.
	// (Teşhis: header=False cookie=False → 401.) Çözüm: kimlik varsa kişisel uygulamaya
	// yönlendir; yoksa "kendi uygulamandaki Tara'yı kullan" talimatı göster.
	import { onMount } from 'svelte';
	import { page } from '$app/stores';

	type View = 'loading' | 'use-app';
	let view = $state<View>('loading');

	function pdksToken(): string {
		try { return localStorage.getItem('pdks_token') ?? ''; } catch { return ''; }
	}

	onMount(() => {
		const k = $page.url.searchParams.get('k');
		const tk = pdksToken();
		if (tk) {
			// Kimlik bu bağlamda var → kişisel uygulamaya geç (k varsa orada anında bas).
			const dest = k
				? `/devam/kur?t=${encodeURIComponent(tk)}&k=${encodeURIComponent(k)}`
				: `/devam/kur?t=${encodeURIComponent(tk)}`;
			window.location.replace(dest);
			return;
		}
		view = 'use-app';
	});
</script>

<svelte:head><title>Giriş / Çıkış</title></svelte:head>

<div class="min-h-screen flex items-center justify-center p-6 bg-gray-50">
	<div class="max-w-sm w-full text-center">
		{#if view === 'loading'}
			<div class="w-12 h-12 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin mx-auto"></div>

		{:else}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-7 space-y-4">
				<div class="w-16 h-16 bg-teal-100 rounded-full flex items-center justify-center mx-auto">
					<svg class="w-9 h-9 text-teal-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" /><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" /></svg>
				</div>
				<h1 class="text-lg font-bold text-gray-900">Uygulamandan okut</h1>
				<p class="text-sm text-gray-600 leading-snug">
					Telefonundaki <strong>kişisel uygulamanı</strong> aç ve <strong>"Tara"</strong>
					düğmesiyle bu ekranı okut.
				</p>
				<div class="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 leading-snug text-left">
					⚠️ Telefonun <strong>kendi kamera uygulamasıyla</strong> bu ekranı okutma — iOS'ta kimlik
					taşınmadığı için çalışmaz. Mutlaka <strong>kendi uygulamandaki "Tara"</strong> ile okut.
				</div>
				<p class="text-xs text-gray-400 leading-snug">
					Uygulaman yoksa: yöneticinden <strong>kişisel QR kartını</strong> iste → bir kez okut →
					açılan sayfayı <strong>ana ekrana ekle</strong>.
				</p>
			</div>
		{/if}
	</div>
</div>
