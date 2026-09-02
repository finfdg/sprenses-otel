<script lang="ts" module>
	export type BadgeType = 'success' | 'error' | 'warning' | 'info' | 'neutral';

	export const BADGE_STYLES: Record<BadgeType, string> = {
		success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
		error: 'bg-red-50 text-red-600 border-red-200',
		warning: 'bg-amber-50 text-amber-700 border-amber-200',
		info: 'bg-blue-50 text-blue-600 border-blue-200',
		neutral: 'bg-gray-100 text-gray-600 border-gray-200'
	};
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		type = 'neutral',
		children
	}: {
		type?: BadgeType;
		children: Snippet;
	} = $props();
</script>

<span
	class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap {BADGE_STYLES[type]}"
>
	{@render children()}
</span>
