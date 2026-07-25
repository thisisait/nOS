/**
 * The version the running code was built from.
 *
 * Read from the image's own package.json rather than injected at build time, so
 * it reports what the SOURCE says — deliberately independent of the image tag an
 * operator chose. A pin that builds one ref and labels it another produces a
 * running system whose tag and contents disagree, and without this the
 * disagreement is undetectable from inside: everything reports healthy because
 * everything IS healthy, just not the version anyone thinks.
 *
 * This is read by /api/health, which is the nOS LIVENESS probe, so it must not
 * be able to fail the request. Resolution happens once at module load inside a
 * total try/catch and yields 'unknown' rather than throwing — the first version
 * resolved a path with __dirname, which does not exist in the ESM bundle, and
 * took the health endpoint down with a ReferenceError. A field describing what
 * the process IS must never stop the process from answering.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';

/** Resolved eagerly: a failure here shows up at boot, never on a probe. */
const VERSION: string = (() => {
  try {
    // The image runs `node dist-server/index.js` from WORKDIR /app, where
    // package.json sits; in dev and e2e the cwd is the repo root. Both resolve
    // without a module-relative path, which is what made this fragile.
    const raw = readFileSync(path.resolve(process.cwd(), 'package.json'), 'utf8');
    const v = (JSON.parse(raw) as { version?: unknown }).version;
    return typeof v === 'string' && v ? v : 'unknown';
  } catch {
    return 'unknown';
  }
})();

export function buildVersion(): string {
  return VERSION;
}
