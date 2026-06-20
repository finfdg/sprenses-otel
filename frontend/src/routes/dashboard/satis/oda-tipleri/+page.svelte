<script lang="ts">
	import { onMount } from 'svelte';
	import {
		BedDouble,
		CheckCircle2,
		Hash,
		PencilLine,
		Plus,
		Target,
		Trash2,
		Users,
	} from 'lucide-svelte';

	import { api, ApiError } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Input from '$lib/components/Input.svelte';
	import ListPage from '$lib/components/ListPage.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { validateRequired } from '$lib/utils/validation';

	// ───── Types ────────────────────────────────────────
	type RoomType = {
		id: number;
		code: string;
		name: string;
		total_rooms: number;
		max_occupancy: number;
		sort_order: number;
		is_active: boolean;
		description: string | null;
		created_at: string;
		updated_at: string;
	};

	type ListResponse = {
		items: RoomType[];
		total_capacity: number;
		active_count: number;
	};

	// ───── Derived ──────────────────────────────────────
	const canView = $derived(hasPermission('sales.room_types', 'view'));
	const canUse = $derived(hasPermission('sales.room_types', 'use'));

	// ───── State ────────────────────────────────────────
	let items = $state<RoomType[]>([]);
	let totalCapacity = $state(0);
	let activeCount = $state(0);
	let loading = $state(true);
	let includeInactive = $state(false);

	let showModal = $state(false);
	let editing = $state<RoomType | null>(null);
	let saving = $state(false);
	let formError = $state('');

	let form = $state({
		code: '',
		name: '',
		total_rooms: 0,
		max_occupancy: 2,
		sort_order: 0,
		is_active: true,
		description: '',
	});
	let fieldErrors = $state<Record<string, string | null>>({});

	let confirmDelete = $state<{ show: boolean; target: RoomType | null }>({
		show: false,
		target: null,
	});

	// Form toplamı — kullanıcıya canlı bilgi: kayıttan sonra toplam ne olacak?
	let projectedTotal = $derived(
		(() => {
			const others = items
				.filter((i) => (!editing || i.id !== editing.id) && i.is_active)
				.reduce((sum, i) => sum + (i.total_rooms || 0), 0);
			const own = form.is_active ? form.total_rooms || 0 : 0;
			return others + own;
		})()
	);

	// ───── Yükleme ──────────────────────────────────────
	async function loadData() {
		loading = true;
		try {
			const data = await api.get<ListResponse>(
				`/sales/room-types/?include_inactive=${includeInactive}`
			);
			items = data.items;
			totalCapacity = data.total_capacity;
			activeCount = data.active_count;
		} catch (err) {
			console.error('Oda tipleri yüklenemedi:', err);
			showToast('Oda tipleri yüklenemedi', 'error');
		}
		loading = false;
	}

	onMount(() => {
		if (canView) {
			loadData();
		}
	});

	// ───── CRUD ─────────────────────────────────────────
	function openCreate() {
		editing = null;
		form = {
			code: '',
			name: '',
			total_rooms: 0,
			max_occupancy: 2,
			sort_order: (items[items.length - 1]?.sort_order ?? 0) + 10,
			is_active: true,
			description: '',
		};
		fieldErrors = {};
		formError = '';
		showModal = true;
	}

	function openEdit(rt: RoomType) {
		editing = rt;
		form = {
			code: rt.code,
			name: rt.name,
			total_rooms: rt.total_rooms,
			max_occupancy: rt.max_occupancy,
			sort_order: rt.sort_order,
			is_active: rt.is_active,
			description: rt.description || '',
		};
		fieldErrors = {};
		formError = '';
		showModal = true;
	}

	function validateForm(): boolean {
		const errors: Record<string, string | null> = {};
		errors.code = validateRequired(form.code, 'Oda tipi kodu');
		errors.name = validateRequired(form.name, 'Oda tipi adı');
		if (form.total_rooms < 0) errors.total_rooms = 'Oda sayısı 0 veya pozitif olmalı';
		if (form.max_occupancy < 1) errors.max_occupancy = 'Maks. kişi 1 veya daha fazla olmalı';
		fieldErrors = errors;
		return !Object.values(errors).some((e) => e !== null);
	}

	async function handleSave() {
		formError = '';
		if (!validateForm()) return;

		saving = true;
		const payload = {
			code: form.code.trim().toUpperCase(),
			name: form.name.trim(),
			total_rooms: form.total_rooms,
			max_occupancy: form.max_occupancy,
			sort_order: form.sort_order,
			is_active: form.is_active,
			description: form.description.trim() || null,
		};

		try {
			if (editing) {
				await api.patch(`/sales/room-types/${editing.id}`, payload);
				showToast('Oda tipi güncellendi', 'success');
			} else {
				await api.post('/sales/room-types/', payload);
				showToast('Oda tipi eklendi', 'success');
			}
			showModal = false;
			await loadData();
		} catch (err: any) {
			if (err instanceof ApiError) {
				formError = err.message;
			} else {
				formError = err?.message || 'Kayıt başarısız';
			}
		}
		saving = false;
	}

	function askDelete(rt: RoomType) {
		confirmDelete = { show: true, target: rt };
	}

	async function handleDelete() {
		if (!confirmDelete.target) return;
		try {
			await api.delete(`/sales/room-types/${confirmDelete.target.id}`);
			showToast('Oda tipi silindi', 'success');
			await loadData();
		} catch (err: any) {
			showToast(err?.message || 'Silinemedi', 'error');
		}
		confirmDelete = { show: false, target: null };
	}

	function toggleIncludeInactive() {
		includeInactive = !includeInactive;
		loadData();
	}
</script>

<svelte:head>
	<title>Sprenses - Oda Tipleri</title>
</svelte:head>

<ListPage
	title="Oda Tipleri"
	description="Otelin fiziksel oda envanteri — doluluk hesabında payda olarak kullanılır"
	{loading}
	isEmpty={items.length === 0}
	emptyIcon={BedDouble}
	emptyTitle="Henüz oda tipi yok"
	emptyMessage="İlk oda tipini ekleyerek başlayın"
	emptyCtaText={canUse ? 'Yeni Tip' : ''}
	onEmptyCta={canUse ? openCreate : null}
	skeletonColumns={6}
	maxWidth="max-w-5xl"
>
	{#snippet actions()}
		<label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
			<input
				type="checkbox"
				checked={includeInactive}
				onchange={toggleIncludeInactive}
				class="w-4 h-4 rounded border-gray-300 accent-teal-700 focus:ring-teal-500"
			/>
			Pasif tipleri göster
		</label>
		{#if canUse}
			<Button onclick={openCreate}><Plus size={16} /> Yeni Tip</Button>
		{/if}
	{/snippet}

	{#snippet stats()}
		<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
			<StatCard
				label="Toplam Oda"
				value={totalCapacity}
				icon={BedDouble}
				accent="teal"
				hint="Aktif tiplerin toplamı"
			/>
			<StatCard
				label="Aktif Tip"
				value={activeCount}
				icon={Hash}
				accent="gray"
				hint="Doluluk hesabına dahil"
			/>
			<StatCard
				label="Hedef"
				value="341"
				icon={Target}
				accent="amber"
				hint={totalCapacity === 341 ? 'Otel toplam oda — uyumlu' : `Otel toplam oda — fark: ${341 - totalCapacity}`}
			/>
		</div>
	{/snippet}

	<!-- Masaüstü: tablo -->
	<div class="hidden sm:block overflow-x-auto">
		<table class="w-full text-sm">
			<thead class="bg-gray-50 border-b border-gray-200">
				<tr>
					<th class="px-4 py-3 text-left font-medium text-gray-600">Kod</th>
					<th class="px-4 py-3 text-left font-medium text-gray-600">Adı</th>
					<th class="px-4 py-3 text-right font-medium text-gray-600">Oda</th>
					<th class="px-4 py-3 text-right font-medium text-gray-600">Maks. Kişi</th>
					<th class="px-4 py-3 text-center font-medium text-gray-600">Durum</th>
					{#if canUse}
						<th class="px-4 py-3 text-right font-medium text-gray-600">İşlemler</th>
					{/if}
				</tr>
			</thead>
			<tbody>
				{#each items as rt (rt.id)}
					<tr class="border-b border-gray-100 hover:bg-gray-50/50 transition-colors">
						<td class="px-4 py-3 font-mono text-xs font-semibold text-gray-700">
							{rt.code}
						</td>
						<td class="px-4 py-3">
							<div class="text-gray-900">{rt.name}</div>
							{#if rt.description}
								<div class="text-xs text-gray-500 mt-0.5">{rt.description}</div>
							{/if}
						</td>
						<td class="px-4 py-3 text-right">
							<span
								class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-teal-50 text-teal-700 text-xs font-medium"
							>
								<Hash class="w-3 h-3" />
								{rt.total_rooms}
							</span>
						</td>
						<td class="px-4 py-3 text-right">
							<span
								class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-50 text-gray-700 text-xs"
							>
								<Users class="w-3 h-3" />
								{rt.max_occupancy}
							</span>
						</td>
						<td class="px-4 py-3 text-center">
							{#if rt.is_active}
								<span
									class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-50 text-green-700 text-xs"
								>
									<CheckCircle2 class="w-3 h-3" />
									Aktif
								</span>
							{:else}
								<span
									class="inline-flex items-center px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 text-xs"
								>
									Pasif
								</span>
							{/if}
						</td>
						{#if canUse}
							<td class="px-4 py-3 text-right">
								<div class="flex items-center justify-end gap-2">
									<button
										onclick={() => openEdit(rt)}
										class="touch-target flex items-center justify-center text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded transition-colors cursor-pointer"
										title="Düzenle"
										aria-label="Düzenle"
									>
										<PencilLine class="w-4 h-4" />
									</button>
									<button
										onclick={() => askDelete(rt)}
										class="touch-target flex items-center justify-center text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors cursor-pointer"
										title="Sil"
										aria-label="Sil"
									>
										<Trash2 class="w-4 h-4" />
									</button>
								</div>
							</td>
						{/if}
					</tr>
				{/each}
			</tbody>
			<tfoot class="bg-gray-50 border-t border-gray-200">
				<tr>
					<td colspan="2" class="px-4 py-3 text-right font-medium text-gray-700">
						Toplam (aktif)
					</td>
					<td class="px-4 py-3 text-right font-bold text-teal-700">
						{items.filter((i) => i.is_active).reduce((s, i) => s + i.total_rooms, 0)}
					</td>
					<td colspan={canUse ? 3 : 2}></td>
				</tr>
			</tfoot>
		</table>
	</div>

	<!-- Mobil: kart görünümü -->
	<div class="sm:hidden space-y-2">
		{#each items as rt (rt.id)}
			<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<div class="text-sm font-medium text-gray-900 truncate">{rt.name}</div>
						<div class="font-mono text-xs font-semibold text-gray-500">{rt.code}</div>
						{#if rt.description}
							<div class="text-xs text-gray-500 mt-0.5 line-clamp-2">{rt.description}</div>
						{/if}
					</div>
					{#if rt.is_active}
						<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-50 text-green-700 text-xs shrink-0">
							<CheckCircle2 class="w-3 h-3" />
							Aktif
						</span>
					{:else}
						<span class="inline-flex items-center px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 text-xs shrink-0">
							Pasif
						</span>
					{/if}
				</div>
				<div class="mt-2 flex items-center justify-between">
					<div class="flex items-center gap-2">
						<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-teal-50 text-teal-700 text-xs font-medium">
							<Hash class="w-3 h-3" />
							{rt.total_rooms} oda
						</span>
						<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-50 text-gray-700 text-xs">
							<Users class="w-3 h-3" />
							{rt.max_occupancy} kişi
						</span>
					</div>
					{#if canUse}
						<div class="flex items-center gap-1">
							<button
								onclick={() => openEdit(rt)}
								class="touch-target flex items-center justify-center text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded transition-colors cursor-pointer"
								title="Düzenle"
								aria-label="Düzenle"
							>
								<PencilLine class="w-4 h-4" />
							</button>
							<button
								onclick={() => askDelete(rt)}
								class="touch-target flex items-center justify-center text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors cursor-pointer"
								title="Sil"
								aria-label="Sil"
							>
								<Trash2 class="w-4 h-4" />
							</button>
						</div>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</ListPage>

<!-- Modal: Oluştur / Düzenle -->
<Modal bind:show={showModal} title={editing ? 'Oda Tipini Düzenle' : 'Yeni Oda Tipi'} maxWidth="max-w-xl">
	<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4">
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="rt-code" class="block text-sm font-medium text-gray-700 mb-1">
					Kod <span class="text-red-600">*</span>
				</label>
				<Input
					id="rt-code"
					type="text"
					size="sm"
					bind:value={form.code}
					invalid={!!fieldErrors.code}
					placeholder="STD KARA"
					class="font-mono uppercase"
				/>
				{#if fieldErrors.code}
					<p class="text-xs text-red-600 mt-1">{fieldErrors.code}</p>
				{:else}
					<p class="text-xs text-gray-500 mt-1">Excel'deki Type sütunuyla aynı yazılmalı</p>
				{/if}
			</div>
			<div>
				<label for="rt-name" class="block text-sm font-medium text-gray-700 mb-1">
					Adı <span class="text-red-600">*</span>
				</label>
				<Input
					id="rt-name"
					type="text"
					size="sm"
					bind:value={form.name}
					invalid={!!fieldErrors.name}
					placeholder="Standart Kara Manzaralı"
				/>
				{#if fieldErrors.name}
					<p class="text-xs text-red-600 mt-1">{fieldErrors.name}</p>
				{/if}
			</div>
		</div>

		<div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
			<div>
				<label for="rt-total" class="block text-sm font-medium text-gray-700 mb-1">
					Oda Sayısı <span class="text-red-600">*</span>
				</label>
				<Input
					id="rt-total"
					type="number"
					size="sm"
					bind:value={form.total_rooms}
					invalid={!!fieldErrors.total_rooms}
					min="0"
				/>
				{#if fieldErrors.total_rooms}
					<p class="text-xs text-red-600 mt-1">{fieldErrors.total_rooms}</p>
				{/if}
			</div>
			<div>
				<label for="rt-max" class="block text-sm font-medium text-gray-700 mb-1">
					Maks. Kişi
				</label>
				<Input
					id="rt-max"
					type="number"
					size="sm"
					bind:value={form.max_occupancy}
					invalid={!!fieldErrors.max_occupancy}
					min="1"
					max="20"
				/>
				{#if fieldErrors.max_occupancy}
					<p class="text-xs text-red-600 mt-1">{fieldErrors.max_occupancy}</p>
				{/if}
			</div>
			<div>
				<label for="rt-sort" class="block text-sm font-medium text-gray-700 mb-1">
					Sıra
				</label>
				<Input
					id="rt-sort"
					type="number"
					size="sm"
					bind:value={form.sort_order}
					min="0"
				/>
			</div>
		</div>

		<div>
			<label for="rt-desc" class="block text-sm font-medium text-gray-700 mb-1">
				Açıklama
			</label>
			<Textarea
				id="rt-desc"
				bind:value={form.description}
				rows={2}
				placeholder="Notlar veya özellikler"
			/>
		</div>

		<div class="flex items-center gap-3">
			<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
				<input
					type="checkbox"
					bind:checked={form.is_active}
					class="w-4 h-4 rounded border-gray-300 accent-teal-700 focus:ring-teal-500"
				/>
				Aktif (doluluk hesabına dahil)
			</label>
		</div>

		<!-- Projected total banner -->
		<div
			class="px-3 py-2 rounded-lg text-sm flex items-center justify-between {projectedTotal === 341 ? 'bg-green-50 text-green-700' : projectedTotal > 341 ? 'bg-amber-50 text-amber-700' : 'bg-gray-50 text-gray-600'}"
		>
			<span>Kaydetme sonrası toplam:</span>
			<span class="font-bold inline-flex items-center gap-1">
				{projectedTotal} / 341
				{#if projectedTotal === 341}
					<CheckCircle2 class="w-4 h-4" />
				{:else if projectedTotal > 341}
					(+{projectedTotal - 341})
				{:else}
					(-{341 - projectedTotal})
				{/if}
			</span>
		</div>

		{#if formError}
			<div class="px-3 py-2 bg-red-50 text-red-700 text-sm rounded-lg border border-red-200">
				{formError}
			</div>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button type="button" variant="secondary" onclick={() => (showModal = false)}>İptal</Button>
			<Button type="submit" loading={saving}>{editing ? 'Güncelle' : 'Kaydet'}</Button>
		</div>
	</form>
</Modal>

<ConfirmDialog
	bind:show={confirmDelete.show}
	title="Oda Tipini Sil"
	message={confirmDelete.target
		? `${confirmDelete.target.name} (${confirmDelete.target.code}) silinecek. Bu tipe bağlı rezervasyon varsa silme engellenir, bunun yerine 'Pasif' yapabilirsiniz.`
		: ''}
	confirmText="Sil"
	danger
	onCancel={() => (confirmDelete = { show: false, target: null })}
	onConfirm={handleDelete}
/>
