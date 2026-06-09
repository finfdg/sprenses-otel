<script lang="ts">
	// Kiosk ekranı — girişteki tablet/TV'de açılır. SOL: yalnız dönen QR. SAĞ: canlı
	// giriş/çıkış paneli (kişi adı + GİRİŞ/ÇIKIŞ + saat). KIOSK_KEY ?key= ile gelir.
	// QR panelden ayarlanan süreye göre yenilenir; son hareketler 3sn'de bir çekilir
	// (kiosk public+oturumsuz olduğu için kimlikli WS taşınamaz — kiosk display istisnası).
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';

	const CONFIG_POLL_MS = 15000; // ayar değişikliğini yakalama
	const RECENT_POLL_MS = 1000;  // son hareketi sık kontrol (hızlı art arda basışta isim hemen değişsin)
	const HOLD_MS = 5000;         // isim en geç bu kadar ekranda kalır, sonra silinir

	let key = $state('');
	let tick = $state(0);
	let clock = $state('');
	let refreshMs = 4000;
	let displayed = $state<any | null>(null); // ekranda gösterilen son hareket (5sn sonra silinir)
	let lastSeenId: number | null = null;     // tekrar göstermemek için son görülen log id
	let qrTimer: ReturnType<typeof setInterval> | null = null;
	let clockTimer: ReturnType<typeof setInterval> | null = null;
	let configTimer: ReturnType<typeof setInterval> | null = null;
	let recentTimer: ReturnType<typeof setInterval> | null = null;
	let clearTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	function updateClock() {
		clock = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}
	function fmtTime(iso: string): string {
		return new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
	}

	// Panelden ayarlanan yenileme süresini çek (yoksa mevcut değeri koru). Hep geçerlilikten kısadır.
	async function fetchRefreshMs(): Promise<number> {
		if (!key) return refreshMs;
		try {
			const res = await fetch(`/api/attendance/kiosk/config?key=${encodeURIComponent(key)}`);
			if (res.ok) {
				const d = await res.json();
				if (d.refresh_sec) return d.refresh_sec * 1000;
			}
		} catch (e) { console.error('Kiosk config alınamadı:', e); }
		return refreshMs;
	}
	// Yeni hareketi göster + 5sn'lik silme zamanlayıcısını (yeniden) kur.
	function showPunch(p: any) {
		displayed = p;
		if (clearTimer) clearTimeout(clearTimer);
		clearTimer = setTimeout(() => { displayed = null; }, HOLD_MS);
	}
	async function fetchRecent() {
		if (!key) return;
		try {
			const res = await fetch(`/api/attendance/kiosk/recent?key=${encodeURIComponent(key)}&limit=1`);
			if (!res.ok) return;
			const d = await res.json();
			const latest = (d.items && d.items[0]) || null;
			if (!latest || latest.id === lastSeenId) return; // yeni basış yoksa dokunma (timer siler)
			const firstLoad = lastSeenId === null;
			lastSeenId = latest.id;
			// İlk yüklemede yalnızca gerçekten taze (son 5sn) basışı göster — eski kaydı gösterme
			const fresh = Date.now() - new Date(latest.punched_at).getTime() < HOLD_MS;
			if (!firstLoad || fresh) showPunch(latest);
		} catch (e) { console.error('Son hareketler alınamadı:', e); }
	}

	function startQrTimer() {
		if (qrTimer) clearInterval(qrTimer);
		qrTimer = setInterval(() => (tick = Date.now()), refreshMs);
	}

	onMount(async () => {
		key = $page.url.searchParams.get('key') ?? '';
		updateClock();
		clockTimer = setInterval(updateClock, 1000);
		tick = Date.now();
		refreshMs = await fetchRefreshMs();
		if (destroyed) return;
		startQrTimer();
		fetchRecent();
		recentTimer = setInterval(fetchRecent, RECENT_POLL_MS);
		// Ayar değişikliğini otomatik yakala → yenileme aralığını CANLI güncelle (sayfa yenilemeden)
		configTimer = setInterval(async () => {
			const newMs = await fetchRefreshMs();
			if (!destroyed && newMs !== refreshMs) {
				refreshMs = newMs;
				tick = Date.now();
				startQrTimer();
			}
		}, CONFIG_POLL_MS);
	});
	onDestroy(() => {
		destroyed = true;
		if (qrTimer) clearInterval(qrTimer);
		if (clockTimer) clearInterval(clockTimer);
		if (configTimer) clearInterval(configTimer);
		if (recentTimer) clearInterval(recentTimer);
		if (clearTimer) clearTimeout(clearTimer);
	});
</script>

<svelte:head><title>Personel Giriş/Çıkış</title></svelte:head>

<div class="min-h-screen bg-gradient-to-br from-teal-700 to-teal-900 text-white">
	{#if !key}
		<div class="min-h-screen flex items-center justify-center p-6">
			<div class="text-center">
				<h1 class="text-2xl font-bold mb-2">Geçersiz Kiosk Linki</h1>
				<p class="text-teal-100">Yönetici panelinden "Kiosk Linki"ni alıp bu cihazda açın.</p>
			</div>
		</div>
	{:else}
		<div class="min-h-screen flex flex-col lg:flex-row">
			<!-- SOL: yalnız QR -->
			<div class="lg:w-1/2 flex flex-col items-center justify-center p-6 lg:p-10">
				<div class="bg-white rounded-3xl p-5 sm:p-6 shadow-2xl">
					<img
						src={`/api/attendance/kiosk/qr?key=${encodeURIComponent(key)}&_=${tick}`}
						alt="Giriş/Çıkış karekodu"
						class="w-64 h-64 sm:w-80 sm:h-80 lg:w-[26rem] lg:h-[26rem] block"
					/>
				</div>
				<p class="text-teal-100 mt-5 text-base sm:text-lg text-center max-w-md leading-snug">
					Kişisel <strong>uygulamanızı</strong> açıp <strong>"Tara"</strong> ile bu karekodu okutun
					<span class="block text-teal-200/70 text-sm mt-1">(telefonun kendi kamerasıyla değil — uygulamanızdaki Tara ile)</span>
				</p>
			</div>

			<!-- SAĞ: canlı giriş/çıkış paneli -->
			<div class="lg:w-1/2 bg-black/15 flex flex-col p-6 lg:p-10">
				<div class="flex items-baseline justify-between gap-4 border-b border-white/10 pb-4">
					<h1 class="text-2xl sm:text-3xl font-bold tracking-tight">Personel Giriş / Çıkış</h1>
					<div class="text-3xl sm:text-4xl font-bold tabular-nums">{clock}</div>
				</div>

				{#if displayed}
					{@const last = displayed}
					<!-- Son hareket (büyük) — 5sn sonra otomatik silinir -->
					<div class="mt-6 rounded-2xl border p-5 sm:p-6 shadow-xl text-white {last.type === 'in' ? 'bg-blue-700 border-blue-500' : 'bg-red-700 border-red-500'}">
						<div class="text-sm text-white/70">Son hareket</div>
						<div class="text-3xl sm:text-4xl font-bold mt-1 leading-tight">{last.full_name}</div>
						{#if last.department}<div class="text-sm text-white/60">{last.department}</div>{/if}
						<div class="flex items-center gap-4 mt-3">
							<span class="text-2xl sm:text-3xl font-extrabold text-white">
								{last.type === 'in' ? 'GİRİŞ' : 'ÇIKIŞ'}
							</span>
							<span class="text-2xl sm:text-3xl tabular-nums text-white/90">{fmtTime(last.punched_at)}</span>
						</div>
					</div>
					<div class="flex-1"></div>
				{:else}
					<div class="flex-1 flex items-center justify-center text-teal-100/50 text-lg">Henüz hareket yok</div>
				{/if}

				<p class="text-teal-100 text-xs mt-4 pt-3 border-t border-white/10">Kod güvenlik için sürekli yenilenir</p>
			</div>
		</div>
	{/if}
</div>
