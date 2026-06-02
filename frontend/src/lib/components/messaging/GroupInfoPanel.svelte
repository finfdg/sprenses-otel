<script lang="ts">
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import type { GroupMember } from '$lib/types/messaging';

	let {
		show = $bindable(false),
		conversationId,
		name = '',
		members = [],
		createdBy = null,
		currentUserId,
		onAddMember,
		onMemberRemoved,
		onLeftGroup,
		onRefresh,
		onNameUpdated,
	}: {
		show: boolean;
		conversationId: number;
		name: string;
		members: GroupMember[];
		createdBy: number | null;
		currentUserId: number;
		onAddMember: () => void;
		onMemberRemoved: () => void;
		onLeftGroup: () => void;
		onRefresh: () => void;
		onNameUpdated: (newName: string) => void;
	} = $props();

	// İsim düzenleme inline state
	let editingName = $state(false);
	let editNameValue = $state('');

	// Confirm dialog state
	let showConfirm = $state(false);
	let confirmMessage = $state('');
	let _confirmResolve: ((v: boolean) => void) | null = null;

	function requestConfirm(message: string): Promise<boolean> {
		confirmMessage = message;
		showConfirm = true;
		return new Promise(resolve => { _confirmResolve = resolve; });
	}

	function isCurrentUserAdmin(): boolean {
		return members.some(m => m.id === currentUserId && m.is_admin);
	}

	function startNameEdit() {
		editNameValue = name;
		editingName = true;
	}

	async function saveGroupName() {
		if (!editNameValue.trim() || editNameValue.trim() === name) {
			editingName = false;
			return;
		}
		try {
			await api.patch(`/messages/conversations/${conversationId}/name`, { name: editNameValue.trim() });
			onNameUpdated(editNameValue.trim());
			editingName = false;
		} catch (err) {
			console.error('Grup adı değiştirilemedi:', err);
			showToast(err instanceof Error ? err.message : 'Grup adı değiştirilirken bir hata oluştu', 'error');
		}
	}

	async function removeGroupMember(userId: number) {
		const isSelf = userId === currentUserId;
		const confirmed = await requestConfirm(
			isSelf ? 'Gruptan ayrılmak istediğinize emin misiniz?' : 'Bu üyeyi gruptan çıkarmak istediğinize emin misiniz?'
		);
		if (!confirmed) return;
		try {
			await api.delete(`/messages/conversations/${conversationId}/members/${userId}`);
			if (isSelf) {
				show = false;
				onLeftGroup();
			} else {
				onMemberRemoved();
			}
		} catch (err) {
			console.error('Üye çıkarılamadı:', err);
			showToast(err instanceof Error ? err.message : 'Üye çıkarılırken bir hata oluştu', 'error');
		}
	}

	async function toggleAdmin(userId: number, makeAdmin: boolean) {
		if (!makeAdmin && userId === currentUserId) {
			const confirmed = await requestConfirm('Yönetici yetkinizi bırakmak istediğinize emin misiniz?');
			if (!confirmed) return;
		}
		try {
			await api.patch(`/messages/conversations/${conversationId}/admins/${userId}`, { is_admin: makeAdmin });
			onRefresh();
		} catch (err) {
			console.error('Yönetici güncellenemedi:', err);
			showToast(err instanceof Error ? err.message : 'Yönetici güncellenirken bir hata oluştu', 'error');
		}
	}
</script>

{#if show}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="absolute inset-0 z-20 flex" onclick={() => show = false} onkeydown={(e) => { if (e.key === 'Escape') show = false; }}>
		<div class="flex-1"></div>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="w-72 md:w-80 bg-white border-l border-gray-200 flex flex-col shadow-xl" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<div class="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
				<h3 class="text-sm font-bold text-gray-900">Grup Bilgisi</h3>
				<button onclick={() => show = false} class="text-gray-400 hover:text-gray-600 cursor-pointer">✕</button>
			</div>

			<div class="px-4 py-3 border-b border-gray-100">
				<p class="text-xs text-gray-400 mb-1">Grup Adı</p>
				{#if editingName}
					<div class="flex items-center gap-2">
						<input
							type="text"
							bind:value={editNameValue}
							onkeydown={(e) => { if (e.key === 'Enter') saveGroupName(); if (e.key === 'Escape') editingName = false; }}
							class="flex-1 text-sm px-2 py-1 bg-gray-100 rounded-lg text-gray-900 outline-none focus:ring-2 focus:ring-teal-100"
						/>
						<button onclick={saveGroupName} class="text-xs text-teal-600 hover:text-teal-700 cursor-pointer font-medium">Kaydet</button>
						<button onclick={() => editingName = false} class="text-xs text-gray-400 hover:text-gray-600 cursor-pointer">İptal</button>
					</div>
				{:else}
					<div class="flex items-center gap-2">
						<p class="text-sm font-semibold text-gray-900 flex-1">{name || 'Grup'}</p>
						{#if isCurrentUserAdmin()}
							<button onclick={startNameEdit} class="text-xs text-teal-600 hover:underline cursor-pointer">Düzenle</button>
						{/if}
					</div>
				{/if}
			</div>

			<div class="px-4 py-3 border-b border-gray-100 flex-1 overflow-hidden flex flex-col">
				<div class="flex items-center justify-between mb-2">
					<p class="text-xs text-gray-400">Üyeler ({members.length})</p>
					{#if isCurrentUserAdmin()}
						<button onclick={onAddMember} class="text-xs text-teal-600 hover:underline cursor-pointer">Üye Ekle</button>
					{/if}
				</div>
				<div class="space-y-1 overflow-y-auto flex-1">
					{#each members as member}
						<div class="flex items-center gap-2 py-1.5">
							<div class="w-7 h-7 rounded-full bg-teal-100 flex items-center justify-center shrink-0">
								<span class="text-xs font-semibold text-teal-700">{member.first_name.charAt(0).toUpperCase()}</span>
							</div>
							<div class="flex-1 min-w-0">
								<p class="text-sm text-gray-900 truncate">
									{member.first_name} {member.last_name}
									{#if member.id === currentUserId}<span class="text-gray-400"> (Sen)</span>{/if}
								</p>
								{#if member.is_admin}<span class="text-[10px] text-amber-600 font-medium">Yönetici</span>{/if}
							</div>
							{#if isCurrentUserAdmin()}
								<div class="flex items-center gap-1 shrink-0">
									{#if member.is_admin}
										<button onclick={() => toggleAdmin(member.id, false)} class="text-[10px] text-gray-400 hover:text-gray-600 cursor-pointer">
											{member.id === currentUserId ? 'Yetkimi Bırak' : 'Kaldır'}
										</button>
									{:else}
										<button onclick={() => toggleAdmin(member.id, true)} class="text-[10px] text-teal-600 hover:text-teal-700 cursor-pointer">Yönetici</button>
									{/if}
									{#if member.id !== currentUserId}
										<button onclick={() => removeGroupMember(member.id)} class="text-[10px] text-red-500 hover:text-red-600 cursor-pointer ml-1">Çıkar</button>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>

			<div class="px-4 py-3 shrink-0">
				<button onclick={() => removeGroupMember(currentUserId)} class="w-full py-2 text-sm text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors cursor-pointer font-medium">Gruptan Ayrıl</button>
			</div>
		</div>
	</div>
{/if}

<ConfirmDialog
	bind:show={showConfirm}
	title="Onay"
	message={confirmMessage}
	confirmText="Evet"
	cancelText="İptal"
	danger
	onConfirm={() => _confirmResolve?.(true)}
	onCancel={() => _confirmResolve?.(false)}
/>
