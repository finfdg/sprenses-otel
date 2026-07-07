<script lang="ts">
	import { tick } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import { Sparkles, Send, Bot, User as UserIcon } from 'lucide-svelte';

	interface ChatMessage {
		role: 'user' | 'assistant';
		text: string;
		tools?: string[];
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
			const res = await api.post<{ cevap: string; kullanilan_araclar: string[] }>(
				'/ai/sor',
				{ soru: metin }
			);
			messages.push({
				role: 'assistant',
				text: res.cevap,
				tools: res.kullanilan_araclar ?? []
			});
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
						<div class="max-w-[80%]">
							<div class="rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap {m.role === 'user' ? 'bg-teal-700 text-white' : 'bg-gray-50 text-gray-800 border border-gray-200'}">
								{m.text}
							</div>
							{#if m.tools && m.tools.length > 0}
								<p class="text-[11px] text-gray-400 mt-1 px-1">
									Kaynak: {m.tools.join(', ')}
								</p>
							{/if}
						</div>
					</div>
				{/each}
			{/if}

			{#if loading}
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
