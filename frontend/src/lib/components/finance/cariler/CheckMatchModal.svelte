<script lang="ts">
	import { formatCurrency } from '$lib/utils/finance';
	import Modal from '$lib/components/Modal.svelte';
	import Input from '$lib/components/Input.svelte';
	import { Search, Loader2 } from 'lucide-svelte';

	interface CandidateCheck {
		id: number;
		check_no: string;
		vendor_name: string;
		vendor_code: string | null;
		due_date: string;
		amount_tl: number;
		currency: string;
		amount_currency: number | null;
		description: string | null;
		score: number;
	}

	let {
		show = $bindable(),
		vtxAmount,
		loading,
		checks,
		search = $bindable(),
		onMatch,
	}: {
		show: boolean;
		vtxAmount: number;
		loading: boolean;
		checks: CandidateCheck[];
		search: string;
		onMatch: (checkId: number) => void;
	} = $props();

	let filtered = $derived.by(() => {
		if (!search) return checks;
		const q = search.toLowerCase();
		return checks.filter(c =>
			c.check_no?.toLowerCase().includes(q) ||
			c.vendor_name?.toLowerCase().includes(q) ||
			c.description?.toLowerCase().includes(q)
		);
	});

	function formatDate(dateStr: string): string {
		const d = new Date(dateStr);
		return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}
</script>

<!-- Çek Eşleştirme Modal -->
<Modal bind:show title="Çek ile Eşleştir" maxWidth="2xl">
	<div class="space-y-4 py-2">
		<!-- Üst bilgi -->
		<div class="bg-gray-50 rounded-xl p-3 text-sm">
			<span class="text-gray-500">Eşleştirilecek tutar:</span>
			<span class="font-bold text-gray-900 ml-1">{formatCurrency(vtxAmount)}</span>
		</div>

		<!-- Arama -->
		<Input
			type="search"
			size="sm"
			icon={Search}
			clearable
			bind:value={search}
			placeholder="Çek no, firma adı veya açıklama ile ara..."
		/>

		<!-- Çek listesi -->
		{#if loading}
			<div class="flex items-center justify-center py-8 text-teal-700">
				<Loader2 size={24} class="animate-spin" />
			</div>
		{:else if filtered.length === 0}
			<div class="text-center py-8 text-gray-500">
				<p class="text-sm">Eşleştirilebilecek çek bulunamadı</p>
				<p class="text-xs mt-1">Tüm çekler zaten eşleştirilmiş veya ödenmiş</p>
			</div>
		{:else}
			<div class="max-h-[400px] overflow-y-auto space-y-2">
				{#each filtered as check}
					{@const amountMatch = Math.abs(check.amount_tl - vtxAmount) < 0.01}
					<button
						onclick={() => onMatch(check.id)}
						class="w-full text-left p-3 rounded-xl border transition-all cursor-pointer
							{amountMatch
								? 'border-teal-300 bg-teal-50/50 hover:bg-teal-50 hover:border-teal-400'
								: 'border-gray-200 bg-white hover:bg-gray-50 hover:border-gray-300'}"
					>
						<div class="flex items-center justify-between">
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2">
									<span class="text-xs font-mono font-bold text-gray-900">{check.check_no}</span>
									{#if amountMatch}
										<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-teal-100 text-teal-700">Tutar eşleşiyor</span>
									{/if}
									{#if check.score >= 50}
										<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700">Önerilen</span>
									{/if}
								</div>
								<p class="text-xs text-gray-600 mt-0.5 truncate">{check.vendor_name}</p>
								{#if check.description}
									<p class="text-[10px] text-gray-500 truncate">{check.description}</p>
								{/if}
							</div>
							<div class="text-right ml-3 shrink-0">
								<p class="text-sm font-bold {amountMatch ? 'text-teal-700' : 'text-gray-900'}">{formatCurrency(check.amount_tl)}</p>
								<p class="text-[10px] text-gray-500">Vade: {formatDate(check.due_date)}</p>
							</div>
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>
</Modal>
