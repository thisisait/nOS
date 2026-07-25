import { describe, expect, it } from 'vitest';
import {
  CORTEX_ISSUE_SEVERITY,
  CORTEX_LIMITS,
  CORTEX_SOURCES,
  analyzeCortex,
  lineColumnAt,
  parseCortex,
  parseCortexTree,
  tokenizeCortex,
  type CortexAst,
  type CortexAstStage,
  type CortexIssue,
  type CortexIssueCode,
} from './cortex-lang';
import {
  CORTEX_NAMESPACES,
  CORTEX_OPCODES,
  CORTEX_SCOPE,
  NAMESPACE_POLICY,
  canonicalOpcodeRegistry,
  cortexRegistryHash,
  getOpcode,
  opcodeNames,
  suggestOpcodes,
} from './cortex-opcodes';

/**
 * The PURE half of POST /agent/v1/validate — tokenizer, parser, AST and the
 * code-owned opcode registry. No DB, no data dir, no imports of ./db: every case
 * here is a pure function of the source string.
 *
 * Coverage is anchored on docs/specs/cortex-validate.md §8's test-vector table.
 * Rows that need the live ontology (5, 6a/6b, 8, 9, 18, 20, 22) are asserted
 * only as far as this stage goes — that they PARSE and survive structural
 * validation, so that the resolution stage is the thing that rejects them.
 */

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const codes = (issues: CortexIssue[]): CortexIssueCode[] => issues.map((i) => i.code);

function only(source: string): CortexIssue {
  const { errors } = analyzeCortex(source);
  expect(errors).toHaveLength(1);
  return errors[0];
}

function astOf(source: string): CortexAst {
  const { ast, errors } = analyzeCortex(source);
  expect(codes(errors)).toEqual([]);
  expect(ast).not.toBeNull();
  return ast as CortexAst;
}

function stage0(source: string): CortexAstStage {
  return astOf(source).pipeline.stages[0];
}

// ---------------------------------------------------------------------------
// tokenizer
// ---------------------------------------------------------------------------

describe('tokenizeCortex', () => {
  it('lexes a full pipeline into the expected token kinds', () => {
    const { tokens, failure } = tokenizeCortex('@input | insert(db:products, ?hidden=true)');
    expect(failure).toBeNull();
    expect(tokens.map((t) => t.kind)).toEqual([
      'source',
      'pipe',
      'word',
      'lparen',
      'word',
      'colon',
      'word',
      'comma',
      'question',
      'word',
      'eq',
      'word',
      'rparen',
      'eof',
    ]);
  });

  it('makes "." its own token so a dotted id is word (dot word)*', () => {
    const { tokens } = tokenizeCortex('tax:nos.services.bookstack');
    expect(tokens.map((t) => t.text)).toEqual([
      'tax',
      ':',
      'nos',
      '.',
      'services',
      '.',
      'bookstack',
      '',
    ]);
  });

  it('treats every whitespace kind, including newlines, as a separator', () => {
    const { tokens, failure } = tokenizeCortex('@input\n\t| map(tax:01)\n');
    expect(failure).toBeNull();
    expect(tokens.map((t) => t.kind)).toEqual([
      'source',
      'pipe',
      'word',
      'lparen',
      'word',
      'colon',
      'word',
      'rparen',
      'eof',
    ]);
  });

  it('decodes string escapes and reports an unknown one with a position', () => {
    const ok = tokenizeCortex('"a\\"b\\\\c\\nd"');
    expect(ok.failure).toBeNull();
    expect(ok.tokens[0].text).toBe('a"b\\c\nd');

    const bad = tokenizeCortex('"a\\qb"');
    expect(bad.failure).toMatchObject({ offset: 2, length: 2, found: '\\q' });
    expect(bad.failure?.expected).toContain('\\\\');
  });

  it('reports an unterminated string at the OPENING quote', () => {
    const { failure } = tokenizeCortex('@input | filter(where="x > 3)');
    expect(failure).toMatchObject({ offset: 22, found: '<unterminated-string>', expected: ['"'] });
    expect(failure?.length).toBe('@input | filter(where="x > 3)'.length - 22);
  });

  it('accepts single-quoted strings and reports the matching quote as expected', () => {
    expect(tokenizeCortex("'x > 3'").tokens[0].text).toBe('x > 3');
    expect(tokenizeCortex("'oops").failure?.expected).toEqual(["'"]);
  });

  it('rejects characters with no production, including "#"', () => {
    expect(tokenizeCortex('# comment').tokens[0].kind).toBe('unknown');
    expect(tokenizeCortex('@input | map(tax:01) % 2').tokens.some((t) => t.kind === 'unknown')).toBe(
      true,
    );
  });

  it('accepts "/" inside a bareword but not as an id (the id rule catches it)', () => {
    const { tokens, failure } = tokenizeCortex('embed(model=nomic/v1)');
    expect(failure).toBeNull();
    expect(tokens.map((t) => t.text)).toContain('nomic/v1');
  });
});

// ---------------------------------------------------------------------------
// terms — the ']'-inside-a-term decision, unicode, bounds
// ---------------------------------------------------------------------------

describe('bracket terms', () => {
  it('runs to the first UNESCAPED "]" and unescapes \\] and \\\\', () => {
    expect(stage0('@input | map(tax:node[a\\]b])').operands[0].surface).toBe('a]b');
    expect(stage0('@input | map(tax:node[a\\\\b])').operands[0].surface).toBe('a\\b');
  });

  it('leaves any other backslash in a term literal (terms are human text)', () => {
    expect(stage0('@input | map(tax:node[C:\\path])').operands[0].surface).toBe('C:\\path');
  });

  it('ends the term at the first "]" when it is not escaped', () => {
    // `[a]b]` closes at the first bracket, so `b]` is left over and the parser
    // fails on it — a typed error, never a silent truncation.
    const err = only('@input | map(tax:node[a]b])');
    expect(err.code).toBe('syntax_error');
    expect(err.detail).toMatchObject({ found: 'b' });
  });

  it('reports an unterminated term at the OPENING bracket', () => {
    const err = only('@input | map(tax:node[Kinematics)');
    expect(err.code).toBe('syntax_error');
    expect(err.offset).toBe(21);
    expect(err.detail).toMatchObject({ found: '<unterminated-term>', expected: [']'] });
  });

  it('carries a unicode term through verbatim (plan §3’s own example)', () => {
    const operand = stage0('@input | map(ent:product[červené tričko L])').operands[0];
    expect(operand).toMatchObject({
      ns: 'ent',
      binding: 'late',
      scopeHint: 'product',
      surface: 'červené tričko L',
      kind: 'unresolved',
      id: null,
      resolvedName: null,
    });
  });

  it('trims a term but keeps the span over the brackets', () => {
    const operand = stage0('@input | map(tax:node[  Kinematics  ])').operands[0];
    expect(operand.surface).toBe('Kinematics');
    expect(operand.span).toEqual([13, 37]);
  });

  it('rejects an empty or whitespace-only term as malformed, not as a miss', () => {
    expect(only('@input | map(tax:node[])').code).toBe('malformed_operand');
    expect(only('@input | map(tax:node[   ])').detail).toMatchObject({ reason: 'empty term' });
  });

  it('reports an over-long term as program_too_large with the bound', () => {
    const term = 'x'.repeat(CORTEX_LIMITS.termLength + 1);
    const err = only(`@input | map(tax:node[${term}])`);
    expect(err.code).toBe('program_too_large');
    expect(err.detail).toEqual({
      bound: 'term_length',
      limit: CORTEX_LIMITS.termLength,
      got: CORTEX_LIMITS.termLength + 1,
    });
  });
});

// ---------------------------------------------------------------------------
// every operator in the grammar
// ---------------------------------------------------------------------------

describe('grammar operators', () => {
  it('parses | : . , ( ) [ ] = ? in one program', () => {
    const ast = astOf('@input | classify(tax:01.01) | insert(db:a.b[t], ?hidden=true, dry_run=true)');
    expect(ast.pipeline.source).toBe('@input');
    expect(ast.pipeline.stages).toHaveLength(2);
    expect(ast.pipeline.stages[0].operands[0].surface).toBe('01.01');
    expect(ast.pipeline.stages[1].operands[0]).toMatchObject({
      ns: 'db',
      binding: 'late',
      scopeHint: 'a.b',
      surface: 't',
      kind: 'deferred',
    });
    expect(ast.pipeline.stages[1].params.hidden).toMatchObject({ value: true, defaulted: true });
    expect(ast.pipeline.stages[1].params.dry_run).toMatchObject({ value: true, defaulted: false });
  });

  it('accepts an empty arglist', () => {
    expect(stage0('@input | review()').operands).toEqual([]);
  });

  it('accepts a program with no source', () => {
    const ast = astOf('classify(tax:01.01)');
    expect(ast.pipeline.source).toBeNull();
    expect(ast.pipeline.stages).toHaveLength(1);
  });

  it('types values by shape: bool, int, string, bare and quoted', () => {
    const params = stage0('@input | rank(tax:01, by="best of all", limit=10)').params;
    expect(params.by.value).toBe('best of all');
    expect(params.limit.value).toBe(10);
    expect(stage0('@input | rank(tax:01, by=score)').params.by.value).toBe('score');
    expect(stage0('@input | embed(tax:01, model=nomic.v1)').params.model.value).toBe('nomic.v1');
    expect(stage0('@input | delete(db:x, dry_run=false)').params.dry_run.value).toBe(false);
  });

  it('rejects a bare literal or ref arg — neither production is defined', () => {
    const err = only('@input | map("just a string")');
    expect(err.code).toBe('syntax_error');
    expect(err.detail).toMatchObject({ expected: ['<entity>', '<key>', '?'] });
  });

  it('rejects a trailing comma in an arglist', () => {
    expect(only('@input | map(tax:01,)').code).toBe('syntax_error');
  });
});

// ---------------------------------------------------------------------------
// syntax errors and position accuracy
// ---------------------------------------------------------------------------

describe('syntax errors carry an exact position', () => {
  it('vector 12 — unclosed arglist at eof', () => {
    const err = only('@input | map(tax:01.01');
    expect(err.code).toBe('syntax_error');
    expect(err.offset).toBe(22);
    expect(err.length).toBe(0);
    expect(err.detail).toEqual({ found: '<eof>', expected: [')', ','] });
  });

  it('vector 13 — @input.map(...) is NOT rewritten to @input | map(...)', () => {
    const err = only('@input.map(tax:01.01)');
    expect(err.code).toBe('syntax_error');
    expect(err.offset).toBe(6);
    expect(err.length).toBe(1);
    expect(err.detail).toEqual({ found: '.', expected: ['|', '<eof>'] });
  });

  it('unknown namespace fails at the ns token with the closed enum as the remedy', () => {
    const err = only('@input | map(foo:bar)');
    expect(err.code).toBe('syntax_error');
    expect(err.offset).toBe(13);
    expect(err.length).toBe(3);
    expect(err.detail).toEqual({ found: 'foo', expected: [...CORTEX_NAMESPACES] });
  });

  it('a missing "(" fails at the offending token', () => {
    const err = only('@input | map tax:01');
    expect(err.code).toBe('syntax_error');
    expect(err.offset).toBe(13);
    expect(err.detail).toMatchObject({ found: 'tax', expected: ['('] });
  });

  it('reports line and column, not just an offset', () => {
    const err = only('@input\n  | map(tax:01.01');
    expect(err.offset).toBe(24);
    expect(err.line).toBe(2);
    expect(err.column).toBe(18);
  });

  it('returns EXACTLY ONE syntax error — no recovery, no phantom cascade', () => {
    const { errors, warnings, ast } = analyzeCortex('@input | map(tax:01 | frobnicate( | ,,');
    expect(errors).toHaveLength(1);
    expect(errors[0].code).toBe('syntax_error');
    expect(warnings).toEqual([]);
    expect(ast).toBeNull();
  });

  it('prefers an EARLIER parse error over a later lexer failure', () => {
    // The bad escape is at offset 30; the parse breaks at the stray dot first.
    const err = only('@input.map(tax:01) | filter(where="a\\qb")');
    expect(err.offset).toBe(6);
    expect(err.detail).toMatchObject({ found: '.' });
  });

  it('an empty program is a syntax error at offset 0', () => {
    const err = only('');
    expect(err.offset).toBe(0);
    expect(err.detail).toEqual({ found: '<eof>', expected: ['<source>', '<opcode>'] });
    expect(only('   \n ').detail).toMatchObject({ found: '<eof>' });
  });

  it('a trailing pipe wants an opcode', () => {
    const err = only('@input | map(tax:01) |');
    expect(err.offset).toBe(22);
    expect(err.detail).toEqual({ found: '<eof>', expected: ['<opcode>'] });
  });

  it('an unbalanced ")" and an unbalanced "(" both fail with a position', () => {
    expect(only('@input | map(tax:01))').offset).toBe(20);
    expect(only('@input | map((tax:01)').offset).toBe(13);
  });

  it('a source with zero stages is a valid no-op (vector 13 pins <eof> as legal there)', () => {
    const ast = astOf('@input');
    expect(ast.pipeline.source).toBe('@input');
    expect(ast.pipeline.stages).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// spec §8 vectors — the syntax + structural half
// ---------------------------------------------------------------------------

describe('spec §8 test vectors (structural half)', () => {
  it('1 — @input | classify(tax:01.01)', () => {
    const stage = stage0('@input | classify(tax:01.01)');
    expect(stage).toMatchObject({ index: 0, opcode: 'classify', mutating: false, effective: {} });
    expect(stage.operands[0]).toMatchObject({
      ns: 'tax',
      kind: 'unresolved', // the resolution stage flips this to `resolved`
      binding: 'exact',
      scopeHint: null,
      surface: '01.01',
      id: null,
      resolvedName: null,
      span: [18, 27],
    });
    expect(analyzeCortex('@input | classify(tax:01.01)').warnings).toEqual([]);
  });

  it('2 — late binding keeps the TERM as surface, not the id', () => {
    const operand = stage0('@input | classify(tax:node[Kinematics])').operands[0];
    expect(operand).toMatchObject({ binding: 'late', scopeHint: 'node', surface: 'Kinematics' });
  });

  it('3 — a taxonomy id in the scope-hint slot narrows the search', () => {
    const operand = stage0('@input | classify(tax:01.01[Kinematics])').operands[0];
    expect(operand).toMatchObject({ binding: 'late', scopeHint: '01.01', surface: 'Kinematics' });
  });

  it('4/5 — an ambiguous or absent term is structurally fine; resolution decides', () => {
    expect(analyzeCortex('@input | classify(tax:node[motion])').errors).toEqual([]);
    expect(analyzeCortex('@input | classify(tax:node[zzzqqxwv])').errors).toEqual([]);
  });

  it('6 — a kg: operand parses and stays unresolved (no shape rule, no oracle)', () => {
    const operand = stage0('@input | get(kg:0f9c3e21-4b7a-4f2c-9d51-8ab6e0c72d13)').operands[0];
    expect(operand).toMatchObject({ ns: 'kg', kind: 'unresolved', id: null });
  });

  it('7 — insert(db:products, dry_run=true): valid, deferred, no default warning', () => {
    const src = '@input | insert(db:products, dry_run=true)';
    const { ast, errors, warnings } = analyzeCortex(src);
    expect(errors).toEqual([]);
    expect(ast?.pipeline.stages[0].operands[0]).toMatchObject({
      ns: 'db',
      kind: 'deferred',
      id: null,
      resolvedName: null,
      surface: 'products',
    });
    expect(ast?.deferred).toEqual([{ stage: 0, operand: 0, ns: 'db' }]);
    expect(codes(warnings)).toEqual(['deferred_namespace', 'deferred_program']);
    expect(ast?.pipeline.stages[0].effective).toEqual({ dry_run: true });
  });

  it('8/9/10 — every rel: verb is structurally valid; the vocabulary is stage 2’s', () => {
    for (const verb of ['is-a', 'requires', 'specializes']) {
      expect(analyzeCortex(`@input | link(rel:${verb})`).errors).toEqual([]);
    }
    expect(codes(analyzeCortex('@input | link(rel:requires)').warnings)).toEqual([
      'mutating_default_dry_run',
    ]);
    expect(stage0('@input | link(rel:requires)').effective).toEqual({ dry_run: true });
  });

  it('11 — delete(db:products): warned, defaulted in `effective`, params stays EMPTY', () => {
    const src = '@input | delete(db:products)';
    const { ast, errors, warnings } = analyzeCortex(src);
    expect(errors).toEqual([]);
    expect(ast?.pipeline.stages[0].params).toEqual({});
    expect(ast?.pipeline.stages[0].effective).toEqual({ dry_run: true });
    const warning = warnings.find((w) => w.code === 'mutating_default_dry_run');
    expect(warning?.detail).toEqual({ opcode: 'delete' });
    expect(warning?.severity).toBe('warning');
  });

  it('14 — unknown_opcode, with suggestions only from the published registry', () => {
    const err = only('@input | frobnicate(tax:01)');
    expect(err.code).toBe('unknown_opcode');
    expect(err.detail).toEqual({ opcode: 'frobnicate', didYouMean: [] });
    expect(err.offset).toBe(9);
  });

  it('15 — arity_error counts ENTITY operands only', () => {
    const err = only('@input | classify()');
    expect(err.code).toBe('arity_error');
    expect(err.detail).toEqual({ opcode: 'classify', min: 1, max: 1, got: 0 });

    // kv args never count toward arity — this is still arity 1, not 3.
    expect(analyzeCortex('@input | classify(tax:01, threshold=3)').errors).toEqual([]);
    expect(only('@input | classify(tax:01, tax:02)').detail).toMatchObject({ got: 2 });
  });

  it('16 — namespace_not_accepted is about the OPCODE, not the resource', () => {
    const { errors } = analyzeCortex('@input | classify(db:products)');
    expect(codes(errors)).toEqual(['namespace_not_accepted']);
    expect(errors[0].detail).toEqual({ opcode: 'classify', ns: 'db', allowed: ['tax', 'kg'] });
  });

  it('17 — a shape-illegal tax id is malformed_operand (and never probes existence)', () => {
    const err = only('@input | classify(tax:Nos.Services)');
    expect(err.code).toBe('malformed_operand');
    expect(err.detail).toEqual({ ns: 'tax', surface: 'Nos.Services', reason: 'id shape' });
  });

  it('19 — the plan’s headline example typechecks; "?" is preserved, not flattened', () => {
    const src = '@input | insert(db:products, ?hidden=true, dry_run=true)';
    const { ast, errors } = analyzeCortex(src);
    expect(codes(errors)).toEqual([]);
    expect(ast?.pipeline.stages[0].params).toEqual({
      hidden: { value: true, defaulted: true, span: [29, 41] },
      dry_run: { value: true, defaulted: false, span: [43, 55] },
    });
    expect(ast?.source).toBe(src);
  });

  it('21 — a reserved scope word without a term is malformed', () => {
    const err = only('@input | classify(tax:node)');
    expect(err.code).toBe('malformed_operand');
    expect(err.detail).toEqual({
      ns: 'tax',
      surface: 'node',
      reason: 'reserved scope word requires a term',
    });
    expect(only('@input | link(rel:verb)').detail).toMatchObject({ ns: 'rel', surface: 'verb' });
    expect(only('@input | get(kg:object)').detail).toMatchObject({ ns: 'kg', surface: 'object' });
  });
});

// ---------------------------------------------------------------------------
// scope hints (D6)
// ---------------------------------------------------------------------------

describe('scope hints (D6)', () => {
  it('accepts "node" or a taxonomy id for tax:, and rejects anything else', () => {
    expect(analyzeCortex('@input | classify(tax:node[x])').errors).toEqual([]);
    expect(analyzeCortex('@input | classify(tax:01.01[x])').errors).toEqual([]);
    expect(only('@input | classify(tax:Bogus[x])').detail).toMatchObject({
      reason: 'scope hint must be "node" or a taxonomy id',
    });
  });

  it('accepts only "verb" for rel: and only "object" for kg:', () => {
    expect(analyzeCortex('@input | resolve(rel:verb[depends on])').errors).toEqual([]);
    expect(only('@input | resolve(rel:relates[x])').detail).toMatchObject({
      reason: 'scope hint must be "verb"',
    });
    expect(analyzeCortex('@input | get(kg:object[minutes])').errors).toEqual([]);
    expect(only('@input | get(kg:card[minutes])').detail).toMatchObject({
      reason: 'scope hint must be "object"',
    });
  });

  it('lets ent:/db:/svc:/doc: carry any grammar-legal hint (KEAP owns no registry)', () => {
    expect(analyzeCortex('@input | map(ent:product[tričko])').errors).toEqual([]);
    expect(analyzeCortex('@input | insert(db:products.eu[Prague])').errors).toEqual([]);
    expect(analyzeCortex('@input | route(svc:bookstack[wiki])').errors).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// params
// ---------------------------------------------------------------------------

describe('params', () => {
  it('rejects an unknown param on a KEAP-owned stage', () => {
    const err = only('@input | classify(tax:01, nope=1)');
    expect(err.code).toBe('unknown_param');
    expect(err.detail).toEqual({ opcode: 'classify', key: 'nope', allowed: ['threshold'] });
  });

  it('records an undeclared param on a Wing-owned stage instead of rejecting it', () => {
    // `hidden` is a column of the products table; §5 forbids KEAP from knowing
    // that schema, so it may not claim the key is wrong.
    const { errors, ast } = analyzeCortex('@input | update(db:products, colour=red)');
    expect(codes(errors)).toEqual([]);
    expect(ast?.pipeline.stages[0].params.colour).toMatchObject({ value: 'red' });
  });

  it('still type-checks the DECLARED gate flags on a Wing-owned stage', () => {
    const err = only('@input | insert(db:products, dry_run=1)');
    expect(err.code).toBe('invalid_param_value');
    expect(err.detail).toEqual({
      opcode: 'insert',
      key: 'dry_run',
      expectedType: 'bool',
      got: 'int',
    });
  });

  it('reports a duplicate key once and keeps the FIRST occurrence', () => {
    const { errors, ast } = analyzeCortex('@input | rank(tax:01, limit=1, limit=2)');
    expect(codes(errors)).toEqual(['duplicate_param']);
    expect(errors[0].detail).toEqual({ key: 'limit' });
    expect(errors[0].offset).toBe(31);
    expect(ast).toBeNull();
    // the fold keeps the first, so a valid program is unaffected by the rule
    expect(parseCortex('@input | rank(tax:01, limit=1, limit=2)').ast?.pipeline.stages[0].params
      .limit.value).toBe(1);
  });

  it('type-checks int and string params', () => {
    expect(only('@input | rank(tax:01, limit=lots)').detail).toMatchObject({
      expectedType: 'int',
      got: 'string',
    });
    expect(only('@input | rank(tax:01, by=true)').detail).toMatchObject({
      expectedType: 'string',
      got: 'bool',
    });
  });

  // -------------------------------------------------------------------------
  // Param keys are MODEL-AUTHORED TEXT, and the lexer's WORD_CHAR admits every
  // `Object.prototype` member name. Both the registry lookup and the AST's
  // `params` map are keyed by that text, so neither may inherit anything.
  // -------------------------------------------------------------------------

  const PROTOTYPE_KEYS = ['constructor', 'toString', 'valueOf', 'hasOwnProperty', '__proto__'];

  it('treats a prototype-named key as UNKNOWN on a KEAP-owned stage, not as a declared one', () => {
    // An unguarded `spec.params[key]` read resolves each of these to an
    // inherited function, skipping the `unknown_param` branch entirely and
    // emitting `invalid_param_value` with `expectedType` undefined — an entry
    // missing a field §4.2 declares for that code, telling the repair loop
    // "wrong type" about a parameter that does not exist.
    for (const key of PROTOTYPE_KEYS) {
      const err = only(`@input | classify(tax:01, ${key}=1)`);
      expect(err.code).toBe('unknown_param');
      expect(err.detail).toEqual({ opcode: 'classify', key, allowed: ['threshold'] });
    }
  });

  it('the open-param pass-through covers prototype-named keys too (a column may be called `constructor`)', () => {
    // §5: KEAP does not know the products table's schema, so it may not reject
    // a column name — and "which strings JavaScript happens to inherit" is not
    // a schema fact KEAP is entitled to assert.
    for (const key of PROTOTYPE_KEYS) {
      const { errors, ast } = analyzeCortex(`@input | insert(db:products, ${key}=true)`);
      expect(codes(errors)).toEqual([]);
      const params = ast!.pipeline.stages[0].params;
      expect(Object.prototype.hasOwnProperty.call(params, key)).toBe(true);
      expect(params[key]).toMatchObject({ value: true });
      expect(Object.keys(params)).toContain(key);
      expect(JSON.parse(JSON.stringify(params))[key]).toMatchObject({ value: true });
    }
  });

  it('catches a duplicate `__proto__` — the params map has no prototype to write through', () => {
    // On a plain object literal `params['__proto__'] = {…}` invokes the
    // inherited setter instead of creating an own property, so the
    // hasOwnProperty duplicate guard never saw the second occurrence.
    const { errors, ast } = analyzeCortex('@input | insert(db:x, __proto__=true, __proto__=false)');
    expect(codes(errors)).toEqual(['duplicate_param']);
    expect(errors[0].detail).toEqual({ key: '__proto__' });
    expect(ast).toBeNull();

    const params = parseCortex('@input | insert(db:x, __proto__=true)').ast!.pipeline.stages[0]
      .params;
    expect(Object.getPrototypeOf(params)).toBeNull();
    expect(params.__proto__).toMatchObject({ value: true });
  });
});

// ---------------------------------------------------------------------------
// dry_run / commit (D8) — report, never inject
// ---------------------------------------------------------------------------

describe('mutating stages (D8)', () => {
  it('never writes the default into params', () => {
    const stage = stage0('@input | preserve(kg:abc)');
    expect(stage.params).toEqual({});
    expect(stage.effective).toEqual({ dry_run: true });
  });

  it('commit=true flips effective.dry_run and warns about the confirm gate', () => {
    const { ast, warnings } = analyzeCortex('@input | delete(db:x, commit=true)');
    expect(ast?.pipeline.stages[0].effective).toEqual({ dry_run: false });
    expect(codes(warnings)).toContain('commit_requires_confirm_gate');
    expect(codes(warnings)).not.toContain('mutating_default_dry_run');
  });

  it('an explicit dry_run=false is warned too — it is the same request as commit', () => {
    const { warnings } = analyzeCortex('@input | delete(db:x, dry_run=false)');
    expect(codes(warnings)).toContain('commit_requires_confirm_gate');
    expect(codes(warnings)).not.toContain('mutating_default_dry_run');
  });

  it('an explicit dry_run wins over a conflicting commit (the safe reading)', () => {
    const stage = stage0('@input | delete(db:x, dry_run=true, commit=true)');
    expect(stage.effective).toEqual({ dry_run: true });
  });

  it('commit=false suppresses the default warning and keeps dry_run on', () => {
    const { ast, warnings } = analyzeCortex('@input | delete(db:x, commit=false)');
    expect(ast?.pipeline.stages[0].effective).toEqual({ dry_run: true });
    expect(codes(warnings)).not.toContain('mutating_default_dry_run');
  });

  it('a non-mutating stage has an empty effective block', () => {
    expect(stage0('@input | rank(tax:01, limit=3)').effective).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// sources, deferral, bounds
// ---------------------------------------------------------------------------

describe('sources', () => {
  it('accepts all five sources', () => {
    for (const source of CORTEX_SOURCES) {
      expect(analyzeCortex(`${source} | map(tax:01)`).errors).toEqual([]);
    }
  });

  it('reports an unknown source as a structural error, not a parse failure', () => {
    const err = only('@nope | map(tax:01)');
    expect(err.code).toBe('unknown_source');
    expect(err.detail).toEqual({ source: '@nope', allowed: [...CORTEX_SOURCES] });
    expect(err.offset).toBe(0);
    expect(err.length).toBe(5);
  });
});

describe('deferral (D7)', () => {
  it('indexes every deferred operand by stage and position', () => {
    const ast = astOf('@input | map(tax:01) | route(svc:mail) | preserve(doc:handbook)');
    expect(ast.deferred).toEqual([
      { stage: 1, operand: 0, ns: 'svc' },
      { stage: 2, operand: 0, ns: 'doc' },
    ]);
  });

  it('emits deferred_program once, as info, with the count', () => {
    const { warnings } = analyzeCortex('@input | route(svc:mail) | preserve(doc:handbook)');
    const program = warnings.filter((w) => w.code === 'deferred_program');
    expect(program).toHaveLength(1);
    expect(program[0]).toMatchObject({ severity: 'info', stage: null, detail: { count: 2 } });
  });

  it('emits nothing deferred for an all-ontology program', () => {
    const { ast, warnings } = analyzeCortex('@input | classify(tax:01.01)');
    expect(ast?.deferred).toEqual([]);
    expect(codes(warnings)).not.toContain('deferred_program');
  });
});

describe('input bounds (§3.6)', () => {
  it('rejects an over-long source before tokenizing', () => {
    const err = only(`@input | map(tax:${'a'.repeat(CORTEX_LIMITS.sourceLength)})`);
    expect(err.code).toBe('program_too_large');
    expect(err.detail).toMatchObject({ bound: 'source_length', limit: CORTEX_LIMITS.sourceLength });
  });

  it('caps stages, args per stage, late-bound operands and id size', () => {
    const many = Array.from({ length: CORTEX_LIMITS.stages + 1 }, () => 'map(tax:01)').join(' | ');
    expect(codes(analyzeCortex(`@input | ${many}`).errors)).toContain('program_too_large');

    const args = Array.from({ length: CORTEX_LIMITS.stageArgs + 1 }, (_, i) => `k${i}=1`).join(', ');
    const argErr = analyzeCortex(`@input | insert(db:x, ${args})`).errors[0];
    expect(argErr.detail).toMatchObject({ bound: 'stage_args' });

    const late = Array.from(
      { length: CORTEX_LIMITS.lateBoundOperands + 1 },
      () => 'map(tax:node[thing])',
    ).join(' | ');
    expect(
      analyzeCortex(`@input | ${late}`).errors.map((e) => e.detail.bound),
    ).toContain('late_bound_operands');

    const deep = Array.from({ length: CORTEX_LIMITS.dottedIdSegments + 1 }, () => 'ab').join('.');
    expect(only(`@input | map(tax:${deep})`).detail).toMatchObject({ bound: 'dotted_id_segments' });
  });

  it('truncates the error list at the cap and says so', () => {
    const stages = Array.from({ length: 12 }, () => 'classify(tax:Bad, nope=1)').join(' | ');
    const { errors, truncated } = analyzeCortex(`@input | ${stages}`);
    expect(errors.length).toBe(CORTEX_LIMITS.errors);
    expect(truncated).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// report-level invariants
// ---------------------------------------------------------------------------

describe('analysis invariants', () => {
  it('nulls the AST whenever there is any error — there is no half-valid program', () => {
    expect(analyzeCortex('@input | classify(tax:node)').ast).toBeNull();
    expect(analyzeCortex('@input | map(tax:01').ast).toBeNull();
  });

  it('every issue carries a severity consistent with the code table', () => {
    const { errors, warnings } = analyzeCortex('@input | insert(db:x) | classify(tax:node)');
    for (const issue of [...errors, ...warnings]) {
      expect(issue.severity).toBe(CORTEX_ISSUE_SEVERITY[issue.code]);
    }
    expect(errors.every((e) => e.severity === 'error')).toBe(true);
    expect(warnings.every((w) => w.severity !== 'error')).toBe(true);
  });

  it('keeps `source` verbatim and stamps the AST version', () => {
    const src = '@input | classify(tax:01.01)';
    const ast = astOf(src);
    expect(ast.source).toBe(src);
    expect(ast.astVersion).toBe(1);
    expect(ast.binding).toBeUndefined(); // stamped by the resolution stage
  });

  it('parseCortexTree exposes the raw args the AST folds away', () => {
    const { tree } = parseCortexTree('@input | insert(db:x, k=1, k=2)');
    expect(tree?.stages[0].args).toHaveLength(3);
    expect(tree?.stages[0].args.filter((a) => a.kind === 'kv')).toHaveLength(2);
  });

  it('lineColumnAt is 1-based and clamps', () => {
    expect(lineColumnAt('ab\ncd', 0)).toEqual({ line: 1, column: 1 });
    expect(lineColumnAt('ab\ncd', 3)).toEqual({ line: 2, column: 1 });
    expect(lineColumnAt('ab\ncd', 99)).toEqual({ line: 2, column: 3 });
  });
});

// ---------------------------------------------------------------------------
// the opcode registry (D2/D3)
// ---------------------------------------------------------------------------

describe('opcode registry', () => {
  it('holds the 14 P1 opcodes and excludes `branch`', () => {
    expect(opcodeNames()).toEqual([
      'get',
      'map',
      'filter',
      'rank',
      'classify',
      'resolve',
      'embed',
      'link',
      'insert',
      'update',
      'delete',
      'preserve',
      'route',
      'review',
    ]);
    expect(getOpcode('branch')).toBeUndefined();
  });

  it('every opcode is well-formed against §2.2', () => {
    for (const op of CORTEX_OPCODES) {
      expect(op.name).toMatch(/^[a-z][a-z0-9-]{0,31}$/);
      expect(op.summary.length).toBeGreaterThan(0);
      expect(op.operands.min).toBeLessThanOrEqual(op.operands.max);
      expect(op.operands.namespaces.length).toBeGreaterThan(0);
      for (const ns of op.operands.namespaces) expect(CORTEX_NAMESPACES).toContain(ns);
      expect(op.since).toBe(1);
      // every mutating verb declares the gate flags KEAP reports on
      if (op.mutating) {
        expect(op.params.dry_run?.type).toBe('bool');
        expect(op.params.commit?.type).toBe('bool');
      }
    }
  });

  it('is frozen at runtime — a capability set nothing can push onto', () => {
    expect(Object.isFrozen(CORTEX_OPCODES)).toBe(true);
    expect(() => {
      (CORTEX_OPCODES as unknown as { push: (x: unknown) => void }).push({ name: 'rm-rf' });
    }).toThrow();
  });

  it('suggests only registry members, and only close ones', () => {
    expect(suggestOpcodes('clasify')).toEqual(['classify']);
    expect(suggestOpcodes('Classify')).toEqual(['classify']);
    expect(suggestOpcodes('frobnicate')).toEqual([]);
    expect(suggestOpcodes('classify')).toEqual([]);
  });

  it('hashes to a stable, prefixed fingerprint', () => {
    expect(cortexRegistryHash()).toMatch(/^cx1:[0-9a-f]{16}$/);
    expect(cortexRegistryHash()).toBe(cortexRegistryHash());
    const lines = canonicalOpcodeRegistry().split('\n');
    expect(lines).toHaveLength(CORTEX_OPCODES.length);
    expect(lines.every((l) => l.startsWith('o\t'))).toBe(true);
    // sorted by name, and free of the prose that would churn it
    expect([...lines].sort()).toEqual(lines);
    expect(canonicalOpcodeRegistry()).not.toContain('project the input');
  });

  it('declares a policy for every namespace, and scope agrees with it', () => {
    for (const ns of CORTEX_NAMESPACES) expect(NAMESPACE_POLICY[ns]).toBeDefined();
    expect(CORTEX_SCOPE.authorizes).toBe(false);
    expect([...CORTEX_SCOPE.resolved].sort()).toEqual(
      CORTEX_NAMESPACES.filter((ns) => NAMESPACE_POLICY[ns] === 'resolved').slice().sort(),
    );
    expect([...CORTEX_SCOPE.unresolved].sort()).toEqual(
      CORTEX_NAMESPACES.filter((ns) => NAMESPACE_POLICY[ns] === 'unresolved').slice().sort(),
    );
    expect([...CORTEX_SCOPE.deferred].sort()).toEqual(
      CORTEX_NAMESPACES.filter((ns) => NAMESPACE_POLICY[ns] === 'deferred').slice().sort(),
    );
  });
});
