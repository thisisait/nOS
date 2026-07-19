/** Pure helpers for the Create-table UI (unit-testable; no Svelte/server deps).
 *
 * KEAP's agent surface accepts a create-table body of the shape
 *   { slug, title, description?, anchors?, schema: { columns: [...] } }
 * with slug matching `^[a-z0-9][a-z0-9-]{0,62}$` (dashes only — NO dots in the
 * v1.12.x contract). These helpers derive/validate the slug + column keys and
 * assemble the body so the modal stays declarative. */
import type { ColumnKind } from '$lib/contracts';

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

export interface CreateTableBody {
	slug: string;
	title: string;
	description?: string;
	anchors?: string[];
	schema: { columns: CreateColumn[] };
}

/** Assemble the KEAP create-table body from validated draft inputs. Call only
 *  after validateDraft() returns ''. */
export function buildCreateBody(input: {
	slug: string;
	title: string;
	description: string;
	anchor: string;
	columns: DraftColumn[];
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
		schema: { columns }
	};
	const desc = input.description.trim();
	if (desc) body.description = desc;
	const anchor = input.anchor.trim();
	if (anchor) body.anchors = [anchor];
	return body;
}
