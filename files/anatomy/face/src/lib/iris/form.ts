// A widget form's rule and its payload, pure so node tests reach them (Form.svelte draws them).
import type { FormField, Lens } from './wire';

/** What the person has typed so far, by field key; nothing is there until they type it. */
export type Draft = Record<string, string | number | boolean | null | undefined>;

/** The pupil's words, never the props': the title and table only fill the blanks. */
export const header = (f: { title: string; table: string }) =>
	`Adds a row to ${f.title} (${f.table})`;

const missing = (v: Draft[string]) => v === undefined || v === null || v === '';

/** A field with no condition always shows; else the other field's draft, as text, must (eq) or must not (neq) be the value. */
export const shown = (f: FormField, draft: Draft) =>
	!f.when || (String(draft[f.when.key] ?? '') === f.when.value) === (f.when.op === 'eq');

/** Every required field holds a value (a bool always does) and no submit is in flight. */
export const canSubmit = (fields: FormField[], draft: Draft, inFlight: boolean) =>
	!inFlight && fields.every((f) => !f.required || f.kind === 'bool' || !missing(draft[f.key]));

/** The values a submit carries: typed by field, an empty optional field left out, a bool always sent, a hidden field never. */
export function formValues(
	fields: FormField[],
	draft: Draft
): Record<string, string | number | boolean> {
	const out: Record<string, string | number | boolean> = {};
	for (const f of fields.filter((x) => shown(x, draft))) {
		const v = draft[f.key];
		if (f.kind === 'bool') out[f.key] = v === true;
		else if (!missing(v)) out[f.key] = f.kind === 'number' ? Number(v) : String(v);
	}
	return out;
}

/** A tab's lens as a form's first values: an eq condition with a value, on a field it can fill; never more. */
export function lensPrefill(lens: Lens[] = [], fields: FormField[]): Draft {
	const out: Draft = {};
	for (const c of lens) {
		const f = fields.find((x) => x.key === c.column);
		if (!f || c.op !== 'eq' || c.value === '') continue;
		if (f.kind === 'select' && !f.options?.includes(c.value)) continue;
		if (f.kind === 'number' && !Number.isFinite(Number(c.value))) continue;
		out[f.key] =
			f.kind === 'number' ? Number(c.value) : f.kind === 'bool' ? c.value === 'true' : c.value;
	}
	return out;
}
