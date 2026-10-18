// A choice's answer (wire.ts ChoiceProps -> choice_reply): the suggestion is where it starts, a
// pick in a single choice replaces the last, and a reply goes once, with only offered labels.
import type { ChoiceProps, ToThalamus } from './wire';

export const initial = (c: ChoiceProps): string[] => [...c.suggested];

export function toggle(c: ChoiceProps, picked: string[], label: string): string[] {
	if (!c.options.some((o) => o.label === label)) return picked;
	if (!c.multi) return [label];
	return picked.includes(label) ? picked.filter((p) => p !== label) : [...picked, label];
}

/** The reply to send, or null: already sent, nothing picked, a label not offered, two on a single. */
export function reply(session: string, c: ChoiceProps, picked: string[], sent: boolean): ToThalamus | null {
	const ok = picked.every((p) => c.options.some((o) => o.label === p));
	if (sent || !c.id || !picked.length || !ok || (!c.multi && picked.length > 1)) return null;
	return { t: 'choice_reply', session, choice: c.id, picked: c.options.map((o) => o.label).filter((l) => picked.includes(l)) };
}

/** What the card shows as answered: m.picked once `onreply` accepted it, else null (send again). */
export async function answer(m: Extract<ToThalamus, { t: 'choice_reply' }>, onreply?: (m: Extract<ToThalamus, { t: 'choice_reply' }>) => Promise<boolean>): Promise<string[] | null> {
	try {
		return (await onreply?.(m)) ? m.picked : null;
	} catch {
		return null;
	}
}
