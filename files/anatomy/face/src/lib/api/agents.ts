/** The face Agents app's client (row wing-inc2-agents-timeline). */
import { bffGet, bffPost } from './client';
import type { RosterAgent } from '$lib/agents/roster';
import type { SessionView } from '$lib/agents/sessions';

export async function loadRoster(): Promise<RosterAgent[]> {
	return (await bffGet<{ agents: RosterAgent[] }>('/bff/agents')).agents;
}

export async function loadSessions(agent: string): Promise<SessionView[]> {
	return (
		await bffGet<{ sessions: SessionView[] }>(`/bff/agents/${encodeURIComponent(agent)}/sessions`)
	).sessions;
}

export function cancelSession(uuid: string): Promise<{ uuid: string; status: string }> {
	return bffPost(`/bff/agent-sessions/${encodeURIComponent(uuid)}/cancel`, {});
}

export type AuditVerdict = {
	chain: 'on' | 'off' | null;
	known: boolean | null;
	ok: boolean | null;
	checked: number | null;
	verifiedAt: string | null;
	note: string | null;
};

export function loadAudit(): Promise<AuditVerdict> {
	return bffGet<AuditVerdict>('/bff/audit');
}
