<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { marked } from 'marked';
	import hljs from 'highlight.js/lib/core';
	import python from 'highlight.js/lib/languages/python';
	import typescript from 'highlight.js/lib/languages/typescript';
	import javascript from 'highlight.js/lib/languages/javascript';
	import xml from 'highlight.js/lib/languages/xml';
	import css from 'highlight.js/lib/languages/css';
	import json from 'highlight.js/lib/languages/json';
	import bash from 'highlight.js/lib/languages/bash';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import Button from '$lib/components/Button.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Input from '$lib/components/Input.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { FileText, Download, Eye, Search, Library, FolderOpen, FileStack } from 'lucide-svelte';

	hljs.registerLanguage('python', python);
	hljs.registerLanguage('typescript', typescript);
	hljs.registerLanguage('javascript', javascript);
	hljs.registerLanguage('xml', xml);
	hljs.registerLanguage('css', css);
	hljs.registerLanguage('json', json);
	hljs.registerLanguage('bash', bash);
	// Dosya uzantısı → highlight.js dili (.svelte/.html → xml ile şablon vurgusu)
	const HL_LANG: Record<string, string> = {
		py: 'python', ts: 'typescript', js: 'javascript', svelte: 'xml',
		html: 'xml', css: 'css', json: 'json', sh: 'bash',
	};

	interface Doc { path: string; title: string; module_codes?: string[]; category: string; size: number; modified: string; }

	// State
	let docs = $state<Doc[]>([]);
	let loading = $state(true);
	let cat = $state('');
	let q = $state('');
	let exporting = $state(false);
	let downloading = $state('');
	// Görüntüleme modalı
	let viewOpen = $state(false);
	let viewLoading = $state(false);
	let viewTitle = $state('');
	let viewPath = $state('');
	let viewHtml = $state('');

	// Türetilmiş
	let catOptions = $derived([
		{ value: '', label: 'Tümü', count: docs.length },
		...Array.from(new Set(docs.map((d) => d.category))).map((c) => ({
			value: c, label: c, count: docs.filter((d) => d.category === c).length,
		})),
	]);
	let filtered = $derived(
		docs.filter((d) => {
			if (cat && d.category !== cat) return false;
			const term = q.trim().toLocaleLowerCase('tr');
			return !term || `${d.title} ${d.path} ${(d.module_codes ?? []).join(' ')}`.toLocaleLowerCase('tr').includes(term);
		}),
	);
	let grouped = $derived.by(() => {
		const m = new Map<string, Doc[]>();
		for (const d of filtered) {
			if (!m.has(d.category)) m.set(d.category, []);
			m.get(d.category)!.push(d);
		}
		return [...m.entries()];
	});

	// Yardımcılar
	function fmtSize(n: number): string {
		return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(0)} KB`;
	}
	function fmtDate(iso: string): string {
		try { return new Date(iso).toLocaleDateString('tr-TR'); } catch { return ''; }
	}
	async function saveBlob(blob: Blob, name: string) {
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url; a.download = name; a.click();
		URL.revokeObjectURL(url);
	}

	// Veri
	async function load() {
		loading = true;
		try {
			const res = await api.get<{ items: Doc[] }>('/system/docs/');
			docs = res.items;
		} catch (e) {
			console.error('Dokümanlar yüklenemedi:', e);
			showToast('Dokümanlar yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	async function viewDoc(d: Doc) {
		viewOpen = true; viewLoading = true; viewTitle = d.title; viewPath = d.path; viewHtml = '';
		try {
			const res = await api.get<{ content: string }>(`/system/docs/raw?path=${encodeURIComponent(d.path)}`);
			// İçerik bizim kendi commit'li repo dosyalarımız + yalnız system.docs yetkili erişir (güvenilir kaynak)
			const ext = (d.path.split('.').pop() || '').toLowerCase();
			if (ext === 'md') {
				viewHtml = marked.parse(res.content, { async: false }) as string;
			} else {
				// Kaynak kod → syntax highlight (hljs çıktısı HTML-escape'li → güvenli)
				const lang = HL_LANG[ext];
				const out = lang
					? hljs.highlight(res.content, { language: lang, ignoreIllegals: true })
					: hljs.highlightAuto(res.content);
				viewHtml = `<pre class="hljs"><code>${out.value}</code></pre>`;
			}
		} catch (e) {
			console.error('Doküman açılamadı:', e);
			showToast('Doküman açılamadı', 'error');
			viewOpen = false;
		} finally {
			viewLoading = false;
		}
	}

	async function downloadDoc(d: Doc) {
		downloading = d.path;
		try {
			const res = await api.fetchRaw(`/system/docs/download?path=${encodeURIComponent(d.path)}`);
			if (!res.ok) throw new Error('indirme başarısız');
			await saveBlob(await res.blob(), d.path.replace(/\//g, '_'));
		} catch (e) {
			console.error('İndirme hatası:', e);
			showToast('İndirme başarısız', 'error');
		} finally {
			downloading = '';
		}
	}

	async function exportWord() {
		exporting = true;
		try {
			const res = await api.fetchRaw('/system/docs/export/word');
			if (!res.ok) throw new Error('word üretilemedi');
			await saveBlob(await res.blob(), 'Sprenses-Dokumanlar.docx');
		} catch (e) {
			console.error('Word indirme hatası:', e);
			showToast('Word belgesi oluşturulamadı', 'error');
		} finally {
			exporting = false;
		}
	}

	onMount(load);
</script>

<svelte:head><title>Dokümanlar — Sprenses</title></svelte:head>

<div class="max-w-6xl mx-auto px-3 sm:px-4 py-4 sm:py-6">
	<PageHeader title="Dokümanlar" description="Proje dokümantasyonu — görüntüle ve indir">
		{#snippet actions()}
			<Button onclick={exportWord} loading={exporting}><Download size={16} /> Word olarak indir</Button>
		{/snippet}
	</PageHeader>

	<!-- Özet kartlar -->
	<div class="grid grid-cols-2 sm:grid-cols-3 gap-3 my-4 sm:my-5">
		<StatCard label="Toplam Doküman" value={docs.length} icon={FileText} accent="teal" />
		<StatCard label="Kategori" value={catOptions.length - 1} icon={FolderOpen} accent="blue" />
		<StatCard label="Birleşik Word" value="indirilebilir" icon={FileStack} accent="emerald" hint="Tüm dokümanlar tek dosyada" />
	</div>

	<!-- Filtre barı -->
	<div class="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
		<div class="flex-1 min-w-0">
			<Input bind:value={q} placeholder="Doküman ara…" icon={Search} clearable />
		</div>
		<div class="overflow-x-auto">
			<SegmentedControl options={catOptions} value={cat} onchange={(v) => (cat = v)} size="sm" ariaLabel="Kategori filtresi" />
		</div>
	</div>

	<!-- İçerik -->
	{#if loading}
		<TableSkeleton rows={8} columns={3} />
	{:else if filtered.length === 0}
		<EmptyState icon={Library} title="Doküman bulunamadı" description={q || cat ? 'Filtreyle eşleşen doküman yok.' : 'Henüz doküman yok.'} />
	{:else}
		<div class="space-y-5">
			{#each grouped as [category, items] (category)}
				<section>
					<h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
						<FolderOpen size={14} /> {category} <span class="text-gray-400 font-normal">({items.length})</span>
					</h2>
					<div class="bg-white border border-gray-200 rounded-2xl shadow-sm divide-y divide-gray-100 overflow-hidden">
						{#each items as d (d.path)}
							<div class="flex items-center gap-3 px-3 sm:px-4 py-3 hover:bg-gray-50 transition-colors">
								<div class="shrink-0 w-9 h-9 rounded-lg bg-teal-50 text-teal-600 flex items-center justify-center">
									<FileText size={18} />
								</div>
								<button onclick={() => viewDoc(d)} class="min-w-0 flex-1 text-left cursor-pointer touch-target">
									<div class="flex items-center gap-1.5 flex-wrap">
										<span class="text-sm font-medium text-gray-800 truncate">{d.title}</span>
										{#each d.module_codes ?? [] as code (code)}
											<span class="shrink-0 px-1.5 py-0.5 rounded bg-teal-50 text-teal-700 text-[10px] font-mono font-medium">{code}</span>
										{/each}
									</div>
									<div class="text-[11px] text-gray-500 font-mono truncate">{d.path}</div>
								</button>
								<div class="hidden sm:block text-[11px] text-gray-500 text-right shrink-0 tabular-nums">
									<div>{fmtSize(d.size)}</div>
									<div>{fmtDate(d.modified)}</div>
								</div>
								<div class="flex items-center gap-1 shrink-0">
									<Button variant="secondary" size="sm" onclick={() => viewDoc(d)}><Eye size={15} /><span class="hidden sm:inline ml-1">Görüntüle</span></Button>
									<Button variant="ghost" size="sm" loading={downloading === d.path} onclick={() => downloadDoc(d)} ariaLabel="İndir"><Download size={15} /></Button>
								</div>
							</div>
						{/each}
					</div>
				</section>
			{/each}
		</div>
	{/if}
</div>

<!-- Görüntüleme modalı -->
<Modal bind:show={viewOpen} title={viewTitle} maxWidth="max-w-4xl">
	<div class="text-[11px] text-gray-500 font-mono mb-3 flex items-center justify-between gap-2 flex-wrap">
		<span class="truncate">{viewPath}</span>
		<Button variant="secondary" size="sm" onclick={() => { const d = docs.find((x) => x.path === viewPath); if (d) downloadDoc(d); }}><Download size={14} /> İndir</Button>
	</div>
	{#if viewLoading}
		<TableSkeleton rows={10} columns={1} showHeader={false} />
	{:else}
		<div class="doc-content max-h-[65vh] overflow-y-auto pr-1">
			<!-- eslint-disable-next-line svelte/no-at-html-tags -- güvenilir kaynak: kendi repo dokümanlarımız, yalnız system.docs yetkili -->
			{@html viewHtml}
		</div>
	{/if}
</Modal>

<style>
	/* {@html} ile basılan markdown içeriği Svelte scope'una girmez → :global gerekir */
	.doc-content :global(h1) { font-size: 1.4rem; font-weight: 700; color: #0f766e; margin: 1rem 0 0.6rem; border-bottom: 1px solid #99f6e4; padding-bottom: 0.3rem; }
	.doc-content :global(h2) { font-size: 1.2rem; font-weight: 700; color: #155e63; margin: 1rem 0 0.5rem; }
	.doc-content :global(h3) { font-size: 1.05rem; font-weight: 700; color: #334155; margin: 0.8rem 0 0.4rem; }
	.doc-content :global(h4) { font-size: 0.95rem; font-weight: 700; color: #475569; margin: 0.7rem 0 0.3rem; }
	.doc-content :global(p) { margin: 0.5rem 0; line-height: 1.6; color: #1f2937; }
	.doc-content :global(ul), .doc-content :global(ol) { margin: 0.4rem 0 0.6rem 1.4rem; line-height: 1.6; }
	.doc-content :global(li) { margin: 0.2rem 0; }
	.doc-content :global(code) { font-family: Consolas, monospace; font-size: 0.85em; background: #f1f5f9; color: #b5176c; padding: 0.1em 0.35em; border-radius: 4px; }
	.doc-content :global(pre) { background: #f4f4f5; border: 1px solid #e4e4e7; border-radius: 8px; padding: 0.75rem 1rem; overflow-x: auto; margin: 0.6rem 0; }
	.doc-content :global(pre code) { background: none; color: #334155; padding: 0; }
	.doc-content :global(table) { border-collapse: collapse; width: 100%; margin: 0.6rem 0; font-size: 0.85rem; display: block; overflow-x: auto; }
	.doc-content :global(th), .doc-content :global(td) { border: 1px solid #d1d5db; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }
	.doc-content :global(th) { background: #f0fdfa; font-weight: 600; }
	.doc-content :global(a) { color: #0d9488; text-decoration: underline; }
	.doc-content :global(blockquote) { border-left: 3px solid #99f6e4; padding-left: 0.8rem; margin: 0.5rem 0; color: #475569; }
	.doc-content :global(hr) { border: none; border-top: 1px solid #e5e7eb; margin: 1rem 0; }
	.doc-content :global(strong) { font-weight: 700; }
	/* Kaynak kod — highlight.js token renkleri (mevcut pre kutusu korunur, sadece renkler) */
	.doc-content :global(pre.hljs) { font-size: 0.8rem; line-height: 1.5; }
	.doc-content :global(pre.hljs code) { font-family: Consolas, 'SF Mono', Menlo, monospace; white-space: pre; }
	.doc-content :global(.hljs-comment), .doc-content :global(.hljs-quote) { color: #6b7280; font-style: italic; }
	.doc-content :global(.hljs-keyword), .doc-content :global(.hljs-selector-tag), .doc-content :global(.hljs-literal) { color: #8250df; }
	.doc-content :global(.hljs-string), .doc-content :global(.hljs-meta-string) { color: #0a7d22; }
	.doc-content :global(.hljs-number), .doc-content :global(.hljs-symbol) { color: #b35900; }
	.doc-content :global(.hljs-title), .doc-content :global(.hljs-title.function_), .doc-content :global(.hljs-section) { color: #0550ae; }
	.doc-content :global(.hljs-title.class_), .doc-content :global(.hljs-built_in), .doc-content :global(.hljs-type) { color: #0a7d8c; }
	.doc-content :global(.hljs-attr), .doc-content :global(.hljs-attribute), .doc-content :global(.hljs-property) { color: #0550ae; }
	.doc-content :global(.hljs-tag), .doc-content :global(.hljs-name) { color: #116329; }
	.doc-content :global(.hljs-meta), .doc-content :global(.hljs-decorator) { color: #953800; }
	.doc-content :global(.hljs-variable), .doc-content :global(.hljs-template-variable) { color: #953800; }
</style>
