// `/for <client>`, `/for personal`, `/for all` in the composer: whom the person works for (wire working_for).
import type { Scope, ToThalamus } from './wire';
import type { Widgets } from './widgets';
import { restore, type Layout } from './workspace';

/** undefined: not a /for line (a turn); null: a /for naming no one (nothing is sent). */
export function forCommand(text: string): Scope | null | undefined {
	const t = text.trim();
	if (t !== '/for' && !t.startsWith('/for ')) return undefined;
	const who = t.slice(4).trim();
	if (!who) return null;
	return who === 'all' || who === 'personal' ? who : { client: who };
}

/** `/clear` or `/branch` alone (contract 9): a fresh conversation for this tab, or a new tab that starts from it. */
export function tabCommand(text: string): 'clear' | 'branch' | undefined {
	const t = text.trim();
	return t === '/clear' || t === '/branch' ? (t.slice(1) as 'clear' | 'branch') : undefined;
}

/** Serve's wall lives on one connection: a new link says `want` again and no widget reads before its
 * answer; the answer (working_for) re-runs every widget, so no row read under another scope stays. */
export function rewall(
	want: Scope | null,
	l: Layout,
	ev: 'connected' | 'working_for'
): { w: Widgets | null; send: ToThalamus[] } {
	if (ev === 'connected' && want) return { w: null, send: [{ t: 'working_for', scope: want }] };
	return restore(l);
}
