<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import ListPage from '$lib/components/ListPage.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Button from '$lib/components/Button.svelte';
	import Select from '$lib/components/Select.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import {
		ShieldCheck, Copy, Check, Gauge, AlertTriangle, CheckCircle2, Bot, Play,
		ChevronDown, ChevronRight, Settings, TrendingUp, FileText, RefreshCw
	} from 'lucide-svelte';

	const canUse = hasPermission('system.denetim', 'use');

	// ─── Sabitler ────────────────────────────────────────────
	const RISK_LABEL: Record<string, string> = {
		kritik: 'Kritik', yuksek: 'Yüksek', orta: 'Orta', dusuk: 'Düşük'
	};
	const RISK_BADGE: Record<string, 'error' | 'warning' | 'info' | 'neutral'> = {
		kritik: 'error', yuksek: 'warning', orta: 'info', dusuk: 'neutral'
	};
	const STATUS_LABEL: Record<string, string> = {
		acik: 'Açık', devam: 'Çalışılıyor', inceleme: 'İnceleme bekliyor',
		kismen: 'Kısmen düzeldi', kapali: 'Düzeldi', iptal: 'Uygulanmayacak'
	};
	const STATUS_BADGE: Record<string, 'success' | 'error' | 'warning' | 'info' | 'neutral'> = {
		acik: 'error', devam: 'info', inceleme: 'warning',
		kismen: 'warning', kapali: 'success', iptal: 'neutral'
	};
	const CATEGORY_LABEL: Record<string, string> = {
		kod: 'Kod', altyapi: 'Altyapı', surec: 'Süreç', dokuman: 'Doküman',
		test: 'Test', guvenlik: 'Güvenlik', veri: 'Veri'
	};
	const RUN_STATUS_LABEL: Record<string, string> = {
		calisiyor: 'Çalışıyor', basarili: 'Başarılı', basarisiz: 'Başarısız',
		atlandi: 'Atlandı', geri_alindi: 'Geri alındı'
	};

	// ─── State ───────────────────────────────────────────────
	let view = $state('bulgular');
	let findings = $state<any[]>([]);
	let board = $state<any | null>(null);
	let runs = $state<any[]>([]);
	let config = $state<any | null>(null);

	let loading = $state(true);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	const pageSize = 50;

	let searchText = $state('');
	let riskFilter = $state('');
	let statusFilter = $state('');
	let categoryFilter = $state('');
	let dimensionFilter = $state('');
	let sortBy = $state('');
	let sortDir = $state<'asc' | 'desc'>('asc');

	let expandedId = $state<number | null>(null);
	let copiedId = $state<number | null>(null);
	let runningId = $state<number | null>(null);
	let savingId = $state<number | null>(null);

	let showConfig = $state(false);
	let configForm = $state<any>({});
	let savingConfig = $state(false);

	let confirmRun = $state(false);
	let runTarget = $state<any | null>(null);

	// ─── Türetilmiş ──────────────────────────────────────────
	let scoreDelta = $derived(
		board ? Math.round((board.current_score - board.baseline_score) * 10) / 10 : 0
	);

	// ─── Formatlama ──────────────────────────────────────────
	function fmtScore(n: number | null | undefined): string {
		if (n === null || n === undefined) return '-';
		return n.toFixed(1).replace('.', ',');
	}

	function fmtPoints(n: number): string {
		if (!n) return '-';
		return (n > 0 ? '+' : '') + n.toFixed(2).replace('.', ',');
	}

	function fmtDate(s: string | null): string {
		if (!s) return '-';
		const d = new Date(s);
		return d.toLocaleDateString('tr-TR') + ' ' +
			d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
	}

	function barWidth(value: number, max = 10): string {
		return `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
	}

	// ─── Veri ────────────────────────────────────────────────
	async function loadFindings() {
		loading = true;
		try {
			const params = new URLSearchParams({
				page: String(page),
				page_size: String(pageSize)
			});
			if (searchText) params.set('search', searchText);
			if (riskFilter) params.set('risk', riskFilter);
			if (statusFilter) params.set('status', statusFilter);
			if (categoryFilter) params.set('category', categoryFilter);
			if (dimensionFilter) params.set('dimension_no', dimensionFilter);
			if (sortBy) {
				params.set('sort_by', sortBy);
				params.set('sort_dir', sortDir);
			}
			const res = await api.get<any>(`/system/denetim/findings?${params}`);
			findings = res.items ?? [];
			total = res.total ?? 0;
			pages = res.pages ?? 1;
		} catch (err) {
			console.error('Bulgular yüklenemedi:', err);
			showToast('Denetim bulguları yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	async function loadBoard() {
		try {
			board = await api.get<any>('/system/denetim/scoreboard');
		} catch (err) {
			console.error('Skor panosu yüklenemedi:', err);
			showToast('Skor panosu yüklenemedi', 'error');
		}
	}

	async function loadRuns() {
		try {
			const res = await api.get<any>('/system/denetim/runs?page=1&page_size=50');
			runs = res.items ?? [];
		} catch (err) {
			console.error('Koşu geçmişi yüklenemedi:', err);
			showToast('Koşu geçmişi yüklenemedi', 'error');
		}
	}

	async function loadConfig() {
		try {
			config = await api.get<any>('/system/denetim/config');
		} catch (err) {
			console.error('Otomasyon ayarları yüklenemedi:', err);
			showToast('Otomasyon ayarları yüklenemedi', 'error');
		}
	}

	async function refreshAll() {
		await Promise.all([loadFindings(), loadBoard(), loadConfig()]);
		if (view === 'kosular') await loadRuns();
	}

	// ─── Bulgu işlemleri ─────────────────────────────────────
	async function setStatus(f: any, status: string) {
		savingId = f.id;
		try {
			await api.patch(`/system/denetim/findings/${f.id}`, { status });
			showToast(`${f.code} → ${STATUS_LABEL[status]}`, 'success');
			await Promise.all([loadFindings(), loadBoard()]);
		} catch (err) {
			console.error('Durum güncellenemedi:', err);
			const msg = err instanceof ApiError ? err.message : 'Durum güncellenemedi';
			showToast(msg, 'error');
		} finally {
			savingId = null;
		}
	}

	async function toggleAuto(f: any) {
		savingId = f.id;
		try {
			await api.patch(`/system/denetim/findings/${f.id}`, { auto_enabled: !f.auto_enabled });
			showToast(
				f.auto_enabled
					? `${f.code} otomasyon kuyruğundan çıkarıldı`
					: `${f.code} otomasyon kuyruğuna eklendi`,
				'success'
			);
			await Promise.all([loadFindings(), loadConfig()]);
		} catch (err) {
			console.error('Otomasyon ayarı değiştirilemedi:', err);
			showToast('Otomasyon ayarı değiştirilemedi', 'error');
		} finally {
			savingId = null;
		}
	}

	async function copyPrompt(f: any) {
		try {
			if (!navigator.clipboard) throw new Error('Pano API desteklenmiyor');
			await navigator.clipboard.writeText(f.prompt);
			copiedId = f.id;
			setTimeout(() => { if (copiedId === f.id) copiedId = null; }, 1800);
			showToast(`${f.code} komutu panoya kopyalandı`, 'success');
		} catch (err) {
			console.error('Panoya kopyalanamadı:', err);
			showToast('Panoya kopyalanamadı', 'error');
		}
	}

	function askRun(f: any) {
		runTarget = f;
		confirmRun = true;
	}

	async function doRun() {
		if (!runTarget) return;
		const f = runTarget;
		runningId = f.id;
		try {
			await api.post(`/system/denetim/findings/${f.id}/run`, {});
			showToast(`${f.code} için otomasyon başlatıldı — birkaç dakika sürebilir`, 'success');
			await loadFindings();
		} catch (err) {
			console.error('Otomasyon başlatılamadı:', err);
			const msg = err instanceof ApiError ? err.message : 'Otomasyon başlatılamadı';
			showToast(msg, 'error');
		} finally {
			runningId = null;
			runTarget = null;
		}
	}

	// ─── Otomasyon ayarları ──────────────────────────────────
	function openConfig() {
		configForm = { ...config };
		showConfig = true;
	}

	async function saveConfig() {
		savingConfig = true;
		try {
			const payload: any = {};
			for (const k of [
				'enabled', 'interval_hours', 'model', 'max_attempts', 'max_budget_usd',
				'timeout_min', 'auto_deploy', 'auto_rollback', 'min_free_mb',
				'notify_inapp', 'notify_email'
			]) {
				if (configForm[k] !== undefined && configForm[k] !== config[k]) {
					payload[k] = configForm[k];
				}
			}
			if (Object.keys(payload).length === 0) {
				showConfig = false;
				return;
			}
			await api.patch('/system/denetim/config', payload);
			showToast('Otomasyon ayarları kaydedildi', 'success');
			showConfig = false;
			await loadConfig();
		} catch (err) {
			console.error('Ayarlar kaydedilemedi:', err);
			const msg = err instanceof ApiError ? err.message : 'Ayarlar kaydedilemedi';
			showToast(msg, 'error');
		} finally {
			savingConfig = false;
		}
	}

	// ─── UI yardımcıları ─────────────────────────────────────
	function toggleExpand(id: number) {
		expandedId = expandedId === id ? null : id;
	}

	function changeView(v: string) {
		view = v;
		if (v === 'kosular' && runs.length === 0) loadRuns();
	}

	function applyFilter() {
		page = 1;
		loadFindings();
	}

	// ─── Lifecycle ───────────────────────────────────────────
	onMount(() => {
		refreshAll();
	});
</script>

<svelte:head>
	<title>Denetim Takip · Sprenses</title>
</svelte:head>

<ListPage
	title="Denetim Takip"
	description={board
		? `${board.report_title} — ${total} bulgu, genel not ${fmtScore(board.current_score)}/100`
		: 'Kurumsal denetim bulgularının yaşayan takibi'}
	loading={loading && view === 'bulgular'}
	isEmpty={view === 'bulgular' && findings.length === 0}
	emptyIcon={ShieldCheck}
	emptyTitle="Bulgu bulunamadı"
	emptyMessage="Seçili filtrelere uyan denetim bulgusu yok."
	bind:search={searchText}
	searchPlaceholder="Kod, başlık veya kanıt ara…"
	onSearch={(v: string) => { searchText = v; applyFilter(); }}
	{page}
	{pages}
	{total}
	{pageSize}
	skeletonRows={10}
	skeletonColumns={7}
	maxWidth="max-w-[1600px]"
	onPageChange={view === 'bulgular' ? (p: number) => { page = p; loadFindings(); } : undefined}
>
	{#snippet actions()}
		<Button variant="secondary" size="sm" onclick={refreshAll} title="Yenile">
			<RefreshCw size={16} /> Yenile
		</Button>
		{#if board?.doc_path}
			<Button variant="ghost" size="sm" href="/dashboard/sistem/dokumanlar" title="Raporu aç">
				<FileText size={16} /> Rapor
			</Button>
		{/if}
		{#if canUse}
			<Button onclick={openConfig}>
				<Settings size={16} /> Otomasyon
			</Button>
		{/if}
	{/snippet}

	{#snippet stats()}
		<div class="grid grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
			<StatCard
				label="Genel Not"
				value={board ? `${fmtScore(board.current_score)}/100` : '-'}
				icon={Gauge}
				accent="teal"
				hint={board
					? `Denetim anı ${fmtScore(board.baseline_score)} · hedef ${fmtScore(board.target_score)}`
					: ''}
				delta={scoreDelta !== 0 ? scoreDelta : undefined}
				deltaText={scoreDelta !== 0 ? `${fmtPoints(scoreDelta)} puan` : undefined}
			/>
			<StatCard
				label="Kritik Açık"
				value={board?.counts?.kritik_acik ?? '-'}
				icon={AlertTriangle}
				accent="red"
				hint="acil müdahale"
			/>
			<StatCard
				label="Yüksek Açık"
				value={board?.counts?.yuksek_acik ?? '-'}
				icon={ShieldCheck}
				accent="amber"
			/>
			<StatCard
				label="Düzelen"
				value={board ? (board.counts.kapali + board.counts.kismen) : '-'}
				icon={CheckCircle2}
				accent="emerald"
				hint={board ? `${board.counts.toplam} bulgudan` : ''}
			/>
			<StatCard
				label="Otomasyon"
				value={config?.enabled ? 'Açık' : 'Kapalı'}
				icon={Bot}
				accent={config?.enabled ? 'emerald' : 'gray'}
				hint={config?.next_candidate
					? `Sıradaki: ${config.next_candidate.code}`
					: `${board?.counts?.otomasyon_kuyrugu ?? 0} madde kuyrukta`}
			/>
		</div>
	{/snippet}

	{#snippet filters()}
		<SegmentedControl
			options={[
				{ value: 'bulgular', label: 'Bulgular', count: total },
				{ value: 'skor', label: 'Skor Panosu' },
				{ value: 'kosular', label: 'Otomasyon Koşuları' }
			]}
			value={view}
			onchange={changeView}
			size="sm"
			ariaLabel="Görünüm"
		/>
		{#if view === 'bulgular'}
			<div class="min-w-[130px]">
				<label for="dn-risk" class="block text-xs font-medium text-gray-500 mb-1">Risk</label>
				<Select id="dn-risk" size="sm" bind:value={riskFilter} onchange={applyFilter}>
					<option value="">Tümü</option>
					<option value="kritik">Kritik</option>
					<option value="yuksek">Yüksek</option>
					<option value="orta">Orta</option>
					<option value="dusuk">Düşük</option>
				</Select>
			</div>
			<div class="min-w-[150px]">
				<label for="dn-status" class="block text-xs font-medium text-gray-500 mb-1">Durum</label>
				<Select id="dn-status" size="sm" bind:value={statusFilter} onchange={applyFilter}>
					<option value="">Tümü</option>
					<option value="acik">Açık</option>
					<option value="devam">Çalışılıyor</option>
					<option value="inceleme">İnceleme bekliyor</option>
					<option value="kismen">Kısmen düzeldi</option>
					<option value="kapali">Düzeldi</option>
					<option value="iptal">Uygulanmayacak</option>
				</Select>
			</div>
			<div class="min-w-[140px]">
				<label for="dn-cat" class="block text-xs font-medium text-gray-500 mb-1">Kategori</label>
				<Select id="dn-cat" size="sm" bind:value={categoryFilter} onchange={applyFilter}>
					<option value="">Tümü</option>
					{#each Object.entries(CATEGORY_LABEL) as [v, l]}
						<option value={v}>{l}</option>
					{/each}
				</Select>
			</div>
			<div class="min-w-[190px]">
				<label for="dn-dim" class="block text-xs font-medium text-gray-500 mb-1">Boyut</label>
				<Select id="dn-dim" size="sm" bind:value={dimensionFilter} onchange={applyFilter}>
					<option value="">Tümü</option>
					{#each board?.dimensions ?? [] as d}
						<option value={String(d.no)}>{d.no}. {d.name}</option>
					{/each}
				</Select>
			</div>
		{/if}
	{/snippet}

	{#if view === 'bulgular'}
		<!-- Masaüstü tablo -->
		<div class="hidden lg:block overflow-x-auto">
			<table class="w-full text-sm">
				<thead class="bg-gray-50 border-b border-gray-200">
					<tr>
						<th class="w-8"></th>
						<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Kod</th>
						<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Bulgu</th>
						<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Risk</th>
						<th class="px-3 py-3 text-center font-medium text-gray-500 text-xs">Efor</th>
						<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Durum</th>
						<th class="px-3 py-3 text-right font-medium text-gray-500 text-xs">Puan Etkisi</th>
						<th class="px-3 py-3 text-center font-medium text-gray-500 text-xs">Otomasyon</th>
						<th class="px-3 py-3 text-right font-medium text-gray-500 text-xs">İşlem</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each findings as f (f.id)}
						<tr class="hover:bg-gray-50 transition-colors {f.status === 'kapali' ? 'bg-emerald-50/40' : ''}">
							<td class="pl-2">
								<button
									type="button"
									class="p-1 text-gray-500 hover:text-gray-800 rounded focus:outline-none focus:ring-2 focus:ring-teal-500"
									onclick={() => toggleExpand(f.id)}
									aria-label={expandedId === f.id ? 'Ayrıntıyı kapat' : 'Ayrıntıyı aç'}
								>
									{#if expandedId === f.id}<ChevronDown size={16} />{:else}<ChevronRight size={16} />{/if}
								</button>
							</td>
							<td class="px-3 py-3 font-mono text-xs text-gray-600 whitespace-nowrap">{f.code}</td>
							<td class="px-3 py-3 text-gray-800 max-w-[520px]">
								<div class="line-clamp-2">{f.title}</div>
								<div class="text-xs text-gray-500 mt-0.5">
									{f.dimension_no}. {f.dimension_name} · {CATEGORY_LABEL[f.category] ?? f.category}
								</div>
							</td>
							<td class="px-3 py-3">
								<StatusBadge type={RISK_BADGE[f.risk]}>{RISK_LABEL[f.risk] ?? f.risk}</StatusBadge>
							</td>
							<td class="px-3 py-3 text-center text-xs font-medium text-gray-600">{f.effort}</td>
							<td class="px-3 py-3">
								<StatusBadge type={STATUS_BADGE[f.status]}>{STATUS_LABEL[f.status] ?? f.status}</StatusBadge>
							</td>
							<td class="px-3 py-3 text-right tabular-nums whitespace-nowrap">
								{#if f.applied_points > 0}
									<span class="text-emerald-700 font-semibold">{fmtPoints(f.applied_points)}</span>
									<span class="text-xs text-gray-500"> puan</span>
								{:else if f.potential_points > 0}
									<span class="text-gray-500">{fmtPoints(f.potential_points)}</span>
									<span class="text-xs text-gray-500"> kazanç</span>
								{:else}
									<span class="text-gray-500">-</span>
								{/if}
							</td>
							<td class="px-3 py-3 text-center">
								{#if !f.automatable}
									<span class="text-xs text-gray-500" title="Repo dışı iş gerektiriyor (GitHub ayarı, AWS provizyonu, insan kararı)">Elle</span>
								{:else if f.auto_enabled}
									<span class="inline-flex items-center gap-1 text-xs text-teal-700 font-medium">
										<Bot size={13} /> Kuyrukta
									</span>
								{:else}
									<span class="text-xs text-gray-500">Uygun</span>
								{/if}
								{#if f.auto_attempts > 0}
									<div class="text-[10px] text-gray-500 mt-0.5">{f.auto_attempts} deneme</div>
								{/if}
							</td>
							<td class="px-3 py-3 text-right whitespace-nowrap">
								<div class="flex items-center justify-end gap-1.5">
									<Button
										variant="secondary"
										size="sm"
										onclick={() => copyPrompt(f)}
										title="Claude Code komutunu panoya kopyala"
									>
										{#if copiedId === f.id}
											<Check size={14} /> Kopyalandı
										{:else}
											<Copy size={14} /> Kopyala
										{/if}
									</Button>
									{#if canUse && f.automatable}
										<Button
											variant="ghost"
											size="sm"
											loading={runningId === f.id}
											disabled={f.status === 'devam'}
											onclick={() => askRun(f)}
											ariaLabel="Otomasyonu şimdi çalıştır"
											title="Otomasyonu şimdi çalıştır"
										>
											<Play size={14} />
										</Button>
									{/if}
								</div>
							</td>
						</tr>

						{#if expandedId === f.id}
							<tr class="bg-gray-50/70">
								<td colspan="9" class="px-6 py-4">
									<div class="grid grid-cols-1 xl:grid-cols-2 gap-5">
										<div class="space-y-4">
											{#if f.evidence}
												<div>
													<h4 class="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Kanıt</h4>
													<p class="text-sm text-gray-700 whitespace-pre-wrap">{f.evidence}</p>
												</div>
											{/if}
											{#if f.solution}
												<div>
													<h4 class="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Önerilen çözüm</h4>
													<p class="text-sm text-gray-700 whitespace-pre-wrap">{f.solution}</p>
												</div>
											{/if}
											{#if f.closure_criteria}
												<div>
													<h4 class="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Kapanış kriteri</h4>
													<p class="text-sm text-gray-700 whitespace-pre-wrap">{f.closure_criteria}</p>
												</div>
											{/if}
											{#if f.closed_at}
												<div class="text-xs text-gray-500">
													Kapanış: {fmtDate(f.closed_at)}
													{#if f.closed_by_name}· {f.closed_by_name}{/if}
													{#if f.closure_note}<br />{f.closure_note}{/if}
												</div>
											{/if}
										</div>

										<div class="space-y-3">
											<div>
												<div class="flex items-center justify-between mb-1">
													<h4 class="text-xs font-semibold text-gray-600 uppercase tracking-wide">
														Claude Code komutu
													</h4>
													<Button variant="secondary" size="sm" onclick={() => copyPrompt(f)}>
														{#if copiedId === f.id}<Check size={14} /> Kopyalandı{:else}<Copy size={14} /> Kopyala{/if}
													</Button>
												</div>
												<pre class="text-[11px] leading-relaxed bg-white border border-gray-200 rounded-lg p-3 max-h-72 overflow-auto whitespace-pre-wrap text-gray-700">{f.prompt}</pre>
											</div>

											{#if f.last_run}
												<div class="text-xs text-gray-600 bg-white border border-gray-200 rounded-lg p-3">
													<div class="font-medium text-gray-700 mb-1">
														Son koşu: {RUN_STATUS_LABEL[f.last_run.status] ?? f.last_run.status}
														<span class="text-gray-500">· {fmtDate(f.last_run.started_at)}</span>
													</div>
													{#if f.last_run.tests_passed !== null}
														<div>Testler: {f.last_run.tests_passed} geçti / {f.last_run.tests_failed ?? 0} hata</div>
													{/if}
													{#if f.last_run.branch}<div class="font-mono text-[11px]">{f.last_run.branch}</div>{/if}
													{#if f.last_run.deployed}<div class="text-emerald-700">Canlıya alındı</div>{/if}
													{#if f.last_run.rolled_back}<div class="text-red-700">Geri alındı</div>{/if}
													{#if f.last_run.error}<div class="text-red-700 mt-1">{f.last_run.error}</div>{/if}
												</div>
											{/if}

											{#if canUse}
												<div class="flex flex-wrap items-center gap-2 pt-1">
													<span class="text-xs text-gray-500">Durumu değiştir:</span>
													{#each ['acik', 'inceleme', 'kismen', 'kapali', 'iptal'] as st}
														{#if st !== f.status}
															<Button
																variant={st === 'kapali' ? 'primary' : 'secondary'}
																size="sm"
																loading={savingId === f.id}
																onclick={() => setStatus(f, st)}
															>{STATUS_LABEL[st]}</Button>
														{/if}
													{/each}
													{#if f.automatable}
														<Button
															variant="ghost"
															size="sm"
															loading={savingId === f.id}
															onclick={() => toggleAuto(f)}
														>
															<Bot size={14} />
															{f.auto_enabled ? 'Kuyruktan çıkar' : 'Otomasyon kuyruğuna ekle'}
														</Button>
													{/if}
												</div>
											{/if}
										</div>
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Mobil kart listesi -->
		<div class="lg:hidden divide-y divide-gray-100">
			{#each findings as f (f.id)}
				<div class="p-3 {f.status === 'kapali' ? 'bg-emerald-50/40' : ''}">
					<div class="flex items-center justify-between gap-2 mb-1.5">
						<span class="text-[11px] font-mono text-gray-500">{f.code}</span>
						<div class="flex items-center gap-1.5">
							<StatusBadge type={RISK_BADGE[f.risk]}>{RISK_LABEL[f.risk] ?? f.risk}</StatusBadge>
							<StatusBadge type={STATUS_BADGE[f.status]}>{STATUS_LABEL[f.status] ?? f.status}</StatusBadge>
						</div>
					</div>
					<p class="text-sm text-gray-800">{f.title}</p>
					<p class="text-xs text-gray-500 mt-0.5">
						{f.dimension_no}. {f.dimension_name} · Efor {f.effort} ·
						{#if f.applied_points > 0}
							<span class="text-emerald-700 font-medium">{fmtPoints(f.applied_points)} puan</span>
						{:else}
							{fmtPoints(f.potential_points)} kazanç
						{/if}
					</p>
					<div class="mt-2 flex gap-2">
						<Button variant="secondary" size="sm" fullWidth onclick={() => copyPrompt(f)}>
							{#if copiedId === f.id}<Check size={14} /> Kopyalandı{:else}<Copy size={14} /> Komutu kopyala{/if}
						</Button>
						<Button variant="ghost" size="sm" onclick={() => toggleExpand(f.id)} ariaLabel="Ayrıntı">
							{#if expandedId === f.id}<ChevronDown size={16} />{:else}<ChevronRight size={16} />{/if}
						</Button>
					</div>
					{#if expandedId === f.id}
						<div class="mt-3 space-y-2 text-xs text-gray-700">
							{#if f.evidence}<p class="whitespace-pre-wrap"><strong>Kanıt:</strong> {f.evidence}</p>{/if}
							{#if f.closure_criteria}<p class="whitespace-pre-wrap"><strong>Kapanış:</strong> {f.closure_criteria}</p>{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{:else if view === 'skor'}
		<!-- Skor panosu -->
		<div class="p-4 sm:p-5">
			{#if board}
				<div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
					<div>
						<div class="text-xs text-gray-500">Denetim anı</div>
						<div class="text-2xl font-semibold text-gray-700 tabular-nums">{fmtScore(board.baseline_score)}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500">Şu an</div>
						<div class="text-2xl font-semibold text-teal-700 tabular-nums">{fmtScore(board.current_score)}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500">Tümü kapanırsa</div>
						<div class="text-2xl font-semibold text-emerald-700 tabular-nums">{fmtScore(board.potential_score)}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500">90 gün hedefi</div>
						<div class="text-2xl font-semibold text-gray-500 tabular-nums">{fmtScore(board.target_score)}</div>
					</div>
				</div>

				<div class="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-500 mb-4">
					<span>Çekirdek ürün katmanı: <strong class="text-gray-700 tabular-nums">{fmtScore(board.core_avg)}</strong> / 10</span>
					<span>Operasyon / uyum katmanı: <strong class="text-gray-700 tabular-nums">{fmtScore(board.ops_avg)}</strong> / 10</span>
				</div>

				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead class="bg-gray-50 border-b border-gray-200">
							<tr>
								<th class="px-3 py-2 text-left font-medium text-gray-500 text-xs">#</th>
								<th class="px-3 py-2 text-left font-medium text-gray-500 text-xs">Boyut</th>
								<th class="px-3 py-2 text-right font-medium text-gray-500 text-xs">Denetim</th>
								<th class="px-3 py-2 text-right font-medium text-gray-500 text-xs">Şu an</th>
								<th class="px-3 py-2 text-left font-medium text-gray-500 text-xs w-56">İlerleme</th>
								<th class="px-3 py-2 text-right font-medium text-gray-500 text-xs">Hedef</th>
								<th class="px-3 py-2 text-right font-medium text-gray-500 text-xs">Açık / Toplam</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-100">
							{#each board.dimensions as d (d.no)}
								<tr class="hover:bg-gray-50">
									<td class="px-3 py-2 text-xs text-gray-500 tabular-nums">{d.no}</td>
									<td class="px-3 py-2 text-gray-800">
										{d.name}
										<span class="text-[10px] text-gray-500 ml-1">
											{d.layer === 'cekirdek' ? 'çekirdek' : 'operasyon'}
										</span>
									</td>
									<td class="px-3 py-2 text-right tabular-nums text-gray-500">{fmtScore(d.score_baseline)}</td>
									<td class="px-3 py-2 text-right tabular-nums font-semibold {d.score_current > d.score_baseline ? 'text-emerald-700' : 'text-gray-700'}">
										{fmtScore(d.score_current)}
									</td>
									<td class="px-3 py-2">
										<div class="h-2 bg-gray-200 rounded-full overflow-hidden relative">
											<div class="absolute inset-y-0 left-0 bg-gray-400" style="width: {barWidth(d.score_baseline)}"></div>
											<div class="absolute inset-y-0 left-0 bg-teal-700" style="width: {barWidth(d.score_current)}"></div>
											<div class="absolute inset-y-0 w-0.5 bg-amber-500" style="left: {barWidth(d.score_target)}"></div>
										</div>
									</td>
									<td class="px-3 py-2 text-right tabular-nums text-gray-500">{fmtScore(d.score_target)}</td>
									<td class="px-3 py-2 text-right tabular-nums text-xs text-gray-600">
										{d.open_count} / {d.total_count}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	{:else}
		<!-- Otomasyon koşuları -->
		<div class="overflow-x-auto">
			{#if runs.length === 0}
				<div class="p-8 text-center text-sm text-gray-500">
					Henüz otomasyon koşusu yok. Bir bulguyu otomasyon kuyruğuna ekleyin veya
					satırdaki ▶ düğmesiyle hemen başlatın.
				</div>
			{:else}
				<table class="w-full text-sm">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Başlangıç</th>
							<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Bulgu</th>
							<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Sonuç</th>
							<th class="px-3 py-3 text-right font-medium text-gray-500 text-xs">Süre</th>
							<th class="px-3 py-3 text-right font-medium text-gray-500 text-xs">Testler</th>
							<th class="px-3 py-3 text-center font-medium text-gray-500 text-xs">Deploy</th>
							<th class="px-3 py-3 text-right font-medium text-gray-500 text-xs">Maliyet</th>
							<th class="px-3 py-3 text-left font-medium text-gray-500 text-xs">Branch</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-100">
						{#each runs as r (r.id)}
							<tr class="hover:bg-gray-50">
								<td class="px-3 py-3 text-xs text-gray-600 whitespace-nowrap">{fmtDate(r.started_at)}</td>
								<td class="px-3 py-3">
									<div class="font-mono text-xs text-gray-600">{r.finding_code}</div>
									<div class="text-xs text-gray-500 max-w-[320px] truncate">{r.finding_title}</div>
								</td>
								<td class="px-3 py-3">
									<StatusBadge
										type={r.status === 'basarili' ? 'success'
											: r.status === 'calisiyor' ? 'info'
											: r.status === 'atlandi' ? 'neutral' : 'error'}
									>{RUN_STATUS_LABEL[r.status] ?? r.status}</StatusBadge>
									{#if r.error}
										<div class="text-[11px] text-red-700 mt-1 max-w-[320px] line-clamp-2">{r.error}</div>
									{/if}
								</td>
								<td class="px-3 py-3 text-right tabular-nums text-xs text-gray-600">
									{r.duration_sec ? `${Math.round(r.duration_sec / 60)} dk` : '-'}
								</td>
								<td class="px-3 py-3 text-right tabular-nums text-xs">
									{#if r.tests_passed !== null && r.tests_passed !== undefined}
										<span class="text-emerald-700">{r.tests_passed}</span>
										{#if r.tests_failed}<span class="text-red-700"> / {r.tests_failed}</span>{/if}
									{:else}-{/if}
								</td>
								<td class="px-3 py-3 text-center text-xs">
									{#if r.rolled_back}
										<span class="text-red-700">Geri alındı</span>
									{:else if r.deployed}
										<span class="text-emerald-700">Canlıda</span>
									{:else}
										<span class="text-gray-500">-</span>
									{/if}
								</td>
								<td class="px-3 py-3 text-right tabular-nums text-xs text-gray-600">
									{r.cost_usd ? `$${r.cost_usd.toFixed(2)}` : '-'}
								</td>
								<td class="px-3 py-3 font-mono text-[11px] text-gray-500 max-w-[220px] truncate">
									{r.branch ?? '-'}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	{/if}
</ListPage>

<!-- Otomasyon ayarları -->
<Modal bind:show={showConfig} title="Otomasyon Ayarları" maxWidth="max-w-2xl">
	{#if configForm}
		<div class="space-y-4">
			<div class="rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900">
				<strong>Otonom mod:</strong> Testler yeşilse düzeltme master'a birleştirilir ve
				canlıya alınır. Deploy sonrası <code>/api/health</code> 200 dönmezse değişiklik
				otomatik geri alınır. Yeni veritabanı migration'ı, bu script veya systemd
				birimlerini içeren değişiklikler <strong>otomatik deploy edilmez</strong> —
				inceleme kuyruğunda bekler.
			</div>

			<label class="flex items-center gap-2 text-sm text-gray-700">
				<input type="checkbox" bind:checked={configForm.enabled} class="accent-teal-700 focus:ring-teal-500" />
				Otomasyon açık (5 saatte bir çalışır)
			</label>

			<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
				<div>
					<label for="cf-model" class="block text-xs font-medium text-gray-500 mb-1">Model</label>
					<Select id="cf-model" bind:value={configForm.model} fullWidth>
						<option value="opus">Opus 5 (en yüksek doğruluk)</option>
						<option value="sonnet">Sonnet 5</option>
						<option value="haiku">Haiku 4.5</option>
					</Select>
				</div>
				<div>
					<label for="cf-budget" class="block text-xs font-medium text-gray-500 mb-1">
						Koşu başına bütçe (USD)
					</label>
					<input
						id="cf-budget"
						type="number"
						step="0.5"
						min="0.5"
						max="50"
						bind:value={configForm.max_budget_usd}
						class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
					/>
				</div>
				<div>
					<label for="cf-attempts" class="block text-xs font-medium text-gray-500 mb-1">
						Bulgu başına en fazla deneme
					</label>
					<input
						id="cf-attempts"
						type="number"
						min="1"
						max="5"
						bind:value={configForm.max_attempts}
						class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
					/>
				</div>
				<div>
					<label for="cf-timeout" class="block text-xs font-medium text-gray-500 mb-1">
						Zaman aşımı (dakika)
					</label>
					<input
						id="cf-timeout"
						type="number"
						min="5"
						max="180"
						bind:value={configForm.timeout_min}
						class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
					/>
				</div>
			</div>

			<div class="space-y-2 pt-1">
				<label class="flex items-center gap-2 text-sm text-gray-700">
					<input type="checkbox" bind:checked={configForm.auto_deploy} class="accent-teal-700 focus:ring-teal-500" />
					Testler yeşilse otomatik merge + deploy
				</label>
				<label class="flex items-center gap-2 text-sm text-gray-700">
					<input type="checkbox" bind:checked={configForm.auto_rollback} class="accent-teal-700 focus:ring-teal-500" />
					Deploy sonrası sağlık kontrolü başarısızsa otomatik geri al
				</label>
				<label class="flex items-center gap-2 text-sm text-gray-700">
					<input type="checkbox" bind:checked={configForm.notify_inapp} class="accent-teal-700 focus:ring-teal-500" />
					Uygulama içi bildirim + push gönder
				</label>
				<label class="flex items-center gap-2 text-sm text-gray-700">
					<input type="checkbox" bind:checked={configForm.notify_email} class="accent-teal-700 focus:ring-teal-500" />
					E-posta gönder (yalnız Denetim modülü izni olan kullanıcılara)
				</label>
			</div>

			<div class="text-xs text-gray-500 pt-1">
				Son koşu: {config?.last_run_at ? fmtDate(config.last_run_at) : 'henüz yok'}
				{#if config?.next_candidate}
					<br />Sıradaki aday: <strong>{config.next_candidate.code}</strong> — {config.next_candidate.title}
				{/if}
			</div>

			<div class="flex justify-end gap-2 pt-2 border-t border-gray-200">
				<Button variant="secondary" onclick={() => (showConfig = false)}>İptal</Button>
				<Button onclick={saveConfig} loading={savingConfig}>Kaydet</Button>
			</div>
		</div>
	{/if}
</Modal>

<ConfirmDialog
	bind:show={confirmRun}
	title="Otomasyonu şimdi çalıştır"
	message={runTarget
		? `${runTarget.code} bulgusu için Claude Code izole bir dalda çalıştırılacak. Testler yeşilse değişiklik canlıya alınır (sağlık kontrolü başarısız olursa otomatik geri alınır). Devam edilsin mi?`
		: ''}
	confirmText="Çalıştır"
	cancelText="Vazgeç"
	onConfirm={doRun}
	onCancel={() => { runTarget = null; }}
/>
