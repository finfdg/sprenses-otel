<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';
	import Select from '$lib/components/Select.svelte';

	interface DeptOption {
		id: number;
		name: string;
		code: string;
		manager_name: string | null;
	}
	interface CatOption {
		id: number;
		name: string;
		type: string;
	}

	let {
		show = $bindable(),
		txDesc,
		txAmount,
		departments,
		budgetCategories,
		selectedDeptId = $bindable(),
		selectedCatId = $bindable(),
		assigning,
		onAssign,
	}: {
		show: boolean;
		txDesc: string;
		txAmount: string;
		departments: DeptOption[];
		budgetCategories: CatOption[];
		selectedDeptId: number | null;
		selectedCatId: number | null;
		assigning: boolean;
		onAssign: () => void;
	} = $props();
</script>

<!-- Departman Atama Modalı -->
<Modal bind:show title="Departmana Ata" maxWidth="max-w-md">
	<div class="space-y-4">
		<div class="bg-gray-50 rounded-lg p-3 text-sm">
			<p class="text-gray-600">{txDesc}</p>
			<p class="font-semibold text-teal-600 mt-1">{txAmount}</p>
		</div>

		<div>
			<label for="dept-select" class="block text-sm font-medium text-gray-700 mb-1">Departman</label>
			<Select id="dept-select" size="sm" bind:value={selectedDeptId}>
				<option value={null}>Seçiniz...</option>
				{#each departments.filter(d => d.manager_name) as dept}
					<option value={dept.id}>{dept.name} — {dept.manager_name}</option>
				{/each}
			</Select>
		</div>

		<div>
			<label for="cat-select" class="block text-sm font-medium text-gray-700 mb-1">Bütçe Kategorisi (opsiyonel)</label>
			<Select id="cat-select" size="sm" bind:value={selectedCatId}>
				<option value={null}>Seçiniz...</option>
				{#each budgetCategories.filter(c => c.type === 'expense') as cat}
					<option value={cat.id}>{cat.name}</option>
				{/each}
			</Select>
		</div>

		<div class="flex items-center justify-end gap-3 pt-2">
				<Button variant="secondary" onclick={() => { show = false; }}>İptal</Button>
				<Button onclick={onAssign} loading={assigning} disabled={!selectedDeptId || assigning}>{assigning ? 'Atanıyor...' : 'Departmana Ata'}</Button>
		</div>
	</div>
</Modal>
