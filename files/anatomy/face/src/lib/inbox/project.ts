/**
 * The face Inbox app's view of Wing's inbox (row wing-inc1-inbox-app). The BFF projects fixed
 * fields, never proxies: a question never carries its reply token or the token's hash, nor its
 * context blob; a notification carries what the list shows. Pure, so the projection is tested.
 */

export type InboxQuestion = {
	uuid: string;
	agent: string;
	kind: string;
	prompt: string;
	options: string[] | null;
	severity: string;
	created: string;
	expires: string | null;
	onExpiry: string | null;
};

export type InboxNotification = {
	uuid: string;
	severity: string;
	title: string;
	body: string;
	created: string;
	from: string;
};

export type AnswerOutcome =
	| { outcome: 'answered' }
	| { outcome: 'lost'; winning: string; by: string }
	| { outcome: 'expired'; onExpiry: string | null }
	| { outcome: 'refused'; why: string };

type Row = Record<string, unknown>;
const str = (v: unknown) => (typeof v === 'string' ? v : '');
const opt = (v: unknown) => (typeof v === 'string' && v !== '' ? v : null);
/** Only object rows: Wing's list is data, and a null or a string in it is no row. */
const rowsOf = (rows: unknown): Row[] =>
	Array.isArray(rows) ? rows.filter((r): r is Row => !!r && typeof r === 'object') : [];

function options(raw: unknown): string[] | null {
	if (typeof raw !== 'string' || !raw) return null;
	try {
		const a = JSON.parse(raw);
		return Array.isArray(a) && a.length && a.every((x) => typeof x === 'string') ? a : null;
	} catch {
		return null;
	}
}

/** A row without a uuid or a prompt is not a question the person can answer. */
export function projectQuestions(rows: unknown): InboxQuestion[] {
	return rowsOf(rows)
		.map((r) => ({
			uuid: str(r.uuid),
			agent: str(r.agent_name) || 'an agent',
			kind: str(r.kind) || 'question',
			prompt: str(r.prompt),
			options: options(r.options_json),
			severity: str(r.severity) || 'medium',
			created: str(r.created_at),
			expires: opt(r.expires_at),
			onExpiry: opt(r.default_on_expiry)
		}))
		.filter((q) => q.uuid && q.prompt);
}

export function projectNotifications(rows: unknown): InboxNotification[] {
	return rowsOf(rows)
		.map((r) => ({
			uuid: str(r.uuid),
			severity: str(r.severity) || 'info',
			title: str(r.title),
			body: str(r.body),
			created: str(r.created_at),
			from: str(r.origin_agent) || str(r.origin_plugin) || str(r.actor_id)
		}))
		.filter((n) => n.uuid && n.title);
}

/** What Wing said to one answer, as the person must read it: only `answered` decided. */
export function answerOutcome(status: number, body: unknown): AnswerOutcome {
	const b = (body && typeof body === 'object' ? body : {}) as Row;
	if (status === 200 && b.result === 'ok') return { outcome: 'answered' };
	if (status === 409 && b.result === 'already')
		return { outcome: 'lost', winning: str(b.answer), by: str(b.answered_by) };
	if (status === 409 && b.result === 'expired')
		return { outcome: 'expired', onExpiry: opt(b.default_on_expiry) };
	return { outcome: 'refused', why: str(b.error) || `Wing answered ${status}` };
}
