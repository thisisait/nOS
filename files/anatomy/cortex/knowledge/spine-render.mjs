/**
 * Render the seed spine from its SoT (`knowledge/spine/*.json`) into the
 * TypeScript module the app and the server import.
 *
 * P-1 of the cortex backend/UI split. Until now the 790-node spine — 43% of the
 * live taxonomy, and every L0/L1 domain the grown nodes hang from — existed ONLY
 * as TypeScript inside the frontend source tree, which `server/taxonomy.ts`
 * imported across the app/server boundary. `knowledge/` was the git SoT for the
 * *delta over* that spine, so "materialise the ontology from git" was impossible
 * for anyone but this repo's build.
 *
 * The authority now lives in `knowledge/spine/`, as data. `src/game/data/
 * taxonomy.ts` is a GENERATED artifact, checked in and gated: CI runs this
 * script and `git diff --exit-code`, the same pattern `lift-xrefs.mjs` uses for
 * brief cross-refs.
 *
 * Why generate the TS instead of importing the JSON directly: the file is
 * imported by BOTH builds (vite for `src/components/TaxonomySelect.tsx`, esbuild
 * for the server bundle) and neither tsconfig enables `resolveJsonModule`.
 * Making the runtime depend on a JSON-import path that two different bundlers
 * must agree on would risk the composition for no gain — the point of P-1 is
 * that the DATA is readable from git without a TypeScript toolchain, and that is
 * satisfied by the JSON being the source rather than the output.
 *
 *   node knowledge/spine-render.mjs [--check]
 *   --check: render and diff without writing (exit 1 on drift)
 */
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SPINE = path.join(HERE, 'spine');
const TARGET = path.join(HERE, '..', 'src', 'game', 'data', 'taxonomy.ts');
const CHECK = process.argv.includes('--check');

// Domain order is the FILE NAME order, and the file names are id-prefixed
// (`01-…` … `12-…`). That is not cosmetic: the composition in
// server/taxonomy.ts walks `Object.values(taxonomyData)` in insertion order, and
// that order decides every parent's `childIds` sequence — which drives sibling
// ordering in the UI and the U1 layout bake. A sorted read reproduces it
// deterministically from disk.
const files = readdirSync(SPINE)
  .filter((f) => f.endsWith('.json') && f !== 'manifest.json')
  .sort();

const entries = [];
for (const f of files) {
  const doc = JSON.parse(readFileSync(path.join(SPINE, f), 'utf8'));
  if (!doc.key || !doc.category) throw new Error(`${f}: expected { key, category }`);
  entries.push([doc.key, doc.category]);
}

const data = Object.fromEntries(entries);
const body = JSON.stringify(data, null, 2);

const rendered = `// GENERATED FILE — DO NOT EDIT.
//
// Source of truth: knowledge/spine/*.json
// Regenerate:      node knowledge/spine-render.mjs
// CI gate:         node knowledge/spine-render.mjs --check
//
// The seed spine is DATA (knowledge/spine), not code. This module exists so the
// app and the server keep importing a TypeScript symbol, and so neither build
// needs resolveJsonModule; it carries no information the JSON does not.
import { TaxonomyData } from '../types/taxonomy';

export const taxonomyData: TaxonomyData = ${body};
`;

const current = readFileSync(TARGET, 'utf8');
if (CHECK) {
  if (current === rendered) {
    console.log(`✓ spine in sync — ${entries.length} domains, ${files.length} files`);
    process.exit(0);
  }
  console.error('✗ src/game/data/taxonomy.ts is out of sync with knowledge/spine/.');
  console.error('  Run: node knowledge/spine-render.mjs');
  process.exit(1);
}

writeFileSync(TARGET, rendered);
console.log(`rendered ${entries.length} domains → ${path.relative(process.cwd(), TARGET)}`);
