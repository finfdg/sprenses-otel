<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { setAuth, loadAuth } from '$lib/stores/auth.svelte';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);
	let showPassword = $state(false);
	let sessionExpiredMessage = $state('');

	onMount(() => {
		if (loadAuth()) {
			goto('/dashboard');
			return;
		}

		// Oturum sonlandı mesajı kontrolü
		const params = new URLSearchParams(window.location.search);
		if (params.get('session_expired') === '1') {
			sessionExpiredMessage = 'Oturumunuz başka bir cihazdan giriş yapıldığı için sonlandırıldı. Lütfen tekrar giriş yapın.';
			window.history.replaceState({}, '', '/');
		}
	});

	async function handleLogin(e: Event) {
		e.preventDefault();
		error = '';

		if (!username || !password) {
			error = 'Lütfen tüm alanları doldurun.';
			return;
		}

		loading = true;
		try {
			const res = await api.post<{ user: any }>('/auth/login', { username, password });
			setAuth(res.user);
			goto('/dashboard');
		} catch (err: any) {
			error = err.message || 'Giriş başarısız';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Sprenses - Giriş</title>
</svelte:head>

<div class="min-h-screen flex flex-col lg:flex-row bg-stone-50">

	<!-- SOL TARAF: Sadece otel fotoğrafı -->
	<div class="hidden lg:block lg:w-1/2 relative overflow-hidden">
		<picture>
			<source
				type="image/webp"
				srcset="/hotel-bg-1024.webp 1024w, /hotel-bg-1920.webp 1920w"
				sizes="50vw"
			/>
			<source
				type="image/jpeg"
				srcset="/hotel-bg-1024.jpg 1024w, /hotel-bg-1920.jpg 1920w"
				sizes="50vw"
			/>
			<img
				src="/hotel-bg-1920.jpg"
				alt="Sprenses Hotel"
				class="absolute inset-0 w-full h-full object-cover"
				loading="eager"
				decoding="async"
			/>
		</picture>
	</div>

	<!-- SAĞ TARAF: Logo + yazılar + login formu -->
	<div class="flex-1 flex items-center justify-center bg-white px-6 py-12">
		<div class="w-full max-w-md">

			<!-- Logo -->
			<div class="text-center mb-8">
				<img src="/logo.svg" alt="Sprenses Hotel" class="w-44 mx-auto mb-4" />
				<div class="w-12 h-0.5 bg-gradient-to-r from-cyan-500 to-teal-500 mx-auto rounded-full mb-5"></div>
				<h1 class="text-2xl font-bold text-gray-900 mb-1">Hoş Geldiniz</h1>
				<p class="text-gray-400 text-sm">Yönetim paneline erişmek için giriş yapın</p>
			</div>

			<!-- Oturum sonlandı uyarısı -->
			{#if sessionExpiredMessage}
				<div class="bg-amber-50 border border-amber-200 text-amber-700 px-4 py-3 rounded-xl text-sm mb-6 flex items-center gap-2">
					<svg class="w-5 h-5 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
					</svg>
					{sessionExpiredMessage}
				</div>
			{/if}

			<!-- Hata -->
			{#if error}
				<div class="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-xl text-sm mb-6 animate-shake">
					{error}
				</div>
			{/if}

			<!-- Form -->
			<form onsubmit={handleLogin} class="space-y-5">
				<div>
					<label for="username" class="block text-gray-500 text-xs font-medium mb-2 uppercase tracking-wider">Kullanıcı Adı</label>
					<div class="relative">
						<input
							type="text"
							id="username"
							bind:value={username}
							placeholder="kullanıcı adınızı girin"
							class="w-full px-4 py-3.5 pl-11 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-300 outline-none focus:border-teal-400 focus:bg-white focus:ring-2 focus:ring-teal-100 transition-all"
						/>
						<svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-300" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"/>
						</svg>
					</div>
				</div>

				<div>
					<label for="password" class="block text-gray-500 text-xs font-medium mb-2 uppercase tracking-wider">Şifre</label>
					<div class="relative">
						<input
							type={showPassword ? 'text' : 'password'}
							id="password"
							bind:value={password}
							placeholder="••••••••"
							class="w-full px-4 py-3.5 pl-11 pr-11 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-300 outline-none focus:border-teal-400 focus:bg-white focus:ring-2 focus:ring-teal-100 transition-all"
						/>
						<svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-300" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
						</svg>
						<button
							type="button"
							aria-label="Şifreyi göster"
							onclick={() => showPassword = !showPassword}
							class="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500 transition-colors cursor-pointer"
						>
							{#if showPassword}
								<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"/>
								</svg>
							{:else}
								<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
									<path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
								</svg>
							{/if}
						</button>
					</div>
				</div>

				<button
					type="submit"
					disabled={loading}
					class="w-full py-3.5 mt-2 bg-gradient-to-r from-cyan-600 to-teal-600 rounded-xl text-white font-semibold tracking-wide hover:-translate-y-0.5 hover:shadow-lg hover:shadow-cyan-200 active:translate-y-0 transition-all disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
				>
					{#if loading}
						<svg class="animate-spin h-5 w-5 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
							<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
							<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
						</svg>
					{:else}
						Giriş Yap
					{/if}
				</button>
			</form>

			<p class="text-gray-300 text-xs text-center mt-10">&copy; 2026 Sprenses Hotel &middot; Tüm hakları saklıdır.</p>
		</div>
	</div>
</div>

<style>
	@keyframes shake {
		0%, 100% { transform: translateX(0); }
		25% { transform: translateX(-6px); }
		75% { transform: translateX(6px); }
	}
	.animate-shake { animation: shake 0.4s ease-in-out; }
</style>
