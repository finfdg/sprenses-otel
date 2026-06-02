<script lang="ts">
	import type { OtherUser, GroupMember } from '$lib/types/messaging';
	import { getInitial } from '$lib/types/messaging';

	let {
		convType,
		convName,
		members = null,
		selectedUser = null,
		isOnline = false,
		isMuted = false,
		otherUnreadCount = 0,
		showMessageSearch = $bindable(false),
		showGroupInfoPanel = $bindable(false),
		onBack,
		onSearchToggle,
		onToggleMute,
	}: {
		convType: string;
		convName: string | null;
		members?: GroupMember[] | null;
		selectedUser?: OtherUser | null;
		isOnline?: boolean;
		isMuted?: boolean;
		otherUnreadCount?: number;
		showMessageSearch: boolean;
		showGroupInfoPanel: boolean;
		onBack: () => void;
		onSearchToggle: () => void;
		onToggleMute?: () => void;
	} = $props();
</script>

<div class="h-14 bg-white border-b border-gray-200 px-3 md:px-4 flex items-center gap-3 shrink-0">
	<!-- Geri butonu (mobil) — diğer konuşmalarda okunmamış varsa badge göster -->
	<button onclick={onBack} class="relative flex md:hidden items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer shrink-0" title="Geri">
		<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" /></svg>
		{#if otherUnreadCount > 0}
			<span class="absolute -top-1.5 -left-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center leading-none shadow-sm">
				{otherUnreadCount > 99 ? '99+' : otherUnreadCount}
			</span>
		{/if}
	</button>

	<div class="relative shrink-0">
		<div class="w-9 h-9 rounded-full {convType === 'group' ? 'bg-indigo-100' : 'bg-teal-100'} flex items-center justify-center">
			{#if convType === 'group'}
				<span class="text-sm font-semibold text-indigo-700">{convName?.charAt(0)?.toUpperCase() || 'G'}</span>
			{:else}
				<span class="text-sm font-semibold text-teal-700">{selectedUser ? getInitial(selectedUser) : '?'}</span>
			{/if}
		</div>
		{#if convType === 'private' && selectedUser && isOnline}
			<div class="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-500 rounded-full border-2 border-white"></div>
		{/if}
	</div>

	<div class="min-w-0 flex-1">
		{#if convType === 'group'}
			<p class="text-sm font-semibold text-gray-900 truncate">{convName || 'Grup'}</p>
			<p class="text-xs text-gray-400 truncate">{members?.length || 0} üye</p>
		{:else}
			<p class="text-sm font-semibold text-gray-900 truncate">{selectedUser?.first_name} {selectedUser?.last_name}</p>
			<p class="text-xs {isOnline ? 'text-green-500' : 'text-gray-400'} truncate">
				{#if isOnline}Çevrimiçi{:else}@{selectedUser?.username}{/if}
			</p>
		{/if}
	</div>

	{#if onToggleMute}
		<button onclick={onToggleMute} class="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer {isMuted ? 'text-red-400 hover:text-red-600' : 'text-gray-400 hover:text-gray-600'}" title={isMuted ? 'Sesi aç' : 'Sessize al'}>
			{#if isMuted}
				<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" /></svg>
			{:else}
				<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" /></svg>
			{/if}
		</button>
	{/if}
	<button onclick={onSearchToggle} class="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer text-gray-400 hover:text-gray-600" title="Mesaj Ara">
		<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" /></svg>
	</button>

	{#if convType === 'group'}
		<button onclick={() => showGroupInfoPanel = !showGroupInfoPanel} class="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer text-gray-400 hover:text-gray-600" title="Grup Bilgisi">
			<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" /></svg>
		</button>
	{/if}
</div>
