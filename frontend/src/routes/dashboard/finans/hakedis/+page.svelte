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
	import { Receipt, AlarmClock, Wallet, Scale, Pencil, Search, ChevronDown, ChevronRight, Users } from 'lucide-svelte';

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
	let collectionsByFirm = $state<Record<string, any[]>>({});
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
	// Firma tek para birimliyse native (€), karışıksa TL karşılığı (fatura tarihi kuru)
	function money(f: any, field: 'open' | 'overdue' | 'advance' | 'net_open' | 'collected'): string {
		if (f.display_currency) {
			const sym = CURRENCY_SYMBOLS[f.display_currency] ?? f.display_currency;
			return `${sym}${fmt(f[`${field}_native`])}`;
		}
		return `₺${fmt(f[`${field}_tl`])}`;
	}
	// Tahsilat kolonu: firma birimi cinsinden; o birimde hiç tahsilat yoksa
	// (ör. EUR faturalı firmaya yalnız TL EFT gelmiş) TL karşılığı gösterilir — "€0,00" yanıltmasın
	function collectedDisplay(f: any): string {
		if (f.display_currency && (f.collected_native ?? 0) > 0) {
			const sym = CURRENCY_SYMBOLS[f.display_currency] ?? f.display_currency;
			return `${sym}${fmt(f.collected_native)}`;
		}
		return `₺${fmt(f.collected_tl)}`;
	}
	// Eşlenmemiş tahsilat havuzu rozet metni: "₺213.959" / birden çok birimde "₺X + €Y"
	function unappliedLabel(f: any): string {
		const byCur = f.unapplied_by_currency || {};
		return Object.entries(byCur)
			.map(([c, v]) => `${CURRENCY_SYMBOLS[c] ?? c}${fmt(v as number)}`)
			.join(' + ');
	}
	function currencyBreakdown(byCur: Record<string, number> | undefined): string {
		if (!byCur) return '';
		return Object.entries(byCur)
			.sort((a, b) => b[1] - a[1])
			.map(([c, v]) => `${CURRENCY_SYMBOLS[c] ?? c}${fmt(v)}`)
			.join(' + ');
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
		if (expanded[code] && (!invoicesByFirm[code] || !collectionsByFirm[code])) {
			invoiceLoading[code] = true;
			try {
				const [inv, col] = await Promise.all([
					api.get<any>(`/finance/hakedis/firms/${encodeURIComponent(code)}/invoices`),
					api.get<any>(`/finance/hakedis/firms/${encodeURIComponent(code)}/collections`),
				]);
				invoicesByFirm[code] = inv.items || [];
				collectionsByFirm[code] = col.items || [];
			} catch (err) {
				console.error('Firma detayı yüklenemedi:', err);
				showToast('Firma detayı yüklenemedi', 'error');
				expanded[code] = false;
			} finally {
				invoiceLoading[code] = false;
			}
		}
	}

	// CRUD — vade tanımı
	function openTermEdit(firm: any) {
		termFirm = firm;
		termDays = firm.term_days ?? 30; // grup "karma" ise 30'dan başla
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
			// Grup satırında vade TÜM üye firmalara uygulanır (her kod kendi onay kontrolünden geçer)
			const codes: string[] = termFirm.is_group
				? termFirm.members.map((m: any) => m.code)
				: [termFirm.code];
			let approvals = 0;
			for (const code of codes) {
				const resp: any = await api.patch(`/finance/hakedis/terms/${encodeURIComponent(code)}`, {
					term_days: termDays, notes: termNotes || null
				});
				if (resp?.approval_required || resp?.request_id) approvals++;
			}
			if (approvals > 0) {
				showToast(`${approvals} vade değişikliği onaya gönderildi`, 'info');
			} else {
				showToast(codes.length > 1 ? `${codes.length} firmanın vadesi güncellendi` : 'Vade güncellendi', 'success');
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
		hint={`${currencyBreakdown(summary?.open_by_currency)} · ${summary?.firm_count ?? 0} firma/grup`} />
	<StatCard label="Alınan Avans (eşlenen)" value={`₺${fmt(summary?.advance_tl ?? 0)}`} icon={Wallet} accent="blue"
		hint={`340 hesabı, güncel kurla${(summary?.unapplied_tl ?? 0) > 0 ? ` · ₺${fmt(summary.unapplied_tl)} eşlenmemiş tahsilat` : ''}`} />
	<StatCard label="Net Açık (avans sonrası)" value={`₺${fmt(summary?.net_open_tl ?? 0)}`} icon={Scale} accent="teal" />
	<StatCard label="Vadesi Geçen" value={`₺${fmt(summary?.overdue_tl ?? 0)}`} icon={AlarmClock} accent="red"
		hint={`${summary?.overdue_firm_count ?? 0} firma · 7 gün içinde ₺${fmt(summary?.due_7d_tl ?? 0)}`} />
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
	<TableSkeleton rows={6} columns={8} />
{:else if filteredFirms.length === 0}
	<EmptyState icon={Receipt} title="Açık hak ediş bulunamadı"
		description={searchDebounced || onlyOverdue ? 'Filtreyle eşleşen firma yok.' : 'Tüm acente faturaları tahsil edilmiş görünüyor.'} />
{:else}
	<!-- Masaüstü tablo — 10 kolon geniş: yatay kaydırma (overflow-x-auto), kolonlar ezilmesin (min-w) -->
	<div class="hidden sm:block bg-white border border-gray-200 rounded-2xl shadow-sm overflow-x-auto">
		<table class="w-full min-w-[1280px] text-sm">
			<thead>
				<tr class="border-b border-gray-200 text-left text-gray-600">
					<th class="px-4 py-3 w-8"></th>
					<th class="px-4 py-3">Firma / Grup</th>
					<th class="px-4 py-3">Vade</th>
					<th class="px-4 py-3 text-right">Açık Tutar</th>
					<th class="px-4 py-3 text-right">Tahsilat</th>
					<th class="px-4 py-3 text-right">Avans</th>
					<th class="px-4 py-3 text-right">Net Açık</th>
					<th class="px-4 py-3 text-right">Vadesi Geçen</th>
					<th class="px-4 py-3">Gecikme</th>
					<th class="px-4 py-3 text-right">Fatura</th>
				</tr>
			</thead>
			<tbody>
				{#each filteredFirms as f (f.code)}
					<tr class="border-b border-gray-100 hover:bg-gray-50 group cursor-pointer" onclick={() => toggleExpand(f.code)}>
						<td class="px-4 py-3 text-gray-500">
							{#if expanded[f.code]}<ChevronDown size={16} />{:else}<ChevronRight size={16} />{/if}
						</td>
						<td class="px-4 py-3 max-w-[300px]">
							<div class="font-medium text-gray-900 flex items-center gap-2">
								<span class="truncate" title={f.name || f.code}>{f.name || f.code}</span>
								{#if f.is_group}
									<span class="shrink-0 inline-flex items-center gap-1 text-xs font-normal text-teal-700 bg-teal-50 border border-teal-200 rounded-full px-2 py-0.5">
										<Users size={11} /> Grup · {f.members.length} firma
									</span>
								{/if}
							</div>
							<div class="text-xs text-gray-500 font-mono truncate"
								title={f.is_group ? f.members.map((m: any) => m.code).join(' · ') : f.code}>
								{f.is_group ? f.members.map((m: any) => m.code).join(' · ') : f.code} · {f.currencies.join(', ')}
							</div>
						</td>
						<td class="px-4 py-3">
							<span class="inline-flex items-center gap-1.5">
								<span class="tabular-nums">{f.term_days === null ? 'karma' : `${f.term_days} gün`}</span>
								{#if f.is_default_term && f.term_days !== null}<span class="text-xs text-gray-500">(varsayılan)</span>{/if}
								{#if canUse}
									<button type="button" aria-label={`${f.name || f.code} vadesini düzenle`}
										onclick={(e) => { e.stopPropagation(); openTermEdit(f); }}
										class="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-teal-700 touch-target">
										<Pencil size={14} />
									</button>
								{/if}
							</span>
						</td>
						<td class="px-4 py-3 text-right tabular-nums" title={f.display_currency ? `TL karşılığı (fatura tarihi kuru): ₺${fmt(f.open_tl)}` : undefined}>
							{money(f, 'open')}
						</td>
						<td class="px-4 py-3 text-right"
							title={`${f.collection_count} tahsilat kaydı · toplam TL karşılığı ₺${fmt(f.collected_tl)}`}>
							{#if f.collected_tl > 0}
								<div class="tabular-nums text-green-700">{collectedDisplay(f)}</div>
								{#if f.last_collection_date}
									<div class="text-[11px] text-gray-500">son: {fmtDate(f.last_collection_date)}</div>
								{/if}
							{:else}
								<span class="text-gray-500" title="Bu firmadan hiç tahsilat kaydı yok">—</span>
							{/if}
							{#if f.unapplied_tl > 0}
								<div class="mt-0.5">
									<span class="inline-block text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5"
										title="Fatura para birimiyle eşleşmeyen (veya faturaları aşan) tahsilat — açık tutardan DÜŞÜLMEMİŞTİR">
										{unappliedLabel(f)} eşlenmemiş
									</span>
								</div>
							{/if}
						</td>
						<td class="px-4 py-3 text-right tabular-nums {f.advance_tl > 0 ? 'text-blue-700' : 'text-gray-500'}">
							{f.advance_tl > 0 ? money(f, 'advance') : '—'}
						</td>
						<td class="px-4 py-3 text-right tabular-nums font-semibold {f.net_open_tl > 0 ? 'text-gray-900' : 'text-green-700'}">
							{money(f, 'net_open')}
						</td>
						<td class="px-4 py-3 text-right tabular-nums {f.overdue_tl > 0 ? 'text-red-600 font-semibold' : 'text-gray-500'}">
							{f.overdue_tl > 0 ? money(f, 'overdue') : '—'}
						</td>
						<td class="px-4 py-3">
							<StatusBadge type={overdueBadge(f.max_overdue_days)}>
								{f.max_overdue_days > 0 ? `${f.max_overdue_days} gün` : 'Vadesinde'}
							</StatusBadge>
						</td>
						<td class="px-4 py-3 text-right tabular-nums text-gray-700">{f.invoice_count}</td>
					</tr>
					{#if expanded[f.code]}
						<tr class="border-b border-gray-100 bg-gray-50/60">
							<td colspan="10" class="px-6 py-3">
								{#if invoiceLoading[f.code]}
									<TableSkeleton rows={3} columns={6} />
								{:else}
									<div class="text-xs font-semibold text-gray-700 mb-1.5">
										Açık Faturalar ({(invoicesByFirm[f.code] || []).length})
									</div>
									<table class="w-full text-xs">
										<thead>
											<tr class="text-left text-gray-600">
												{#if f.is_group}<th class="py-1.5 pr-3">Firma</th>{/if}
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
													{#if f.is_group}
														<td class="py-1.5 pr-3 text-gray-700">{(inv.customer_name || inv.customer_code || '').slice(0, 26)}</td>
													{/if}
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

									<!-- Tahsilat dökümü — "bu firmadan hiç tahsilat yapılmış mı?" kanıtı -->
									<div class="mt-4 pt-3 border-t border-gray-200">
										{#if (collectionsByFirm[f.code] || []).length > 0}
											<div class="text-xs font-semibold text-gray-700 mb-1.5">
												Tahsilatlar ({(collectionsByFirm[f.code] || []).length})
											</div>
											<table class="w-full text-xs">
												<thead>
													<tr class="text-left text-gray-600">
														<th class="py-1.5 pr-3">Tarih</th>
														{#if f.is_group}<th class="py-1.5 pr-3">Firma</th>{/if}
														<th class="py-1.5 pr-3 text-right">Tutar</th>
														<th class="py-1.5 pr-3 text-right">TL Karşılığı</th>
														<th class="py-1.5 pr-3">Açıklama</th>
													</tr>
												</thead>
												<tbody>
													{#each collectionsByFirm[f.code] || [] as col (col.id)}
														<tr class="border-t border-gray-100">
															<td class="py-1.5 pr-3 tabular-nums">{fmtDate(col.collection_date)}</td>
															{#if f.is_group}
																<td class="py-1.5 pr-3 text-gray-700">{(col.customer_name || col.customer_code || '').slice(0, 26)}</td>
															{/if}
															<td class="py-1.5 pr-3 text-right tabular-nums font-medium text-green-700">
																{CURRENCY_SYMBOLS[col.currency] ?? col.currency}{fmt(col.amount)}
															</td>
															<td class="py-1.5 pr-3 text-right tabular-nums text-gray-600">₺{fmt(col.amount_tl)}</td>
															<td class="py-1.5 pr-3 text-gray-600 max-w-[360px] truncate" title={col.description}>{col.description || '—'}</td>
														</tr>
													{/each}
												</tbody>
											</table>
										{:else}
											<p class="text-xs text-gray-500">Bu firmadan henüz hiç tahsilat kaydı yok.</p>
										{/if}
										{#if f.unapplied_tl > 0}
											<p class="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
												<strong>{unappliedLabel(f)}</strong> tutarında tahsilat, firmanın fatura para birimiyle
												eşleşmediği (veya faturaları aştığı) için hiçbir faturaya mahsup edilemedi —
												yukarıdaki açık tutardan <strong>düşülmemiştir</strong>.
											</p>
										{/if}
									</div>
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
						<div class="text-xs text-gray-500 font-mono">
							{f.is_group ? `Grup · ${f.members.length} firma` : f.code}
						</div>
					</div>
					<StatusBadge type={overdueBadge(f.max_overdue_days)}>
						{f.max_overdue_days > 0 ? `${f.max_overdue_days} gün` : 'Vadesinde'}
					</StatusBadge>
				</div>
				<div class="mt-3 grid grid-cols-2 gap-2 text-sm">
					<div><span class="text-gray-500">Açık:</span> <span class="tabular-nums">{money(f, 'open')}</span></div>
					<div><span class="text-gray-500">Tahsilat:</span>
						<span class="tabular-nums {f.collected_tl > 0 ? 'text-green-700' : 'text-gray-500'}">
							{f.collected_tl > 0 ? collectedDisplay(f) : '—'}</span>
						{#if f.last_collection_date}<span class="text-xs text-gray-500">(son {fmtDate(f.last_collection_date)})</span>{/if}
					</div>
					<div><span class="text-gray-500">Avans:</span> <span class="tabular-nums text-blue-700">{money(f, 'advance')}</span></div>
					<div><span class="text-gray-500">Net Açık:</span> <span class="tabular-nums font-semibold">{money(f, 'net_open')}</span></div>
					<div><span class="text-gray-500">Geciken:</span>
						<span class="tabular-nums {f.overdue_tl > 0 ? 'text-red-600 font-semibold' : ''}">{money(f, 'overdue')}</span></div>
					<div><span class="text-gray-500">Vade:</span> {f.term_days === null ? 'karma' : `${f.term_days} gün${f.is_default_term ? ' (vars.)' : ''}`}</div>
				</div>
				{#if f.unapplied_tl > 0}
					<div class="mt-2">
						<span class="inline-block text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
							{unappliedLabel(f)} eşlenmemiş tahsilat — açık tutardan düşülmedi
						</span>
					</div>
				{/if}
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
		{#if termFirm?.is_group}
			<p class="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
				Bu bir grup: vade, gruptaki <strong>{termFirm.members.length} firmanın tümüne</strong> uygulanacak
				({termFirm.members.map((m: any) => m.code).join(', ')}).
			</p>
		{/if}
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
