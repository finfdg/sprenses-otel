<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Button from '$lib/components/Button.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { Plus, Pencil, Trash2, Clock, CalendarClock } from 'lucide-svelte';

	type Shift = {
		id: number; name: string; color: string;
		start_time: string; end_time: string; start_time2: string | null; end_time2: string | null;
		is_split: boolean; crosses_midnight: boolean; duration_minutes: number; duration_hours: number;
		description: string | null; is_active: boolean; sort_order: number;
	};

	const COLORS = ['#3b82f6', '#f59e0b', '#6366f1', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'];
	const canUse = hasPermission('hr.shifts', 'use');

	let shifts = $state<Shift[]>([]);
	let loading = $state(true);

	let showModal = $state(false);
	let editing = $state<Shift | null>(null);
	let form = $state({
		name: '', color: '#3b82f6', start_time: '07:00', end_time: '15:00',
		is_split: false, start_time2: '13:00', end_time2: '17:00',
		description: '', is_active: true, sort_order: 0,
	});
	let saving = $state(false);
	let formError = $state('');
	let confirmDel = $state<{ show: boolean; target: Shift | null }>({ show: false, target: null });

	let activeCount = $derived(shifts.filter((s) => s.is_active).length);

	function fmtDur(mins: number): string {
		const h = Math.floor(mins / 60);
		const m = mins % 60;
		return m > 0 ? `${h} sa ${m} dk` : `${h} sa`;
	}

	async function load() {
		loading = true;
		try {
			const r = await api.get<{ items: Shift[] }>('/hr/shifts');
			shifts = r.items;
		} catch (e) {
			console.error('Vardiyalar alınamadı:', e);
		}
		loading = false;
	}

	function openCreate() {
		editing = null;
		formError = '';
		form = { name: '', color: COLORS[shifts.length % COLORS.length], start_time: '07:00', end_time: '15:00', is_split: false, start_time2: '13:00', end_time2: '17:00', description: '', is_active: true, sort_order: (shifts.length + 1) };
		showModal = true;
	}
	function openEdit(s: Shift) {
		editing = s;
		formError = '';
		form = {
			name: s.name, color: s.color, start_time: s.start_time, end_time: s.end_time,
			is_split: s.is_split, start_time2: s.start_time2 ?? '13:00', end_time2: s.end_time2 ?? '17:00',
			description: s.description ?? '', is_active: s.is_active, sort_order: s.sort_order,
		};
		showModal = true;
	}
	async function save() {
		formError = '';
		if (!form.name.trim()) { formError = 'Vardiya adı zorunlu'; return; }
		if (!form.start_time || !form.end_time) { formError = 'Başlangıç ve bitiş saati zorunlu'; return; }
		if (form.is_split && (!form.start_time2 || !form.end_time2)) { formError = 'Split vardiyada ikinci segment saatleri zorunlu'; return; }
		saving = true;
		const payload = {
			name: form.name.trim(), color: form.color,
			start_time: form.start_time, end_time: form.end_time,
			start_time2: form.is_split ? form.start_time2 : null,
			end_time2: form.is_split ? form.end_time2 : null,
			description: form.description.trim() || null,
			is_active: form.is_active, sort_order: form.sort_order,
		};
		try {
			const res: any = editing
				? await api.patch(`/hr/shifts/${editing.id}`, payload)
				: await api.post('/hr/shifts', payload);
			showModal = false;
			if (res?.requires_approval) {
				showToast('İşlem onaya gönderildi', 'info');
			} else {
				showToast(editing ? 'Vardiya güncellendi' : 'Vardiya eklendi', 'success');
				await load();
			}
		} catch (e) {
			formError = e instanceof ApiError ? e.message : 'Kayıt başarısız';
		} finally {
			saving = false;
		}
	}
	function askDelete(s: Shift) { confirmDel = { show: true, target: s }; }
	async function doDelete() {
		const s = confirmDel.target;
		if (!s) return;
		try {
			const res: any = await api.delete(`/hr/shifts/${s.id}`);
			confirmDel = { show: false, target: null };
			if (res?.requires_approval) showToast('Silme onaya gönderildi', 'info');
			else { showToast('Vardiya silindi', 'success'); await load(); }
		} catch (e) {
			showToast(e instanceof ApiError ? e.message : 'Silinemedi', 'error');
		}
	}

	onMount(load);
</script>

<svelte:head><title>Vardiyalar | Sprenses</title></svelte:head>

<div class="max-w-6xl mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-5">
	<PageHeader title="Vardiyalar" description="Otel vardiya tanımları (Sabah / Akşam / Gece / Split)">
		{#snippet actions()}
			{#if canUse}<Button onclick={openCreate}><Plus size={16} /> Yeni Vardiya</Button>{/if}
		{/snippet}
	</PageHeader>

	<div class="grid grid-cols-2 lg:grid-cols-2 gap-3 sm:gap-4 max-w-md">
		<StatCard label="Toplam Vardiya" value={`${shifts.length}`} icon={CalendarClock} accent="teal" hint="Tanımlı" />
		<StatCard label="Aktif" value={`${activeCount}`} icon={Clock} accent="emerald" hint="Kullanımda" />
	</div>

	{#if loading}
		<TableSkeleton rows={4} columns={3} />
	{:else if shifts.length === 0}
		<EmptyState icon={CalendarClock} title="Henüz vardiya yok" description="Otel vardiyalarını tanımlayın" ctaText={canUse ? 'Yeni Vardiya' : ''} onCta={canUse ? openCreate : null} />
	{:else}
		<div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each shifts as s (s.id)}
				<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden {s.is_active ? '' : 'opacity-60'}">
					<div class="h-1.5" style="background-color: {s.color}"></div>
					<div class="p-4 space-y-2.5">
						<div class="flex items-start justify-between gap-2">
							<div class="flex items-center gap-2 min-w-0">
								<span class="w-3 h-3 rounded-full shrink-0" style="background-color: {s.color}"></span>
								<h3 class="font-semibold text-gray-900 truncate">{s.name}</h3>
							</div>
							{#if canUse}
								<div class="flex items-center gap-1 shrink-0">
									<button onclick={() => openEdit(s)} class="p-1.5 text-gray-400 hover:text-teal-600 hover:bg-teal-50 rounded cursor-pointer" title="Düzenle"><Pencil size={15} /></button>
									<button onclick={() => askDelete(s)} class="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded cursor-pointer" title="Sil"><Trash2 size={15} /></button>
								</div>
							{/if}
						</div>
						<div class="text-2xl font-bold text-gray-900 tabular-nums">
							{s.start_time}<span class="text-gray-400 font-normal mx-1">–</span>{s.end_time}
							{#if s.is_split && s.start_time2}<span class="text-base text-gray-500"> + {s.start_time2}–{s.end_time2}</span>{/if}
						</div>
						<div class="flex flex-wrap items-center gap-1.5 text-xs">
							<span class="px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">{fmtDur(s.duration_minutes)}</span>
							{#if s.crosses_midnight}<StatusBadge type="info">Gece (gün aşan)</StatusBadge>{/if}
							{#if s.is_split}<StatusBadge type="warning">Split</StatusBadge>{/if}
							{#if !s.is_active}<StatusBadge type="neutral">Pasif</StatusBadge>{/if}
						</div>
						{#if s.description}<p class="text-xs text-gray-500 leading-snug">{s.description}</p>{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Ekle / Düzenle -->
<Modal bind:show={showModal} title={editing ? 'Vardiyayı Düzenle' : 'Yeni Vardiya'} maxWidth="max-w-md">
	<div class="space-y-4">
		<div>
			<label for="sf-name" class="block text-sm font-medium text-gray-700 mb-1">Vardiya Adı <span class="text-red-500">*</span></label>
			<input id="sf-name" type="text" bind:value={form.name} placeholder="Sabah, Akşam, Gece…" class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
		</div>
		<div>
			<span class="block text-sm font-medium text-gray-700 mb-1">Renk</span>
			<div class="flex flex-wrap gap-2">
				{#each COLORS as c}
					<button type="button" onclick={() => (form.color = c)} class="w-7 h-7 rounded-full border-2 cursor-pointer {form.color === c ? 'border-gray-800 scale-110' : 'border-transparent'} transition-transform" style="background-color: {c}" aria-label="Renk"></button>
				{/each}
			</div>
		</div>
		<div class="grid grid-cols-2 gap-3">
			<div>
				<label for="sf-start" class="block text-sm font-medium text-gray-700 mb-1">Başlangıç <span class="text-red-500">*</span></label>
				<input id="sf-start" type="time" bind:value={form.start_time} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm tabular-nums focus:ring-2 focus:ring-teal-500 outline-none" />
			</div>
			<div>
				<label for="sf-end" class="block text-sm font-medium text-gray-700 mb-1">Bitiş <span class="text-red-500">*</span></label>
				<input id="sf-end" type="time" bind:value={form.end_time} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm tabular-nums focus:ring-2 focus:ring-teal-500 outline-none" />
			</div>
		</div>
		<p class="text-xs text-gray-400 -mt-2">Bitiş, başlangıçtan küçük/eşitse vardiya gece yarısını geçer (ör. 23:00–07:00).</p>

		<label class="flex items-center gap-2 cursor-pointer">
			<input type="checkbox" bind:checked={form.is_split} class="rounded border-gray-300 text-teal-700 focus:ring-teal-500" />
			<span class="text-sm text-gray-700">Split vardiya (iki ayrı segment — ör. restoran/banquet)</span>
		</label>
		{#if form.is_split}
			<div class="grid grid-cols-2 gap-3 pl-1 border-l-2 border-amber-200">
				<div>
					<label for="sf-start2" class="block text-xs font-medium text-gray-600 mb-1">2. Başlangıç</label>
					<input id="sf-start2" type="time" bind:value={form.start_time2} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm tabular-nums focus:ring-2 focus:ring-teal-500 outline-none" />
				</div>
				<div>
					<label for="sf-end2" class="block text-xs font-medium text-gray-600 mb-1">2. Bitiş</label>
					<input id="sf-end2" type="time" bind:value={form.end_time2} class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm tabular-nums focus:ring-2 focus:ring-teal-500 outline-none" />
				</div>
			</div>
		{/if}

		<div>
			<label for="sf-desc" class="block text-sm font-medium text-gray-700 mb-1">Açıklama (opsiyonel)</label>
			<input id="sf-desc" type="text" bind:value={form.description} placeholder="Hangi departman/görev…" class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
		</div>
		<label class="flex items-center gap-2 cursor-pointer">
			<input type="checkbox" bind:checked={form.is_active} class="rounded border-gray-300 text-teal-700 focus:ring-teal-500" />
			<span class="text-sm text-gray-700">Aktif</span>
		</label>

		{#if formError}<div class="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">{formError}</div>{/if}
		<div class="flex justify-end gap-2 pt-1">
			<Button type="button" variant="secondary" onclick={() => (showModal = false)}>İptal</Button>
			<Button onclick={save} loading={saving}>{editing ? 'Güncelle' : 'Kaydet'}</Button>
		</div>
	</div>
</Modal>

<ConfirmDialog
	bind:show={confirmDel.show}
	danger
	title="Vardiyayı Sil"
	message={confirmDel.target ? `"${confirmDel.target.name}" vardiyası silinecek. Devam edilsin mi?` : ''}
	confirmText="Sil"
	onCancel={() => (confirmDel = { show: false, target: null })}
	onConfirm={doDelete}
/>
