import { api } from '$lib/api';
import { disconnectWebSocket } from '$lib/stores/websocket.svelte';

interface ModulePermission {
	module_code: string;
	module_name: string;
	can_view: boolean;
	can_use: boolean;
}

interface RoleBrief {
	id: number;
	name: string;
}

export interface User {
	id: number;
	username: string;
	email: string;
	first_name: string;
	last_name: string;
	role_id: number;
	role: RoleBrief | null;
	is_active: boolean;
	permissions: ModulePermission[];
}

export const authState = $state<{ user: User | null }>({ user: null });

export function setAuth(userData: User) {
	authState.user = userData;
	localStorage.setItem('user', JSON.stringify(userData));
}

export function loadAuth(): boolean {
	const u = localStorage.getItem('user');
	if (u) {
		try {
			const parsed = JSON.parse(u);
			if (!parsed.username || !parsed.first_name) {
				localStorage.removeItem('user');
				return false;
			}
			authState.user = parsed;
			return true;
		} catch (e) {
			console.error('Auth verisi yüklenemedi:', e);
			localStorage.removeItem('user');
			return false;
		}
	}
	return false;
}

export async function logout() {
	disconnectWebSocket();

	// Push aboneliğini iptal et (başka kullanıcı giriş yapınca karışmasın)
	try {
		const { unsubscribeFromPush, isPushSupported } = await import('$lib/utils/push');
		if (isPushSupported()) {
			await unsubscribeFromPush();
		}
	} catch (e) {
		console.error('Push aboneliği iptal edilemedi (desteklenmiyor olabilir):', e);
	}

	try {
		await api.post('/auth/logout', {});
	} catch (e) {
		console.error('Logout isteği başarısız:', e);
	}
	authState.user = null;
	localStorage.removeItem('user');

	try {
		const { invalidateCashFlowCache } = await import('./cashflow.svelte');
		invalidateCashFlowCache();
	} catch (e) {
		console.error('Nakit akım cache temizlenemedi (store henüz yüklenmemiş olabilir):', e);
	}
}

export async function refreshAuth(): Promise<boolean> {
	try {
		const userData = await api.get<User>('/auth/me');
		authState.user = userData;
		localStorage.setItem('user', JSON.stringify(userData));
		return true;
	} catch (e) {
		console.error('Kullanıcı bilgisi güncellenemedi:', e);
		return false;
	}
}

export function hasPermission(moduleCode: string, action: 'view' | 'use' = 'view'): boolean {
	const currentUser = authState.user;
	if (!currentUser || !currentUser.permissions) return false;
	const perm = currentUser.permissions.find(p => p.module_code === moduleCode);
	if (!perm) return false;
	if (action === 'view') return perm.can_view;
	if (action === 'use') return perm.can_use;
	return false;
}
