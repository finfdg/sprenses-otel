<script lang="ts">
	import ScheduledModule from '$lib/components/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="Vergiler"
	subtitle="Vergi ödemelerini takip edin ve nakit akım planlaması yapın"
	apiPrefix="/accounting/taxes"
	permissionCode="accounting.taxes"
	sourceType="tax"
	showCategory={true}
	categoryLabel="Vergi Türü"
	categories={['KDV', 'Stopaj', 'Damga Vergisi', 'SGK', 'Kurumlar Vergisi', 'Gelir Vergisi', 'Emlak Vergisi', 'Diğer']}
/>
