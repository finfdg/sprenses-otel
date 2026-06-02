<script lang="ts">
	interface Comparison {
		label: string;
		perCapita: number | null;
	}

	let {
		currentPerCapita,
		previousPerCapita = null,
		comparisons = null,
		increaseThreshold = 10,
		decreaseThreshold = 10,
	}: {
		currentPerCapita: number;
		previousPerCapita?: number | null;
		comparisons?: Comparison[] | null;
		increaseThreshold?: number;
		decreaseThreshold?: number;
	} = $props();

	// Eski API uyumluluğu: previousPerCapita varsa comparisons'a dönüştür
	let effectiveComparisons = $derived.by(() => {
		if (comparisons && comparisons.length > 0) return comparisons;
		if (previousPerCapita !== null && previousPerCapita !== undefined) {
			return [{ label: 'Ö.Form', perCapita: previousPerCapita }];
		}
		return [];
	});

	function getIndicator(prevPerCapita: number | null) {
		if (prevPerCapita === null || prevPerCapita === 0 || isNaN(currentPerCapita)) return null;
		const changePercent = ((currentPerCapita - prevPerCapita) / prevPerCapita) * 100;
		if (changePercent > increaseThreshold) return { type: 'increase', color: 'text-red-600 bg-red-50 border-red-200', icon: '↑', changePercent };
		if (changePercent < -decreaseThreshold) return { type: 'decrease', color: 'text-green-600 bg-green-50 border-green-200', icon: '↓', changePercent };
		return null; // Eşik aşılmadıysa gösterme
	}
</script>

{#if effectiveComparisons.length > 0}
	<span class="inline-flex flex-wrap items-center gap-1">
		{#each effectiveComparisons as comp}
			{@const indicator = getIndicator(comp.perCapita)}
			{#if indicator}
				<span class="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded-full border {indicator.color}">
					<span class="font-medium">{comp.label}</span>
					<span>{indicator.icon}</span>
					<span>%{Math.abs(indicator.changePercent).toFixed(1)}</span>
				</span>
			{/if}
		{/each}
	</span>
{/if}
