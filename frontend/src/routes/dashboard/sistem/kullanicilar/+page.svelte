<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onlinePresence, onWsEvent } from '$lib/stores/websocket.svelte';
	import { validateRequired, validateEmail, validatePassword } from '$lib/utils/validation';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import { Plus, Pencil, KeyRound, Trash2, Users, Eye, EyeOff, MailCheck } from 'lucide-svelte';

	const canUse = hasPermission('system.users', 'use');

	interface Role { id: number; name: string; }
	interface UserItem {
		id: number; username: string; email: string; first_name: string; last_name: string;
		role_id: number; role: Role | null; is_active: boolean; created_at: string; last_online_at: string | null;
		email_verified: boolean; email_verified_at: string | null;
	}

	function isOnline(userId: number): boolean {
		void onlinePresence.version;
		return onlinePresence.ids.has(userId);
	}

	function formatLastSeen(dateStr: string | null): string {
		if (!dateStr) return '';
		const d = new Date(dateStr);
		const diff = Math.floor((new Date().getTime() - d.getTime()) / 1000);
		if (diff < 60) return 'Az önce';
		if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
		if (diff < 86400) return `${Math.floor(diff / 3600)} saat önce`;
		if (diff < 604800) return `${Math.floor(diff / 86400)} gün önce`;
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	}

	// State
	let users = $state<UserItem[]>([]);
	let roles = $state<Role[]>([]);
	let loading = $state(true);

	// Form modal
	let showModal = $state(false);
	let editingUser = $state<UserItem | null>(null);
	let formFirstName = $state('');
	let formLastName = $state('');
	let formUsername = $state('');
	let formEmail = $state('');
	let formPassword = $state('');
	let formRoleId = $state(2);
	let formActive = $state(true);
	let formError = $state('');
	let saving = $state(false);
	let fieldErrors = $state<Record<string, string | null>>({});
	let showPwd = $state(false);

	// Reset şifre modal
	let showResetModal = $state(false);
	let resetUserId = $state(0);
	let resetPassword = $state('');
	let resetError = $state('');
	let resetting = $state(false);
	let showResetPwd = $state(false);

	// Silme
	let showDeleteConfirm = $state(false);
	let deleteTarget = $state<UserItem | null>(null);

	async function loadData() {
		loading = true;
		try {
			const [uRes, r] = await Promise.all([
				api.get<any>('/system/users/?page=1&page_size=200'),
				api.get<any[]>('/system/roles/'),
			]);
			users = uRes.items ?? uRes;
			roles = r.map((role: any) => ({ id: role.id, name: role.name }));
		} catch (err) {
			console.error('Kullanıcı verileri yüklenemedi:', err);
			showToast('Kullanıcı verileri yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	function openCreate() {
		editingUser = null;
		formFirstName = ''; formLastName = ''; formUsername = ''; formEmail = '';
		formPassword = ''; formRoleId = 2; formActive = true; formError = ''; fieldErrors = {}; showPwd = false;
		showModal = true;
	}

	function openEdit(u: UserItem) {
		editingUser = u;
		formFirstName = u.first_name; formLastName = u.last_name; formUsername = u.username;
		formEmail = u.email; formPassword = ''; formRoleId = u.role_id; formActive = u.is_active;
		formError = ''; fieldErrors = {}; showPwd = false;
		showModal = true;
	}

	function validateForm(): boolean {
		const errors: Record<string, string | null> = {};
		errors.first_name = validateRequired(formFirstName, 'Ad');
		errors.username = validateRequired(formUsername, 'Kullanıcı adı');
		errors.email = validateEmail(formEmail);
		errors.password = validatePassword(formPassword, !editingUser);
		fieldErrors = errors;
		return !Object.values(errors).some((e) => e !== null);
	}

	async function handleSave() {
		formError = '';
		if (!validateForm()) return;
		saving = true;
		try {
			if (editingUser) {
				const data: any = {
					first_name: formFirstName, last_name: formLastName, username: formUsername,
					email: formEmail || '', role_id: formRoleId, is_active: formActive,
				};
				if (formPassword) data.password = formPassword;
				await api.patch(`/system/users/${editingUser.id}`, data);
			} else {
				await api.post('/system/users/', {
					first_name: formFirstName, last_name: formLastName, username: formUsername,
					email: formEmail || '', password: formPassword, role_id: formRoleId, is_active: formActive,
				});
			}
			showModal = false;
			showToast(editingUser ? 'Kullanıcı güncellendi' : 'Kullanıcı oluşturuldu', 'success');
			await loadData();
		} catch (err: any) {
			formError = err.message || 'Hata oluştu';
			if (err instanceof ApiError && err.fields.length > 0) {
				const updated = { ...fieldErrors };
				for (const f of err.fields) updated[f] = ' ';
				fieldErrors = updated;
			}
		} finally {
			saving = false;
		}
	}

	function askDelete(u: UserItem) { deleteTarget = u; showDeleteConfirm = true; }

	async function handleDelete() {
		if (!deleteTarget) return;
		try {
			await api.delete(`/system/users/${deleteTarget.id}`);
			showToast('Kullanıcı silindi', 'success');
			await loadData();
		} catch (err: any) {
			showToast(err.message || 'Silinemedi', 'error');
		} finally {
			deleteTarget = null;
		}
	}

	function openReset(u: UserItem) {
		resetUserId = u.id; resetPassword = ''; resetError = ''; showResetPwd = false; showResetModal = true;
	}

	async function handleResetPassword() {
		if (!resetPassword || resetPassword.length < 8) { resetError = 'Şifre en az 8 karakter olmalıdır'; return; }
		resetting = true; resetError = '';
		try {
			await api.post(`/system/users/${resetUserId}/reset-password`, { new_password: resetPassword });
			showResetModal = false;
			showToast('Şifre başarıyla sıfırlandı', 'success');
		} catch (err: any) {
			resetError = err?.message || 'Şifre sıfırlanırken bir hata oluştu';
		} finally {
			resetting = false;
		}
	}

	let verifyingId = $state<number | null>(null);
	async function sendVerification(u: UserItem) {
		verifyingId = u.id;
		try {
			await api.post(`/system/users/${u.id}/send-verification`, {});
			showToast(`Teyit e-postası gönderildi: ${u.email}`, 'success');
		} catch (err: any) {
			console.error('Teyit e-postası gönderilemedi:', err);
			showToast(err?.message || 'Teyit e-postası gönderilemedi', 'error');
		} finally {
			verifyingId = null;
		}
	}

	onMount(() => {
		loadData();
		// Kullanıcı offline olduğunda last_online_at'i anında güncelle
		const unsub = onWsEvent('user_status', (data: any) => {
			if (!data.is_online && typeof data.user_id === 'number') {
				const idx = users.findIndex((u) => u.id === data.user_id);
				if (idx !== -1) users[idx].last_online_at = new Date().toISOString();
			}
		});
		return unsub;
	});
</script>

<svelte:head><title>Kullanıcılar · Sprenses</title></svelte:head>

<div class="max-w-4xl mx-auto space-y-5 sm:space-y-6">
	<PageHeader title="Kullanıcılar" description="Sistem kullanıcılarını, rollerini ve erişimlerini yönetin">
		{#snippet actions()}
			{#if canUse}
				<Button onclick={openCreate}><Plus size={16} /> Yeni Kullanıcı</Button>
			{/if}
		{/snippet}
	</PageHeader>

	{#if loading}
		<div class="grid gap-3">
			{#each Array(4) as _, i (i)}
				<div class="bg-white border border-gray-200 rounded-xl p-4 md:p-5 shadow-sm flex items-center justify-between animate-pulse">
					<div class="space-y-2">
						<div class="h-4 w-44 bg-gray-200 rounded"></div>
						<div class="h-3 w-28 bg-gray-100 rounded"></div>
					</div>
					<div class="h-8 w-40 bg-gray-100 rounded-lg"></div>
				</div>
			{/each}
		</div>
	{:else if users.length === 0}
		<div class="bg-white border border-gray-200 rounded-2xl shadow-sm">
			<EmptyState icon={Users} title="Henüz kullanıcı yok" description={canUse ? "İlk kullanıcıyı eklemek için 'Yeni Kullanıcı' butonunu kullanın." : 'Görüntülenecek kullanıcı bulunmuyor.'} ctaText={canUse ? 'Yeni Kullanıcı' : ''} onCta={canUse ? openCreate : null} />
		</div>
	{:else}
		<div class="grid gap-3">
			{#each users as u (u.id)}
				<div class="bg-white border border-gray-200 rounded-xl p-4 md:p-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between shadow-sm">
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="relative flex h-2.5 w-2.5 shrink-0" aria-hidden="true">
								{#if isOnline(u.id)}
									<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
									<span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500"></span>
								{:else}
									<span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-gray-300"></span>
								{/if}
							</span>
							<span class="font-semibold text-gray-900 truncate">{u.first_name} {u.last_name}</span>
							<span class="text-gray-500 text-sm truncate">@{u.username}</span>
						</div>
						<div class="flex flex-wrap items-center gap-2 mt-1.5 ml-[18px]">
							<span class="text-xs font-medium px-2 py-0.5 rounded-full bg-teal-50 text-teal-700 border border-teal-200">{u.role?.name || '—'}</span>
							{#if !u.is_active}
								<StatusBadge type="neutral">Pasif</StatusBadge>
							{/if}
							{#if u.email}
								{#if u.email_verified}
									<StatusBadge type="success">E-posta teyitli</StatusBadge>
								{:else}
									<StatusBadge type="warning">E-posta teyit bekliyor</StatusBadge>
								{/if}
							{:else}
								<span class="text-xs text-gray-500">E-posta yok</span>
							{/if}
							{#if isOnline(u.id)}
								<span class="text-xs text-green-600 font-medium">● Çevrimiçi</span>
							{:else}
								<span class="text-xs text-gray-500" title={u.last_online_at ? new Date(u.last_online_at).toLocaleString('tr-TR') : ''}>
									{u.last_online_at ? `Son görülme: ${formatLastSeen(u.last_online_at)}` : 'Çevrimdışı'}
								</span>
							{/if}
						</div>
					</div>
					{#if canUse}
						<div class="flex items-center gap-2 shrink-0 flex-wrap justify-end">
							{#if u.email && !u.email_verified}
								<Button variant="secondary" size="sm" loading={verifyingId === u.id} onclick={() => sendVerification(u)} title="Teyit e-postası gönder"><MailCheck size={14} /> Teyit gönder</Button>
							{/if}
							<Button variant="secondary" size="sm" onclick={() => openEdit(u)}><Pencil size={14} /> Düzenle</Button>
							<Button variant="secondary" size="sm" onclick={() => openReset(u)} title="Şifre sıfırla"><KeyRound size={14} /> Şifre</Button>
							<Button variant="danger" size="sm" onclick={() => askDelete(u)}><Trash2 size={14} /> Sil</Button>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Oluştur / Düzenle Modal -->
<Modal bind:show={showModal} title={editingUser ? 'Kullanıcıyı Düzenle' : 'Yeni Kullanıcı'} maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4" novalidate>
		{#if formError}
			<div class="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-lg text-sm" role="alert">{formError}</div>
		{/if}

		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="u-first" class="block text-sm font-medium text-gray-700 mb-1">Ad <span class="text-red-600">*</span></label>
				<Input id="u-first" bind:value={formFirstName} placeholder="Ad" invalid={!!fieldErrors.first_name} aria-describedby={fieldErrors.first_name ? 'u-first-error' : undefined} />
				{#if fieldErrors.first_name}<p id="u-first-error" class="text-xs text-red-600 mt-1">{fieldErrors.first_name}</p>{/if}
			</div>
			<div>
				<label for="u-last" class="block text-sm font-medium text-gray-700 mb-1">Soyad</label>
				<Input id="u-last" bind:value={formLastName} placeholder="Soyad" />
			</div>
		</div>

		<div>
			<label for="u-username" class="block text-sm font-medium text-gray-700 mb-1">Kullanıcı Adı <span class="text-red-600">*</span></label>
			<Input id="u-username" bind:value={formUsername} placeholder="kullaniciadi" invalid={!!fieldErrors.username} aria-describedby={fieldErrors.username ? 'u-username-error' : undefined} />
			{#if fieldErrors.username}<p id="u-username-error" class="text-xs text-red-600 mt-1">{fieldErrors.username}</p>{/if}
		</div>

		<div>
			<label for="u-email" class="block text-sm font-medium text-gray-700 mb-1">E-posta <span class="text-gray-500 font-normal">(isteğe bağlı)</span></label>
			<Input id="u-email" type="email" bind:value={formEmail} placeholder="ornek@sprenses.com" invalid={!!fieldErrors.email} aria-describedby={fieldErrors.email ? 'u-email-error' : undefined} />
			{#if fieldErrors.email}<p id="u-email-error" class="text-xs text-red-600 mt-1">{fieldErrors.email}</p>{/if}
		</div>

		<div>
			<label for="u-password" class="block text-sm font-medium text-gray-700 mb-1">Şifre {#if editingUser}<span class="text-gray-500 font-normal">(boş bırakırsanız değişmez)</span>{:else}<span class="text-red-600">*</span>{/if}</label>
			<div class="relative">
				<Input id="u-password" type={showPwd ? 'text' : 'password'} bind:value={formPassword} invalid={!!fieldErrors.password} aria-describedby={fieldErrors.password ? 'u-password-error' : undefined} class="pr-10" />
				<button type="button" onclick={() => showPwd = !showPwd} aria-label={showPwd ? 'Şifreyi gizle' : 'Şifreyi göster'} class="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-600 cursor-pointer">
					{#if showPwd}<EyeOff size={16} />{:else}<Eye size={16} />{/if}
				</button>
			</div>
			{#if fieldErrors.password}<p id="u-password-error" class="text-xs text-red-600 mt-1">{fieldErrors.password}</p>{/if}
		</div>

		<div>
			<label for="u-role" class="block text-sm font-medium text-gray-700 mb-1">Rol</label>
			<Select id="u-role" bind:value={formRoleId}>
				{#each roles as r (r.id)}<option value={r.id}>{r.name}</option>{/each}
			</Select>
		</div>

		<label class="flex items-center gap-2 cursor-pointer">
			<input type="checkbox" bind:checked={formActive} class="accent-teal-700 w-4 h-4" />
			<span class="text-sm text-gray-700">Aktif kullanıcı</span>
		</label>

		<div class="flex justify-end gap-2 pt-1">
			<Button variant="secondary" onclick={() => showModal = false}>İptal</Button>
			<Button type="submit" loading={saving}>{editingUser ? 'Güncelle' : 'Kaydet'}</Button>
		</div>
	</form>
</Modal>

<!-- Şifre Sıfırla Modal -->
<Modal bind:show={showResetModal} title="Şifre Sıfırla" maxWidth="max-w-sm">
	<form onsubmit={(e) => { e.preventDefault(); handleResetPassword(); }} class="space-y-4">
		<div>
			<label for="u-reset-pwd" class="block text-sm font-medium text-gray-700 mb-1">Yeni Şifre</label>
			<div class="relative">
				<Input id="u-reset-pwd" type={showResetPwd ? 'text' : 'password'} bind:value={resetPassword} placeholder="En az 6 karakter" class="pr-10" />
				<button type="button" onclick={() => showResetPwd = !showResetPwd} aria-label={showResetPwd ? 'Şifreyi gizle' : 'Şifreyi göster'} class="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-600 cursor-pointer">
					{#if showResetPwd}<EyeOff size={16} />{:else}<Eye size={16} />{/if}
				</button>
			</div>
		</div>
		{#if resetError}<p class="text-sm text-red-600" role="alert">{resetError}</p>{/if}
		<div class="flex justify-end gap-2 pt-1">
			<Button variant="secondary" onclick={() => showResetModal = false}>İptal</Button>
			<Button type="submit" loading={resetting}>Sıfırla</Button>
		</div>
	</form>
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Kullanıcıyı Sil"
	message="{deleteTarget?.first_name} {deleteTarget?.last_name} kullanıcısını silmek istediğinize emin misiniz?"
	confirmText="Sil"
	cancelText="Vazgeç"
	danger={true}
	onConfirm={handleDelete}
/>
