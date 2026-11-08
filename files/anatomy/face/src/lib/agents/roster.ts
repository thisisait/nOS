/**
 * The agent roster as the face Agents app shows it (row wing-inc2-agents-timeline): a projection
 * of Wing's GET /agents. Models, capability scopes and PII classes stay in Wing; an agent that
 * did not load keeps its error, so a broken definition is visible rather than missing. Pure.
 */
export interface RosterAgent {
	name: string;
	version: number | null;
	description: string;
	gated: boolean;
	error: string | null;
}

export function projectRoster(payload: unknown): RosterAgent[] {
	const data = (payload as { data?: unknown } | null)?.data;
	if (!Array.isArray(data)) return [];
	return data
		.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object')
		.map((r) => ({
			name: typeof r.name === 'string' ? r.name : '',
			version: typeof r.version === 'number' ? r.version : null,
			description: typeof r.description === 'string' ? r.description : '',
			gated: r.has_outcome === true,
			error: typeof r.error === 'string' ? r.error : null
		}))
		.filter((a) => a.name);
}
