// The approval queue, as the terminal shell keeps it (thalamus/src/shell.rs): oldest
// first and only that one decided (30-32); approve once its whole edit was shown (33,
// 175, 221-223), reject any time (176); one decision each (179); closed = not decided (157-161).
import type { Component, ToShell, ToThalamus } from './wire';

export type Waiting = { approval: string; component: Component };
/** `whole` names the approval whose last row was in view; any other id is not shown. */
export type Queue = { pending: Waiting[]; whole: string | null };
export type Decision = 'approve' | 'reject';

export const empty = (): Queue => ({ pending: [], whole: null });

export const asked = (q: Queue, m: Extract<ToShell, { t: 'approval_request' }>): Queue => ({
	...q,
	pending: [...q.pending, { approval: m.approval, component: m.component }]
});

export const seen = (q: Queue, approval: string): Queue =>
	q.pending[0]?.approval === approval ? { ...q, whole: approval } : q;

export function decide(q: Queue, approval: string, decision: Decision) {
	const first = q.pending[0];
	if (first?.approval !== approval || (decision === 'approve' && q.whole !== approval))
		return { q, send: null, decided: null };
	const send: ToThalamus = { t: 'approval_decision', approval, decision, note: null };
	return { q: { pending: q.pending.slice(1), whole: null }, send, decided: first };
}

export const closed = (q: Queue) => ({
	q: empty(),
	notes: q.pending.map((w) => `not decided, nothing written: approval ${w.approval}`)
});

export const composerOpen = (q: Queue) => q.pending.length === 0;
