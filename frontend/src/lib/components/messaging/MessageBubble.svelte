<script lang="ts">
	import type { MessageItem } from '$lib/types/messaging';
	import { formatMsgTime, formatFileSize, getFileIcon, getUserColor } from '$lib/types/messaging';

	let {
		msg,
		isMine,
		isGroupChat = false,
		isRead = false,
		isPrivate = false,
		editingMsgId = null,
		swipedMsgId = null,
		actionMenuMsgId = null,
		onStartEdit,
		onDelete,
		onToggleActionMenu,
		onTouchStart,
		onTouchEnd,
		onLightbox,
	}: {
		msg: MessageItem;
		isMine: boolean;
		isGroupChat?: boolean;
		isRead?: boolean;
		isPrivate?: boolean;
		editingMsgId?: number | null;
		swipedMsgId?: number | null;
		actionMenuMsgId?: number | null;
		onStartEdit: (msg: MessageItem) => void;
		onDelete: (msgId: number) => void;
		onToggleActionMenu: (e: MouseEvent, msgId: number) => void;
		onTouchStart: (e: TouchEvent, msg: MessageItem) => void;
		onTouchEnd: (e: TouchEvent, msg: MessageItem) => void;
		onLightbox: (url: string) => void;
	} = $props();

	const uc = isGroupChat && !isMine ? getUserColor(msg.sender_id) : null;
</script>

{#if msg.message_type === 'system'}
	<div data-msg-id={msg.id} class="flex justify-center my-2">
		<span class="bg-gray-200/80 text-gray-500 text-xs px-3 py-1 rounded-full italic">{msg.content}</span>
	</div>
{:else if isMine}
	<!-- Gönderen (sağ) -->
	<div data-msg-id={msg.id} class="flex justify-end items-end gap-1 group transition-all">
		{#if !msg.is_deleted}
			<div class="relative">
				<button class="hidden md:flex items-center justify-center w-6 h-6 rounded-full opacity-0 group-hover:opacity-100 transition-opacity text-gray-300 hover:text-gray-500 hover:bg-gray-200 cursor-pointer" onclick={(e) => onToggleActionMenu(e, msg.id)} aria-label="Mesaj seçenekleri">
					<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 20 20"><path d="M6 10a2 2 0 11-4 0 2 2 0 014 0zm6 0a2 2 0 11-4 0 2 2 0 014 0zm6 0a2 2 0 11-4 0 2 2 0 014 0z" /></svg>
				</button>
				{#if actionMenuMsgId === msg.id}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div class="absolute bottom-full right-0 mb-1 bg-white shadow-lg rounded-lg border border-gray-200 z-30 py-1 min-w-[130px]" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
						{#if msg.message_type === 'text'}
							<button onclick={(e) => { e.stopPropagation(); onStartEdit(msg); }} class="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2 cursor-pointer">Düzenle</button>
						{/if}
						<button onclick={(e) => { e.stopPropagation(); onDelete(msg.id); }} class="w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2 cursor-pointer">Sil</button>
					</div>
				{/if}
			</div>
		{/if}
		{#if swipedMsgId === msg.id && !msg.is_deleted}
			<div class="flex md:hidden items-center gap-1.5 transition-all">
				{#if msg.message_type === 'text'}
					<button onclick={(e) => { e.stopPropagation(); onStartEdit(msg); }} class="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center cursor-pointer shadow-sm" title="Düzenle">✏️</button>
				{/if}
				<button onclick={(e) => { e.stopPropagation(); onDelete(msg.id); }} class="w-8 h-8 rounded-full bg-red-500 text-white flex items-center justify-center cursor-pointer shadow-sm" title="Sil">🗑️</button>
			</div>
		{/if}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="max-w-[85%] md:max-w-[70%]" ontouchstart={(e) => onTouchStart(e, msg)} ontouchend={(e) => onTouchEnd(e, msg)}>
			{#if msg.is_deleted}
				<div class="bg-gray-200/60 px-3 md:px-4 py-2 rounded-2xl rounded-br-md"><p class="text-sm text-gray-400 italic">Bu mesaj silindi</p></div>
			{:else if msg.message_type === 'image' && msg.file_url}
				<div class="bg-teal-500 p-1 rounded-2xl rounded-br-md cursor-pointer" onclick={() => onLightbox(msg.file_url!)} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onLightbox(msg.file_url!); } }} role="button" tabindex="0" aria-label="Fotoğrafı büyüt">
					<img src={msg.file_url} alt={msg.file_name || 'Fotoğraf'} class="max-w-full max-h-64 rounded-xl object-cover" loading="lazy" />
					{#if msg.content && msg.content !== msg.file_name}<p class="text-white text-sm px-2 py-1">{msg.content}</p>{/if}
				</div>
			{:else if msg.message_type === 'video' && msg.file_url}
				<div class="bg-teal-500 p-1 rounded-2xl rounded-br-md">
					<!-- svelte-ignore a11y_media_has_caption -->
					<video src={msg.file_url} controls class="max-w-full max-h-64 rounded-xl" preload="metadata"></video>
					{#if msg.content && msg.content !== msg.file_name}<p class="text-white text-sm px-2 py-1">{msg.content}</p>{/if}
				</div>
			{:else if msg.message_type === 'file' && msg.file_url}
				<div class="bg-teal-500 text-white px-3 md:px-4 py-2 rounded-2xl rounded-br-md">
					<a href={msg.file_url} download={msg.file_name} class="flex items-center gap-2 hover:opacity-80" onclick={(e) => e.stopPropagation()}>
						<span class="text-2xl">{getFileIcon(msg.file_type)}</span>
						<div class="min-w-0"><p class="text-sm font-medium truncate">{msg.file_name}</p><p class="text-xs opacity-75">{formatFileSize(msg.file_size)}</p></div>
					</a>
					{#if msg.content && msg.content !== msg.file_name}<p class="text-sm mt-1">{msg.content}</p>{/if}
				</div>
			{:else}
				<div class="bg-teal-500 text-white px-3 md:px-4 py-2 rounded-2xl rounded-br-md text-sm whitespace-pre-wrap break-words {editingMsgId === msg.id ? 'ring-2 ring-teal-300' : ''}">{msg.content}</div>
			{/if}
			<div class="flex items-center gap-1 mt-0.5 justify-end">
				{#if msg.is_edited && !msg.is_deleted}<span class="text-[10px] text-gray-300 italic">düzenlendi</span>{/if}
				<span class="text-[10px] text-gray-300">{formatMsgTime(msg.created_at)}</span>
				{#if !msg.is_deleted && isPrivate}
					{#if isRead}
						<svg class="w-4 h-3 text-blue-500 shrink-0" viewBox="0 0 24 14" fill="none"><path d="M2 7l3.5 3.5L13 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 7l3.5 3.5L19 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
					{:else}
						<svg class="w-3 h-3 text-gray-300 shrink-0" viewBox="0 0 14 14" fill="none"><path d="M2 7l3.5 3.5L12 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{:else}
	<!-- Alınan (sol) -->
	<div data-msg-id={msg.id} class="flex justify-start transition-all">
		<div class="max-w-[85%] md:max-w-[70%]">
			{#if isGroupChat && msg.sender_name}
				<p class="text-xs ml-1 mb-0.5 font-semibold {uc?.name || 'text-gray-400'}">{msg.sender_name}</p>
			{/if}
			{#if msg.is_deleted}
				<div class="bg-gray-100 border border-gray-200 px-3 md:px-4 py-2 rounded-2xl rounded-bl-md"><p class="text-sm text-gray-400 italic">Bu mesaj silindi</p></div>
			{:else if msg.message_type === 'image' && msg.file_url}
				<div class="{uc ? uc.imgBg : 'bg-white border border-gray-200'} p-1 rounded-2xl rounded-bl-md cursor-pointer" onclick={() => onLightbox(msg.file_url!)} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onLightbox(msg.file_url!); } }} role="button" tabindex="0" aria-label="Fotoğrafı büyüt">
					<img src={msg.file_url} alt={msg.file_name || 'Fotoğraf'} class="max-w-full max-h-64 rounded-xl object-cover" loading="lazy" />
					{#if msg.content && msg.content !== msg.file_name}<p class="{uc ? 'text-white' : 'text-gray-900'} text-sm px-2 py-1">{msg.content}</p>{/if}
				</div>
			{:else if msg.message_type === 'video' && msg.file_url}
				<div class="{uc ? uc.imgBg : 'bg-white border border-gray-200'} p-1 rounded-2xl rounded-bl-md">
					<!-- svelte-ignore a11y_media_has_caption -->
					<video src={msg.file_url} controls class="max-w-full max-h-64 rounded-xl" preload="metadata"></video>
					{#if msg.content && msg.content !== msg.file_name}<p class="{uc ? 'text-white' : 'text-gray-900'} text-sm px-2 py-1">{msg.content}</p>{/if}
				</div>
			{:else if msg.message_type === 'file' && msg.file_url}
				<div class="{uc ? uc.fileBg + ' text-white' : 'bg-white border border-gray-200 text-gray-900'} px-3 md:px-4 py-2 rounded-2xl rounded-bl-md">
					<a href={msg.file_url} download={msg.file_name} class="flex items-center gap-2 hover:opacity-80">
						<span class="text-2xl">{getFileIcon(msg.file_type)}</span>
						<div class="min-w-0"><p class="text-sm font-medium truncate">{msg.file_name}</p><p class="text-xs {uc ? 'opacity-75' : 'text-gray-400'}">{formatFileSize(msg.file_size)}</p></div>
					</a>
					{#if msg.content && msg.content !== msg.file_name}<p class="text-sm mt-1">{msg.content}</p>{/if}
				</div>
			{:else}
				<div class="{uc ? uc.bg + ' ' + uc.text : 'bg-white border border-gray-200 text-gray-900'} px-3 md:px-4 py-2 rounded-2xl rounded-bl-md text-sm whitespace-pre-wrap break-words">{msg.content}</div>
			{/if}
			<div class="flex items-center gap-1 mt-0.5">
				{#if msg.is_edited && !msg.is_deleted}<span class="text-[10px] text-gray-300 italic">düzenlendi</span>{/if}
				<span class="text-[10px] text-gray-300">{formatMsgTime(msg.created_at)}</span>
			</div>
		</div>
	</div>
{/if}
