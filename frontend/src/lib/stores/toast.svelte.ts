// Toast bildirim yönetimi — Svelte 5 runes modülü

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
	id: number;
	message: string;
	type: ToastType;
}

export const toasts = $state<Toast[]>([]);

let nextId = 0;

export function showToast(message: string, type: ToastType = 'success', duration: number = 3000): void {
	const id = nextId++;
	toasts.push({ id, message, type });
	setTimeout(() => {
		const idx = toasts.findIndex(t => t.id === id);
		if (idx !== -1) toasts.splice(idx, 1);
	}, duration);
}

export function removeToast(id: number): void {
	const idx = toasts.findIndex(t => t.id === id);
	if (idx !== -1) toasts.splice(idx, 1);
}
