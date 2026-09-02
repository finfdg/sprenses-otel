<script lang="ts">
	import ScheduledModule from '$lib/components/scheduled/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="SGK"
	subtitle="SGK prim ödemelerini takip edin"
	apiPrefix="/hr/sgk"
	permissionCode="hr.sgk"
	sourceType="sgk"
	showCategory={false}
/>
