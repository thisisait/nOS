/**
 * Conformance runner for the `onto1:` composition contract (P-2).
 *
 * THIS IS THE ARTIFACT A PORT IS GRADED AGAINST. An implementation of
 * docs/specs/onto1-composition-contract.md conforms iff, for every fixture in
 * knowledge/fixtures/onto1/, it reproduces BOTH the exact canonical
 * serialization and the digest.
 *
 * Both are checked, not just the digest, and that is deliberate: two hashes that
 * differ tell you nothing about WHICH field stopped mattering. The canonical
 * string is the diagnostic; the digest is the assertion.
 *
 *   node knowledge/onto1-conformance.mjs            # grade the reference impl
 *   node knowledge/onto1-conformance.mjs --bless    # (re)compute expectations
 *
 * A port in another language reimplements the contract and compares its output
 * to each fixture's `expected` block — no need to run this file.
 */
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { composeFingerprint } from './onto1-compose.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.join(HERE, 'fixtures', 'onto1');
const BLESS = process.argv.includes('--bless');

const files = readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();
let failed = 0;

for (const f of files) {
  const full = path.join(DIR, f);
  const doc = JSON.parse(readFileSync(full, 'utf8'));
  const got = composeFingerprint(doc.spine, doc.ext ?? [], doc.relationTypes ?? []);
  const actual = {
    nodeCount: got.nodeCount,
    dropped: got.dropped,
    onto1: got.onto1,
    canonical: got.canonical.split('\n'),
  };

  if (BLESS) {
    doc.expected = actual;
    writeFileSync(full, JSON.stringify(doc, null, 1) + '\n');
    console.log(`blessed ${f} — ${actual.nodeCount} nodes, ${actual.onto1}`);
    continue;
  }

  const want = doc.expected;
  if (!want) {
    console.error(`✗ ${f}: no expected block — run --bless`);
    failed++;
    continue;
  }
  const diffs = [];
  if (want.onto1 !== actual.onto1) diffs.push(`onto1 ${want.onto1} != ${actual.onto1}`);
  if (want.nodeCount !== actual.nodeCount) diffs.push(`nodeCount ${want.nodeCount} != ${actual.nodeCount}`);
  if (JSON.stringify(want.dropped) !== JSON.stringify(actual.dropped)) {
    diffs.push(`dropped ${JSON.stringify(want.dropped)} != ${JSON.stringify(actual.dropped)}`);
  }
  const wl = want.canonical ?? [];
  const al = actual.canonical;
  for (let i = 0; i < Math.max(wl.length, al.length); i++) {
    if (wl[i] !== al[i]) {
      diffs.push(`line ${i + 1}: expected ${JSON.stringify(wl[i])}, got ${JSON.stringify(al[i])}`);
      break; // the first divergence is the informative one
    }
  }

  if (diffs.length) {
    console.error(`✗ ${f} — ${doc.why ?? ''}`);
    for (const d of diffs) console.error(`    ${d}`);
    failed++;
  } else {
    console.log(`✓ ${f}  ${actual.nodeCount} nodes  ${actual.onto1}`);
  }
}

if (!BLESS) {
  console.log(failed ? `✗ ${failed}/${files.length} fixture(s) failed` : `✓ onto1 conformance — ${files.length}/${files.length}`);
  process.exitCode = failed ? 1 : 0;
}
