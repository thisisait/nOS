/** BFF · config DataTables (KEAP SoT + fallback). KEAP `/api/tables` is the
 *  source of truth (uid-pinned, edge-trusted); when it is unconfigured or down
 *  we serve the vendored repo-default (SoC) rows so the desktop stays usable. */
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { keapTableRows, keapConfigured, UpstreamError } from '$lib/server/upstream';
import type { DataTable, DataTableRow } from '$lib/contracts';
import { FACE_LAYOUTS, FACE_WALLPAPERS, FACE_CONTROLS } from '$lib/server/defaults';

const ALLOWED = new Set(['face.layouts', 'face.wallpapers', 'face.controls']);

/** Map a built-in spec to a DataTableRow: id = its stable slug, plus the spec's
 *  own fields as the flat cell bag. */
const toRows = (specs: { slug: string }[]): DataTableRow[] =>
	specs.map((spec) => ({ id: spec.slug, ...spec }));

/** Repo-default (SoC) rows, used when KEAP is unconfigured/unreachable — the
 *  system rows the KEAP seeder also upserts (roles/pazny.keap/tasks/
 *  seed-face-tables.yml), so the fallback and the live table agree. */
const repoDefaults: Record<string, DataTableRow[]> = {
	'face.layouts': toRows(FACE_LAYOUTS),
	'face.wallpapers': toRows(FACE_WALLPAPERS),
	'face.controls': toRows(FACE_CONTROLS)
};

export const GET: RequestHandler = async ({ url, locals }) => {
	const slug = url.searchParams.get('slug') ?? '';
	if (!ALLOWED.has(slug)) return json({ error: 'unknown table' }, { status: 404 });

	const table: DataTable = { slug, title: slug, columns: [], rows: [], source: 'fallback' };

	if (keapConfigured()) {
		try {
			const data = (await keapTableRows(slug, locals.identity.uid)) as {
				rows?: DataTableRow[];
			};
			table.rows = data.rows ?? [];
			table.source = 'keap';
			return json(table);
		} catch (e) {
			// KEAP down → fall through to repo defaults (desktop stays usable).
			if (!(e instanceof UpstreamError)) throw e;
		}
	}
	table.rows = repoDefaults[slug] ?? [];
	return json(table);
};
