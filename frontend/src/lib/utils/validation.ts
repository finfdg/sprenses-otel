/** Form doğrulama yardımcıları */

export function validateEmail(email: string): string | null {
	if (!email) return null; // email opsiyonel olabilir
	const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
	if (!re.test(email)) return 'Geçerli bir e-posta adresi giriniz';
	return null;
}

export function validatePassword(password: string, required: boolean = true): string | null {
	if (!password && !required) return null;
	if (!password) return 'Şifre gereklidir';
	if (password.length < 6) return 'Şifre en az 6 karakter olmalıdır';
	return null;
}

export function validateRequired(value: string, fieldName: string): string | null {
	if (!value || !value.trim()) return `${fieldName} gereklidir`;
	return null;
}

export function validateMinLength(value: string, min: number, fieldName: string): string | null {
	if (value && value.length < min) return `${fieldName} en az ${min} karakter olmalıdır`;
	return null;
}

export function validateModuleCode(code: string): string | null {
	if (!code) return 'Modül kodu gereklidir';
	if (!/^[a-z][a-z0-9.]*$/.test(code)) return 'Modül kodu küçük harf, rakam ve nokta içerebilir';
	return null;
}
