import { describe, it, expect } from 'vitest';
import {
	surfaceApp,
	parseSurfaceApp,
	isControlPanelWindow,
	controlsFromTable,
	iconGlyph,
	CP_GRID_APP,
	FALLBACK_CONTROLS
} from './surfaces';
import type { ControlEntry, DataTable } from '$lib/contracts';

describe('surface app-slug round-trip', () => {
	it('encodes + decodes a simple surface', () => {
		const app = surfaceApp({ surface: 'wallpaper' });
		expect(app).toBe('cp:wallpaper');
		expect(parseSurfaceApp(app)).toEqual({ surface: 'wallpaper', table: undefined });
	});
	it('encodes + decodes rawDataTable with a table slug (incl. dotted names)', () => {
		const app = surfaceApp({ surface: 'rawDataTable', table: 'face-wallpapers' });
		expect(app).toBe('cp:rawDataTable:face-wallpapers');
		expect(parseSurfaceApp(app)).toEqual({ surface: 'rawDataTable', table: 'face-wallpapers' });
	});
	it('returns null for a non-CP app', () => {
		expect(parseSurfaceApp('files')).toBeNull();
		expect(parseSurfaceApp(CP_GRID_APP)).toBeNull();
	});
});

describe('isControlPanelWindow', () => {
	it('matches the grid and any surface', () => {
		expect(isControlPanelWindow(CP_GRID_APP)).toBe(true);
		expect(isControlPanelWindow('cp:wallpaper')).toBe(true);
		expect(isControlPanelWindow('cp:rawDataTable:face-controls')).toBe(true);
	});
	it('rejects other apps', () => {
		expect(isControlPanelWindow('files')).toBe(false);
		expect(isControlPanelWindow('notes')).toBe(false);
	});
});

describe('controlsFromTable', () => {
	it('falls back to repo defaults for empty/null', () => {
		expect(controlsFromTable(null)).toEqual(FALLBACK_CONTROLS);
	});
	it('projects valid rows and drops unknown surfaces', () => {
		const table: DataTable = {
			slug: 'face-controls',
			title: 'Controls',
			source: 'keap',
			columns: [],
			rows: [
				{
					id: '1',
					slug: 'wallpaper',
					name: 'Wallpaper',
					icon: '🖼️',
					surface: 'wallpaper',
					system: true
				},
				{ id: '2', slug: 'bogus', name: 'Bogus', surface: 'not-a-surface', system: false }
			]
		};
		const out = controlsFromTable(table);
		expect(out).toHaveLength(1);
		expect(out[0]).toMatchObject<Partial<ControlEntry>>({
			slug: 'wallpaper',
			surface: 'wallpaper'
		});
	});
});

describe('iconGlyph', () => {
	it('maps known lucide names → emoji', () => {
		expect(iconGlyph('layout-dashboard')).toBe('🪟');
		expect(iconGlyph('hard-drive')).toBe('💾');
		expect(iconGlyph('User')).toBe('👤'); // case-insensitive
		expect(iconGlyph('image')).toBe('🖼️');
	});
	it('passes an existing emoji through', () => {
		expect(iconGlyph('🎨')).toBe('🎨');
	});
	it('falls back to 🔧 for unknown ascii names and empty', () => {
		expect(iconGlyph('some-unknown-icon')).toBe('🔧');
		expect(iconGlyph('')).toBe('🔧');
	});
});
