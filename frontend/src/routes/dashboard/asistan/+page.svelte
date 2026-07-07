<script lang="ts">
	import { tick } from 'svelte';
	import { marked } from 'marked';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import AiChart from '$lib/components/AiChart.svelte';
	import { Sparkles, Send, Bot, User as UserIcon } from 'lucide-svelte';

	interface ChartPoint { etiket: string; deger: number; }
	interface Chart { tip: string; baslik?: string; para_birimi?: string; seri: ChartPoint[]; }

	interface ChatMessage {
		role: 'user' | 'assistant';
		text: string;
		tools?: string[];
		charts?: Chart[];
	}

	interface PendingAction {
		action_key: string;
		entity_id: number;
		payload: Record<string, unknown>;
		ozet: string;
	}

	interface AskResponse {
		cevap: string;
		kullanilan_araclar: string[];
		bekleyen_islem?: PendingAction | null;
		grafikler?: Chart[] | null;
	}

	const ORNEK_SORULAR = [
		'Bu ay nakit akışı nasıl?',
		'Önümüzdeki 30 günde vadesi gelen çekler neler?',
		'En borçlu 5 cari kim?'
	];

	let messages = $state<ChatMessage[]>([]);
	let input = $state('');
	let loading = $state(false);
	let scrollBox = $state<HTMLDivElement | null>(null);
	// Faz 2 — yazma işlemi onay akışı
	let pendingAction = $state<PendingAction | null>(null);
	let showConfirm = $state(false);
	let executing = $state(false);

	// Güvenli markdown: LLM çıktısı olduğu için ÖNCE tüm HTML'i escape et (script/HTML
	// enjeksiyonu engellenir), SONRA marked ile sadece markdown sözdizimini render et.
	// Böylece tablo/kalın/liste biçimlenir ama ham <script>/<img onerror> HTML'i geçemez.
	function renderMd(text: string): string {
		const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
		return marked.parse(esc, { async: false }) as string;
	}

	// Mobil kart görünümü için: render edilen markdown tablolarının her hücresine
	// başlık metnini `data-label` olarak ekle (CSS ::before ile mobilde etiket:değer gösterir).
	function enhanceTables(node: HTMLElement) {
		const apply = () => {
			node.querySelectorAll('table').forEach((table) => {
				const headers = Array.from(table.querySelectorAll('thead th')).map(
					(th) => th.textContent?.trim() ?? ''
				);
				table.querySelectorAll('tbody tr').forEach((tr) => {
					Array.from(tr.children).forEach((td, i) => {
						if (headers[i]) td.setAttribute('data-label', headers[i]);
					});
				});
			});
		};
		apply();
		return { update: apply };
	}

	async function scrollToBottom() {
		await tick();
		if (scrollBox) scrollBox.scrollTop = scrollBox.scrollHeight;
	}

	async function gonder(soru?: string) {
		const metin = (soru ?? input).trim();
		if (!metin || loading) return;

		messages.push({ role: 'user', text: metin });
		input = '';
		loading = true;
		await scrollToBottom();

		try {
			const res = await api.post<AskResponse>('/ai/sor', { soru: metin });
			messages.push({
				role: 'assistant',
				text: res.cevap,
				tools: res.kullanilan_araclar ?? [],
				charts: res.grafikler ?? []
			});
			// Yazma önerisi geldiyse kullanıcı onayına sun (ConfirmDialog)
			if (res.bekleyen_islem) {
				pendingAction = res.bekleyen_islem;
				showConfirm = true;
			}
		} catch (err) {
			console.error('Asistan yanıt hatası:', err);
			const msg = err instanceof Error ? err.message : 'Asistan yanıt veremedi';
			showToast(msg, 'error');
			messages.push({
				role: 'assistant',
				text: 'Üzgünüm, şu an yanıt veremedim. Lütfen tekrar deneyin.'
			});
		} finally {
			loading = false;
			await scrollToBottom();
		}
	}

	async function onaylaIslem() {
		showConfirm = false;
		const action = pendingAction;
		pendingAction = null;
		if (!action) return;
		executing = true;
		try {
			const r = await api.post<{ durum: string; mesaj: string }>('/ai/uygula', {
				action_key: action.action_key,
				entity_id: action.entity_id,
				payload: action.payload
			});
			messages.push({ role: 'assistant', text: r.mesaj });
		} catch (err) {
			console.error('İşlem uygulanamadı:', err);
			const msg = err instanceof Error ? err.message : 'İşlem uygulanamadı';
			showToast(msg, 'error');
			messages.push({ role: 'assistant', text: 'İşlem uygulanamadı: ' + msg });
		} finally {
			executing = false;
			await scrollToBottom();
		}
	}

	function iptalIslem() {
		showConfirm = false;
		pendingAction = null;
		messages.push({ role: 'assistant', text: 'İşlem iptal edildi.' });
		scrollToBottom();
	}

	function onKeydown(e: KeyboardEvent) {
		// Enter → gönder, Shift+Enter → yeni satır
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			gonder();
		}
	}
</script>

<svelte:head>
	<title>Yapay Zeka Asistanı — Sprenses</title>
</svelte:head>

<div class="space-y-4">
	<PageHeader
		title="Yapay Zeka Asistanı"
		description="Finans verilerinizi doğal dilde sorgulayın. Asistan yalnız görme yetkiniz olan verilere erişir."
	/>

	<div class="bg-white border border-gray-200 rounded-2xl shadow-sm flex flex-col h-[calc(100vh-16rem)] min-h-[420px]">
		<!-- Mesaj alanı -->
		<div bind:this={scrollBox} class="flex-1 overflow-y-auto p-4 space-y-4">
			{#if messages.length === 0}
				<!-- Boş durum -->
				<div class="h-full flex flex-col items-center justify-center text-center px-4">
					<span class="w-14 h-14 rounded-2xl bg-teal-50 flex items-center justify-center mb-4">
						<Sparkles class="w-7 h-7 text-teal-700" />
					</span>
					<h2 class="text-base font-semibold text-gray-900">Size nasıl yardımcı olabilirim?</h2>
					<p class="text-sm text-gray-500 mt-1 max-w-md">
						Aşağıdaki örneklerden birini seçin ya da kendi sorunuzu yazın.
					</p>
					<div class="flex flex-wrap gap-2 justify-center mt-4 max-w-lg">
						{#each ORNEK_SORULAR as ornek}
							<button
								onclick={() => gonder(ornek)}
								disabled={loading}
								class="text-sm text-teal-700 bg-teal-50 hover:bg-teal-100 border border-teal-200 rounded-full px-3 py-1.5 transition-colors disabled:opacity-50 cursor-pointer"
							>
								{ornek}
							</button>
						{/each}
					</div>
				</div>
			{:else}
				{#each messages as m}
					<div class="flex gap-3 {m.role === 'user' ? 'flex-row-reverse' : ''}">
						<span class="w-8 h-8 rounded-full flex items-center justify-center shrink-0 {m.role === 'user' ? 'bg-gray-100' : 'bg-teal-700'}">
							{#if m.role === 'user'}
								<UserIcon class="w-4 h-4 text-gray-600" />
							{:else}
								<Bot class="w-4 h-4 text-white" />
							{/if}
						</span>
						<div class="max-w-[92%] sm:max-w-[80%] min-w-0">
							{#if m.role === 'user'}
								<div class="rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap bg-teal-700 text-white">
									{m.text}
								</div>
							{:else}
								<div class="md rounded-2xl px-4 py-2.5 text-sm bg-gray-50 text-gray-800 border border-gray-200" use:enhanceTables>
									{@html renderMd(m.text)}
								</div>
							{/if}
							{#if m.charts && m.charts.length > 0}
								{#each m.charts as c}
									<AiChart tip={c.tip} baslik={c.baslik} para_birimi={c.para_birimi} seri={c.seri} />
								{/each}
							{/if}
							{#if m.tools && m.tools.length > 0}
								<p class="text-[11px] text-gray-400 mt-1 px-1">
									Kaynak: {m.tools.join(', ')}
								</p>
							{/if}
						</div>
					</div>
				{/each}
			{/if}

			{#if loading || executing}
				<div class="flex gap-3">
					<span class="w-8 h-8 rounded-full bg-teal-700 flex items-center justify-center shrink-0">
						<Bot class="w-4 h-4 text-white" />
					</span>
					<div class="rounded-2xl px-4 py-3 bg-gray-50 border border-gray-200">
						<span class="flex gap-1">
							<span class="w-2 h-2 rounded-full bg-gray-400 animate-bounce [animation-delay:-0.3s]"></span>
							<span class="w-2 h-2 rounded-full bg-gray-400 animate-bounce [animation-delay:-0.15s]"></span>
							<span class="w-2 h-2 rounded-full bg-gray-400 animate-bounce"></span>
						</span>
					</div>
				</div>
			{/if}
		</div>

		<!-- Giriş alanı -->
		<div class="border-t border-gray-200 p-3">
			<div class="flex items-end gap-2">
				<textarea
					bind:value={input}
					onkeydown={onKeydown}
					disabled={loading}
					rows="1"
					placeholder="Bir soru yazın... (Enter ile gönder)"
					class="flex-1 resize-none rounded-xl border border-gray-300 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 disabled:bg-gray-50 max-h-32"
				></textarea>
				<Button onclick={() => gonder()} loading={loading} disabled={!input.trim()} ariaLabel="Gönder">
					<Send class="w-4 h-4" />
					<span class="hidden sm:inline">Gönder</span>
				</Button>
			</div>
			<p class="text-[11px] text-gray-400 mt-2 px-1">
				Asistan yapay zeka ile çalışır; kritik kararlar öncesi verileri modülünden doğrulayın.
			</p>
		</div>
	</div>
</div>

<!-- Faz 2 — yazma işlemi onay diyaloğu -->
<ConfirmDialog
	bind:show={showConfirm}
	title="İşlemi onaylıyor musunuz?"
	message={pendingAction?.ozet ?? ''}
	confirmText="Onayla ve Uygula"
	cancelText="Vazgeç"
	onConfirm={onaylaIslem}
	onCancel={iptalIslem}
/>

<style>
	/* {@html} ile basılan markdown Svelte scope'una girmez → :global gerekir.
	   Chat balonu için kompakt; ilk/son öğe kenar boşluğu sıfırlanır. */
	.md :global(> :first-child) { margin-top: 0; }
	.md :global(> :last-child) { margin-bottom: 0; }
	.md :global(p) { margin: 0.4rem 0; line-height: 1.6; }
	.md :global(ul), .md :global(ol) { margin: 0.4rem 0 0.4rem 1.3rem; line-height: 1.6; }
	.md :global(li) { margin: 0.15rem 0; }
	.md :global(strong) { font-weight: 700; }
	.md :global(h1), .md :global(h2), .md :global(h3), .md :global(h4) { font-weight: 700; margin: 0.6rem 0 0.35rem; line-height: 1.3; }
	.md :global(h1) { font-size: 1.05rem; }
	.md :global(h2) { font-size: 1rem; }
	.md :global(h3), .md :global(h4) { font-size: 0.925rem; }
	.md :global(code) { font-family: Consolas, monospace; font-size: 0.85em; background: #eef2f7; color: #b5176c; padding: 0.1em 0.35em; border-radius: 4px; }
	.md :global(pre) { background: #f4f4f5; border: 1px solid #e4e4e7; border-radius: 8px; padding: 0.6rem 0.8rem; overflow-x: auto; margin: 0.5rem 0; }
	.md :global(pre code) { background: none; color: #334155; padding: 0; }
	.md :global(table) { border-collapse: collapse; width: 100%; margin: 0.5rem 0; font-size: 0.8rem; display: block; overflow-x: auto; }
	.md :global(th), .md :global(td) { border: 1px solid #d1d5db; padding: 0.35rem 0.55rem; text-align: left; vertical-align: top; white-space: nowrap; }
	.md :global(th) { background: #f0fdfa; font-weight: 600; }
	.md :global(a) { color: #0d9488; text-decoration: underline; }
	.md :global(blockquote) { border-left: 3px solid #99f6e4; padding-left: 0.7rem; margin: 0.4rem 0; color: #475569; }
	.md :global(hr) { border: none; border-top: 1px solid #e5e7eb; margin: 0.7rem 0; }

	/* Mobil (<640px): tablo → etiket:değer kart görünümü (projenin tablo→kart standardı).
	   thead gizlenir; her satır bir kart; her hücre solda başlık (data-label) sağda değer. */
	@media (max-width: 639px) {
		.md :global(table) { font-size: 0.8rem; }
		.md :global(thead) { display: none; }
		.md :global(tbody tr) {
			display: block;
			border: 1px solid #e5e7eb;
			border-radius: 8px;
			padding: 0.25rem 0.6rem;
			margin: 0 0 0.5rem;
			background: #fff;
		}
		.md :global(tbody td) {
			display: flex;
			justify-content: space-between;
			gap: 0.75rem;
			border: none;
			padding: 0.25rem 0;
			white-space: normal;
			text-align: right;
		}
		.md :global(tbody td:not(:last-child)) { border-bottom: 1px solid #f1f5f9; }
		.md :global(tbody td::before) {
			content: attr(data-label);
			font-weight: 600;
			color: #6b7280;
			text-align: left;
			margin-right: 0.5rem;
		}
		/* Boş hücreler (ör. Toplam satırının boş kolonları) kartta yer kaplamasın */
		.md :global(tbody td:empty) { display: none; }
	}
</style>
