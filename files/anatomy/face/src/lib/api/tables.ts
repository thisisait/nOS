/** Config-DataTable client (KEAP SoT + fallback) — read + gated write.
 *  Reads are open; writes hit the BFF which enforces manager-tier RBAC + holds
 *  the RW token (a non-manager caller gets a 403 with a clear message). */
import { bffGet, bffPost } from './client';
import type { DataTable } from '$lib/contracts';

/** Fetch a config table (face-layouts / face-wallpapers / face-controls). The
 *  BFF returns `source: 'keap'` when live, `source: 'fallback'` (repo defaults +
 *  user-state) when KEAP is unreachable, and `canWrite` for the current caller. */
export async function loadTable(slug: string): Promise<DataTable> {
	return bffGet<DataTable>('/bff/tables', { slug });
}

/** Upsert a row into a table (create-or-merge on its stable key). Throws
 *  ApiError(403) when the caller lacks the manager tier, (503) when read-only. */
export async function tablesUpsertRow(
	slug: string,
	row: Record<string, unknown>
): Promise<unknown> {
	return bffPost('/bff/tables', { op: 'upsertRow', slug, row });
}

/** Create-or-return a table by slug. */
export async function tablesCreateTable(body: {
	slug: string;
	title?: string;
	columns?: unknown[];
	[k: string]: unknown;
}): Promise<unknown> {
	return bffPost('/bff/tables', { op: 'createTable', ...body });
}
