<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Check, Pencil, X } from 'lucide-svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { formatFileSize, getFileIcon } from '$lib/types/messaging';
	import EmojiPicker from '$lib/components/EmojiPicker.svelte';

	let {
		messageInput = $bindable(''),
		editingMsgId = null,
		editContent = $bindable(''),
		sendingMessage = false,
		typingUserName = '',
		otherUserTyping = false,
		onSendMessage,
		onSaveEdit,
		onCancelEdit,
		onTypingInput,
		onDraftSave,
		onSendFile,
	}: {
		messageInput: string;
		editingMsgId?: number | null;
		editContent: string;
		sendingMessage?: boolean;
		typingUserName?: string;
		otherUserTyping?: boolean;
		onSendMessage: () => void;
		onSaveEdit: () => void;
		onCancelEdit: () => void;
		onTypingInput: () => void;
		onDraftSave: () => void;
		onSendFile: (file: File, caption: string) => void;
	} = $props();

	let messageInputEl: HTMLTextAreaElement;
	let editInputEl: HTMLInputElement;
	let fileInputEl: HTMLInputElement;
	let cameraInputEl: HTMLInputElement;

	// Dosya gönderme
	let pendingFile = $state<File | null>(null);
	let pendingFilePreview = $state<string | null>(null);
	let fileCaption = $state('');
	let uploadingFile = $state(false);

	// Menüler
	let showEmojiPicker = $state(false);
	let showAttachMenu = $state(false);

	function autoResizeTextarea() {
		if (!messageInputEl) return;
		messageInputEl.style.height = 'auto';
		messageInputEl.style.height = Math.min(messageInputEl.scrollHeight, 120) + 'px';
	}

	function handleKeyDown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			if (editingMsgId) onSaveEdit();
			else if (pendingFile) handleSendFile();
			else onSendMessage();
		}
		if (e.key === 'Escape') {
			if (editingMsgId) onCancelEdit();
			if (pendingFile) clearPendingFile();
			if (showEmojiPicker) showEmojiPicker = false;
			if (showAttachMenu) showAttachMenu = false;
		}
	}

	function handleFileSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		setPendingFile(file);
		input.value = '';
	}

	const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25 MB

	function setPendingFile(file: File) {
		if (file.size > MAX_FILE_SIZE) {
			showToast(`Dosya boyutu çok büyük (maks. 25 MB). Seçilen: ${(file.size / (1024 * 1024)).toFixed(1)} MB`, 'error');
			return;
		}
		if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
		pendingFile = file;
		fileCaption = '';
		if (file.type.startsWith('image/') || file.type.startsWith('video/')) {
			pendingFilePreview = URL.createObjectURL(file);
		} else {
			pendingFilePreview = null;
		}
	}

	function clearPendingFile() {
		if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
		pendingFile = null;
		pendingFilePreview = null;
		fileCaption = '';
	}

	async function handleSendFile() {
		if (!pendingFile || uploadingFile) return;
		uploadingFile = true;
		try {
			await onSendFile(pendingFile, fileCaption.trim());
			clearPendingFile();
		} catch (err) {
			console.error('Dosya gönderilemedi:', err);
			showToast('Dosya gönderilirken bir hata oluştu', 'error');
		}
		uploadingFile = false;
	}

	function handleEmojiSelect(emoji: string) {
		messageInput += emoji;
		showEmojiPicker = false;
		showAttachMenu = false;
		if (messageInputEl) {
			messageInputEl.focus();
			autoResizeTextarea();
		}
	}

	export function focusInput() {
		if (messageInputEl) messageInputEl.focus();
	}

	export function resetHeight() {
		if (messageInputEl) messageInputEl.style.height = 'auto';
	}

	export function hasPendingFile(): boolean {
		return !!pendingFile;
	}

	export function clearFile() {
		clearPendingFile();
	}

	onDestroy(() => {
		if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
	});
</script>

<!-- Dosya Önizleme -->
{#if pendingFile}
	<div class="bg-white border-t border-gray-200 p-3 shrink-0">
		<div class="flex items-start gap-3">
			{#if pendingFilePreview && pendingFile.type.startsWith('image/')}
				<img src={pendingFilePreview} alt="Önizleme" class="w-16 h-16 rounded-lg object-cover" />
			{:else if pendingFilePreview && pendingFile.type.startsWith('video/')}
				<!-- svelte-ignore a11y_media_has_caption -->
				<video src={pendingFilePreview} class="w-16 h-16 rounded-lg object-cover"></video>
			{:else}
				<div class="w-16 h-16 rounded-lg bg-gray-100 flex items-center justify-center text-2xl">{getFileIcon(pendingFile.type)}</div>
			{/if}
			<div class="flex-1 min-w-0">
				<p class="text-sm font-medium text-gray-900 truncate">{pendingFile.name}</p>
				<p class="text-xs text-gray-500">{formatFileSize(pendingFile.size)}</p>
				<input type="text" bind:value={fileCaption} onkeydown={handleKeyDown} placeholder="Açıklama ekle..." class="mt-1 w-full px-2 py-1 bg-gray-100 rounded text-base md:text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-1 focus:ring-teal-100" />
			</div>
			<div class="flex items-center gap-1 shrink-0">
				<button onclick={clearPendingFile} class="w-8 h-8 rounded-full text-gray-500 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center cursor-pointer" title="İptal"><X class="w-4 h-4" /></button>
				<button onclick={handleSendFile} disabled={uploadingFile} class="w-10 h-10 rounded-full bg-teal-700 text-white flex items-center justify-center hover:bg-teal-800 transition-colors cursor-pointer disabled:opacity-40 shrink-0" title="Gönder">
					{#if uploadingFile}<div class="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
					{:else}<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" /></svg>{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Düzenleme modu -->
{#if editingMsgId}
	<div class="bg-white border-t border-gray-200 shrink-0">
		<div class="px-3 py-1.5 bg-teal-50 border-b border-teal-100 flex items-center justify-between">
			<span class="text-xs text-teal-700 font-medium inline-flex items-center gap-1"><Pencil class="w-3 h-3" /> Mesaj düzenleniyor</span>
			<button onclick={onCancelEdit} class="text-gray-500 hover:text-gray-600 cursor-pointer p-0.5" title="Vazgeç"><X class="w-4 h-4" /></button>
		</div>
		<div class="p-2 md:p-3 flex items-center gap-2">
			<input bind:this={editInputEl} type="text" bind:value={editContent} onkeydown={handleKeyDown} placeholder="Mesajı düzenle..." class="flex-1 bg-gray-100 rounded-full px-4 py-2.5 text-base md:text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-2 focus:ring-teal-100 focus:bg-white transition-all" />
			<button onclick={onSaveEdit} disabled={!editContent.trim()} class="w-10 h-10 rounded-full bg-teal-700 text-white flex items-center justify-center hover:bg-teal-800 transition-colors cursor-pointer disabled:opacity-40 shrink-0" title="Kaydet"><Check class="w-5 h-5" /></button>
		</div>
	</div>
{:else if !pendingFile}
	{#if otherUserTyping}
		<div class="bg-white border-t border-gray-100 px-4 py-1 shrink-0"><span class="text-xs text-gray-500 italic">{typingUserName || 'Birisi'} yazıyor...</span></div>
	{/if}
	<div class="bg-white border-t border-gray-200 px-2 pt-2 pb-5 md:px-3 md:py-2 flex items-end gap-1.5 shrink-0 relative">
		<!-- Ek menüsü butonu -->
		<div class="relative shrink-0">
			<button onclick={() => { showAttachMenu = !showAttachMenu; showEmojiPicker = false; }} class="w-9 h-9 rounded-full text-gray-500 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-all cursor-pointer {showAttachMenu ? 'bg-gray-100 text-gray-600 rotate-45' : ''}" title="Ekle">
				<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
			</button>
			{#if showAttachMenu}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="absolute bottom-full left-0 mb-2 bg-white shadow-xl rounded-xl border border-gray-200 py-1 min-w-[160px] z-30" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
					<button onclick={() => { fileInputEl?.click(); showAttachMenu = false; }} class="w-full px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2.5 cursor-pointer">
						<svg class="w-4.5 h-4.5 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" /></svg>
						Dosya
					</button>
					<button onclick={() => { showEmojiPicker = !showEmojiPicker; showAttachMenu = false; }} class="w-full px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2.5 cursor-pointer">
						<span class="text-base">😊</span>
						Emoji
					</button>
					<button onclick={() => { cameraInputEl?.click(); showAttachMenu = false; }} class="w-full px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2.5 cursor-pointer">
						<svg class="w-4.5 h-4.5 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" /><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" /></svg>
						Kamera
					</button>
				</div>
			{/if}
		</div>
		<input bind:this={fileInputEl} type="file" accept="image/jpeg,image/png,image/gif,image/webp,video/mp4,video/webm,video/quicktime,video/3gpp,.mov,.3gp,.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv" onchange={handleFileSelect} class="hidden" />
		<input bind:this={cameraInputEl} type="file" accept="image/jpeg,image/png,image/gif,image/webp,video/mp4,video/webm,video/quicktime,video/3gpp,.mov,.3gp" capture="environment" onchange={handleFileSelect} class="hidden" />
		<!-- Mesaj textarea -->
		<textarea bind:this={messageInputEl} bind:value={messageInput} onkeydown={handleKeyDown} oninput={() => { onTypingInput(); autoResizeTextarea(); onDraftSave(); }} placeholder="Mesajınızı yazın..." rows="1" class="flex-1 min-w-0 bg-gray-100 rounded-2xl px-4 py-2 text-base md:text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-2 focus:ring-teal-100 focus:bg-white transition-all resize-none leading-snug max-h-[120px] overflow-y-auto"></textarea>
		<!-- Gönder -->
		<button onclick={onSendMessage} disabled={sendingMessage || !messageInput.trim()} class="w-9 h-9 rounded-full bg-teal-700 text-white flex items-center justify-center hover:bg-teal-800 transition-colors cursor-pointer disabled:opacity-40 shrink-0" title="Gönder">
			<svg class="w-4.5 h-4.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" /></svg>
		</button>
	</div>
{/if}

{#if showEmojiPicker}<EmojiPicker onSelect={handleEmojiSelect} onClose={() => { showEmojiPicker = false; showAttachMenu = false; }} />{/if}
