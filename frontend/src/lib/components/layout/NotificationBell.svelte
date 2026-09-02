<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { playNotificationSound, notificationSettings, toggleSound } from '$lib/stores/notification.svelte';
	import { Bell, Landmark, Loader2, Volume2, VolumeX, X } from 'lucide-svelte';

	const TYPE_ICONS: Record<string, any> = {
		bank_statement_uploaded: Landmark,
	};

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
			.catch((err) => console.error('Okunmamış bildirim sayısı alınamadı:', err));
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

	function typeIcon(type: string): any {
		return TYPE_ICONS[type] ?? Bell;
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
		class="relative touch-target flex items-center justify-center text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded-lg transition-colors cursor-pointer"
		aria-label="Bildirimler"
	>
		<Bell size={20} />
		{#if unreadCount > 0}
			<span class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] flex items-center justify-center bg-brass text-teal-900 text-[10px] font-bold rounded-full px-1">
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
						class="touch-target flex items-center justify-center rounded hover:bg-gray-200 transition-colors cursor-pointer"
						title={notificationSettings.soundEnabled ? 'Bildirimleri sessize al' : 'Bildirim sesini aç'}
						aria-label={notificationSettings.soundEnabled ? 'Bildirimleri sessize al' : 'Bildirim sesini aç'}
					>
						{#if notificationSettings.soundEnabled}
							<Volume2 size={16} class="text-teal-600" />
						{:else}
							<VolumeX size={16} class="text-gray-500" />
						{/if}
					</button>
					{#if unreadCount > 0}
						<button
							onclick={markAllRead}
							class="touch-target inline-flex items-center text-xs text-teal-700 hover:text-teal-800 font-medium cursor-pointer"
						>
							Tümünü okundu işaretle
						</button>
					{/if}
					{#if notifications.length > 0}
						<button
							onclick={deleteAllNotifications}
							class="touch-target inline-flex items-center text-xs text-red-600 hover:text-red-700 font-medium cursor-pointer"
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
						<Loader2 size={20} class="animate-spin text-teal-600" />
					</div>
				{:else if notifications.length === 0}
					<div class="flex flex-col items-center justify-center py-8 text-gray-500">
						<Bell size={32} class="mb-2" />
						<span class="text-sm">Bildirim yok</span>
					</div>
				{:else}
					{#each notifications as n (n.id)}
						{@const NIcon = typeIcon(n.type)}
						<div
							class="group w-full flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left border-b border-gray-50 last:border-0 {n.is_read ? 'opacity-60' : ''}"
						>
							<button
								onclick={() => clickNotification(n)}
								class="flex items-start gap-3 flex-1 min-w-0 cursor-pointer"
							>
								<span class="shrink-0 mt-0.5 text-gray-500"><NIcon size={18} /></span>
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
								aria-label="Bildirimi sil"
							>
								<X size={14} />
							</button>
						</div>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>
