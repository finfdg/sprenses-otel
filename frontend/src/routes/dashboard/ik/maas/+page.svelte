<script lang="ts">
	import ScheduledModule from '$lib/components/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="Maaş"
	subtitle="Aylık maaş ödemelerini takip edin"
	apiPrefix="/hr/salary"
	permissionCode="hr.salary"
	sourceType="salary"
	showCategory={false}
/>
