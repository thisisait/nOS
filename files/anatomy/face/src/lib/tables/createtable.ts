/** Pure helpers for the Create-table UI (unit-testable; no Svelte/server deps).
 *
 * KEAP's agent surface accepts a create-table body of the shape
 *   { slug, title, description?, anchors?, schema: { columns: [...] } }
 * with slug matching `^[a-z0-9][a-z0-9-]{0,62}$` (dashes only — NO dots in the
 * v1.12.x contract). These helpers derive/validate the slug + column keys and
 * assemble the body so the modal stays declarative. */
import type { ColumnKind, TableView } from '$lib/contracts';

/** A column being authored in the builder (pre-validation form shape). */
export interface DraftColumn {
	key: string;
	label: string;
	kind: ColumnKind;
	required: boolean;
	/** Raw comma-separated options text (only meaningful when kind==='select'). */
	options: string;
}

/** Column kinds offered in the builder — excludes machine-only kinds
 *  ('vector' is Pulse-generated; 'objectRef' needs a target picker we don't have). */
export const CREATE_COLUMN_KINDS: ColumnKind[] = [
	'text',
	'number',
	'boolean',
	'date',
	'select',
	'json',
	'user',
	'taxonomyRef'
];

export const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;
export const COLUMN_KEY_RE = /^[a-z_][a-z0-9_]*$/;

/** Derive a KEAP-legal slug from a free-text title: lowercase, non-alphanumerics
 *  → dashes, collapse repeats, trim edge dashes, cap at 63 chars. */
export function slugFromTitle(title: string): string {
	const s = title
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/-+/g, '-')
		.replace(/^-+|-+$/g, '')
		.slice(0, 63)
		.replace(/-+$/g, '');
	return s;
}

export function isValidSlug(slug: string): boolean {
	return SLUG_RE.test(slug);
}

/** Parse a comma-separated options string → trimmed, non-empty, de-duped list. */
export function parseOptions(raw: string): string[] {
	const seen = new Set<string>();
	const out: string[] = [];
	for (const part of raw.split(',')) {
		const v = part.trim();
		if (v && !seen.has(v)) {
			seen.add(v);
			out.push(v);
		}
	}
	return out;
}

export function defaultColumns(): DraftColumn[] {
	return [
		{ key: 'name', label: 'Name', kind: 'text', required: true, options: '' },
		{ key: 'slug', label: 'Slug', kind: 'text', required: true, options: '' }
	];
}

/** Validate the whole draft. Returns an error string, or '' when valid. */
export function validateDraft(slug: string, cols: DraftColumn[]): string {
	if (!isValidSlug(slug)) {
		return 'Slug must be lowercase letters, digits and dashes (2–63 chars, no leading/trailing dash).';
	}
	if (cols.length === 0) return 'Add at least one column.';
	const keys = new Set<string>();
	for (const c of cols) {
		const key = c.key.trim();
		if (!key) return 'Every column needs a key.';
		if (!COLUMN_KEY_RE.test(key)) {
			return `Column key "${key}" must start with a letter/underscore and use only letters, digits, underscores.`;
		}
		if (keys.has(key)) return `Duplicate column key "${key}".`;
		keys.add(key);
		if (c.kind === 'select' && parseOptions(c.options).length === 0) {
			return `Select column "${key}" needs at least one option.`;
		}
	}
	return '';
}

/** A create-table body column as KEAP expects it. */
export interface CreateColumn {
	key: string;
	label: string;
	kind: ColumnKind;
	required?: boolean;
	options?: string[];
}

/** KEAP's `POST /agent/v1/tables` reads the column list from the body's TOP LEVEL
 *  and wraps it itself:
 *
 *      createTableRequestSchema.safeParse({ ..., schema: { columns: b.columns } })
 *
 *  Sending only `schema.columns` therefore resolves `b.columns` to undefined and
 *  the zod parse fails with the bare message "Required" — which the modal
 *  surfaced verbatim, so every create attempt failed without naming a field.
 *  Measured against the live v1.36.0 agent surface on 2026-07-28.
 *
 *  We emit BOTH spellings: `columns` is what the current server reads, `schema`
 *  is what this contract documented and what a tolerant server accepts. Neither
 *  is redundant while the two repos release independently. */
/** Grades a creator can pick. `private` is left out: face reads fail closed on
 *  it for a non-admin, so the manager who made the table could not open it. */
export const CREATE_VISIBILITIES = [
	'private',
	'tier-managers',
	'tier-users',
	'tier-guests',
	'shared'
] as const;
export type CreateVisibility = (typeof CREATE_VISIBILITIES)[number];

export interface CreateTableBody {
	slug: string;
	title: string;
	description?: string;
	anchors?: string[];
	visibility: CreateVisibility;
	columns: CreateColumn[];
	schema: { columns: CreateColumn[] };
	/** The KEAP view block (row face-style-at-create); absent = the grid. */
	view?: TableView;
}

// ── The style, chosen at create (row face-style-at-create) ──────────────────
// Each non-grid style names the columns it renders; a style missing a required
// one would be degraded to the grid by resolveView, so the form refuses it here.
export const CREATE_STYLES = ['grid', 'blog', 'timeline', 'tiles', 'chat'] as const;
export type CreateStyle = (typeof CREATE_STYLES)[number];
export type StyleRole = 'titleColumn' | 'bodyColumn' | 'dateColumn' | 'mediaColumn' | 'askColumn';
export type StylePicks = Partial<Record<StyleRole, string>>;
type RoleSpec = { role: StyleRole; label: string; kinds: ColumnKind[]; required: boolean };
const T = (role: StyleRole, label: string, required = false): RoleSpec => ({
	role,
	label,
	kinds: ['text'],
	required
});
export const STYLE_ROLES: Record<CreateStyle, RoleSpec[]> = {
	grid: [],
	blog: [T('titleColumn', 'Title'), T('bodyColumn', 'Body', true)],
	timeline: [
		{ role: 'dateColumn', label: 'Date', kinds: ['date'], required: true },
		T('titleColumn', 'Title')
	],
	tiles: [T('titleColumn', 'Title'), T('mediaColumn', 'Image URL')],
	chat: [T('askColumn', 'Asked', true), T('bodyColumn', 'Answer', true)]
};

/** '' when the picks fit the style and the draft's columns, else the reason. */
export function validateStyle(style: CreateStyle, picks: StylePicks, cols: DraftColumn[]): string {
	for (const r of STYLE_ROLES[style]) {
		const key = (picks[r.role] ?? '').trim();
		if (!key) {
			if (r.required) return `The ${style} style needs a ${r.label} column.`;
			continue;
		}
		const col = cols.find((c) => c.key.trim() === key);
		if (!col) return `${r.label}: no column "${key}".`;
		if (!r.kinds.includes(col.kind))
			return `${r.label} column "${key}" must be ${r.kinds.join(' or ')}.`;
	}
	if (style === 'chat' && picks.askColumn && picks.askColumn === picks.bodyColumn)
		return 'Asked and Answer must be two different columns.';
	return '';
}

/** The view block for a validated style; undefined for the grid (KEAP's default). */
export function viewBlock(style: CreateStyle, picks: StylePicks): TableView | undefined {
	if (style === 'grid') return undefined;
	const view: TableView = { style };
	for (const r of STYLE_ROLES[style]) {
		const key = (picks[r.role] ?? '').trim();
		if (key) view[r.role] = key;
	}
	return view;
}

/** Assemble the KEAP create-table body from validated draft inputs. Call only
 *  after validateDraft() returns ''. */
export function buildCreateBody(input: {
	slug: string;
	title: string;
	description: string;
	anchor: string;
	columns: DraftColumn[];
	visibility?: CreateVisibility;
	view?: TableView;
}): CreateTableBody {
	const columns: CreateColumn[] = input.columns.map((c) => {
		const key = c.key.trim();
		const col: CreateColumn = { key, label: c.label.trim() || key, kind: c.kind };
		if (c.required) col.required = true;
		if (c.kind === 'select') {
			const opts = parseOptions(c.options);
			if (opts.length) col.options = opts;
		}
		return col;
	});
	const body: CreateTableBody = {
		slug: input.slug.trim(),
		title: input.title.trim(),
		visibility: input.visibility ?? 'tier-managers',
		// Top-level `columns` is the one the server actually reads; `schema` mirrors
		// it for a tolerant/older server. See the CreateTableBody note above.
		columns,
		schema: { columns }
	};
	const desc = input.description.trim();
	if (desc) body.description = desc;
	const anchor = input.anchor.trim();
	if (anchor) body.anchors = [anchor];
	if (input.view) body.view = input.view;
	return body;
}
