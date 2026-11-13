/**
 * "Awaiting you" (row face-app-awaiting / agents-awaiting-surface, ruling 2026-11-11 (b)): what cannot
 * move without the operator, merged by the BFF from the two Wing reads the face already makes. Read-only:
 * every row is answered elsewhere (the Inbox app — Q15, Wing is the one answering channel). The other
 * source tools/awaiting-operator.py reads that the face cannot (the apex ruling) is NAMED; the thalamus
 * ledger's Iris cards come through a read hello, Bone's unlanded loop proposals through
 * GET /api/v1/loop/awaiting, and a source
 * that does not answer is UNKNOWN, never an empty list. Pure: tested.
 */
import { projectNotifications, projectQuestions } from '$lib/inbox/project';

export type AwaitingKind = 'question' | 'alert' | 'approval' | 'proposal';
export type AwaitingItem = { id: string; kind: AwaitingKind; title: string; since: string };
/** `unknown`: a source that was asked and did not answer, said with why; never an empty list. */
export type Awaiting = { items: AwaitingItem[]; unreachable: string[]; unknown: string[] };

/** The kinds the CLI reader sees that the face does not, in its words. */
export const UNREACHABLE = ['a signed ruling amended after signing (apex)'];

const URGENT = new Set(['critical', 'high']);
const ID = /^[0-9a-f-]{1,64}$/i;
const TOOL = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
/** loop-status.awaiting()'s `unlanded` states; anything else Bone sends is dropped. */
const PROPOSAL_STATES = new Set(['unjudged', 'ready', 're-judge', 'indeterminate']);
const text = (v: unknown, n: number) => (typeof v === 'string' ? v.slice(0, n) : '');

/** Bone GET /api/v1/loop/awaiting `unlanded`: uuid, what it fixes, its state and why, never the diff. */
export function projectProposals(unlanded: unknown): AwaitingItem[] {
	if (!Array.isArray(unlanded)) return [];
	return unlanded.flatMap((x) => {
		const o = (x ?? {}) as Record<string, unknown>;
		if (typeof o.uuid !== 'string' || !ID.test(o.uuid)) return [];
		if (typeof o.state !== 'string' || !PROPOSAL_STATES.has(o.state)) return [];
		const why = text(o.detail, 160);
		const title = `Loop proposal for ${text(o.weakness_id, 80) || '?'}: ${o.state}${why ? ` (${why})` : ''}`;
		return [{ id: o.uuid, kind: 'proposal' as const, title, since: text(o.verdict_at, 40) }];
	});
}

/** The person's own open Iris cards (approvals_open items): id, tool and when only, never the session. */
export function projectApprovals(items: unknown): AwaitingItem[] {
	if (!Array.isArray(items)) return [];
	return items.flatMap((x) => {
		const o = (x ?? {}) as Record<string, unknown>;
		const { approval, tool, asked_at } = o;
		if (typeof approval !== 'string' || !ID.test(approval)) return [];
		if (typeof tool !== 'string' || !TOOL.test(tool)) return [];
		const since = typeof asked_at === 'string' ? asked_at.slice(0, 40) : '';
		return [
			{ id: approval, kind: 'approval' as const, title: `Iris asks you to approve ${tool}`, since }
		];
	});
}

/** `cards`: the approvals_open items, or why the thalamus gave none; `proposals`: Bone's awaiting
 *  answer, or why it gave none. Each "why" is shown as unknown. */
export function projectAwaiting(
	questions: unknown,
	notifications: unknown,
	cards: unknown[] | string = 'not asked',
	proposals: unknown = 'not asked'
): Awaiting {
	const q = projectQuestions(questions).map((x) => ({
		id: x.uuid,
		kind: 'question' as const,
		title: `${x.agent}: ${x.prompt}`.slice(0, 200),
		since: x.created
	}));
	const n = projectNotifications(notifications)
		.filter((x) => URGENT.has(x.severity.toLowerCase()))
		.map((x) => ({
			id: x.uuid,
			kind: 'alert' as const,
			title: x.title.slice(0, 200),
			since: x.created
		}));
	const c = typeof cards === 'string' ? [] : projectApprovals(cards);
	const unknown = typeof cards === 'string' ? [`Iris cards: ${cards.slice(0, 200)}`] : [];
	const b = (proposals ?? {}) as { unlanded?: unknown; unknown?: unknown };
	const bWhy = typeof proposals === 'string' ? proposals : text(b.unknown, 200);
	if (bWhy || !Array.isArray(b.unlanded))
		unknown.push(`Loop proposals: ${bWhy || 'Bone sent no list'}`);
	const p = bWhy ? [] : projectProposals(b.unlanded);
	return { items: [...q, ...n, ...c, ...p], unreachable: UNREACHABLE, unknown };
}
