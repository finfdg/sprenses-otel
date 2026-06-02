// Mesajlaşma modülü paylaşılan tip tanımları

export interface OtherUser {
	id: number;
	username: string;
	first_name: string;
	last_name: string;
}

export interface GroupMember {
	id: number;
	first_name: string;
	last_name: string;
	username: string;
	is_admin: boolean;
}

export interface MessageItem {
	id: number;
	conversation_id: number;
	sender_id: number;
	content: string;
	message_type: string;
	created_at: string;
	is_edited: boolean;
	edited_at: string | null;
	is_deleted: boolean;
	file_url: string | null;
	file_name: string | null;
	file_size: number | null;
	file_type: string | null;
	sender_name: string | null;
}

export interface ConversationItem {
	id: number;
	type: string;
	name: string | null;
	other_user: OtherUser | null;
	members: GroupMember[] | null;
	last_message: MessageItem | null;
	unread_count: number;
	is_muted: boolean;
	updated_at: string;
}

export interface ConversationDetail {
	id: number;
	type: string;
	name: string | null;
	other_user: OtherUser | null;
	members: GroupMember[] | null;
	messages: MessageItem[];
	has_more: boolean;
	other_user_last_read_at: string | null;
	created_by: number | null;
}

export interface ChatUser {
	id: number;
	username: string;
	first_name: string;
	last_name: string;
	role_name: string | null;
	has_existing_conversation: boolean;
	conversation_id: number | null;
}

// ─── Yardımcı Fonksiyonlar ──────────────────────────────────────

export function formatTime(dateStr: string): string {
	const date = new Date(dateStr);
	const now = new Date();
	// Takvim günü bazlı karşılaştırma (saat farkı yerine)
	const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
	const msgDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
	const diffDays = Math.round((today.getTime() - msgDay.getTime()) / (1000 * 60 * 60 * 24));
	if (diffDays === 0) return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
	if (diffDays === 1) return 'Dün';
	return date.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit' });
}

export function formatMsgTime(dateStr: string): string {
	return new Date(dateStr).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
}

export function getInitial(u: OtherUser | null): string {
	return u?.first_name?.charAt(0)?.toUpperCase() || '?';
}

export function getConvDisplayName(conv: ConversationItem): string {
	if (conv.type === 'group') return conv.name || 'Grup';
	return conv.other_user ? `${conv.other_user.first_name} ${conv.other_user.last_name}` : '';
}

export function getConvInitial(conv: ConversationItem): string {
	if (conv.type === 'group') return conv.name?.charAt(0)?.toUpperCase() || 'G';
	return getInitial(conv.other_user);
}

export function formatFileSize(bytes: number | null): string {
	if (!bytes) return '';
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function getFileIcon(fileType: string | null): string {
	if (!fileType) return '📎';
	if (fileType.includes('pdf')) return '📄';
	if (fileType.includes('word') || fileType.includes('document')) return '📝';
	if (fileType.includes('excel') || fileType.includes('spreadsheet')) return '📊';
	if (fileType.includes('text')) return '📃';
	return '📎';
}

// ─── Tarih Ayracı ────────────────────────────────────────────────

export function formatDateSeparator(dateStr: string): string {
	const date = new Date(dateStr);
	const now = new Date();
	const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
	const msgDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
	const diffDays = Math.round((today.getTime() - msgDay.getTime()) / (1000 * 60 * 60 * 24));
	if (diffDays === 0) return 'Bugün';
	if (diffDays === 1) return 'Dün';
	return date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' });
}

export function shouldShowDateSeparator(current: MessageItem, prev: MessageItem | null): boolean {
	if (!prev) return true;
	const d1 = new Date(current.created_at);
	const d2 = new Date(prev.created_at);
	return d1.getFullYear() !== d2.getFullYear() || d1.getMonth() !== d2.getMonth() || d1.getDate() !== d2.getDate();
}

export const userColorPalette = [
	{ bg: 'bg-violet-500', text: 'text-white', name: 'text-violet-600', imgBg: 'bg-violet-500', fileBg: 'bg-violet-500', avatarBg: 'bg-violet-100', avatarText: 'text-violet-700' },
	{ bg: 'bg-orange-500', text: 'text-white', name: 'text-orange-600', imgBg: 'bg-orange-500', fileBg: 'bg-orange-500', avatarBg: 'bg-orange-100', avatarText: 'text-orange-700' },
	{ bg: 'bg-blue-500', text: 'text-white', name: 'text-blue-600', imgBg: 'bg-blue-500', fileBg: 'bg-blue-500', avatarBg: 'bg-blue-100', avatarText: 'text-blue-700' },
	{ bg: 'bg-rose-500', text: 'text-white', name: 'text-rose-600', imgBg: 'bg-rose-500', fileBg: 'bg-rose-500', avatarBg: 'bg-rose-100', avatarText: 'text-rose-700' },
	{ bg: 'bg-emerald-500', text: 'text-white', name: 'text-emerald-600', imgBg: 'bg-emerald-500', fileBg: 'bg-emerald-500', avatarBg: 'bg-emerald-100', avatarText: 'text-emerald-700' },
	{ bg: 'bg-amber-500', text: 'text-white', name: 'text-amber-700', imgBg: 'bg-amber-500', fileBg: 'bg-amber-500', avatarBg: 'bg-amber-100', avatarText: 'text-amber-700' },
	{ bg: 'bg-cyan-500', text: 'text-white', name: 'text-cyan-600', imgBg: 'bg-cyan-500', fileBg: 'bg-cyan-500', avatarBg: 'bg-cyan-100', avatarText: 'text-cyan-700' },
	{ bg: 'bg-pink-500', text: 'text-white', name: 'text-pink-600', imgBg: 'bg-pink-500', fileBg: 'bg-pink-500', avatarBg: 'bg-pink-100', avatarText: 'text-pink-700' },
];

export function getUserColor(userId: number) {
	const idx = userId % userColorPalette.length;
	return userColorPalette[idx];
}
