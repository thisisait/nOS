/** BFF · config DataTables (KEAP SoT + fallback + gated WRITE).
 *
 * KEAP's agent surface (`/agent/v1/tables`, loopback bearer) is the source of
 * truth. Reads are open to any authenticated user (RO token); when KEAP is
 * unconfigured/down we serve vendored repo-default (SoC) rows so the desktop
 * stays usable. WRITES (upsert row / create table) are RBAC-gated to manager+
 * tiers here — the browser never gets the RW token and can't set its own tier.
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
import { canWriteTables } from '$lib/security/tier';
import { toTableSummaries, type TableSummary } from '$lib/tables/summary';
import type { DataTable, DataTableRow, ColumnSpec } from '$lib/contracts';
import { FACE_LAYOUTS, FACE_WALLPAPERS, FACE_CONTROLS } from '$lib/server/defaults';

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
	]
};

const toRows = (specs: { slug: string }[]): DataTableRow[] =>
	specs.map((spec) => ({ id: spec.slug, ...spec }));

/** Guarantee every row carries a stable, UNIQUE `id`. KEAP's agent surface
 *  returns flat rows keyed by a business column (slug/name) with NO `id` field,
 *  so a naive `{#each rows (row.id)}` sees N `undefined` keys and Svelte throws
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
	'face-controls': toRows(FACE_CONTROLS)
};

/** KEAP agent responses may be enveloped `{success,data}` or bare — unwrap. */
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
				unit: typeof col.unit === 'string' ? col.unit : undefined
			} as ColumnSpec;
		})
		.filter((c): c is ColumnSpec => c !== null);
}

// TODO remove when KEAP GET /agent/v1/tables accepts the agent bearer: the
// list-all endpoint currently requires forward-auth identity (401 on the bearer)
// even though GET /agent/v1/tables/:slug accepts it. Until then, probe the known
// config-table slugs via the working per-slug route so the Tables sidebar fills.
const KNOWN_CONFIG_TABLES = ['face-layouts', 'face-wallpapers', 'face-controls'];

async function knownTableSummaries(): Promise<TableSummary[]> {
	const out: TableSummary[] = [];
	for (const slug of KNOWN_CONFIG_TABLES) {
		try {
			const def = unwrap<{ id?: string; slug?: string; title?: string; rowCount?: number }>(
				await keapTableDef(slug)
			);
			out.push({
				slug: (typeof def.id === 'string' && def.id) || slug,
				title: typeof def.title === 'string' && def.title ? def.title : slug,
				rowCount: typeof def.rowCount === 'number' ? def.rowCount : 0
			});
		} catch {
			/* table absent — skip it */
		}
	}
	return out;
}

export const GET: RequestHandler = async ({ url, locals }) => {
	// op=list → the Tables app's sidebar (all tables in KEAP).
	if (url.searchParams.get('op') === 'list') {
		if (!keapConfigured()) return json({ tables: [], source: 'fallback' });
		try {
			return json({ tables: toTableSummaries(await keapListTables()), source: 'keap' });
		} catch (e) {
			if (e instanceof UpstreamError) {
				// KEAP list-all needs forward-auth (a KEAP gap) — probe known slugs.
				return json({ tables: await knownTableSummaries(), source: 'known-slugs' });
			}
			throw e;
		}
	}

	const slug = url.searchParams.get('slug') ?? '';
	// Reads are open to any authenticated user for any well-formed slug — KEAP's
	// RO token is the real authority on what's readable. Repo-fallback rows exist
	// only for the vendored config tables.
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

	if (keapConfigured()) {
		try {
			const rowsData = unwrap<{ rows?: DataTableRow[] }>(
				await keapTableRows(slug, locals.identity.uid)
			);
			const liveRows =
				rowsData.rows ?? (Array.isArray(rowsData) ? (rowsData as DataTableRow[]) : []);
			table.rows = withStableIds(liveRows);
			table.source = 'keap';
			// Best-effort column enrichment from the table def (non-fatal on failure).
			try {
				const def = unwrap<{ view?: DataTable['view'] }>(await keapTableDef(slug));
				const cols = mapColumns(def);
				if (cols.length > 0) table.columns = cols;
				// The render style rides the same def fetch — one call, and a
				// table that declares no style simply has no key.
				if (def && typeof def === 'object' && def.view) table.view = def.view;
			} catch {
				/* keep fallback columns */
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
		throw error(503, 'DataTables are read-only here (no KEAP write token configured).');
	}
	const body = (await request.json().catch(() => ({}))) as Post;
	const slug = (body.slug ?? '').trim();
	if (!SLUG_RE.test(slug)) throw error(400, 'invalid table slug');

	// TODO audit: emit a Bone audit event (actor = identity.uid, action = table write)
	// once the shell has a Bone audit hook. KEAP already records the write server-side.
	try {
		if (body.op === 'upsertRow') {
			if (!body.row || typeof body.row !== 'object') throw error(400, 'row object required');
			return json(unwrap(await keapUpsertRow(slug, body.row)));
		}
		if (body.op === 'createTable') {
			const { op: _op, ...tableBody } = body;
			void _op;
			return json(unwrap(await keapCreateTable(tableBody)));
		}
		throw error(400, 'unsupported op');
	} catch (e) {
		if (e instanceof UpstreamError) throw error(e.status, e.message);
		throw e;
	}
};
