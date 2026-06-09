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
	import { validateRequired, validateModuleCode } from '$lib/utils/validation';
	import { Plus, Pencil, Trash2, LayoutGrid } from 'lucide-svelte';
	import { showToast } from '$lib/stores/toast.svelte';

	const canUse = hasPermission('system.modules', 'use');

	interface ModuleItem {
		id: number;
		name: string;
		code: string;
		description: string | null;
		icon: string | null;
		parent_id: number | null;
		sort_order: number;
		is_active: boolean;
		children: ModuleItem[];
	}

	let modules = $state<ModuleItem[]>([]);
	let flatModules = $state<ModuleItem[]>([]);
	let loading = $state(true);
	let showModal = $state(false);
	let editingModule = $state<ModuleItem | null>(null);
	let showDeleteConfirm = $state(false);
	let deleteTarget = $state<ModuleItem | null>(null);

	let formName = $state('');
	let formCode = $state('');
	let formDesc = $state('');
	let formIcon = $state('');
	let formParentId = $state<number | null>(null);
	let formSortOrder = $state(0);
	let formActive = $state(true);
	let formError = $state('');
	let saving = $state(false);

	let fieldErrors = $state<Record<string, string | null>>({});

	onMount(async () => {
		await loadData();
	});

	async function loadData() {
		loading = true;
		try {
			const [tree, flat] = await Promise.all([
				api.get<ModuleItem[]>('/system/modules/tree'),
				api.get<ModuleItem[]>('/system/modules/'),
			]);
			modules = tree;
			flatModules = flat;
		} catch (err) { console.error('Modül verileri yüklenemedi:', err); }
		loading = false;
	}

	function openCreate() {
		editingModule = null;
		formName = '';
		formCode = '';
		formDesc = '';
		formIcon = '';
		formParentId = null;
		formSortOrder = 0;
		formActive = true;
		formError = '';
		fieldErrors = {};
		showModal = true;
	}

	function openEdit(m: ModuleItem) {
		editingModule = m;
		formName = m.name;
		formCode = m.code;
		formDesc = m.description || '';
		formIcon = m.icon || '';
		formParentId = m.parent_id;
		formSortOrder = m.sort_order;
		formActive = m.is_active;
		formError = '';
		fieldErrors = {};
		showModal = true;
	}

	function validateForm(): boolean {
		const errors: Record<string, string | null> = {};

		errors.name = validateRequired(formName, 'Modül adı');
		errors.code = validateModuleCode(formCode);

		fieldErrors = errors;

		return !Object.values(errors).some(e => e !== null);
	}

	async function handleSave() {
		formError = '';

		if (!validateForm()) return;

		saving = true;
		const data: any = {
			name: formName,
			code: formCode,
			description: formDesc || null,
			icon: formIcon || null,
			parent_id: formParentId,
			sort_order: formSortOrder,
			is_active: formActive,
		};

		try {
			if (editingModule) {
				await api.patch(`/system/modules/${editingModule.id}`, data);
			} else {
				await api.post('/system/modules/', data);
			}
			showModal = false;
			await loadData();
		} catch (err: any) {
			formError = err.message || 'Hata oluştu';
		}
		saving = false;
	}

	function askDelete(m: ModuleItem) {
		deleteTarget = m;
		showDeleteConfirm = true;
	}

	async function handleDelete() {
		if (!deleteTarget) return;
		try {
			await api.delete(`/system/modules/${deleteTarget.id}`);
			await loadData();
		} catch (err: any) {
			showToast(err.message || 'Silinemedi', 'error');
		}
	}

	// Parent modules for dropdown (only top-level)
	function getParentOptions() {
		return flatModules.filter(m => !m.parent_id);
	}
</script>

<svelte:head><title>Sprenses - Modüller</title></svelte:head>

<div class="max-w-4xl mx-auto">
	<div class="mb-6">
		<PageHeader title="Modüller" description="Sistem modülleri ve menü hiyerarşisi">
			{#snippet actions()}
				{#if canUse}
					<Button onclick={openCreate}><Plus size={16} /> Yeni Modül</Button>
				{/if}
			{/snippet}
		</PageHeader>
	</div>

	{#if loading}
		<TableSkeleton rows={4} columns={3} />
	{:else if modules.length === 0}
		<EmptyState
			icon={LayoutGrid}
			title="Henüz modül yok"
			description={canUse ? "İlk modülü eklemek için 'Yeni Modül' butonunu kullanın." : 'Görüntülenecek modül bulunmuyor.'}
			ctaText={canUse ? 'Yeni Modül' : ''}
			onCta={canUse ? openCreate : null}
		/>
	{:else}
		<div class="grid gap-3">
			{#each modules as m}
				<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
					<div class="p-4 md:p-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
						<div class="min-w-0">
							<span class="font-semibold text-gray-900">{m.name}</span>
							<span class="text-gray-500 ml-2 text-xs font-mono">{m.code}</span>
							{#if m.description}
								<div class="text-gray-500 text-sm mt-0.5">{m.description}</div>
							{/if}
						</div>
						<div class="flex items-center gap-2 shrink-0">
							{#if !m.is_active}
								<span class="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200">Pasif</span>
							{/if}
							{#if canUse}
								<Button variant="secondary" size="sm" onclick={() => openEdit(m)}><Pencil size={14} /> Düzenle</Button>
								<Button variant="danger" size="sm" onclick={() => askDelete(m)}><Trash2 size={14} /> Sil</Button>
							{/if}
						</div>
					</div>

					{#if m.children && m.children.length > 0}
						<div class="border-t border-gray-100">
							{#each m.children as child}
								<div class="px-4 md:px-5 py-3 pl-6 md:pl-10 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-gray-50 last:border-b-0 bg-gray-50/50">
									<div class="min-w-0">
										<span class="text-gray-500 mr-1.5">└</span>
										<span class="text-sm text-gray-700">{child.name}</span>
										<span class="text-gray-500 ml-2 text-xs font-mono">{child.code}</span>
									</div>
									<div class="flex items-center gap-2 shrink-0">
										{#if !child.is_active}
											<span class="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200">Pasif</span>
										{/if}
										{#if canUse}
											<Button variant="secondary" size="sm" onclick={() => openEdit(child)}><Pencil size={14} /> Düzenle</Button>
											<Button variant="danger" size="sm" onclick={() => askDelete(child)}><Trash2 size={14} /> Sil</Button>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Modal -->
<Modal bind:show={showModal} title={editingModule ? 'Modül Düzenle' : 'Yeni Modül'} maxWidth="max-w-md">
	{#if formError}
		<div class="bg-red-50 border border-red-200 text-red-600 px-3 py-2 rounded-lg text-sm mb-4">{formError}</div>
	{/if}

	<div class="space-y-4">
		<div>
			<label for="m-name" class="block text-sm font-medium text-gray-700 mb-1">Modül Adı <span class="text-red-600">*</span></label>
			<input id="m-name" bind:value={formName} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
			{#if fieldErrors.name}
				<p class="text-red-600 text-xs mt-1">{fieldErrors.name}</p>
			{/if}
		</div>
		<div>
			<label for="m-code" class="block text-sm font-medium text-gray-700 mb-1">Kod <span class="text-red-600">*</span></label>
			<input id="m-code" bind:value={formCode} placeholder="system.newmodule" class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm font-mono outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
			{#if fieldErrors.code}
				<p class="text-red-600 text-xs mt-1">{fieldErrors.code}</p>
			{/if}
		</div>
		<div>
			<label for="m-desc" class="block text-sm font-medium text-gray-700 mb-1">Açıklama</label>
			<input id="m-desc" bind:value={formDesc} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="m-parent" class="block text-sm font-medium text-gray-700 mb-1">Üst Modül</label>
				<select id="m-parent" bind:value={formParentId} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all">
					<option value={null}>Yok (Ana modül)</option>
					{#each getParentOptions() as p}
						<option value={p.id}>{p.name}</option>
					{/each}
				</select>
			</div>
			<div>
				<label for="m-sort" class="block text-sm font-medium text-gray-700 mb-1">Sıra</label>
				<input id="m-sort" type="number" bind:value={formSortOrder} class="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all" />
			</div>
		</div>
		<div class="flex items-center gap-2">
			<input type="checkbox" id="modActive" bind:checked={formActive} class="accent-teal-700 w-4 h-4" />
			<label for="modActive" class="text-sm text-gray-600">Aktif</label>
		</div>
	</div>

	<div class="flex justify-end gap-2 mt-6">
		<Button variant="secondary" onclick={() => showModal = false}>İptal</Button>
		<Button onclick={handleSave} loading={saving}>{editingModule ? 'Güncelle' : 'Kaydet'}</Button>
	</div>
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Modül Sil"
	message="{deleteTarget?.name} modülünü silmek istediğinize emin misiniz?"
	confirmText="Sil"
	danger={true}
	onConfirm={handleDelete}
/>
