<script lang="ts">
	import { authState, logout } from '$lib/stores/auth.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { toggleSidebar } from '$lib/stores/ui.svelte';
	import { notificationSettings, toggleSound } from '$lib/stores/notification.svelte';
	import NotificationBell from './NotificationBell.svelte';
	import { isPushSupported, getPushPermissionState, subscribeToPush, requestPushPermission, unsubscribeFromPush } from '$lib/utils/push';
	import { onlinePresence } from '$lib/stores/websocket.svelte';

	let userMenuOpen = $state(false);
	let onlinePopoverOpen = $state(false);
	let pushEnabled = $state(false);
	let pushSupported = $state(false);

	onMount(() => {
		document.addEventListener('click', closeMenu);
		document.addEventListener('click', closeOnlinePopover);
		pushSupported = isPushSupported();
		if (pushSupported) {
			pushEnabled = getPushPermissionState() === 'granted';
		}
		return () => {
			document.removeEventListener('click', closeMenu);
			document.removeEventListener('click', closeOnlinePopover);
		};
	});

	async function handlePushToggle() {
		if (!pushEnabled) {
			const granted = await requestPushPermission();
			if (granted) {
				const success = await subscribeToPush();
				pushEnabled = success;
			}
		} else {
			await unsubscribeFromPush();
			pushEnabled = false;
		}
	}

	async function handleLogout() {
		await logout();
		goto('/');
	}

	function goBack() {
		if (typeof window !== 'undefined') {
			window.history.back();
		}
	}

	function closeMenu(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (!target.closest('.user-menu')) {
			userMenuOpen = false;
		}
	}

	// Check if we're deeper than dashboard root
	function canGoBack(): boolean {
		return $page.url.pathname !== '/dashboard';
	}

	const routeTitles: Record<string, string> = {
		'/dashboard': 'Panel',
		'/dashboard/mesajlasma': 'Mesajlaşma',
		'/dashboard/kalite/sablonlar': 'Şablonlar',
		'/dashboard/kalite/formlar': 'Formlar',
		'/dashboard/finans/nakit-akim': 'Nakit Akım',
		'/dashboard/finans/bankalar': 'Bankalar',
		'/dashboard/finans/doviz': 'Döviz Kurları',
		'/dashboard/finans/cariler': 'Cariler',
		'/dashboard/finans/cekler': 'Verilen Çekler',
		'/dashboard/finans/krediler': 'Krediler',
		'/dashboard/finans/avanslar': 'Alınan Avanslar',
		'/dashboard/sistem/kullanicilar': 'Kullanıcılar',
		'/dashboard/sistem/roller': 'Roller',
		'/dashboard/sistem/moduller': 'Modüller',
		'/dashboard/sistem/audit-loglar': 'Audit Logları',
		'/dashboard/sistem/hata-loglar': 'Hata Logları',
	};

	// Online kullanıcılar — Admin ve Finans Müdürü rolleri için
	let showOnline = $derived(
		authState.user?.role?.name === 'Admin' || authState.user?.role?.name === 'Finans Müdürü'
	);

	// Kendi ID'sini hariç tut
	let onlineCount = $derived.by(() => {
		void onlinePresence.version;
		const myId = authState.user?.id;
		let count = 0;
		for (const id of onlinePresence.ids) {
			if (id !== myId) count++;
		}
		return count;
	});

	let onlineUsersList = $derived.by(() => {
		void onlinePresence.version;
		const myId = authState.user?.id;
		const list: { id: number; name: string }[] = [];
		for (const [id, name] of onlinePresence.names) {
			if (id !== myId) list.push({ id, name });
		}
		return list.sort((a, b) => a.name.localeCompare(b.name, 'tr'));
	});

	function closeOnlinePopover(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (!target.closest('.online-popover')) {
			onlinePopoverOpen = false;
		}
	}

	let pageTitle = $derived((() => {
		const path = $page.url.pathname;
		// Exact match first
		if (routeTitles[path]) return routeTitles[path];
		// Prefix match for sub-routes (e.g. /dashboard/kalite/formlar/123)
		const keys = Object.keys(routeTitles).sort((a, b) => b.length - a.length);
		for (const key of keys) {
			if (path.startsWith(key + '/') || path === key) return routeTitles[key];
		}
		return '';
	})());
</script>

<header class="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-3 md:px-5 shrink-0 safe-top">
	<!-- Left: Hamburger + Back button -->
	<div class="flex items-center gap-2 md:gap-3">
		<!-- Hamburger — sadece mobilde -->
		<button
			onclick={toggleSidebar}
			class="flex md:hidden items-center justify-center touch-target w-11 h-11 -ml-2 rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer"
			title="Menü"
			aria-label="Menüyü aç"
		>
			<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
			</svg>
		</button>

		{#if canGoBack()}
			<button
				onclick={goBack}
				class="flex items-center justify-center touch-target w-11 h-11 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer"
				title="Geri"
				aria-label="Önceki sayfa"
			>
				<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
				</svg>
			</button>
		{/if}
	</div>

	<!-- Center: Page title -->
	{#if pageTitle}
		<h1 class="text-sm font-semibold text-gray-700 truncate">{pageTitle}</h1>
	{/if}

	<!-- Right: Online users + Notification bell + User dropdown -->
	<div class="flex items-center gap-1">
	{#if showOnline}
		<div class="relative online-popover">
			<button
				onclick={() => onlinePopoverOpen = !onlinePopoverOpen}
				class="flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
				title="Online kullanıcılar"
			>
				<span class="relative flex h-2.5 w-2.5">
					{#if onlineCount > 0}
						<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
					{/if}
					<span class="relative inline-flex rounded-full h-2.5 w-2.5 {onlineCount > 0 ? 'bg-green-500' : 'bg-gray-300'}"></span>
				</span>
				<span class="text-xs font-medium {onlineCount > 0 ? 'text-green-600' : 'text-gray-400'}">{onlineCount}</span>
			</button>

			{#if onlinePopoverOpen}
				<div class="absolute top-full right-0 mt-1 w-56 bg-white border border-gray-200 rounded-xl shadow-lg py-2 z-50">
					<div class="px-3 py-1.5 border-b border-gray-100">
						<p class="text-xs font-medium text-gray-500">Online Kullanıcılar ({onlineCount})</p>
					</div>
					{#if onlineUsersList.length === 0}
						<div class="px-3 py-3 text-xs text-gray-400 text-center">Şu anda kimse online değil</div>
					{:else}
						<div class="max-h-48 overflow-y-auto">
							{#each onlineUsersList as ou}
								<div class="flex items-center gap-2 px-3 py-1.5">
									<span class="w-2 h-2 rounded-full bg-green-500 shrink-0"></span>
									<span class="text-sm text-gray-700 truncate">{ou.name}</span>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
	<NotificationBell />
	<div class="relative user-menu">
		<button
			onclick={() => userMenuOpen = !userMenuOpen}
			class="flex items-center gap-2 px-2 md:px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
		>
			<div class="w-7 h-7 rounded-full bg-teal-100 flex items-center justify-center">
				<span class="text-xs font-semibold text-teal-700">
					{authState.user?.first_name?.charAt(0)?.toUpperCase() || '?'}
				</span>
			</div>
			<span class="text-sm text-gray-700 font-medium hidden sm:inline">{authState.user?.first_name} {authState.user?.last_name}</span>
			<svg class="w-3.5 h-3.5 text-gray-400 transition-transform {userMenuOpen ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
			</svg>
		</button>

		{#if userMenuOpen}
			<div class="absolute top-full right-0 mt-1 w-56 max-w-[calc(100vw-1rem)] bg-white border border-gray-200 rounded-xl shadow-lg py-1 z-50">
				<!-- User info -->
				<div class="px-4 py-3 border-b border-gray-100">
					<p class="text-sm font-medium text-gray-900">{authState.user?.first_name} {authState.user?.last_name}</p>
					<p class="text-xs text-gray-400 mt-0.5">@{authState.user?.username}</p>
					<p class="text-xs text-teal-600 mt-1">{authState.user?.role?.name || '-'}</p>
				</div>

				<!-- Profile -->
				<button
					class="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors cursor-pointer"
					onclick={() => { userMenuOpen = false; }}
				>
					<svg class="w-4 h-4 text-gray-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
					</svg>
					Profil
				</button>

				<!-- Bildirim Sesi Toggle -->
				<button
					class="w-full flex items-center justify-between px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors cursor-pointer"
					onclick={(e) => { e.stopPropagation(); toggleSound(!notificationSettings.soundEnabled); }}
				>
					<span class="flex items-center gap-2.5">
						<svg class="w-4 h-4 text-gray-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
						</svg>
						Bildirim Sesi
					</span>
					<div class="relative w-9 h-5 rounded-full transition-colors {notificationSettings.soundEnabled ? 'bg-teal-500' : 'bg-gray-300'}">
						<div class="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform {notificationSettings.soundEnabled ? 'translate-x-4' : ''}"></div>
					</div>
				</button>

				<!-- Anlık Bildirimler Toggle -->
				{#if pushSupported}
					<button
						class="w-full flex items-center justify-between px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors cursor-pointer"
						onclick={(e) => { e.stopPropagation(); handlePushToggle(); }}
					>
						<span class="flex items-center gap-2.5">
							<svg class="w-4 h-4 text-gray-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
							</svg>
							Anlık Bildirimler
						</span>
						<div class="relative w-9 h-5 rounded-full transition-colors {pushEnabled ? 'bg-teal-500' : 'bg-gray-300'}">
							<div class="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform {pushEnabled ? 'translate-x-4' : ''}"></div>
						</div>
					</button>
				{/if}

				<!-- Divider -->
				<div class="h-px bg-gray-100 my-1"></div>

				<!-- Logout -->
				<button
					class="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-red-500 hover:bg-red-50 transition-colors cursor-pointer"
					onclick={handleLogout}
				>
					<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
					</svg>
					Çıkış Yap
				</button>
			</div>
		{/if}
	</div>
	</div>
</header>
