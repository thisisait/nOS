import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/**
 * The `conflicts-user-files` doctrine guard — the one check in `fs-roots.ts`
 * that exists to stop a mapped folder from mirroring the per-user tree a SECOND
 * time, under `fsmap:<id>` ownership and the MAPPING's visibility (`shared` or
 * `public`), where the users-pass prune filter (`source === 'fs'`) can never
 * see the duplicates to clean them up.
 *
 * It had never been exercised. It read `KEAP_USER_FILES_DIR` — a variable the
 * ORGAN never sets (`cortex.plist.j2` sets `CORTEX_FS_USER_ROOTS`, which
 * `aliasFsEnv` maps to `KEAP_FS_USER_ROOTS`) — so the whole branch was dead in
 * this deployment and a root announced over
 * `tenants/<slug>/users` resolved cleanly. That is a silent one-user's-documents
 * -readable-by-everyone failure, so the guard gets a case per root shape.
 *
 * `fs-roots.ts` parses `KEAP_FS_ROOTS` at module LOAD, so every scenario runs
 * through `vi.resetModules()` + a fresh dynamic import — the same reason the
 * fs-sync fixtures spawn a child process per scenario.
 *
 * Fixtures live in a fresh `mkdtemp`. The real user tree is never read, written
 * or resolved by anything here.
 */

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'cortex-fsroots-'));
afterAll(() => fs.rmSync(TMP, { recursive: true, force: true }));

let seq = 0;
function tree(name: string, rel: string[] = []): string {
  const base = path.join(TMP, `${name}-${seq++}`);
  fs.mkdirSync(base, { recursive: true });
  for (const r of rel) fs.mkdirSync(path.join(base, r), { recursive: true });
  return base;
}

const ENV_KEYS = ['KEAP_FS_ROOTS', 'KEAP_USER_FILES_DIR', 'KEAP_FS_USER_ROOTS'] as const;
const saved: Record<string, string | undefined> = {};
beforeEach(() => {
  for (const k of ENV_KEYS) {
    saved[k] = process.env[k];
    delete process.env[k];
  }
  vi.resetModules();
});
afterEach(() => {
  for (const k of ENV_KEYS) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
});

async function resolveWith(env: Record<string, string>, rootKey: string, rel = '') {
  Object.assign(process.env, env);
  const mod = await import('./fs-roots');
  return mod.resolveInRoot(rootKey, rel);
}

describe('conflicts-user-files', () => {
  it('REFUSES a root announced over the per-user tree the ORGAN actually walks', async () => {
    // The deployment shape: the organ is configured through the roots LIST, and
    // never through KEAP_USER_FILES_DIR. This is the case that was silently
    // passing — the guard keyed on a variable that is not set here.
    const users = tree('users', ['pazny/documents']);
    const r = await resolveWith(
      { KEAP_FS_ROOTS: `docs=${users}`, KEAP_FS_USER_ROOTS: `child-dirs=${users}` },
      'docs',
    );
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.error).toBe('conflicts-user-files');
  });

  it('REFUSES a root NESTED inside the per-user tree', async () => {
    const users = tree('users-nested', ['pazny/documents']);
    const r = await resolveWith(
      { KEAP_FS_ROOTS: `docs=${path.join(users, 'pazny')}`, KEAP_FS_USER_ROOTS: `child-dirs=${users}` },
      'docs',
    );
    expect(r.ok === false && r.error).toBe('conflicts-user-files');
  });

  it('REFUSES a root that CONTAINS the per-user tree', async () => {
    const parent = tree('estate', ['tenants/pazny/users/pazny/documents']);
    const r = await resolveWith(
      {
        KEAP_FS_ROOTS: `estate=${parent}`,
        KEAP_FS_USER_ROOTS: `child-dirs=${path.join(parent, 'tenants/pazny/users')}`,
      },
      'estate',
    );
    expect(r.ok === false && r.error).toBe('conflicts-user-files');
  });

  it('checks EVERY root, not just the first — the second is where a mapping overlaps', async () => {
    // `literal:nos-docs` is the self-model tree, which is the SECOND entry in
    // the organ's real configuration. A guard that stopped at roots[0] would
    // let a mapping double-ingest exactly that tree.
    const users = tree('users-two', ['pazny/documents']);
    const shared = tree('shared-two', ['nOS']);
    const r = await resolveWith(
      {
        KEAP_FS_ROOTS: `sm=${shared}`,
        KEAP_FS_USER_ROOTS: `child-dirs=${users},literal:nos-docs=${shared}`,
      },
      'sm',
    );
    expect(r.ok === false && r.error).toBe('conflicts-user-files');
  });

  it('still honours KEAP_USER_FILES_DIR — the single-path shape is one child-dirs root', async () => {
    const users = tree('users-single', ['pazny/documents']);
    const r = await resolveWith({ KEAP_FS_ROOTS: `docs=${users}`, KEAP_USER_FILES_DIR: users }, 'docs');
    expect(r.ok === false && r.error).toBe('conflicts-user-files');
  });

  it('ALLOWS a disjoint root — the guard must not refuse every mapping', async () => {
    const users = tree('users-disjoint', ['pazny/documents']);
    const library = tree('library-disjoint', ['pdf']);
    const r = await resolveWith(
      { KEAP_FS_ROOTS: `lib=${library}`, KEAP_FS_USER_ROOTS: `child-dirs=${users}` },
      'lib',
    );
    expect(r.ok).toBe(true);
  });

  it('ALLOWS a disjoint root whose NAME merely prefixes the users tree', async () => {
    // `/…/users-archive` starts with `/…/users` as a STRING but is a different
    // directory. Containment is per path SEGMENT, and a prefix test without the
    // separator would refuse a legitimate mapping.
    const base = tree('prefix-base', ['users/pazny/documents', 'users-archive/pdf']);
    const r = await resolveWith(
      {
        KEAP_FS_ROOTS: `arch=${path.join(base, 'users-archive')}`,
        KEAP_FS_USER_ROOTS: `child-dirs=${path.join(base, 'users')}`,
      },
      'arch',
    );
    expect(r.ok).toBe(true);
  });

  it('is inert when no per-user root is configured at all', async () => {
    const library = tree('inert', ['pdf']);
    const r = await resolveWith({ KEAP_FS_ROOTS: `lib=${library}` }, 'lib');
    expect(r.ok).toBe(true);
  });
});
