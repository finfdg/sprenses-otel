<script lang="ts">
	// Personel basış sayfası — kiosk QR'ı okutunca açılır (/devam?k=<token>).
	// Çerez (pdks_token) kimliği + k token ile giriş/çıkış kaydeder.
	import { onMount } from 'svelte';
	import { page } from '$app/stores';

	type View = 'loading' | 'punched' | 'status' | 'no-setup' | 'error';
	let view = $state<View>('loading');

	// punched sonucu
	let punchType = $state<'in' | 'out'>('in');
	let punchName = $state('');
	let punchTime = $state('');
	let punchMsg = $state('');
	let minutesToday = $state(0);

	// status (me)
	let meName = $state('');
	let meInside = $state(false);
	let meDept = $state('');

	let errMsg = $state('');

	function fmtMin(m: number): string {
		const h = Math.floor(m / 60);
		return h > 0 ? `${h} saat ${m % 60} dk` : `${m} dk`;
	}

	async function loadStatus() {
		try {
			const res = await fetch('/api/attendance/me', { credentials: 'include' });
			if (res.status === 401) { view = 'no-setup'; return; }
			const data = await res.json();
			meName = data.full_name ?? '';
			meInside = !!data.inside;
			meDept = data.department ?? '';
			minutesToday = data.minutes_today ?? 0;
			view = 'status';
		} catch (e) {
			console.error(e);
			view = 'error';
			errMsg = 'Bağlantı hatası.';
		}
	}

	async function doPunch(k: string) {
		try {
			const res = await fetch('/api/attendance/punch', {
				method: 'POST',
				credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ k }),
			});
			if (res.status === 401) { view = 'no-setup'; return; }
			const data = await res.json().catch(() => ({}));
			if (res.ok) {
				punchType = data.type;
				punchName = data.full_name ?? '';
				punchTime = data.time ?? '';
				punchMsg = data.message ?? '';
				minutesToday = data.minutes_today ?? 0;
				view = 'punched';
			} else {
				view = 'error';
				errMsg = data.detail ?? 'İşlem başarısız.';
			}
		} catch (e) {
			console.error(e);
			view = 'error';
			errMsg = 'Bağlantı hatası.';
		}
	}

	onMount(() => {
		const k = $page.url.searchParams.get('k');
		if (k) doPunch(k);
		else loadStatus();
	});
</script>

<svelte:head><title>Giriş / Çıkış</title></svelte:head>

<div class="min-h-screen flex items-center justify-center p-6 bg-gray-50">
	<div class="max-w-sm w-full text-center">
		{#if view === 'loading'}
			<div class="w-12 h-12 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin mx-auto"></div>

		{:else if view === 'punched'}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-7 space-y-4 {punchType === 'in' ? 'ring-2 ring-emerald-300' : 'ring-2 ring-amber-300'}">
				<div class="w-20 h-20 rounded-full flex items-center justify-center mx-auto {punchType === 'in' ? 'bg-emerald-100' : 'bg-amber-100'}">
					{#if punchType === 'in'}
						<svg class="w-11 h-11 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
					{:else}
						<svg class="w-11 h-11 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M17.25 8.25L21 12m0 0l-3.75 3.75M21 12H9m0-9H6.75A2.25 2.25 0 004.5 5.25v13.5A2.25 2.25 0 006.75 21H9" /></svg>
					{/if}
				</div>
				<div>
					<div class="text-3xl font-bold {punchType === 'in' ? 'text-emerald-700' : 'text-amber-700'}">
						{punchType === 'in' ? 'GİRİŞ' : 'ÇIKIŞ'}
					</div>
					<div class="text-5xl font-bold text-gray-900 tabular-nums mt-1">{punchTime}</div>
				</div>
				<div class="text-lg font-medium text-gray-800">{punchName}</div>
				<p class="text-sm text-gray-500">{punchMsg}</p>
				{#if minutesToday > 0}
					<div class="text-xs text-gray-400 border-t border-gray-100 pt-3">Bugün toplam: {fmtMin(minutesToday)}</div>
				{/if}
			</div>

		{:else if view === 'status'}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-7 space-y-3">
				<div class="text-lg font-semibold text-gray-900">{meName}</div>
				{#if meDept}<div class="text-xs text-gray-500">{meDept}</div>{/if}
				<div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium {meInside ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}">
					<span class="w-2 h-2 rounded-full {meInside ? 'bg-emerald-500' : 'bg-gray-400'}"></span>
					{meInside ? 'İçeridesin' : 'Dışarıdasın'}
				</div>
				{#if minutesToday > 0}<div class="text-xs text-gray-400">Bugün: {fmtMin(minutesToday)}</div>{/if}
				<div class="bg-teal-50 border border-teal-200 rounded-lg p-3 text-sm text-teal-800 leading-snug mt-2">
					📷 {meInside ? 'Çıkış' : 'Giriş'} için, girişteki ekrandaki <strong>karekodu telefon kameranla okut</strong>.
				</div>
			</div>

		{:else if view === 'no-setup'}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-7 space-y-3">
				<div class="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center mx-auto">
					<svg class="w-9 h-9 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" /></svg>
				</div>
				<h1 class="text-lg font-bold text-gray-900">Önce kurulum gerekli</h1>
				<p class="text-sm text-gray-600 leading-snug">
					Bu telefon henüz tanımlı değil. Yöneticinizin verdiği <strong>kişisel QR kartınızı</strong>
					bir kez okutarak kurulumu tamamlayın.
				</p>
			</div>

		{:else}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-7 space-y-3">
				<div class="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto">
					<svg class="w-9 h-9 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
				</div>
				<h1 class="text-lg font-bold text-gray-900">İşlem yapılamadı</h1>
				<p class="text-sm text-gray-600">{errMsg}</p>
				<p class="text-xs text-gray-400">Girişteki ekrandaki <strong>güncel</strong> kodu tekrar okutmayı deneyin.</p>
			</div>
		{/if}
	</div>
</div>
