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
import type { ColumnSpec, DataTable, TableView } from '$lib/contracts';

export type ResolvedStyle = 'grid' | 'blog' | 'timeline' | 'tiles';

export interface ResolvedView {
	style: ResolvedStyle;
	title: ColumnSpec | null;
	body: ColumnSpec | null;
	date: ColumnSpec | null;
	media: ColumnSpec | null;
	meta: ColumnSpec[];
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
		...(degraded ? { degradedFrom: degraded } : {}),
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
