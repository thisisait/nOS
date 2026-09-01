import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
	resolveView,
	orderRows,
	timelineSections,
	formatWhen,
	inboxHref,
	VIEW_ACTIONS
} from './view';
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

// ── timeline sections (2026-08-31) ──────────────────────────────────────────
//
// The roadmap complaint, pinned: 122 rows as one flat dot-list read as a chat
// feed. Sections make the time axis visible (month headings) and give the
// undated tail — which `orderRows` sinks — ONE honest bucket named after the
// date column itself, instead of a wall of "—".
describe('timelineSections', () => {
	const tl = resolveView(
		table(COLS, { style: 'timeline', titleColumn: 'title', dateColumn: 'created' })
	);
	const rows = [
		{ id: 'a', title: 'a', created: '2026-09-02' },
		{ id: 'b', title: 'b', created: '2026-09-20' },
		{ id: 'c', title: 'c', created: 1754006400 }, // epoch seconds, Aug 2026
		{ id: 'd', title: 'd', created: '' },
		{ id: 'e', title: 'e', created: null as unknown as string }
	];

	it('groups the ordered rows by month and buckets the undated tail last', () => {
		const secs = timelineSections(orderRows(rows, tl), tl);
		expect(secs.map((s) => s.rows.length).reduce((x, y) => x + y, 0)).toBe(rows.length);
		// newest month first, then the undated bucket — named after the COLUMN,
		// so a roadmap says "no Target" and this table says "no Created".
		expect(secs.at(-1)?.label).toBe('no Created');
		expect(
			secs
				.at(-1)
				?.rows.map((r) => r.id)
				.sort()
		).toEqual(['d', 'e']);
		expect(secs[0].rows.map((r) => r.id)).toEqual(['b', 'a']);
		// two dated months → two labeled sections before the undated one
		expect(secs).toHaveLength(3);
		expect(secs[0].label).not.toBe(secs[1].label);
	});

	it('every other style gets one unlabeled section — no second code path', () => {
		const grid = resolveView(table(COLS));
		const secs = timelineSections(rows, grid);
		expect(secs).toEqual([{ label: '', rows }]);
	});

	it('an empty table is one empty section, not zero sections', () => {
		expect(timelineSections([], tl)).toEqual([{ label: '', rows: [] }]);
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

// ── chat (2026-08-31) ────────────────────────────────────────────────────────
//
// The style the caddy-sessions table is for: one row is one EXCHANGE, because a
// caddy turn is a sentence in and an answer out. Two columns are load-bearing,
// so a chat missing either degrades to the grid rather than rendering a list
// with round corners — the same rule blog and timeline already carry.
//
// NOT YET DECLARABLE END TO END, and the test says so rather than the comment
// alone: KEAP validates `view.style` against its own enum (shared/contracts/
// table.ts, tableViewStyleSchema), so a table definition carrying
// `style: chat` would be REFUSED at seed time until that enum learns the word.
// This half is the renderer's, and it is honest on its own: the resolver
// accepts chat, degrades correctly, and does nothing surprising.
describe('chat style', () => {
	const table = (view: unknown) =>
		({
			id: 'caddy-sessions',
			title: 'Caddy sessions',
			columns: [
				{ key: 'transcript', label: 'What was said', kind: 'text' },
				{ key: 'summary', label: 'Answer', kind: 'text' },
				{ key: 'started', label: 'Started', kind: 'date' }
			],
			view
		}) as unknown as Parameters<typeof resolveView>[0];

	it('resolves both halves of the exchange', () => {
		const v = resolveView(table({ style: 'chat', askColumn: 'transcript', bodyColumn: 'summary' }));
		expect(v.style).toBe('chat');
		expect(v.ask?.key).toBe('transcript');
		expect(v.body?.key).toBe('summary');
		expect(v.degradedFrom).toBeUndefined();
	});

	it('degrades to grid when the asking side is missing', () => {
		const v = resolveView(table({ style: 'chat', bodyColumn: 'summary' }));
		expect(v.style).toBe('grid');
		expect(v.degradedFrom).toBe('chat');
		expect(v.ask).toBeNull();
	});

	it('degrades when the answer column is gone, and says so', () => {
		const v = resolveView(table({ style: 'chat', askColumn: 'transcript', bodyColumn: 'nope' }));
		expect(v.degradedFrom).toBe('chat');
	});

	it('never sets ask for another style', () => {
		const v = resolveView(table({ style: 'grid', askColumn: 'transcript' }));
		expect(v.ask).toBeNull();
	});
});

// ── collab v1 (2026-09-01) ───────────────────────────────────────────────────
//
// The conversation surface's one pure helper: a missing ref is NO LINK.
describe('inboxHref', () => {
	it('builds the hand-off from the fixed column', () => {
		expect(inboxHref('https://wing.dev.local/', { id: '1', session_uuid: 'a b' })).toBe(
			'https://wing.dev.local/inbox?ref=a%20b'
		);
	});

	it('is null without a ref or without Wing — an offer that opens nothing must not', () => {
		expect(inboxHref('https://wing.dev.local', { id: '1' })).toBeNull();
		expect(inboxHref('https://wing.dev.local', { id: '1', session_uuid: '  ' })).toBeNull();
		expect(inboxHref('', { id: '1', session_uuid: 'u' })).toBeNull();
		expect(inboxHref('javascript:alert(1)', { id: '1', session_uuid: 'u' })).toBeNull();
	});
});

describe('VIEW_ACTIONS', () => {
	it('is a closed catalog, and every member has an arm in the renderer', () => {
		// The fail-closed rule from view.ts's own header: the handler ships
		// first, the id second. This reads the RENDERER, not this file's prose.
		const src = readFileSync(
			new URL('../components/DataTableApp.svelte', import.meta.url),
			'utf-8'
		);
		const arms = src.slice(src.indexOf('const OFFER_ARMS'));
		for (const a of VIEW_ACTIONS) expect(arms).toContain(`'${a}':`);
	});
});
