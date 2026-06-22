<script lang="ts">
	import type { UploadResult } from '$lib/types/reservation';
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';
	import { Trash2 } from 'lucide-svelte';

	let {
		show = $bindable(),
		result,
		canUse,
		onReviewRemovals,
	}: {
		show: boolean;
		result: UploadResult | null;
		canUse: boolean;
		onReviewRemovals: () => void;
	} = $props();

	function formatInt(n: number): string {
		if (n == null || isNaN(n)) return '-';
		return new Intl.NumberFormat('tr-TR').format(n);
	}
	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		const d = new Date(iso);
		return new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(d);
	}
</script>

<!-- ── Yükleme Sonuç Modalı ── -->
<Modal bind:show title="Yükleme Sonucu" maxWidth="max-w-md">
	{#if result}
		<div class="space-y-3 text-sm">
			<div class="bg-teal-50 rounded-lg p-3 text-teal-900">
				<div class="font-semibold">{result.hotel_name ?? 'Bilinmeyen otel'}</div>
				<div class="text-xs text-teal-700 mt-0.5">
					{result.file_name}
				</div>
				{#if result.period_checkin_start}
					<div class="text-xs text-teal-700 mt-1">
						Check-in: {formatDate(result.period_checkin_start)} → {formatDate(result.period_checkin_end)}
					</div>
				{/if}
			</div>

			<div class="grid grid-cols-3 gap-2">
				<div class="bg-gray-50 rounded-lg p-3 text-center">
					<div class="text-[10px] text-gray-500 uppercase font-semibold">Toplam</div>
					<div class="text-2xl font-bold text-gray-900 mt-1">{formatInt(result.total_rows)}</div>
				</div>
				<div class="bg-emerald-50 rounded-lg p-3 text-center">
					<div class="text-[10px] text-emerald-700 uppercase font-semibold">Yeni</div>
					<div class="text-2xl font-bold text-emerald-700 mt-1">{formatInt(result.new_rows)}</div>
				</div>
				<div class="bg-amber-50 rounded-lg p-3 text-center">
					<div class="text-[10px] text-amber-700 uppercase font-semibold">Güncellenen</div>
					<div class="text-2xl font-bold text-amber-700 mt-1">{formatInt(result.updated_rows)}</div>
				</div>
			</div>

			{#if result.removal_candidates.length > 0}
				<div class="bg-rose-50 border border-rose-200 rounded-lg p-3">
					<div class="flex items-start gap-2">
						<Trash2 size={16} class="text-rose-600 mt-0.5 shrink-0" />
						<div class="flex-1 min-w-0">
							<div class="font-semibold text-rose-900 text-sm">
								{formatInt(result.removal_candidates.length)} olası iptal tespit edildi
							</div>
							<div class="text-xs text-rose-700 mt-1 leading-snug">
								Bu kayıtlar yüklemenin kapsamında (check-in &amp; kayıt tarihi)
								olduğu halde son Excel'de bulunmuyor — büyük olasılıkla kaynak
								sistemde iptal edilmişler.
							</div>
							{#if canUse}
								<Button variant="danger" size="sm" class="mt-2" onclick={onReviewRemovals}>
									<Trash2 size={12} />
									Kayıtları İncele
								</Button>
							{/if}
						</div>
					</div>
				</div>
			{/if}

			<Button fullWidth class="mt-2" onclick={() => (show = false)}>Tamam</Button>
		</div>
	{/if}
</Modal>
