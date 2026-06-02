<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { playNotificationSound, notificationSettings, toggleSound } from '$lib/stores/notification.svelte';

	interface NotificationItem {
		id: number;
		type: string;
		title: string;
		body: string;
		link: string | null;
		is_read: boolean;
		created_at: string;
	}

	let open = $state(false);
	let notifications = $state<NotificationItem[]>([]);
	let unreadCount = $state(0);
	let loading = $state(false);
	let loaded = $state(false);

	// İlk yüklemede okunmamış sayıyı al
	$effect(() => {
		api.get<{ count: number }>('/notifications/unread-count')
			.then(data => { unreadCount = data.count; })
			.catch(() => {});
	});

	// Gerçek zamanlı bildirim dinle
	$effect(() => {
		const unsub = onWsEvent('notification', (data: any) => {
			const n = data.notification as NotificationItem;
			notifications = [n, ...notifications].slice(0, 50);
			if (!n.is_read) unreadCount++;
			if (notificationSettings.soundEnabled) {
				playNotificationSound();
			}
		});
		return unsub;
	});

	async function toggleDropdown() {
		open = !open;
		if (open && !loaded) {
			loading = true;
			try {
				const data = await api.get<{ items: NotificationItem[] }>('/notifications/?page_size=50');
				notifications = data.items;
				loaded = true;
			} catch (err) {
				console.error('Bildirimler yüklenemedi:', err);
			}
			loading = false;
		}
	}

	function closeDropdown() {
		open = false;
	}

	async function markAllRead() {
		try {
			await api.patch('/notifications/read', {});
			unreadCount = 0;
			notifications = notifications.map(n => ({ ...n, is_read: true }));
		} catch (err) {
			console.error('Okundu işaretlenemedi:', err);
		}
	}

	async function deleteNotification(e: MouseEvent, n: NotificationItem) {
		e.stopPropagation();
		try {
			await api.delete(`/notifications/${n.id}`);
			notifications = notifications.filter(item => item.id !== n.id);
			if (!n.is_read) unreadCount = Math.max(0, unreadCount - 1);
		} catch (err) {
			console.error('Bildirim silinemedi:', err);
		}
	}

	async function deleteAllNotifications() {
		try {
			await api.delete('/notifications/all');
			notifications = [];
			unreadCount = 0;
		} catch (err) {
			console.error('Bildirimler silinemedi:', err);
		}
	}

	async function clickNotification(n: NotificationItem) {
		if (!n.is_read) {
			try {
				const resp = await api.patch<{ unread_count: number }>('/notifications/read', { notification_ids: [n.id] });
				n.is_read = true;
				unreadCount = resp.unread_count;
				notifications = notifications.map(item => item.id === n.id ? { ...item, is_read: true } : item);
			} catch (err) {
				console.error('Okundu işaretlenemedi:', err);
			}
		}
		open = false;
		if (n.link) goto(n.link);
	}

	function timeAgo(dateStr: string): string {
		const now = new Date();
		const date = new Date(dateStr);
		const diff = Math.floor((now.getTime() - date.getTime()) / 1000);

		if (diff < 60) return 'Az önce';
		if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
		if (diff < 86400) return `${Math.floor(diff / 3600)} sa önce`;
		if (diff < 604800) return `${Math.floor(diff / 86400)} gün önce`;
		return date.toLocaleDateString('tr-TR');
	}

	function typeIcon(type: string): string {
		switch (type) {
			case 'bank_statement_uploaded': return '🏦';
			default: return '🔔';
		}
	}

	// Dışarı tıklayınca kapat
	function handleWindowClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (!target.closest('.notification-bell')) {
			open = false;
		}
	}
</script>

<svelte:window onclick={handleWindowClick} />

<div class="notification-bell relative">
	<!-- Çan butonu -->
	<button
		onclick={toggleDropdown}
		class="relative p-2 text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded-lg transition-colors cursor-pointer"
		aria-label="Bildirimler"
	>
		<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
			<path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
		</svg>
		{#if unreadCount > 0}
			<span class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] flex items-center justify-center bg-red-500 text-white text-[10px] font-bold rounded-full px-1">
				{unreadCount > 99 ? '99+' : unreadCount}
			</span>
		{/if}
	</button>

	<!-- Dropdown -->
	{#if open}
		<div class="fixed left-2 right-2 top-[3.75rem] sm:absolute sm:left-auto sm:right-0 sm:top-full sm:mt-2 sm:w-96 bg-white rounded-xl shadow-xl border border-gray-200 z-50 overflow-hidden">
			<!-- Başlık -->
			<div class="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-100 bg-gray-50 flex-wrap">
				<h3 class="text-sm font-semibold text-gray-800">Bildirimler</h3>
				<div class="flex items-center gap-2 flex-wrap">
					<!-- Ses açma/kapama -->
					<button
						onclick={() => toggleSound(!notificationSettings.soundEnabled)}
						class="p-1 rounded hover:bg-gray-200 transition-colors cursor-pointer"
						title={notificationSettings.soundEnabled ? 'Bildirimleri sessize al' : 'Bildirim sesini aç'}
					>
						{#if notificationSettings.soundEnabled}
							<svg class="w-4 h-4 text-teal-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
							</svg>
						{:else}
							<svg class="w-4 h-4 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
							</svg>
						{/if}
					</button>
					{#if unreadCount > 0}
						<button
							onclick={markAllRead}
							class="text-xs text-teal-600 hover:text-teal-700 font-medium cursor-pointer"
						>
							Tümünü okundu işaretle
						</button>
					{/if}
					{#if notifications.length > 0}
						<button
							onclick={deleteAllNotifications}
							class="text-xs text-red-600 hover:text-red-600 font-medium cursor-pointer"
							title="Tüm bildirimleri sil"
						>
							Tümünü sil
						</button>
					{/if}
				</div>
			</div>

			<!-- Bildirim listesi -->
			<div class="max-h-80 overflow-y-auto">
				{#if loading}
					<div class="flex items-center justify-center py-8">
						<svg class="animate-spin h-5 w-5 text-teal-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
							<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
							<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
						</svg>
					</div>
				{:else if notifications.length === 0}
					<div class="flex flex-col items-center justify-center py-8 text-gray-500">
						<svg class="w-8 h-8 mb-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
						</svg>
						<span class="text-sm">Bildirim yok</span>
					</div>
				{:else}
					{#each notifications as n (n.id)}
						<div
							class="group w-full flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left border-b border-gray-50 last:border-0 {n.is_read ? 'opacity-60' : ''}"
						>
							<button
								onclick={() => clickNotification(n)}
								class="flex items-start gap-3 flex-1 min-w-0 cursor-pointer"
							>
								<span class="text-lg shrink-0 mt-0.5">{typeIcon(n.type)}</span>
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<span class="text-sm font-medium text-gray-800 truncate">{n.title}</span>
										{#if !n.is_read}
											<span class="w-2 h-2 bg-teal-500 rounded-full shrink-0"></span>
										{/if}
									</div>
									<p class="text-xs text-gray-500 mt-0.5 line-clamp-2">{n.body}</p>
									<span class="text-[10px] text-gray-500 mt-1 block">{timeAgo(n.created_at)}</span>
								</div>
							</button>
							<button
								onclick={(e) => deleteNotification(e, n)}
								class="shrink-0 mt-1 p-1 rounded hover:bg-red-100 text-gray-500 hover:text-red-600 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
								title="Bildirimi sil"
							>
								<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						</div>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>
