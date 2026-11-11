/**
 * "Awaiting you" (row face-app-awaiting / agents-awaiting-surface, ruling 2026-11-11 (b)): what cannot
 * move without the operator, merged by the BFF from the two Wing reads the face already makes. Read-only:
 * every row is answered elsewhere (the Inbox app — Q15, Wing is the one answering channel). The other
 * sources tools/awaiting-operator.py reads (the thalamus ledger, Bone's loop ledger, the apex ruling)
 * are not reachable from the face yet and are NAMED, never rendered as an empty list. Pure: tested.
 */
import { projectNotifications, projectQuestions } from '$lib/inbox/project';

export type AwaitingKind = 'question' | 'alert';
export type AwaitingItem = { id: string; kind: AwaitingKind; title: string; since: string };
export type Awaiting = { items: AwaitingItem[]; unreachable: string[] };

/** The kinds the CLI reader sees that the face does not, in its words. */
export const UNREACHABLE = [
	'Iris approval cards (the thalamus ledger)',
	'judged loop proposals not yet landed (Bone)',
	'a signed ruling amended after signing (apex)'
];

const URGENT = new Set(['critical', 'high']);

export function projectAwaiting(questions: unknown, notifications: unknown): Awaiting {
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
	return { items: [...q, ...n], unreachable: UNREACHABLE };
}
