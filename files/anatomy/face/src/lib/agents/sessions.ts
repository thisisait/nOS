/**
 * Agent sessions as an end user may see them — a PROJECTION, never a proxy.
 *
 * Wing's session row also carries trace_id, model_uri, token counts, and the
 * raw result/error JSON. None of that reaches a browser unless a field is added
 * here on purpose. Pure, so vitest runs it in node.
 */

/** One session as the browser is allowed to see it. */
export interface SessionView {
	uuid: string;
	agent: string;
	status: string;
	startedAt: string | null;
	endedAt: string | null;
	stopReason: string | null;
	outcome: string | null;
}

const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);

export function projectSession(raw: unknown): SessionView | null {
	if (!raw || typeof raw !== 'object') return null;
	const r = raw as Record<string, unknown>;
	const uuid = str(r.uuid);
	if (!uuid) return null;
	return {
		uuid,
		agent: str(r.agent_name) ?? '',
		status: str(r.status) ?? 'unknown',
		startedAt: str(r.started_at),
		endedAt: str(r.ended_at),
		stopReason: str(r.stop_reason),
		outcome: str(r.outcome_result)
	};
}

/** Wing's GET list is `{data: [...]}`; the single GET is `{session, ...}`. */
export function projectSessionList(payload: unknown): SessionView[] {
	const data = (payload as { data?: unknown } | null)?.data;
	return Array.isArray(data)
		? data.map(projectSession).filter((s): s is SessionView => s !== null)
		: [];
}

/** Wing's 202 on open: the uuid and the status, nothing else (not pid, not actor). */
export function projectOpened(payload: unknown): { uuid: string; status: string } | null {
	const r = (payload ?? {}) as Record<string, unknown>;
	const uuid = str(r.session_uuid);
	return uuid ? { uuid, status: str(r.status) ?? 'starting' } : null;
}

export const AGENT_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const PROMPT_MAX = 8000;

/** The open body accepts exactly `{prompt?}`. Anything else is refused, not stripped. */
export function parseOpenBody(body: unknown): { prompt?: string } | string {
	if (!body || typeof body !== 'object' || Array.isArray(body)) return 'body must be a JSON object';
	const keys = Object.keys(body);
	if (keys.some((k) => k !== 'prompt')) return 'body accepts only {prompt}';
	const prompt = (body as { prompt?: unknown }).prompt;
	if (prompt === undefined) return {};
	if (typeof prompt !== 'string' || prompt.length > PROMPT_MAX)
		return `prompt must be a string of at most ${PROMPT_MAX} characters`;
	return { prompt };
}
