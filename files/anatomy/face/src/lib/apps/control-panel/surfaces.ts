/**
 * Control-panel surface routing (G4).
 *
 * The control panel opens a *window* per surface (never a modal). Because the
 * desktop store's `WindowModel` only carries an `app` slug, we encode the
 * surface (and, for rawDataTable, the table slug) INTO that slug and decode it
 * in the host component. Pure functions here so the round-trip is unit-testable.
 */
import type { ControlEntry, DataTable, DataTableRow } from '$lib/contracts';

/** The app slug of the control-panel grid window itself. */
export const CP_GRID_APP = 'control-panel';
const CP_PREFIX = 'cp:';

/** Repo-seeded control entries (used when `face-controls` is empty / KEAP down). */
export const FALLBACK_CONTROLS: ControlEntry[] = [
	{ slug: 'wallpaper', name: 'Wallpaper', icon: '🖼️', surface: 'wallpaper', system: true },
	{ slug: 'layouts', name: 'Layouts', icon: '🧩', surface: 'layouts', system: true },
	{ slug: 'identity', name: 'Identity', icon: '🪪', surface: 'identity', system: true },
	{ slug: 'storage', name: 'Storage', icon: '🗄️', surface: 'storage', system: true },
	{
		slug: 'wallpapers-table',
		name: 'Wallpapers (raw)',
		icon: '📄',
		surface: 'rawDataTable',
		table: 'face-wallpapers',
		system: true
	}
];

/** Encode a control entry into a window `app` slug. */
export function surfaceApp(entry: Pick<ControlEntry, 'surface' | 'table'>): string {
	if (entry.surface === 'rawDataTable') {
		return `${CP_PREFIX}rawDataTable:${entry.table ?? ''}`;
	}
	return `${CP_PREFIX}${entry.surface}`;
}

export interface ParsedSurface {
	surface: ControlEntry['surface'];
	table?: string;
}

/** Decode a window `app` slug back into a surface (null if not a CP surface). */
export function parseSurfaceApp(app: string): ParsedSurface | null {
	if (!app.startsWith(CP_PREFIX)) return null;
	const rest = app.slice(CP_PREFIX.length);
	const idx = rest.indexOf(':');
	const surface = (idx === -1 ? rest : rest.slice(0, idx)) as ControlEntry['surface'];
	const table = idx === -1 ? undefined : rest.slice(idx + 1) || undefined;
	return { surface, table };
}

/** True for any window this group owns (the grid or one of its surfaces). */
export function isControlPanelWindow(app: string): boolean {
	return app === CP_GRID_APP || app.startsWith(CP_PREFIX);
}

const KNOWN_SURFACES = new Set<ControlEntry['surface']>([
	'wallpaper',
	'layouts',
	'identity',
	'storage',
	'rawDataTable'
]);

/** The shell has no icon font, so KEAP rows that carry a lucide icon NAME
 *  (e.g. "layout-dashboard") would render as raw text. Map the known names to an
 *  emoji glyph (dock convention); pass through anything that's already an emoji;
 *  fall back to 🔧 for the unknown/empty. Rendered as escaped text, never HTML. */
const LUCIDE_EMOJI: Record<string, string> = {
	image: '🖼️',
	wallpaper: '🖼️',
	palette: '🎨',
	'layout-dashboard': '🪟',
	layout: '🪟',
	layers: '🧩',
	grid: '🧩',
	user: '👤',
	users: '👥',
	identity: '🪪',
	'id-card': '🪪',
	'hard-drive': '💾',
	database: '🗄️',
	folder: '📁',
	file: '📄',
	settings: '⚙️',
	gear: '⚙️',
	cog: '⚙️',
	bell: '🔔',
	shield: '🛡️',
	monitor: '🖥️'
};

export function iconGlyph(icon: string): string {
	const key = icon.trim().toLowerCase();
	if (!key) return '🔧';
	if (LUCIDE_EMOJI[key]) return LUCIDE_EMOJI[key];
	// Already a glyph/emoji (no ascii-name shape) → keep it; else fall back.
	return /^[a-z0-9-]+$/.test(key) ? '🔧' : icon;
}

/** Project a `face-controls` DataTable into typed entries, with repo fallback. */
export function controlsFromTable(table: DataTable | null): ControlEntry[] {
	const rows: DataTableRow[] = table?.rows ?? [];
	const entries: ControlEntry[] = [];
	for (const r of rows) {
		const surface = r.surface as ControlEntry['surface'];
		if (!KNOWN_SURFACES.has(surface)) continue;
		const slug = String(r.slug ?? r.id ?? '');
		if (!slug) continue;
		entries.push({
			slug,
			name: String(r.name ?? slug),
			icon: iconGlyph(typeof r.icon === 'string' ? r.icon : ''),
			surface,
			table: typeof r.table === 'string' ? r.table : undefined,
			system: r.system === true || r.system === 'true'
		});
	}
	return entries.length > 0 ? entries : FALLBACK_CONTROLS;
}
