import { describe, it, expect } from 'vitest';
import {
	slugFromTitle,
	isValidSlug,
	parseOptions,
	defaultColumns,
	validateDraft,
	buildCreateBody,
	type DraftColumn
} from './createtable';

describe('slugFromTitle', () => {
	it('lowercases and dashes spaces/dots/underscores', () => {
		expect(slugFromTitle('My Cool Table')).toBe('my-cool-table');
		expect(slugFromTitle('foo.bar_baz')).toBe('foo-bar-baz');
	});
	it('collapses repeats and trims edge dashes', () => {
		expect(slugFromTitle('  --Hello???World--  ')).toBe('hello-world');
		expect(slugFromTitle('a   b')).toBe('a-b');
	});
	it('strips invalid characters', () => {
		expect(slugFromTitle('Ærö & Co!')).toBe('r-co');
	});
	it('caps at 63 chars with no trailing dash', () => {
		const s = slugFromTitle('x'.repeat(80));
		expect(s.length).toBeLessThanOrEqual(63);
		expect(s.endsWith('-')).toBe(false);
	});
});

describe('isValidSlug', () => {
	it('accepts dash slugs, rejects dots/edges/empty', () => {
		expect(isValidSlug('face-systems')).toBe(true);
		expect(isValidSlug('a')).toBe(true);
		expect(isValidSlug('face.systems')).toBe(false); // dots rejected
		expect(isValidSlug('-lead')).toBe(false); // leading dash rejected
		expect(isValidSlug('trail-')).toBe(true); // KEAP allows a trailing dash
		expect(isValidSlug('')).toBe(false);
		expect(isValidSlug('x'.repeat(64))).toBe(false);
	});
});

describe('parseOptions', () => {
	it('trims, drops empties, de-dupes', () => {
		expect(parseOptions('a, b ,, a,c')).toEqual(['a', 'b', 'c']);
		expect(parseOptions('   ')).toEqual([]);
	});
});

describe('validateDraft', () => {
	const cols = () => defaultColumns();
	it('passes a well-formed draft', () => {
		expect(validateDraft('good-slug', cols())).toBe('');
	});
	it('rejects a bad slug', () => {
		expect(validateDraft('bad.slug', cols())).toMatch(/slug/i);
	});
	it('rejects zero columns', () => {
		expect(validateDraft('good', [])).toMatch(/at least one column/i);
	});
	it('rejects empty / malformed / duplicate keys', () => {
		const empty: DraftColumn[] = [
			{ key: '', label: 'X', kind: 'text', required: false, options: '' }
		];
		expect(validateDraft('good', empty)).toMatch(/key/i);
		const bad: DraftColumn[] = [
			{ key: '1bad', label: 'X', kind: 'text', required: false, options: '' }
		];
		expect(validateDraft('good', bad)).toMatch(/must start/i);
		const dup: DraftColumn[] = [
			{ key: 'a', label: 'A', kind: 'text', required: false, options: '' },
			{ key: 'a', label: 'A2', kind: 'text', required: false, options: '' }
		];
		expect(validateDraft('good', dup)).toMatch(/duplicate/i);
	});
	it('requires options for a select column', () => {
		const sel: DraftColumn[] = [
			{ key: 'k', label: 'K', kind: 'select', required: false, options: '  ' }
		];
		expect(validateDraft('good', sel)).toMatch(/option/i);
	});
});

describe('buildCreateBody', () => {
	it('assembles schema.columns, omitting required/options when absent', () => {
		const body = buildCreateBody({
			slug: 'my-table',
			title: 'My Table',
			description: '',
			anchor: '',
			columns: [
				{ key: 'name', label: 'Name', kind: 'text', required: true, options: '' },
				{ key: 'k', label: '', kind: 'text', required: false, options: 'x,y' }
			]
		});
		expect(body.slug).toBe('my-table');
		expect(body.title).toBe('My Table');
		expect(body.description).toBeUndefined();
		expect(body.anchors).toBeUndefined();
		expect(body.schema.columns[0]).toEqual({
			key: 'name',
			label: 'Name',
			kind: 'text',
			required: true
		});
		// label defaults to key; options ignored for non-select; required omitted.
		expect(body.schema.columns[1]).toEqual({ key: 'k', label: 'k', kind: 'text' });
	});
	it('includes options for select and anchors/description when set', () => {
		const body = buildCreateBody({
			slug: 'sel',
			title: 'Sel',
			description: '  a desc ',
			anchor: ' nos.applications ',
			columns: [{ key: 'kind', label: 'Kind', kind: 'select', required: false, options: 'a, b, a' }]
		});
		expect(body.description).toBe('a desc');
		expect(body.anchors).toEqual(['nos.applications']);
		expect(body.schema.columns[0].options).toEqual(['a', 'b']);
	});
});
