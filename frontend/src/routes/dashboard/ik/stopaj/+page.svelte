<script lang="ts">
	import ScheduledModule from '$lib/components/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="Stopaj"
	subtitle="Stopaj ödemelerini takip edin"
	apiPrefix="/hr/withholding"
	permissionCode="hr.withholding"
	sourceType="withholding"
	showCategory={false}
/>
