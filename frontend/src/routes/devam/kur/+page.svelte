<script lang="ts">
	// Personel uygulaması — kişisel QR karttan açılır (?t=access_token), ana ekrana eklenir.
	// Kimlik URL'deki t'dir (kalıcı). Giriş/çıkış için UYGULAMA-İÇİ kamerayla girişteki
	// ekranın QR'ı taranır → her şey tek bağlamda olur (iOS kamera-izole-bağlam sorunu yok).
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import jsQR from 'jsqr';

	type View = 'loading' | 'ready' | 'scanning' | 'result' | 'error';
	let view = $state<View>('loading');

	let token = $state('');
	let name = $state('');
	let dept = $state('');
	let inside = $state(false);
	let minutesToday = $state(0);
	let errMsg = $state('');
	let scanError = $state('');

	// ─── TANI (geçici) — iOS kimlik/kamera akışını yerinde görmek için ───
	let dbg = $state<string[]>([]);
	function dlog(s: string) { dbg = [...dbg, s]; }

	// punch sonucu
	let punchType = $state<'in' | 'out'>('in');
	let punchTime = $state('');
	let punchMsg = $state('');

	let videoEl: HTMLVideoElement;
	let canvasEl: HTMLCanvasElement;
	let stream: MediaStream | null = null;
	let rafId = 0;

	function fmtMin(m: number): string {
		const h = Math.floor(m / 60);
		return h > 0 ? `${h} saat ${m % 60} dk` : `${m} dk`;
	}

	async function loadMe() {
		try {
			dlog(`me → token ${token ? 'VAR(' + token.slice(0, 6) + '…)' : 'YOK'}`);
			const res = await fetch('/api/attendance/me', { headers: { 'X-Pdks-Token': token } });
			dlog(`me ← HTTP ${res.status}`);
			if (res.status === 401) { view = 'error'; errMsg = 'Bu kart tanımlı değil veya pasif.'; return; }
			const d = await res.json();
			name = d.full_name ?? '';
			dept = d.department ?? '';
			inside = !!d.inside;
			minutesToday = d.minutes_today ?? 0;
			view = 'ready';
		} catch (e) {
			console.error(e);
			view = 'error';
			errMsg = 'Bağlantı hatası.';
		}
	}

	async function startScan() {
		scanError = '';
		view = 'scanning';
		try {
			dlog('kamera isteniyor (getUserMedia)…');
			stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
			videoEl.srcObject = stream;
			await videoEl.play();
			dlog('kamera AÇIK · tarama başladı');
			rafId = requestAnimationFrame(tick);
		} catch (e: any) {
			console.error('Kamera hatası:', e);
			dlog(`kamera HATA: ${e?.name || e}`);
			scanError = 'Kamera açılamadı. Tarayıcı kamera iznini verin.';
			view = 'ready';
		}
	}

	function tick() {
		if (view !== 'scanning' || !videoEl) return;
		if (videoEl.readyState >= 2) {
			const w = videoEl.videoWidth;
			const h = videoEl.videoHeight;
			if (w && h) {
				canvasEl.width = w;
				canvasEl.height = h;
				const ctx = canvasEl.getContext('2d', { willReadFrequently: true });
				if (ctx) {
					ctx.drawImage(videoEl, 0, 0, w, h);
					const img = ctx.getImageData(0, 0, w, h);
					const code = jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
					if (code && code.data) { onDecode(code.data); return; }
				}
			}
		}
		rafId = requestAnimationFrame(tick);
	}

	function stopScan() {
		if (rafId) cancelAnimationFrame(rafId);
		rafId = 0;
		if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
	}

	function onDecode(data: string) {
		stopScan();
		dlog(`QR okundu: ${data.slice(0, 32)}…`);
		// Kiosk QR'ı "https://.../devam?k=<token>" taşır — k'yı ayıkla
		let k = data;
		try { const u = new URL(data); k = u.searchParams.get('k') ?? data; } catch { /* ham token */ }
		doPunch(k);
	}

	async function doPunch(k: string) {
		view = 'loading';
		try {
			dlog(`punch → k=${k.slice(0, 10)}… token ${token ? 'VAR(' + token.slice(0, 6) + '…)' : 'YOK'}`);
			const res = await fetch('/api/attendance/punch', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', 'X-Pdks-Token': token },
				body: JSON.stringify({ k }),
			});
			dlog(`punch ← HTTP ${res.status}`);
			const d = await res.json().catch(() => ({}));
			if (res.ok) {
				punchType = d.type;
				punchTime = d.time ?? '';
				punchMsg = d.message ?? '';
				minutesToday = d.minutes_today ?? 0;
				view = 'result';
			} else {
				scanError = d.detail ?? 'İşlem başarısız.';
				view = 'ready';
				loadMe();
			}
		} catch (e) {
			console.error(e);
			scanError = 'Bağlantı hatası.';
			view = 'ready';
		}
	}

	function backToReady() {
		scanError = '';
		loadMe();
	}

	onMount(() => {
		const sa = (navigator as any).standalone === true
			|| (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);
		dlog(`sayfa=/devam/kur · ${sa ? 'ANA-EKRAN (standalone)' : 'TARAYICI sekmesi'}`);
		token = $page.url.searchParams.get('t') ?? '';
		dlog(`URL t=${token ? 'VAR' : 'YOK'}`);
		if (!token) { view = 'error'; errMsg = 'Geçersiz link.'; return; }
		try { localStorage.setItem('pdks_token', token); } catch { /* yoksay */ }
		loadMe();
	});
	onDestroy(stopScan);
</script>

<svelte:head><title>Giriş / Çıkış</title></svelte:head>

<div class="min-h-screen flex items-center justify-center p-5 bg-gray-50">
	<div class="max-w-sm w-full">
		{#if view === 'loading'}
			<div class="text-center py-16"><div class="w-12 h-12 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin mx-auto"></div></div>

		{:else if view === 'ready'}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 text-center space-y-4">
				<div class="text-xl font-bold text-gray-900">{name}</div>
				{#if dept}<div class="text-xs text-gray-500 -mt-2">{dept}</div>{/if}
				<div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium {inside ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}">
					<span class="w-2 h-2 rounded-full {inside ? 'bg-emerald-500' : 'bg-gray-400'}"></span>
					{inside ? 'İçeridesin' : 'Dışarıdasın'}{minutesToday > 0 ? ` · bugün ${fmtMin(minutesToday)}` : ''}
				</div>

				{#if scanError}
					<div class="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">{scanError}</div>
				{/if}

				<button onclick={startScan} class="w-full py-4 rounded-xl text-white font-bold text-lg {inside ? 'bg-amber-600 hover:bg-amber-700' : 'bg-emerald-600 hover:bg-emerald-700'} active:scale-95 transition-all cursor-pointer inline-flex items-center justify-center gap-2">
					<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" /><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" /></svg>
					{inside ? 'ÇIKIŞ — Karekodu Tara' : 'GİRİŞ — Karekodu Tara'}
				</button>
				<p class="text-xs text-gray-400 leading-snug">Girişteki ekranın karekoduna telefonu tut.</p>
				<div class="bg-teal-50 border border-teal-200 rounded-lg p-2.5 text-[11px] text-teal-800 leading-snug">
					💡 Bu sayfayı telefonun <strong>ana ekranına ekle</strong> — her gün hızlıca aç.
				</div>
			</div>

		{:else if view === 'scanning'}
			<div class="bg-black rounded-2xl overflow-hidden shadow-xl">
				<!-- svelte-ignore a11y_media_has_caption -->
				<video bind:this={videoEl} playsinline muted autoplay class="w-full aspect-square object-cover"></video>
				<div class="p-4 text-center bg-black">
					<p class="text-white text-sm mb-3">Girişteki ekranın karekodunu çerçeveye al</p>
					<button onclick={() => { stopScan(); view = 'ready'; }} class="px-5 py-2 rounded-lg bg-white/20 text-white text-sm font-medium cursor-pointer">Vazgeç</button>
				</div>
			</div>
			<canvas bind:this={canvasEl} class="hidden"></canvas>

		{:else if view === 'result'}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-7 text-center space-y-4 {punchType === 'in' ? 'ring-2 ring-emerald-300' : 'ring-2 ring-amber-300'}">
				<div class="w-20 h-20 rounded-full flex items-center justify-center mx-auto {punchType === 'in' ? 'bg-emerald-100' : 'bg-amber-100'}">
					<svg class="w-11 h-11 {punchType === 'in' ? 'text-emerald-600' : 'text-amber-600'}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
				</div>
				<div class="text-3xl font-bold {punchType === 'in' ? 'text-emerald-700' : 'text-amber-700'}">{punchType === 'in' ? 'GİRİŞ' : 'ÇIKIŞ'}</div>
				<div class="text-5xl font-bold text-gray-900 tabular-nums">{punchTime}</div>
				<p class="text-sm text-gray-500">{punchMsg}</p>
				<button onclick={backToReady} class="w-full py-3 rounded-xl bg-gray-100 text-gray-700 font-medium cursor-pointer">Tamam</button>
			</div>

		{:else}
			<div class="bg-white rounded-2xl shadow-sm border border-gray-200 p-7 text-center space-y-3">
				<div class="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto">
					<svg class="w-9 h-9 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
				</div>
				<h1 class="text-lg font-bold text-gray-900">Hata</h1>
				<p class="text-sm text-gray-600">{errMsg}</p>
				<p class="text-xs text-gray-400">Yöneticinizden güncel QR kartınızı isteyin.</p>
			</div>
		{/if}

		<!-- TANI paneli (geçici) -->
		{#if dbg.length && view !== 'scanning'}
			<div class="mt-4 bg-gray-900 text-gray-100 rounded-xl p-3 text-left font-mono text-[11px] leading-relaxed break-all">
				<div class="text-gray-400 mb-1">🔎 tanı kaydı</div>
				{#each dbg as line}<div>• {line}</div>{/each}
			</div>
		{/if}
	</div>
</div>
