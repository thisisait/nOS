/** BFF · config DataTables (KEAP SoT + fallback). Wave 0 ships the fallback
 *  path (empty repo-default set); G2 wires the KEAP read + the seeded rows and
 *  fills `repoDefaults` from the vendored SoC layer. */
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { keapTableRows, keapConfigured, UpstreamError } from '$lib/server/upstream';
import type { DataTable, DataTableRow } from '$lib/contracts';

const ALLOWED = new Set(['face.layouts', 'face.wallpapers', 'face.controls']);

/** Repo-default (SoC) rows, used when KEAP is unconfigured/unreachable. G2
 *  replaces these stubs with the real seeded defaults imported from the vendored
 *  defaults module. */
const repoDefaults: Record<string, DataTableRow[]> = {
	'face.layouts': [],
	'face.wallpapers': [],
	'face.controls': []
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
