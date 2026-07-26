import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { listUserRoots, assertMountSentinel } from './cortex-fs';

/**
 * The gate that actually validates the fs-sync port — S2 §6.4.
 *
 * The nightly diff (§6) measures AGREEMENT between two corpora. It cannot
 * measure CORRECTNESS, because the corpus it runs against is 166 generated
 * self-model cards and ONE real user document: id-set agreement over that is
 * satisfiable tonight and proves almost nothing. Prune, the cap, an EACCES
 * truncation, a visibility flip, a move/rename, two uids — none of them are
 * reachable from one PDF, and every one of them destroys data when it is wrong.
 *
 * So this suite exercises them directly, and it is deliberately NOT a night: it
 * never appears in the 3-night count and it never claims one.
 *
 * ── Hard constraints this file exists inside ────────────────────────────────
 *
 *   - fixtures live in a fresh `mkdtemp`, OUTSIDE `nos_data_root`. The real user
 *     tree ({{ nos_data_root }}/tenants/<slug>/users) is REAL USER DATA and is
 *     never written, moved or deleted by anything here. A prune bug in this
 *     module destroys files that are not ours; that is the whole reason the
 *     prune cases below are written against a throwaway tree first.
 *   - every store is a fresh directory the organ creates itself. KEAP's live
 *     store is never opened, read or copied.
 *
 * ── Why a child process per scenario ────────────────────────────────────────
 *
 * Same structural reason as `cortex-store.test.ts`: `db.ts` holds its connection
 * in module scope and captures its data directory at module LOAD, and
 * `fs-sync.ts` resolves `USER_ROOTS` at module load too. One vitest module graph
 * therefore gets exactly ONE store and ONE roots list, so "the same tree under a
 * different roots config" is not expressible in-process. The CLI below is the
 * same entry point the daemon and Ansible use.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname);
const ORGAN = path.resolve(HERE, '..');
const CLI = path.join(HERE, 'cortex-fs-cli.ts');

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'cortex-fs-'));
afterAll(() => fs.rmSync(TMP, { recursive: true, force: true }));

let seq = 0;
/** A fresh (fixture tree, store dir) pair. Never reused across scenarios. */
function scenario(name: string) {
  const root = path.join(TMP, `${name}-${seq++}`);
  const tree = path.join(root, 'user-files');
  const store = path.join(root, 'store');
  fs.mkdirSync(tree, { recursive: true });
  fs.mkdirSync(store, { recursive: true });
  return { root, tree, store };
}

function write(base: string, rel: string, body: string): string {
  const abs = path.join(base, rel);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, body);
  return abs;
}

interface SyncOut {
  users: {
    scanned: number;
    upserted: number;
    removed: number;
    unchanged: number;
    skipped: number;
    users: string[];
    pruneRefused?: boolean;
    danglingAnchors?: number;
    emptyBodies?: number;
    rootsMissing?: string[];
    rootCollisions?: number;
    perRoot?: Array<{ path: string; spec: string; scanned: number; users: string[] }>;
    sentinel?: string;
  } | null;
  objects: Array<{
    id: string;
    userId: string;
    type: string;
    title: string;
    visibility: string;
    size?: number;
    mtime?: number;
    bodyHash: string | null;
    degradedRead?: boolean;
  }>;
  embeddingsPending: number;
}

function sync(
  store: string,
  env: Record<string, string>,
): { status: number; out: string; result: SyncOut | null } {
  const res = require('node:child_process').spawnSync(
    process.execPath,
    ['--import', 'tsx', CLI, '--json'],
    {
      cwd: ORGAN,
      encoding: 'utf8',
      env: {
        ...process.env,
        CORTEX_STORE_PATH: store,
        // A spine-only store: the self-model generator is irrelevant to fs-sync
        // and shells out to python3 for ~30 s per scenario.
        CORTEX_SELFMODEL: '0',
        ...env,
      },
      maxBuffer: 64 * 1024 * 1024,
    },
  ) as { status: number | null; stdout: string; stderr: string };
  const out = `${res.stdout ?? ''}${res.stderr ?? ''}`;
  const line = out.split('\n').find((l) => l.startsWith('CORTEX_FS_RESULT '));
  return {
    status: res.status ?? -1,
    out,
    result: line ? (JSON.parse(line.slice('CORTEX_FS_RESULT '.length)) as SyncOut) : null,
  };
}

const childDirs = (p: string) => `child-dirs=${p}`;
const literal = (uid: string, p: string) => `literal:${uid}=${p}`;
const idOf = (uid: string, rel: string) =>
  `fs:${uid}:${crypto.createHash('sha1').update(rel).digest('hex').slice(0, 16)}`;

// ---------------------------------------------------------------------------
// The roots list (§1.4) — parsing, and the id equality the whole stage rests on
// ---------------------------------------------------------------------------

describe('roots list', () => {
  const env = (e: Record<string, string>) => e as NodeJS.ProcessEnv;

  it('reads KEAP_USER_FILES_DIR as exactly one child-dirs root (the byte-identical default)', () => {
    const roots = listUserRoots(env({ KEAP_USER_FILES_DIR: '/tmp/users' }));
    expect(roots).toEqual([{ path: '/tmp/users', uid: { kind: 'child-dirs' }, spec: 'child-dirs' }]);
  });

  it('parses both derivations, in order, splitting on the FIRST = so paths may contain one', () => {
    const roots = listUserRoots(
      env({ KEAP_FS_USER_ROOTS: 'child-dirs=/a/users,literal:nos-docs=/b/sh=ared' }),
    );
    expect(roots.map((r) => [r.spec, r.path])).toEqual([
      ['child-dirs', '/a/users'],
      ['literal:nos-docs', '/b/sh=ared'],
    ]);
    expect(roots[1].uid).toEqual({ kind: 'literal', uid: 'nos-docs' });
  });

  it('drops a malformed entry without taking the other root down with it', () => {
    const roots = listUserRoots(env({ KEAP_FS_USER_ROOTS: 'nonsense=/a,child-dirs=/b' }));
    expect(roots.map((r) => r.path)).toEqual(['/b']);
  });

  it('drops a duplicate path — two roots over one tree would double-walk it', () => {
    const roots = listUserRoots(
      env({ KEAP_USER_FILES_DIR: '/a/users', KEAP_FS_USER_ROOTS: 'child-dirs=/a/users' }),
    );
    expect(roots).toHaveLength(1);
  });

  it('is inert with nothing configured', () => {
    expect(listUserRoots(env({}))).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// The mount sentinel (§1.7)
// ---------------------------------------------------------------------------

describe('mount sentinel', () => {
  it("distinguishes 'nobody asked us to check' from 'we checked and it is gone'", () => {
    expect(assertMountSentinel({} as NodeJS.ProcessEnv)).toEqual({ status: 'not-configured' });
  });

  it('REFUSES when the sentinel is absent — a stale empty mountpoint walks cleanly', () => {
    const { root } = scenario('sentinel-absent');
    expect(() =>
      assertMountSentinel({ CORTEX_FS_MOUNT_SENTINEL: path.join(root, '.nos-mount-ok') } as NodeJS.ProcessEnv),
    ).toThrow(/Refusing the fs-sync pass/);
  });

  it('REFUSES a different estate mounted at the same path', () => {
    const { root } = scenario('sentinel-wrong');
    const p = path.join(root, '.nos-mount-ok');
    fs.writeFileSync(p, JSON.stringify({ tenant: 'other', volumeUuid: null, writtenAt: 'x' }));
    expect(() =>
      assertMountSentinel({
        CORTEX_FS_MOUNT_SENTINEL: p,
        CORTEX_FS_TENANT_SLUG: 'pazny',
      } as NodeJS.ProcessEnv),
    ).toThrow(/declares tenant "other"/);
  });

  it('accepts the matching estate, and does NOT gate on age', () => {
    const { root } = scenario('sentinel-ok');
    const p = path.join(root, '.nos-mount-ok');
    fs.writeFileSync(
      p,
      JSON.stringify({ tenant: 'pazny', volumeUuid: 'X', writtenAt: '2020-01-01T00:00:00Z' }),
    );
    const state = assertMountSentinel({
      CORTEX_FS_MOUNT_SENTINEL: p,
      CORTEX_FS_TENANT_SLUG: 'pazny',
    } as NodeJS.ProcessEnv);
    expect(state.status).toBe('ok');
  });

  it('refuses the PASS before any walk — nothing scanned, nothing pruned', () => {
    const { tree, store, root } = scenario('sentinel-pass');
    write(tree, 'alice/documents/a.md', 'hello');
    const r = sync(store, {
      CORTEX_FS_USER_ROOTS: childDirs(tree),
      CORTEX_FS_MOUNT_SENTINEL: path.join(root, 'nope.json'),
    });
    expect(r.status).not.toBe(0);
    expect(r.out).toMatch(/Refusing the fs-sync pass/);
    expect(r.result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The pass itself
// ---------------------------------------------------------------------------

describe('users pass — attribution, composition, ids', () => {
  it('mirrors two uids, scopes each object to its own owner, and derives KEAP ids', () => {
    const { tree, store } = scenario('two-uids');
    write(tree, 'alice/documents/notes.md', '# Alice');
    write(tree, 'bob/library/book.md', '# Bob');
    write(tree, 'bob/agents/scratch.md', 'NOT knowledge');
    const r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.status, r.out).toBe(0);
    expect(r.result!.users!.scanned).toBe(2); // agents/ is not a knowledge class
    expect(r.result!.users!.users.sort()).toEqual(['alice', 'bob']);
    const byId = new Map(r.result!.objects.map((o) => [o.id, o]));
    expect(byId.get(idOf('alice', 'documents/notes.md'))?.userId).toBe('alice');
    expect(byId.get(idOf('bob', 'library/book.md'))?.userId).toBe('bob');
    expect(r.result!.objects).toHaveLength(2);
  });

  it('canonicalises a folder name into the uid the row scope uses', () => {
    const { tree, store } = scenario('canon-uid');
    write(tree, 'Pázny Dev/documents/a.md', 'x');
    const r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.users).toEqual(['pazny-dev']);
  });

  /**
   * THE composition case. `literal:<uid>` must derive the SAME id the container
   * derives through the nested `/user-files/nos-docs` mount — that id equality
   * is the only reason the two corpora can be compared at all (§6.2).
   */
  it('a literal root produces the ids a nested mount would, from a separate tree', () => {
    const { root, tree, store } = scenario('two-roots');
    const shared = path.join(root, 'shared-nos-docs');
    write(tree, 'alice/documents/a.md', 'A');
    write(shared, 'nOS/infra/PostgreSQL.md', '# PostgreSQL');
    const r = sync(store, {
      CORTEX_FS_USER_ROOTS: `${childDirs(tree)},${literal('nos-docs', shared)}`,
      CORTEX_FS_SYNC_DIRS: 'documents,library,inbox,nOS',
    });
    expect(r.status, r.out).toBe(0);
    expect(r.result!.users!.scanned).toBe(2);
    const ids = new Set(r.result!.objects.map((o) => o.id));
    // relPath is 'nOS/infra/PostgreSQL.md' — exactly what the container walks.
    expect(ids.has(idOf('nos-docs', 'nOS/infra/PostgreSQL.md'))).toBe(true);
    expect(r.result!.users!.perRoot!.map((p) => [p.spec, p.scanned])).toEqual([
      ['child-dirs', 1],
      ['literal:nos-docs', 1],
    ]);
  });

  it('flips visibility to shared for a reserved uid, and back, exactly once', () => {
    const { root, tree, store } = scenario('visibility');
    const shared = path.join(root, 'shared');
    write(shared, 'nOS/x.md', 'x');
    const roots = literal('nos-docs', shared);
    const dirs = 'documents,library,inbox,nOS';
    let r = sync(store, { CORTEX_FS_USER_ROOTS: roots, CORTEX_FS_SYNC_DIRS: dirs });
    expect(r.result!.objects[0].visibility).toBe('private');

    r = sync(store, {
      CORTEX_FS_USER_ROOTS: roots,
      CORTEX_FS_SYNC_DIRS: dirs,
      CORTEX_FS_SHARED_UIDS: 'nos-docs',
    });
    // Visibility is part of the skip key: the flip propagates to an ALREADY
    // mirrored file (size+mtime alone would skip it forever) …
    expect(r.result!.users!.upserted).toBe(1);
    expect(r.result!.objects[0].visibility).toBe('shared');

    r = sync(store, {
      CORTEX_FS_USER_ROOTS: roots,
      CORTEX_FS_SYNC_DIRS: dirs,
      CORTEX_FS_SHARED_UIDS: 'nos-docs',
    });
    expect(r.result!.users!.upserted).toBe(0); // … and exactly once.
    expect(r.result!.users!.unchanged).toBe(1);
  });

  it('honours frontmatter type/title, CRLF and the strict-parse rule', () => {
    const { tree, store } = scenario('frontmatter');
    write(tree, 'a/documents/typed.md', '---\ntype: skill\ntitle: A Skill\n---\nbody\n');
    write(tree, 'a/documents/crlf.md', '---\r\ntype: hint\r\ntitle: CRLF\r\n---\r\nbody\r\n');
    // Opens with a horizontal rule, not frontmatter: the whole thing is body,
    // and the title falls back to the basename.
    write(tree, 'a/documents/rule.md', '---\nnot a key line\n---\nmore\n');
    const r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    const by = new Map(r.result!.objects.map((o) => [o.title, o]));
    expect(by.get('A Skill')?.type).toBe('skill');
    expect(by.get('CRLF')?.type).toBe('hint');
    expect(by.get('rule.md')?.type).toBe('page');
  });

  it('counts a dangling [[node]] anchor rather than dropping it silently', () => {
    const { tree, store } = scenario('dangling');
    write(tree, 'a/documents/anchored.md', 'see [[no.such.node]]');
    const r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.danglingAnchors).toBe(1);
  });

  it('caps the stored body at BODY_CAP without failing the file', () => {
    const { tree, store } = scenario('bodycap');
    write(tree, 'a/documents/big.md', 'x'.repeat(20000));
    const r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.upserted).toBe(1);
    expect(r.result!.users!.emptyBodies).toBeUndefined();
  });
});

describe('users pass — the destructive paths', () => {
  it('prunes an object whose file is gone, when the found-set is trustworthy', () => {
    const { tree, store } = scenario('prune');
    write(tree, 'a/documents/keep.md', 'k');
    const gone = write(tree, 'a/documents/gone.md', 'g');
    let r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.upserted).toBe(2);

    fs.rmSync(gone);
    r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.removed).toBe(1);
    expect(r.result!.users!.pruneRefused).toBeFalsy();
    expect(r.result!.objects.map((o) => o.title)).toEqual(['keep.md']);
  });

  it('a move/rename is a delete+create — new id, old id pruned', () => {
    const { tree, store } = scenario('move');
    write(tree, 'a/documents/old.md', 'same bytes');
    let r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.objects[0].id).toBe(idOf('a', 'documents/old.md'));

    fs.renameSync(path.join(tree, 'a/documents/old.md'), path.join(tree, 'a/documents/new.md'));
    r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.removed).toBe(1);
    expect(r.result!.users!.upserted).toBe(1);
    expect(r.result!.objects.map((o) => o.id)).toEqual([idOf('a', 'documents/new.md')]);
  });

  /**
   * THE guard this corpus shape needs most. 166 of 167 objects belong to ONE
   * uid, so the GLOBAL zero-scan guard is far too coarse: one file in any other
   * tree keeps `found.length > 0` and the whole self-model would be pruned while
   * that guard stayed silent.
   */
  it('holds back a uid that contributed 0 files while another uid still has some', () => {
    const { tree, store } = scenario('per-uid-zero');
    write(tree, 'alice/documents/a.md', 'A');
    write(tree, 'bob/documents/b.md', 'B');
    let r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.objects).toHaveLength(2);

    fs.rmSync(path.join(tree, 'bob/documents'), { recursive: true });
    r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.removed).toBe(0);
    expect(r.result!.users!.pruneRefused).toBe(true);
    expect(r.result!.objects).toHaveLength(2); // bob's mirror survives
  });

  it('refuses to prune when the walk hit the file cap — a truncated found-set is unproven', () => {
    const { tree, store } = scenario('cap');
    write(tree, 'a/documents/one.md', '1');
    write(tree, 'a/documents/two.md', '2');
    write(tree, 'a/documents/three.md', '3');
    let r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.objects).toHaveLength(3);

    // Cap below the tree size: the walk stops early, so every unseen mirror is
    // UNPROVEN rather than absent — including the two files still on disk.
    r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree), CORTEX_FS_MAX_FILES: '1' });
    expect(r.result!.users!.scanned).toBe(1);
    expect(r.result!.users!.skipped).toBe(-1); // the capped sentinel
    expect(r.result!.users!.pruneRefused).toBe(true);
    expect(r.result!.users!.removed).toBe(0);
    expect(r.result!.objects).toHaveLength(3);
  });

  it('refuses to prune when the whole tree scans zero while mirrors exist', () => {
    const { tree, store } = scenario('zero-scan');
    write(tree, 'a/documents/a.md', 'A');
    sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });

    fs.rmSync(path.join(tree, 'a'), { recursive: true });
    const r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.scanned).toBe(0);
    expect(r.result!.users!.removed).toBe(0);
    expect(r.result!.users!.pruneRefused).toBe(true);
    expect(r.result!.objects).toHaveLength(1);
  });

  it('treats an ABSENT root as truncation, not as an empty tree', () => {
    const { root, tree, store } = scenario('root-absent');
    const shared = path.join(root, 'shared');
    write(tree, 'a/documents/a.md', 'A');
    write(shared, 'nOS/x.md', 'x');
    const roots = `${childDirs(tree)},${literal('nos-docs', shared)}`;
    const dirs = 'documents,library,inbox,nOS';
    let r = sync(store, { CORTEX_FS_USER_ROOTS: roots, CORTEX_FS_SYNC_DIRS: dirs });
    expect(r.result!.objects).toHaveLength(2);

    fs.rmSync(shared, { recursive: true });
    r = sync(store, { CORTEX_FS_USER_ROOTS: roots, CORTEX_FS_SYNC_DIRS: dirs });
    expect(r.result!.users!.rootsMissing).toEqual([shared]);
    expect(r.result!.users!.pruneRefused).toBe(true);
    expect(r.result!.users!.removed).toBe(0);
    expect(r.result!.objects).toHaveLength(2); // the shared mirror survives
  });

  it('refuses to prune when a walk was truncated by an unreadable subtree (EACCES)', () => {
    const { tree, store } = scenario('eacces');
    write(tree, 'a/documents/keep.md', 'k');
    write(tree, 'a/documents/sub/deep.md', 'd');
    let r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.objects).toHaveLength(2);

    const sub = path.join(tree, 'a/documents/sub');
    fs.chmodSync(sub, 0o000);
    try {
      r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
      expect(r.result!.users!.pruneRefused).toBe(true);
      expect(r.result!.users!.removed).toBe(0);
      expect(r.result!.objects).toHaveLength(2);
    } finally {
      fs.chmodSync(sub, 0o755);
    }
  });

  it('a body that will not read keeps the previous body and retries next pass', () => {
    const { tree, store } = scenario('degraded');
    const abs = write(tree, 'a/documents/x.md', 'real content');
    let r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    const hash = r.result!.objects[0].bodyHash;
    expect(hash).toBeTruthy();

    // The VirtioFS shape: the directory still enumerates a non-zero size, the
    // body reads back as nothing. Reproduced here by making the file unreadable
    // (the throw branch) — same observable, no bind mount required. The mtime
    // bump is what makes the pass LOOK at the file at all: chmod moves ctime,
    // not mtime, so without it the skip key still matches and the degraded read
    // never happens — which is itself the correct behaviour, and the reason a
    // degraded pass must withhold the mtime rather than stamp it.
    fs.chmodSync(abs, 0o000);
    const later = new Date(Date.now() + 2000);
    fs.utimesSync(abs, later, later);
    try {
      r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
      expect(r.result!.users!.emptyBodies).toBe(1);
      const o = r.result!.objects[0];
      expect(o.bodyHash).toBe(hash); // NOT clobbered
      expect(o.degradedRead).toBe(true);
      expect(o.mtime).toBe(0); // withheld → the next pass retries
    } finally {
      fs.chmodSync(abs, 0o644);
    }
    r = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(r.result!.users!.emptyBodies).toBeUndefined();
    expect(r.result!.objects[0].degradedRead).toBeUndefined();
    expect(r.result!.objects[0].bodyHash).toBe(hash);
  });
});

describe('the embedding diff sees the mirror', () => {
  it('a mirrored object becomes a pending embedding', () => {
    const { tree, store } = scenario('pending');
    write(tree, 'a/documents/a.md', 'A');
    const before = sync(store, { CORTEX_FS_USER_ROOTS: '' });
    write(tree, 'a/documents/b.md', 'B');
    const after = sync(store, { CORTEX_FS_USER_ROOTS: childDirs(tree) });
    expect(after.result!.embeddingsPending).toBeGreaterThan(before.result!.embeddingsPending);
  });
});

afterEach(() => {
  /* each scenario owns its own tmpdir; nothing shared to reset */
});

beforeAll(() => {
  // Fail loudly rather than silently walking someone's real tree.
  expect(TMP.startsWith(os.tmpdir())).toBe(true);
});
