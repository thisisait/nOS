/**
 * The shell's severity vocabulary — one type, one mapping, one place.
 *
 * WHY THIS EXISTS, measured 2026-08-05 before it did: the face had 51
 * hand-written colour rules across 18 components and no shared severity type.
 * The same three states were spelled four different ways —
 *
 *     `loading…`   `empty folder`   `No tables in KEAP yet.`   `No rows.`
 *     `No table.`  `could not list tables`  `could not load table`
 *
 * — each with its own local CSS class, so the same condition looked different
 * depending on which app you were in. That is a UI consistency problem, but it
 * is also a CORRECTNESS one: `DataTableApp.svelte` carries a comment reading
 * "Say it, rather than rendering an empty article list that looks…", which
 * means the doctrine already existed in one component and nowhere it could be
 * applied. A rule that lives in a comment is a rule that is followed by
 * whoever happens to read it.
 *
 * THE FOUR STATUS KINDS ARE NOT COSMETIC. They are the distinction this whole
 * estate keeps getting wrong — a Kuma container reported healthy for ten days
 * while serving its own installer, and every signal the operator owned was
 * green. So:
 *
 *   loading  — we have not asked yet. Says nothing about the answer.
 *   empty    — we asked, and the answer was genuinely nothing.
 *   error    — we asked, and did not get an answer. NOT the same as empty.
 *   unwired  — we could not ask: a token, URL or scope is missing. This one is
 *              a DEPLOYMENT fact, and it is the one most often rendered as an
 *              empty list, which reads as "all clear".
 *
 * Keeping them as distinct kinds means a caller cannot collapse them by
 * accident; it has to choose, and the choice is visible in the diff.
 *
 * Pure module — no Svelte import — so vitest runs it in node.
 */

/** Severity vocabulary shared by every state indicator in the shell. */
export type Tone = 'neutral' | 'ok' | 'info' | 'warn' | 'bad';

/** What a panel is currently able to say. See the module header — these four
 *  are deliberately not interchangeable. */
export type StatusKind = 'loading' | 'empty' | 'error' | 'unwired';

export const TONES: readonly Tone[] = ['neutral', 'ok', 'info', 'warn', 'bad'] as const;
export const STATUS_KINDS: readonly StatusKind[] = [
	'loading',
	'empty',
	'error',
	'unwired'
] as const;

/**
 * Tone for each status kind.
 *
 * `empty` is NEUTRAL, not ok. "There is nothing here" is not good news — it is
 * the absence of news, and colouring it green is how a blank panel starts
 * reading as a healthy one.
 *
 * `unwired` is WARN rather than bad: nothing is broken, but nothing is being
 * watched either, and that deserves to be as loud as a failure is quiet.
 */
export const STATUS_TONE: Record<StatusKind, Tone> = {
	loading: 'neutral',
	empty: 'neutral',
	error: 'bad',
	unwired: 'warn'
};

/** Leading glyph per kind. Text, never HTML — the shell escapes everything. */
export const STATUS_GLYPH: Record<StatusKind, string> = {
	loading: '…',
	empty: '∅',
	error: '!',
	unwired: '⚠'
};

/** CSS custom-property names for a tone. Defined once in `app.css`. */
export function toneVars(tone: Tone): { ink: string; soft: string; solid: string } {
	if (tone === 'neutral') {
		return {
			ink: 'var(--muted, #9aa4b2)',
			soft: 'rgba(255, 255, 255, 0.07)',
			solid: 'var(--muted, #9aa4b2)'
		};
	}
	return {
		ink: `var(--${tone}-ink)`,
		soft: `var(--${tone}-soft)`,
		solid: `var(--${tone})`
	};
}

/** A process exit code → tone. `null` means the run reported no result yet,
 *  which is INFO (in flight), never ok. */
export function exitTone(code: number | null | undefined): Tone {
	if (code === null || code === undefined) return 'info';
	return code === 0 ? 'ok' : 'bad';
}

/** A9 severity string → tone. Unknown severities stay neutral rather than
 *  being guessed into a colour. */
export function severityTone(severity: string | null | undefined): Tone {
	switch ((severity ?? '').toLowerCase()) {
		case 'critical':
		case 'high':
			return 'bad';
		case 'medium':
			return 'warn';
		case 'low':
		case 'info':
			return 'info';
		default:
			return 'neutral';
	}
}
