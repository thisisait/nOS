/**
 * The Cortex organ's filesystem seam — LOCALLY AUTHORED (not a port).
 * S2 step 2 + step 3 (`docs/plans/cortex-corpus-parallel.md` §1.4, §1.7).
 *
 * Two things live here, and they are the only two things `server/fs-sync.ts`
 * needed that KEAP's copy does not have. Everything else in that file is the
 * ported pass, unchanged.
 *
 * ── 1. The roots list: making a compose file's composition visible in code ───
 *
 * In KEAP, `KEAP_USER_FILES_DIR` is a single path and `/user-files` is TWO host
 * trees stacked at it by the compose file:
 *
 *   {{ nos_data_root }}/tenants/<slug>/users        -> /user-files
 *   {{ keap_selfmodel_root }}                       -> /user-files/nos-docs  :ro
 *
 * The organ has no compose file, so that composition has to become explicit or
 * it is simply lost. It is expressed as an ORDERED LIST of roots, each declaring
 * how uids are derived from it:
 *
 *   child-dirs      today's behaviour verbatim — iterate the root's top-level
 *                   directories, `canonicalUid(name)` each one
 *   literal:<uid>   walk the root as if it WERE one uid's directory
 *
 * Both shapes then hit the same `walkUser`, produce the same `relPath`, and
 * therefore the same `fs:<uid>:<sha1(relPath)[:16]>` ids the container derives
 * through the nested mount. That id equality is the whole point: it is what
 * makes the two corpora comparable at all (§6.2).
 *
 * Two mechanisms were rejected, and the first is worth writing down because it
 * fails SILENTLY:
 *
 *   - a symlink farm (`run/user-files/nos-docs -> …/shared/nos-docs`).
 *     `syncUserFiles` does `lstatSync(userDir)` then `if (!st?.isDirectory())
 *     continue` — an lstat on a symlink reports `isDirectory() === false`, so
 *     the uid is skipped; and `walkDir` skips symlinks outright by doctrine
 *     (realpath ∈ scope). No error, no log: the entire 166-object self-model
 *     would just be absent, and the per-uid prune guard would then hold its
 *     mirrors back forever, so the failure would read as permanent staleness
 *     rather than as a fault.
 *   - a host bind mount. macOS has none without macFUSE/bindfs; the Linux form
 *     needs root. A new dependency and a privilege escalation, for a daemon that
 *     runs as the operator.
 *
 * This module is deliberately UPSTREAMABLE: it reads `KEAP_*` env names and
 * knows nothing about the cortex organ, so it can move into KEAP as-is and take
 * `fs-sync.ts`'s small diff with it. `CORTEX_FS_*` are aliased onto the `KEAP_*`
 * names by `aliasFsEnv()` below, exactly as `index.ts` already does for tokens.
 *
 * ── 2. The mount sentinel: not walking an unmounted disk ─────────────────────
 *
 * `nos_data_root` is `/Volumes/SSD1TB/nOS/data` — a REMOVABLE volume. The
 * existing `tasks/stacks/docker-external-mount-preflight.yml` probes the Docker
 * VM's ability to bind that path; a host daemon goes nowhere near it, and there
 * is no host-side assertion at all today.
 *
 * fs-sync's five prune guards are correct and are all kept, but they are all
 * REACTIVE — they notice, after the walk, that the found-set cannot be trusted.
 * The sentinel is the other half: correctness should not rest on a guard
 * reacting to an unmounted disk when it can rest on never walking one. A
 * directory can also survive an eject as a stale EMPTY MOUNTPOINT, which a
 * `find` cannot distinguish from a genuinely empty tree and a sentinel can.
 *
 * The sentinel is written by the converge at `{{ nos_data_root }}/.nos-mount-ok`
 * — at `nos_data_root`, NOT inside `tenants/<slug>/users`, because the user tree
 * is real user data and nothing here may write to it.
 */
import fs from 'node:fs';
import path from 'node:path';

// ── 1. The roots list ────────────────────────────────────────────────────────

/** How a root's top level maps onto owner uids. */
export type UidDerivation =
  /** Iterate the root's top-level directories; `canonicalUid(name)` each. */
  | { kind: 'child-dirs' }
  /** Walk the root as one uid's own directory. */
  | { kind: 'literal'; uid: string };

export interface UserRoot {
  /** Absolute host path. */
  path: string;
  uid: UidDerivation;
  /** `child-dirs` / `literal:<uid>` — the spec as written, for reports. */
  spec: string;
}

function parseDerivation(raw: string): UidDerivation | null {
  if (raw === 'child-dirs') return { kind: 'child-dirs' };
  if (raw.startsWith('literal:')) {
    const uid = raw.slice('literal:'.length).trim();
    return uid ? { kind: 'literal', uid } : null;
  }
  return null;
}

/**
 * Resolve the ordered roots list.
 *
 * `KEAP_FS_USER_ROOTS` is a comma-separated list of `<derivation>=<path>`:
 *
 *   child-dirs=/Volumes/SSD1TB/nOS/data/tenants/pazny/users,\
 *   literal:nos-docs=/Volumes/SSD1TB/nOS/data/tenants/pazny/shared/nos-docs
 *
 * Split on the FIRST '=' only, so a path containing '=' survives; a derivation
 * never contains one.
 *
 * `KEAP_USER_FILES_DIR` (KEAP's single-path var) still works and is equivalent
 * to one `child-dirs` root — that is the byte-identical default, and it is what
 * keeps this module a strict generalisation rather than a replacement.
 *
 * A malformed entry is DROPPED WITH A WARNING rather than silently ignored,
 * mirroring `fs-roots.ts`'s treatment of a malformed `KEAP_FS_ROOTS` entry. It
 * is not fatal here because a typo in one root must not take the other root's
 * corpus down with it — but the absence of a configured root IS surfaced as
 * data by the pass itself (`rootsMissing`), because absence is not emptiness.
 */
export function listUserRoots(env: NodeJS.ProcessEnv = process.env): UserRoot[] {
  const out: UserRoot[] = [];
  const seen = new Set<string>();
  const push = (p: string, uid: UidDerivation, spec: string) => {
    const abs = path.resolve(p);
    if (seen.has(abs)) {
      console.warn(`[fs-sync] dropping duplicate user root ${JSON.stringify(abs)}`);
      return;
    }
    seen.add(abs);
    out.push({ path: abs, uid, spec });
  };

  const single = env.KEAP_USER_FILES_DIR?.trim();
  if (single) push(single, { kind: 'child-dirs' }, 'child-dirs');

  for (const entry of (env.KEAP_FS_USER_ROOTS ?? '').split(',')) {
    const spec = entry.trim();
    if (!spec) continue;
    const eq = spec.indexOf('=');
    const derivation = eq > 0 ? parseDerivation(spec.slice(0, eq).trim()) : null;
    const dir = eq > 0 ? spec.slice(eq + 1).trim() : '';
    if (!derivation || !dir) {
      console.warn(
        `[fs-sync] dropping malformed KEAP_FS_USER_ROOTS entry ${JSON.stringify(spec)} ` +
          '(want child-dirs=/path or literal:<uid>=/path)',
      );
      continue;
    }
    push(dir, derivation, spec.slice(0, eq).trim());
  }
  return out;
}

/**
 * Map the `CORTEX_FS_*` deployment vocabulary onto the `KEAP_*` names the
 * ported modules read, BEFORE they are imported.
 *
 * Same seam, same reason and same one-way flow as `index.ts::aliasTokenEnv`:
 * the ported files stay byte-identical (or, for `fs-sync.ts`, carry only the
 * marked upstreamable diff), and the organ's own variable names are the ones
 * `roles/pazny.cortex` owns. The CORTEX_* name wins when both are set.
 *
 * `KEAP_FS_SHARED_UIDS` has no CORTEX_* alias on purpose: it is not a path, it
 * is the visibility rule, and it must be the SAME value on both sides or the
 * two corpora disagree on `visibility` for the whole self-model — which is a
 * comparison the diff harness would then report as a real difference. Set it
 * identically from one Ansible variable.
 */
export function aliasFsEnv(env: NodeJS.ProcessEnv): void {
  if (env.CORTEX_FS_USER_ROOTS?.trim()) env.KEAP_FS_USER_ROOTS = env.CORTEX_FS_USER_ROOTS;
  if (env.CORTEX_FS_SYNC_DIRS?.trim()) env.KEAP_FS_SYNC_DIRS = env.CORTEX_FS_SYNC_DIRS;
  if (env.CORTEX_FS_SHARED_UIDS?.trim()) env.KEAP_FS_SHARED_UIDS = env.CORTEX_FS_SHARED_UIDS;
  if (env.CORTEX_FS_SYNC_INTERVAL_S?.trim()) env.KEAP_FS_SYNC_INTERVAL_S = env.CORTEX_FS_SYNC_INTERVAL_S;
  if (env.CORTEX_FS_MAX_FILES?.trim()) env.KEAP_FS_MAX_FILES = env.CORTEX_FS_MAX_FILES;
}

// ── 2. The mount sentinel ────────────────────────────────────────────────────

export interface MountSentinel {
  /** Tenant slug the converge wrote. Must equal the organ's expected slug. */
  tenant: string;
  /** Volume UUID (`diskutil info -plist`), or null on a non-removable root. */
  volumeUuid: string | null;
  /** Converge timestamp, ISO 8601. Recorded, never asserted on — a stale
   *  sentinel on a mounted volume is a stale converge, not an unmounted disk. */
  writtenAt: string;
  /** The `nos_data_root` the converge believed it was writing into. */
  dataRoot?: string;
}

export type SentinelState =
  | { status: 'ok'; path: string; sentinel: MountSentinel }
  /** No sentinel path configured — the organ is not reading a removable tree
   *  (a fixture run, a CI box). DISTINCT from 'missing': one is "we were never
   *  asked to check", the other is "we checked and the disk is not there". */
  | { status: 'not-configured' };

/**
 * Assert the sentinel, or THROW.
 *
 * Throwing rather than returning a flag is the same rule `cortex-store.ts`
 * applies to a materialise that produces nothing: a pass that cannot prove it
 * is looking at the right disk must not produce a result at all, because a
 * result with `scanned: 0` is indistinguishable — to every consumer downstream —
 * from a genuinely empty tree. The five prune guards then never get the chance
 * to be the last line of defence, which is exactly the ordering S0 asked for.
 *
 * What is checked, and what deliberately is not:
 *
 *   present   the file exists and parses. A stale EMPTY MOUNTPOINT left behind
 *             by an eject has no sentinel in it, which is the case a `find`
 *             cannot tell from an empty tree.
 *   tenant    equals `CORTEX_FS_TENANT_SLUG`. This is the check that catches
 *             the genuinely dangerous mistake: a DIFFERENT volume mounted at
 *             the same path. Same path, real sentinel, wrong estate — and every
 *             uid in the corpus would be pruned as absent.
 *   age       NOT checked. A converge that has not run for a month is not a
 *             reason to refuse to read a mounted disk, and a timestamp gate here
 *             would turn "nobody converged" into "the corpus vanished".
 */
export function assertMountSentinel(env: NodeJS.ProcessEnv = process.env): SentinelState {
  const sentinelPath = env.CORTEX_FS_MOUNT_SENTINEL?.trim();
  if (!sentinelPath) return { status: 'not-configured' };

  let raw: string;
  try {
    raw = fs.readFileSync(sentinelPath, 'utf8');
  } catch (err) {
    throw new Error(
      `Refusing the fs-sync pass: the mount sentinel ${sentinelPath} could not be read (${String(err)}).\n` +
        'The tree the organ mirrors lives on a REMOVABLE volume, and an unmounted volume presents as an\n' +
        'empty (or stale, empty-mountpoint) directory — which walks cleanly, scans 0 files, and would\n' +
        'leave the prune guards as the only thing between a transient eject and the loss of every mirror\n' +
        'plus its vectors. Nothing has been walked and nothing has been pruned.\n' +
        'Mount the volume and re-run, or unset CORTEX_FS_MOUNT_SENTINEL for a tree that is not removable.',
    );
  }

  let sentinel: MountSentinel;
  try {
    sentinel = JSON.parse(raw) as MountSentinel;
  } catch {
    throw new Error(
      `Refusing the fs-sync pass: the mount sentinel ${sentinelPath} exists but is not JSON, so it ` +
        'proves nothing about which volume is mounted here.',
    );
  }

  const expected = env.CORTEX_FS_TENANT_SLUG?.trim();
  if (expected && sentinel.tenant !== expected) {
    throw new Error(
      `Refusing the fs-sync pass: mount sentinel ${sentinelPath} declares tenant ` +
        `${JSON.stringify(sentinel.tenant)} but this organ is configured for ${JSON.stringify(expected)}.\n` +
        'A DIFFERENT volume is mounted at this path. Walking it would find none of this estate\'s uids and\n' +
        'would read as a mass delete — the one failure the per-uid guard cannot distinguish from a genuinely\n' +
        'emptied tree, because every uid would be missing at once.',
    );
  }

  return { status: 'ok', path: sentinelPath, sentinel };
}
