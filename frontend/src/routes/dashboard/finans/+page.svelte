<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/dashboard/finans/nakit-akim', { replaceState: true });
	});
</script>
