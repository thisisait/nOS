/** BFF · config DataTables (KEAP SoT + fallback + gated READ/WRITE).
 *
 * KEAP's human door (`/api/tables`, as the signed-in person — see
 * $lib/server/upstream) is the source of truth; KEAP enforces that person's
 * table/row access and owns writes as user:<uid>. Reads also honour the
 * table's visibility grade against edge-trusted `identity.groups` (fail closed). Face config tables (face-layouts etc.) stay
 * readable to any authenticated caller — they are not client books. When KEAP
 * is unconfigured/down we serve vendored repo-default (SoC) rows for those
 * config tables so the desktop stays usable. WRITES (upsert row / create table)
 * are RBAC-gated to manager+ tiers here — the browser never sees the proxy
 * secret and can't set its own identity or tier.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	keapTableRows,
	keapTableDef,
	keapListTables,
	keapUpsertRow,
	keapCreateTable,
	keapConfigured,
	keapWriteConfigured,
	UpstreamError
} from '$lib/server/upstream';
import { canReadTable, canWriteTables, canViewAnatomy } from '$lib/security/tier';
import { BOOK_SCOPED, filterBookRows, mayWriteBookRow, type Row } from '$lib/security/bookScope';
import { toTableSummaries, type TableSummary } from '$lib/tables/summary';
import { narrowView, decorateRowRefs } from '$lib/tables/view';
import { postTableAudit } from '$lib/server/audit';
import type { DataTable, DataTableRow, ColumnSpec, Identity } from '$lib/contracts';
import { FACE_LAYOUTS, FACE_WALLPAPERS, FACE_CONTROLS, FACE_DOCK } from '$lib/server/defaults';

// Config tables with vendored repo-default rows (the SoC fallback when KEAP is
// unreachable) live in `repoDefaults`/`FALLBACK_COLUMNS` below; any other valid
// slug is served live-from-KEAP-only (empty on failure).
const SLUG_RE = /^[a-z0-9][a-z0-9._-]{0,127}$/;

/** Repo-default column specs per config table — the editor's fallback shape when
 *  KEAP's table def is unreachable (also the shape the seeder authored). */
const FALLBACK_COLUMNS: Record<string, ColumnSpec[]> = {
	'face-layouts': [
		{ key: 'slug', label: 'Key', kind: 'text', required: true },
		{ key: 'name', label: 'Name', kind: 'text', required: true },
		{ key: 'icon', label: 'Icon', kind: 'text' },
		{ key: 'cells', label: 'Cells (JSON)', kind: 'json' }
	],
	'face-wallpapers': [
		{ key: 'slug', label: 'Key', kind: 'text', required: true },
		{ key: 'name', label: 'Name', kind: 'text', required: true },
		{ key: 'kind', label: 'Kind', kind: 'select', options: ['gradient', 'image'] },
		{ key: 'css', label: 'CSS gradient', kind: 'text' }
	],
	'face-controls': [
		{ key: 'slug', label: 'Key', kind: 'text', required: true },
		{ key: 'name', label: 'Name', kind: 'text', required: true },
		{ key: 'icon', label: 'Icon', kind: 'text' },
		{
			key: 'surface',
			label: 'Surface',
			kind: 'select',
			options: ['wallpaper', 'layouts', 'identity', 'storage', 'rawDataTable']
		},
		{ key: 'table', label: 'Table (for rawDataTable)', kind: 'text' }
	],
	'face-dock': [
		{ key: 'slug', label: 'App key', kind: 'text', required: true },
		{ key: 'order', label: 'Bar position', kind: 'number', required: true }
	]
};

const toRows = (specs: { slug: string }[]): DataTableRow[] =>
	specs.map((spec) => ({ id: spec.slug, ...spec }));

/** Guarantee every row carries a stable, UNIQUE `id`. Rows arrive flat, keyed
 *  by a business column (slug/name), with `__id` but NO `id` field, so a naive `{#each rows (row.id)}` sees N `undefined` keys and Svelte throws
 *  `each_key_duplicate`, unmounting the table. Derive id from the natural key,
 *  falling back to the row index and de-duping on collision. */
function withStableIds(rows: DataTableRow[]): DataTableRow[] {
	const seen = new Set<string>();
	return rows.map((r, i) => {
		const natural = r.id ?? r.slug ?? r.name;
		let id = natural != null && String(natural).trim() ? String(natural) : `row-${i}`;
		if (seen.has(id)) id = `${id}-${i}`;
		seen.add(id);
		return { ...r, id };
	});
}

const repoDefaults: Record<string, DataTableRow[]> = {
	'face-layouts': toRows(FACE_LAYOUTS),
	'face-wallpapers': toRows(FACE_WALLPAPERS),
	'face-controls': toRows(FACE_CONTROLS),
	'face-dock': toRows(FACE_DOCK)
};

/** KEAP responses may be enveloped `{success,data}` or bare — unwrap. */
function unwrap<T = Record<string, unknown>>(raw: unknown): T {
	const r = raw as { data?: T } | T;
	return (r && typeof r === 'object' && 'data' in (r as object) ? (r as { data: T }).data : r) as T;
}

/** Map a KEAP table-def's columns → the shell's ColumnSpec (best-effort). */
function mapColumns(def: unknown): ColumnSpec[] {
	const d = def as { schema?: { columns?: unknown[] }; columns?: unknown[] };
	const cols = d.schema?.columns ?? d.columns;
	if (!Array.isArray(cols)) return [];
	return cols
		.map((c) => {
			const col = c as Record<string, unknown>;
			const key = typeof col.key === 'string' ? col.key : '';
			if (!key) return null;
			return {
				key,
				label: typeof col.label === 'string' ? col.label : key,
				kind: (typeof col.kind === 'string' ? col.kind : 'text') as ColumnSpec['kind'],
				options: Array.isArray(col.options) ? (col.options as string[]) : undefined,
				required: col.required === true,
				role: typeof col.role === 'string' ? col.role : undefined,
				dim: typeof col.dim === 'number' ? col.dim : undefined,
				unit: typeof col.unit === 'string' ? col.unit : undefined,
				refTable: typeof col.refTable === 'string' ? col.refTable : undefined,
				refDisplay: typeof col.refDisplay === 'string' ? col.refDisplay : undefined
			} as ColumnSpec;
		})
		.filter((c): c is ColumnSpec => c !== null);
}

// Fallback when the list-all call fails: probe the known config-table slugs via
// the per-table route so the Tables sidebar still fills.
const KNOWN_CONFIG_TABLES = ['face-layouts', 'face-wallpapers', 'face-controls', 'face-dock'];

function isFaceConfigTable(slug: string): boolean {
	return (KNOWN_CONFIG_TABLES as readonly string[]).includes(slug);
}

/** Config catalog: any authenticated caller. Everything else: visibility grade. */
function mayReadTable(
	slug: string,
	visibility: string | undefined,
	groups: readonly string[] | undefined,
	who?: { uid?: string; ownerId?: string }
): boolean {
	return isFaceConfigTable(slug) || canReadTable(visibility, groups, who);
}

async function fetchLiveRows(slug: string, who: Identity): Promise<DataTableRow[]> {
	const rowsData = unwrap<{ rows?: DataTableRow[] }>(await keapTableRows(slug, who));
	const live = rowsData.rows ?? (Array.isArray(rowsData) ? (rowsData as DataTableRow[]) : []);
	return withStableIds(live);
}

async function scopeContext(who: Identity, slug: string) {
	const { uid, groups } = who;
	const access = await fetchLiveRows('book-access', who).catch(() => [] as DataTableRow[]);
	const needInv =
		slug === 'invoice-line' ||
		slug === 'journal-entry' ||
		slug === 'posting' ||
		slug === 'party' ||
		slug === 'pending-invoice-verify';
	const invoices = needInv
		? await fetchLiveRows('invoice', who).catch(() => [] as DataTableRow[])
		: [];
	const journals =
		slug === 'posting'
			? await fetchLiveRows('journal-entry', who).catch(() => [] as DataTableRow[])
			: [];
	return { access, invoices, journals, groups, uid };
}

function readableSummaries(
	tables: TableSummary[],
	groups: readonly string[] | undefined,
	uid: string
): TableSummary[] {
	return tables.filter((t) =>
		mayReadTable(t.slug, t.visibility, groups, { uid, ownerId: t.ownerId })
	);
}

async function knownTableSummaries(who: Identity): Promise<TableSummary[]> {
	const out: TableSummary[] = [];
	for (const slug of KNOWN_CONFIG_TABLES) {
		try {
			const def = unwrap<{
				id?: string;
				slug?: string;
				title?: string;
				rowCount?: number;
				visibility?: string;
				ownerId?: string;
			}>(await keapTableDef(slug, who));
			out.push({
				slug: (typeof def.id === 'string' && def.id) || slug,
				title: typeof def.title === 'string' && def.title ? def.title : slug,
				rowCount: typeof def.rowCount === 'number' ? def.rowCount : 0,
				...(typeof def.visibility === 'string' ? { visibility: def.visibility } : {}),
				...(typeof def.ownerId === 'string' ? { ownerId: def.ownerId } : {})
			});
		} catch {
			/* table absent — skip it */
		}
	}
	return out;
}

export const GET: RequestHandler = async ({ url, locals }) => {
	const groups = locals.identity.groups;

	// op=list → the Tables app's sidebar (tables this caller may read).
	if (url.searchParams.get('op') === 'list') {
		if (!keapConfigured()) return json({ tables: [], source: 'fallback' });
		try {
			return json({
				tables: readableSummaries(
					toTableSummaries(await keapListTables(locals.identity)),
					groups,
					locals.identity.uid
				),
				source: 'keap'
			});
		} catch (e) {
			if (e instanceof UpstreamError) {
				return json({
					tables: readableSummaries(
						await knownTableSummaries(locals.identity),
						groups,
						locals.identity.uid
					),
					source: 'known-slugs'
				});
			}
			throw e;
		}
	}

	const slug = url.searchParams.get('slug') ?? '';
	if (!SLUG_RE.test(slug)) return json({ error: 'unknown table' }, { status: 404 });

	const canWrite = canWriteTables(locals.identity.groups) && keapWriteConfigured();
	const table: DataTable = {
		slug,
		title: slug,
		columns: FALLBACK_COLUMNS[slug] ?? [],
		rows: [],
		source: 'fallback',
		canWrite
	};

	const forbid = () => {
		throw error(403, "DataTable reads require the table's visibility tier.");
	};

	let def: { view?: DataTable['view']; visibility?: string; ownerId?: string } | undefined;
	if (keapConfigured()) {
		try {
			def = unwrap<{ view?: DataTable['view']; visibility?: string; ownerId?: string }>(
				await keapTableDef(slug, locals.identity)
			);
		} catch (e) {
			if (!(e instanceof UpstreamError)) throw e;
		}
	}
	const vis = typeof def?.visibility === 'string' ? def.visibility : undefined;
	const uid = locals.identity.uid;
	if (!mayReadTable(slug, vis, groups, { uid, ownerId: def?.ownerId })) forbid();

	if (def) {
		const cols = mapColumns(def);
		if (cols.length > 0) table.columns = cols;
		if (def.view) {
			const { view, dropped } = narrowView(def.view, table.columns);
			if (view) table.view = view;
			if (dropped.length) table.viewDropped = dropped;
		}
	}

	if (keapConfigured()) {
		try {
			const rowsData = unwrap<{ rows?: DataTableRow[] }>(
				await keapTableRows(slug, locals.identity)
			);
			const liveRows =
				rowsData.rows ?? (Array.isArray(rowsData) ? (rowsData as DataTableRow[]) : []);
			table.rows = withStableIds(liveRows);
			table.source = 'keap';
			if (BOOK_SCOPED.has(slug) && !canViewAnatomy(groups)) {
				const ctx = await scopeContext(locals.identity, slug);
				const invoices = slug === 'invoice' ? table.rows : ctx.invoices;
				const journals = slug === 'journal-entry' ? table.rows : ctx.journals;
				table.rows = filterBookRows({
					slug,
					rows: table.rows,
					uid: locals.identity.uid,
					groups,
					access: ctx.access,
					invoices,
					journals
				}) as DataTableRow[];
			}
			// rowRef: skip a refTable the caller cannot read (do not load party for a guest).
			const refTables = [
				...new Set(
					table.columns
						.filter((c) => c.kind === 'rowRef' && c.refTable && c.refDisplay)
						.map((c) => c.refTable as string)
				)
			];
			if (refTables.length) {
				const refRows: Record<string, DataTableRow[]> = {};
				await Promise.all(
					refTables.map(async (t) => {
						try {
							const rdef = unwrap<{ visibility?: string; ownerId?: string }>(
								await keapTableDef(t, locals.identity)
							);
							const rvis = typeof rdef.visibility === 'string' ? rdef.visibility : undefined;
							if (!mayReadTable(t, rvis, groups, { uid, ownerId: rdef.ownerId })) return;
							const rd = unwrap<{ rows?: DataTableRow[] }>(await keapTableRows(t, locals.identity));
							refRows[t] = rd.rows ?? (Array.isArray(rd) ? (rd as DataTableRow[]) : []);
						} catch {
							/* leave raw ids showing for this table */
						}
					})
				);
				const byColumn: Record<string, DataTableRow[]> = {};
				for (const c of table.columns) {
					if (c.kind === 'rowRef' && c.refTable && refRows[c.refTable]) {
						byColumn[c.key] = refRows[c.refTable];
					}
				}
				if (Object.keys(byColumn).length) {
					table.rows = decorateRowRefs(table.rows, table.columns, byColumn);
				}
			}
			return json(table);
		} catch (e) {
			if (!(e instanceof UpstreamError)) throw e;
		}
	}
	table.rows = repoDefaults[slug] ?? [];
	return json(table);
};

type Post =
	| { op: 'upsertRow'; slug: string; row: Record<string, unknown> }
	| { op: 'createTable'; slug: string; title?: string; columns?: unknown[]; [k: string]: unknown };

export const POST: RequestHandler = async ({ request, locals }) => {
	// RBAC gate — manager+ tiers only (from the edge-trusted identity, never the body).
	if (!canWriteTables(locals.identity.groups)) {
		throw error(403, 'DataTable writes require the manager tier or higher.');
	}
	if (!keapWriteConfigured()) {
		throw error(503, 'DataTables are read-only here (no KEAP proxy secret configured).');
	}
	const body = (await request.json().catch(() => ({}))) as Post;
	const slug = (body.slug ?? '').trim();
	if (!SLUG_RE.test(slug)) throw error(400, 'invalid table slug');

	try {
		if (body.op === 'upsertRow') {
			if (!body.row || typeof body.row !== 'object') throw error(400, 'row object required');
			if (BOOK_SCOPED.has(slug)) {
				const ctx = await scopeContext(locals.identity, slug);
				const invoices = slug === 'invoice' ? ([body.row] as DataTableRow[]) : ctx.invoices;
				if (
					!mayWriteBookRow({
						slug,
						row: body.row as Row,
						uid: locals.identity.uid,
						groups: locals.identity.groups,
						access: ctx.access,
						invoices
					})
				) {
					throw error(403, 'this book is not assigned to you');
				}
			}
			const result = json(unwrap(await keapUpsertRow(slug, body.row, locals.identity)));
			// Audit-only: fire-and-forget, never blocks or fails the write it's
			// auditing (postTableAudit swallows its own errors). row_id is the
			// natural key every table upserts by — KEAP's own response envelope
			// shape varies more than the request body does.
			const rowId = String(
				(body.row as Record<string, unknown>).slug ?? (body.row as Record<string, unknown>).id ?? ''
			);
			void postTableAudit(locals.identity.uid, slug, rowId);
			return result;
		}
		if (body.op === 'createTable') {
			const { op: _op, ...tableBody } = body;
			void _op;
			return json(unwrap(await keapCreateTable(tableBody, locals.identity)));
		}
		throw error(400, 'unsupported op');
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};
