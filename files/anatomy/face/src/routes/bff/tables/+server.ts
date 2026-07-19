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
	keapUpsertRow,
	keapCreateTable,
	keapConfigured,
	keapWriteConfigured,
	UpstreamError
} from '$lib/server/upstream';
import { canWriteTables } from '$lib/security/tier';
import type { DataTable, DataTableRow, ColumnSpec } from '$lib/contracts';
import { FACE_LAYOUTS, FACE_WALLPAPERS, FACE_CONTROLS } from '$lib/server/defaults';

const ALLOWED = new Set(['face-layouts', 'face-wallpapers', 'face-controls']);
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

export const GET: RequestHandler = async ({ url, locals }) => {
	const slug = url.searchParams.get('slug') ?? '';
	if (!ALLOWED.has(slug)) return json({ error: 'unknown table' }, { status: 404 });

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
			table.rows = rowsData.rows ?? (Array.isArray(rowsData) ? (rowsData as DataTableRow[]) : []);
			table.source = 'keap';
			// Best-effort column enrichment from the table def (non-fatal on failure).
			try {
				const cols = mapColumns(unwrap(await keapTableDef(slug)));
				if (cols.length > 0) table.columns = cols;
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
