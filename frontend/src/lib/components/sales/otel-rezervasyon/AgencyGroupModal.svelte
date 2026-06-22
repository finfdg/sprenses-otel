<script lang="ts">
	import type { ApiGroup } from '$lib/types/reservation';
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import { Settings2, Trash2, Plus, X } from 'lucide-svelte';

	let {
		show = $bindable(),
		view = $bindable(),
		groups,
		editTarget,
		name = $bindable(),
		members,
		search = $bindable(),
		suggestions,
		saving,
		onEditGroup,
		onAskDelete,
		onClose,
		onNewGroup,
		onRemoveMember,
		onAddMember,
		onSave,
	}: {
		show: boolean;
		view: 'list' | 'form';
		groups: ApiGroup[];
		editTarget: ApiGroup | null;
		name: string;
		members: string[];
		search: string;
		suggestions: string[];
		saving: boolean;
		onEditGroup: (g: ApiGroup) => void;
		onAskDelete: (g: ApiGroup) => void;
		onClose: () => void;
		onNewGroup: () => void;
		onRemoveMember: (name: string) => void;
		onAddMember: (name: string) => void;
		onSave: () => void;
	} = $props();
</script>

<!-- ══════════════════════════════════════════════════════
     Acente Grup Yönetim Modalı (Liste + Form tek modal)
     Not: Modal.svelte ayrı footer slotu desteklemez; butonlar
     içeriğin sonuna yerleştirilir.
     ══════════════════════════════════════════════════════ -->
<Modal
	bind:show
	title={view === 'list' ? 'Acente Gruplarını Yönet' : (editTarget ? `Grubu Düzenle: ${editTarget.name}` : 'Yeni Acente Grubu')}
	maxWidth={view === 'list' ? 'max-w-2xl' : 'max-w-lg'}
>
	{#if view === 'list'}
		<div class="space-y-2.5">
			{#each groups as g (g.id)}
				<div class="border border-gray-200 rounded-lg p-3 flex items-start gap-3">
					<div class="flex-1 min-w-0">
						<div class="font-semibold text-sm text-gray-900 mb-1.5">{g.name}</div>
						<div class="flex flex-wrap gap-1">
							{#each g.members as m}
								<span class="bg-teal-50 text-teal-700 text-xs px-2 py-0.5 rounded-full border border-teal-200">{m}</span>
							{/each}
							{#if g.members.length === 0}
								<span class="text-xs text-gray-500 italic">Üye yok</span>
							{/if}
						</div>
					</div>
					<div class="flex gap-1 shrink-0">
						<button onclick={() => onEditGroup(g)}
							class="touch-target flex items-center justify-center text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded transition-colors cursor-pointer" title="Düzenle" aria-label="Düzenle">
							<Settings2 size={15} />
						</button>
						<button onclick={() => onAskDelete(g)}
							class="touch-target flex items-center justify-center text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors cursor-pointer" title="Sil" aria-label="Sil">
							<Trash2 size={15} />
						</button>
					</div>
				</div>
			{/each}
			{#if groups.length === 0}
				<p class="text-sm text-gray-500 text-center py-6">Henüz grup tanımlanmamış</p>
			{/if}
		</div>

		<!-- Liste alt aksiyonları -->
		<div class="flex justify-end gap-2 pt-4 mt-4 border-t border-gray-200">
			<Button variant="secondary" onclick={onClose}>Kapat</Button>
			<Button onclick={onNewGroup}><Plus size={15} /> Yeni Grup</Button>
		</div>
	{:else}
		<div class="space-y-4">
			<div>
				<label for="gm-name" class="block text-sm font-medium text-gray-700 mb-1">
					Grup Adı <span class="text-red-600">*</span>
				</label>
				<Input
					id="gm-name"
					type="text"
					size="sm"
					bind:value={name}
					placeholder="örn: ALLTOURS"
					oninput={(e) => { name = (e.target as HTMLInputElement).value.toUpperCase(); }}
				/>
			</div>
			<div>
				<span class="block text-sm font-medium text-gray-700 mb-1">Acenteler</span>
				<div class="flex flex-wrap gap-1.5 min-h-[40px] p-2 bg-gray-50 border border-gray-200 rounded-lg mb-2">
					{#each members as m}
						<span class="inline-flex items-center gap-1 bg-teal-100 text-teal-800 text-xs px-2 py-1 rounded-full">
							{m}
							<button onclick={() => onRemoveMember(m)} class="hover:text-red-600 ml-0.5 cursor-pointer" aria-label="Üyeyi çıkar">
								<X size={11} />
							</button>
						</span>
					{/each}
					{#if members.length === 0}
						<span class="text-xs text-gray-500 self-center">Henüz üye eklenmedi</span>
					{/if}
				</div>
				<div class="relative">
					<Input
						type="text"
						size="sm"
						bind:value={search}
						placeholder="Acente adı ara ve ekle…"
					/>
					{#if suggestions.length > 0}
						<div class="absolute z-20 top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
							{#each suggestions as s}
								<button onclick={() => onAddMember(s)}
									class="w-full text-left px-3 py-2 text-sm hover:bg-teal-50 hover:text-teal-700 transition-colors cursor-pointer">
									{s}
								</button>
							{/each}
						</div>
					{/if}
				</div>
				<p class="text-xs text-gray-500 mt-1.5">
					Yalnızca mevcut rezervasyon verilerinde görünen ve başka gruba atanmamış acenteler önerilir.
				</p>
			</div>
		</div>

		<!-- Form alt aksiyonları -->
		<div class="flex justify-end gap-2 pt-4 mt-4 border-t border-gray-200">
			<Button variant="secondary" onclick={() => (view = 'list')}>← Geri</Button>
			<Button onclick={onSave} loading={saving} disabled={!name.trim()}>{editTarget ? 'Kaydet' : 'Oluştur'}</Button>
		</div>
	{/if}
</Modal>
