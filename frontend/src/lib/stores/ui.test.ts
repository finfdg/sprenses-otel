import { describe, it, expect, beforeEach } from 'vitest';
import { sidebar, toggleSidebar, closeSidebar } from './ui.svelte';

beforeEach(() => {
	sidebar.open = false;
});

// ─── sidebar state ───────────────────────────────────────────

describe('sidebar', () => {
	it('başlangıçta kapalıdır', () => {
		expect(sidebar.open).toBe(false);
	});
});

// ─── toggleSidebar ───────────────────────────────────────────

describe('toggleSidebar', () => {
	it('kapalıysa açar', () => {
		toggleSidebar();
		expect(sidebar.open).toBe(true);
	});

	it('açıksa kapatır', () => {
		sidebar.open = true;
		toggleSidebar();
		expect(sidebar.open).toBe(false);
	});

	it('iki kez çağrılırsa eski duruma döner', () => {
		toggleSidebar();
		toggleSidebar();
		expect(sidebar.open).toBe(false);
	});
});

// ─── closeSidebar ────────────────────────────────────────────

describe('closeSidebar', () => {
	it('açıksa kapatır', () => {
		sidebar.open = true;
		closeSidebar();
		expect(sidebar.open).toBe(false);
	});

	it('zaten kapalıysa kapalı kalır', () => {
		closeSidebar();
		expect(sidebar.open).toBe(false);
	});
});
