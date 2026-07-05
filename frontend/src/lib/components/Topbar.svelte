<script lang="ts">
	import { authState, logout } from '$lib/stores/auth.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { toggleSidebar } from '$lib/stores/ui.svelte';
	import { notificationSettings, toggleSound } from '$lib/stores/notification.svelte';
	import NotificationBell from './NotificationBell.svelte';
	import Modal from './Modal.svelte';
	import { isPushSupported, getPushPermissionState, subscribeToPush, requestPushPermission, unsubscribeFromPush } from '$lib/utils/push';
	import { onlinePresence } from '$lib/stores/websocket.svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { Database, Loader2, CheckCircle2, XCircle, MinusCircle, Menu, ArrowLeft, ChevronDown, User, Volume2, Bell, LogOut } from 'lucide-svelte';

	type SednaStep = { key: string; label: string; ok?: boolean; skipped?: boolean; summary: string };

	let userMenuOpen = $state(false);
	let onlinePopoverOpen = $state(false);
	let pushEnabled = $state(false);
	let pushSupported = $state(false);
	// Merkezi Sedna senkronizasyonu (tek butonla tüm içe aktarmalar)
	let sednaConfigured = $state(false);
	let sednaAnyAllowed = $state(false);
	let sednaSyncing = $state(false);
	let sednaModalOpen = $state(false);
	let sednaSteps = $state<SednaStep[]>([]);

	async function loadSednaSyncStatus() {
		try {
			const r = await api.get<{ configured: boolean; any_allowed: boolean }>('/finance/sedna/status');
			sednaConfigured = !!r.configured;
			sednaAnyAllowed = !!r.any_allowed;
		} catch (e) {
			console.error('Sedna senkronizasyon durumu alınamadı:', e);
			sednaConfigured = false;
		}
	}
	async function runSednaSync() {
		if (sednaSyncing) return;
		sednaSyncing = true;
		try {
			const r = await api.post<{ ok_count: number; total: number; steps: SednaStep[] }>(
				'/finance/sedna/sync-all', {}
			);
			sednaSteps = r.steps;
			sednaModalOpen = true;
			showToast(`Sedna: ${r.ok_count}/${r.total} adım tamamlandı`, r.ok_count === r.total ? 'success' : 'info');
		} catch (err: any) {
			console.error('Sedna senkronizasyon hatası:', err);
			showToast(err?.body?.detail || "Sedna'dan veri çekilemedi (SSH tüneli kapalı olabilir)", 'error');
		} finally {
			sednaSyncing = false;
		}
	}

	onMount(() => {
		document.addEventListener('click', closeMenu);
		document.addEventListener('click', closeOnlinePopover);
		document.addEventListener('keydown', closeOnEscape);
		pushSupported = isPushSupported();
		if (pushSupported) {
			pushEnabled = getPushPermissionState() === 'granted';
		}
		loadSednaSyncStatus();
		return () => {
			document.removeEventListener('click', closeMenu);
			document.removeEventListener('click', closeOnlinePopover);
			document.removeEventListener('keydown', closeOnEscape);
		};
	});

	// Esc → açık menü/popover'ı kapat (dışarı tıklamaya ek olarak)
	function closeOnEscape(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			userMenuOpen = false;
			onlinePopoverOpen = false;
		}
	}

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
		'/dashboard/finans/nakit-akim': 'Nakit Akım',
		'/dashboard/finans/bankalar': 'Bankalar',
		'/dashboard/finans/doviz': 'Döviz Kurları',
		'/dashboard/finans/cariler': 'Cariler',
		'/dashboard/finans/cekler': 'Verilen Çekler',
		'/dashboard/finans/krediler': 'Krediler',
		'/dashboard/finans/avanslar': 'Alınan Avanslar',
		'/dashboard/finans/butce': 'Bütçe',
		'/dashboard/finans/onay': 'Onay Kutusu',
		'/dashboard/finans/bankalar/talimatlar': 'Banka Talimatları',
		'/dashboard/muhasebe/vergiler': 'Vergiler',
		'/dashboard/muhasebe/duzenli-odemeler': 'Düzenli Ödemeler',
		'/dashboard/muhasebe/alinan-kiralar': 'Alınan Kiralar',
		'/dashboard/muhasebe/verilen-kiralar': 'Verilen Kiralar',
		'/dashboard/muhasebe/temettu': 'Temettü',
		'/dashboard/ik/maas': 'Maaş',
		'/dashboard/ik/stopaj': 'Stopaj',
		'/dashboard/ik/sgk': 'SGK',
		'/dashboard/satis/otel-rezervasyon': 'Otel Rezervasyon',
		'/dashboard/satis/oda-tipleri': 'Oda Tipleri',
		'/dashboard/satis/ucak-rezervasyon': 'Uçak Rezervasyon',
		'/dashboard/sistem/kullanicilar': 'Kullanıcılar',
		'/dashboard/sistem/roller': 'Roller',
		'/dashboard/sistem/moduller': 'Modüller',
		'/dashboard/sistem/audit-loglar': 'Audit Logları',
		'/dashboard/sistem/hata-loglar': 'Hata Logları',
		'/dashboard/sistem/onay-akisi': 'Onay Akışı',
		'/dashboard/sistem/sunucu': 'Sunucu',
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
			<Menu size={20} />
		</button>

		{#if canGoBack()}
			<button
				onclick={goBack}
				class="flex items-center justify-center touch-target w-11 h-11 rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer"
				title="Geri"
				aria-label="Önceki sayfa"
			>
				<ArrowLeft size={20} />
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
				class="touch-target flex items-center justify-center gap-1.5 px-2 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
				title="Online kullanıcılar"
				aria-label="Online kullanıcılar"
			>
				<span class="relative flex h-2.5 w-2.5">
					{#if onlineCount > 0}
						<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
					{/if}
					<span class="relative inline-flex rounded-full h-2.5 w-2.5 {onlineCount > 0 ? 'bg-green-500' : 'bg-gray-300'}"></span>
				</span>
				<span class="text-xs font-medium {onlineCount > 0 ? 'text-green-600' : 'text-gray-500'}">{onlineCount}</span>
			</button>

			{#if onlinePopoverOpen}
				<div class="absolute top-full right-0 mt-1 w-56 bg-white border border-gray-200 rounded-xl shadow-lg py-2 z-50">
					<div class="px-3 py-1.5 border-b border-gray-100">
						<p class="text-xs font-medium text-gray-500">Online Kullanıcılar ({onlineCount})</p>
					</div>
					{#if onlineUsersList.length === 0}
						<div class="px-3 py-3 text-xs text-gray-500 text-center">Şu anda kimse online değil</div>
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
	{#if sednaConfigured && sednaAnyAllowed}
		<button
			onclick={runSednaSync}
			disabled={sednaSyncing}
			class="touch-target flex items-center justify-center gap-1.5 px-2.5 rounded-lg text-teal-700 hover:bg-teal-50 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
			title="Sedna muhasebe verilerini çek (cari hareketleri · IBAN · verilen çek)"
			aria-label="Sedna senkronizasyonu"
		>
			{#if sednaSyncing}
				<Loader2 size={18} class="animate-spin" />
			{:else}
				<Database size={18} />
			{/if}
			<span class="text-xs font-medium hidden sm:inline">{sednaSyncing ? 'Çekiliyor…' : 'Sedna'}</span>
		</button>
	{/if}
	<NotificationBell />
	<div class="relative user-menu">
		<button
			onclick={() => userMenuOpen = !userMenuOpen}
			class="flex items-center gap-2 px-2 md:px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
		>
			<div class="w-7 h-7 rounded-full bg-teal-700 flex items-center justify-center">
				<span class="text-xs font-semibold text-white">
					{authState.user?.first_name?.charAt(0)?.toUpperCase() || '?'}
				</span>
			</div>
			<span class="text-sm text-gray-700 font-medium hidden sm:inline">{authState.user?.first_name} {authState.user?.last_name}</span>
			<ChevronDown class="w-3.5 h-3.5 text-gray-500 transition-transform {userMenuOpen ? 'rotate-180' : ''}" />
		</button>

		{#if userMenuOpen}
			<div class="absolute top-full right-0 mt-1 w-56 max-w-[calc(100vw-1rem)] bg-white border border-gray-200 rounded-xl shadow-lg py-1 z-50">
				<!-- User info -->
				<div class="px-4 py-3 border-b border-gray-100">
					<p class="text-sm font-medium text-gray-900">{authState.user?.first_name} {authState.user?.last_name}</p>
					<p class="text-xs text-gray-500 mt-0.5">@{authState.user?.username}</p>
					<p class="text-xs text-teal-600 mt-1">{authState.user?.role?.name || '-'}</p>
				</div>

				<!-- Profile -->
				<button
					class="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors cursor-pointer"
					onclick={() => { userMenuOpen = false; }}
				>
					<User size={16} class="text-gray-500" />
					Profil
				</button>

				<!-- Bildirim Sesi Toggle -->
				<button
					class="w-full flex items-center justify-between px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors cursor-pointer"
					onclick={(e) => { e.stopPropagation(); toggleSound(!notificationSettings.soundEnabled); }}
				>
					<span class="flex items-center gap-2.5">
						<Volume2 size={16} class="text-gray-500" />
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
							<Bell size={16} class="text-gray-500" />
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
					class="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors cursor-pointer"
					onclick={handleLogout}
				>
					<LogOut size={16} />
					Çıkış Yap
				</button>
			</div>
		{/if}
	</div>
	</div>
</header>

<!-- Sedna senkronizasyon sonucu -->
<Modal bind:show={sednaModalOpen} title="Sedna Senkronizasyonu" maxWidth="max-w-md">
	<div class="p-4 sm:p-5 space-y-2">
		<p class="text-xs text-gray-500 mb-1">Muhasebe (Sedna) veritabanından çekilen veriler:</p>
		{#each sednaSteps as s}
			<div class="flex items-start gap-2.5 p-2.5 rounded-lg border {s.ok ? 'border-emerald-200 bg-emerald-50' : s.skipped ? 'border-gray-200 bg-gray-50' : 'border-red-200 bg-red-50'}">
				{#if s.ok}
					<CheckCircle2 size={18} class="text-emerald-600 shrink-0 mt-0.5" />
				{:else if s.skipped}
					<MinusCircle size={18} class="text-gray-400 shrink-0 mt-0.5" />
				{:else}
					<XCircle size={18} class="text-red-600 shrink-0 mt-0.5" />
				{/if}
				<div class="min-w-0">
					<p class="text-sm font-medium text-gray-900">{s.label}</p>
					<p class="text-xs text-gray-600 mt-0.5">{s.summary}</p>
				</div>
			</div>
		{/each}
	</div>
</Modal>
