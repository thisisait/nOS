// The agents' open questions in the face Iris (row iris-face-answers-questions, operator
// 2026-11-08): a tier-1 person answers in place; the thalamus relays it to Wing, which
// resolves it once. The face shows what Wing said and never guesses an outcome.
import type { ToShell, ToThalamus, Value } from './wire';

export type Question = { uuid: string; agent: string; prompt: string; expires?: string };
type Result = Extract<ToShell, { t: 'answer_result' }>;

const str = (v: Value | undefined) => (typeof v === 'string' ? v : '');

/** Wing's rows as the socket lists them; a row without a uuid or a prompt is not a question. */
export function fromWire(items: { [k: string]: Value }[]): Question[] {
	return items
		.map((r) => ({
			uuid: str(r.uuid),
			agent: str(r.agent_name) || 'an agent',
			prompt: str(r.prompt),
			expires: str(r.expires_at) || undefined
		}))
		.filter((q) => q.uuid && q.prompt);
}

/** One answer to send, or null for a blank one (Wing trims, so a blank is no answer). */
export function answer(uuid: string, text: string): Extract<ToThalamus, { t: 'answer' }> | null {
	const a = text.trim();
	return a ? { t: 'answer', uuid, answer: a } : null;
}

/** What the person reads after Wing decided: the words say who won when it was not them. */
export function said(r: Result): string {
	switch (r.outcome) {
		case 'answered':
			return 'answered';
		case 'lost':
			return `already answered: ${r.winning_answer ?? 'another answer'} won first`;
		case 'expired':
			return 'expired before the answer arrived';
		default:
			return `not answered: ${r.why ?? 'refused'}`;
	}
}
