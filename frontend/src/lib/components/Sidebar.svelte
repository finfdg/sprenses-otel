<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { hasPermission, authState } from '$lib/stores/auth.svelte';
	import { api } from '$lib/api';
	import { sidebar, closeSidebar } from '$lib/stores/ui.svelte';
	import { playNotificationSound, isConversationMuted, setMutedConversations, mutedConversationIds } from '$lib/stores/notification.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';

	let collapsed = $state(false);
	let expandedGroups = $state<Record<string, boolean>>({ quality: false, finance: false, accounting: false, hr: false, sales: false, system: false });
	let unreadCount = $state(0);
	let wsUnsubscribers: Array<() => void> = [];
	let visibilityHandler: (() => void) | null = null;

	// Reaktif izin haritası — authState güncellendiğinde sidebar otomatik güncellenir
	let permMap = $derived.by(() => {
		const u = authState.user;
		if (u?.permissions) {
			const map: Record<string, { can_view: boolean; can_use: boolean }> = {};
			for (const p of u.permissions) {
				map[p.module_code] = { can_view: p.can_view, can_use: p.can_use };
			}
			return map;
		}
		return {};
	});

	function hasPerm(moduleCode: string, action: 'view' | 'use' = 'view'): boolean {
		const p = permMap[moduleCode];
		if (!p) return false;
		return action === 'view' ? p.can_view : p.can_use;
	}

	// markAsRead optimistik güncellemesinden sonra sunucu sync'ini engelle
	// (PATCH tamamlanmadan GET stale veri döner → sayı geri sıçrar)
	let lastLocalUpdateAt = 0;
	const SYNC_COOLDOWN_MS = 3000;

	async function syncUnreadCount() {
		if (Date.now() - lastLocalUpdateAt < SYNC_COOLDOWN_MS) return;
		try {
			const data = await api.get<{ total_unread: number }>('/messages/unread-count');
			// Fetch sırasında optimistik güncelleme geldiyse sonucu görmezden gel
			if (Date.now() - lastLocalUpdateAt < SYNC_COOLDOWN_MS) return;
			unreadCount = data.total_unread;
		} catch (err) { console.error('Okunmamış sayısı alınamadı:', err); }
	}

	onMount(() => {
		if (hasPermission('messaging')) {
			// İlk yüklemede sunucudan güncel sayıyı al
			syncUnreadCount();

			// Muted konuşma bilgisini yükle (mesajlaşma sayfası açılmadan önce de gerekli)
			if (mutedConversationIds.ids.size === 0) {
				api.get<Array<{ id: number; is_muted: boolean }>>('/messages/conversations')
					.then(convs => {
						const mutedIds = convs.filter(c => c.is_muted).map(c => c.id);
						if (mutedIds.length > 0) setMutedConversations(mutedIds);
					})
					.catch(() => { /* sessizce geç */ });
			}

			// WebSocket event'leri — polling yerine event-driven
			wsUnsubscribers.push(
				// Yeni mesaj geldi → sayacı artır + ses çal (sessiz konuşmalar hariç)
				// Not: Mesajlaşma sayfasındayken artırma yapılmaz — sayfa kendi yönetir
				onWsEvent('new_message', (event: any) => {
					const currentUserId = authState.user?.id;
					if (event.message.sender_id !== currentUserId) {
						const onMessaging = typeof window !== 'undefined' && window.location.pathname.startsWith('/dashboard/mesajlasma');
						if (!onMessaging) {
							unreadCount++;
						}
						const convId = event.message.conversation_id || event.conversation_id;
						if (!onMessaging && !isConversationMuted(convId)) {
							playNotificationSound();
						}
					}
				}),
				// Mesajlaşma sayfası: farklı konuşmaya mesaj geldi → sayacı artır
				onWsEvent('unread_incremented', () => {
					unreadCount++;
				}),
				// read_status: karşı tarafın okuması bizim okunmamış sayımızı etkilemez
				// (eski hali syncUnreadCount çağırıyordu → race condition ile stale veri geliyordu)
				// Mesajlaşma sayfasından gelen yerel "okundu" bildirimi (optimistik)
				onWsEvent('unread_updated', (event: any) => {
					if (typeof event.total_unread === 'number') {
						lastLocalUpdateAt = Date.now();
						unreadCount = event.total_unread;
					} else {
						syncUnreadCount();
					}
				}),
				// WS yeniden bağlandığında kaçırılan event'leri telafi et
				onWsEvent('connected', () => {
					lastLocalUpdateAt = 0; // Cooldown sıfırla — reconnect sonrası tam sync gerekli
					syncUnreadCount();
					// Muted konuşma bilgisini yenile (reconnect sonrası stale olabilir)
					api.get<Array<{ id: number; is_muted: boolean }>>('/messages/conversations')
						.then(convs => {
							setMutedConversations(convs.filter(c => c.is_muted).map(c => c.id));
						})
						.catch(() => { /* sessizce geç */ });
				})
			);

			// Page Visibility API: sekme görünür olunca tek seferlik senkronize et
			visibilityHandler = () => {
				if (!document.hidden) {
					syncUnreadCount();
				}
			};
			document.addEventListener('visibilitychange', visibilityHandler);
		}
	});

	onDestroy(() => {
		wsUnsubscribers.forEach(unsub => unsub());
		if (visibilityHandler) {
			document.removeEventListener('visibilitychange', visibilityHandler);
		}
	});

	function isActive(path: string): boolean {
		return $page.url.pathname === path;
	}

	function isGroupActive(prefix: string): boolean {
		return $page.url.pathname.startsWith(prefix);
	}

	function toggleGroup(key: string) {
		if (collapsed) {
			collapsed = false;
			expandedGroups[key] = true;
			return;
		}
		expandedGroups[key] = !expandedGroups[key];
	}

	function toggleCollapse() {
		collapsed = !collapsed;
		if (collapsed) {
			// Close all groups when collapsing
			Object.keys(expandedGroups).forEach(k => expandedGroups[k] = false);
		}
	}

	// Auto-expand groups based on current page
	$effect(() => {
		if (isGroupActive('/dashboard/sistem') && !collapsed) {
			expandedGroups.system = true;
		}
		if (isGroupActive('/dashboard/kalite') && !collapsed) {
			expandedGroups.quality = true;
		}
		if (isGroupActive('/dashboard/finans') && !collapsed) {
			expandedGroups.finance = true;
		}
		if (isGroupActive('/dashboard/muhasebe') && !collapsed) {
			expandedGroups.accounting = true;
		}
		if (isGroupActive('/dashboard/ik') && !collapsed) {
			expandedGroups.hr = true;
		}
		if (isGroupActive('/dashboard/satis') && !collapsed) {
			expandedGroups.sales = true;
		}
	});

	// Mobilde sayfa değişince sidebar'ı kapat
	$effect(() => {
		const _ = $page.url.pathname;
		if (typeof window !== 'undefined' && window.innerWidth < 768) {
			closeSidebar();
		}
	});
</script>

<aside class="fixed inset-y-0 left-0 z-40 w-60 transform transition-transform duration-300 ease-in-out {sidebar.open ? 'translate-x-0' : '-translate-x-full'} md:relative md:translate-x-0 md:z-auto md:transition-all md:duration-300 {collapsed ? 'md:w-16' : 'md:w-60'} bg-white border-r border-gray-200 flex flex-col h-full shrink-0">
	<!-- Logo + Collapse toggle -->
	<div class="flex items-center justify-between px-3 py-4 border-b border-gray-100 {collapsed ? 'md:justify-center' : ''}">
		{#if !collapsed}
			<a href="/dashboard" class="pl-2">
				<img src="/logo.svg" alt="Sprenses Hotel" class="h-7 opacity-90 hover:opacity-100 transition-opacity" />
			</a>
		{/if}
		<!-- Collapse butonu — sadece masaüstünde görünür -->
		<button
			onclick={toggleCollapse}
			class="hidden md:flex items-center justify-center touch-target w-11 h-11 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer"
			title={collapsed ? 'Menüyü genişlet' : 'Menüyü daralt'}
			aria-label={collapsed ? 'Menüyü genişlet' : 'Menüyü daralt'}
		>
			{#if collapsed}
				<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
				</svg>
			{:else}
				<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
				</svg>
			{/if}
		</button>
		<!-- Mobilde kapat butonu -->
		<button
			onclick={closeSidebar}
			class="flex md:hidden items-center justify-center touch-target w-11 h-11 -mr-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer"
			title="Menüyü kapat"
			aria-label="Menüyü kapat"
		>
			<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<!-- Navigation -->
	<nav class="flex-1 overflow-y-auto py-3 px-2 space-y-1">
		<!-- Panel -->
		<a
			href="/dashboard"
			class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors {isActive('/dashboard') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'} {collapsed ? 'md:justify-center' : ''}"
			title={collapsed ? 'Panel' : ''}
		>
			<svg class="w-5 h-5 shrink-0 {isActive('/dashboard') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
			</svg>
			<span class="{collapsed ? 'md:hidden' : ''}">Panel</span>
		</a>

		<!-- Mesajlaşma -->
		{#if hasPerm('messaging')}
			<a
				href="/dashboard/mesajlasma"
				class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors {isActive('/dashboard/mesajlasma') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'} {collapsed ? 'md:justify-center' : ''}"
				title={collapsed ? 'Mesajlaşma' : ''}
			>
				<span class="relative">
					<svg class="w-5 h-5 shrink-0 {isActive('/dashboard/mesajlasma') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
					</svg>
					{#if unreadCount > 0 && collapsed}
						<span class="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 flex items-center justify-center px-1 text-[10px] font-bold text-white bg-red-500 rounded-full leading-none">
							{unreadCount > 99 ? '99+' : unreadCount}
						</span>
					{/if}
				</span>
				<span class="flex-1 flex items-center justify-between {collapsed ? 'md:hidden' : ''}">
					<span>Mesajlaşma</span>
					{#if unreadCount > 0}
						<span class="min-w-[20px] h-5 flex items-center justify-center px-1.5 text-[11px] font-bold text-white bg-red-500 rounded-full leading-none">
							{unreadCount > 99 ? '99+' : unreadCount}
						</span>
					{/if}
				</span>
			</a>
		{/if}

		<!-- Kalite Group -->
		{#if hasPerm('quality.templates') || hasPerm('quality.forms')}
			<div class="pt-2 pb-1">
				<div class="h-px bg-gray-100"></div>
			</div>

			<button
				onclick={() => toggleGroup('quality')}
				class="w-full flex items-center {collapsed ? 'md:justify-center' : 'justify-between'} px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer {isGroupActive('/dashboard/kalite') ? 'text-teal-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
				title={collapsed ? 'Kalite' : ''}
			>
				<span class="flex items-center gap-3">
					<svg class="w-5 h-5 shrink-0 {isGroupActive('/dashboard/kalite') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
					</svg>
					<span class="{collapsed ? 'md:hidden' : ''} font-medium">Kalite</span>
				</span>
				<svg class="w-4 h-4 text-gray-400 transition-transform {expandedGroups.quality ? 'rotate-180' : ''} {collapsed ? 'md:hidden' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
				</svg>
			</button>

			{#if expandedGroups.quality && !collapsed}
				<div class="ml-4 space-y-0.5">
					{#if hasPerm('quality.templates')}
						<a
							href="/dashboard/kalite/sablonlar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/kalite/sablonlar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/kalite/sablonlar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
							</svg>
							Şablonlar
						</a>
					{/if}

					{#if hasPerm('quality.forms')}
						<a
							href="/dashboard/kalite/formlar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isGroupActive('/dashboard/kalite/formlar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isGroupActive('/dashboard/kalite/formlar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 019 9v.375M10.125 2.25A3.375 3.375 0 0113.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 013.375 3.375M9 15l2.25 2.25L15 12" />
							</svg>
							Formlar
						</a>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- Finans Group -->
		{#if hasPerm('finance.cash_flow') || hasPerm('finance.banks') || hasPerm('finance.doviz') || hasPerm('finance.cariler') || hasPerm('finance.checks')}
			<div class="pt-2 pb-1">
				<div class="h-px bg-gray-100"></div>
			</div>

			<button
				onclick={() => toggleGroup('finance')}
				class="w-full flex items-center {collapsed ? 'md:justify-center' : 'justify-between'} px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer {isGroupActive('/dashboard/finans') ? 'text-teal-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
				title={collapsed ? 'Finans' : ''}
			>
				<span class="flex items-center gap-3">
					<svg class="w-5 h-5 shrink-0 {isGroupActive('/dashboard/finans') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
					</svg>
					<span class="{collapsed ? 'md:hidden' : ''} font-medium">Finans</span>
				</span>
				<svg class="w-4 h-4 text-gray-400 transition-transform {expandedGroups.finance ? 'rotate-180' : ''} {collapsed ? 'md:hidden' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
				</svg>
			</button>

			{#if expandedGroups.finance && !collapsed}
				<div class="ml-4 space-y-0.5">
					{#if hasPerm('finance.cash_flow')}
						<a
							href="/dashboard/finans/nakit-akim"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/nakit-akim') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/nakit-akim') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
							</svg>
							Nakit Akım
						</a>
					{/if}

					{#if hasPerm('finance.banks')}
						<a
							href="/dashboard/finans/bankalar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/bankalar') && !isActive('/dashboard/finans/bankalar/talimatlar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/bankalar') && !isActive('/dashboard/finans/bankalar/talimatlar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0012 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75z" />
							</svg>
							Bankalar
						</a>
						<a
							href="/dashboard/finans/bankalar/talimatlar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/bankalar/talimatlar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/bankalar/talimatlar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
							</svg>
							Talimatlar
						</a>
					{/if}

					{#if hasPerm('finance.doviz')}
						<a
							href="/dashboard/finans/doviz"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/doviz') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/doviz') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
							</svg>
							Döviz
						</a>
					{/if}

					{#if hasPerm('finance.cariler')}
						<a
							href="/dashboard/finans/cariler"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/cariler') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/cariler') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
							</svg>
							Cariler
						</a>
					{/if}
					{#if hasPerm('finance.checks')}
						<a
							href="/dashboard/finans/cekler"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/cekler') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/cekler') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
							</svg>
							Verilen Çekler
						</a>
					{/if}
					{#if hasPerm('finance.krediler')}
						<a
							href="/dashboard/finans/krediler"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/krediler') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/krediler') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z" />
							</svg>
							Krediler
						</a>
					{/if}
					{#if hasPerm('finance.avanslar')}
						<a
							href="/dashboard/finans/avanslar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/avanslar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/avanslar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
							</svg>
							Alınan Avanslar
						</a>
					{/if}
					{#if hasPerm('finance.butce')}
						<a
							href="/dashboard/finans/butce"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/butce') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/butce') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
							</svg>
							Bütçe
						</a>
					{/if}
					{#if hasPerm('finance.onay')}
						<a
							href="/dashboard/finans/onay"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/finans/onay') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/finans/onay') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
							</svg>
							Onay Kutusu
						</a>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- Muhasebe Group -->
		{#if hasPerm('accounting.taxes') || hasPerm('accounting.recurring') || hasPerm('accounting.rent_income') || hasPerm('accounting.rent_expense') || hasPerm('accounting.dividend')}
			<div class="pt-2 pb-1">
				<div class="h-px bg-gray-100"></div>
			</div>

			<button
				onclick={() => toggleGroup('accounting')}
				class="w-full flex items-center {collapsed ? 'md:justify-center' : 'justify-between'} px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer {isGroupActive('/dashboard/muhasebe') ? 'text-teal-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
				title={collapsed ? 'Muhasebe' : ''}
			>
				<span class="flex items-center gap-3">
					<svg class="w-5 h-5 shrink-0 {isGroupActive('/dashboard/muhasebe') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 15.75V18m-7.5-6.75h.008v.008H8.25v-.008zm0 2.25h.008v.008H8.25V13.5zm0 2.25h.008v.008H8.25v-.008zm0 2.25h.008v.008H8.25V18zm2.498-6.75h.007v.008h-.007v-.008zm0 2.25h.007v.008h-.007V13.5zm0 2.25h.007v.008h-.007v-.008zm0 2.25h.007v.008h-.007V18zm2.504-6.75h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V13.5zm0 2.25h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V18zm2.498-6.75h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V13.5zM8.25 6h7.5v2.25h-7.5V6zM12 2.25c-1.892 0-3.758.11-5.593.322C5.307 2.7 4.5 3.65 4.5 4.757V19.5a2.25 2.25 0 002.25 2.25h10.5a2.25 2.25 0 002.25-2.25V4.757c0-1.108-.806-2.057-1.907-2.185A48.507 48.507 0 0012 2.25z" />
					</svg>
					<span class="{collapsed ? 'md:hidden' : ''} font-medium">Muhasebe</span>
				</span>
				<svg class="w-4 h-4 text-gray-400 transition-transform {expandedGroups.accounting ? 'rotate-180' : ''} {collapsed ? 'md:hidden' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
				</svg>
			</button>

			{#if expandedGroups.accounting && !collapsed}
				<div class="ml-4 space-y-0.5">
					{#if hasPerm('accounting.taxes')}
						<a
							href="/dashboard/muhasebe/vergiler"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/muhasebe/vergiler') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/muhasebe/vergiler') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 14.25l6-6m4.5-3.493V21.75l-3.75-1.5-3.75 1.5-3.75-1.5-3.75 1.5V4.757c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0c1.1.128 1.907 1.077 1.907 2.185zM9.75 9h.008v.008H9.75V9zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 4.5h.008v.008h-.008V13.5zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
							</svg>
							Vergiler
						</a>
					{/if}
					{#if hasPerm('accounting.recurring')}
						<a
							href="/dashboard/muhasebe/duzenli-odemeler"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/muhasebe/duzenli-odemeler') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/muhasebe/duzenli-odemeler') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
							</svg>
							Düzenli Ödemeler
						</a>
					{/if}
					{#if hasPerm('accounting.rent_income')}
						<a
							href="/dashboard/muhasebe/alinan-kiralar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/muhasebe/alinan-kiralar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/muhasebe/alinan-kiralar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
							</svg>
							Alınan Kiralar
						</a>
					{/if}
					{#if hasPerm('accounting.rent_expense')}
						<a
							href="/dashboard/muhasebe/verilen-kiralar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/muhasebe/verilen-kiralar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/muhasebe/verilen-kiralar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 21v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21m0 0h4.5V3.545M12.75 21h7.5V10.75M2.25 21h1.5m18 0h-18M2.25 9l4.5-1.636M18.75 3l-1.5.545m0 6.205l3 1m1.5.5l-1.5-.5M6.75 7.364V3h-3v18m3-13.636l10.5-3.819" />
							</svg>
							Verilen Kiralar
						</a>
					{/if}
					{#if hasPerm('accounting.dividend')}
						<a
							href="/dashboard/muhasebe/temettu"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/muhasebe/temettu') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/muhasebe/temettu') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
							</svg>
							Temettü
						</a>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- İnsan Kaynakları Group -->
		{#if hasPerm('hr.salary') || hasPerm('hr.withholding') || hasPerm('hr.sgk')}
			<div class="pt-2 pb-1">
				<div class="h-px bg-gray-100"></div>
			</div>

			<button
				onclick={() => toggleGroup('hr')}
				class="w-full flex items-center {collapsed ? 'md:justify-center' : 'justify-between'} px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer {isGroupActive('/dashboard/ik') ? 'text-teal-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
				title={collapsed ? 'İnsan Kaynakları' : ''}
			>
				<span class="flex items-center gap-3">
					<svg class="w-5 h-5 shrink-0 {isGroupActive('/dashboard/ik') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
					</svg>
					<span class="{collapsed ? 'md:hidden' : ''} font-medium">İnsan Kaynakları</span>
				</span>
				<svg class="w-4 h-4 text-gray-400 transition-transform {expandedGroups.hr ? 'rotate-180' : ''} {collapsed ? 'md:hidden' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
				</svg>
			</button>

			{#if expandedGroups.hr && !collapsed}
				<div class="ml-4 space-y-0.5">
					{#if hasPerm('hr.salary')}
						<a
							href="/dashboard/ik/maas"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/ik/maas') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/ik/maas') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
							</svg>
							Maaş
						</a>
					{/if}
					{#if hasPerm('hr.withholding')}
						<a
							href="/dashboard/ik/stopaj"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/ik/stopaj') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/ik/stopaj') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
							</svg>
							Stopaj
						</a>
					{/if}
					{#if hasPerm('hr.sgk')}
						<a
							href="/dashboard/ik/sgk"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/ik/sgk') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/ik/sgk') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
							</svg>
							SGK
						</a>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- Satış Group -->
		{#if hasPerm('sales.flight') || hasPerm('sales.hotel_reservation') || hasPerm('sales.room_types')}
			<div class="pt-2 pb-1">
				<div class="h-px bg-gray-100"></div>
			</div>

			<button
				onclick={() => toggleGroup('sales')}
				class="w-full flex items-center {collapsed ? 'md:justify-center' : 'justify-between'} px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer {isGroupActive('/dashboard/satis') ? 'text-teal-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
				title={collapsed ? 'Satış' : ''}
			>
				<span class="flex items-center gap-3">
					<svg class="w-5 h-5 shrink-0 {isGroupActive('/dashboard/satis') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z" />
					</svg>
					<span class="{collapsed ? 'md:hidden' : ''} font-medium">Satış</span>
				</span>
				<svg class="w-4 h-4 text-gray-400 transition-transform {expandedGroups.sales ? 'rotate-180' : ''} {collapsed ? 'md:hidden' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
				</svg>
			</button>

			{#if expandedGroups.sales && !collapsed}
				<div class="ml-4 space-y-0.5">
					{#if hasPerm('sales.hotel_reservation')}
						<a
							href="/dashboard/satis/otel-rezervasyon"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/satis/otel-rezervasyon') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/satis/otel-rezervasyon') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
							</svg>
							Otel Rezervasyon
						</a>
					{/if}
					{#if hasPerm('sales.room_types')}
						<a
							href="/dashboard/satis/oda-tipleri"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/satis/oda-tipleri') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/satis/oda-tipleri') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 12a2.25 2.25 0 002.25 2.25h13.5A2.25 2.25 0 0021 12M3 12V8.25A2.25 2.25 0 015.25 6h13.5A2.25 2.25 0 0121 8.25V12M3 12v6a.75.75 0 00.75.75h.75a.75.75 0 00.75-.75v-.75a.75.75 0 01.75-.75h12a.75.75 0 01.75.75v.75a.75.75 0 00.75.75h.75a.75.75 0 00.75-.75v-6m-15-3v.75c0 .414.336.75.75.75h.75a.75.75 0 00.75-.75V9m6.75 0v.75c0 .414.336.75.75.75h.75a.75.75 0 00.75-.75V9" />
							</svg>
							Oda Tipleri
						</a>
					{/if}
					{#if hasPerm('sales.flight')}
						<a
							href="/dashboard/satis/ucak-rezervasyon"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/satis/ucak-rezervasyon') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/satis/ucak-rezervasyon') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.125A59.769 59.769 0 0121.485 12 59.768 59.768 0 013.27 20.875L5.999 12zm0 0h7.5" />
							</svg>
							Uçak Rezervasyon
						</a>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- Separator + Sistem -->
		{#if hasPerm('system.users') || hasPerm('system.roles') || hasPerm('system.modules') || hasPerm('system.audit_logs') || hasPerm('system.error_logs') || hasPerm('system.approval')}
			<div class="pt-2 pb-1">
				<div class="h-px bg-gray-100"></div>
			</div>

			<!-- Sistem Group -->
			<button
				onclick={() => toggleGroup('system')}
				class="w-full flex items-center {collapsed ? 'md:justify-center' : 'justify-between'} px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer {isGroupActive('/dashboard/sistem') ? 'text-teal-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
				title={collapsed ? 'Sistem' : ''}
			>
				<span class="flex items-center gap-3">
					<svg class="w-5 h-5 shrink-0 {isGroupActive('/dashboard/sistem') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
						<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
					</svg>
					<span class="{collapsed ? 'md:hidden' : ''} font-medium">Sistem</span>
				</span>
				<svg class="w-4 h-4 text-gray-400 transition-transform {expandedGroups.system ? 'rotate-180' : ''} {collapsed ? 'md:hidden' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
				</svg>
			</button>

			{#if expandedGroups.system && !collapsed}
				<div class="ml-4 space-y-0.5">
					{#if hasPerm('system.users')}
						<a
							href="/dashboard/sistem/kullanicilar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/sistem/kullanicilar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/sistem/kullanicilar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
							</svg>
							Kullanıcılar
						</a>
					{/if}

					{#if hasPerm('system.roles')}
						<a
							href="/dashboard/sistem/roller"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/sistem/roller') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/sistem/roller') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
							</svg>
							Roller
						</a>
					{/if}

					{#if hasPerm('system.modules')}
						<a
							href="/dashboard/sistem/moduller"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/sistem/moduller') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/sistem/moduller') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />
							</svg>
							Modüller
						</a>
					{/if}

					{#if hasPerm('system.audit_logs')}
						<a
							href="/dashboard/sistem/audit-loglar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/sistem/audit-loglar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/sistem/audit-loglar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
							</svg>
							Audit Logları
						</a>
					{/if}

					{#if hasPerm('system.error_logs')}
						<a
							href="/dashboard/sistem/hata-loglar"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/sistem/hata-loglar') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/sistem/hata-loglar') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
							</svg>
							Hata Logları
						</a>
					{/if}

					{#if hasPerm('system.approval')}
						<a
							href="/dashboard/sistem/onay-akisi"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/sistem/onay-akisi') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/sistem/onay-akisi') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z" />
							</svg>
							Onay Akışı
						</a>
					{/if}
					{#if hasPerm('system.server')}
						<a
							href="/dashboard/sistem/sunucu"
							class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {isActive('/dashboard/sistem/sunucu') ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'}"
						>
							<svg class="w-4 h-4 shrink-0 {isActive('/dashboard/sistem/sunucu') ? 'text-teal-600' : 'text-gray-400'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
							</svg>
							Sunucu
						</a>
					{/if}
				</div>
			{/if}

			<!-- Mobilde sistem alt menüsü her zaman açılabilir -->
			{#if expandedGroups.system && collapsed}
				<!-- Masaüstünde collapsed iken alt menü gizli kalır -->
			{/if}
		{/if}
	</nav>

	<!-- Bottom: version -->
	<div class="px-3 py-3 border-t border-gray-100">
		<p class="text-xs text-gray-300 pl-2 {collapsed ? 'md:hidden' : ''}">Sprenses v1.0</p>
	</div>
</aside>
