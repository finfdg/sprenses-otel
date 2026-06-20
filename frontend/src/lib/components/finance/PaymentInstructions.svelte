<script lang="ts">
	import { api, ApiError } from '$lib/api';
	import MoneyInput from '$lib/components/MoneyInput.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Button from '$lib/components/Button.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { FileText, Plus, Trash2, Download, Search, X } from 'lucide-svelte';

	let { canUse = false }: { canUse?: boolean } = $props();

	// ───── Tipler ─────────────────────────────────────────
	type PiItem = {
		id: number;
		vendor_id: number | null;
		hesap_kodu: string | null;
		hesap_adi: string;
		amount: number;
		balance_snapshot: number | null;
		notes: string | null;
		sort_order: number;
		bank_name: string | null;
		iban: string | null;
	};
	type PiList = {
		id: number;
		name: string;
		description: string | null;
		status: string;
		item_count: number;
		total_amount: number;
		creator_name: string | null;
		created_at: string | null;
		items: PiItem[];
	};
	type VendorHit = {
		id: number;
		hesap_kodu: string;
		hesap_adi: string;
		bakiye: number;
	};

	// ───── State ──────────────────────────────────────────
	let lists = $state<PiList[]>([]);
	let activeList = $state<PiList | null>(null);
	let loading = $state(true);
	let busy = $state(false);

	// Yeni liste modal
	let showNewModal = $state(false);
	let newName = $state('');

	// Cari arama
	let searchTerm = $state('');
	let searchResults = $state<VendorHit[]>([]);
	let searching = $state(false);
	let searchTimer: ReturnType<typeof setTimeout> | null = null;

	// Silme onayı
	let confirmDelete = $state<{ show: boolean; kind: 'list' | 'item'; id: number | null; label: string }>(
		{ show: false, kind: 'list', id: null, label: '' },
	);

	const activeTotal = $derived(
		activeList ? activeList.items.reduce((s, it) => s + (it.amount || 0), 0) : 0,
	);

	// ───── Formatlama ─────────────────────────────────────
	function fmt(n: number): string {
		return new Intl.NumberFormat('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0);
	}
	function fmtDate(iso: string | null): string {
		if (!iso) return '-';
		const d = new Date(iso);
		return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;
	}

	// ───── Veri ───────────────────────────────────────────
	async function loadLists() {
		loading = true;
		try {
			lists = await api.get<PiList[]>('/finance/payment-instructions/');
		} catch (e) {
			console.error('Talimat listeleri alınamadı:', e);
			showToast('Talimat listeleri alınamadı', 'error');
		} finally {
			loading = false;
		}
	}

	async function openList(id: number) {
		try {
			activeList = await api.get<PiList>(`/finance/payment-instructions/${id}`);
		} catch (e) {
			console.error('Liste açılamadı:', e);
			showToast('Liste açılamadı', 'error');
		}
	}

	// ───── Liste CRUD ─────────────────────────────────────
	function openNewModal() {
		newName = `Ödeme Talimatı ${new Date().toLocaleDateString('tr-TR')}`;
		showNewModal = true;
	}

	async function createList() {
		const name = newName.trim();
		if (!name) {
			showToast('Liste adı zorunludur', 'warning');
			return;
		}
		busy = true;
		try {
			const created = await api.post<PiList>('/finance/payment-instructions/', { name, items: [] });
			showNewModal = false;
			await loadLists();
			activeList = created;
			showToast('Talimat listesi oluşturuldu', 'success');
		} catch (e) {
			console.error('Liste oluşturulamadı:', e);
			showToast(e instanceof ApiError ? e.message : 'Liste oluşturulamadı', 'error');
		} finally {
			busy = false;
		}
	}

	function askDeleteList() {
		if (!activeList) return;
		confirmDelete = { show: true, kind: 'list', id: activeList.id, label: activeList.name };
	}

	async function doDelete() {
		if (confirmDelete.id == null) return;
		try {
			if (confirmDelete.kind === 'list') {
				await api.delete(`/finance/payment-instructions/${confirmDelete.id}`);
				activeList = null;
				await loadLists();
				showToast('Liste silindi', 'success');
			} else if (activeList) {
				await api.delete(`/finance/payment-instructions/${activeList.id}/items/${confirmDelete.id}`);
				activeList.items = activeList.items.filter((it) => it.id !== confirmDelete.id);
				await loadLists();
			}
		} catch (e) {
			console.error('Silme hatası:', e);
			showToast('Silinemedi', 'error');
		} finally {
			confirmDelete = { show: false, kind: 'list', id: null, label: '' };
		}
	}

	// ───── Cari arama + ekleme ────────────────────────────
	function onSearchInput() {
		if (searchTimer) clearTimeout(searchTimer);
		const q = searchTerm.trim();
		if (q.length < 2) {
			searchResults = [];
			return;
		}
		searchTimer = setTimeout(() => runSearch(q), 300);
	}

	async function runSearch(q: string) {
		searching = true;
		try {
			const res = await api.get<any>(`/finance/cariler/vendors?search=${encodeURIComponent(q)}&page_size=15`);
			const existingIds = new Set((activeList?.items || []).map((it) => it.vendor_id));
			searchResults = (res.items || []).filter((v: VendorHit) => !existingIds.has(v.id));
		} catch (e) {
			console.error('Cari arama hatası:', e);
		} finally {
			searching = false;
		}
	}

	async function addVendor(v: VendorHit) {
		if (!activeList) return;
		// Negatif bakiye = bizim borcumuz (ödenecek). Pozitifse 0 başlat.
		const payAmount = v.bakiye < 0 ? Math.abs(v.bakiye) : 0;
		try {
			const updated = await api.post<any>(`/finance/payment-instructions/${activeList.id}/items`, {
				items: [{
					vendor_id: v.id,
					hesap_kodu: v.hesap_kodu,
					hesap_adi: v.hesap_adi,
					amount: payAmount,
					balance_snapshot: v.bakiye,
				}],
			});
			activeList = updated;
			searchResults = searchResults.filter((r) => r.id !== v.id);
			searchTerm = '';
			searchResults = [];
			await loadLists();
		} catch (e) {
			console.error('Cari eklenemedi:', e);
			showToast('Cari eklenemedi', 'error');
		}
	}

	// ───── Tutar düzenleme (debounce'lu kaydet) ───────────
	let saveTimers = new Map<number, ReturnType<typeof setTimeout>>();
	function scheduleSave(item: PiItem) {
		const existing = saveTimers.get(item.id);
		if (existing) clearTimeout(existing);
		saveTimers.set(item.id, setTimeout(() => persistAmount(item), 600));
	}

	async function persistAmount(item: PiItem) {
		if (!activeList) return;
		try {
			await api.patch(`/finance/payment-instructions/${activeList.id}/items/${item.id}`, {
				amount: item.amount ?? 0,
			});
			await loadLists();
		} catch (e) {
			console.error('Tutar güncellenemedi:', e);
			showToast('Tutar güncellenemedi', 'error');
		}
	}

	function askDeleteItem(item: PiItem) {
		confirmDelete = { show: true, kind: 'item', id: item.id, label: item.hesap_adi };
	}

	// ───── Banka / IBAN seçimi ────────────────────────────
	let ibanMenuId = $state<number | null>(null);
	let ibanOpts = $state<Array<{ id: number; bank_name: string | null; iban: string; is_default: boolean }>>([]);
	let ibanLoading = $state(false);
	function fmtIban(s: string | null): string {
		const v = (s || '').replace(/\s+/g, '');
		return v ? (v.match(/.{1,4}/g) || []).join(' ') : '';
	}
	async function openIban(item: PiItem) {
		if (!item.vendor_id) { showToast('Bu kalemin carisi yok — IBAN seçilemez', 'info'); return; }
		if (ibanMenuId === item.id) { ibanMenuId = null; return; }
		ibanMenuId = item.id; ibanOpts = []; ibanLoading = true;
		try {
			ibanOpts = await api.get(`/finance/cariler/vendors/${item.vendor_id}/bank-accounts`);
		} catch (e) {
			console.error('IBAN listesi alınamadı:', e);
			showToast('IBAN listesi alınamadı', 'error');
		} finally {
			ibanLoading = false;
		}
	}
	async function pickIban(item: PiItem, ba: { bank_name: string | null; iban: string } | null) {
		if (!activeList) return;
		try {
			await api.patch(`/finance/payment-instructions/${activeList.id}/items/${item.id}`, {
				bank_name: ba?.bank_name ?? null,
				iban: ba?.iban ?? null,
			});
			item.bank_name = ba?.bank_name ?? null;
			item.iban = ba?.iban ?? null;
			ibanMenuId = null;
		} catch (e) {
			console.error('IBAN güncellenemedi:', e);
			showToast('IBAN güncellenemedi', 'error');
		}
	}

	// ───── Dışa aktarma ───────────────────────────────────
	async function download(kind: 'excel' | 'pdf' | 'ykb-excel', debtorAccount = '') {
		if (!activeList) return;
		busy = true;
		try {
			const path =
				kind === 'ykb-excel'
					? `/finance/payment-instructions/${activeList.id}/export/ykb-excel?debtor_account=${encodeURIComponent(debtorAccount)}`
					: `/finance/payment-instructions/${activeList.id}/export/${kind}`;
			const res = await api.fetchRaw(path);
			if (!res.ok) throw new Error('İndirme başarısız');
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download =
				kind === 'ykb-excel'
					? `ykb-toplu-odeme-${activeList.id}.xlsx`
					: `odeme-talimati-${activeList.id}.${kind === 'excel' ? 'xlsx' : 'pdf'}`;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			URL.revokeObjectURL(url);
		} catch (e) {
			console.error('İndirme hatası:', e);
			showToast('Dosya indirilemedi', 'error');
		} finally {
			busy = false;
		}
	}

	// ───── Yapı Kredi toplu ödeme export'u ────────────────
	let ykbModalOpen = $state(false);
	let ykbDebtor = $state('');

	function openYkbExport() {
		try {
			ykbDebtor = localStorage.getItem('ykb_debtor_account') || '';
		} catch (e) {
			console.error('localStorage okunamadı:', e);
			ykbDebtor = '';
		}
		ykbModalOpen = true;
	}

	async function confirmYkbExport() {
		const deb = ykbDebtor.trim();
		try {
			localStorage.setItem('ykb_debtor_account', deb);
		} catch (e) {
			console.error('localStorage yazılamadı:', e);
		}
		ykbModalOpen = false;
		await download('ykb-excel', deb);
	}

	// İlk yükleme
	loadLists();
</script>

<div class="space-y-4">
	<!-- Üst bar: liste seçimi + yeni -->
	<div class="flex items-center gap-2 flex-wrap">
		<Select
			value={activeList?.id ?? ''}
			onchange={(e) => {
				const v = (e.target as HTMLSelectElement).value;
				if (v) openList(Number(v));
				else activeList = null;
			}}
			size="sm"
			fullWidth={false}
			class="flex-1 sm:flex-none sm:min-w-[280px]"
		>
			<option value="">— Liste seçin —</option>
			{#each lists as l (l.id)}
				<option value={l.id}>{l.name} ({l.item_count} cari · ₺{fmt(l.total_amount)})</option>
			{/each}
		</Select>
		{#if canUse}
			<Button onclick={openNewModal}>
				<Plus size={16} /> Yeni Liste
			</Button>
		{/if}
		{#if activeList && canUse}
			<Button variant="danger" onclick={askDeleteList}>
				<Trash2 size={16} /> Listeyi Sil
			</Button>
		{/if}
	</div>

	{#if loading}
		<TableSkeleton rows={5} columns={4} />
	{:else if !activeList}
		<EmptyState
			icon={FileText}
			title="Ödeme talimat listesi seçilmedi"
			description={lists.length === 0 ? 'Henüz liste yok. Yeni bir liste oluşturup cari ekleyin.' : 'Yukarıdan bir liste seçin veya yeni oluşturun.'}
		/>
	{:else}
		<!-- Aktif liste -->
		<div class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
			<!-- Başlık + toplam + indirme -->
			<div class="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-100 bg-gray-50/60 flex-wrap">
				<div>
					<div class="font-semibold text-gray-800">{activeList.name}</div>
					<div class="text-xs text-gray-500">{activeList.items.length} cari · {fmtDate(activeList.created_at)}</div>
				</div>
				<div class="flex items-center gap-3 flex-wrap">
					<div class="text-right">
						<div class="text-[10px] text-gray-500 uppercase">Toplam</div>
						<div class="text-lg font-bold text-rose-600 tabular-nums">₺{fmt(activeTotal)}</div>
					</div>
					<button onclick={() => download('excel')} disabled={busy || activeList.items.length === 0}
						class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-700 rounded-lg hover:bg-emerald-100 text-xs font-medium disabled:opacity-50">
						<Download size={14} /> Excel
					</button>
					<button onclick={openYkbExport} disabled={busy || activeList.items.length === 0}
						title="Yapı Kredi toplu ödeme yükleme formatı"
						class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 text-xs font-medium disabled:opacity-50">
						<Download size={14} /> Excel (Yapı Kredi)
					</button>
					<button onclick={() => download('pdf')} disabled={busy || activeList.items.length === 0}
						class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 text-rose-700 rounded-lg hover:bg-rose-100 text-xs font-medium disabled:opacity-50">
						<Download size={14} /> PDF
					</button>
				</div>
			</div>

			<!-- Cari ekleme arama -->
			{#if canUse}
				<div class="px-4 py-3 border-b border-gray-100 relative">
					<div class="relative">
						<Input
							type="search"
							icon={Search}
							size="sm"
							bind:value={searchTerm}
							oninput={onSearchInput}
							placeholder="Cari ekle — hesap kodu veya ad ara…"
							style="padding-right:2.25rem"
						/>
						{#if searchTerm}
							<button onclick={() => { searchTerm = ''; searchResults = []; }} class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-600 z-10">
								<X size={16} />
							</button>
						{/if}
					</div>
					{#if searchResults.length > 0}
						<div class="absolute left-4 right-4 z-20 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-y-auto">
							{#each searchResults as v (v.id)}
								<button
									onclick={() => addVendor(v)}
									class="w-full flex items-center justify-between gap-2 px-3 py-2 hover:bg-teal-50 text-left text-sm border-b border-gray-50 last:border-0"
								>
									<span class="min-w-0">
										<span class="font-medium text-gray-800 truncate block">{v.hesap_adi}</span>
										<span class="text-xs text-gray-500">{v.hesap_kodu}</span>
									</span>
									<span class="text-xs font-semibold tabular-nums shrink-0 {v.bakiye < 0 ? 'text-rose-600' : 'text-gray-500'}">
										{v.bakiye < 0 ? '₺' + fmt(Math.abs(v.bakiye)) : '₺0,00'}
									</span>
								</button>
							{/each}
						</div>
					{:else if searching}
						<div class="text-xs text-gray-500 mt-1 pl-1">Aranıyor…</div>
					{/if}
				</div>
			{/if}

			<!-- Kalemler -->
			{#if activeList.items.length === 0}
				<p class="text-sm text-gray-500 text-center py-8">Henüz cari eklenmedi. Yukarıdan arayıp ekleyin.</p>
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="text-xs text-gray-500 border-b border-gray-100">
								<th class="text-left py-2 px-3 w-8">#</th>
								<th class="text-left py-2 px-3 hidden sm:table-cell">Hesap Kodu</th>
								<th class="text-left py-2 px-3">Cari Adı</th>
								<th class="text-left py-2 px-3 hidden md:table-cell">Banka / IBAN</th>
								<th class="text-right py-2 px-3 w-44">Ödeme Tutarı</th>
								{#if canUse}<th class="w-10"></th>{/if}
							</tr>
						</thead>
						<tbody>
							{#each activeList.items as item, i (item.id)}
								<tr class="border-b border-gray-50 hover:bg-gray-50/50">
									<td class="py-1.5 px-3 text-gray-500">{i + 1}</td>
									<td class="py-1.5 px-3 text-gray-500 hidden sm:table-cell tabular-nums">{item.hesap_kodu ?? '-'}</td>
									<td class="py-1.5 px-3 text-gray-800 truncate max-w-[220px]" title={item.hesap_adi}>{item.hesap_adi}</td>
									<td class="py-1.5 px-3 hidden md:table-cell">
										{#if canUse}
											<div class="relative">
												<button onclick={() => openIban(item)} class="text-left hover:bg-gray-100 rounded px-1.5 py-1 max-w-[220px] cursor-pointer {item.iban ? 'text-gray-700' : 'text-gray-400 italic'}" title="IBAN seç/değiştir">
													{#if item.iban}
														<span class="block text-xs font-medium truncate">{item.bank_name || 'Banka'}</span>
														<span class="block font-mono text-[11px] text-gray-500 truncate">{fmtIban(item.iban)}</span>
													{:else}
														<span class="text-xs">IBAN seç</span>
													{/if}
												</button>
												{#if ibanMenuId === item.id}
													<button class="fixed inset-0 z-10 cursor-default" aria-label="Kapat" onclick={() => (ibanMenuId = null)}></button>
													<div class="absolute left-0 mt-1 w-72 bg-white border border-gray-200 rounded-lg shadow-lg z-20 py-1 max-h-64 overflow-y-auto">
														{#if ibanLoading}
															<div class="px-3 py-2 text-xs text-gray-400">Yükleniyor…</div>
														{:else if ibanOpts.length === 0}
															<div class="px-3 py-2 text-xs text-gray-500">Bu carinin kayıtlı IBAN'ı yok. <span class="text-gray-400">Cari kartından ekleyin.</span></div>
														{:else}
															{#each ibanOpts as ba (ba.id)}
																<button onclick={() => pickIban(item, ba)} class="w-full text-left px-3 py-2 hover:bg-teal-50 cursor-pointer {item.iban === ba.iban ? 'bg-teal-50' : ''}">
																	<span class="block text-xs font-medium text-gray-800">{ba.bank_name || 'Banka'}{ba.is_default ? ' · varsayılan' : ''}</span>
																	<span class="block font-mono text-[11px] text-gray-500">{fmtIban(ba.iban)}</span>
																</button>
															{/each}
														{/if}
														{#if item.iban}
															<button onclick={() => pickIban(item, null)} class="w-full text-left px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 border-t border-gray-100 cursor-pointer">IBAN'ı kaldır</button>
														{/if}
													</div>
												{/if}
											</div>
										{:else if item.iban}
											<span class="text-xs"><span class="block">{item.bank_name || ''}</span><span class="block font-mono text-[11px] text-gray-500">{fmtIban(item.iban)}</span></span>
										{:else}
											<span class="text-xs text-gray-300">—</span>
										{/if}
									</td>
									<td class="py-1.5 px-3">
										{#if canUse}
											<MoneyInput
												bind:value={item.amount}
												currency="TRY"
												min={0}
												onchange={() => scheduleSave(item)}
											/>
										{:else}
											<span class="block text-right tabular-nums font-medium">₺{fmt(item.amount)}</span>
										{/if}
									</td>
									{#if canUse}
										<td class="py-1.5 px-2 text-center">
											<button onclick={() => askDeleteItem(item)} class="p-1 text-red-400 hover:text-red-600" title="Çıkar">
												<Trash2 size={14} />
											</button>
										</td>
									{/if}
								</tr>
							{/each}
						</tbody>
						<tfoot>
							<tr class="border-t-2 border-gray-200 font-bold">
								<td colspan={4} class="py-2 px-3 text-right text-gray-600">TOPLAM</td>
								<td class="py-2 px-3 text-right tabular-nums text-rose-600">₺{fmt(activeTotal)}</td>
								{#if canUse}<td></td>{/if}
							</tr>
						</tfoot>
					</table>
				</div>
			{/if}
		</div>
	{/if}
</div>

<!-- Yeni liste modal -->
<Modal bind:show={showNewModal} title="Yeni Ödeme Talimat Listesi" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); createList(); }} class="space-y-4">
		<div>
			<label for="pi-name" class="text-xs text-gray-500 mb-1 block">Liste Adı <span class="text-rose-500">*</span></label>
			<Input id="pi-name" size="sm" bind:value={newName} placeholder="ör: Haftalık Ödeme 26.05" required />
		</div>
		<div class="flex items-center justify-end gap-2">
			<Button variant="secondary" onclick={() => (showNewModal = false)}>Vazgeç</Button>
			<Button type="submit" loading={busy} disabled={busy}>Oluştur</Button>
		</div>
	</form>
</Modal>

<Modal bind:show={ykbModalOpen} title="Yapı Kredi Toplu Ödeme Excel'i" maxWidth="max-w-md">
	<form onsubmit={(e) => { e.preventDefault(); confirmYkbExport(); }} class="space-y-4">
		<p class="text-sm text-gray-600">
			Yapı Kredi internet bankacılığına yüklenecek formatta indirir. <span class="font-medium">IBAN, alıcı adı, tutar (TL)</span> ve açıklama listeden otomatik gelir.
		</p>
		<div>
			<label for="ykb-debtor" class="text-xs text-gray-500 mb-1 block">Borçlu Hesap (ödemenin yapılacağı YKB hesap no)</label>
			<Input id="ykb-debtor" size="sm" bind:value={ykbDebtor} inputmode="numeric"
				class="tabular-nums"
				placeholder="ör: 65610029" />
			<p class="text-[11px] text-gray-400 mt-1">Boş bırakırsanız kayıtlı Yapı Kredi TL hesabınız otomatik gelir. Girerseniz tarayıcıda da hatırlanır.</p>
		</div>
		<div class="flex items-center justify-end gap-2">
			<Button variant="secondary" onclick={() => (ykbModalOpen = false)}>Vazgeç</Button>
			<Button type="submit" loading={busy} disabled={busy}>
				<Download size={15} /> İndir
			</Button>
		</div>
	</form>
</Modal>

<ConfirmDialog
	bind:show={confirmDelete.show}
	title={confirmDelete.kind === 'list' ? 'Listeyi Sil' : 'Cariyi Çıkar'}
	message={confirmDelete.kind === 'list'
		? `"${confirmDelete.label}" listesi ve tüm kalemleri silinecek. Devam edilsin mi?`
		: `"${confirmDelete.label}" listeden çıkarılsın mı?`}
	confirmText={confirmDelete.kind === 'list' ? 'Listeyi Sil' : 'Çıkar'}
	cancelText="Vazgeç"
	danger
	onConfirm={doDelete}
/>
