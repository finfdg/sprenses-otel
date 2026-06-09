<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { validateRequired } from '$lib/utils/validation';
	import { showToast } from '$lib/stores/toast.svelte';
	import { Plus, Pencil, Trash2, Shield } from 'lucide-svelte';

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

	// ── Toplu izin işlemleri ───────────────────────────────
	// Tüm modülleri topluca ayarla (Tümünü seç / Sadece görme / Temizle)
	function setAllPerms(view: boolean, use: boolean) {
		for (const m of modules) {
			formPerms[m.id] = { view, use };
		}
	}

	type Group = { parent: ModuleItem; children: ModuleItem[] };

	// Grubun (ana modül + alt modüller) toplu durumu: hiç / kısmi / tümü
	function groupState(group: Group, key: 'view' | 'use'): 'none' | 'some' | 'all' {
		const all = [group.parent, ...group.children];
		const on = all.filter(m => formPerms[m.id]?.[key]).length;
		return on === 0 ? 'none' : on === all.length ? 'all' : 'some';
	}

	// Grup görme'yi topluca aç/kapat (alt modüllere yayılır)
	function toggleGroupView(group: Group, checked: boolean) {
		for (const m of [group.parent, ...group.children]) {
			formPerms[m.id].view = checked;
			if (!checked) formPerms[m.id].use = false;
		}
	}

	// Grup kullanma'yı topluca aç/kapat (kullanma → görme'yi de açar)
	function toggleGroupUse(group: Group, checked: boolean) {
		for (const m of [group.parent, ...group.children]) {
			formPerms[m.id].use = checked;
			if (checked) formPerms[m.id].view = true;
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
	<div class="mb-6">
		<PageHeader title="Roller" description="Sistem rolleri ve modül izin matrisi">
			{#snippet actions()}
				{#if canUse}
					<Button onclick={openCreate}><Plus size={16} /> Yeni Rol</Button>
				{/if}
			{/snippet}
		</PageHeader>
	</div>

	{#if loading}
		<TableSkeleton rows={4} columns={3} />
	{:else if roles.length === 0}
		<EmptyState
			icon={Shield}
			title="Henüz rol yok"
			description={canUse ? "İlk rolü eklemek için 'Yeni Rol' butonunu kullanın." : 'Görüntülenecek rol bulunmuyor.'}
			ctaText={canUse ? 'Yeni Rol' : ''}
			onCta={canUse ? openCreate : null}
		/>
	{:else}
		<div class="grid gap-3">
			{#each roles as r}
				<div class="bg-white border border-gray-200 rounded-xl p-4 md:p-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between shadow-sm">
					<div class="min-w-0">
						<span class="font-semibold text-gray-900">{r.name}</span>
						{#if r.description}
							<span class="text-gray-500 ml-2 text-sm">{r.description}</span>
						{/if}
						<div class="text-xs text-gray-500 mt-1">{r.permissions.filter(p => p.can_view).length} modül erişimi</div>
					</div>
					{#if canUse}
					<div class="flex items-center gap-2 shrink-0">
						<Button variant="secondary" size="sm" onclick={() => openEdit(r)}><Pencil size={14} /> Düzenle</Button>
						<Button variant="danger" size="sm" onclick={() => askDelete(r)}><Trash2 size={14} /> Sil</Button>
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
			<label for="r-name" class="block text-sm font-medium text-gray-700 mb-1">Rol Adı <span class="text-red-600">*</span></label>
			<input id="r-name" bind:value={formName} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
			{#if fieldErrors.name}
				<p class="text-red-600 text-xs mt-1">{fieldErrors.name}</p>
			{/if}
		</div>
		<div>
			<label for="r-desc" class="block text-sm font-medium text-gray-700 mb-1">Açıklama</label>
			<input id="r-desc" bind:value={formDesc} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
		</div>

		<!-- Permission Matrix -->
		<div>
			<div class="flex items-center justify-between mb-2 gap-2 flex-wrap">
				<span class="block text-sm font-medium text-gray-700">İzinler</span>
				<div class="flex gap-1.5 shrink-0">
					<Button variant="ghost" size="sm" onclick={() => setAllPerms(true, true)}>Tümünü seç</Button>
					<Button variant="ghost" size="sm" onclick={() => setAllPerms(true, false)}>Sadece görme</Button>
					<Button variant="ghost" size="sm" onclick={() => setAllPerms(false, false)}>Temizle</Button>
				</div>
			</div>
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
								<td class="px-3 md:px-4 py-2.5 text-gray-700 font-medium">
									{group.parent.name}
									{#if group.children.length}
										<span class="text-gray-400 font-normal text-xs ml-1">(grup)</span>
									{/if}
								</td>
								<td class="text-center px-3 md:px-4 py-2.5">
									<input type="checkbox" checked={groupState(group, 'view') === 'all'} indeterminate={groupState(group, 'view') === 'some'} onchange={(e) => toggleGroupView(group, e.currentTarget.checked)} class="accent-teal-700 w-4 h-4 cursor-pointer" />
								</td>
								<td class="text-center px-3 md:px-4 py-2.5">
									<input type="checkbox" checked={groupState(group, 'use') === 'all'} indeterminate={groupState(group, 'use') === 'some'} onchange={(e) => toggleGroupUse(group, e.currentTarget.checked)} class="accent-teal-700 w-4 h-4 cursor-pointer" />
								</td>
							</tr>
							<!-- Alt modül satırları -->
							{#each group.children as child}
								<tr class="border-t border-gray-50 bg-gray-50/50">
									<td class="px-3 md:px-4 py-2 text-gray-600 pl-6 md:pl-9 text-sm">
										<span class="text-gray-500 mr-1.5">└</span>{child.name}
									</td>
									<td class="text-center px-3 md:px-4 py-2">
										<input type="checkbox" checked={formPerms[child.id].view} onchange={(e) => toggleView(child.id, e.currentTarget.checked)} class="accent-teal-700 w-4 h-4 cursor-pointer" />
									</td>
									<td class="text-center px-3 md:px-4 py-2">
										<input type="checkbox" checked={formPerms[child.id].use} onchange={(e) => toggleUse(child.id, e.currentTarget.checked)} class="accent-teal-700 w-4 h-4 cursor-pointer" />
									</td>
								</tr>
							{/each}
						{/each}
					</tbody>
				</table>
			</div>
			<p class="text-xs text-gray-500 mt-2">Kullanma izni: ekleme, düzenleme ve silme işlemlerini kapsar.</p>
		</div>
	</div>

	<div class="flex justify-end gap-2 mt-6">
		<Button variant="secondary" onclick={() => showModal = false}>İptal</Button>
		<Button onclick={handleSave} loading={saving}>{editingRole ? 'Güncelle' : 'Kaydet'}</Button>
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
