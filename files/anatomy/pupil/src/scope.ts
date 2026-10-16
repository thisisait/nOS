// `/for <client>`, `/for personal`, `/for all` in the composer: whom the person works for (wire working_for).
import type { Scope } from './wire';

/** undefined: not a /for line (a turn); null: a /for naming no one (nothing is sent). */
export function forCommand(text: string): Scope | null | undefined {
	const t = text.trim();
	if (t !== '/for' && !t.startsWith('/for ')) return undefined;
	const who = t.slice(4).trim();
	if (!who) return null;
	return who === 'all' || who === 'personal' ? who : { client: who };
}
