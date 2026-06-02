<script lang="ts">
	import { onMount } from 'svelte';
	import {
		BedDouble,
		CheckCircle2,
		Hash,
		PencilLine,
		Plus,
		Trash2,
		Users,
	} from 'lucide-svelte';

	import { api, ApiError } from '$lib/api';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Modal from '$lib/components/Modal.svelte';
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

<div class="max-w-5xl mx-auto p-4 sm:p-6 space-y-6">
	<!-- Header -->
	<div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
		<div>
			<h1 class="text-2xl font-bold text-gray-900 flex items-center gap-2">
				<BedDouble class="w-7 h-7 text-teal-600" />
				Oda Tipleri
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				Otelin fiziksel oda envanteri — doluluk hesabında payda olarak kullanılır
			</p>
		</div>
		<div class="flex items-center gap-2">
			<label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
				<input
					type="checkbox"
					checked={includeInactive}
					onchange={toggleIncludeInactive}
					class="w-4 h-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
				/>
				Pasif tipleri göster
			</label>
			{#if canUse}
				<button
					onclick={openCreate}
					class="inline-flex items-center gap-1.5 px-4 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg hover:bg-teal-700 transition-colors cursor-pointer"
				>
					<Plus class="w-4 h-4" />
					Yeni Tip
				</button>
			{/if}
		</div>
	</div>

	<!-- Stat Cards -->
	<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
			<div class="text-xs uppercase tracking-wide text-gray-500">Toplam Oda</div>
			<div class="text-3xl font-bold text-teal-700 mt-1">{totalCapacity}</div>
			<div class="text-xs text-gray-500 mt-1">Aktif tiplerin toplamı</div>
		</div>
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
			<div class="text-xs uppercase tracking-wide text-gray-500">Aktif Tip</div>
			<div class="text-3xl font-bold text-gray-800 mt-1">{activeCount}</div>
			<div class="text-xs text-gray-500 mt-1">Doluluk hesabına dahil</div>
		</div>
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
			<div class="text-xs uppercase tracking-wide text-gray-500">Hedef</div>
			<div class="text-3xl font-bold text-amber-600 mt-1">341</div>
			<div class="text-xs text-gray-500 mt-1">
				Otel toplam oda — {totalCapacity === 341 ? '✓ uyumlu' : `fark: ${341 - totalCapacity}`}
			</div>
		</div>
	</div>

	<!-- Liste -->
	{#if loading}
		<div class="bg-white border border-gray-200 rounded-xl p-8 text-center text-gray-500">
			Yükleniyor...
		</div>
	{:else if items.length === 0}
		<EmptyState
			icon={BedDouble}
			title="Henüz oda tipi yok"
			description="İlk oda tipini ekleyerek başlayın"
			ctaText={canUse ? 'Yeni Tip' : ''}
			onCta={canUse ? openCreate : null}
		/>
	{:else}
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			<div class="overflow-x-auto">
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
												class="p-1.5 text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded transition-colors cursor-pointer"
												title="Düzenle"
											>
												<PencilLine class="w-4 h-4" />
											</button>
											<button
												onclick={() => askDelete(rt)}
												class="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors cursor-pointer"
												title="Sil"
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
		</div>
	{/if}
</div>

<!-- Modal: Oluştur / Düzenle -->
<Modal bind:show={showModal} title={editing ? 'Oda Tipini Düzenle' : 'Yeni Oda Tipi'} maxWidth="max-w-xl">
	<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4">
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div>
				<label for="rt-code" class="block text-sm font-medium text-gray-700 mb-1">
					Kod <span class="text-red-600">*</span>
				</label>
				<input
					id="rt-code"
					type="text"
					bind:value={form.code}
					placeholder="STD KARA"
					class="w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 font-mono uppercase {fieldErrors.code ? 'border-red-300' : 'border-gray-300'}"
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
				<input
					id="rt-name"
					type="text"
					bind:value={form.name}
					placeholder="Standart Kara Manzaralı"
					class="w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 {fieldErrors.name ? 'border-red-300' : 'border-gray-300'}"
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
				<input
					id="rt-total"
					type="number"
					bind:value={form.total_rooms}
					min="0"
					class="w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 {fieldErrors.total_rooms ? 'border-red-300' : 'border-gray-300'}"
				/>
				{#if fieldErrors.total_rooms}
					<p class="text-xs text-red-600 mt-1">{fieldErrors.total_rooms}</p>
				{/if}
			</div>
			<div>
				<label for="rt-max" class="block text-sm font-medium text-gray-700 mb-1">
					Maks. Kişi
				</label>
				<input
					id="rt-max"
					type="number"
					bind:value={form.max_occupancy}
					min="1"
					max="20"
					class="w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 {fieldErrors.max_occupancy ? 'border-red-300' : 'border-gray-300'}"
				/>
				{#if fieldErrors.max_occupancy}
					<p class="text-xs text-red-600 mt-1">{fieldErrors.max_occupancy}</p>
				{/if}
			</div>
			<div>
				<label for="rt-sort" class="block text-sm font-medium text-gray-700 mb-1">
					Sıra
				</label>
				<input
					id="rt-sort"
					type="number"
					bind:value={form.sort_order}
					min="0"
					class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
				/>
			</div>
		</div>

		<div>
			<label for="rt-desc" class="block text-sm font-medium text-gray-700 mb-1">
				Açıklama
			</label>
			<textarea
				id="rt-desc"
				bind:value={form.description}
				rows="2"
				placeholder="Notlar veya özellikler"
				class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
			></textarea>
		</div>

		<div class="flex items-center gap-3">
			<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
				<input
					type="checkbox"
					bind:checked={form.is_active}
					class="w-4 h-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
				/>
				Aktif (doluluk hesabına dahil)
			</label>
		</div>

		<!-- Projected total banner -->
		<div
			class="px-3 py-2 rounded-lg text-sm flex items-center justify-between {projectedTotal === 341 ? 'bg-green-50 text-green-700' : projectedTotal > 341 ? 'bg-amber-50 text-amber-700' : 'bg-gray-50 text-gray-600'}"
		>
			<span>Kaydetme sonrası toplam:</span>
			<span class="font-bold">
				{projectedTotal} / 341
				{#if projectedTotal === 341}
					✓
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
			<button
				type="button"
				onclick={() => (showModal = false)}
				class="px-4 py-2 text-sm text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors cursor-pointer"
			>
				İptal
			</button>
			<button
				type="submit"
				disabled={saving}
				class="px-4 py-2 text-sm text-white bg-teal-600 rounded-lg hover:bg-teal-700 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
			>
				{saving ? 'Kaydediliyor...' : 'Kaydet'}
			</button>
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
