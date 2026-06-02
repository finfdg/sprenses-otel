<script lang="ts">
	import ScheduledModule from '$lib/components/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="Verilen Kiralar"
	subtitle="Kira giderlerini takip edin"
	apiPrefix="/accounting/rent-expense"
	permissionCode="accounting.rent_expense"
	sourceType="rent_expense"
	showCategory={true}
	categoryLabel="Kategori"
	categories={['Dükkan', 'Ofis', 'Depo', 'Arsa', 'Diğer']}
/>
