<script lang="ts">
	import ScheduledModule from '$lib/components/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="Temettü"
	subtitle="Temettü ödemelerini takip edin"
	apiPrefix="/accounting/dividend"
	permissionCode="accounting.dividend"
	sourceType="dividend"
	showCategory={false}
/>
