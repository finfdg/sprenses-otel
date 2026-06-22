<script lang="ts">
	import type { Vendor } from '$lib/types/vendor';
	import { formatCurrency } from '$lib/utils/finance';
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';

	let {
		show = $bindable(),
		vendor,
		lists,
		selectedListId = $bindable(),
		newName = $bindable(),
		adding,
		onConfirm,
	}: {
		show: boolean;
		vendor: Vendor | null;
		lists: { id: number; name: string; item_count: number }[];
		selectedListId: number | '';
		newName: string;
		adding: boolean;
		onConfirm: () => void;
	} = $props();
</script>

<!-- Ödeme Talimatına Ekle Modal -->
<Modal bind:show title="Ödeme Talimatına Ekle" maxWidth="max-w-md">
	{#if vendor}
		<div class="space-y-4 text-sm">
			<div class="bg-gray-50 rounded-lg p-3">
				<div class="font-medium text-gray-800">{vendor.hesap_adi}</div>
				<div class="text-xs text-gray-500 mt-0.5">{vendor.hesap_kodu}</div>
				<div class="text-xs mt-1.5">
					Ödenecek tutar:
					<span class="font-bold {vendor.bakiye < 0 ? 'text-rose-600' : 'text-gray-500'}">
						{formatCurrency(vendor.bakiye < 0 ? -vendor.bakiye : 0)}
					</span>
					<span class="text-gray-500">(bakiyeden — listede düzenlenebilir)</span>
				</div>
			</div>

			{#if lists.length > 0}
				<div>
					<label for="pi-list-select" class="text-xs text-gray-500 mb-1 block">Mevcut Listeye Ekle</label>
					<Select id="pi-list-select" size="sm" bind:value={selectedListId}>
						{#each lists as l (l.id)}
							<option value={l.id}>{l.name} ({l.item_count} cari)</option>
						{/each}
					</Select>
				</div>
				<div class="text-center text-xs text-gray-500">— veya —</div>
			{/if}

			<div>
				<label for="pi-new-name" class="text-xs text-gray-500 mb-1 block">Yeni Liste Oluştur</label>
				<Input id="pi-new-name" size="sm" bind:value={newName} placeholder="ör: Haftalık Ödeme 26.05" />
				<p class="text-[11px] text-gray-500 mt-1">Ad girerseniz yeni liste oluşturulur, aksi halde seçili listeye eklenir.</p>
			</div>

			<div class="flex items-center justify-end gap-2 pt-1">
				<Button variant="secondary" onclick={() => { show = false; }}>Vazgeç</Button>
				<Button onclick={onConfirm} loading={adding}>Ekle</Button>
			</div>
		</div>
	{/if}
</Modal>
