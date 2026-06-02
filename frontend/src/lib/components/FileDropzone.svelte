<script lang="ts" module>
	export function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}

	export function validateFiles(files: File[], accept: string, maxSize: number): { valid: File[]; errors: string[] } {
		const errors: string[] = [];
		const valid: File[] = [];
		const acceptList = accept
			.split(',')
			.map((s) => s.trim())
			.filter(Boolean);
		for (const file of files) {
			if (maxSize > 0 && file.size > maxSize) {
				errors.push(`${file.name}: boyut ${formatSize(file.size)} > sınır ${formatSize(maxSize)}`);
				continue;
			}
			if (acceptList.length > 0) {
				const matches = acceptList.some((pattern) => {
					if (pattern.startsWith('.')) {
						return file.name.toLowerCase().endsWith(pattern.toLowerCase());
					}
					if (pattern.endsWith('/*')) {
						const prefix = pattern.slice(0, -1); // "image/"
						return file.type.startsWith(prefix);
					}
					return file.type === pattern;
				});
				if (!matches) {
					errors.push(`${file.name}: tür desteklenmiyor`);
					continue;
				}
			}
			valid.push(file);
		}
		return { valid, errors };
	}
</script>

<script lang="ts">
	import { Upload } from 'lucide-svelte';

	let {
		accept = '',
		maxSize = 0,
		multiple = false,
		disabled = false,
		label = 'Dosyayı buraya sürükleyin veya tıklayın',
		hint = '',
		onSelect,
		onError
	}: {
		accept?: string;
		maxSize?: number;
		multiple?: boolean;
		disabled?: boolean;
		label?: string;
		hint?: string;
		onSelect: (files: File[]) => void;
		onError?: (errors: string[]) => void;
	} = $props();

	let dragOver = $state(false);
	let inputEl = $state<HTMLInputElement | null>(null);

	function handleFiles(files: FileList | File[] | null) {
		if (!files || disabled) return;
		const arr = Array.from(files);
		if (arr.length === 0) return;
		const result = validateFiles(arr, accept, maxSize);
		if (result.errors.length > 0) onError?.(result.errors);
		if (result.valid.length > 0) onSelect(result.valid);
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
		handleFiles(e.dataTransfer?.files ?? null);
	}

	function onDragOver(e: DragEvent) {
		e.preventDefault();
		if (!disabled) dragOver = true;
	}

	function onDragLeave() {
		dragOver = false;
	}

	function onInputChange(e: Event) {
		const t = e.target as HTMLInputElement;
		handleFiles(t.files);
		t.value = '';
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	ondrop={onDrop}
	ondragover={onDragOver}
	ondragleave={onDragLeave}
	class="border-2 border-dashed rounded-xl p-6 text-center transition-colors {disabled
		? 'border-gray-200 bg-gray-50 opacity-60'
		: dragOver
			? 'border-teal-400 bg-teal-50'
			: 'border-gray-300 bg-white hover:border-teal-300'}"
>
	<div class="flex flex-col items-center gap-2">
		<div class="w-10 h-10 rounded-full bg-teal-50 flex items-center justify-center {dragOver ? 'bg-teal-100' : ''}">
			<Upload size={20} class="text-teal-500" />
		</div>
		<p class="text-sm font-medium text-gray-700">{label}</p>
		{#if hint}
			<p class="text-xs text-gray-400">{hint}</p>
		{/if}
		<button
			type="button"
			onclick={() => inputEl?.click()}
			{disabled}
			class="mt-1 px-4 py-1.5 text-xs font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
		>
			Göz at
		</button>
		<input
			bind:this={inputEl}
			type="file"
			{accept}
			{multiple}
			{disabled}
			onchange={onInputChange}
			class="hidden"
			aria-label="Dosya seç"
		/>
	</div>
</div>
