<script lang="ts">
	// Kiosk ekranı — girişteki tablet/TV'de açılır. SOL: yalnız dönen QR. SAĞ: canlı
	// giriş/çıkış paneli (kişi adı + GİRİŞ/ÇIKIŞ + saat). KIOSK_KEY ?key= ile gelir.
	// QR panelden ayarlanan süreye göre yenilenir; son hareketler 3sn'de bir çekilir
	// (kiosk public+oturumsuz olduğu için kimlikli WS taşınamaz — kiosk display istisnası).
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';

	const CONFIG_POLL_MS = 15000; // ayar değişikliğini yakalama
	const RECENT_POLL_MS = 3000;  // son hareketleri tazeleme

	let key = $state('');
	let tick = $state(0);
	let clock = $state('');
	let refreshMs = 4000;
	let recent = $state<any[]>([]);
	let qrTimer: ReturnType<typeof setInterval> | null = null;
	let clockTimer: ReturnType<typeof setInterval> | null = null;
	let configTimer: ReturnType<typeof setInterval> | null = null;
	let recentTimer: ReturnType<typeof setInterval> | null = null;
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
	async function fetchRecent() {
		if (!key) return;
		try {
			const res = await fetch(`/api/attendance/kiosk/recent?key=${encodeURIComponent(key)}&limit=8`);
			if (res.ok) { const d = await res.json(); recent = d.items ?? []; }
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

				{#if recent.length}
					{@const last = recent[0]}
					<!-- Son hareket (büyük) -->
					<div class="mt-6 rounded-2xl border p-5 sm:p-6 {last.type === 'in' ? 'bg-emerald-500/20 border-emerald-400/40' : 'bg-amber-500/20 border-amber-400/40'}">
						<div class="text-sm text-teal-100/70">Son hareket</div>
						<div class="text-3xl sm:text-4xl font-bold mt-1 leading-tight">{last.full_name}</div>
						{#if last.department}<div class="text-sm text-teal-100/60">{last.department}</div>{/if}
						<div class="flex items-center gap-4 mt-3">
							<span class="text-2xl sm:text-3xl font-extrabold {last.type === 'in' ? 'text-emerald-300' : 'text-amber-300'}">
								{last.type === 'in' ? 'GİRİŞ' : 'ÇIKIŞ'}
							</span>
							<span class="text-2xl sm:text-3xl tabular-nums">{fmtTime(last.punched_at)}</span>
						</div>
					</div>

					<!-- Önceki hareketler -->
					{#if recent.length > 1}
						<div class="mt-6 min-h-0 flex-1 overflow-y-auto">
							<div class="text-xs uppercase tracking-wider text-teal-200/50 mb-2">Önceki hareketler</div>
							<div class="space-y-2">
								{#each recent.slice(1) as r (r.id)}
									<div class="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2.5">
										<span class="font-medium truncate">{r.full_name}</span>
										<span class="flex items-center gap-3 shrink-0 ml-2">
											<span class="text-sm font-semibold {r.type === 'in' ? 'text-emerald-300' : 'text-amber-300'}">{r.type === 'in' ? 'Giriş' : 'Çıkış'}</span>
											<span class="text-sm tabular-nums text-teal-100/70">{fmtTime(r.punched_at)}</span>
										</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				{:else}
					<div class="flex-1 flex items-center justify-center text-teal-100/50 text-lg">Henüz hareket yok</div>
				{/if}

				<p class="text-teal-200/50 text-xs mt-4 pt-3 border-t border-white/10">Kod güvenlik için sürekli yenilenir</p>
			</div>
		</div>
	{/if}
</div>
