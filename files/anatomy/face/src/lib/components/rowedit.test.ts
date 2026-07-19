import { describe, it, expect } from 'vitest';
import {
	rowKeyColumn,
	editableColumns,
	validateJsonCell,
	coerceCell,
	buildRow,
	validateRow
} from './rowedit';
import type { ColumnSpec } from '$lib/contracts';

const COLS: ColumnSpec[] = [
	{ key: 'slug', label: 'Key', kind: 'text', required: true },
	{ key: 'name', label: 'Name', kind: 'text', required: true },
	{ key: 'weight', label: 'W', kind: 'number' },
	{ key: 'on', label: 'On', kind: 'boolean' },
	{ key: 'cells', label: 'Cells', kind: 'json' },
	{ key: 'emb', label: 'Embedding', kind: 'vector', dim: 768 }
];

describe('rowedit · key + editable', () => {
	it('prefers slug/key/id as the row key', () => {
		expect(rowKeyColumn(COLS)?.key).toBe('slug');
		expect(rowKeyColumn([{ key: 'id', label: 'id', kind: 'text' }])?.key).toBe('id');
		expect(rowKeyColumn([{ key: 'x', label: 'x', kind: 'text', required: true }])?.key).toBe('x');
	});
	it('drops vector (read-only) columns from the editable set', () => {
		expect(editableColumns(COLS).map((c) => c.key)).not.toContain('emb');
		expect(editableColumns(COLS)).toHaveLength(5);
	});
});

describe('rowedit · json cell', () => {
	it('accepts empty (→ undefined) and valid JSON', () => {
		expect(validateJsonCell('')).toEqual({ ok: true, value: undefined });
		expect(validateJsonCell('[{"x":0}]').value).toEqual([{ x: 0 }]);
	});
	it('rejects malformed JSON', () => {
		expect(validateJsonCell('{nope').ok).toBe(false);
	});
});

describe('rowedit · coerce + build', () => {
	it('coerces by kind and omits empties', () => {
		expect(coerceCell(COLS[2], '5')).toBe(5);
		expect(coerceCell(COLS[2], '')).toBeUndefined();
		expect(coerceCell(COLS[3], 'true')).toBe(true);
		expect(coerceCell(COLS[3], false)).toBe(false);
	});
	it('buildRow drops vector + empties, parses json', () => {
		const row = buildRow(COLS, {
			slug: 'a',
			name: 'A',
			weight: '3',
			on: true,
			cells: '[]',
			emb: 'x'
		});
		expect(row).toEqual({ slug: 'a', name: 'A', weight: 3, on: true, cells: [] });
		expect(row).not.toHaveProperty('emb');
	});
});

describe('rowedit · validate', () => {
	it('requires the key + required cells', () => {
		expect(validateRow(COLS, { name: 'A' })).toMatch(/Key/);
		expect(validateRow(COLS, { slug: 'a' })).toMatch(/Name/);
		expect(validateRow(COLS, { slug: 'a', name: 'A' })).toBeNull();
	});
	it('rejects malformed json even when optional', () => {
		expect(validateRow(COLS, { slug: 'a', name: 'A', cells: '{bad' })).toMatch(/Cells/);
	});
});
