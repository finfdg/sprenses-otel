// Mobil sidebar açık/kapalı durumu — Svelte 5 runes modülü

// State'i bir obje içinde tutarak export sorununu çözüyoruz
export const sidebar = $state({ open: false });

export function toggleSidebar() {
	sidebar.open = !sidebar.open;
}

export function closeSidebar() {
	sidebar.open = false;
}
