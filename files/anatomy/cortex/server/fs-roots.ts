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
 *   - the overlap check vs KEAP_USER_FILES_DIR (realpath containment, both
 *     directions) runs lazily at resolve time, so a conflicting root degrades
 *     to a typed error, never to double-ingest;
 *   - a root whose path does not exist stays REGISTERED with exists:false — a
 *     mount may appear after boot, and dropping it at parse time would create
 *     a restart-ordering trap.
 */
import { realpathSync, statSync } from 'node:fs';
import path from 'node:path';

const KEY_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;
const RESERVED_KEYS = new Set(['users', 'user-files']);

/** Same env var fs-sync.ts reads — read directly (not imported) so the
 *  dependency stays one-way: fs-sync → fs-roots, never back. */
const USER_FILES_DIR = process.env.KEAP_USER_FILES_DIR ?? '';

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

  // Lazy overlap guard vs the per-user tree: equal/ancestor/descendant in
  // either direction would run two sync pipelines over one tree.
  if (USER_FILES_DIR) {
    try {
      const usersReal = realpathSync(USER_FILES_DIR);
      if (
        rootReal === usersReal ||
        rootReal.startsWith(usersReal + path.sep) ||
        usersReal.startsWith(rootReal + path.sep)
      ) {
        return {
          ok: false,
          error: 'conflicts-user-files',
          message: `root '${rootKey}' conflicts with the per-user tree`,
        };
      }
    } catch {
      /* users dir not present — nothing to conflict with */
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
