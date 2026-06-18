<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import TemplateBuilder from '$lib/components/quality/TemplateBuilder.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import { ClipboardList, Plus, Pencil, Trash2 } from 'lucide-svelte';

	interface TemplateItem {
		id: number;
		name: string;
		description: string | null;
		frequency: string;
		is_active: boolean;
		section_count: number;
		field_count: number;
		created_at: string;
	}

	const canUse = hasPermission('quality.templates', 'use');

	let templates = $state<TemplateItem[]>([]);
	let loading = $state(true);
	let showModal = $state(false);

	// Pagination
	let currentPage = $state(1);
	let totalItems = $state(0);
	let totalPages = $state(1);
	let pageSize = $state(25);
	let editingId = $state<number | null>(null);

	// Form alanları
	let formName = $state('');
	let formDescription = $state('');
	let formFrequency = $state('daily');
	let formIsActive = $state(true);
	let formFooterText = $state('');
	let formSections = $state<any[]>([]);
	let formAssignees = $state<any[]>([]);
	let saving = $state(false);
	let formError = $state('');

	// Kullanıcı ve rol listesi (atamalar için)
	let users = $state<any[]>([]);
	let roles = $state<any[]>([]);

	// Eşik değerleri
	let formIncreaseThreshold = $state(10);
	let formDecreaseThreshold = $state(10);

	// Logo
	let formLogoUrl = $state<string | null>(null);
	let uploadingLogo = $state(false);

	// Silme onayı
	let showDeleteConfirm = $state(false);
	let deleteTargetId = $state<number | null>(null);
	let deleteTargetName = $state('');

	const frequencyLabels: Record<string, string> = {
		daily: 'Günlük',
		weekly: 'Haftalık',
		monthly: 'Aylık',
	};

	onMount(async () => {
		await loadData();
	});

	function goToPage(p: number) {
		if (p < 1 || p > totalPages) return;
		currentPage = p;
		loadData();
	}

	function changePageSize(s: number) {
		pageSize = s;
		currentPage = 1;
		loadData();
	}

	async function loadData() {
		loading = true;
		try {
			const tRes = await api.get<any>(`/quality/templates/?page=${currentPage}&page_size=${pageSize}`);
			templates = tRes.items ?? tRes;
			totalItems = tRes.total ?? templates.length;
			totalPages = tRes.pages ?? 1;
		} catch (err) {
			console.error('Şablonlar yüklenemedi:', err);
			showToast('Şablonlar yüklenemedi', 'error');
		}

		// Kullanıcı ve rol listesi (atamalar için) — izin yoksa sessizce atla
		try {
			const uRes = await api.get<any>('/system/users/?page=1&page_size=200');
			users = (uRes.items ?? uRes).map((u: any) => ({
				id: u.id,
				first_name: u.first_name,
				last_name: u.last_name,
			}));
		} catch (err) {
			console.error('Kullanıcı listesi yüklenemedi:', err);
			users = [];
		}

		try {
			const rRes = await api.get<any>('/system/roles/');
			roles = (Array.isArray(rRes) ? rRes : rRes.items ?? []).map((r: any) => ({
				id: r.id,
				name: r.name,
			}));
		} catch (err) {
			console.error('Rol listesi yüklenemedi:', err);
			roles = [];
		}

		loading = false;
	}

	function openCreate() {
		editingId = null;
		formName = '';
		formDescription = '';
		formFrequency = 'daily';
		formIsActive = true;
		formFooterText = '';
		formIncreaseThreshold = 10;
		formDecreaseThreshold = 10;
		formLogoUrl = null;
		formSections = [];
		formAssignees = [];
		formError = '';
		showModal = true;
	}

	async function openEdit(t: TemplateItem) {
		try {
			const detail = await api.get<any>(`/quality/templates/${t.id}`);
			editingId = t.id;
			formName = detail.name;
			formDescription = detail.description || '';
			formFrequency = detail.frequency;
			formIsActive = detail.is_active;
			formFooterText = detail.footer_text || '';
			formIncreaseThreshold = detail.increase_threshold ?? 10;
			formDecreaseThreshold = detail.decrease_threshold ?? 10;
			formSections = (detail.sections || []).map((s: any) => ({
				name: s.name,
				sort_order: s.sort_order,
				fields: (s.fields || []).map((f: any) => ({
					label: f.label,
					field_type: f.field_type,
					unit: f.unit || '',
					is_required: f.is_required,
					is_resource: f.is_resource,
					is_guest_count: f.is_guest_count,
					is_month_end_only: f.is_month_end_only || false,
					options: f.options || '',
					sort_order: f.sort_order,
				})),
			}));
			formAssignees = (detail.assignees || []).map((a: any) => ({
				assignment_type: a.assignment_type,
				user_id: a.user_id,
				role_id: a.role_id,
			}));
			formLogoUrl = detail.logo_url || null;
			formError = '';
			showModal = true;
		} catch (err) {
			console.error('Şablon detayı yüklenemedi:', err);
			showToast('Şablon detayı yüklenemedi', 'error');
		}
	}

	async function handleSave() {
		if (!formName.trim()) {
			formError = 'Şablon adı zorunludur';
			return;
		}

		// Bölüm isimlerini kontrol et
		for (const sec of formSections) {
			if (!sec.name.trim()) {
				formError = 'Tüm bölümlerin adı doldurulmalıdır';
				return;
			}
			for (const field of sec.fields) {
				if (!field.label.trim()) {
					formError = 'Tüm alanların etiketi doldurulmalıdır';
					return;
				}
			}
		}

		saving = true;
		formError = '';

		const payload = {
			name: formName.trim(),
			description: formDescription.trim() || null,
			frequency: formFrequency,
			is_active: formIsActive,
			footer_text: formFooterText.trim() || null,
			increase_threshold: formIncreaseThreshold,
			decrease_threshold: formDecreaseThreshold,
			sections: formSections.map((s, si) => ({
				name: s.name.trim(),
				sort_order: si,
				fields: s.fields.map((f: any, fi: number) => ({
					label: f.label.trim(),
					field_type: f.field_type,
					unit: f.unit?.trim() || null,
					is_required: f.is_required,
					is_resource: f.is_resource,
					is_guest_count: f.is_guest_count,
					is_month_end_only: f.is_month_end_only || false,
					options: f.options?.trim() || null,
					sort_order: fi,
				})),
			})),
			assignees: formAssignees.filter(a => a.user_id || a.role_id),
		};

		try {
			if (editingId) {
				await api.patch(`/quality/templates/${editingId}`, payload);
				showToast('Şablon güncellendi', 'success');
			} else {
				await api.post('/quality/templates/', payload);
				showToast('Şablon oluşturuldu', 'success');
			}
			showModal = false;
			await loadData();
		} catch (err: any) {
			formError = err.message || 'Bir hata oluştu';
			console.error('Kayıt hatası:', err);
		}
		saving = false;
	}

	async function handleLogoUpload(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file || !editingId) return;

		// Boyut kontrolü (2 MB)
		if (file.size > 2 * 1024 * 1024) {
			showToast('Logo dosyası 2 MB\'dan küçük olmalıdır', 'error');
			return;
		}

		// Uzantı kontrolü
		const ext = file.name.split('.').pop()?.toLowerCase();
		if (!['png', 'jpg', 'jpeg', 'svg', 'webp'].includes(ext || '')) {
			showToast('Desteklenmeyen dosya formatı. PNG, JPG, SVG veya WEBP yükleyin.', 'error');
			return;
		}

		uploadingLogo = true;
		try {
			const fd = new FormData();
			fd.append('file', file);
			const res = await api.upload<any>(`/quality/templates/${editingId}/logo`, fd);
			formLogoUrl = res.logo_url;
			showToast('Logo yüklendi', 'success');
		} catch (err: any) {
			console.error('Logo yükleme hatası:', err);
			showToast(err.message || 'Logo yüklenemedi', 'error');
		}
		uploadingLogo = false;
		// Input'u temizle (aynı dosyayı tekrar seçebilmek için)
		input.value = '';
	}

	async function handleLogoDelete() {
		if (!editingId) return;
		uploadingLogo = true;
		try {
			await api.delete(`/quality/templates/${editingId}/logo`);
			formLogoUrl = null;
			showToast('Logo silindi', 'success');
		} catch (err: any) {
			console.error('Logo silme hatası:', err);
			showToast(err.message || 'Logo silinemedi', 'error');
		}
		uploadingLogo = false;
	}

	function confirmDelete(t: TemplateItem) {
		deleteTargetId = t.id;
		deleteTargetName = t.name;
		showDeleteConfirm = true;
	}

	async function handleDelete() {
		if (!deleteTargetId) return;
		try {
			await api.delete(`/quality/templates/${deleteTargetId}`);
			showToast('Şablon silindi', 'success');
			showDeleteConfirm = false;
			await loadData();
		} catch (err: any) {
			showToast(err.message || 'Silinemedi', 'error');
			console.error('Silme hatası:', err);
		}
	}
</script>

<div class="max-w-6xl mx-auto">
	<!-- Başlık -->
	<div class="mb-6">
		<PageHeader title="Kalite Şablonları" description="Denetim ve kontrol formu şablonları">
			{#snippet actions()}
				{#if canUse}
					<Button onclick={openCreate}><Plus size={16} /> Yeni Şablon</Button>
				{/if}
			{/snippet}
		</PageHeader>
	</div>

	<!-- İçerik -->
	{#if loading}
		<TableSkeleton rows={4} columns={3} showHeader={false} />
	{:else if templates.length === 0}
		<EmptyState icon={ClipboardList} title="Henüz şablon oluşturulmadı" />
	{:else}
		<div class="grid gap-3 sm:gap-4">
			{#each templates as t (t.id)}
				<div class="bg-white border border-gray-200 rounded-xl p-4 sm:p-5 hover:shadow-sm transition-shadow">
					<div class="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
						<div class="flex-1 min-w-0">
							<div class="flex flex-wrap items-center gap-2">
								<h3 class="font-semibold text-gray-900">{t.name}</h3>
								<span class="text-xs px-2 py-0.5 rounded-full border shrink-0 {
									t.frequency === 'daily' ? 'bg-blue-50 text-blue-600 border-blue-200' :
									t.frequency === 'weekly' ? 'bg-purple-50 text-purple-600 border-purple-200' :
									'bg-amber-50 text-amber-600 border-amber-200'
								}">
									{frequencyLabels[t.frequency] || t.frequency}
								</span>
								{#if !t.is_active}
									<span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 border border-gray-200 shrink-0">Pasif</span>
								{/if}
							</div>
							{#if t.description}
								<p class="text-sm text-gray-500 mt-1">{t.description}</p>
							{/if}
							<div class="flex items-center gap-4 mt-2 text-xs text-gray-500">
								<span>{t.section_count} bölüm</span>
								<span>{t.field_count} alan</span>
								<span>{new Date(t.created_at).toLocaleDateString('tr-TR')}</span>
							</div>
						</div>

						{#if canUse}
							<div class="flex gap-2 shrink-0">
								<Button variant="secondary" size="sm" onclick={() => openEdit(t)}><Pencil size={14} /> Düzenle</Button>
								<Button variant="danger" size="sm" onclick={() => confirmDelete(t)}><Trash2 size={14} /> Sil</Button>
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>

		<!-- Sayfalama -->
		{#if totalItems > pageSize || currentPage > 1}
			<div class="mt-4 bg-white border border-gray-200 rounded-xl px-4">
				<Pagination page={currentPage} {pageSize} total={totalItems} onPageChange={goToPage} onPageSizeChange={changePageSize} />
			</div>
		{/if}
	{/if}
</div>

<!-- Oluştur/Düzenle Modalı -->
<Modal bind:show={showModal} title={editingId ? 'Şablonu Düzenle' : 'Yeni Şablon'} maxWidth="max-w-4xl">
	<div class="space-y-4">
		{#if formError}
			<div class="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{formError}</div>
		{/if}

		<!-- Temel bilgiler -->
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="qt-name" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">Şablon Adı *</label>
				<Input
					id="qt-name"
					bind:value={formName}
					placeholder="Örn: Teknik Servis Günlük Kontrol Çizelgesi"
				/>
			</div>
			<div class="flex gap-4">
				<div class="flex-1">
					<label for="qt-freq" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">Sıklık</label>
					<Select
						id="qt-freq"
						bind:value={formFrequency}
					>
						<option value="daily">Günlük</option>
						<option value="weekly">Haftalık</option>
						<option value="monthly">Aylık</option>
					</Select>
				</div>
				<div class="flex items-end pb-1">
					<label class="flex items-center gap-2 cursor-pointer">
						<input type="checkbox" bind:checked={formIsActive} class="accent-teal-700 w-4 h-4" />
						<span class="text-sm text-gray-700">Aktif</span>
					</label>
				</div>
			</div>
		</div>

		<div>
			<label for="qt-desc" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">Açıklama</label>
			<Textarea
				id="qt-desc"
				bind:value={formDescription}
				placeholder="Şablon açıklaması..."
				rows={2}
			/>
		</div>

		<div>
			<label for="qt-footer" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">PDF Altbilgi</label>
			<Input
				id="qt-footer"
				bind:value={formFooterText}
				placeholder="PDF raporunun her sayfasında görünecek altbilgi metni..."
			/>
			<p class="text-xs text-gray-500 mt-0.5">Bu metin PDF çıktısının her sayfasının alt kısmında görünür</p>
		</div>

		<!-- Eşik Değerleri -->
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="qt-inc" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">Artış Uyarı Eşiği (%)</label>
				<Input
					id="qt-inc"
					type="number"
					step="1"
					min="0"
					max="100"
					bind:value={formIncreaseThreshold}
				/>
				<p class="text-xs text-gray-500 mt-0.5">Bu yüzdeyi aşan artışlar kırmızı uyarı olarak gösterilir</p>
			</div>
			<div>
				<label for="qt-dec" class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">Azalış Uyarı Eşiği (%)</label>
				<Input
					id="qt-dec"
					type="number"
					step="1"
					min="0"
					max="100"
					bind:value={formDecreaseThreshold}
				/>
				<p class="text-xs text-gray-500 mt-0.5">Bu yüzdeyi aşan azalışlar yeşil uyarı olarak gösterilir</p>
			</div>
		</div>

		<!-- Logo -->
		<div>
			<span class="block text-gray-500 text-xs font-medium mb-1 uppercase tracking-wider">PDF Logosu</span>
			<div class="flex items-center gap-4">
				{#if formLogoUrl}
					<div class="flex items-center gap-3 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
						<img src="{formLogoUrl}" alt="Logo" class="h-8 max-w-[160px] object-contain" />
						<button
							onclick={handleLogoDelete}
							disabled={uploadingLogo}
							class="text-xs text-red-600 hover:text-red-700 transition-colors cursor-pointer disabled:opacity-50"
							title="Logoyu sil"
						>
							✕
						</button>
					</div>
				{/if}
				{#if editingId}
					<label class="flex items-center gap-1.5 text-sm text-teal-600 hover:text-teal-700 cursor-pointer transition-colors {uploadingLogo ? 'opacity-50 pointer-events-none' : ''}">
						{#if uploadingLogo}
							<span class="w-4 h-4 border-2 border-teal-200 border-t-teal-600 rounded-full animate-spin"></span>
							Yükleniyor...
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
							</svg>
							{formLogoUrl ? 'Değiştir' : 'Logo Yükle'}
						{/if}
						<input
							type="file"
							accept=".png,.jpg,.jpeg,.svg,.webp"
							onchange={handleLogoUpload}
							class="hidden"
							disabled={uploadingLogo}
						/>
					</label>
				{:else}
					<p class="text-xs text-gray-500">Logo yüklemek için önce şablonu oluşturun</p>
				{/if}
			</div>
			<p class="text-xs text-gray-500 mt-0.5">PDF çıktısının her sayfasının sol üst köşesinde görünür (maks. 2 MB, PNG/JPG/SVG/WEBP)</p>
		</div>

		<!-- Bölüm ve alan oluşturucu -->
		<TemplateBuilder
			bind:sections={formSections}
			bind:assignees={formAssignees}
			{users}
			{roles}
		/>

		<!-- Kaydet butonu -->
		<div class="flex flex-col-reverse sm:flex-row justify-end gap-2 sm:gap-3 pt-3 border-t border-gray-100">
			<Button variant="secondary" onclick={() => showModal = false}>İptal</Button>
			<Button onclick={handleSave} loading={saving}>{editingId ? 'Güncelle' : 'Oluştur'}</Button>
		</div>
	</div>
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Şablonu Sil"
	message="{deleteTargetName} şablonunu silmek istediğinize emin misiniz?"
	confirmText="Sil"
	danger={true}
	onConfirm={handleDelete}
/>
