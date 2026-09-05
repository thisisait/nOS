/**
 * SCHEMA-PIN GATE (dtt tables contract, clause 2 — the highest-value clause).
 *
 * Validates every state/keap-tables/*.table.yml against KEAP's OWN zod schema,
 * vendored at the pinned keap_repo_ref (v1.44.0 / a97c91ff — see the sibling
 * files' headers). This makes "a definition runs ahead of the pin" structurally
 * impossible instead of release discipline: the caddy-sessions `style: chat`
 * incident was a def valid only against a schema an orphan tag carried; a
 * dev-cut release would have 400'd the seed and killed the converge, and no
 * offline gate caught it. This one does.
 *
 * It runs the SAME schema KEAP's agent door runs, mapping each def onto the
 * CreateTableRequest shape EXACTLY as the door does (nos-keap server/agent.ts
 * ~916-938): the seeder sends a flat `{slug, columns, …}` body and the door
 * lifts `columns` under `schema` and injects the slug as id AFTER validation
 * (id is branded uuid-only), so the parse sees no id/slug. We mirror that — a
 * faithful "would this def 400 the seed?" check, not a re-expression of the law.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parse as parseYaml } from 'yaml';
import { createTableRequestSchema } from './table';

// files/anatomy/face/src/lib/keap-contracts → repo root is six levels up.
const DEFS = fileURLToPath(new URL('../../../../../../state/keap-tables/', import.meta.url));

/** The door's-eye body: flat def → CreateTableRequest (columns under schema,
 *  no id/slug — the door injects the slug as id post-parse). */
function doorBody(def: Record<string, unknown>, dropConcept: Record<string, string> = {}) {
	const schema = (def.schema ?? {}) as Record<string, unknown>;
	// A documented exception strips ONLY the named column's concept before
	// validating — the binding it cannot satisfy — leaving every other field
	// (and every other column) fully checked.
	const columns = Array.isArray(schema.columns)
		? schema.columns.map((c) => {
				const col = c as Record<string, unknown>;
				return typeof col.key === 'string' && dropConcept[col.key]
					? { ...col, concept: undefined }
					: col;
			})
		: schema.columns;
	return {
		title: def.title,
		description: def.description,
		driver: def.driver,
		schema: { columns },
		anchors: def.anchors,
		visibility: def.visibility,
		graph: def.graph,
		view: def.view,
		sharedWith: def.sharedWith
	};
}

/** Documented cross-repo exceptions: (table file → column → why) where a def
 *  cannot satisfy the concept↔kind rule because KEAP's vocabulary lacks a
 *  binding AND another nOS contract fixes the column's kind. The gate strips
 *  only the named column's concept before validating; each entry names the
 *  resolution that removes it. This is a real external gap, tracked to closure
 *  — never a place to park nOS's own drift. */
const CONCEPT_EXCEPTIONS: Record<string, Record<string, string>> = {
	'loop-config.table.yml': {
		enabled:
			'MUST be boolean (test_the_harness_toggle_defaults_off; the fixture ships ' +
			'enabled: false, consumed as a boolean), but KEAP v1.44.0 has no ' +
			'boolean-binding concept. Remove once KEAP ships one (keap boolean-concept ' +
			'proposal, 2026-09-06) and re-vendor.'
	}
};

const files = readdirSync(DEFS)
	.filter((f) => f.endsWith('.table.yml'))
	.sort();

describe('keap-tables definitions validate against the pinned KEAP schema', () => {
	it('finds the 18-ish system table defs', () => {
		expect(files.length).toBeGreaterThanOrEqual(15);
	});

	for (const f of files) {
		it(`${f} parses as a valid CreateTableRequest`, () => {
			const def = parseYaml(readFileSync(DEFS + f, 'utf-8')) as Record<string, unknown>;
			const r = createTableRequestSchema.safeParse(doorBody(def, CONCEPT_EXCEPTIONS[f]));
			expect(
				r.success ? null : r.error.issues,
				`${f}: ${r.success ? '' : r.error.issues[0]?.message}`
			).toBeNull();
		});
	}
});

describe('the gate has teeth (rejects what KEAP would 400)', () => {
	it('refuses the invented `tier-admins` visibility grade', () => {
		const bad = doorBody({
			title: 'x',
			visibility: 'tier-admins',
			schema: { columns: [{ key: 'a', label: 'A', kind: 'text', role: 'dimension' }] }
		});
		expect(createTableRequestSchema.safeParse(bad).success).toBe(false);
	});

	it('refuses a rowRef column with no refTable', () => {
		const bad = doorBody({
			title: 'x',
			schema: { columns: [{ key: 'r', label: 'R', kind: 'rowRef', role: 'dimension' }] }
		});
		expect(createTableRequestSchema.safeParse(bad).success).toBe(false);
	});
});
