<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { validateRequired } from '$lib/utils/validation';
	import { showToast } from '$lib/stores/toast.svelte';

	const canUse = hasPermission('system.roles', 'use');

	interface PermItem {
		module_id: number;
		module_code: string;
		module_name: string;
		can_view: boolean;
		can_use: boolean;
	}

	interface RoleItem {
		id: number;
		name: string;
		description: string | null;
		is_active: boolean;
		permissions: PermItem[];
	}

	interface ModuleItem {
		id: number;
		name: string;
		code: string;
		parent_id: number | null;
	}

	let roles = $state<RoleItem[]>([]);
	let modules = $state<ModuleItem[]>([]);
	let loading = $state(true);
	let showModal = $state(false);
	let editingRole = $state<RoleItem | null>(null);
	let showDeleteConfirm = $state(false);
	let deleteTarget = $state<RoleItem | null>(null);

	let formName = $state('');
	let formDesc = $state('');
	let formPerms = $state<Record<number, { view: boolean; use: boolean }>>({});
	let formError = $state('');
	let saving = $state(false);

	let fieldErrors = $state<Record<string, string | null>>({});

	function toggleView(moduleId: number, checked: boolean) {
		formPerms[moduleId].view = checked;
		if (!checked) {
			formPerms[moduleId].use = false;
		}
	}

	function toggleUse(moduleId: number, checked: boolean) {
		formPerms[moduleId].use = checked;
		if (checked) {
			formPerms[moduleId].view = true;
		}
	}

	onMount(async () => {
		await loadData();
	});

	async function loadData() {
		loading = true;
		try {
			const [r, m] = await Promise.all([
				api.get<RoleItem[]>('/system/roles/'),
				api.get<ModuleItem[]>('/system/modules/'),
			]);
			roles = r;
			modules = m;
		} catch (err) { console.error('Rol verileri yüklenemedi:', err); }
		loading = false;
	}

	function initPerms(existing?: PermItem[]) {
		const perms: Record<number, { view: boolean; use: boolean }> = {};
		for (const m of modules) {
			const ex = existing?.find(p => p.module_id === m.id);
			perms[m.id] = {
				view: ex?.can_view ?? false,
				use: ex?.can_use ?? false,
			};
		}
		return perms;
	}

	function openCreate() {
		editingRole = null;
		formName = '';
		formDesc = '';
		formPerms = initPerms();
		formError = '';
		fieldErrors = {};
		showModal = true;
	}

	function openEdit(r: RoleItem) {
		editingRole = r;
		formName = r.name;
		formDesc = r.description || '';
		formPerms = initPerms(r.permissions);
		formError = '';
		fieldErrors = {};
		showModal = true;
	}

	function validateForm(): boolean {
		const errors: Record<string, string | null> = {};

		errors.name = validateRequired(formName, 'Rol adı');

		fieldErrors = errors;

		return !Object.values(errors).some(e => e !== null);
	}

	async function handleSave() {
		formError = '';

		if (!validateForm()) return;

		saving = true;
		const permissions = Object.entries(formPerms).map(([mid, p]) => ({
			module_id: parseInt(mid),
			can_view: p.view,
			can_use: p.use,
		}));

		try {
			if (editingRole) {
				await api.patch(`/system/roles/${editingRole.id}`, {
					name: formName,
					description: formDesc || null,
					permissions,
				});
			} else {
				await api.post('/system/roles/', {
					name: formName,
					description: formDesc || null,
					permissions,
				});
			}
			showModal = false;
			await loadData();
		} catch (err: any) {
			formError = err.message || 'Hata oluştu';
		}
		saving = false;
	}

	function askDelete(r: RoleItem) {
		deleteTarget = r;
		showDeleteConfirm = true;
	}

	async function handleDelete() {
		if (!deleteTarget) return;
		try {
			await api.delete(`/system/roles/${deleteTarget.id}`);
			await loadData();
		} catch (err: any) {
			showToast(err.message || 'Silinemedi', 'error');
		}
	}

	// Modülleri hiyerarşik grupla: ana modül + alt modüller
	function getGroupedModules(): { parent: ModuleItem; children: ModuleItem[] }[] {
		const parents = modules.filter(m => !m.parent_id);
		return parents.map(p => ({
			parent: p,
			children: modules.filter(m => m.parent_id === p.id),
		}));
	}
</script>

<svelte:head><title>Sprenses - Roller</title></svelte:head>

<div class="max-w-4xl mx-auto">
	{#if canUse}
		<div class="flex justify-end mb-6">
			<button onclick={openCreate} class="px-4 py-2.5 sm:py-2 bg-teal-600 text-white text-sm rounded-lg hover:bg-teal-700 transition-colors cursor-pointer whitespace-nowrap">
				+ Yeni Rol
			</button>
		</div>
	{/if}

	{#if loading}
		<p class="text-gray-400">Yükleniyor...</p>
	{:else if roles.length === 0}
		<div class="bg-white border border-gray-200 rounded-2xl p-8 text-center text-gray-400 shadow-sm">
			Henüz rol yok.
		</div>
	{:else}
		<div class="grid gap-3">
			{#each roles as r}
				<div class="bg-white border border-gray-200 rounded-xl p-4 md:p-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between shadow-sm">
					<div class="min-w-0">
						<span class="font-semibold text-gray-900">{r.name}</span>
						{#if r.description}
							<span class="text-gray-400 ml-2 text-sm">{r.description}</span>
						{/if}
						<div class="text-xs text-gray-400 mt-1">{r.permissions.filter(p => p.can_view).length} modül erişimi</div>
					</div>
					{#if canUse}
					<div class="flex items-center gap-2 shrink-0">
						<button onclick={() => openEdit(r)} class="px-3 py-2 sm:py-1.5 text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer">Düzenle</button>
						<button onclick={() => askDelete(r)} class="px-3 py-2 sm:py-1.5 text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors cursor-pointer">Sil</button>
					</div>
				{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Modal -->
<Modal bind:show={showModal} title={editingRole ? 'Rol Düzenle' : 'Yeni Rol'} maxWidth="max-w-xl">
	{#if formError}
		<div class="bg-red-50 border border-red-200 text-red-600 px-3 py-2 rounded-lg text-sm mb-4">{formError}</div>
	{/if}

	<div class="space-y-4">
		<div>
			<label for="r-name" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">Rol Adı</label>
			<input id="r-name" bind:value={formName} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
			{#if fieldErrors.name}
				<p class="text-red-500 text-xs mt-1">{fieldErrors.name}</p>
			{/if}
		</div>
		<div>
			<label for="r-desc" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">Açıklama</label>
			<input id="r-desc" bind:value={formDesc} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
		</div>

		<!-- Permission Matrix -->
		<div>
			<span class="block text-gray-500 text-xs font-medium mb-2 uppercase tracking-wider">İzinler</span>
			<div class="border border-gray-200 rounded-xl overflow-x-auto">
				<table class="w-full text-sm min-w-[320px]">
					<thead>
						<tr class="bg-gray-50">
							<th class="text-left px-3 md:px-4 py-3 text-gray-500 font-medium">Modül</th>
							<th class="text-center px-3 md:px-4 py-3 text-gray-500 font-medium">Görme</th>
							<th class="text-center px-3 md:px-4 py-3 text-gray-500 font-medium">Kullanma</th>
						</tr>
					</thead>
					<tbody>
						{#each getGroupedModules() as group}
							<!-- Ana modül satırı -->
							<tr class="border-t border-gray-100">
								<td class="px-3 md:px-4 py-2.5 text-gray-700 font-medium">{group.parent.name}</td>
								<td class="text-center px-3 md:px-4 py-2.5">
									<input type="checkbox" checked={formPerms[group.parent.id].view} onchange={(e) => toggleView(group.parent.id, e.currentTarget.checked)} class="accent-teal-600 w-4 h-4 cursor-pointer" />
								</td>
								<td class="text-center px-3 md:px-4 py-2.5">
									<input type="checkbox" checked={formPerms[group.parent.id].use} onchange={(e) => toggleUse(group.parent.id, e.currentTarget.checked)} class="accent-teal-600 w-4 h-4 cursor-pointer" />
								</td>
							</tr>
							<!-- Alt modül satırları -->
							{#each group.children as child}
								<tr class="border-t border-gray-50 bg-gray-50/50">
									<td class="px-3 md:px-4 py-2 text-gray-600 pl-6 md:pl-9 text-sm">
										<span class="text-gray-300 mr-1.5">└</span>{child.name}
									</td>
									<td class="text-center px-3 md:px-4 py-2">
										<input type="checkbox" checked={formPerms[child.id].view} onchange={(e) => toggleView(child.id, e.currentTarget.checked)} class="accent-teal-600 w-4 h-4 cursor-pointer" />
									</td>
									<td class="text-center px-3 md:px-4 py-2">
										<input type="checkbox" checked={formPerms[child.id].use} onchange={(e) => toggleUse(child.id, e.currentTarget.checked)} class="accent-teal-600 w-4 h-4 cursor-pointer" />
									</td>
								</tr>
							{/each}
						{/each}
					</tbody>
				</table>
			</div>
			<p class="text-xs text-gray-400 mt-2">Kullanma izni: ekleme, düzenleme ve silme işlemlerini kapsar.</p>
		</div>
	</div>

	<div class="flex gap-3 mt-6">
		<button onclick={() => showModal = false} class="flex-1 py-2.5 text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer">İptal</button>
		<button onclick={handleSave} disabled={saving} class="flex-1 py-2.5 text-sm text-white bg-teal-600 rounded-lg hover:bg-teal-700 transition-colors cursor-pointer disabled:opacity-50">
			{saving ? 'Kaydediliyor...' : 'Kaydet'}
		</button>
	</div>
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Rol Sil"
	message="{deleteTarget?.name} rolünü silmek istediğinize emin misiniz?"
	confirmText="Sil"
	danger={true}
	onConfirm={handleDelete}
/>
