import { describe, expect, it } from 'vitest';
import { resolveView, orderRows, formatWhen } from './view';
import type { ColumnSpec, DataTable } from '$lib/contracts';

/**
 * Render-style resolution.
 *
 * The behaviour worth pinning is not "blog renders as blog" — that is visible
 * in a screenshot. It is the DEGRADE: KEAP refuses a blog with no body column
 * at author time, but this client also serves the offline fallback path, where
 * a stale block can arrive alongside columns that no longer match it. A style
 * that renders an untitled, bodyless list is worse than a grid, because it
 * looks like the style is working.
 */
const col = (key: string, kind: string, label = key): ColumnSpec =>
	({ key, label, kind }) as ColumnSpec;

const table = (columns: ColumnSpec[], view?: DataTable['view']): DataTable =>
	({
		slug: 't',
		title: 'T',
		columns,
		rows: [],
		source: 'keap',
		...(view ? { view } : {})
	}) as DataTable;

const COLS = [
	col('title', 'text', 'Title'),
	col('research', 'text', 'Research'),
	col('created', 'date', 'Created'),
	col('status', 'select', 'Status'),
	col('shot', 'file', 'Shot')
];

describe('resolveView', () => {
	it('an absent view block is the grid, and picks a sensible title', () => {
		const r = resolveView(table(COLS));
		expect(r.style).toBe('grid');
		expect(r.title?.key).toBe('title');
		expect(r.degradedFrom).toBeUndefined();
	});

	it('honours a fully-declared blog', () => {
		const r = resolveView(
			table(COLS, {
				style: 'blog',
				titleColumn: 'title',
				bodyColumn: 'research',
				metaColumns: ['status']
			})
		);
		expect(r.style).toBe('blog');
		expect(r.body?.key).toBe('research');
		expect(r.meta.map((m) => m.key)).toEqual(['status']);
	});

	it('DEGRADES a blog whose body column is gone, and says so', () => {
		// The stale-block case. Rendering an empty article list here would look
		// deliberate; the grid at least shows the data.
		const r = resolveView(table([col('title', 'text')], { style: 'blog', bodyColumn: 'research' }));
		expect(r.style).toBe('grid');
		expect(r.degradedFrom).toBe('blog');
	});

	it('never auto-picks a substitute body column', () => {
		// If the named body is missing, falling back to "some other text column"
		// would silently render the WRONG cell as the article — worse than
		// degrading, because the output looks correct.
		const r = resolveView(table(COLS, { style: 'blog', bodyColumn: 'ghost' }));
		expect(r.body).toBeNull();
		expect(r.degradedFrom).toBe('blog');
	});

	it('refuses a vector column as a body — it is 768 floats, not prose', () => {
		const cols = [col('title', 'text'), col('embedding', 'vector')];
		const r = resolveView(table(cols, { style: 'blog', bodyColumn: 'embedding' }));
		expect(r.style).toBe('grid');
		expect(r.degradedFrom).toBe('blog');
	});

	it('DEGRADES a timeline with no resolvable date', () => {
		const r = resolveView(table([col('title', 'text')], { style: 'timeline' }));
		expect(r.style).toBe('grid');
		expect(r.degradedFrom).toBe('timeline');
	});

	it('a timeline finds its date column without being told', () => {
		const r = resolveView(table(COLS, { style: 'timeline' }));
		expect(r.style).toBe('timeline');
		expect(r.date?.key).toBe('created');
	});

	it('tiles need nothing beyond a title — media is optional', () => {
		expect(resolveView(table([col('title', 'text')], { style: 'tiles' })).style).toBe('tiles');
		expect(resolveView(table(COLS, { style: 'tiles' })).media?.key).toBe('shot');
	});

	it('drops meta columns that no longer exist rather than rendering blanks', () => {
		const r = resolveView(table(COLS, { style: 'grid', metaColumns: ['status', 'ghost'] }));
		expect(r.meta.map((m) => m.key)).toEqual(['status']);
	});

	it('does not reuse one column for two roles', () => {
		const r = resolveView(table([col('only', 'text')], { style: 'grid' }));
		expect(r.title?.key).toBe('only');
		expect(r.body).toBeNull();
	});
});

describe('orderRows', () => {
	const rows = [
		{ id: 'a', created: 100 },
		{ id: 'b', created: 300 },
		{ id: 'c', created: 200 }
	];

	it('only the timeline reorders — every other style keeps the table order', () => {
		for (const style of ['grid', 'blog', 'tiles'] as const) {
			const v = resolveView(table(COLS, { style, bodyColumn: 'research' }));
			expect(orderRows(rows, v).map((r) => r.id)).toEqual(['a', 'b', 'c']);
		}
	});

	it('timeline is newest first', () => {
		const v = resolveView(table(COLS, { style: 'timeline', dateColumn: 'created' }));
		expect(orderRows(rows, v).map((r) => r.id)).toEqual(['b', 'c', 'a']);
	});

	it('a row with no parseable date SINKS but is never dropped', () => {
		// The corpus and the view must not disagree about how many rows exist.
		const v = resolveView(table(COLS, { style: 'timeline', dateColumn: 'created' }));
		const out = orderRows([...rows, { id: 'x' } as (typeof rows)[0]], v);
		expect(out).toHaveLength(4);
		expect(out[out.length - 1].id).toBe('x');
	});
});

describe('formatWhen', () => {
	it('accepts epoch seconds, epoch ms and an ISO string', () => {
		for (const raw of [1_780_000_000, 1_780_000_000_000, '2026-05-29T00:00:00Z']) {
			expect(formatWhen(raw)).not.toBe('—');
		}
	});

	it('says nothing rather than lying when the value is unparseable', () => {
		for (const raw of [null, undefined, 'not a date', {}]) expect(formatWhen(raw)).toBe('—');
	});
});
