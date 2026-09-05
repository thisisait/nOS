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
function doorBody(def: Record<string, unknown>) {
	const schema = (def.schema ?? {}) as Record<string, unknown>;
	return {
		title: def.title,
		description: def.description,
		driver: def.driver,
		schema: { columns: schema.columns },
		anchors: def.anchors,
		visibility: def.visibility,
		graph: def.graph,
		view: def.view,
		sharedWith: def.sharedWith
	};
}

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
			const r = createTableRequestSchema.safeParse(doorBody(def));
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
