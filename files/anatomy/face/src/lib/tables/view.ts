/**
 * Render-style resolution for a DataTable.
 *
 * KEAP validates the `view` block at author time (`viewMetaSchema`); this only
 * RESOLVES it for rendering — picks sensible columns when the block names none,
 * and degrades to the grid rather than throwing when it names one that is gone.
 *
 * WHY THE DEGRADE IS DELIBERATE. KEAP refuses a blog with no body column, so a
 * malformed block should not exist. But this client also serves the offline
 * fallback path (`source: 'fallback'`, repo defaults, KEAP unreachable) where
 * the block may be stale relative to the columns it arrives with. A view that
 * silently renders an untitled, bodyless list is worse than a grid: it looks
 * like the style is working. So a style whose REQUIRED column cannot be
 * resolved falls back to the grid, and says so in `degradedFrom`.
 */
import type {
	ColumnSpec,
	DataTable,
	DataTableRow,
	HighlightSpec,
	RowOp,
	RowPredicate,
	TableView
} from '$lib/contracts';

export type ResolvedStyle = 'grid' | 'blog' | 'timeline' | 'tiles' | 'chat';

/**
 * Every action this renderer can offer. A CLOSED CATALOG, in code.
 *
 * `TableView.offer.action` selects from this list; it never carries a command,
 * a URL or a handler. That split is not local caution — it is the rule
 * `state/genome/entity.schema.json` states for the whole estate ("a capability
 * must not be addable by data, so opcodes and handlers stay code, per
 * runtime"), and the reason a model may fill this block at all.
 *
 * TWO MEMBERS, and the fail-closed ordering is the genome's too: the handler
 * ships first and the id joins this list second. A member with no arm in the
 * renderer is a declaration that validates and does nothing.
 *
 * `open-inbox` (collab v1) hands a pending turn to Wing, the only channel that
 * may answer one — it navigates and writes nothing, like the first member. The
 * address is built in code (`inboxHref`) from Wing's own catalog entry and a
 * fixed column; the block chooses the id and the rows, never a URL.
 */
export const VIEW_ACTIONS = ['focus-highlight', 'open-inbox'] as const;
export type ViewAction = (typeof VIEW_ACTIONS)[number];

/** The column `open-inbox` reads its ref from. Fixed in CODE: a data-chosen
 *  key is a data-chosen URL, one indirection short of a data-chosen capability.
 *  ponytail: one column name for one table — generalise when a second table
 *  needs the action, not before. */
export const INBOX_REF_COLUMN = 'session_uuid';

/**
 * Wing's inbox deep-link for a row — or null, which is the whole point.
 *
 * A row with no session ref, or a catalog with no Wing, yields NOTHING rather
 * than a link to `/inbox?ref=` — an offer that opens an empty page looks like
 * it worked. The caller reports the null; it never falls back to a guess.
 */
export function inboxHref(wingBase: string, row: DataTableRow): string | null {
	const ref = row[INBOX_REF_COLUMN];
	if (!/^https?:\/\//.test(wingBase)) return null;
	if (typeof ref !== 'string' || !ref.trim()) return null;
	return `${wingBase.replace(/\/+$/, '')}/inbox?ref=${encodeURIComponent(ref.trim())}`;
}

const ROW_OPS: readonly RowOp[] = ['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'contains'] as const;

/** Caps. A declaration that can grow without bound is a layout that can. */
const MAX_FACETS = 2;
const MAX_HIGHLIGHTS = 4;
const MAX_PREDICATES = 4;
/** A highlight label is a chip. An offer label is a sentence. The two limits
 *  match KEAP's `highlightSpecSchema` / `offerSpecSchema` — a cap that is
 *  tighter here would truncate, at render, a label the store accepted. */
const MAX_LABEL = 48;
const MAX_OFFER_LABEL = 120;

export interface ResolvedHighlight {
	label: string;
	when: RowPredicate[];
}

export interface ResolvedOffer {
	label: string;
	action: ViewAction;
	when: RowPredicate[];
}

export interface ResolvedView {
	style: ResolvedStyle;
	title: ColumnSpec | null;
	body: ColumnSpec | null;
	/** `chat` only: the column holding what was ASKED. The body holds the
	 *  answer, so one row renders as two bubbles. Null for every other style. */
	ask: ColumnSpec | null;
	date: ColumnSpec | null;
	media: ColumnSpec | null;
	meta: ColumnSpec[];
	/** The two filter levels, outer→inner. Resolved columns, ≤2. */
	facets: ColumnSpec[];
	/** Row classes worth jumping to. ≤4, each with ≥1 resolvable predicate. */
	highlights: ResolvedHighlight[];
	/** The single suggestion, or null. */
	offer: ResolvedOffer | null;
	/** Set when a declared style could not be honoured — the UI says so rather
	 *  than quietly rendering something that looks intentional. */
	degradedFrom?: ResolvedStyle;
}

const byKey = (cols: ColumnSpec[], key?: string): ColumnSpec | null =>
	(key && cols.find((c) => c.key === key)) || null;

/** First column of any of `kinds`, skipping ones already spoken for. */
function firstOf(cols: ColumnSpec[], kinds: string[], taken: Set<string>): ColumnSpec | null {
	return cols.find((c) => kinds.includes(c.kind) && !taken.has(c.key)) ?? null;
}

export function resolveView(table: DataTable): ResolvedView {
	const cols = table.columns ?? [];
	const v: TableView = table.view ?? { style: 'grid' };
	const taken = new Set<string>();

	const title = byKey(cols, v.titleColumn) ?? firstOf(cols, ['text'], taken);
	if (title) taken.add(title.key);

	// The body is the reason the non-grid styles exist, so it is never
	// auto-picked as "some other text column" when one was named and is gone —
	// that is precisely the case the degrade below catches.
	const body = byKey(cols, v.bodyColumn);
	if (body) taken.add(body.key);

	const date = byKey(cols, v.dateColumn) ?? firstOf(cols, ['date'], taken);
	if (date) taken.add(date.key);

	const media = byKey(cols, v.mediaColumn) ?? firstOf(cols, ['file'], taken);
	if (media) taken.add(media.key);

	const meta = (v.metaColumns ?? [])
		.map((k) => byKey(cols, k))
		.filter((c): c is ColumnSpec => c !== null);

	// The three generative keys resolve the same way every other one does: a
	// name that resolves to nothing is DROPPED, never guessed at. `narrowView`
	// has usually already removed these at the BFF; resolving again here is what
	// keeps the offline-fallback path (a stale block beside changed columns)
	// from rendering a facet over a column that is gone.
	const facets = (v.facets ?? [])
		.slice(0, MAX_FACETS)
		.map((k) => byKey(cols, k))
		.filter((c): c is ColumnSpec => c !== null);

	const keys = new Set(cols.map((c) => c.key));
	const resolvable = (w: RowPredicate[]): boolean =>
		w.length > 0 && w.every((p) => keys.has(p.column));

	const highlights = (v.highlights ?? [])
		.slice(0, MAX_HIGHLIGHTS)
		.filter((h) => resolvable(h.when ?? []))
		.map((h) => ({ label: h.label, when: h.when }));

	const o = v.offer;
	const offer: ResolvedOffer | null =
		o && (VIEW_ACTIONS as readonly string[]).includes(o.action) && resolvable(o.when ?? [])
			? { label: o.label, action: o.action as ViewAction, when: o.when }
			: null;

	const want = v.style ?? 'grid';
	// vector cells are never renderable inline (they are 768 floats); a style
	// that resolved onto one would print "⋯" as its whole body.
	const bodyOk = body !== null && body.kind !== 'vector';
	// `chat` renders ONE ROW AS AN EXCHANGE: the asking column becomes the left
	// bubble, the body the right one. It is the caddy-sessions shape (a turn is
	// a sentence in and an answer out), and it needs both halves — a chat with
	// only one side is a list with round corners, so it degrades like the rest.
	const asking = byKey(cols, v.askColumn);
	const degraded =
		(want === 'blog' && !bodyOk) ||
		(want === 'timeline' && !date) ||
		(want === 'chat' && (!bodyOk || !asking))
			? want
			: undefined;

	return {
		style: degraded ? 'grid' : want,
		title,
		body: bodyOk ? body : null,
		ask: want === 'chat' && !degraded ? asking : null,
		date,
		media,
		meta,
		facets,
		highlights,
		offer,
		...(degraded ? { degradedFrom: degraded } : {})
	};
}

// ── The trust boundary ───────────────────────────────────────────────────────
//
// ONE DOOR. `narrowView` is called at the single seam where a view block enters
// the shell (`routes/bff/tables/+server.ts`), so a block authored in KEAP and a
// block proposed by a model arrive through the same check. That is the only
// reason this is a boundary and not a decoration: a second, gentler entrance
// makes the first one advice.
//
// REFUSE, DO NOT REPAIR. A predicate naming an unknown column or an unknown op
// is dropped WHOLE and named in `dropped`; it is never coerced, never partially
// kept. Coercion is how untrusted input starts steering: a repaired predicate
// still filters rows, just not the ones anybody declared.
//
// WHAT A MODEL MAY INFLUENCE: which existing column a facet or predicate names,
// which of the seven ops, a scalar value, a label string, which action id from
// VIEW_ACTIONS, the order of highlights.
// WHAT IT MAY NEVER PRODUCE: a column that is not in `columns`, an op outside
// the enum, an action not in VIEW_ACTIONS, a URL, a command, markup, a style,
// or more than the caps above. Labels render through Svelte's `{expr}`; there
// is no sanitiser in this shell and there must not need to be.

const str = (v: unknown, max = MAX_LABEL): string | null =>
	typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null;

function narrowPredicate(raw: unknown, keys: Set<string>): RowPredicate | null {
	if (!raw || typeof raw !== 'object') return null;
	const p = raw as Record<string, unknown>;
	const column = typeof p.column === 'string' ? p.column : '';
	const op = typeof p.op === 'string' ? p.op : '';
	const value = p.value;
	if (!keys.has(column)) return null;
	if (!(ROW_OPS as readonly string[]).includes(op)) return null;
	// Scalars only. An object value is the shape that could carry markup, and a
	// null one makes `contains` mean something different from `eq`.
	if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') {
		return null;
	}
	return {
		column,
		op: op as RowOp,
		value: typeof value === 'string' ? value.slice(0, 256) : value
	};
}

/**
 * Narrow an untrusted `view` block to what these columns can actually render.
 *
 * Returns the surviving block plus what was thrown away. `dropped` is not
 * diagnostics — it reaches the header as a warn badge, for the same reason
 * `degradedFrom` does: a block that silently lost half of itself renders as a
 * working one.
 */
export function narrowView(
	raw: unknown,
	columns: ColumnSpec[]
): { view: TableView | undefined; dropped: string[] } {
	const dropped: string[] = [];
	if (!raw || typeof raw !== 'object') return { view: undefined, dropped };
	const v = raw as Record<string, unknown>;
	const keys = new Set(columns.map((c) => c.key));

	// The five original keys are passed through untouched: `resolveView` already
	// resolves an unknown column to null and degrades the style, and that
	// behaviour predates this function. Narrowing them here would change what a
	// KEAP-authored block does today for no gain.
	const out: TableView = {
		style: (['grid', 'blog', 'timeline', 'tiles', 'chat'] as const).includes(
			v.style as ResolvedStyle
		)
			? (v.style as ResolvedStyle)
			: 'grid',
		...(typeof v.titleColumn === 'string' ? { titleColumn: v.titleColumn } : {}),
		...(typeof v.bodyColumn === 'string' ? { bodyColumn: v.bodyColumn } : {}),
		...(typeof v.askColumn === 'string' ? { askColumn: v.askColumn } : {}),
		...(typeof v.dateColumn === 'string' ? { dateColumn: v.dateColumn } : {}),
		...(typeof v.mediaColumn === 'string' ? { mediaColumn: v.mediaColumn } : {}),
		...(Array.isArray(v.metaColumns)
			? { metaColumns: v.metaColumns.filter((c): c is string => typeof c === 'string').slice(0, 4) }
			: {})
	};
	if (v.style !== undefined && out.style !== v.style) dropped.push(`style:${String(v.style)}`);

	if (Array.isArray(v.facets)) {
		const facets: string[] = [];
		for (const f of v.facets) {
			if (typeof f !== 'string' || !keys.has(f)) dropped.push(`facet:${String(f)}`);
			else if (facets.length >= MAX_FACETS) dropped.push(`facet:${f} (over ${MAX_FACETS})`);
			else facets.push(f);
		}
		if (facets.length) out.facets = facets;
	}

	if (Array.isArray(v.highlights)) {
		const highlights: HighlightSpec[] = [];
		for (const h of v.highlights) {
			const spec = h as Record<string, unknown>;
			const label = str(spec?.label);
			const when = Array.isArray(spec?.when)
				? spec.when.slice(0, MAX_PREDICATES).map((p) => narrowPredicate(p, keys))
				: [];
			// One bad predicate voids the whole highlight. A partially applied AND
			// selects a DIFFERENT set of rows and labels it with the author's words.
			if (!label || !when.length || when.some((p) => p === null)) {
				dropped.push(`highlight:${label ?? '?'}`);
			} else if (highlights.length >= MAX_HIGHLIGHTS) {
				dropped.push(`highlight:${label} (over ${MAX_HIGHLIGHTS})`);
			} else {
				highlights.push({ label, when: when as RowPredicate[] });
			}
		}
		if (highlights.length) out.highlights = highlights;
	}

	if (v.offer && typeof v.offer === 'object') {
		const o = v.offer as Record<string, unknown>;
		const label = str(o.label, MAX_OFFER_LABEL);
		const action = typeof o.action === 'string' ? o.action : '';
		const when = Array.isArray(o.when)
			? o.when.slice(0, MAX_PREDICATES).map((p) => narrowPredicate(p, keys))
			: [];
		if (
			label &&
			(VIEW_ACTIONS as readonly string[]).includes(action) &&
			when.length &&
			!when.some((p) => p === null)
		) {
			out.offer = { label, action, when: when as RowPredicate[] };
		} else {
			dropped.push(`offer:${action || '?'}`);
		}
	}

	return { view: out, dropped };
}

// ── Predicates over rows ─────────────────────────────────────────────────────

/** One predicate against one row. Comparison is on the cell's own type where
 *  both sides are numbers, and on lowercased strings otherwise — a `select`
 *  column holds strings and an author writing `shipped` means `Shipped` too. */
export function matchPredicate(row: DataTableRow, p: RowPredicate): boolean {
	const cell = row[p.column];
	if (typeof cell === 'number' && typeof p.value === 'number') {
		switch (p.op) {
			case 'eq':
				return cell === p.value;
			case 'neq':
				return cell !== p.value;
			case 'lt':
				return cell < p.value;
			case 'lte':
				return cell <= p.value;
			case 'gt':
				return cell > p.value;
			case 'gte':
				return cell >= p.value;
			case 'contains':
				return String(cell).includes(String(p.value));
		}
	}
	// An absent cell is the empty string, so `{op: eq, value: ""}` is how a
	// declaration asks for "this row has no parent" — the roadmap's roots.
	const a = (cell === null || cell === undefined ? '' : String(cell)).toLowerCase();
	const b = String(p.value).toLowerCase();
	switch (p.op) {
		case 'eq':
			return a === b;
		case 'neq':
			return a !== b;
		case 'lt':
			return a < b;
		case 'lte':
			return a <= b;
		case 'gt':
			return a > b;
		case 'gte':
			return a >= b;
		case 'contains':
			return b !== '' && a.includes(b);
	}
}

/** Every predicate must hold (AND). An empty list matches nothing, never
 *  everything — `narrowView` refuses one, and a bug that produced one must not
 *  silently select the whole table. */
export const matchRow = (row: DataTableRow, when: RowPredicate[]): boolean =>
	when.length > 0 && when.every((p) => matchPredicate(row, p));

// ── The generative half ──────────────────────────────────────────────────────

/**
 * Prompt a local model to PROPOSE a view block for a table that has none.
 *
 * DESIGN-TIME, NOT REQUEST-TIME, and that is the whole judgement here. For the
 * roadmap the answer is already in the columns — `status` says what someone
 * CLAIMS and `verified` says what a PROBE OBSERVED, so "shipped AND
 * contradicted" is the most useful row class the table can hold, and it is four
 * lines of YAML rather than a model call on every open. A model that fills a
 * contract nobody has proven useful is a fill for an empty form.
 *
 * So the loop is: `ask(buildViewProposalPrompt(t))` → `narrowView(JSON.parse(…))`
 * → the operator reads the surviving block and pastes it into the table's
 * `.table.yml`, where it is reviewable, diffable and identical for every
 * renderer. Same parser, same caps, same door as an authored block — which is
 * why there is no second code path here, and no cache, and no BFF route.
 */
export function buildViewProposalPrompt(table: DataTable): string {
	const cols = (table.columns ?? [])
		.filter((c) => c.kind !== 'vector')
		.map((c) => `${c.key} (${c.kind}${c.options?.length ? `: ${c.options.join('|')}` : ''})`)
		.join('\n');
	return [
		`Table "${table.title}" has these columns:`,
		cols,
		'',
		`Propose a JSON view block. Reply with JSON ONLY, no prose, no code fence:`,
		`{"style":"grid|blog|timeline|tiles|chat","titleColumn":"…","dateColumn":"…",`,
		` "facets":["col","col"],`,
		` "highlights":[{"label":"…","when":[{"column":"…","op":"eq|neq|lt|lte|gt|gte|contains","value":"…"}]}],`,
		` "offer":{"label":"…","action":"${VIEW_ACTIONS[0]}","when":[…]}}`,
		'',
		`Rules: every "column" MUST be one of the keys listed above.`,
		`At most ${MAX_FACETS} facets (low-cardinality dimensions), ${MAX_HIGHLIGHTS} highlights.`,
		`A highlight names rows an operator would want to jump to — prefer a pair of`,
		`columns that can DISAGREE (a claim beside an observation) over a single status.`,
		`"action" must be exactly one of: ${VIEW_ACTIONS.join(', ')}.`
	].join('\n');
}

/** Rows in the order the style wants them. Only timeline reorders; every other
 *  style preserves the server's order, which is the table's own. */
export function orderRows<T extends Record<string, unknown> & { id?: string }>(
	rows: T[],
	view: ResolvedView
): T[] {
	if (view.style !== 'timeline' || !view.date) return rows;
	const k = view.date.key;
	const at = (r: T): number => {
		const raw = r[k];
		if (typeof raw === 'number') return raw;
		if (typeof raw === 'string') {
			const t = Date.parse(raw);
			return Number.isNaN(t) ? -Infinity : t / 1000;
		}
		return -Infinity;
	};
	// Newest first, and a row with no parseable date sinks rather than
	// disappearing — the corpus and the view must not disagree about how many
	// rows exist.
	return [...rows].sort((a, b) => at(b) - at(a));
}

/** Epoch seconds, ms, or a parseable string → ms. Null when it is none of those. */
function toMs(raw: unknown): number | null {
	if (typeof raw === 'number') return raw > 1e11 ? raw : raw * 1000;
	if (typeof raw === 'string') {
		const t = Date.parse(raw);
		if (!Number.isNaN(t)) return t;
	}
	return null;
}

/** Human date for the timeline gutter. Epoch seconds, ms, or a parseable string. */
export function formatWhen(raw: unknown): string {
	const ms = toMs(raw);
	if (ms === null) return '—';
	return new Date(ms).toLocaleDateString(undefined, {
		year: 'numeric',
		month: 'short',
		day: 'numeric'
	});
}

export interface TimelineSection<T> {
	/** Month heading ("Sep 2026"), or the honest bucket for rows the date
	 *  column is empty on ("no Target" — the column's own label, so a roadmap
	 *  says "no Target" and a log says "no Started"). */
	label: string;
	rows: T[];
}

/**
 * The already-ordered timeline rows, bucketed by month.
 *
 * WHY: 122 roadmap rows as one flat dot-list read as a chat feed — every entry
 * the same weight, the time axis invisible, and the undated rows (`orderRows`
 * sinks them) rendering a wall of "—". A timeline earns its name only when time
 * is a visible axis, so the gutter dates become month headings and the undated
 * tail becomes one named bucket instead of dozens of identical dashes.
 *
 * Pure projection over `orderRows`' output — it reorders nothing, drops
 * nothing (the corpus and the view must not disagree about how many rows
 * exist), and for any non-timeline view it returns one unlabeled section so
 * the caller needs no second code path.
 */
export function timelineSections<T extends Record<string, unknown>>(
	rows: T[],
	view: ResolvedView
): TimelineSection<T>[] {
	if (view.style !== 'timeline' || !view.date) return [{ label: '', rows }];
	const key = view.date.key;
	const sections: TimelineSection<T>[] = [];
	for (const row of rows) {
		const ms = toMs(row[key]);
		const label =
			ms === null
				? `no ${view.date.label}`
				: new Date(ms).toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
		const last = sections[sections.length - 1];
		if (last && last.label === label) last.rows.push(row);
		else sections.push({ label, rows: [row] });
	}
	return sections.length ? sections : [{ label: '', rows }];
}
