<script lang="ts">
	// Panel "Günün Özeti" kartı — /api/ai/gunun-ozeti'den deterministik özet (AI çağrısı yok).
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { Sparkles, ArrowRight } from 'lucide-svelte';

	interface Section {
		baslik: string;
		adet?: number;
		para_bazli?: { para_birimi: string; toplam: number }[];
		toplam_tl?: number;
		oda?: number;
	}

	let bolumler = $state<Section[]>([]);
	let loaded = $state(false);

	const nf = (n: number) => new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(n);

	function ozet(b: Section): string {
		if (b.para_bazli && b.para_bazli.length)
			return b.para_bazli.map((p) => `${nf(p.toplam)} ${p.para_birimi}`).join(' + ');
		if (b.toplam_tl !== undefined) return `${b.adet} çek · ${nf(b.toplam_tl)} ₺`;
		if (b.oda !== undefined) return `${b.adet} rezervasyon · ${b.oda} oda`;
		return String(b.adet ?? '—');
	}

	onMount(async () => {
		try {
			const d = await api.get<{ bolumler: Section[] }>('/ai/gunun-ozeti');
			bolumler = d.bolumler ?? [];
		} catch (e) {
			console.error('Günün özeti yüklenemedi:', e);
		} finally {
			loaded = true;
		}
	});
</script>

{#if loaded && bolumler.length > 0}
	<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4">
		<div class="flex items-center justify-between mb-3">
			<div class="flex items-center gap-2">
				<span class="w-7 h-7 rounded-lg bg-teal-50 flex items-center justify-center">
					<Sparkles class="w-4 h-4 text-teal-700" />
				</span>
				<h3 class="text-base text-gray-900">Günün Özeti</h3>
			</div>
			<a
				href="/dashboard/asistan"
				class="text-xs text-teal-700 hover:text-teal-800 inline-flex items-center gap-1"
			>
				Asistan'a sor <ArrowRight class="w-3.5 h-3.5" />
			</a>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
			{#each bolumler as b}
				<div class="rounded-xl bg-gray-50 border border-gray-100 p-3">
					<p class="text-xs text-gray-500">{b.baslik}</p>
					<p class="text-sm font-semibold text-gray-800 mt-1 tabular-nums">{ozet(b)}</p>
				</div>
			{/each}
		</div>
	</div>
{/if}
