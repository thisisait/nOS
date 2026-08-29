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
	OfferSpec,
	RowOp,
	RowPredicate,
	TableView
} from '$lib/contracts';

export type ResolvedStyle = 'grid' | 'blog' | 'timeline' | 'tiles';

/**
 * Every action this renderer can offer. A CLOSED CATALOG, in code.
 *
 * `TableView.offer.action` selects from this list; it never carries a command,
 * a URL or a handler. That split is not local caution — it is the rule
 * `state/genome/entity.schema.json` states for the whole estate ("a capability
 * must not be addable by data, so opcodes and handlers stay code, per
 * runtime"), and the reason a model may fill this block at all.
 *
 * ONE MEMBER, deliberately, and the fail-closed ordering is the genome's too:
 * the handler ships first and the id joins this list second. A member with no
 * arm in the renderer is a declaration that validates and does nothing.
 */
export const VIEW_ACTIONS = ['focus-highlight'] as const;
export type ViewAction = (typeof VIEW_ACTIONS)[number];

const ROW_OPS: readonly RowOp[] = ['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'contains'] as const;

/** Caps. A declaration that can grow without bound is a layout that can. */
const MAX_FACETS = 2;
const MAX_HIGHLIGHTS = 4;
const MAX_PREDICATES = 4;
const MAX_LABEL = 48;

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
	const degraded =
		(want === 'blog' && !bodyOk) || (want === 'timeline' && !date) ? want : undefined;

	return {
		style: degraded ? 'grid' : want,
		title,
		body: bodyOk ? body : null,
		date,
		media,
		meta,
		...(degraded ? { degradedFrom: degraded } : {})
	};
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

/** Human date for the timeline gutter. Epoch seconds, ms, or a parseable string. */
export function formatWhen(raw: unknown): string {
	let ms: number | null = null;
	if (typeof raw === 'number') ms = raw > 1e11 ? raw : raw * 1000;
	else if (typeof raw === 'string') {
		const t = Date.parse(raw);
		if (!Number.isNaN(t)) ms = t;
	}
	if (ms === null) return '—';
	return new Date(ms).toLocaleDateString(undefined, {
		year: 'numeric',
		month: 'short',
		day: 'numeric'
	});
}
