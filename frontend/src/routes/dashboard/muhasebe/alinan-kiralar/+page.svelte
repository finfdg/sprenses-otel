<script lang="ts">
	import ScheduledModule from '$lib/components/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="Alınan Kiralar"
	subtitle="Kira gelirlerini takip edin"
	apiPrefix="/accounting/rent-income"
	permissionCode="accounting.rent_income"
	sourceType="rent_income"
	showCategory={true}
	categoryLabel="Kategori"
	categories={['Dükkan', 'Ofis', 'Depo', 'Arsa', 'Diğer']}
/>
