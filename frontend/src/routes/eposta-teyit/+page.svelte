<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import Button from '$lib/components/Button.svelte';
	import { CheckCircle2, XCircle, Loader2, Mail } from 'lucide-svelte';

	type Status = 'loading' | 'success' | 'error';
	let status = $state<Status>('loading');
	let message = $state('');
	let email = $state('');

	async function verify() {
		const token = $page.url.searchParams.get('token');
		if (!token) {
			status = 'error';
			message = 'Bağlantı geçersiz — token bulunamadı.';
			return;
		}
		try {
			const res = await fetch('/api/auth/verify-email', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ token }),
			});
			const data = await res.json().catch(() => ({}));
			if (res.ok) {
				status = 'success';
				email = data.email || '';
				message = data.detail || 'E-posta adresiniz doğrulandı.';
			} else {
				status = 'error';
				message = data.detail || 'Bağlantı geçersiz veya süresi dolmuş.';
			}
		} catch (e) {
			console.error('E-posta doğrulama isteği başarısız:', e);
			status = 'error';
			message = 'Doğrulama sırasında bir hata oluştu. Lütfen tekrar deneyin.';
		}
	}

	onMount(verify);
</script>

<svelte:head>
	<title>E-posta Doğrulama — Sprenses</title>
</svelte:head>

<div class="min-h-screen flex items-center justify-center px-4 bg-gray-50">
	<div class="w-full max-w-md bg-white border border-gray-200 rounded-2xl shadow-sm p-8 text-center">
		<div class="flex items-center justify-center gap-2 text-gray-800 mb-6">
			<Mail class="w-5 h-5 text-teal-700" />
			<span class="font-semibold">Sprenses Otel</span>
		</div>

		{#if status === 'loading'}
			<Loader2 class="w-12 h-12 mx-auto text-teal-700 animate-spin" />
			<p class="mt-4 text-gray-600">E-posta adresiniz doğrulanıyor…</p>
		{:else if status === 'success'}
			<CheckCircle2 class="w-14 h-14 mx-auto text-green-600" />
			<h1 class="mt-4 text-lg font-semibold text-gray-900">E-posta doğrulandı</h1>
			<p class="mt-2 text-sm text-gray-600">{message}</p>
			{#if email}
				<p class="mt-1 text-sm font-medium text-gray-800">{email}</p>
			{/if}
			<div class="mt-6">
				<Button href="/" fullWidth>Giriş sayfasına dön</Button>
			</div>
		{:else}
			<XCircle class="w-14 h-14 mx-auto text-red-600" />
			<h1 class="mt-4 text-lg font-semibold text-gray-900">Doğrulanamadı</h1>
			<p class="mt-2 text-sm text-gray-600">{message}</p>
			<p class="mt-2 text-xs text-gray-500">
				Bağlantının süresi dolmuş olabilir. Yöneticinizden yeni bir teyit e-postası
				göndermesini isteyebilirsiniz.
			</p>
			<div class="mt-6">
				<Button href="/" variant="secondary" fullWidth>Giriş sayfasına dön</Button>
			</div>
		{/if}
	</div>
</div>
