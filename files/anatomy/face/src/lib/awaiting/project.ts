/**
 * "Awaiting you" (row face-app-awaiting / agents-awaiting-surface, ruling 2026-11-11 (b)): what cannot
 * move without the operator, merged by the BFF from the two Wing reads the face already makes. Read-only:
 * every row is answered elsewhere (the Inbox app — Q15, Wing is the one answering channel). The other
 * sources tools/awaiting-operator.py reads (Bone's loop ledger, the apex ruling) are not reachable from
 * the face yet and are NAMED; the thalamus ledger's Iris cards come through a read hello, and a source
 * that does not answer is UNKNOWN, never an empty list. Pure: tested.
 */
import { projectNotifications, projectQuestions } from '$lib/inbox/project';

export type AwaitingKind = 'question' | 'alert' | 'approval';
export type AwaitingItem = { id: string; kind: AwaitingKind; title: string; since: string };
/** `unknown`: a source that was asked and did not answer, said with why; never an empty list. */
export type Awaiting = { items: AwaitingItem[]; unreachable: string[]; unknown: string[] };

/** The kinds the CLI reader sees that the face does not, in its words. */
export const UNREACHABLE = [
	'judged loop proposals not yet landed (Bone)',
	'a signed ruling amended after signing (apex)'
];

const URGENT = new Set(['critical', 'high']);
const ID = /^[0-9a-f-]{1,64}$/i;
const TOOL = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;

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

/** `cards`: the approvals_open items, or why the thalamus gave none (shown as unknown). */
export function projectAwaiting(
	questions: unknown,
	notifications: unknown,
	cards: unknown[] | string = 'not asked'
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
	return { items: [...q, ...n, ...c], unreachable: UNREACHABLE, unknown };
}
