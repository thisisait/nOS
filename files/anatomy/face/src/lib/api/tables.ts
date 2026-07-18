/** Config-DataTable client (KEAP SoT + fallback). Wave 0 ships the read path +
 *  the fallback contract; G2 wires the KEAP seeder + user-row writes. */
import { bffGet } from './client';
import type { DataTable } from '$lib/contracts';

/** Fetch a config table (face.layouts / face.wallpapers / face.controls). The
 *  BFF returns `source: 'keap'` when live, `source: 'fallback'` (repo defaults +
 *  user-state) when KEAP is unreachable — the UI can surface a soft banner. */
export async function loadTable(slug: string): Promise<DataTable> {
	return bffGet<DataTable>('/bff/tables', { slug });
}
