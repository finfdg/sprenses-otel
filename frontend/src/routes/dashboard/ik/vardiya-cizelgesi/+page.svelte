<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { WS_EVENT } from '$lib/constants/realtime';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Button from '$lib/components/Button.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import {
		CalendarDays, ChevronLeft, ChevronRight, Search, Copy, Users,
		CalendarCheck, Gauge, Paintbrush, Eraser, MousePointerClick, X
	} from 'lucide-svelte';

	type Shift = {
		id: number; name: string; color: string;
		start_time: string; end_time: string; start_time2: string | null; end_time2: string | null;
		is_split: boolean; crosses_midnight: boolean; duration_hours: number;
	};
	type Person = { id: number; full_name: string; employee_code: string; department: string | null; title: string | null };
	type Assignment = { id: number; personnel_id: number; shift_id: number; work_date: string; note: string | null };

	const DAY_NAMES = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
	const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

	const canUse = hasPermission('hr.shift_schedule', 'use');

	// ── Tarih yardımcıları (yerel — UTC kayması yok) ──
	function pad(n: number): string { return String(n).padStart(2, '0'); }
	function isoOf(d: Date): string { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
	function addDays(d: Date, n: number): Date { const c = new Date(d.getFullYear(), d.getMonth(), d.getDate()); c.setDate(c.getDate() + n); return c; }
	function mondayOf(d: Date): Date { const c = new Date(d.getFullYear(), d.getMonth(), d.getDate()); const wd = (c.getDay() + 6) % 7; return addDays(c, -wd); }
	function textOn(hex: string): string {
		const h = (hex || '#888').replace('#', '');
		const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
		return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? '#1f2937' : '#ffffff';
	}
	function fmtLongDate(iso: string): string {
		const d = new Date(iso + 'T00:00:00');
		return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
	}

	// ── State ──
	let shifts = $state<Shift[]>([]);
	let personnel = $state<Person[]>([]);
	let departments = $state<string[]>([]);
	let assignments = $state<Assignment[]>([]);
	let loading = $state(true);

	let weekStart = $state<Date>(mondayOf(new Date()));
	let search = $state('');
	let deptFilter = $state('');
	// Fırça: null=seçim modu, 'clear'=silgi, number=vardiya id
	let brush = $state<number | 'clear' | null>(null);
	// Mobil tek-gün görünümü — haftalık grid yerine seçili günün personel listesi (Pzt=0)
	let selectedDayIndex = $state((new Date().getDay() + 6) % 7);

	// Tek hücre seçim modalı
	let showCellModal = $state(false);
	let cellTarget = $state<{ p: Person; iso: string } | null>(null);
	// Onay diyalogları
	let showFillCol = $state(false);
	let fillColDay = $state<{ iso: string; label: string } | null>(null);
	let showCopyPrev = $state(false);

	// ── Türetilmiş ──
	let weekStartIso = $derived(isoOf(weekStart));
	let days = $derived.by(() => {
		const todayIso = isoOf(new Date());
		return Array.from({ length: 7 }, (_, i) => {
			const d = addDays(weekStart, i);
			return { iso: isoOf(d), dayName: DAY_NAMES[i], dayNum: d.getDate(), month: MONTHS[d.getMonth()], isToday: isoOf(d) === todayIso, isWeekend: i >= 5 };
		});
	});
	let weekLabel = $derived.by(() => {
		const a = days[0], b = days[6];
		if (!a || !b) return '';
		const ad = addDays(weekStart, 0), bd = addDays(weekStart, 6);
		const yr = bd.getFullYear();
		if (ad.getMonth() === bd.getMonth()) return `${a.dayNum} – ${b.dayNum} ${a.month} ${yr}`;
		return `${a.dayNum} ${a.month} – ${b.dayNum} ${b.month} ${yr}`;
	});
	let shiftMap = $derived(new Map(shifts.map((s) => [s.id, s])));
	let cellMap = $derived(new Map(assignments.map((a) => [`${a.personnel_id}|${a.work_date}`, a])));
	let filteredPersonnel = $derived.by(() => {
		const q = search.trim().toLocaleLowerCase('tr');
		return personnel.filter((p) => {
			if (deptFilter && p.department !== deptFilter) return false;
			if (!q) return true;
			return (
				p.full_name.toLocaleLowerCase('tr').includes(q) ||
				(p.employee_code || '').toLocaleLowerCase('tr').includes(q) ||
				(p.title || '').toLocaleLowerCase('tr').includes(q)
			);
		});
	});
	let visiblePids = $derived(new Set(filteredPersonnel.map((p) => p.id)));
	let dayCounts = $derived.by(() => {
		const m: Record<string, number> = {};
		for (const d of days) m[d.iso] = 0;
		for (const a of assignments) if (visiblePids.has(a.personnel_id) && a.work_date in m) m[a.work_date]++;
		return m;
	});
	let assignedThisWeek = $derived(assignments.filter((a) => visiblePids.has(a.personnel_id)).length);
	let coverage = $derived(filteredPersonnel.length > 0 ? Math.round((assignedThisWeek / (filteredPersonnel.length * 7)) * 100) : 0);
	let selectedDay = $derived(days[selectedDayIndex] ?? days[0]);
	let selectedDayLabel = $derived(selectedDay ? `${selectedDay.dayName} ${selectedDay.dayNum} ${selectedDay.month}` : '');
	let brushLabel = $derived(
		brush === null ? 'Seçim modu' : brush === 'clear' ? 'İzinli / Sil' : (shiftMap.get(brush)?.name ?? 'Vardiya')
	);

	// ── Veri ──
	async function load() {
		loading = true;
		try {
			const end = isoOf(addDays(weekStart, 6));
			const r = await api.get<{ shifts: Shift[]; personnel: Person[]; departments: string[]; assignments: Assignment[] }>(
				`/hr/shift-schedule?start=${weekStartIso}&end=${end}`
			);
			shifts = r.shifts;
			personnel = r.personnel;
			departments = r.departments;
			assignments = r.assignments;
		} catch (e) {
			console.error('Vardiya çizelgesi alınamadı:', e);
			showToast(e instanceof ApiError ? e.message : 'Çizelge yüklenemedi', 'error');
		}
		loading = false;
	}

	let reloadTimer: ReturnType<typeof setTimeout> | undefined;
	function scheduleReload() { clearTimeout(reloadTimer); reloadTimer = setTimeout(load, 600); }

	function gotoWeek(delta: number) { weekStart = addDays(weekStart, delta * 7); load(); }
	function gotoToday() { weekStart = mondayOf(new Date()); load(); }

	function upsertLocal(a: Assignment) {
		assignments = [...assignments.filter((x) => !(x.personnel_id === a.personnel_id && x.work_date === a.work_date)), a];
	}

	async function assignCell(pid: number, iso: string, shiftId: number) {
		try {
			const res: any = await api.post('/hr/shift-schedule', { personnel_id: pid, shift_id: shiftId, work_date: iso });
			if (res?.requires_approval) { showToast('Atama onaya gönderildi', 'info'); return; }
			upsertLocal(res);
		} catch (e) { showToast(e instanceof ApiError ? e.message : 'Atama başarısız', 'error'); }
	}
	async function removeCell(pid: number, iso: string) {
		const a = cellMap.get(`${pid}|${iso}`);
		if (!a) return;
		try {
			const res: any = await api.delete(`/hr/shift-schedule/${a.id}`);
			if (res?.requires_approval) { showToast('Silme onaya gönderildi', 'info'); return; }
			assignments = assignments.filter((x) => x.id !== a.id);
		} catch (e) { showToast(e instanceof ApiError ? e.message : 'Silinemedi', 'error'); }
	}

	function onCell(p: Person, iso: string) {
		if (!canUse) return;
		if (brush === null) { cellTarget = { p, iso }; showCellModal = true; return; }
		if (brush === 'clear') { removeCell(p.id, iso); return; }
		assignCell(p.id, iso, brush);
	}
	async function pickShift(sid: number) {
		if (cellTarget) await assignCell(cellTarget.p.id, cellTarget.iso, sid);
		showCellModal = false;
	}
	async function clearFromModal() {
		if (cellTarget) await removeCell(cellTarget.p.id, cellTarget.iso);
		showCellModal = false;
	}

	// Satır doldur (kişinin tüm haftası) — fırça gerekli
	async function fillRow(p: Person) {
		if (brush === null) { showToast('Önce bir vardiya fırçası seçin', 'info'); return; }
		try {
			const res: any = await api.post('/hr/shift-schedule/bulk', {
				personnel_ids: [p.id], shift_id: brush === 'clear' ? null : brush, dates: days.map((d) => d.iso),
			});
			showToast(`${p.full_name}: ${res.count} gün güncellendi`, 'success');
			await load();
		} catch (e) { showToast(e instanceof ApiError ? e.message : 'İşlem başarısız', 'error'); }
	}

	// Sütun doldur (günün tüm görünür personeli) — fırça + onay
	function askFillColumn(day: { iso: string; dayName: string; dayNum: number; month: string }) {
		if (!canUse) return;
		if (brush === null) { showToast('Önce bir vardiya fırçası seçin', 'info'); return; }
		fillColDay = { iso: day.iso, label: `${day.dayName} ${day.dayNum} ${day.month}` };
		showFillCol = true;
	}
	async function doFillColumn() {
		if (!fillColDay) return;
		try {
			const res: any = await api.post('/hr/shift-schedule/bulk', {
				personnel_ids: filteredPersonnel.map((p) => p.id),
				shift_id: brush === 'clear' ? null : brush,
				dates: [fillColDay.iso],
			});
			showToast(`${res.count} hücre güncellendi`, 'success');
			showFillCol = false;
			await load();
		} catch (e) { showToast(e instanceof ApiError ? e.message : 'İşlem başarısız', 'error'); }
	}

	// Geçen haftayı kopyala
	async function doCopyPrev() {
		try {
			const src = isoOf(addDays(weekStart, -7));
			const res: any = await api.post('/hr/shift-schedule/copy-week', { source_start: src, target_start: weekStartIso });
			showToast(res.count ? `${res.count} hücre kopyalandı` : 'Önceki hafta boş', res.count ? 'success' : 'info');
			showCopyPrev = false;
			await load();
		} catch (e) { showToast(e instanceof ApiError ? e.message : 'Kopyalanamadı', 'error'); }
	}

	onMount(() => {
		load();
		const unsubs = [
			onWsEvent(WS_EVENT.SHIFT_SCHEDULE_UPDATED, scheduleReload),
			onWsEvent(WS_EVENT.APPROVAL_STATUS_CHANGED, (e: any) => { if (e?.module_code === 'hr.shift_schedule') scheduleReload(); }),
		];
		return () => { unsubs.forEach((u) => u()); clearTimeout(reloadTimer); };
	});
</script>

<svelte:head><title>Vardiya Çizelgesi | Sprenses</title></svelte:head>

<div class="max-w-[1400px] mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-5">
	<PageHeader title="Vardiya Çizelgesi" description="Haftalık rota — hangi gün kim hangi vardiyada">
		{#snippet actions()}
			{#if canUse}
				<Button variant="secondary" onclick={() => (showCopyPrev = true)}><Copy size={16} /> Geçen Haftayı Kopyala</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
		<StatCard label="Personel" value={`${filteredPersonnel.length}`} icon={Users} accent="teal" hint={deptFilter || 'Tümü'} />
		<StatCard label="Aktif Vardiya" value={`${shifts.length}`} icon={CalendarDays} accent="gray" hint="Seçilebilir" />
		<StatCard label="Atanan (bu hafta)" value={`${assignedThisWeek}`} icon={CalendarCheck} accent="blue" hint="Dolu hücre" />
		<StatCard label="Doluluk" value={`%${coverage}`} icon={Gauge} accent="emerald" hint="Haftalık kapsam" />
	</div>

	<!-- Araç çubuğu -->
	<div class="bg-white border border-gray-200 rounded-xl shadow-sm p-3 sm:p-4 space-y-3">
		<!-- Hafta navigasyonu -->
		<div class="flex items-center justify-between gap-2 flex-wrap">
			<div class="flex items-center gap-1.5">
				<button onclick={() => gotoWeek(-1)} class="p-2 text-gray-500 hover:text-teal-700 hover:bg-teal-50 rounded-lg cursor-pointer" title="Önceki hafta" aria-label="Önceki hafta"><ChevronLeft size={18} /></button>
				<button onclick={gotoToday} class="px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg cursor-pointer">Bu Hafta</button>
				<button onclick={() => gotoWeek(1)} class="p-2 text-gray-500 hover:text-teal-700 hover:bg-teal-50 rounded-lg cursor-pointer" title="Sonraki hafta" aria-label="Sonraki hafta"><ChevronRight size={18} /></button>
				<span class="ml-1 text-base font-semibold text-gray-900 tabular-nums">{weekLabel}</span>
			</div>
			<div class="flex items-center gap-2 flex-wrap w-full sm:w-auto">
				<div class="relative flex-1 min-w-[140px] sm:flex-none">
					<Search size={15} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
					<input type="text" bind:value={search} placeholder="Personel ara…" class="w-full sm:w-56 pl-8 pr-7 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none" />
					{#if search}<button onclick={() => (search = '')} class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 cursor-pointer" aria-label="Temizle"><X size={14} /></button>{/if}
				</div>
				<select bind:value={deptFilter} class="shrink-0 py-2 px-2.5 border border-gray-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-teal-500 outline-none cursor-pointer">
					<option value="">Tüm departmanlar</option>
					{#each departments as d}<option value={d}>{d}</option>{/each}
				</select>
			</div>
		</div>

		<!-- Fırça çubuğu -->
		{#if canUse}
			<div class="flex items-center gap-2 flex-wrap border-t border-gray-100 pt-3">
				<span class="text-xs font-medium text-gray-500 inline-flex items-center gap-1"><Paintbrush size={14} /> Fırça:</span>
				<button onclick={() => (brush = null)} class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border cursor-pointer {brush === null ? 'bg-gray-800 text-white border-gray-800' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}"><MousePointerClick size={13} /> Seçim</button>
				{#each shifts as s (s.id)}
					<button onclick={() => (brush = s.id)} class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border cursor-pointer {brush === s.id ? 'border-gray-800 ring-2 ring-gray-300' : 'border-gray-200 hover:bg-gray-50'}" style={brush === s.id ? `background:${s.color};color:${textOn(s.color)}` : ''}>
						<span class="w-2.5 h-2.5 rounded-full" style="background:{s.color}"></span>{s.name}
					</button>
				{/each}
				<button onclick={() => (brush = 'clear')} class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border cursor-pointer {brush === 'clear' ? 'bg-red-600 text-white border-red-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-red-50'}"><Eraser size={13} /> İzinli / Sil</button>
				<span class="text-xs text-gray-400 ml-auto hidden sm:inline">
					{#if brush === null}Hücreye tıkla → vardiya seç{:else}Hücrelere tıkla → <b class="text-gray-600">{brushLabel}</b> uygula · gün başlığına tıkla → sütunu doldur{/if}
				</span>
			</div>
		{/if}
	</div>

	<!-- Grid -->
	<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
		{#if loading}
			<div class="p-4 space-y-2">
				{#each Array(8) as _}<div class="h-10 bg-gray-100 rounded animate-pulse"></div>{/each}
			</div>
		{:else if personnel.length === 0}
			<EmptyState icon={Users} title="Personel bulunamadı" description="Devam Takip modülünden personel ekleyin veya içe aktarın." />
		{:else if filteredPersonnel.length === 0}
			<EmptyState icon={Search} title="Eşleşen personel yok" description="Arama veya departman filtresini değiştirin." />
		{:else}
			<div class="hidden md:block overflow-auto max-h-[68vh]">
				<table class="w-full border-collapse text-sm">
					<thead>
						<tr>
							<th class="sticky top-0 left-0 z-30 bg-gray-50 border-b border-r border-gray-200 px-3 py-2 text-left font-semibold text-gray-600 min-w-[180px]">
								Personel <span class="text-gray-400 font-normal">({filteredPersonnel.length})</span>
							</th>
							{#each days as day}
								<th class="sticky top-0 z-20 border-b border-gray-200 px-1 py-1.5 min-w-[92px] {day.isToday ? 'bg-teal-50' : day.isWeekend ? 'bg-gray-100' : 'bg-gray-50'}">
									<button onclick={() => askFillColumn(day)} disabled={!canUse} class="w-full rounded-md px-1 py-1 {canUse ? 'cursor-pointer hover:bg-white/70' : 'cursor-default'}" title={canUse ? 'Bu günü tüm görünür personele uygula (fırça gerekli)' : ''}>
										<div class="text-xs font-semibold {day.isToday ? 'text-teal-700' : 'text-gray-700'}">{day.dayName}</div>
										<div class="text-[11px] text-gray-500 tabular-nums">{day.dayNum} {day.month.slice(0, 3)}</div>
										<div class="text-[10px] text-gray-400 tabular-nums">{dayCounts[day.iso] ?? 0} kişi</div>
									</button>
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each filteredPersonnel as p (p.id)}
							<tr class="group hover:bg-gray-50/60">
								<th class="sticky left-0 z-10 bg-white group-hover:bg-gray-50 border-b border-r border-gray-100 px-3 py-1.5 text-left font-normal align-middle">
									<div class="flex items-center justify-between gap-2">
										<div class="min-w-0">
											<div class="font-medium text-gray-900 truncate max-w-[150px]">{p.full_name}</div>
											<div class="text-[11px] text-gray-400 truncate max-w-[150px]">
												{p.department || '—'}{p.title ? ` · ${p.title}` : ''}
											</div>
										</div>
										{#if canUse}
											<button onclick={() => fillRow(p)} class="shrink-0 p-1 text-gray-300 hover:text-teal-700 hover:bg-teal-50 rounded opacity-0 group-hover:opacity-100 cursor-pointer transition-opacity" title="Tüm haftayı fırçayla doldur" aria-label="Haftayı doldur"><Paintbrush size={14} /></button>
										{/if}
									</div>
								</th>
								{#each days as day}
									{@const a = cellMap.get(`${p.id}|${day.iso}`)}
									{@const sh = a ? shiftMap.get(a.shift_id) : null}
									<td class="border-b border-l border-gray-100 p-0.5 text-center {day.isToday ? 'bg-teal-50/40' : day.isWeekend ? 'bg-gray-50/60' : ''}">
										<button
											onclick={() => onCell(p, day.iso)}
											disabled={!canUse}
											class="w-full h-9 rounded-md text-xs font-medium truncate px-1 transition-colors {sh ? 'shadow-sm' : 'text-gray-300 hover:bg-gray-100'} {canUse ? 'cursor-pointer' : 'cursor-default'}"
											style={sh ? `background:${sh.color};color:${textOn(sh.color)}` : ''}
											title={sh ? `${sh.name} ${sh.start_time}–${sh.end_time}${a?.note ? ' · ' + a.note : ''}` : (canUse ? 'Vardiya ata' : '')}
										>
											{sh ? sh.name : (canUse ? '+' : '')}
										</button>
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<!-- Mobil: tek-gün liste görünümü (geniş grid yerine; md+ grid kalır) -->
			<div class="md:hidden">
				<div class="overflow-x-auto border-b border-gray-100 px-2 py-2">
					<div class="flex gap-1.5 min-w-max">
						{#each days as day, i}
							<button onclick={() => (selectedDayIndex = i)} class="flex flex-col items-center px-3 py-1.5 rounded-lg border shrink-0 cursor-pointer {selectedDayIndex === i ? 'bg-teal-700 text-white border-teal-700' : day.isToday ? 'bg-teal-50 text-teal-700 border-teal-200' : 'bg-white text-gray-600 border-gray-200'}">
								<span class="text-xs font-semibold">{day.dayName}</span>
								<span class="text-[11px] tabular-nums">{day.dayNum} {day.month.slice(0, 3)}</span>
								<span class="text-[10px] opacity-75 tabular-nums">{dayCounts[day.iso] ?? 0} kişi</span>
							</button>
						{/each}
					</div>
				</div>
				{#if canUse}
					<div class="flex items-center justify-between gap-2 px-3 py-2 bg-gray-50 border-b border-gray-100">
						<span class="text-xs font-medium text-gray-600">{selectedDayLabel}{brush !== null ? ` · fırça: ${brushLabel}` : ''}</span>
						<button onclick={() => selectedDay && askFillColumn(selectedDay)} class="text-xs font-medium text-teal-700 hover:bg-teal-50 px-2 py-1 rounded cursor-pointer inline-flex items-center gap-1"><Paintbrush size={12} /> Günü doldur</button>
					</div>
				{/if}
				<div class="divide-y divide-gray-100 max-h-[64vh] overflow-y-auto">
					{#each filteredPersonnel as p (p.id)}
						{@const a = cellMap.get(`${p.id}|${selectedDay?.iso}`)}
						{@const sh = a ? shiftMap.get(a.shift_id) : null}
						<button onclick={() => selectedDay && onCell(p, selectedDay.iso)} disabled={!canUse} class="w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left {canUse ? 'active:bg-gray-50 cursor-pointer' : 'cursor-default'}">
							<span class="min-w-0">
								<span class="block font-medium text-gray-900 truncate text-sm">{p.full_name}</span>
								<span class="block text-[11px] text-gray-400 truncate">{p.department || '—'}{p.title ? ` · ${p.title}` : ''}</span>
							</span>
							{#if sh}
								<span class="shrink-0 px-2.5 py-1 rounded-md text-xs font-semibold" style="background:{sh.color};color:{textOn(sh.color)}">{sh.name}</span>
							{:else}
								<span class="shrink-0 px-2.5 py-1 rounded-md text-xs text-gray-400 border border-dashed border-gray-300">{canUse ? '+ Ata' : '—'}</span>
							{/if}
						</button>
					{/each}
				</div>
			</div>
		{/if}
	</div>
</div>

<!-- Tek hücre: vardiya seç -->
<Modal bind:show={showCellModal} title="Vardiya Ata" maxWidth="max-w-sm">
	{#if cellTarget}
		<div class="space-y-3">
			<div class="text-sm text-gray-600">
				<span class="font-semibold text-gray-900">{cellTarget.p.full_name}</span>
				<span class="text-gray-400"> · </span>
				{fmtLongDate(cellTarget.iso)}
			</div>
			<div class="grid grid-cols-2 gap-2">
				{#each shifts as s (s.id)}
					<button onclick={() => pickShift(s.id)} class="flex items-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 hover:border-gray-400 hover:shadow-sm cursor-pointer text-left">
						<span class="w-3.5 h-3.5 rounded-full shrink-0" style="background:{s.color}"></span>
						<span class="min-w-0">
							<span class="block text-sm font-medium text-gray-900 truncate">{s.name}</span>
							<span class="block text-[11px] text-gray-500 tabular-nums">{s.start_time}–{s.end_time}{s.is_split ? ' (+)' : ''}</span>
						</span>
					</button>
				{/each}
			</div>
			<button onclick={clearFromModal} class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-red-200 text-red-700 hover:bg-red-50 cursor-pointer text-sm font-medium">
				<Eraser size={15} /> İzinli (Vardiyayı kaldır)
			</button>
		</div>
	{/if}
</Modal>

<ConfirmDialog
	bind:show={showFillCol}
	title="Sütunu Doldur"
	message={fillColDay ? `${fillColDay.label} günü için görünür ${filteredPersonnel.length} personele "${brushLabel}" uygulanacak. Devam edilsin mi?` : ''}
	confirmText="Uygula"
	onCancel={() => (showFillCol = false)}
	onConfirm={doFillColumn}
/>

<ConfirmDialog
	bind:show={showCopyPrev}
	title="Geçen Haftayı Kopyala"
	message={`Bir önceki haftanın (${weekLabel} öncesi) tüm vardiya atamaları bu haftaya kopyalanacak. Mevcut atamalar bu haftada eşleşen günlerde değişir. Devam edilsin mi?`}
	confirmText="Kopyala"
	onCancel={() => (showCopyPrev = false)}
	onConfirm={doCopyPrev}
/>
