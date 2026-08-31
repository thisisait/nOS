/**
 * Read-only knowledge roots registry — the mount table behind the admin-managed
 * "mapped folders" (fs_mappings, server/fs-sync.ts syncMapping).
 *
 * The nOS role bind-mounts each configured host tree to /mounts/<key> (:ro)
 * and announces it via KEAP_FS_ROOTS="key=/mounts/key,other=/mounts/other".
 * The key — not the container path — is the root's stable identity: a host
 * relocation re-mounts under the same key and every mapping keeps working.
 *
 * Doctrine guards (see the mapped-folders spec §3/§12.2):
 *   - keys 'users' and 'user-files' are reserved — the per-user doctrine tree
 *     has its OWN sync pipeline (fs-sync users pass) and a root over it would
 *     double-ingest every file;
 *   - the overlap check vs EVERY per-user root (realpath containment, both
 *     directions) runs lazily at resolve time, so a conflicting root degrades
 *     to a typed error, never to double-ingest;
 *   - a root whose path does not exist stays REGISTERED with exists:false — a
 *     mount may appear after boot, and dropping it at parse time would create
 *     a restart-ordering trap.
 */
import { realpathSync, statSync } from 'node:fs';
import path from 'node:path';
// ── nOS S3 DIFF 1/2 — the guard resolves the roots the organ really walks ───
// KEAP reads `process.env.KEAP_USER_FILES_DIR` here, and its compose file sets
// that variable, so the overlap guard runs on KEAP. The ORGAN'S plist never
// sets it — since docs/archive/cortex-corpus-parallel.md §1.4 the users pass
// walks an ORDERED LIST
// (`CORTEX_FS_USER_ROOTS` -> `KEAP_FS_USER_ROOTS`), of which the single path is
// only one shape. So on this deployment the guard was keyed on a variable
// nobody sets, the `if` never ran, and a mapped-folder root laid over the
// per-user tree would have resolved cleanly and mirrored every user's documents
// under owner `fsmap:<id>` with the MAPPING's visibility — one user's files
// readable by everyone, and invisible to the users-pass prune filter.
//
// NOT UPSTREAMABLE, corrected 2026-08-31 — the first draft of this marker said
// KEAP would take it unchanged. It would not: `listUserRoots` lives in
// server/cortex-fs.ts, which is nOS-AUTHORED and has no counterpart upstream.
// Sending this patch to KEAP would mean vendoring the roots-list abstraction
// with it, and KEAP does not need it — its compose file stacks the two trees
// at one path, so a single `KEAP_USER_FILES_DIR` is the whole truth there.
// The divergence exists because the deployments differ, which is the honest
// reason for a declaration rather than a pull request.
import { listUserRoots } from './cortex-fs';

const KEY_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;
const RESERVED_KEYS = new Set(['users', 'user-files']);

/**
 * The per-user tree, as the users pass actually sees it.
 *
 * This used to be `process.env.KEAP_USER_FILES_DIR` read directly, "so the
 * dependency stays one-way: fs-sync → fs-roots, never back". The direction was
 * right and the VALUE was wrong: since §1.4 the users pass walks an ORDERED LIST
 * of roots (`KEAP_FS_USER_ROOTS`, which the organ's deployment sets from
 * `CORTEX_FS_USER_ROOTS`), and `KEAP_USER_FILES_DIR` is only ONE of the shapes
 * that list can take — the organ's plist never sets it at all. So the guard this
 * module's header calls a doctrine guard was reading a variable nobody sets, the
 * `if` never ran, and a mapped-folder root over the per-user tree would have
 * resolved cleanly and mirrored every user's documents under owner `fsmap:<id>`
 * with the MAPPING's visibility — one user's files readable by everyone, and
 * invisible to the users-pass prune filter (`source === 'fs'`) that would
 * otherwise have cleaned the duplicates up.
 *
 * `listUserRoots` is the same resolver `fs-sync.ts` uses, so the guard is now
 * defined against the roots that pass will really walk rather than against a
 * second, hand-kept spelling of them. The dependency stays one-way: `cortex-fs`
 * imports nothing local, so `fs-roots → cortex-fs ← fs-sync` has no cycle.
 *
 * Resolved LAZILY (and memoised) rather than at module load: `aliasFsEnv()` maps
 * `CORTEX_FS_*` onto the `KEAP_FS_*` names at daemon start, and this module may
 * be imported before that runs — reading the env at load would freeze an empty
 * list and disable the guard exactly the way the old constant did.
 */
let userRootPaths: string[] | null = null;
function perUserRoots(): string[] {
  if (!userRootPaths) userRootPaths = listUserRoots().map((r) => r.path);
  return userRootPaths;
}

// ── nOS S3 DIFF 2/2 — memoised, with a seam so a test can re-resolve ────────
/** Test seam only: drop the memoised roots so a scenario can re-resolve them. */
export function _resetUserRootsCache(): void {
  userRootPaths = null;
}

export interface FsRoot {
  key: string;
  path: string;
  exists: boolean;
}

// Parsed once at module init. Syntactically invalid entries are dropped with
// a warning (a typo'd key must not silently become a mappable root). Relative
// paths resolve against cwd — e2e convenience; containers pass /mounts/<key>.
const roots = new Map<string, string>();
for (const entry of (process.env.KEAP_FS_ROOTS ?? '').split(',')) {
  const spec = entry.trim();
  if (!spec) continue;
  const eq = spec.indexOf('=');
  const key = eq > 0 ? spec.slice(0, eq).trim() : '';
  const dir = eq > 0 ? spec.slice(eq + 1).trim() : '';
  if (!KEY_RE.test(key) || !dir) {
    console.warn(`[fs-roots] dropping malformed KEAP_FS_ROOTS entry ${JSON.stringify(spec)} (want key=/path, key ~ ${KEY_RE})`);
    continue;
  }
  if (RESERVED_KEYS.has(key)) {
    console.warn(`[fs-roots] dropping reserved root key '${key}' — the per-user tree is not a mappable root`);
    continue;
  }
  if (roots.has(key)) {
    console.warn(`[fs-roots] dropping duplicate root key '${key}'`);
    continue;
  }
  roots.set(key, path.resolve(dir));
}

function isDir(p: string): boolean {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
}

/** All registered roots with a LIVE existence probe (mounts come and go). */
export function listRoots(): FsRoot[] {
  return [...roots.entries()].map(([key, p]) => ({ key, path: p, exists: isDir(p) }));
}

export type FsRootErrorCode =
  | 'unknown-root'
  | 'invalid-path'
  | 'escapes-root'
  | 'not-a-dir'
  | 'conflicts-user-files';

export type ResolveInRootResult =
  | { ok: true; abs: string }
  | { ok: false; error: FsRootErrorCode; message: string };

/**
 * Resolve a '/'-separated relPath ('' = whole root) to an absolute directory
 * inside the root, or a typed error. Containment is checked twice: lexically
 * (refuse '.', '..', dot-prefixed, empty segments and backslashes before any
 * fs call) and physically (the realpath must stay under the root's realpath,
 * so a symlinked alias inside the tree cannot escape it). Callers re-run this
 * on EVERY sync pass — a hand-edited DB row can't escape either.
 */
export function resolveInRoot(rootKey: string, relPath: string): ResolveInRootResult {
  const rootPath = roots.get(rootKey);
  if (!rootPath) return { ok: false, error: 'unknown-root', message: `unknown root '${rootKey}'` };

  const segs = relPath === '' ? [] : relPath.split('/');
  for (const s of segs) {
    if (!s || s === '.' || s === '..' || s.startsWith('.') || s.includes('\\')) {
      return { ok: false, error: 'invalid-path', message: `invalid path '${relPath}'` };
    }
  }

  let rootReal: string;
  try {
    rootReal = realpathSync(rootPath);
  } catch {
    // Unmounted/missing root — the mapping's objects and vectors survive.
    return { ok: false, error: 'not-a-dir', message: `root '${rootKey}' is not mounted at ${rootPath}` };
  }

  // Lazy overlap guard vs EVERY per-user root: equal/ancestor/descendant in
  // either direction would run two sync pipelines over one tree. Checked against
  // all of them, not the first — a second root is exactly where a hand-written
  // mapping is most likely to overlap, and the loop costs one realpath per root.
  for (const usersDir of perUserRoots()) {
    let usersReal: string;
    try {
      usersReal = realpathSync(usersDir);
    } catch {
      continue; // that root is not mounted right now — nothing to conflict with
    }
    if (
      rootReal === usersReal ||
      rootReal.startsWith(usersReal + path.sep) ||
      usersReal.startsWith(rootReal + path.sep)
    ) {
      return {
        ok: false,
        error: 'conflicts-user-files',
        message: `root '${rootKey}' (${rootReal}) overlaps the per-user tree at ${usersReal} — the ` +
          'users pass already mirrors it, and a mapping over it would ingest every file a second time ' +
          'under a mapping-wide visibility',
      };
    }
  }

  let abs: string;
  try {
    abs = realpathSync(path.join(rootReal, ...segs));
  } catch {
    return { ok: false, error: 'not-a-dir', message: `no such directory '${relPath}' under root '${rootKey}'` };
  }
  if (abs !== rootReal && !abs.startsWith(rootReal + path.sep)) {
    return { ok: false, error: 'escapes-root', message: `path '${relPath}' escapes root '${rootKey}'` };
  }
  if (!isDir(abs)) {
    return { ok: false, error: 'not-a-dir', message: `'${relPath}' is not a directory` };
  }
  return { ok: true, abs };
}
