<script lang="ts">
	let { value, label }: { value: string | number; label: string } = $props();
</script>

<div class="bg-white border border-gray-200 rounded-2xl p-6 text-center shadow-sm">
	<div class="text-3xl font-bold text-teal-600">{value}</div>
	<div class="text-xs text-gray-400 mt-1 uppercase tracking-wider">{label}</div>
</div>
