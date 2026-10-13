// A widget form's rule and its payload, pure so node tests reach them (Form.svelte draws them).
import type { FormField } from './wire';

/** What the person has typed so far, by field key; nothing is there until they type it. */
export type Draft = Record<string, string | number | boolean | null | undefined>;

/** The pupil's words, never the props': the title and table only fill the blanks. */
export const header = (f: { title: string; table: string }) => `Adds a row to ${f.title} (${f.table})`;

const missing = (v: Draft[string]) => v === undefined || v === null || v === '';

/** Every required field holds a value (a bool always does) and no submit is in flight. */
export const canSubmit = (fields: FormField[], draft: Draft, inFlight: boolean) =>
	!inFlight && fields.every((f) => !f.required || f.kind === 'bool' || !missing(draft[f.key]));

/** The values a submit carries: typed by field, an empty optional field left out, a bool always sent. */
export function formValues(fields: FormField[], draft: Draft): Record<string, string | number | boolean> {
	const out: Record<string, string | number | boolean> = {};
	for (const f of fields) {
		const v = draft[f.key];
		if (f.kind === 'bool') out[f.key] = v === true;
		else if (!missing(v)) out[f.key] = f.kind === 'number' ? Number(v) : String(v);
	}
	return out;
}
