<!--
	Textarea.svelte — Tüm formlarda ortak çok satırlı metin girişi (tasarım sistemi primitive'i).

	Neden: 17 <textarea> elle aynı sınıf dizisini kopyalıyordu. Varsayılan resize kapalı
	(resize-none); resize={true} ile açılır. Hata kenarlığı + odak halkası standart.

	Kullanım:
		<Textarea bind:value={form.notes} rows={3} placeholder="İsteğe bağlı notlar" />
		<Textarea bind:value={form.desc} invalid={!!err} aria-describedby="desc-error" />
-->
<script lang="ts">
	import type { HTMLTextareaAttributes } from 'svelte/elements';

	let {
		value = $bindable(),
		invalid = false,
		rows = 3,
		resize = false,
		class: klass = '',
		...rest
	}: {
		value?: string;
		invalid?: boolean;
		rows?: number;
		/** true → kullanıcı yeniden boyutlandırabilir (varsayılan kapalı) */
		resize?: boolean;
		/** Yalnızca layout (genişlik/boşluk) için ek sınıf */
		class?: string;
	} & Omit<HTMLTextareaAttributes, 'value' | 'rows' | 'class'> = $props();

	let cls = $derived(
		'w-full px-3 py-2.5 border rounded-lg text-sm bg-white text-gray-900 ' +
			'focus:outline-none focus:ring-2 focus:ring-teal-500 ' +
			'disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed ' +
			(resize ? '' : 'resize-none ') +
			(invalid ? 'border-red-400 ' : 'border-gray-300 ') +
			klass
	);
</script>

<textarea {rows} bind:value class={cls} aria-invalid={invalid || undefined} {...rest}></textarea>
