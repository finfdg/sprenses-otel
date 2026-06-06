<script lang="ts">
	import ScheduledModule from '$lib/components/ScheduledModule.svelte';
</script>

<ScheduledModule
	title="Düzenli Ödemeler"
	subtitle="Kira, sigorta, abonelik gibi düzenli giderleri yönetin"
	apiPrefix="/accounting/recurring"
	permissionCode="accounting.recurring"
	sourceType="recurring"
	showCategory={true}
	categoryLabel="Kategori"
	categories={['Kira', 'Sigorta', 'Abonelik', 'Fatura', 'Bakım', 'Güvenlik', 'Diğer']}
	enableVendorSync={true}
/>
