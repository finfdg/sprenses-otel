<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { hasPermission, authState } from '$lib/stores/auth.svelte';
	import { api } from '$lib/api';
	import { sidebar, closeSidebar } from '$lib/stores/ui.svelte';
	import { playNotificationSound, isConversationMuted, setMutedConversations, mutedConversationIds } from '$lib/stores/notification.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { NAV_GROUPS, PANEL_ICON, MESSAGING_ICON, type NavGroup, type NavItem } from '$lib/config/navigation';
	import { ChevronDown, ChevronsLeft, ChevronsRight, X } from 'lucide-svelte';

	let collapsed = $state(false);
	// Açıl/kapan durumu konfigteki gruplardan türetilir (elle liste tutulmaz)
	let expandedGroups = $state<Record<string, boolean>>(
		Object.fromEntries(NAV_GROUPS.map((g) => [g.key, false]))
	);
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

	// Bir grubun en az bir alt sayfasına görme izni var mı? (grup başlığını göster)
	function groupVisible(group: NavGroup): boolean {
		return group.items.some((it) => hasPerm(it.code));
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

	// Bir menü öğesi aktif mi? prefixActive → alt rotalı sayfalar (formlar/[id])
	function itemActive(it: NavItem): boolean {
		return it.prefixActive ? isGroupActive(it.href) : isActive(it.href);
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

	// Mevcut rotaya göre ilgili grubu otomatik aç (konfig üzerinden)
	$effect(() => {
		if (collapsed) return;
		for (const g of NAV_GROUPS) {
			if (isGroupActive(g.prefix)) {
				expandedGroups[g.key] = true;
			}
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

<aside class="fixed inset-y-0 left-0 z-40 w-60 transform transition-transform duration-300 ease-in-out {sidebar.open ? 'translate-x-0' : '-translate-x-full'} md:relative md:translate-x-0 md:z-auto md:transition-all md:duration-300 {collapsed ? 'md:w-16' : 'md:w-60'} bg-teal-700 border-r border-teal-800 flex flex-col h-full shrink-0">
	<!-- Logo + Collapse toggle -->
	<div class="flex items-center justify-between px-3 py-4 border-b border-teal-600/50 {collapsed ? 'md:flex-col md:justify-center md:gap-2' : ''}">
		<a href="/dashboard" class="flex items-center gap-2.5 {collapsed ? '' : 'pl-2'}" title="Sprenses — Panel">
			<span class="w-8 h-8 rounded-lg bg-brass flex items-center justify-center shrink-0">
				<span class="font-serif text-white text-lg font-semibold leading-none">S</span>
			</span>
			<span class="flex flex-col {collapsed ? 'md:hidden' : ''}">
				<span class="font-serif text-white text-base font-semibold leading-tight">Sprenses</span>
				<span class="text-[10px] tracking-[2px] text-teal-300 leading-tight">OTEL YÖNETİMİ</span>
			</span>
		</a>
		<!-- Collapse butonu — sadece masaüstünde görünür -->
		<button
			onclick={toggleCollapse}
			class="hidden md:flex items-center justify-center touch-target w-11 h-11 rounded-lg text-teal-300 hover:text-white hover:bg-teal-600 transition-colors cursor-pointer"
			title={collapsed ? 'Menüyü genişlet' : 'Menüyü daralt'}
			aria-label={collapsed ? 'Menüyü genişlet' : 'Menüyü daralt'}
		>
			{#if collapsed}
				<ChevronsRight size={20} />
			{:else}
				<ChevronsLeft size={20} />
			{/if}
		</button>
		<!-- Mobilde kapat butonu -->
		<button
			onclick={closeSidebar}
			class="flex md:hidden items-center justify-center touch-target w-11 h-11 -mr-2 rounded-lg text-teal-300 hover:text-white hover:bg-teal-600 transition-colors cursor-pointer"
			title="Menüyü kapat"
			aria-label="Menüyü kapat"
		>
			<X size={20} />
		</button>
	</div>

	<!-- Navigation -->
	<nav class="flex-1 overflow-y-auto py-3 px-2 space-y-1">
		<!-- Panel -->
		<a
			href="/dashboard"
			class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors {isActive('/dashboard') ? 'bg-teal-600 text-white font-medium' : 'text-teal-200 hover:bg-teal-600/60 hover:text-white'} {collapsed ? 'md:justify-center' : ''}"
			title={collapsed ? 'Panel' : ''}
		>
			<svg class="w-5 h-5 shrink-0 {isActive('/dashboard') ? 'text-brass-light' : 'text-teal-300'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				{#each PANEL_ICON as d}<path stroke-linecap="round" stroke-linejoin="round" d={d} />{/each}
			</svg>
			<span class="{collapsed ? 'md:hidden' : ''}">Panel</span>
		</a>

		<!-- Yönetim Paneli (GM/Finans üst düzey KPI) -->
		{#if hasPermission('yonetim.panel')}
			<a
				href="/dashboard/yonetim"
				class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors {isActive('/dashboard/yonetim') ? 'bg-teal-600 text-white font-medium' : 'text-teal-200 hover:bg-teal-600/60 hover:text-white'} {collapsed ? 'md:justify-center' : ''}"
				title={collapsed ? 'Yönetim Paneli' : ''}
			>
				<svg class="w-5 h-5 shrink-0 {isActive('/dashboard/yonetim') ? 'text-brass-light' : 'text-teal-300'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h12M5.25 18l4.5-4.5 3 3 4.5-4.5M18 12.75V9" />
				</svg>
				<span class="{collapsed ? 'md:hidden' : ''}">Yönetim Paneli</span>
			</a>
		{/if}

		<!-- Mesajlaşma (özel: okunmamış badge) -->
		{#if hasPerm('messaging')}
			<a
				href="/dashboard/mesajlasma"
				class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors {isActive('/dashboard/mesajlasma') ? 'bg-teal-600 text-white font-medium' : 'text-teal-200 hover:bg-teal-600/60 hover:text-white'} {collapsed ? 'md:justify-center' : ''}"
				title={collapsed ? 'Mesajlaşma' : ''}
			>
				<span class="relative">
					<svg class="w-5 h-5 shrink-0 {isActive('/dashboard/mesajlasma') ? 'text-brass-light' : 'text-teal-300'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						{#each MESSAGING_ICON as d}<path stroke-linecap="round" stroke-linejoin="round" d={d} />{/each}
					</svg>
					{#if unreadCount > 0 && collapsed}
						<span class="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 flex items-center justify-center px-1 text-[10px] font-bold text-teal-900 bg-brass rounded-full leading-none">
							{unreadCount > 99 ? '99+' : unreadCount}
						</span>
					{/if}
				</span>
				<span class="flex-1 flex items-center justify-between {collapsed ? 'md:hidden' : ''}">
					<span>Mesajlaşma</span>
					{#if unreadCount > 0}
						<span class="min-w-[20px] h-5 flex items-center justify-center px-1.5 text-[11px] font-bold text-teal-900 bg-brass rounded-full leading-none">
							{unreadCount > 99 ? '99+' : unreadCount}
						</span>
					{/if}
				</span>
			</a>
		{/if}

		<!-- Modül grupları (lib/config/navigation üzerinden) -->
		{#each NAV_GROUPS as group (group.key)}
			{#if groupVisible(group)}
				<div class="pt-2 pb-1">
					<div class="h-px bg-teal-600/50"></div>
				</div>

				<button
					onclick={() => toggleGroup(group.key)}
					class="w-full flex items-center {collapsed ? 'md:justify-center' : 'justify-between'} px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer {isGroupActive(group.prefix) ? 'text-white' : 'text-teal-200 hover:bg-teal-600/60 hover:text-white'}"
					title={collapsed ? group.label : ''}
				>
					<span class="flex items-center gap-3">
						<svg class="w-5 h-5 shrink-0 {isGroupActive(group.prefix) ? 'text-brass-light' : 'text-teal-300'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							{#each group.icon as d}<path stroke-linecap="round" stroke-linejoin="round" d={d} />{/each}
						</svg>
						<span class="{collapsed ? 'md:hidden' : ''} font-medium">{group.label}</span>
					</span>
					<ChevronDown class="w-4 h-4 text-teal-300 transition-transform {expandedGroups[group.key] ? 'rotate-180' : ''} {collapsed ? 'md:hidden' : ''}" />
				</button>

				{#if expandedGroups[group.key] && !collapsed}
					<div class="ml-4 space-y-0.5">
						{#each group.items as it (it.href)}
							{#if hasPerm(it.code)}
								<a
									href={it.href}
									class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors {itemActive(it) ? 'bg-teal-600 text-white font-medium' : 'text-teal-300 hover:bg-teal-600/60 hover:text-white'}"
								>
									<svg class="w-4 h-4 shrink-0 {itemActive(it) ? 'text-brass-light' : 'text-teal-300'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
										{#each it.icon as d}<path stroke-linecap="round" stroke-linejoin="round" d={d} />{/each}
									</svg>
									{it.label}
								</a>
							{/if}
						{/each}
					</div>
				{/if}
			{/if}
		{/each}
	</nav>

	<!-- Bottom: version -->
	<div class="px-3 py-3 border-t border-teal-600/50">
		<p class="text-xs text-teal-300 pl-2 {collapsed ? 'md:hidden' : ''}">Sprenses v1.0</p>
	</div>
</aside>
