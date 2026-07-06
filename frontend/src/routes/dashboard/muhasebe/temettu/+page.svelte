<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge, { type BadgeType } from '$lib/components/StatusBadge.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import Field from '$lib/components/Field.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import {
		Plus, Trash2, X, Check, ChevronRight, Coins, Banknote, Landmark,
		Users, CalendarDays, Search
	} from 'lucide-svelte';

	// Sabitler
	const STATUS_LABELS: Record<string, string> = { active: 'Aktif', cancelled: 'İptal' };
	const STATUS_BADGE: Record<string, BadgeType> = { active: 'success', cancelled: 'neutral' };
	// Yıl seçenekleri veriden türetilir (sabit dizi DEĞİL — gelecekteki yıllar gizlenmesin).
	let YEARS = $state<number[]>([]);

	// Türetilmiş
	let canUse = $derived(hasPermission('accounting.dividend', 'use'));

	// Veri state
	let distributions = $state<any[]>([]);
	let loading = $state(true);
	let total = $state(0);
	let page = $state(1);
	let pageSize = $state(50);

	// Filtre state
	let yearFilter = $state('');
	let statusFilter = $state('');
	let searchInput = $state('');
	let search = $state('');

	// Detay (accordion)
	let expandedId = $state<number | null>(null);
	let detail = $state<any>(null);
	let detailLoading = $state(false);
	let expandedInstallmentId = $state<number | null>(null);

	// Oluşturma modalı
	let showCreate = $state(false);
	let saving = $state(false);
	let formError = $state('');
	let fieldErrors = $state<Record<string, string>>({});
	type SHRow = { name: string; share_value: number | null };
	let form = $state<{
		name: string; decision_date: string; total_gross: number | null; capital: number | null;
		stopaj_pct: number | null; installment_count: number; year: number;
		first_installment_date: string; notes: string; shareholders: SHRow[];
	}>({
		name: '', decision_date: '', total_gross: null, capital: null, stopaj_pct: 15,
		installment_count: 6, year: new Date().getFullYear(), first_installment_date: '',
		notes: '', shareholders: [{ name: '', share_value: null }],
	});

	// Silme
	let deleteItem = $state<any>(null);
	let showDeleteConfirm = $state(false);

	// ── Formatlama ──
	function fmt(n: number | null | undefined): string {
		if (n == null) return '—';
		return `₺${n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
	}
	function fmtPct(ratio: number | null | undefined): string {
		if (ratio == null) return '—';
		return `%${(ratio * 100).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
	}
	function fmtDate(d: string | null): string {
		if (!d) return '—';
		return new Date(d + 'T00:00:00').toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}

	// ── Canlı önizleme (istemci tarafı; sunucu yeniden hesaplar) ──
	let preview = $derived.by(() => {
		const tg = form.total_gross || 0;
		const rate = (form.stopaj_pct || 0) / 100;
		const sumShare = form.shareholders.reduce((a, s) => a + (s.share_value || 0), 0);
		const denom = (form.capital && Math.abs(form.capital - sumShare) < 0.005) ? form.capital : sumShare;
		const rows = form.shareholders.map((s) => {
			const sv = s.share_value || 0;
			const ratio = denom > 0 ? sv / denom : 0;
			const gross = Math.round(tg * (denom > 0 ? sv / denom : 0) * 100) / 100;
			const stopaj = Math.round(gross * rate * 100) / 100;
			return { name: s.name, ratio, gross, stopaj, net: Math.round((gross - stopaj) * 100) / 100 };
		});
		return {
			rows,
			totalGross: rows.reduce((a, r) => a + r.gross, 0),
			totalStopaj: rows.reduce((a, r) => a + r.stopaj, 0),
			totalNet: rows.reduce((a, r) => a + r.net, 0),
		};
	});

	// ── Yıl seçici: dağıtımı olan yılları backend'den al, cari yıl ±1 penceresiyle birleştir
	// (boş modülde de kullanılabilir aralık kalsın; gelecekteki yıllar gizlenmesin). ──
	async function loadYears() {
		const cy = new Date().getFullYear();
		const base = [cy - 1, cy, cy + 1];
		try {
			const res = await api.get<any>('/accounting/dividend/years');
			const fromData: number[] = Array.isArray(res?.years) ? res.years : [];
			YEARS = Array.from(new Set([...base, ...fromData])).sort((a, b) => a - b);
		} catch (err) {
			console.error('Yıl listesi yüklenemedi:', err);
			YEARS = Array.from(new Set(base)).sort((a, b) => a - b);
		}
	}

	// ── Veri yükleme ──
	async function loadData() {
		loading = true;
		try {
			const params = new URLSearchParams();
			params.set('page', String(page));
			params.set('page_size', String(pageSize));
			if (yearFilter) params.set('year', yearFilter);
			if (statusFilter) params.set('status', statusFilter);
			if (search.trim()) params.set('search', search.trim());
			const data = await api.get<any>(`/accounting/dividend/?${params}`);
			distributions = data.items;
			total = data.total;
		} catch (err) {
			console.error('Temettü verileri yüklenemedi:', err);
			showToast('Temettü verileri yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	async function loadDetail(id: number) {
		detailLoading = true;
		try {
			detail = await api.get<any>(`/accounting/dividend/${id}`);
		} catch (err) {
			console.error('Dağıtım detayı yüklenemedi:', err);
			showToast('Dağıtım detayı yüklenemedi', 'error');
			detail = null;
		} finally {
			detailLoading = false;
		}
	}

	function toggleExpand(dist: any) {
		if (expandedId === dist.id) {
			expandedId = null;
			detail = null;
			expandedInstallmentId = null;
			return;
		}
		expandedId = dist.id;
		expandedInstallmentId = null;
		detail = null;
		loadDetail(dist.id);
	}

	// Detaydaki ödemeleri taksite göre grupla
	let paymentsByInstallment = $derived.by(() => {
		const m = new Map<number, any[]>();
		if (detail?.payments) {
			for (const p of detail.payments) {
				if (!m.has(p.installment_id)) m.set(p.installment_id, []);
				m.get(p.installment_id)!.push(p);
			}
		}
		return m;
	});

	// ── Oluşturma ──
	function openCreate() {
		form = {
			name: '', decision_date: '', total_gross: null, capital: null, stopaj_pct: 15,
			installment_count: 6, year: new Date().getFullYear(), first_installment_date: '',
			notes: '', shareholders: [{ name: '', share_value: null }],
		};
		formError = '';
		fieldErrors = {};
		showCreate = true;
	}
	function addShareholder() { form.shareholders = [...form.shareholders, { name: '', share_value: null }]; }
	function removeShareholder(i: number) {
		if (form.shareholders.length <= 1) return;
		form.shareholders = form.shareholders.filter((_, idx) => idx !== i);
	}

	function validate(): boolean {
		const e: Record<string, string> = {};
		if (!form.name.trim()) e.name = 'Dağıtım adı zorunludur';
		if (!form.total_gross || form.total_gross <= 0) e.total_gross = 'Dağıtılacak kâr payı sıfırdan büyük olmalıdır';
		if (!form.installment_count || form.installment_count < 1) e.installment_count = 'Taksit sayısı en az 1 olmalıdır';
		if (!form.first_installment_date) e.first_installment_date = 'İlk taksit tarihi zorunludur';
		const validSh = form.shareholders.filter((s) => s.name.trim() && (s.share_value || 0) > 0);
		if (validSh.length === 0) e.shareholders = 'En az bir pay sahibi (ad + pay değeri) girilmelidir';
		fieldErrors = e;
		return Object.keys(e).length === 0;
	}

	async function handleCreate() {
		if (!validate()) return;
		saving = true;
		formError = '';
		try {
			const payload = {
				name: form.name.trim(),
				decision_date: form.decision_date || null,
				total_gross: form.total_gross,
				capital: form.capital,
				withholding_rate: (form.stopaj_pct || 0) / 100,
				installment_count: form.installment_count,
				year: form.year,
				first_installment_date: form.first_installment_date,
				notes: form.notes || null,
				shareholders: form.shareholders
					.filter((s) => s.name.trim() && (s.share_value || 0) > 0)
					.map((s) => ({ name: s.name.trim(), share_value: s.share_value })),
			};
			const res = await api.post<any>('/accounting/dividend/', payload);
			showCreate = false;
			if (res?.requires_approval) {
				showToast('Dağıtım onay sürecine alındı', 'info');
			} else {
				showToast('Kâr payı dağıtımı oluşturuldu', 'success');
			}
			await loadData();
		} catch (err: any) {
			console.error('Dağıtım oluşturma hatası:', err);
			formError = err?.message || 'Kaydetme sırasında hata oluştu';
		} finally {
			saving = false;
		}
	}

	// ── Ödeme toggle ──
	async function togglePayment(payment: any, field: 'is_paid' | 'stopaj_paid', value: boolean) {
		try {
			const res = await api.patch<any>(`/accounting/dividend/payments/${payment.id}`, { [field]: value });
			if (res?.requires_approval) {
				showToast('Değişiklik onay sürecine alındı', 'info');
			} else if (expandedId) {
				await loadDetail(expandedId);
			}
		} catch (err: any) {
			console.error('Ödeme güncelleme hatası:', err);
			showToast(err?.message || 'Ödeme güncellenirken hata oluştu', 'error');
		}
	}

	// ── Silme / iptal ──
	function openDelete(dist: any) { deleteItem = dist; showDeleteConfirm = true; }
	async function confirmDelete() {
		if (!deleteItem) return;
		const item = deleteItem;
		try {
			const res = await api.delete<any>(`/accounting/dividend/${item.id}`);
			showToast(res?.requires_approval ? 'Silme onay sürecine alındı' : 'Dağıtım silindi', res?.requires_approval ? 'info' : 'success');
			if (expandedId === item.id) { expandedId = null; detail = null; }
			await loadData();
		} catch (err: any) {
			console.error('Dağıtım silme hatası:', err);
			showToast(err?.message || 'Silme sırasında hata oluştu', 'error');
		} finally {
			deleteItem = null;
		}
	}

	// Arama debounce
	let searchTimer: ReturnType<typeof setTimeout>;
	$effect(() => {
		const v = searchInput;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { search = v.trim(); }, 300);
		return () => clearTimeout(searchTimer);
	});

	let filterKey = $derived(`${yearFilter}|${statusFilter}|${search}`);
	let prevFilterKey = '';
	$effect(() => {
		const fk = filterKey;
		if (prevFilterKey && fk !== prevFilterKey) { page = 1; loadData(); }
		prevFilterKey = fk;
	});

	function changePage(p: number) { page = p; loadData(); }
	function changePageSize(s: number) { pageSize = s; page = 1; loadData(); }

	// Lifecycle
	let unsub: (() => void) | null = null;
	onMount(() => {
		loadYears();
		loadData();
		unsub = onWsEvent('finance_updated', (msg: any) => {
			if (!msg?.module || msg.module === 'accounting') {
				loadYears();
				loadData();
				if (expandedId) loadDetail(expandedId);
			}
		});
	});
	onDestroy(() => { unsub?.(); });
</script>

<svelte:head><title>Temettü · Sprenses</title></svelte:head>

<div class="space-y-5 sm:space-y-6">
	<PageHeader title="Temettü" description="Kâr payı dağıtımlarını, stopajı ve taksitli ödemeleri takip edin">
		{#snippet actions()}
			{#if canUse}
				<Button onclick={openCreate}><Plus size={16} /> Yeni Dağıtım</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<!-- Filtreler -->
	<div class="flex flex-col sm:flex-row gap-2 sm:gap-3 sm:items-center">
		<Input
			type="search" size="sm" icon={Search} clearable
			bind:value={searchInput} aria-label="Dağıtım ara"
			placeholder="Dağıtım adı ara…" class="sm:w-72"
		/>
		<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={yearFilter} aria-label="Yıla göre filtrele">
			<option value="">Tüm Yıllar</option>
			{#each YEARS as y (y)}<option value={String(y)}>{y}</option>{/each}
		</Select>
		<Select size="sm" fullWidth={false} class="flex-1 sm:flex-none" bind:value={statusFilter} aria-label="Duruma göre filtrele">
			<option value="">Tüm Durumlar</option>
			<option value="active">Aktif</option>
			<option value="cancelled">İptal</option>
		</Select>
		<span class="text-sm text-gray-500 sm:ml-auto">{total} dağıtım</span>
	</div>

	<!-- Liste -->
	<div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
		{#if loading}
			<TableSkeleton rows={4} columns={5} />
		{:else if distributions.length === 0}
			<EmptyState
				icon={Coins}
				title="Henüz kâr payı dağıtımı yok"
				description={search || yearFilter || statusFilter ? 'Filtrelere uygun dağıtım bulunamadı.' : "İlk dağıtımı eklemek için 'Yeni Dağıtım' butonunu kullanın."}
				ctaText={canUse && !(search || yearFilter || statusFilter) ? 'Yeni Dağıtım' : ''}
				onCta={canUse && !(search || yearFilter || statusFilter) ? openCreate : null}
			/>
		{:else}
			<div class="divide-y divide-gray-100">
				{#each distributions as dist (dist.id)}
					<div>
						<!-- Dağıtım satırı -->
						<button
							onclick={() => toggleExpand(dist)}
							class="w-full flex items-center gap-3 px-4 py-3.5 text-left hover:bg-gray-50 transition-colors cursor-pointer"
						>
							<ChevronRight size={18} class="text-gray-400 shrink-0 transition-transform {expandedId === dist.id ? 'rotate-90' : ''}" />
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2 flex-wrap">
									<span class="font-semibold text-gray-900">{dist.name}</span>
									<span class="text-xs text-gray-500">{dist.year}</span>
									<StatusBadge type={STATUS_BADGE[dist.status] ?? 'neutral'}>{STATUS_LABELS[dist.status] ?? dist.status}</StatusBadge>
								</div>
								<div class="text-xs text-gray-500 mt-0.5">
									{dist.shareholder_count} pay sahibi · {dist.installment_count} taksit ·
									Net ödeme {dist.net_paid_count}/{dist.net_total_count}
								</div>
							</div>
							<div class="text-right shrink-0 hidden sm:block">
								<div class="font-bold text-gray-900 tabular-nums">{fmt(dist.total_gross)}</div>
								<div class="text-xs text-gray-500">Brüt kâr payı</div>
							</div>
						</button>

						<!-- Genişletilmiş detay -->
						{#if expandedId === dist.id}
							<div class="px-4 pb-5 bg-gray-50/50">
								{#if detailLoading}
									<div class="py-4"><TableSkeleton rows={3} columns={4} /></div>
								{:else if detail}
									<!-- Özet kartları -->
									<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 pt-4 pb-4">
										<StatCard label="Toplam Brüt" value={fmt(detail.total_gross)} accent="teal" icon={Coins} />
										<StatCard label="Toplam Net" value={fmt(detail.total_net)} accent="emerald" icon={Banknote} />
										<StatCard label="Toplam Stopaj" value={fmt(detail.total_stopaj)} accent="amber" icon={Landmark} />
										<StatCard label="Net Ödeme" value={`${detail.net_paid_count}/${detail.net_total_count}`} accent="blue" icon={Check} hint="pay sahibi × taksit" />
									</div>

									<!-- Pay sahipleri -->
									<h3 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5"><Users size={15} /> Pay Sahipleri</h3>
									<div class="overflow-x-auto border border-gray-200 rounded-lg bg-white mb-5">
										<table class="w-full text-sm">
											<thead class="bg-gray-50 text-gray-600 text-xs">
												<tr>
													<th class="text-left font-medium px-3 py-2">Pay Sahibi</th>
													<th class="text-right font-medium px-3 py-2 hidden sm:table-cell">Pay Değeri</th>
													<th class="text-right font-medium px-3 py-2">Oran</th>
													<th class="text-right font-medium px-3 py-2">Brüt Kâr Payı</th>
													<th class="text-right font-medium px-3 py-2 hidden md:table-cell">Stopaj</th>
													<th class="text-right font-medium px-3 py-2">Net Kâr Payı</th>
												</tr>
											</thead>
											<tbody class="divide-y divide-gray-100">
												{#each detail.shareholders as s (s.id)}
													<tr class="hover:bg-gray-50/60">
														<td class="px-3 py-2 text-gray-800">{s.name}</td>
														<td class="px-3 py-2 text-right tabular-nums text-gray-600 hidden sm:table-cell">{fmt(s.share_value)}</td>
														<td class="px-3 py-2 text-right tabular-nums text-gray-600">{fmtPct(s.share_ratio)}</td>
														<td class="px-3 py-2 text-right tabular-nums text-gray-800">{fmt(s.gross_dividend)}</td>
														<td class="px-3 py-2 text-right tabular-nums text-amber-700 hidden md:table-cell">{fmt(s.stopaj_amount)}</td>
														<td class="px-3 py-2 text-right tabular-nums font-semibold text-emerald-700">{fmt(s.net_dividend)}</td>
													</tr>
												{/each}
											</tbody>
										</table>
									</div>

									<!-- Taksitler -->
									<h3 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5"><CalendarDays size={15} /> Taksitler</h3>
									<div class="space-y-2">
										{#each detail.installments as inst (inst.id)}
											<div class="border border-gray-200 rounded-lg bg-white overflow-hidden">
												<button
													onclick={() => expandedInstallmentId = expandedInstallmentId === inst.id ? null : inst.id}
													class="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-gray-50 cursor-pointer"
												>
													<ChevronRight size={16} class="text-gray-400 shrink-0 transition-transform {expandedInstallmentId === inst.id ? 'rotate-90' : ''}" />
													<div class="min-w-0 flex-1">
														<div class="flex items-center gap-2 flex-wrap">
															<span class="font-medium text-gray-800">{inst.installment_no}. Taksit</span>
															<span class="text-xs text-gray-500">{inst.label}</span>
															{#if inst.net_paid}<StatusBadge type="success">Net Ödendi</StatusBadge>{/if}
															{#if inst.stopaj_paid}<StatusBadge type="info">Stopaj Ödendi</StatusBadge>{/if}
														</div>
														<div class="text-xs text-gray-500 mt-0.5">
															Net {fmt(inst.net_amount)} · Stopaj {fmt(inst.stopaj_amount)} (muhtasar {fmtDate(inst.stopaj_due_date)})
															· ödenen {inst.paid_count}/{inst.total_count}
														</div>
													</div>
													<div class="text-right shrink-0 hidden sm:block tabular-nums font-semibold text-gray-800">{fmt(inst.gross_amount)}</div>
												</button>

												<!-- Pay sahibi × taksit ödeme satırları -->
												{#if expandedInstallmentId === inst.id}
													<div class="overflow-x-auto border-t border-gray-100">
														<table class="w-full text-sm">
															<thead class="bg-gray-50 text-gray-600 text-xs">
																<tr>
																	<th class="text-left font-medium px-3 py-2">Pay Sahibi</th>
																	<th class="text-right font-medium px-3 py-2">Net</th>
																	<th class="text-right font-medium px-3 py-2 hidden md:table-cell">Stopaj</th>
																	<th class="text-center font-medium px-3 py-2">Net Ödendi</th>
																	<th class="text-center font-medium px-3 py-2">Stopaj Ödendi</th>
																</tr>
															</thead>
															<tbody class="divide-y divide-gray-100">
																{#each (paymentsByInstallment.get(inst.id) ?? []) as p (p.id)}
																	<tr class="hover:bg-gray-50/60">
																		<td class="px-3 py-2 text-gray-800">{p.shareholder_name}</td>
																		<td class="px-3 py-2 text-right tabular-nums text-gray-800">{fmt(p.net_amount)}</td>
																		<td class="px-3 py-2 text-right tabular-nums text-amber-700 hidden md:table-cell">{fmt(p.stopaj_amount)}</td>
																		<td class="px-3 py-2 text-center">
																			<input
																				type="checkbox" checked={p.is_paid} disabled={!canUse}
																				onchange={(e) => togglePayment(p, 'is_paid', e.currentTarget.checked)}
																				aria-label={`${p.shareholder_name} net ödendi`}
																				class="w-4 h-4 accent-teal-700 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
																			/>
																		</td>
																		<td class="px-3 py-2 text-center">
																			<input
																				type="checkbox" checked={p.stopaj_paid} disabled={!canUse}
																				onchange={(e) => togglePayment(p, 'stopaj_paid', e.currentTarget.checked)}
																				aria-label={`${p.shareholder_name} stopaj ödendi`}
																				class="w-4 h-4 accent-teal-700 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
																			/>
																		</td>
																	</tr>
																{/each}
															</tbody>
														</table>
													</div>
												{/if}
											</div>
										{/each}
									</div>

									<!-- Aksiyonlar -->
									{#if canUse}
										<div class="flex justify-end pt-4">
											<Button variant="danger" size="sm" onclick={() => openDelete(dist)}><Trash2 size={15} /> Dağıtımı Sil</Button>
										</div>
									{/if}
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</div>

			{#if total > pageSize || page > 1}
				<div class="px-4 border-t border-gray-100">
					<Pagination {page} {pageSize} {total} onPageChange={changePage} onPageSizeChange={changePageSize} />
				</div>
			{/if}
		{/if}
	</div>
</div>

<!-- Oluşturma Modalı -->
<Modal bind:show={showCreate} title="Yeni Kâr Payı Dağıtımı" maxWidth="max-w-3xl">
	<form onsubmit={(e) => { e.preventDefault(); handleCreate(); }} class="space-y-4" novalidate>
		{#if formError}
			<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700" role="alert">{formError}</div>
		{/if}

		<Field label="Dağıtım Adı" required for="name" error={fieldErrors.name}>
			{#snippet children({ id, invalid, describedby })}
				<Input {id} {invalid} aria-describedby={describedby} bind:value={form.name} placeholder="ör. 2025 Kâr Payı Dağıtımı" />
			{/snippet}
		</Field>

		<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<Field label="Dağıtılacak Kâr Payı (Brüt)" required for="total_gross" error={fieldErrors.total_gross}>
				{#snippet children({ id, invalid, describedby })}
					<MoneyInput {id} ariaInvalid={invalid} ariaDescribedby={describedby} bind:value={form.total_gross} currency="TRY" min={0} placeholder="0,00" />
				{/snippet}
			</Field>
			<Field label="Sermaye / Pay İtibari Değeri" for="capital">
				{#snippet children({ id })}
					<MoneyInput {id} bind:value={form.capital} currency="TRY" min={0} placeholder="0,00" />
				{/snippet}
			</Field>
		</div>

		<div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
			<Field label="Stopaj (%)" for="stopaj_pct">
				{#snippet children({ id })}
					<MoneyInput {id} bind:value={form.stopaj_pct} min={0} max={100} decimals={2} placeholder="15" />
				{/snippet}
			</Field>
			<Field label="Taksit Sayısı" required for="installment_count" error={fieldErrors.installment_count}>
				{#snippet children({ id })}
					<Select {id} bind:value={form.installment_count}>
						{#each [1, 2, 3, 4, 6, 12] as n (n)}<option value={n}>{n}</option>{/each}
					</Select>
				{/snippet}
			</Field>
			<Field label="Yıl" for="year">
				{#snippet children({ id })}
					<Select {id} bind:value={form.year}>
						{#each YEARS as y (y)}<option value={y}>{y}</option>{/each}
					</Select>
				{/snippet}
			</Field>
			<Field label="Karar Tarihi" for="decision_date">
				{#snippet children({ id })}
					<Input {id} type="date" bind:value={form.decision_date} />
				{/snippet}
			</Field>
		</div>

		<Field label="İlk Taksit Tarihi (aylık ay-sonları)" required for="first_installment_date" error={fieldErrors.first_installment_date}>
			{#snippet children({ id, invalid, describedby })}
				<Input {id} {invalid} type="date" aria-describedby={describedby} bind:value={form.first_installment_date} />
			{/snippet}
		</Field>

		<!-- Pay sahipleri -->
		<div>
			<div class="flex items-center justify-between mb-2">
				<span class="text-sm font-medium text-gray-700">Pay Sahipleri <span class="text-red-600">*</span></span>
				<Button variant="secondary" size="sm" onclick={addShareholder}><Plus size={14} /> Ortak Ekle</Button>
			</div>
			{#if fieldErrors.shareholders}<p class="text-xs text-red-600 mb-2">{fieldErrors.shareholders}</p>{/if}
			<div class="space-y-2">
				{#each form.shareholders as sh, i (i)}
					<div class="flex items-center gap-2">
						<Input bind:value={sh.name} placeholder="Pay sahibi adı" class="flex-1" aria-label={`Pay sahibi ${i + 1} adı`} />
						<div class="w-40 shrink-0">
							<MoneyInput bind:value={sh.share_value} currency="TRY" min={0} placeholder="Pay değeri" />
						</div>
						<button
							type="button" onclick={() => removeShareholder(i)}
							disabled={form.shareholders.length <= 1}
							aria-label="Pay sahibini kaldır"
							class="p-2 text-red-600 hover:bg-red-50 rounded-lg cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
						><X size={16} /></button>
					</div>
				{/each}
			</div>
		</div>

		<!-- Canlı önizleme -->
		{#if preview.rows.some((r) => r.gross > 0)}
			<div class="border border-gray-200 rounded-lg bg-gray-50/60 overflow-x-auto">
				<table class="w-full text-xs">
					<thead class="text-gray-600">
						<tr>
							<th class="text-left font-medium px-3 py-2">Önizleme</th>
							<th class="text-right font-medium px-3 py-2">Oran</th>
							<th class="text-right font-medium px-3 py-2">Brüt</th>
							<th class="text-right font-medium px-3 py-2">Stopaj</th>
							<th class="text-right font-medium px-3 py-2">Net</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-100">
						{#each preview.rows as r}
							<tr>
								<td class="px-3 py-1.5 text-gray-700">{r.name || '—'}</td>
								<td class="px-3 py-1.5 text-right tabular-nums text-gray-600">{fmtPct(r.ratio)}</td>
								<td class="px-3 py-1.5 text-right tabular-nums text-gray-700">{fmt(r.gross)}</td>
								<td class="px-3 py-1.5 text-right tabular-nums text-amber-700">{fmt(r.stopaj)}</td>
								<td class="px-3 py-1.5 text-right tabular-nums font-semibold text-emerald-700">{fmt(r.net)}</td>
							</tr>
						{/each}
					</tbody>
					<tfoot class="border-t-2 border-gray-200 bg-white">
						<tr class="font-semibold text-gray-800">
							<td class="px-3 py-2">TOPLAM</td>
							<td></td>
							<td class="px-3 py-2 text-right tabular-nums">{fmt(preview.totalGross)}</td>
							<td class="px-3 py-2 text-right tabular-nums text-amber-700">{fmt(preview.totalStopaj)}</td>
							<td class="px-3 py-2 text-right tabular-nums text-emerald-700">{fmt(preview.totalNet)}</td>
						</tr>
					</tfoot>
				</table>
			</div>
		{/if}

		<Field label="Notlar" for="notes">
			{#snippet children({ id })}
				<Textarea {id} bind:value={form.notes} rows={2} placeholder="İsteğe bağlı notlar" />
			{/snippet}
		</Field>

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="secondary" onclick={() => showCreate = false}>İptal</Button>
			<Button type="submit" loading={saving}>Oluştur</Button>
		</div>
	</form>
</Modal>

<!-- Silme Onayı -->
<ConfirmDialog
	bind:show={showDeleteConfirm}
	title="Dağıtımı Sil"
	message={deleteItem ? `"${deleteItem.name}" kâr payı dağıtımını ve tüm taksit/ödeme kayıtlarını silmek istediğinize emin misiniz?` : ''}
	confirmText="Sil"
	cancelText="Vazgeç"
	danger
	onConfirm={confirmDelete}
/>
