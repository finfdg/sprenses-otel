<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { loadAuth, refreshAuth, logout, authState, hasPermission } from '$lib/stores/auth.svelte';
	import { requiredModulesForPath } from '$lib/config/navigation';
	import { sidebar, closeSidebar } from '$lib/stores/ui.svelte';
	import { unlockAudio } from '$lib/stores/notification.svelte';
	import { connectWebSocket, disconnectWebSocket, onWsEvent, resetReconnect, wsState } from '$lib/stores/websocket.svelte';
	import { isPushSupported, getPushPermissionState, subscribeToPush, requestPushPermission } from '$lib/utils/push';
	import { showToast } from '$lib/stores/toast.svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Topbar from '$lib/components/Topbar.svelte';
	import ToastContainer from '$lib/components/ToastContainer.svelte';

	let { children } = $props();
	let ready = $state(false);
	let wsUnsubscribers: Array<() => void> = [];
	let wsConnectedOnce = false;

	// ── Route guard (derinlemesine savunma) ──────────────────────────────
	// Yetkisiz kullanıcı bir modül sayfasına gitmeye çalışırsa, sayfanın veri
	// çekmesi beklenmeden panele yönlendirilir. Backend zaten her endpoint'i
	// require_permission ile 403'ler (asıl kapı orada); bu, temiz UX + ikinci
	// savunma katmanıdır. Gerekli izin haritası tek kaynaktan: lib/config/navigation.
	$effect(() => {
		if (!ready) return;
		const user = authState.user;
		if (!user) return;
		const pathname = $page.url.pathname;
		const required = requiredModulesForPath(pathname);
		if (required && !required.some((c) => hasPermission(c, 'view'))) {
			showToast('Bu sayfaya erişim yetkiniz yok', 'error');
			goto('/dashboard', { replaceState: true });
		}
	});

	onMount(() => {
		// ── Belge kilidi + iOS klavye ofset telafisi (Topbar takılma düzeltmesi) ──
		// (1) html/body kilidi: iOS Safari'de belge kaydırılabiliyor (kök min-h-screen
		//     100vh > h-dvh taşması + rubber-band chaining) → Topbar belgeyle çıkıp
		//     takılı kalıyordu. CSS: app.css `.app-shell-lock`.
		document.documentElement.classList.add('app-shell-lock');
		// (2) iOS klavyesi input odağında overflow-hidden'a RAĞMEN belgeyi kaydırır
		//     ve kapanınca çoğu zaman geri almaz (PWA standalone dahil). Klavye
		//     kapanışını visualViewport resize + focusout ile yakala (event-driven —
		//     polling değil), odak bir form alanında DEĞİLSE ofseti sıfırla.
		const resetViewportScroll = () => {
			const a = document.activeElement;
			if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return; // yazma sürüyor
			if (window.scrollY !== 0 || (window.visualViewport?.offsetTop ?? 0) > 0) {
				window.scrollTo(0, 0);
			}
		};
		let focusoutTimer: ReturnType<typeof setTimeout> | undefined;
		const onFocusOut = () => {
			// iOS klavye kapanış animasyonunun bitmesini bekle
			clearTimeout(focusoutTimer);
			focusoutTimer = setTimeout(resetViewportScroll, 250);
		};
		window.visualViewport?.addEventListener('resize', resetViewportScroll);
		window.addEventListener('focusout', onFocusOut);

		// ── Global WS canlandırma (R4) ─────────────────────────────────────
		// Ağ geri geldiğinde veya sekme tekrar görünür olduğunda reconnect sayacını
		// sıfırlayıp bağlantıyı canlandır (resetReconnect idempotent — bağlıysa no-op;
		// mesajlaşma sayfasındaki yerel handler ile çakışmaz).
		const onNetworkOnline = () => resetReconnect();
		const onWsVisibility = () => {
			if (document.visibilityState === 'visible' && !wsState.connected) {
				resetReconnect();
			}
		};
		window.addEventListener('online', onNetworkOnline);
		document.addEventListener('visibilitychange', onWsVisibility);

		if (!loadAuth()) {
			goto('/');
		} else {
			ready = true;
			connectWebSocket();

			// Kullanıcı izinlerini API'den güncelleyerek localStorage'daki eski veriyi tazele
			refreshAuth();

			// WebSocket: Yeniden bağlantıda izinleri tazele (sunucu yeniden başladığında vb.)
			wsUnsubscribers.push(
				onWsEvent('connected', async () => {
					if (wsConnectedOnce) {
						// WS yeniden bağlandı — modül/izin değişiklikleri olmuş olabilir
						await refreshAuth();
					}
					wsConnectedOnce = true;
				}),
				// WebSocket: Yetki değişikliği bildirimi — anlık güncelleme
				onWsEvent('permission_changed', async () => {
					await refreshAuth();
					showToast('Yetki ve izinleriniz güncellendi', 'info');
				}),
				// Banka ekstresi yüklenince bildirim (tüm sayfalarda)
			onWsEvent('bank_statement_uploaded', (data: any) => {
				const uploader = data.uploader_name ?? '';
				const fileName = data.file_name ?? '';
				const newTx = data.new_transactions ?? 0;
				const skipped = data.skipped_transactions ?? 0;
				const iban = data.account_iban ?? '';

				showToast(
					`${uploader} yeni ekstre yükledi: ${fileName} — ${newTx} yeni, ${skipped} mükerrer işlem (${iban})`,
					'info',
					8000,
				);
			}),
			onWsEvent('force_logout', async () => {
					showToast('Hesabınız devre dışı bırakıldı. Çıkış yapılıyor...', 'error');
					setTimeout(async () => {
						await logout();
						goto('/');
					}, 2000);
				}),
				onWsEvent('session_expired', async (data: any) => {
					const reason = data.reason || 'Oturumunuz başka bir cihazdan sonlandırıldı';
					showToast(reason, 'error', 5000);
					setTimeout(async () => {
						await logout();
						window.location.href = '/?session_expired=1';
					}, 2000);
				})
			);

			// Service worker'a mevcut kullanıcı ID'sini bildir (push filtreleme için)
			if ('serviceWorker' in navigator) {
				const currentUser = authState.user;
				if (currentUser) {
					navigator.serviceWorker.ready.then(reg => {
						reg.active?.postMessage({
							type: 'SET_USER_ID',
							userId: currentUser.id
						});
					});
				}
			}

			// Push notification: izin verilmişse her açılışta aboneliği yenile/doğrula
			if (isPushSupported()) {
				const permState = getPushPermissionState();
				if (permState === 'granted') {
					subscribeToPush().catch(err => console.error('Push aboneliği başarısız:', err));
				} else if (permState === 'default') {
					setTimeout(async () => {
						const granted = await requestPushPermission();
						if (granted) {
							await subscribeToPush();
						}
					}, 5000);
				}
			}
		}

		// iOS ses kısıtlaması için ilk etkileşimde audio unlock
		const unlock = () => {
			unlockAudio();
			document.removeEventListener('click', unlock);
			document.removeEventListener('keydown', unlock);
		};
		document.addEventListener('click', unlock, { once: true });
		document.addEventListener('keydown', unlock, { once: true });

		return () => {
			document.documentElement.classList.remove('app-shell-lock');
			window.visualViewport?.removeEventListener('resize', resetViewportScroll);
			window.removeEventListener('focusout', onFocusOut);
			window.removeEventListener('online', onNetworkOnline);
			document.removeEventListener('visibilitychange', onWsVisibility);
			clearTimeout(focusoutTimer);
			document.removeEventListener('click', unlock);
			document.removeEventListener('keydown', unlock);
			wsUnsubscribers.forEach(unsub => unsub());
			disconnectWebSocket();
		};
	});
</script>

{#if ready}
	<div class="flex h-dvh overflow-hidden safe-x">
		<!-- Mobil backdrop overlay -->
		{#if sidebar.open}
			<button
				class="fixed inset-0 bg-black/40 z-30 md:hidden cursor-default"
				onclick={closeSidebar}
				aria-label="Menüyü kapat"
			></button>
		{/if}

		<!-- Sidebar -->
		<Sidebar />

		<!-- Main area -->
		<div class="flex-1 flex flex-col overflow-hidden">
			<!-- Topbar -->
			<Topbar />

			<!-- Content -->
			<main class="flex-1 overflow-y-auto overflow-x-hidden p-3 md:p-6 bg-gray-50">
				{@render children()}
			</main>
		</div>
	</div>

	<ToastContainer />
{/if}
