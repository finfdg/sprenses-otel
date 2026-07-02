<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { WS_EVENT } from '$lib/constants/realtime';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge, { type BadgeType } from '$lib/components/StatusBadge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Input from '$lib/components/Input.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import Field from '$lib/components/Field.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { Receipt, AlarmClock, CalendarClock, Building2, Pencil, Search, ChevronDown, ChevronRight } from 'lucide-svelte';

	// Sabitler
	const BUCKET_LABELS: Record<string, string> = {
		not_due: 'Vadesi gelmemiş', overdue_1_7: '1-7 gün', overdue_8_30: '8-30 gün', overdue_30_plus: '30+ gün'
	};
	const CURRENCY_SYMBOLS: Record<string, string> = { EUR: '€', USD: '$', TL: '₺', TRY: '₺', GBP: '£' };

	// Türetilmiş
	let canUse = $derived(hasPermission('finance.hakedis', 'use'));

	// Veri state
	let firms = $state<any[]>([]);
	let summary = $state<any>(null);
	let loading = $state(true);
	let invoicesByFirm = $state<Record<string, any[]>>({});
	let invoiceLoading = $state<Record<string, boolean>>({});

	// UI state
	let search = $state('');
	let searchDebounced = $state('');
	let onlyOverdue = $state(false);
	let expanded = $state<Record<string, boolean>>({});
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	let unsubWs: (() => void) | null = null;

	// Form state (vade düzenleme)
	let termModalOpen = $state(false);
	let termFirm = $state<any>(null);
	let termDays = $state<number | null>(30);
	let termNotes = $state('');
	let termSaving = $state(false);
	let fieldErrors = $state<Record<string, string>>({});

	let filteredFirms = $derived(firms.filter((f) => {
		if (onlyOverdue && f.overdue_tl <= 0) return false;
		if (!searchDebounced) return true;
		const q = searchDebounced.toLocaleLowerCase('tr');
		return f.code.toLocaleLowerCase('tr').includes(q) || (f.name || '').toLocaleLowerCase('tr').includes(q);
	}));

	// Formatlama
	function fmt(n: number): string {
		return new Intl.NumberFormat('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0);
	}
	function fmtDate(s: string | null): string {
		if (!s) return '—';
		const [y, m, d] = s.split('-');
		return `${d}.${m}.${y}`;
	}
	function overdueBadge(days: number): BadgeType {
		if (days <= 0) return 'success';
		if (days <= 7) return 'warning';
		return 'error';
	}

	// Veri fonksiyonları
	async function loadData() {
		loading = true;
		try {
			const r: any = await api.get('/finance/hakedis/');
			firms = r.firms || [];
			summary = r.summary || null;
		} catch (err) {
			console.error('Hak ediş verisi yüklenemedi:', err);
			showToast('Hak ediş verisi yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	async function toggleExpand(code: string) {
		expanded[code] = !expanded[code];
		if (expanded[code] && !invoicesByFirm[code]) {
			invoiceLoading[code] = true;
			try {
				const r: any = await api.get(`/finance/hakedis/firms/${encodeURIComponent(code)}/invoices`);
				invoicesByFirm[code] = r.items || [];
			} catch (err) {
				console.error('Fatura detayı yüklenemedi:', err);
				showToast('Fatura detayı yüklenemedi', 'error');
				expanded[code] = false;
			} finally {
				invoiceLoading[code] = false;
			}
		}
	}

	// CRUD — vade tanımı
	function openTermEdit(firm: any) {
		termFirm = firm;
		termDays = firm.term_days;
		termNotes = '';
		fieldErrors = {};
		termModalOpen = true;
	}

	async function handleTermSave() {
		fieldErrors = {};
		if (termDays === null || termDays < 0 || termDays > 365) {
			fieldErrors = { term_days: 'Vade 0-365 gün aralığında olmalıdır' };
			return;
		}
		termSaving = true;
		try {
			const resp: any = await api.patch(`/finance/hakedis/terms/${encodeURIComponent(termFirm.code)}`, {
				term_days: termDays, notes: termNotes || null
			});
			if (resp?.approval_required || resp?.request_id) {
				showToast('Vade değişikliği onaya gönderildi', 'info');
			} else {
				showToast('Vade güncellendi', 'success');
			}
			termModalOpen = false;
			await loadData();
		} catch (err: any) {
			console.error('Vade kaydedilemedi:', err);
			showToast(err?.message || 'Vade kaydedilemedi', 'error');
		} finally {
			termSaving = false;
		}
	}

	// UI yardımcıları
	function onSearchInput() {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => (searchDebounced = search), 300);
	}
	// Input'un ✕ (clearable) butonu value'yu doğrudan boşaltır → debounce'u beklemeden yansıt
	$effect(() => {
		if (search === '') searchDebounced = '';
	});

	// Lifecycle
	onMount(() => {
		loadData();
		unsubWs = onWsEvent(WS_EVENT.FINANCE_UPDATED, () => loadData());
	});
	onDestroy(() => {
		if (searchTimer) clearTimeout(searchTimer);
		unsubWs?.();
	});
</script>

<svelte:head>
	<title>Hak Ediş Takibi | Sprenses</title>
</svelte:head>

<PageHeader
	title="Hak Ediş Takibi"
	description="Çıkışta kesilen acente faturaları — anlaşma vadesi (30/45 gün) içinde tahsilat takibi. Münferit (walk-in) satışlar hariçtir: misafir çıkışta öder."
/>

<!-- Özet kartları -->
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
	<StatCard label="Açık Hak Ediş" value={`₺${fmt(summary?.open_tl ?? 0)}`} icon={Receipt} accent="teal"
		hint={`${summary?.firm_count ?? 0} firma`} />
	<StatCard label="Vadesi Geçen" value={`₺${fmt(summary?.overdue_tl ?? 0)}`} icon={AlarmClock} accent="red"
		hint={`${summary?.overdue_firm_count ?? 0} firma gecikmede`} />
	<StatCard label="7 Gün İçinde Vadesi Dolan" value={`₺${fmt(summary?.due_7d_tl ?? 0)}`} icon={CalendarClock} accent="amber" />
	<StatCard label="30+ Gün Geciken" value={`₺${fmt(summary?.buckets?.overdue_30_plus ?? 0)}`} icon={Building2} accent="red" />
</div>

<!-- Filtre barı -->
<div class="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
	<div class="w-full sm:w-80">
		<Input
			bind:value={search}
			oninput={onSearchInput}
			icon={Search}
			clearable
			placeholder="Firma kodu veya adı ara…"
			aria-label="Firma ara"
		/>
	</div>
	<label class="inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
		<input type="checkbox" bind:checked={onlyOverdue} class="accent-teal-700 focus:ring-teal-500" />
		Yalnız vadesi geçenler
	</label>
	<span class="text-sm text-gray-500 sm:ml-auto">{filteredFirms.length} firma</span>
</div>

<!-- Ana içerik -->
{#if loading}
	<TableSkeleton rows={6} columns={7} />
{:else if filteredFirms.length === 0}
	<EmptyState icon={Receipt} title="Açık hak ediş bulunamadı"
		description={searchDebounced || onlyOverdue ? 'Filtreyle eşleşen firma yok.' : 'Tüm acente faturaları tahsil edilmiş görünüyor.'} />
{:else}
	<!-- Masaüstü tablo -->
	<div class="hidden sm:block bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-gray-200 text-left text-gray-600">
					<th class="px-4 py-3 w-8"></th>
					<th class="px-4 py-3">Firma</th>
					<th class="px-4 py-3">Vade</th>
					<th class="px-4 py-3 text-right">Açık Tutar</th>
					<th class="px-4 py-3 text-right">Vadesi Geçen</th>
					<th class="px-4 py-3">Gecikme</th>
					<th class="px-4 py-3">Sonraki Vade</th>
					<th class="px-4 py-3 text-right">Fatura</th>
				</tr>
			</thead>
			<tbody>
				{#each filteredFirms as f (f.code)}
					<tr class="border-b border-gray-100 hover:bg-gray-50 group cursor-pointer" onclick={() => toggleExpand(f.code)}>
						<td class="px-4 py-3 text-gray-500">
							{#if expanded[f.code]}<ChevronDown size={16} />{:else}<ChevronRight size={16} />{/if}
						</td>
						<td class="px-4 py-3">
							<div class="font-medium text-gray-900">{f.name || f.code}</div>
							<div class="text-xs text-gray-500 font-mono">{f.code} · {f.currencies.join(', ')}</div>
						</td>
						<td class="px-4 py-3">
							<span class="inline-flex items-center gap-1.5">
								<span class="tabular-nums">{f.term_days} gün</span>
								{#if f.is_default_term}<span class="text-xs text-gray-500">(varsayılan)</span>{/if}
								{#if canUse}
									<button type="button" aria-label={`${f.name || f.code} vadesini düzenle`}
										onclick={(e) => { e.stopPropagation(); openTermEdit(f); }}
										class="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-teal-700 touch-target">
										<Pencil size={14} />
									</button>
								{/if}
							</span>
						</td>
						<td class="px-4 py-3 text-right tabular-nums font-medium">₺{fmt(f.open_tl)}</td>
						<td class="px-4 py-3 text-right tabular-nums {f.overdue_tl > 0 ? 'text-red-600 font-semibold' : 'text-gray-500'}">
							{f.overdue_tl > 0 ? `₺${fmt(f.overdue_tl)}` : '—'}
						</td>
						<td class="px-4 py-3">
							<StatusBadge type={overdueBadge(f.max_overdue_days)}>
								{f.max_overdue_days > 0 ? `${f.max_overdue_days} gün` : 'Vadesinde'}
							</StatusBadge>
						</td>
						<td class="px-4 py-3 tabular-nums text-gray-700">{fmtDate(f.next_due_date)}</td>
						<td class="px-4 py-3 text-right tabular-nums text-gray-700">{f.invoice_count}</td>
					</tr>
					{#if expanded[f.code]}
						<tr class="border-b border-gray-100 bg-gray-50/60">
							<td colspan="8" class="px-6 py-3">
								{#if invoiceLoading[f.code]}
									<TableSkeleton rows={3} columns={6} />
								{:else}
									<table class="w-full text-xs">
										<thead>
											<tr class="text-left text-gray-600">
												<th class="py-1.5 pr-3">Fatura No</th>
												<th class="py-1.5 pr-3">Tarih</th>
												<th class="py-1.5 pr-3">Vade</th>
												<th class="py-1.5 pr-3">Gecikme</th>
												<th class="py-1.5 pr-3 text-right">Tutar</th>
												<th class="py-1.5 pr-3 text-right">Kalan</th>
											</tr>
										</thead>
										<tbody>
											{#each invoicesByFirm[f.code] || [] as inv (inv.id)}
												<tr class="border-t border-gray-100">
													<td class="py-1.5 pr-3 font-mono">{inv.invoice_no || '—'}</td>
													<td class="py-1.5 pr-3 tabular-nums">{fmtDate(inv.invoice_date)}</td>
													<td class="py-1.5 pr-3 tabular-nums">{fmtDate(inv.due_date)}</td>
													<td class="py-1.5 pr-3">
														{#if inv.overdue_days > 0}
															<span class="text-red-600 font-medium">{inv.overdue_days} gün</span>
														{:else}
															<span class="text-gray-500">—</span>
														{/if}
													</td>
													<td class="py-1.5 pr-3 text-right tabular-nums">
														{CURRENCY_SYMBOLS[inv.currency] ?? inv.currency}{fmt(inv.amount)}
													</td>
													<td class="py-1.5 pr-3 text-right tabular-nums font-medium">
														{CURRENCY_SYMBOLS[inv.currency] ?? inv.currency}{fmt(inv.remaining)}
														<span class="text-gray-500 font-normal">(₺{fmt(inv.remaining_tl)})</span>
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								{/if}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Mobil kartlar -->
	<div class="sm:hidden space-y-3">
		{#each filteredFirms as f (f.code)}
			<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4">
				<div class="flex items-start justify-between gap-2">
					<div>
						<div class="font-medium text-gray-900">{f.name || f.code}</div>
						<div class="text-xs text-gray-500 font-mono">{f.code}</div>
					</div>
					<StatusBadge type={overdueBadge(f.max_overdue_days)}>
						{f.max_overdue_days > 0 ? `${f.max_overdue_days} gün` : 'Vadesinde'}
					</StatusBadge>
				</div>
				<div class="mt-3 grid grid-cols-2 gap-2 text-sm">
					<div><span class="text-gray-500">Açık:</span> <span class="tabular-nums font-medium">₺{fmt(f.open_tl)}</span></div>
					<div><span class="text-gray-500">Geciken:</span>
						<span class="tabular-nums {f.overdue_tl > 0 ? 'text-red-600 font-semibold' : ''}">₺{fmt(f.overdue_tl)}</span></div>
					<div><span class="text-gray-500">Vade:</span> {f.term_days} gün{f.is_default_term ? ' (vars.)' : ''}</div>
					<div><span class="text-gray-500">Sonraki:</span> <span class="tabular-nums">{fmtDate(f.next_due_date)}</span></div>
				</div>
				{#if canUse}
					<div class="mt-3">
						<Button variant="secondary" size="sm" fullWidth onclick={() => openTermEdit(f)}>
							<Pencil size={14} /> Vadeyi Düzenle
						</Button>
					</div>
				{/if}
			</div>
		{/each}
	</div>
{/if}

<!-- Vade düzenleme modalı -->
<Modal bind:show={termModalOpen} title={`Vade Tanımı — ${termFirm?.name || termFirm?.code || ''}`} maxWidth="max-w-md">
	<div class="space-y-4">
		<Field label="Sözleşme vadesi (gün)" required error={fieldErrors.term_days}>
			<Input type="number" bind:value={termDays} min={0} max={365} placeholder="30"
				invalid={!!fieldErrors.term_days} />
		</Field>
		<Field label="Not">
			<Textarea bind:value={termNotes} rows={2} placeholder="ör. 2026 anlaşması — 45 gün" />
		</Field>
		<p class="text-xs text-gray-500">
			Vade, fatura tarihine eklenerek son ödeme tarihini belirler. Sedna'da vade bilgisi tutulmadığından
			bu tanım yalnız bu sistemde saklanır.
		</p>
		<div class="flex justify-end gap-2 pt-2">
			<Button variant="secondary" onclick={() => (termModalOpen = false)}>İptal</Button>
			<Button variant="primary" loading={termSaving} onclick={handleTermSave}>Kaydet</Button>
		</div>
	</div>
</Modal>
