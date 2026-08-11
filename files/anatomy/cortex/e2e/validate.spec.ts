import { test, expect } from '@playwright/test';

/**
 * PORTED from KEAP v1.27.0 `e2e/validate.spec.ts`. Build sequence step 8.
 *
 * POST /agent/v1/validate — the Cortex typechecker, end to end against the
 * BUILT server (dist-server/index.js), which is the only place the whole chain
 * is real: the boot-time FTS rebuild that late binding queries, the seeded verb
 * vocabulary, the live database identity stamped into every AST, and the
 * esbuild bundle itself.
 *
 * What this spec proves that the unit suite cannot:
 *  - the route is mounted, authenticated at RO scope, and speaks the
 *    {success, data} envelope;
 *  - a typed error report arrives as DATA inside a 200, while a malformed
 *    REQUEST is a transport 400 — the two are different failures and the
 *    surface must not conflate them;
 *  - the deferred (db:/svc:/doc:) contract Wing consumes survives the bundle;
 *  - `ast.binding` agrees with the two live surfaces it is supposed to pin
 *    (`/agent/v1/health` and `/agent/v1/validate/opcodes`), which is the drift
 *    check the whole TTL design rests on.
 *
 * STATELESS BY CONSTRUCTION. This spec seeds nothing and cleans nothing up —
 * `validate` has zero side effects, so there is nothing to clean.
 *
 * ── The FOUR deviations from KEAP's copy, and why ───────────────────────────
 *
 * Everything else is the KEAP file unchanged, deliberately: this suite is a
 * cross-implementation gate, and an assertion that was reworded while being
 * moved stops being evidence that both sides answer the same.
 *
 *  1. The `selfmodel` contract assertion is gone (test 10). KEAP's health
 *     declares `contracts: {selfmodel: 1, cortex: 1}`; the organ declares
 *     `{cortex: 1}` only. The organ does not implement the slug-tree contract —
 *     no `/agent/v1/objects`, no corpus — and declaring a contract you do not
 *     serve is worse than declaring nothing. The replacement asserts the
 *     ABSENCE, so the day someone adds `selfmodel` to the organ's health this
 *     test is what asks whether the surface behind it moved too.
 *  2. That same test's census note about KEAP's e2e is dropped with it.
 *  3. Test 9 gains three lines: `ast.binding` is compared against `/health`'s
 *     new `binding` block as well as against KEAP's nested `ontology.version`.
 *     The block is the organ's addition (design step 12 asks `/health` to carry
 *     all three axes); asserting the two agree is what stops it becoming a
 *     second, drifting copy of the same three facts.
 *  4. `expect(binding.ontologyVersion).toBe('onto1:76d1f3ad728b382b')` is added
 *     beside the shape check. The suite boots an unmaterialised store, which is
 *     exactly the input state the step-5 hard gate pins, so the literal is
 *     available here and the regex alone would not notice a digest that changed.
 *
 * The boot-order and fail-closed properties are NOT here; they need a second
 * process and live in e2e/organ-boot.spec.ts.
 */
test.describe.configure({ mode: 'serial' });

const RO = { Authorization: 'Bearer e2e-ro', 'Content-Type': 'application/json' };

/** The digest of the fresh, unmaterialised spine — build sequence step 5. */
const PINNED_ONTOLOGY_VERSION = 'onto1:76d1f3ad728b382b';

type Issue = {
  code: string;
  severity: string;
  stage: number | null;
  offset: number | null;
  detail: Record<string, unknown>;
};
type Report = {
  valid: boolean;
  phase: number;
  complete: boolean;
  scope: { model: string; authorizes: boolean; resolved: string[]; unresolved: string[]; deferred: string[] };
  ast: {
    astVersion: number;
    source: string;
    pipeline: {
      source: string | null;
      stages: Array<{
        index: number;
        opcode: string;
        mutating: boolean;
        operands: Array<Record<string, unknown>>;
        params: Record<string, { value: unknown; defaulted: boolean }>;
        effective: Record<string, boolean>;
      }>;
    };
    deferred: Array<{ stage: number; operand: number; ns: string }>;
    binding: {
      ontologyVersion: string;
      databaseId: string;
      opcodeRegistryHash: string;
      validatedAt: string;
      expiresAt: string;
      ttlSeconds: number;
    };
  } | null;
  errors: Issue[];
  warnings: Issue[];
};

async function validate(
  request: import('@playwright/test').APIRequestContext,
  body: unknown,
): Promise<Report> {
  const res = await request.post('/agent/v1/validate', { headers: RO, data: body });
  expect(res.status()).toBe(200);
  const json = (await res.json()) as { success: boolean; data: Report };
  expect(json.success).toBe(true);
  return json.data;
}

test.describe('cortex validate', () => {
  test('requires a bearer token', async ({ request }) => {
    const noTok = await request.post('/agent/v1/validate', {
      headers: { 'Content-Type': 'application/json' },
      data: { source: '@input | classify(tax:01.01)' },
    });
    expect(noTok.status()).toBe(401);

    // RO is sufficient: the endpoint has zero side effects, and demanding a
    // write token to typecheck would force the executor to hold write
    // credentials for a read operation.
    const roTok = await request.post('/agent/v1/validate', {
      headers: RO,
      data: { source: '@input | classify(tax:01.01)' },
    });
    expect(roTok.status()).toBe(200);
  });

  test('a valid program returns a resolved AST that carries both surface and id', async ({ request }) => {
    const report = await validate(request, { source: '@input | classify(tax:01.01)' });
    expect(report.valid).toBe(true);
    expect(report.phase).toBe(1);
    expect(report.complete).toBe(true);
    expect(report.errors).toEqual([]);
    expect(report.warnings).toEqual([]);

    const stage = report.ast!.pipeline.stages[0];
    expect(stage.opcode).toBe('classify');
    expect(stage.mutating).toBe(false);
    expect(stage.operands[0]).toMatchObject({
      ns: 'tax',
      kind: 'resolved',
      binding: 'exact',
      surface: '01.01',
      id: '01.01',
      resolvedName: 'Physics',
    });
    // `valid` is a statement about meaning, never about permission.
    expect(report.scope.authorizes).toBe(false);
    expect(report.scope.model).toBe('system-ontology');
  });

  test('late binding resolves against the LIVE index the server built at boot', async ({ request }) => {
    const report = await validate(request, { source: '@input | classify(tax:node[Kinematics])' });
    expect(report.valid).toBe(true);
    expect(report.ast!.pipeline.stages[0].operands[0]).toMatchObject({
      binding: 'late',
      scopeHint: 'node',
      surface: 'Kinematics',
      id: '01.01.01.01',
      resolvedName: 'Kinematics',
    });
  });

  test('a comparable-score multimatch is refused with candidates — the validator does not choose', async ({
    request,
  }) => {
    const report = await validate(request, { source: '@input | classify(tax:node[motion])' });
    expect(report.valid).toBe(false);
    expect(report.ast).toBeNull();
    expect(report.errors.map((e) => e.code)).toEqual(['ambiguous_operand']);

    const detail = report.errors[0].detail as {
      surface: string;
      candidates: Array<Record<string, unknown>>;
    };
    expect(detail.surface).toBe('motion');
    expect(detail.candidates.length).toBeGreaterThanOrEqual(2);
    for (const candidate of detail.candidates) {
      expect(Object.keys(candidate).sort()).toEqual(['id', 'name', 'path']);
    }
  });

  test('typed error report: a bad program is DATA inside a 200, a bad request is a 400', async ({
    request,
  }) => {
    // The typed-error case — an unknown opcode, reported with a position and a
    // repair hint drawn only from the published registry.
    const report = await validate(request, { source: '@input | frobnicate(tax:01)' });
    expect(report.valid).toBe(false);
    expect(report.ast).toBeNull();
    expect(report.errors).toHaveLength(1);
    expect(report.errors[0]).toMatchObject({ code: 'unknown_opcode', severity: 'error', stage: 0 });
    expect(report.errors[0].detail).toEqual({ opcode: 'frobnicate', didYouMean: [] });

    // A parse failure is the SOLE entry, positioned, and never repaired.
    const syntax = await validate(request, { source: '@input.map(tax:01.01)' });
    expect(syntax.errors.map((e) => e.code)).toEqual(['syntax_error']);
    expect(syntax.errors[0].offset).toBe(6);

    // The envelope, by contrast, is a transport error.
    const bad = await request.post('/agent/v1/validate', { headers: RO, data: { ttlSeconds: 900 } });
    expect(bad.status()).toBe(400);
    expect((await bad.json()).success).toBe(false);
  });

  test('an unparseable BODY is the envelope too — not express HTML, and never a stack', async ({
    request,
  }) => {
    // A body-parser SyntaxError is an ERROR, not a response: it skips every
    // ordinary handler and lands in express's built-in finalhandler, which
    // answers text/html with `err.stack` inlined whenever NODE_ENV is not
    // 'production' — and nothing in this organ's deployment sets NODE_ENV. The
    // reply used to be ten stack frames carrying absolute host paths
    // (…/node_modules/body-parser/lib/types/json.js:96:19), which is both a
    // disclosure and a straight contradiction of the 404 handler's stated
    // contract that everything is answered in the {success,error} envelope.
    for (const body of ['{"source": ', '{"source": "@input",}', 'not json at all']) {
      const res = await request.post('/agent/v1/validate', { headers: RO, data: body });
      expect(res.status(), body).toBe(400);
      expect(res.headers()['content-type'], body).toContain('application/json');
      const text = await res.text();
      expect(text).not.toContain('SyntaxError');
      expect(text).not.toContain('node_modules');
      expect(text).not.toContain('    at ');
      const json = JSON.parse(text) as { success: boolean; error: string };
      expect(json.success).toBe(false);
      expect(json.error).toContain('malformed request');
    }

    // The 2 MB TRANSPORT ceiling answers in the envelope as well. It is a
    // different limit from §3.6's 4096-char program cap, which is a typed
    // `program_too_large` entry inside a 200 — see the parser's own note in
    // server/index.ts. This asserts the transport half.
    const huge = await request.post('/agent/v1/validate', {
      headers: RO,
      data: JSON.stringify({ source: 'x'.repeat(3 * 1024 * 1024) }),
    });
    expect(huge.status()).toBe(413);
    const hugeJson = (await huge.json()) as { success: boolean; error: string };
    expect(hugeJson.success).toBe(false);
    expect(hugeJson.error).toContain('entity.too.large');
  });

  test('kg:/ent: return a constant refusal that is independent of the operand', async ({ request }) => {
    const a = await validate(request, { source: '@input | get(kg:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee)' });
    const b = await validate(request, { source: '@input | get(kg:11111111-2222-3333-4444-555555555555)' });
    expect(a.errors.map((e) => e.code)).toEqual(['namespace_not_resolvable']);
    expect(a.errors[0].detail).toEqual({ ns: 'kg', scope: 'system-ontology' });
    // Byte-identical: `detail` contains no operand text at all, so the error
    // cannot report anything about whether that object exists.
    expect(JSON.stringify(a.errors)).toBe(JSON.stringify(b.errors));

    const ent = await validate(request, { source: '@input | map(ent:product[červené tričko L])' });
    expect(ent.errors[0].detail).toEqual({ ns: 'ent', scope: 'system-ontology' });
    expect(a.scope.unresolved).toEqual(['kg', 'ent']);
  });

  test('deferred namespaces: valid, not complete, indexed for Wing, never resolved here', async ({
    request,
  }) => {
    const report = await validate(request, {
      source: '@input | insert(db:products, ?hidden=true, dry_run=true)',
    });
    // A program full of db: operands is a CORRECT phase-1 result, not a failure.
    expect(report.valid).toBe(true);
    expect(report.complete).toBe(false);
    expect(report.errors).toEqual([]);

    const operand = report.ast!.pipeline.stages[0].operands[0];
    expect(operand).toMatchObject({ ns: 'db', kind: 'deferred', surface: 'products', id: null, resolvedName: null });
    expect(report.ast!.deferred).toEqual([{ stage: 0, operand: 0, ns: 'db' }]);
    expect(report.warnings.map((w) => w.code).sort()).toEqual(['deferred_namespace', 'deferred_program']);
    for (const warning of report.warnings) expect(warning.severity).toBe('info');

    // `?hidden=true` is a column of a table the validator is forbidden to know
    // about: it is recorded verbatim for Wing, with the `?` form preserved, not
    // flattened.
    expect(report.ast!.pipeline.stages[0].params.hidden).toMatchObject({ value: true, defaulted: true });
    expect(report.ast!.pipeline.stages[0].params.dry_run).toMatchObject({ value: true, defaulted: false });
    expect(report.ast!.pipeline.stages[0].effective).toEqual({ dry_run: true });

    // And the same namespace in a non-accepting slot is still a typed error —
    // the ONE semantic statement made about a deferred operand is about the
    // OPCODE, not the resource.
    const wrongSlot = await validate(request, { source: '@input | classify(db:products)' });
    expect(wrongSlot.errors.map((e) => e.code)).toEqual(['namespace_not_accepted']);
  });

  test('a mutating stage without an explicit gate reports the dry-run default without injecting it', async ({
    request,
  }) => {
    const report = await validate(request, { source: '@input | link(rel:requires)' });
    expect(report.valid).toBe(true);
    expect(report.ast!.pipeline.stages[0].operands[0]).toMatchObject({ id: 'requires', kind: 'resolved' });
    expect(report.warnings.map((w) => w.code)).toContain('mutating_default_dry_run');
    expect(report.ast!.pipeline.stages[0].effective).toEqual({ dry_run: true });
    // `params` is a verbatim record of what the model emitted. `effective` is
    // computed and is what Wing must obey.
    expect(report.ast!.pipeline.stages[0].params).toEqual({});
  });

  test('ast.binding pins the three drift axes against the live surfaces', async ({ request }) => {
    const health = (await (await request.get('/agent/v1/health')).json()).data as {
      contracts: Record<string, number>;
      binding: { ontologyVersion: string; databaseId: string; opcodeRegistryHash: string };
      database: { id: string } | null;
      ontology: { version: string };
    };
    const registry = (await (await request.get('/agent/v1/validate/opcodes', { headers: RO })).json())
      .data as { contract: number; registryHash: string; opcodes: Array<{ name: string }> };

    const report = await validate(request, { source: '@input | classify(tax:01.01)', ttlSeconds: 1200 });
    const binding = report.ast!.binding;

    expect(binding.ontologyVersion).toBe(health.ontology.version);
    expect(binding.ontologyVersion).toMatch(/^onto1:[0-9a-f]{16}$/);
    // ADDED (4): the suite boots an unmaterialised store, so the digest here is
    // the literal the step-5 hard gate pins, not just a well-shaped string.
    expect(binding.ontologyVersion).toBe(PINNED_ONTOLOGY_VERSION);
    expect(binding.databaseId).toBe(health.database!.id);
    expect(binding.opcodeRegistryHash).toBe(registry.registryHash);
    expect(binding.opcodeRegistryHash).toMatch(/^cx1:[0-9a-f]{16}$/);
    expect(binding.ttlSeconds).toBe(1200);
    expect(Date.parse(binding.expiresAt) - Date.parse(binding.validatedAt)).toBe(1_200_000);

    // ADDED (3): /health's own `binding` block is the organ's publication of the
    // same three axes. It must be the SAME three values, not a second copy free
    // to drift from the AST that consumers actually bind against.
    expect(health.binding).toEqual({
      ontologyVersion: binding.ontologyVersion,
      databaseId: binding.databaseId,
      opcodeRegistryHash: binding.opcodeRegistryHash,
    });

    // The AST carries its own source, which is how revalidation at dispatch works.
    expect(report.ast!.source).toBe('@input | classify(tax:01.01)');

    // An out-of-range TTL is clamped, never rejected.
    const clamped = await validate(request, { source: '@input | classify(tax:01.01)', ttlSeconds: 999999 });
    expect(clamped.ast!.binding.ttlSeconds).toBe(3600);
  });

  test('the health surface declares the cortex contract and claims nothing else', async ({
    request,
  }) => {
    const health = (await (await request.get('/agent/v1/health')).json()).data as {
      contracts: Record<string, number>;
      ontology: { version: string; verbs: number };
    };
    expect(health.contracts.cortex).toBe(2);
    // DEVIATION (1) from KEAP's copy, which asserts `contracts.selfmodel === 1`.
    // The organ serves no slug-tree surface, so it declares no slug-tree
    // contract. Asserting the ABSENCE rather than deleting the check means the
    // day `selfmodel` appears in this health body, this line asks whether the
    // surface behind it appeared too.
    expect(health.contracts.selfmodel).toBeUndefined();
    expect(Object.keys(health.contracts)).toEqual(['cortex']);
    // The census counts are still there beside the version field.
    expect(typeof health.ontology.verbs).toBe('number');
  });

  test('the opcode registry is published for Wing to gate against', async ({ request }) => {
    const res = await request.get('/agent/v1/validate/opcodes', { headers: RO });
    expect(res.status()).toBe(200);
    const data = (await res.json()).data as {
      contract: number;
      registryHash: string;
      opcodes: Array<{ name: string; mutating: boolean; operands: { min: number; max: number; namespaces: string[] } }>;
    };
    expect(data.contract).toBe(2);
    const names = data.opcodes.map((o) => o.name);
    expect(names).toContain('classify');
    expect(names).toContain('insert');
    // `branch` is deliberately absent — the IR stays flat, and declaring an
    // opcode the grammar cannot express leaks a deferred decision into the
    // primer the model is trained on.
    expect(names).not.toContain('branch');
    expect(data.opcodes.find((o) => o.name === 'insert')!.mutating).toBe(true);
    expect(data.opcodes.find((o) => o.name === 'embed')!.mutating).toBe(false);

    // unauthenticated is refused
    expect((await request.get('/agent/v1/validate/opcodes')).status()).toBe(401);
  });

  test('validate leaves no trace: the corpus census is identical before and after a sweep', async ({
    request,
  }) => {
    const census = async () => {
      const data = (await (await request.get('/agent/v1/health')).json()).data as {
        corpus: Record<string, number>;
        ontology: { verbs: number; toeRelations: number; curatedRelations: number; version: string };
      };
      return JSON.stringify({ corpus: data.corpus, ontology: data.ontology });
    };

    const before = await census();
    for (const source of [
      '@input | classify(tax:node[motion])',
      '@input | link(rel:verb[depends])',
      '@input | link(rel:totally-made-up-verb)',
      '@input | get(kg:whatever)',
      '@input | insert(db:products, commit=true)',
      '@input | classify(tax:node[zzzqqxwv])',
    ]) {
      await validate(request, { source });
    }
    // In particular: an unknown `rel:` verb must NOT grow the vocabulary the way
    // KEAP's POST /agent/v1/relations does, and an unmatched term must not warm
    // a cache.
    expect(await census()).toBe(before);
  });
});
