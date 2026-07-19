/**
 * Pure logic for the DataTable RowEditor — kept out of the .svelte component so
 * the row-key resolution, json validation, and coercion are unit-testable.
 */
import type { ColumnSpec } from '$lib/contracts';

/** Columns that never take user input in the editor (Pulse-generated). */
export const READONLY_KINDS = new Set(['vector']);

/** The stable-key column of a table (used as the upsert key). Prefer an explicit
 *  slug/key/id column; else the first required text column; else the first column. */
export function rowKeyColumn(columns: ColumnSpec[]): ColumnSpec | null {
	for (const pref of ['slug', 'key', 'id']) {
		const c = columns.find((col) => col.key === pref);
		if (c) return c;
	}
	const req = columns.find((c) => c.required && c.kind === 'text');
	return req ?? columns[0] ?? null;
}

/** Columns the editor renders an input for (drops read-only/vector kinds). */
export function editableColumns(columns: ColumnSpec[]): ColumnSpec[] {
	return columns.filter((c) => !READONLY_KINDS.has(c.kind));
}

export interface JsonCheck {
	ok: boolean;
	value?: unknown;
	error?: string;
}

/** Validate + parse a json-cell string. Empty is allowed (→ undefined). */
export function validateJsonCell(raw: string): JsonCheck {
	const s = (raw ?? '').trim();
	if (s === '') return { ok: true, value: undefined };
	try {
		return { ok: true, value: JSON.parse(s) };
	} catch (e) {
		return { ok: false, error: e instanceof Error ? e.message : 'invalid JSON' };
	}
}

/** Coerce one raw form value to its column kind. Returns undefined to omit. */
export function coerceCell(col: ColumnSpec, raw: unknown): unknown {
	if (col.kind === 'number') {
		if (raw === '' || raw === null || raw === undefined) return undefined;
		const n = Number(raw);
		return Number.isFinite(n) ? n : undefined;
	}
	if (col.kind === 'boolean') return raw === true || raw === 'true';
	if (col.kind === 'json') {
		const c = validateJsonCell(typeof raw === 'string' ? raw : JSON.stringify(raw ?? ''));
		return c.ok ? c.value : undefined;
	}
	const s = raw === null || raw === undefined ? '' : String(raw);
	return s === '' ? undefined : s;
}

/** Build the flat row bag from form values, coerced by column kind. */
export function buildRow(
	columns: ColumnSpec[],
	values: Record<string, unknown>
): Record<string, unknown> {
	const out: Record<string, unknown> = {};
	for (const col of editableColumns(columns)) {
		const v = coerceCell(col, values[col.key]);
		if (v !== undefined) out[col.key] = v;
	}
	return out;
}

/** Validate a form: required cells present + the stable key present. Returns an
 *  error message or null when valid. */
export function validateRow(columns: ColumnSpec[], values: Record<string, unknown>): string | null {
	const keyCol = rowKeyColumn(columns);
	if (keyCol) {
		const kv = values[keyCol.key];
		if (kv === undefined || kv === null || String(kv).trim() === '') {
			return `“${keyCol.label}” is required (it is the row key).`;
		}
	}
	for (const col of editableColumns(columns)) {
		if (!col.required) continue;
		const v = values[col.key];
		if (v === undefined || v === null || (typeof v === 'string' && v.trim() === '')) {
			return `“${col.label}” is required.`;
		}
		if (col.kind === 'json' && typeof v === 'string') {
			const c = validateJsonCell(v);
			if (!c.ok) return `“${col.label}”: ${c.error}`;
		}
	}
	// Non-required json cells must still be valid JSON if filled.
	for (const col of editableColumns(columns)) {
		if (col.kind === 'json' && typeof values[col.key] === 'string') {
			const c = validateJsonCell(values[col.key] as string);
			if (!c.ok) return `“${col.label}”: ${c.error}`;
		}
	}
	return null;
}
