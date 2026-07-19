/** Pure mapping of KEAP's `TableInfo[]` (from GET /agent/v1/tables) → the
 *  compact summaries the Tables-app sidebar renders. Defensive about the shape:
 *  KEAP may envelope as `{success,data:[…]}` or return a bare array, and a row
 *  may carry `id` or `slug` as its key. No server imports → unit-testable. */

export interface TableSummary {
	slug: string;
	title: string;
	rowCount: number;
}

/** Unwrap a possibly-enveloped `{data}` payload. */
function unwrap(raw: unknown): unknown {
	return raw && typeof raw === 'object' && 'data' in (raw as object)
		? (raw as { data: unknown }).data
		: raw;
}

export function toTableSummaries(raw: unknown): TableSummary[] {
	const arr = unwrap(raw);
	if (!Array.isArray(arr)) return [];
	return arr
		.map((t) => {
			const o = t as Record<string, unknown>;
			const slug =
				(typeof o.id === 'string' && o.id) ||
				(typeof o.slug === 'string' && o.slug) ||
				(typeof o.name === 'string' && o.name) ||
				'';
			if (!slug) return null;
			return {
				slug,
				title: typeof o.title === 'string' && o.title ? o.title : slug,
				rowCount: typeof o.rowCount === 'number' ? o.rowCount : 0
			} satisfies TableSummary;
		})
		.filter((t): t is TableSummary => t !== null)
		.sort((a, b) => a.slug.localeCompare(b.slug));
}
