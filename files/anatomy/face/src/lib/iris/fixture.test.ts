// Every to_shell sample of the contract fixture, rendered: each string the wire
// carried must reach the page as text (gate: tests/anatomy/test_pupil_renders_the_fixture.py).
import { readFileSync } from 'node:fs';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import { number, shownValue, signed } from './fmt';
import { header } from './form';
import ApprovalCard from './ApprovalCard.svelte';
import Message from './Message.svelte';
import type { Component, ToShell, Value } from './wire';

// PUPIL_FIXTURE: a planted copy (tests/anatomy/test_pupil_renders_the_fixture.py) must go red here.
const FIXTURE =
	process.env.PUPIL_FIXTURE ??
	new URL('../../../../contracts/thalamus-shell.fixture.json', import.meta.url);
const fx = JSON.parse(readFileSync(FIXTURE, 'utf8')) as {
	to_shell: { case: string; msg: ToShell }[];
};
// Each kind's props, as wire.ts types them: a prop the fixture renames is named here, not drawn as nothing.
const PROPS: Record<string, string[]> = {
	action_approval: ['action', 'app', 'params', 'says'],
	table_results: ['columns', 'matched', 'name', 'projected', 'query', 'rows', 'table', 'total'],
	row_diff_approval: ['cells', 'lines', 'op', 'read_from', 'row_id', 'table', 'title', 'warning'],
	table_schema_approval: ['columns', 'description', 'title', 'visibility'],
	column_add_approval: ['columns', 'existing', 'table', 'title'],
	inbox_list: ['items', 'refused'],
	approvals_list: ['items', 'unknown'],
	red_status: ['hold_count', 'holds', 'red_count', 'reds'],
	markdown: ['text'],
	table: ['columns', 'rows', 'title'],
	list: ['items', 'ordered', 'title'],
	record: ['fields', 'title'],
	chart: ['chart', 'series', 'title', 'x'],
	tree: ['nodes', 'title'],
	timeline: ['items', 'title'],
	graph: ['edges', 'nodes', 'title'],
	sequence: ['participants', 'steps', 'title'],
	knowledge_tree: ['focus', 'hidden', 'nodes', 'title'],
	form: ['fields', 'form', 'omitted', 'prefill', 'table', 'title'],
	choice: ['id', 'multi', 'options', 'question', 'suggested'],
	dashboard: ['dropped', 'lens', 'name', 'widgets'],
	kpi: ['delta', 'delta_label', 'source', 'title', 'unit', 'value']
};
const KINDS = Object.keys(PROPS);
// Props a sample may leave out (an insert names no row); any other missing or extra prop is a rename.
const OPTIONAL: Record<string, string[]> = {
	row_diff_approval: ['lines', 'read_from', 'row_id', 'warning'],
	table_schema_approval: ['description'],
	form: ['prefill'],
	knowledge_tree: ['title'],
	kpi: ['delta', 'delta_label', 'source', 'unit']
};

const text = (html: string) =>
	html
		.replace(/<[^>]*>/g, ' ')
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'")
		.replace(/&amp;/g, '&')
		.replace(/\s+/g, ' ');

const draw = (msg: ToShell) => text(render(Message, { props: { msg } }).body);

/** The strings and counts a renderer owes the person; table cells outside `columns` are not shown (as shell.rs). */
function owed(v: Value | Component, skip: Set<string> = new Set()): string[] {
	if (typeof v === 'string') return [v];
	// A zero count is said as words or left out ("nothing red"), as shell.rs does.
	if (typeof v === 'number') return v === 0 ? [] : [String(v)];
	if (Array.isArray(v)) return v.flatMap((x) => owed(x));
	if (v && typeof v === 'object')
		return Object.entries(v).flatMap(([k, x]) => (skip.has(k) ? [] : owed(x as Value)));
	return [];
}

function owedBy(c: Component): string[] {
	// Markdown owes its words, not its markup: the markdown tests below check each node.
	if (c.kind === 'markdown') return ['Next on the roadmap', 'restic fork', 'nos dtt list roadmap'];
	// A form owes its own header, each label and option, and what it cannot edit; not the minted id.
	if (c.kind === 'form')
		return [
			header(c.props),
			...c.props.fields.flatMap((f) => [f.label, ...(f.options ?? [])]),
			...c.props.omitted.map((o) => `${o.key} (${o.kind})`),
			'Add row'
		];
	// A choice owes its question, every label and note, the suggestion's mark and the button; not the minted id.
	if (c.kind === 'choice')
		return [
			c.props.question,
			...c.props.options.flatMap((o) => [o.label, ...(o.note ? [o.note] : [])]),
			'navrženo',
			'Odpovědět'
		];
	// An offer owes its name, each lens column and set value, each widget title, what was left out and why, and the button.
	if (c.kind === 'dashboard')
		return [
			c.props.name,
			...c.props.lens.flatMap((l) => [l.column, ...(l.value ? [l.value] : [])]),
			...c.props.widgets.map((w) => w.title),
			...c.props.dropped.flatMap((d) => [d.title, d.why]),
			'Place here',
			'Place on a new board'
		];
	// A KPI owes its number in the shell locale, its unit, the delta as a signed word-free arrow, and where it came from.
	if (c.kind === 'kpi') {
		const k = c.props;
		return [
			k.title,
			number(k.value).replace(/\s+/g, ' '),
			...(k.unit ? [k.unit] : []),
			...(k.delta !== undefined ? [signed(k.delta).replace(/\s+/g, ' ')] : []),
			...(k.delta_label ? [k.delta_label] : []),
			...(k.source ? [k.source] : [])
		];
	}
	if (c.kind !== 'table_results') return owed(c.props as unknown as Value);
	// The table's name, not its id (live 2026-10-12: the header showed the roadmap's UUID).
	const { name, query, matched, total, columns, rows } = c.props;
	const counts = [`${rows.length} of ${matched} matched`, `(${total} rows)`];
	// A cell owes its reading in the shell locale (fmt.ts: 42 under amount is CZK 42.00); the wire keeps the raw value.
	const read = (v: Value | undefined, k: string) =>
		typeof v === 'number' || typeof v === 'string'
			? v === 0
				? []
				: [shownValue(v, k).replace(/\s+/g, ' ')]
			: owed(v ?? null);
	return [
		name,
		query,
		...counts,
		...columns,
		...rows.flatMap((r) => [r.__id, ...columns.flatMap((k) => read(r.cells[k], k))])
	];
}

describe('the pupil renders the contract fixture', () => {
	const components = fx.to_shell.flatMap((c) => ('component' in c.msg ? [c.msg.component] : []));

	it('the fixture holds every kind the pupil knows, and no other', () => {
		expect(new Set(components.map((c) => c.kind))).toEqual(new Set(KINDS));
	});

	for (const c of components)
		it(`${c.kind} carries the props the pupil reads`, () => {
			const keys = Object.keys(c.props).sort();
			const opt = OPTIONAL[c.kind] ?? [];
			expect(keys, `${c.kind} props`).toEqual(
				PROPS[c.kind].filter((k) => keys.includes(k) || !opt.includes(k))
			);
		});

	for (const { case: name, msg } of fx.to_shell) {
		it(`draws "${name}" (${msg.t})`, () => {
			const page = draw(msg);
			expect(page).not.toContain('no renderer for component kind');
			// A chat line's session id is the banner's to show, not every line's.
			const skip = new Set(msg.t === 'session' ? ['t'] : ['t', 'session']);
			const want = 'component' in msg ? owedBy(msg.component) : owed(msg as unknown as Value, skip);
			for (const s of want) expect(page.toLowerCase(), `${name}: ${s}`).toContain(s.toLowerCase());
		});
	}

	it('says when a search was substring, and when it was semantic', () => {
		const msg = fx.to_shell.find(
			(c) => 'component' in c.msg && c.msg.component.kind === 'table_results'
		)!.msg;
		expect(draw(msg)).toContain('substring match, not semantic');
		const semantic = structuredClone(msg) as Extract<ToShell, { t: 'render' }>;
		(semantic.component.props as { projected: boolean }).projected = true;
		expect(draw(semantic)).not.toContain('substring');
		expect(draw(semantic)).toContain('semantic');
	});

	it('a table and a record read their values in the shell locale', () => {
		const table = draw({
			t: 'render',
			session: 's',
			component: {
				kind: 'table',
				props: {
					columns: ['amount', 'due'],
					rows: [[1234.5, '2026-03-05']]
				}
			}
		});
		expect(table).toContain('CZK 1,234.50');
		expect(table).toContain('3/5/2026');
		const record = draw({
			t: 'render',
			session: 's',
			component: {
				kind: 'record',
				props: {
					fields: [
						{ key: 'amount', value: 1234.5 },
						{ key: 'due', value: '2026-03-05' }
					]
				}
			}
		});
		expect(record).toContain('CZK 1,234.50');
		expect(record).toContain('3/5/2026');
	});

	it('a table is headed by its name and counts, never its id', () => {
		const msg: ToShell = {
			t: 'render',
			session: 's',
			component: {
				kind: 'table_results',
				props: {
					table: '0b6f6a1e-roadmap-uuid',
					name: 'nOS Roadmap',
					query: 'status = next',
					matched: 23,
					total: 122,
					columns: ['title'],
					projected: false,
					rows: [{ __id: 'r1', cells: { title: 'pupil-eye' } }]
				}
			}
		};
		const page = draw(msg);
		expect(page).toContain('nOS Roadmap — 1 of 23 matched (122 rows)');
		expect(page).toContain('status = next');
		expect(page).not.toContain('0b6f6a1e-roadmap-uuid');
	});

	it('an approval head names the table by title and id, and what the write does', () => {
		const card = (name: string) => draw(fx.to_shell.find((c) => c.case === name)!.msg);
		expect(card('a row edit awaits approval')).toContain(
			'update nOS Roadmap (roadmap) / backup-restic-fork'
		);
		const insert = card('a new row awaits approval');
		expect(insert).toContain(
			'insert a new row in Expenses (expenses) — nothing is written unless you approve'
		);
		expect(insert).toContain('contains text from search_memory');
		expect(card('a row edit awaits approval')).not.toContain('contains text from');
	});

	it('a delete card says delete in red, and every value it removes', () => {
		const msg = fx.to_shell.find((c) => c.case === 'a row delete awaits approval')!.msg;
		const html = render(Message, { props: { msg } }).body;
		expect(text(html)).toContain('delete Expenses (expenses) / e3');
		expect(text(html)).toContain('kind : "travel" → (deleted)');
		expect(html).toMatch(/class="bad[^"]*"[^>]*>[^<]*deletes the whole row/);
		const waiting = {
			approval: 'a',
			component: (msg as Extract<ToShell, { t: 'approval_request' }>).component
		};
		const card = render(ApprovalCard, {
			props: { waiting, of: 1, whole: true, onseen: () => {}, ondecide: () => {} }
		}).body;
		expect(text(card)).toContain('approve deleting this row?');
	});

	// Local bench 2026-10-16: asked for bench row 10, the card was for row 19.
	it('a card for a row other than the one named says so in red, before its cells', () => {
		const msg = fx.to_shell.find(
			(c) => c.case === 'a delete of a row other than the one named'
		)!.msg;
		const html = render(Message, { props: { msg } }).body;
		expect(html).toMatch(
			/class="bad[^"]*"[^>]*>[^<]*you asked for "10"; this row is "bench row 19"/
		);
		expect(html.indexOf('you asked for')).toBeLessThan(html.indexOf('title'));
		expect(
			draw(fx.to_shell.find((c) => c.case === 'a row delete awaits approval')!.msg)
		).not.toContain('you asked for');
	});

	it('a table card says create, private, and every column whole', () => {
		const msg = fx.to_shell.find((c) => c.case === 'a new table awaits approval')!.msg;
		const page = draw(msg);
		for (const want of [
			'create table Expenses, private to you — nothing is created unless you approve',
			'What I spend on trips',
			'item (Item): text, required',
			'amount (Amount): number',
			'category (Category): select of travel, food',
			'settled (Settled): boolean',
			'trip (Trip): rowRef → Trips (t-trips), shown by name'
		])
			expect(page).toContain(want);
		const waiting = {
			approval: 'a',
			component: (msg as Extract<ToShell, { t: 'approval_request' }>).component
		};
		const card = render(ApprovalCard, {
			props: { waiting, of: 1, whole: true, onseen: () => {}, ondecide: () => {} }
		}).body;
		expect(text(card)).toContain('approve creating this table?');
	});

	it('a column add card shows the table read-only and every new column whole', () => {
		const msg = fx.to_shell.find((c) => c.case === 'new columns await approval')!.msg;
		const page = draw(msg);
		for (const want of [
			'add columns to Expenses (expenses) — nothing is added unless you approve',
			'has item (Item): text',
			'has receipt (Receipt): file',
			'+ paid_on (Paid on): date',
			'+ category (Category): select of travel, food',
			'existing rows get no value in the new columns'
		])
			expect(page).toContain(want);
		const waiting = {
			approval: 'a',
			component: (msg as Extract<ToShell, { t: 'approval_request' }>).component
		};
		const card = render(ApprovalCard, {
			props: { waiting, of: 1, whole: true, onseen: () => {}, ondecide: () => {} }
		}).body;
		expect(text(card)).toContain('approve adding these columns?');
	});

	it('an empty diff side reads (empty), not blank', () => {
		const msg = fx.to_shell.find((c) => c.msg.t === 'approval_request')!.msg;
		expect(draw(msg)).toContain('(empty) → "landed"');
	});

	// Live 2026-10-12: a roadmap search drew `body` as a column and squeezed the rest to one letter wide.
	it('a long-text column folds into the row, the short ones stay columns', () => {
		const body = 'Session 2026-09-20 against FINISHING-REPORT.md. '.repeat(12);
		const msg: ToShell = {
			t: 'render',
			session: 's',
			component: {
				kind: 'table_results',
				props: {
					table: 'roadmap',
					name: 'nOS Roadmap',
					query: 'all rows',
					matched: 1,
					total: 1,
					columns: ['body', 'slug', 'status'],
					projected: false,
					rows: [{ __id: 'r1', cells: { body, slug: 'pupil-eye', status: 'next' } }]
				}
			}
		};
		const html = render(Message, { props: { msg } }).body;
		const heads = [...html.matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1].trim());
		expect(heads).toEqual(['slug', 'status']);
		expect(html).toContain('<details');
		expect(text(html)).toContain(body.trim());
	});

	// Live 2026-10-13: a count (limit 0) drew "0 of 118 matched" over a header row of every column.
	it('a count draws the count, not an empty table', () => {
		const msg: ToShell = {
			t: 'render',
			session: 's',
			component: {
				kind: 'table_results',
				props: {
					table: 'roadmap',
					name: 'nOS Roadmap',
					query: 'track = security',
					matched: 118,
					total: 700,
					columns: ['slug', 'body'],
					projected: false,
					rows: []
				}
			}
		};
		const html = render(Message, { props: { msg } }).body;
		expect(html).not.toContain('<table');
		expect(text(html)).toContain('nOS Roadmap — 118 matched (700 rows)');
	});

	// Live 2026-10-13: a grouped count drew "8 of136" and a "▶ platform" fold under every group.
	it('a group table has its spaces and no fold of what is already on screen', () => {
		const msg: ToShell = {
			t: 'render',
			session: 's',
			component: {
				kind: 'table_results',
				props: {
					table: 'roadmap',
					name: 'nOS Roadmap',
					query: 'grouped by track',
					matched: 136,
					total: 700,
					columns: ['track', 'count'],
					projected: false,
					rows: [{ __id: 'platform', cells: { track: 'platform', count: 62 } }]
				}
			}
		};
		const html = render(Message, { props: { msg } }).body;
		expect(text(html)).toContain('1 of 136 matched');
		expect(html).not.toContain('<details');
	});

	it('a tool the thalamus runs is said in the log', () => {
		const html = draw({ t: 'activity', session: 's', phase: { tool: { name: 'query_rows' } } });
		expect(html).toContain('query_rows');
	});

	it('markup in a model string stays text', () => {
		const html = render(Message, {
			props: { msg: { t: 'text', session: 's', text: '<img src=x onerror=alert(1)>' } }
		}).body;
		expect(html).not.toContain('<img');
		expect(html).toContain('&lt;img');
	});
});

const html = (msg: ToShell) => render(Message, { props: { msg } }).body;
const say = (text: string): ToShell => ({ t: 'text', session: 's', text });

describe('markdown is drawn as nodes, never as markup', () => {
	const sample = fx.to_shell.find(
		(c) => 'component' in c.msg && c.msg.component.kind === 'markdown'
	)!.msg;

	it('the fixture sample draws every block type', () => {
		const h = html(sample);
		for (const tag of [
			'<h1',
			'<h2',
			'<h3',
			'<p',
			'<ul',
			'<ol',
			'<li',
			'<pre',
			'<strong',
			'<em',
			'<code'
		])
			expect(h, tag).toContain(tag);
		expect(h).not.toContain('**');
		expect(h).not.toContain('```');
	});

	// Live 2026-10-12: the pupil drew `**49 řádků**` raw.
	it('a text message in markdown draws <strong>, no literal **', () => {
		const h = html(say('Tabulka má **49 řádků**.'));
		expect(h).toContain('<strong>49 řádků</strong>');
		expect(h).not.toContain('**');
	});

	it('a link is text: label (url) for http(s), the label alone otherwise, never an anchor', () => {
		const h = html(sample);
		expect(h).not.toMatch(/<a[\s>]/);
		expect(text(h)).toContain('the doctrine (https://thisisait.eu)');
		expect(text(h)).toContain('a local file');
		expect(h).not.toContain('file:///etc/passwd');
	});

	it('markup inside markdown stays text', () => {
		const h = html(say('**<img src=x onerror=alert(1)>** and `<script>`'));
		expect(h).not.toContain('<img');
		expect(h).not.toContain('<script');
		expect(h).toContain('&lt;img');
	});

	it('text that is not markdown is one paragraph of itself', () => {
		expect(text(html(say('a * b = c, 2 * 3')))).toContain('a * b = c, 2 * 3');
	});
});

describe('the kinds the model shows are drawn as their shapes', () => {
	const of = (kind: string) =>
		fx.to_shell.find((c) => 'component' in c.msg && c.msg.component.kind === kind)!.msg;

	it('a table is a grid of its columns, with no row id', () => {
		const h = html(of('table'));
		const heads = [...h.matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1].trim());
		expect(heads).toEqual(['track', 'next', 'done']);
		expect(h.match(/<tr/g)?.length).toBe(3);
	});

	it('an ordered list is an <ol>, and a tone is said in words', () => {
		const h = html(of('list'));
		expect(h).toContain('<ol');
		expect(text(h)).toContain('warn chart — not built yet');
	});

	it('a record value that is not a scalar is drawn as JSON text in a <pre>', () => {
		const h = html(of('record'));
		expect(h).toContain('<pre');
		expect(text(h)).toContain('"next": "I4c"');
	});
});

describe('a chart is SVG marks and text labels, inside its box', () => {
	type Chart = Extract<Component, { kind: 'chart' }>;
	const sample = fx.to_shell.find(
		(c) => 'component' in c.msg && c.msg.component.kind === 'chart'
	)!.msg;
	const chart = (props: Chart['props']): ToShell => ({
		t: 'render',
		session: 's',
		component: { kind: 'chart', props }
	});
	// Every <text> as drawn: x, y, anchor, size, and the words.
	const labels = (h: string) =>
		[...h.matchAll(/<text([^>]*)>([^<]*)<\/text>/g)].map(([, a, t]) => {
			const at = (k: string) => a.match(new RegExp(`${k}="([^"]*)"`))?.[1];
			return {
				x: Number(at('x')),
				y: Number(at('y')),
				anchor: at('text-anchor') ?? 'start',
				size: Number(at('font-size')),
				t: text(t).trim()
			};
		});

	// The box the chart drew itself into: it follows its container, so read it, never assume it.
	const box = (h: string) => {
		const m = h.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);
		expect(m, 'the svg has a viewBox').toBeTruthy();
		return { W: Number(m![1]), H: Number(m![2]) };
	};
	const inside = (h: string, what: string) => {
		const { W, H } = box(h);
		for (const l of labels(h)) {
			// A glyph is at most 0.6em wide in the UI font.
			const w = l.t.length * l.size * 0.6;
			const [lo, hi] =
				l.anchor === 'end'
					? [l.x - w, l.x]
					: l.anchor === 'middle'
						? [l.x - w / 2, l.x + w / 2]
						: [l.x, l.x + w];
			expect(lo, `${what}: ${l.t}`).toBeGreaterThanOrEqual(0);
			expect(hi, `${what}: ${l.t}`).toBeLessThanOrEqual(W);
			expect(l.y - l.size, `${what}: ${l.t}`).toBeGreaterThanOrEqual(0);
			expect(l.y, `${what}: ${l.t}`).toBeLessThanOrEqual(H);
		}
	};

	it('every value of a bar chart is a bar, said as series, x and value', () => {
		const h = html(sample);
		const c = (sample as Extract<ToShell, { t: 'render' }>).component as Chart;
		expect(h).toContain('<svg');
		expect(h.match(/<rect[^>]*class="bar/g)?.length).toBe(6);
		for (const s of c.props.series)
			for (const [x, y] of s.points) expect(text(h)).toContain(`${s.name} · ${x}: ${y}`);
		expect(text(h)).toContain('Rows by status');
	});

	it('the y axis is labelled from the data scale', () => {
		const ys = labels(html(sample))
			.filter((l) => l.anchor === 'end')
			.map((l) => l.t);
		expect(ys).toContain('0');
		expect(ys).toContain('95');
	});

	it('a line chart is one polyline per series, a vertex per point', () => {
		const h = html(
			chart({
				chart: 'line',
				x: 'category',
				series: [
					{
						name: 'open',
						points: [
							['mon', 3],
							['tue', 5],
							['wed', 2]
						]
					},
					{
						name: 'closed',
						points: [
							['mon', 1],
							['tue', -2],
							['wed', 4]
						]
					}
				]
			})
		);
		const lines = [...h.matchAll(/<polyline[^>]*points="([^"]*)"/g)].map((m) =>
			m[1].trim().split(/\s+/)
		);
		expect(lines.map((l) => l.length)).toEqual([3, 3]);
		expect(text(h)).toContain('closed · tue: -2');
	});

	it('eight columns keep x labels readable and inside the box', () => {
		const names = [
			'platform',
			'pupilbox',
			'billingx',
			'hostingx',
			'edgeboxx',
			'vaultedx',
			'memoryxx',
			'faceappx'
		];
		const h = html(
			chart({
				chart: 'bar',
				x: 'category',
				series: [{ name: 'rows', points: names.map((x, i) => [x, i + 1]) }]
			})
		);
		const drawn = labels(h)
			.filter((l) => l.anchor === 'middle')
			.map((l) => l.t);
		expect(drawn).toEqual(names);
		const axis = h.match(/<line[^>]*class="axis[^"]*"[^>]*/)?.[0] ?? '';
		const num = (k: string) => Number(axis.match(new RegExp(`${k}="([^"]*)"`))?.[1]);
		expect(num('x2') - num('x1'), 'plot width').toBeGreaterThanOrEqual(box(h).W - 20);
		inside(h, 'bar');
	});

	it('every label stays inside the viewBox, even 6 series of 60 long, wide-ranged points', () => {
		const series = Array.from({ length: 6 }, (_, k) => ({
			name: `series number ${k}`,
			points: Array.from(
				{ length: 60 },
				(_, i) => [`a rather long x label ${i}`, (i - 30) * 10 ** (k + 4)] as [string, number]
			)
		}));
		for (const kind of ['bar', 'line'] as const) {
			const h = html(chart({ title: 'wide', chart: kind, x: 'category', series }));
			expect(labels(h).length).toBeGreaterThan(2);
			inside(h, kind);
		}
	});

	// An image hides its marks from a screen reader; an interactive chart is a group of focusable marks.
	it('a chart is a labelled group of focusable marks, not an image', () => {
		const h = html(sample);
		const svg = h.match(/<svg[^>]*>/)?.[0] ?? '';
		expect(svg).toContain('role="group"');
		expect(svg).toMatch(/aria-label="[^"]*Rows by status[^"]*"/);
		expect(h).not.toContain('role="img"');
		const marks = h.match(/<rect[^>]*class="bar[^>]*>/g) ?? [];
		expect(marks.length).toBe(6);
		for (const m of marks) expect(m).toContain('tabindex="0"');
	});

	const tips = (h: string, c: Chart['props']) => {
		for (const s of c.series)
			for (const [x, y] of s.points) expect(text(h)).toContain(`${s.name} · ${x}: ${y}`);
	};

	it('a pie is one <path> per value, each with its <title>', () => {
		const c: Chart['props'] = {
			title: 'Share',
			chart: 'pie',
			x: 'category',
			series: [
				{
					name: 'rows',
					points: [
						['pupil', 4],
						['keap', 0],
						['face', 6]
					]
				}
			]
		};
		const h = html(chart(c));
		expect(h.match(/<path[^>]*class="slice[^>]*>\s*<title>/g)?.length).toBe(3);
		tips(h, c);
		for (const x of ['pupil', 'keap', 'face']) expect(text(h)).toContain(x);
	});

	it('a scatter is one <circle> per point over a number axis', () => {
		const c: Chart['props'] = {
			chart: 'scatter',
			x: 'number',
			series: [
				{
					name: 'p50',
					points: [
						['3', 5],
						['10', 12.5]
					]
				},
				{
					name: 'p99',
					points: [
						['3', 9],
						['7', 30],
						['-2', 1]
					]
				}
			]
		};
		const h = html(chart(c));
		expect(h.match(/<circle/g)?.length).toBe(5);
		expect(h).not.toContain('<polyline');
		tips(h, c);
		expect(text(h)).toContain('number x');
	});

	it('an area is a filled path per series; a stacked bar a bar per value', () => {
		const series = [
			{
				name: 'open',
				points: [
					['mon', 3],
					['tue', 5]
				] as [string, number][]
			},
			{
				name: 'done',
				points: [
					['mon', 1],
					['tue', 2]
				] as [string, number][]
			}
		];
		const area = html(chart({ chart: 'area', x: 'category', series }));
		expect(area.match(/<path[^>]*class="area/g)?.length).toBe(2);
		const stacked = html(chart({ chart: 'stacked_bar', x: 'category', series }));
		expect(stacked.match(/<rect[^>]*class="bar/g)?.length).toBe(4);
		tips(stacked, { chart: 'stacked_bar', x: 'category', series });
	});

	it('a widget chart with no rows yet says so', () => {
		const h = html(
			chart({
				title: 'Expenses by kind',
				chart: 'bar',
				x: 'category',
				series: [{ name: 'rows', points: [] }]
			})
		);
		expect(text(h)).toContain('no rows yet');
		expect(h).not.toContain('<rect');
	});

	it('every kind, on every axis, keeps its labels inside the viewBox', () => {
		const day = (i: number) => new Date(Date.UTC(2026, 0, 1 + i * 6)).toISOString().slice(0, 10);
		const cases: Chart['props'][] = [
			{
				chart: 'line',
				x: 'time',
				series: [
					{
						name: 'rows',
						points: Array.from({ length: 60 }, (_, i) => [day(i), i * 1e6] as [string, number])
					}
				]
			},
			{
				chart: 'scatter',
				x: 'number',
				series: [
					{
						name: 'rows',
						points: Array.from(
							{ length: 60 },
							(_, i) => [String(i * 12345.678 - 99999), -i] as [string, number]
						)
					}
				]
			},
			{
				chart: 'area',
				x: 'category',
				series: [
					{
						name: 'rows',
						points: Array.from(
							{ length: 60 },
							(_, i) => [`a rather long x label ${i}`, i] as [string, number]
						)
					}
				]
			},
			{
				chart: 'stacked_bar',
				x: 'time',
				series: [0, 1].map((k) => ({
					name: `s${k}`,
					points: Array.from({ length: 30 }, (_, i) => [day(i), i + k] as [string, number])
				}))
			},
			{
				chart: 'pie',
				x: 'category',
				series: [
					{
						name: 'rows',
						points: [
							['a', 1],
							['b', 2]
						]
					}
				]
			}
		];
		for (const c of cases) inside(html(chart({ title: 'every axis', ...c })), `${c.chart}/${c.x}`);
	});

	it('a chart draws no link, no foreign markup, no script', () => {
		const h = html(
			chart({
				chart: 'bar',
				x: 'category',
				series: [{ name: '<script>x</script>', points: [['<img onerror=1>', 1]] }]
			})
		);
		expect(h).not.toMatch(/<(a|foreignObject|script|img)[\s>]/);
		expect(h).toContain('&lt;img');
	});
});

describe('a graph is SVG nodes and edges, every word as text', () => {
	const sample = fx.to_shell.find(
		(c) => 'component' in c.msg && c.msg.component.kind === 'graph'
	)!.msg;
	const g = (
		(sample as Extract<ToShell, { t: 'render' }>).component as Extract<Component, { kind: 'graph' }>
	).props;

	it('one <text> per node label and one <path> per edge', () => {
		const h = html(sample);
		const labels = [...h.matchAll(/<text[^>]*class="label[^"]*"[^>]*>([^<]*)<\/text>/g)].map((m) =>
			text(m[1]).trim()
		);
		expect(labels).toEqual(g.nodes.map((n) => n.label));
		expect(h.match(/<path[^>]*class="edge/g)?.length).toBe(g.edges.length);
		for (const e of g.edges) if (e.label) expect(text(h)).toContain(e.label);
	});
});

describe('a sequence is SVG lifelines and arrows, every word as text', () => {
	const sample = fx.to_shell.find(
		(c) => 'component' in c.msg && c.msg.component.kind === 'sequence'
	)!.msg;
	const q = (
		(sample as Extract<ToShell, { t: 'render' }>).component as Extract<
			Component,
			{ kind: 'sequence' }
		>
	).props;

	it('a <text> per participant and step, a <path> per message', () => {
		const h = html(sample);
		const drawn = [...h.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => text(m[1]).trim());
		for (const p of q.participants) expect(drawn).toContain(p);
		for (const s of q.steps)
			expect(drawn).toContain('text' in s ? s.text : 'note' in s ? s.note : s.phase);
		expect(h.match(/<path[^>]*class="msg/g)?.length).toBe(
			q.steps.filter((s) => 'from' in s).length
		);
	});
});

describe('a kpi is one big number, its delta said as text', () => {
	type Kpi = Extract<Component, { kind: 'kpi' }>['props'];
	const kpi = (props: Kpi): ToShell => ({
		t: 'widget',
		session: 's',
		widget: 'k',
		component: { kind: 'kpi', props }
	});

	it('the number is the big text node, read in the shell locale with its unit', () => {
		const h = html(kpi({ title: 'Travel spend', value: 12450.5, unit: 'Kč' }));
		expect(h).toMatch(/class="kpi-value[^"]*"[^>]*>12,450.5 Kč</);
		expect(text(h)).toContain('Travel spend');
	});

	it('money reads as CZK when the title names it and no unit is given', () => {
		expect(text(html(kpi({ title: 'sum of amount', value: 42 })))).toContain(
			number(42, true).replace(/\s+/g, ' ')
		);
	});

	it('a delta is an arrow and a sign in text, its word for a screen reader; none is drawn when there is none', () => {
		const up = text(html(kpi({ title: 't', value: 1, delta: 320, delta_label: 'vs last month' })));
		expect(up).toContain('↑ +320');
		expect(up).toContain('up');
		expect(up).toContain('vs last month');
		const down = text(html(kpi({ title: 't', value: 1, delta: -3.5 })));
		expect(down).toContain('↓ −3.5');
		expect(down).toContain('down');
		expect(html(kpi({ title: 't', value: 1 }))).not.toContain('kpi-delta');
	});

	it('a kpi draws no link, no markup from its strings', () => {
		const h = html(kpi({ title: '<img onerror=1>', value: 1, source: '<script>x</script>' }));
		expect(h).not.toMatch(/<(a|script|img)[\s>]/);
		expect(h).toContain('&lt;img');
	});
});
