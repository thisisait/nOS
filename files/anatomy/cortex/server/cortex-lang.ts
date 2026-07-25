/**
 * cortex-lang — the PURE half of `POST /agent/v1/validate`: a hand-written
 * tokenizer, an LL(1) recursive-descent parser, the AST types, and the
 * structural (ontology-free) validation phase.
 *
 * Authorities: docs/specs/cortex-validate.md (this repo, frozen for
 * implementation) and nOS docs/plans/nos-cortex-lang.md §3 (the EBNF).
 *
 * NO database, NO express, NO I/O — everything here is a pure function of the
 * source string plus the frozen registry in ./cortex-opcodes. Operand
 * resolution (`tax:`/`rel:` lookups, the `kg:`/`ent:` refusal, the ontology
 * fingerprint and the `binding` block) is the NEXT stage and deliberately does
 * not live here.
 *
 * Phases (spec §4.3) — a phase with errors does not run the next one:
 *   1. envelope (zod, elsewhere)
 *   2. tokenize + parse      → EXACTLY ONE `syntax_error`, with a position
 *   3. structural            → all errors collected  ← this module
 *   4. resolution            → all errors collected  ← next stage
 *
 * The grammar (plan §3), left-factored for LL(1):
 *
 *   program    ::= pipeline
 *   pipeline   ::= source? stage ("|" stage)*
 *   stage      ::= opcode "(" arglist? ")"
 *   arglist    ::= arg ("," arg)*
 *   arg        ::= "?" key "=" value | ident (":" entity_rest | "=" value)
 *   entity_rest::= dotted_id ("[" term "]")?
 *   dotted_id  ::= ident ("." ident)*
 *   value      ::= string | dotted_word
 *
 * Every decision the grammar left open is recorded at the point it is made,
 * tagged `DECISION`, because the next stage and the P2 primer both depend on
 * them being written down rather than inferred from behaviour.
 */
import {
  CORTEX_NAMESPACES,
  NAMESPACE_POLICY,
  RESERVED_SCOPE_WORDS,
  getOpcode,
  isCortexNamespace,
  suggestOpcodes,
  type CortexNamespace,
  type CortexParamSpec,
} from './cortex-opcodes';

// ---------------------------------------------------------------------------
// Sources and bounds
// ---------------------------------------------------------------------------

/** plan §3. An unknown `@word` is a STRUCTURAL error (`unknown_source`), not a
 *  syntax error: the parser accepts any `@ident` so the repair loop gets the
 *  allowed list instead of a parse position. */
export const CORTEX_SOURCES = ['@input', '@user', '@ctx', '@sel', '@prev'] as const;
export type CortexSource = (typeof CORTEX_SOURCES)[number];

const SOURCE_SET: ReadonlySet<string> = new Set<string>(CORTEX_SOURCES);

export function isCortexSource(value: string): value is CortexSource {
  return SOURCE_SET.has(value);
}

/** Spec §3.6. Every breach produces `program_too_large` with `{bound, limit, got}`.
 *  `express.json({limit:'2mb'})` is a transport ceiling, not a semantic one, and
 *  late binding runs one FTS query per late-bound operand. */
export const CORTEX_LIMITS = {
  sourceLength: 4096,
  stages: 16,
  stageArgs: 16,
  lateBoundOperands: 8,
  termLength: 128,
  dottedIdLength: 256,
  dottedIdSegments: 16,
  errors: 20,
} as const;

/** Canonical id shape, verbatim from `server/objects.ts` NODE_ID: the seed
 *  (dotted 2-digit) and grown (dotted lowercase slug) forms, which are
 *  structurally disjoint. Duplicated rather than imported because objects.ts
 *  keeps it private and this module must stay free of that import graph. */
const TAX_ID_RE = /^(?:\d{2}(?:\.\d{2})*|[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*)$/;

/** Relation verb shape, verbatim from `server/agent.ts` RELATION_TYPE_RE. */
const REL_VERB_RE = /^[a-z][a-z0-9-]{0,63}$/;

// ---------------------------------------------------------------------------
// Issues (spec §4)
// ---------------------------------------------------------------------------

export type CortexSeverity = 'error' | 'warning' | 'info';

export type CortexIssueCode =
  | 'syntax_error'
  | 'program_too_large'
  | 'unknown_source'
  | 'unknown_opcode'
  | 'arity_error'
  | 'unknown_param'
  | 'duplicate_param'
  | 'missing_required_param'
  | 'invalid_param_value'
  | 'namespace_not_accepted'
  | 'malformed_operand'
  | 'unknown_operand'
  | 'ambiguous_operand'
  | 'namespace_not_resolvable'
  | 'late_binding_unavailable'
  | 'mutating_default_dry_run'
  | 'commit_requires_confirm_gate'
  | 'deferred_namespace'
  | 'deferred_program';

/** The severity table IS the contract (`valid === false` iff some entry is an
 *  error). Declared whole here — including the four codes only the resolution
 *  stage can emit — so both stages read one table. */
export const CORTEX_ISSUE_SEVERITY: Readonly<Record<CortexIssueCode, CortexSeverity>> = {
  syntax_error: 'error',
  program_too_large: 'error',
  unknown_source: 'error',
  unknown_opcode: 'error',
  arity_error: 'error',
  unknown_param: 'error',
  duplicate_param: 'error',
  missing_required_param: 'error',
  invalid_param_value: 'error',
  namespace_not_accepted: 'error',
  malformed_operand: 'error',
  unknown_operand: 'error',
  ambiguous_operand: 'error',
  namespace_not_resolvable: 'error',
  late_binding_unavailable: 'error',
  // `deferred_namespace` is INFO, not an error: a program full of `db:` operands
  // is a correct phase-1 result. Making it an error would invalidate the plan's
  // own §3 example and train P2 on a language that rejects its own primer.
  mutating_default_dry_run: 'warning',
  commit_requires_confirm_gate: 'warning',
  deferred_namespace: 'info',
  deferred_program: 'info',
};

export interface CortexIssue {
  /** the contract. `message` is prose and is NOT stable across releases. */
  code: CortexIssueCode;
  severity: CortexSeverity;
  message: string;
  /** 0-based stage index, `null` for program-level entries */
  stage: number | null;
  /** character offset into `source`; `null` when no span is known */
  offset: number | null;
  length: number | null;
  /** ADDITIVE to spec §4.1 (which lists offset/length only). 1-based, and worth
   *  the two fields: a repair prompt that says "line 3, column 12" is usable by
   *  a human reading a multi-line pipeline, an offset is not. */
  line: number | null;
  column: number | null;
  /** code-specific and CLOSED — nothing is added ad hoc, because the disclosure
   *  argument in §1.6 depends on errors carrying no incidental information. */
  detail: Record<string, unknown>;
}

/** 1-based line/column for a character offset. Exported: the resolution and
 *  report stages anchor their own errors with it. */
export function lineColumnAt(source: string, offset: number): { line: number; column: number } {
  const clamped = Math.max(0, Math.min(offset, source.length));
  let line = 1;
  let lineStart = 0;
  for (let i = 0; i < clamped; i += 1) {
    if (source[i] === '\n') {
      line += 1;
      lineStart = i + 1;
    }
  }
  return { line, column: clamped - lineStart + 1 };
}

// ---------------------------------------------------------------------------
// Tokenizer
// ---------------------------------------------------------------------------

export type CortexTokenKind =
  | 'source'
  | 'word'
  | 'string'
  | 'term'
  | 'pipe'
  | 'lparen'
  | 'rparen'
  | 'comma'
  | 'eq'
  | 'colon'
  | 'question'
  | 'dot'
  | 'unknown'
  | 'eof';

export interface CortexToken {
  kind: CortexTokenKind;
  /** decoded text — the unescaped value for `string`, the unescaped+trimmed
   *  inner text for `term`, the raw slice otherwise */
  text: string;
  /** the raw source slice (for `term`, brackets included) */
  raw: string;
  offset: number;
  /** exclusive end offset */
  end: number;
}

/** A single syntax failure with an exact position. `found`/`expected` become the
 *  `detail` of the one `syntax_error` entry (§4.3: recovery in a hand-written
 *  LL(1) parser is guessing, and a resynchronized parse sends the repair loop
 *  after phantoms — one accurate position beats five guesses). */
export interface CortexSyntaxFailure {
  offset: number;
  length: number;
  found: string;
  expected: string[];
}

const PUNCTUATION: Readonly<Record<string, CortexTokenKind>> = {
  '|': 'pipe',
  '(': 'lparen',
  ')': 'rparen',
  ',': 'comma',
  '=': 'eq',
  ':': 'colon',
  '?': 'question',
  '.': 'dot',
};

/**
 * DECISION — bareword charset is ASCII `[A-Za-z0-9_/-]`.
 *
 * It has to cover opcodes (`classify`), namespace tokens, id segments (`01`,
 * `bookstack`), param keys (`dry_run`) and unquoted values (`score`, `10`,
 * `-3`, `a/b`). `.` is deliberately NOT in it — it is its own token, which is
 * what makes `@input.map(…)` fail at offset 6 on the dot (test vector 13)
 * instead of lexing as one blob. Non-ASCII must be quoted or bracketed; a bare
 * `červené` is a syntax error, `"červené"` and `[červené tričko L]` are not.
 */
const WORD_CHAR = /[A-Za-z0-9_/-]/;
const SOURCE_START = /[A-Za-z_]/;

/** DECISION — string escapes are a closed set. An unrecognized escape is a
 *  syntax error carrying the legal set, rather than being passed through: a
 *  silent pass-through is an unlogged normalization, which §6/§7.6 forbid. */
const STRING_ESCAPES: Readonly<Record<string, string>> = {
  '\\': '\\',
  '"': '"',
  "'": "'",
  n: '\n',
  t: '\t',
  r: '\r',
};

const ESCAPE_EXPECTED = ['\\\\', '\\"', "\\'", '\\n', '\\t', '\\r'];

export interface CortexLexResult {
  tokens: CortexToken[];
  /** set for an unterminated string/term or an illegal escape. Scanning stops
   *  there and an `eof` token is emitted AT the failure offset, so the parser
   *  still runs and an EARLIER parse error still wins (see `parseCortexTree`). */
  failure: CortexSyntaxFailure | null;
}

export function tokenizeCortex(source: string): CortexLexResult {
  const tokens: CortexToken[] = [];
  const push = (kind: CortexTokenKind, offset: number, end: number, text?: string): void => {
    const raw = source.slice(offset, end);
    tokens.push({ kind, text: text ?? raw, raw, offset, end });
  };
  const finish = (at: number, failure: CortexSyntaxFailure | null): CortexLexResult => {
    tokens.push({ kind: 'eof', text: '', raw: '', offset: at, end: at });
    return { tokens, failure };
  };

  let i = 0;
  while (i < source.length) {
    const ch = source[i];

    if (ch === ' ' || ch === '\t' || ch === '\r' || ch === '\n' || ch === '\f' || ch === '\v') {
      i += 1;
      continue;
    }

    // --- source token: '@' ident ------------------------------------------
    if (ch === '@') {
      const start = i;
      i += 1;
      if (i < source.length && SOURCE_START.test(source[i])) {
        while (i < source.length && WORD_CHAR.test(source[i])) i += 1;
        push('source', start, i);
      } else {
        push('unknown', start, i);
      }
      continue;
    }

    // --- quoted string ------------------------------------------------------
    if (ch === '"' || ch === "'") {
      const start = i;
      i += 1;
      let value = '';
      let closed = false;
      while (i < source.length) {
        const c = source[i];
        if (c === '\\') {
          const next = source[i + 1];
          const decoded = next === undefined ? undefined : STRING_ESCAPES[next];
          if (decoded === undefined) {
            return finish(i, {
              offset: i,
              length: next === undefined ? 1 : 2,
              found: source.slice(i, next === undefined ? i + 1 : i + 2),
              expected: ESCAPE_EXPECTED,
            });
          }
          value += decoded;
          i += 2;
          continue;
        }
        if (c === ch) {
          i += 1;
          closed = true;
          break;
        }
        value += c;
        i += 1;
      }
      if (!closed) {
        // DECISION — an unterminated string is reported at the OPENING quote,
        // not at eof. The repair loop needs to know which quote to close; the
        // eof offset says nothing a human or a model can act on.
        return finish(start, {
          offset: start,
          length: source.length - start,
          found: '<unterminated-string>',
          expected: [ch],
        });
      }
      push('string', start, i, value);
      continue;
    }

    // --- bracket term -------------------------------------------------------
    if (ch === '[') {
      const start = i;
      i += 1;
      let raw = '';
      let closed = false;
      while (i < source.length) {
        const c = source[i];
        if (c === '\\') {
          const next = source[i + 1];
          // DECISION — how a ']' inside a term is handled: the term runs to the
          // first UNESCAPED ']'. `\]` yields a literal ']' and `\\` a literal
          // '\'; every other backslash is two literal characters (terms are
          // human text — `C:\path` must survive, unlike inside a string).
          //
          // Rejected alternatives: (a) no escape at all, which makes
          // `[foo]bar]` a SILENT TRUNCATION — the one failure mode late binding
          // must never have, since a valid-but-wrong operand is indistinguishable
          // from a correct one after the fact; (b) balanced-bracket counting,
          // which makes `[array[0]]` legal but still truncates `[foo]bar]` and
          // is not LL(1)-lexable without a counter the grammar never mentions.
          if (next === ']' || next === '\\') {
            raw += next;
            i += 2;
            continue;
          }
          raw += c;
          i += 1;
          continue;
        }
        if (c === ']') {
          i += 1;
          closed = true;
          break;
        }
        raw += c;
        i += 1;
      }
      if (!closed) {
        return finish(start, {
          offset: start,
          length: source.length - start,
          found: '<unterminated-term>',
          expected: [']'],
        });
      }
      // DECISION — the term is TRIMMED. Leading/trailing whitespace cannot be
      // significant: the value's only consumer is an FTS query, which tokenizes
      // it away. Emptiness and the 128-char bound are measured on the trimmed
      // value; the span still covers the brackets.
      push('term', start, i, raw.trim());
      continue;
    }

    // --- punctuation --------------------------------------------------------
    const punct = PUNCTUATION[ch];
    if (punct !== undefined) {
      push(punct, i, i + 1);
      i += 1;
      continue;
    }

    // --- bareword -----------------------------------------------------------
    if (WORD_CHAR.test(ch)) {
      const start = i;
      while (i < source.length && WORD_CHAR.test(source[i])) i += 1;
      push('word', start, i);
      continue;
    }

    // Anything else — `#`, `%`, a stray backslash, a bare non-ASCII letter.
    // DECISION — `#` is listed among plan §3's operators with no production and
    // no example. P1 does NOT accept it: inventing a comment (or fragment)
    // syntax the primer never teaches is worse than a typed error with a
    // position.
    push('unknown', i, i + 1);
    i += 1;
  }

  return finish(source.length, null);
}

// ---------------------------------------------------------------------------
// Parse tree (pre-AST — keeps the raw arg list so duplicate params are visible)
// ---------------------------------------------------------------------------

export type CortexSpan = [number, number];

export type CortexValueType = 'bool' | 'int' | 'string';

export interface CortexValue {
  type: CortexValueType;
  value: boolean | number | string;
  /** true when the value was written unquoted (`by=score`) */
  bare: boolean;
  span: CortexSpan;
}

export interface CortexTreeEntity {
  kind: 'entity';
  ns: CortexNamespace;
  /** the `dotted_id` slot verbatim */
  dottedId: string;
  segments: number;
  /** the bracket term, decoded and trimmed; `null` when absent */
  term: string | null;
  termSpan: CortexSpan | null;
  span: CortexSpan;
}

export interface CortexTreeParam {
  kind: 'kv';
  key: string;
  keySpan: CortexSpan;
  /** `?key=value` — "default when absent" (plan §3), semantically distinct from
   *  `key=value` and never flattened into it (§3.3). */
  defaulted: boolean;
  value: CortexValue;
  span: CortexSpan;
}

export type CortexTreeArg = CortexTreeEntity | CortexTreeParam;

export interface CortexTreeStage {
  opcode: string;
  opcodeSpan: CortexSpan;
  args: CortexTreeArg[];
  span: CortexSpan;
}

export interface CortexTree {
  source: string | null;
  sourceSpan: CortexSpan | null;
  stages: CortexTreeStage[];
}

class ParseAbort extends Error {
  readonly failure: CortexSyntaxFailure;
  constructor(failure: CortexSyntaxFailure) {
    super(`syntax error at ${failure.offset}`);
    this.failure = failure;
  }
}

/** `found` is the raw slice, capped so a closed `detail` can never echo a large
 *  chunk of the program back at the caller. */
function describeToken(token: CortexToken): string {
  if (token.kind === 'eof') return '<eof>';
  return token.raw.length > 32 ? `${token.raw.slice(0, 32)}…` : token.raw;
}

export interface CortexTreeResult {
  tree: CortexTree | null;
  failure: CortexSyntaxFailure | null;
}

export function parseCortexTree(source: string): CortexTreeResult {
  const lex = tokenizeCortex(source);
  const tokens = lex.tokens;
  let pos = 0;

  const peek = (): CortexToken => tokens[pos];
  const advance = (): CortexToken => tokens[pos++];
  const fail = (token: CortexToken, expected: string[]): never => {
    throw new ParseAbort({
      offset: token.offset,
      length: token.end - token.offset,
      found: describeToken(token),
      expected,
    });
  };

  const parseValue = (): CortexValue => {
    const token = peek();
    if (token.kind === 'string') {
      advance();
      return { type: 'string', value: token.text, bare: false, span: [token.offset, token.end] };
    }
    if (token.kind === 'word') {
      advance();
      let text = token.text;
      let end = token.end;
      // A dotted bareword value (`model=nomic.v1`) is one value, not a value
      // followed by a stray dot.
      while (peek().kind === 'dot') {
        advance();
        const seg = peek();
        if (seg.kind !== 'word') fail(seg, ['<ident>']);
        advance();
        text += `.${seg.text}`;
        end = seg.end;
      }
      const span: CortexSpan = [token.offset, end];
      // DECISION — value typing is by SHAPE, at the parse site, and is strict:
      // `true`/`false` are booleans, `-?\d+` is an int, everything else is a
      // string. So `dry_run=1` is an `invalid_param_value`, not a truthy bool —
      // a validator that coerces teaches the model a laxer language than the one
      // the primer states.
      if (text === 'true' || text === 'false') {
        return { type: 'bool', value: text === 'true', bare: true, span };
      }
      if (/^-?\d+$/.test(text)) {
        return { type: 'int', value: Number(text), bare: true, span };
      }
      return { type: 'string', value: text, bare: true, span };
    }
    return fail(token, ['<value>']);
  };

  const parseEntityRest = (nsToken: CortexToken): CortexTreeEntity => {
    if (!isCortexNamespace(nsToken.text)) {
      // DECISION — an unknown namespace is a SYNTAX error, not a semantic one.
      // `ns` is a closed terminal set in the EBNF, §4.2 has no
      // `unknown_namespace` code, and `malformed_operand.detail.ns` is typed as
      // one of the seven — there is nowhere to put `foo`. The expected list is
      // the whole enum, which is the best repair hint available.
      fail(nsToken, [...CORTEX_NAMESPACES]);
    }
    const first = peek();
    if (first.kind !== 'word') fail(first, ['<ident>']);
    advance();
    let dottedId = first.text;
    let segments = 1;
    let end = first.end;
    while (peek().kind === 'dot') {
      advance();
      const seg = peek();
      if (seg.kind !== 'word') fail(seg, ['<ident>']);
      advance();
      dottedId += `.${seg.text}`;
      segments += 1;
      end = seg.end;
    }
    let term: string | null = null;
    let termSpan: CortexSpan | null = null;
    if (peek().kind === 'term') {
      const t = advance();
      term = t.text;
      termSpan = [t.offset, t.end];
      end = t.end;
    }
    return {
      kind: 'entity',
      ns: nsToken.text as CortexNamespace,
      dottedId,
      segments,
      term,
      termSpan,
      span: [nsToken.offset, end],
    };
  };

  const parseArg = (): CortexTreeArg => {
    const token = peek();
    if (token.kind === 'question') {
      advance();
      const key = peek();
      if (key.kind !== 'word') fail(key, ['<key>']);
      advance();
      const eq = peek();
      if (eq.kind !== 'eq') fail(eq, ['=']);
      advance();
      const value = parseValue();
      return {
        kind: 'kv',
        key: key.text,
        keySpan: [key.offset, key.end],
        defaulted: true,
        value,
        span: [token.offset, value.span[1]],
      };
    }
    if (token.kind === 'word') {
      advance();
      const next = peek();
      if (next.kind === 'colon') {
        advance();
        return parseEntityRest(token);
      }
      if (next.kind === 'eq') {
        advance();
        const value = parseValue();
        return {
          kind: 'kv',
          key: token.text,
          keySpan: [token.offset, token.end],
          defaulted: false,
          value,
          span: [token.offset, value.span[1]],
        };
      }
      // DECISION — the EBNF's `arg ::= entity | kv | ref | literal` names two
      // productions (`ref`, `literal`) that it never defines, no opcode in the
      // registry declares a slot for either, and no test vector uses one. P1
      // therefore accepts NEITHER: a bare literal or ref is a syntax error.
      // (`kind:"literal"` stays in the operand union, reserved, so adding them
      // later is a contract bump rather than a schema change.)
      return fail(next, [':', '=']);
    }
    return fail(token, ['<entity>', '<key>', '?']);
  };

  const parseStage = (): CortexTreeStage => {
    const name = peek();
    if (name.kind !== 'word') fail(name, ['<opcode>']);
    advance();
    const lparen = peek();
    if (lparen.kind !== 'lparen') fail(lparen, ['(']);
    advance();
    const args: CortexTreeArg[] = [];
    if (peek().kind === 'rparen') {
      const rparen = advance();
      return {
        opcode: name.text,
        opcodeSpan: [name.offset, name.end],
        args,
        span: [name.offset, rparen.end],
      };
    }
    let end = lparen.end;
    for (;;) {
      args.push(parseArg());
      const next = peek();
      if (next.kind === 'rparen') {
        advance();
        end = next.end;
        break;
      }
      if (next.kind === 'comma') {
        advance();
        continue;
      }
      // The expected set is the one the CURRENT production is waiting on. `[`
      // is grammatically reachable here too, but it was already offered and
      // declined by the (successful) optional match inside the entity — which
      // is why test vector 12 expects exactly `[")", ","]`.
      fail(next, [')', ',']);
    }
    return {
      opcode: name.text,
      opcodeSpan: [name.offset, name.end],
      args,
      span: [name.offset, end],
    };
  };

  let tree: CortexTree | null = null;
  let parseFailure: CortexSyntaxFailure | null = null;
  try {
    let src: string | null = null;
    let srcSpan: CortexSpan | null = null;
    if (peek().kind === 'source') {
      const token = advance();
      src = token.text;
      srcSpan = [token.offset, token.end];
    }
    const stages: CortexTreeStage[] = [];
    if (src === null) {
      // DECISION — a program must contain at least a source or one stage; the
      // empty string is a syntax error at offset 0. A source with ZERO stages
      // (`@input`) is accepted and is a valid no-op: test vector 13 pins the
      // expected set after a source as `["|","<eof>"]`, which is only true if
      // eof is grammatically reachable there. Rejecting it would need an error
      // code §4.2 does not define.
      if (peek().kind === 'eof') fail(peek(), ['<source>', '<opcode>']);
      stages.push(parseStage());
    }
    while (peek().kind === 'pipe') {
      advance();
      stages.push(parseStage());
    }
    if (peek().kind !== 'eof') fail(peek(), ['|', '<eof>']);
    tree = { source: src, sourceSpan: srcSpan, stages };
  } catch (err) {
    if (!(err instanceof ParseAbort)) throw err;
    parseFailure = err.failure;
  }

  // A lexer failure stops scanning, so the parser sees a synthetic eof AT that
  // offset. An earlier parse error is the real first failure and wins; anything
  // at or past the lexer's offset is the lexer's to report.
  if (lex.failure && (!parseFailure || parseFailure.offset >= lex.failure.offset)) {
    return { tree: null, failure: lex.failure };
  }
  if (parseFailure) return { tree: null, failure: parseFailure };
  return { tree, failure: null };
}

// ---------------------------------------------------------------------------
// AST (spec §3.3)
// ---------------------------------------------------------------------------

export const CORTEX_AST_VERSION = 1;

/**
 * DECISION — `unresolved` is a fourth operand kind.
 *
 * §3.3 lists `resolved | deferred | literal`, but §1.2/§3.2/§5 all require a
 * state for `kg:`/`ent:` that is explicitly NOT `deferred` ("a different state,
 * in a different list, with a different code — Wing does not own the KEAP corpus
 * and cannot resolve them either"). `unresolved` is also the kind this module
 * emits for `tax:`/`rel:` operands *before* the resolution stage runs, so the
 * pre- and post-resolution ASTs share one schema.
 *
 * `literal` is reserved and currently unreachable (see the `ref`/`literal`
 * decision in `parseArg`).
 */
export type CortexOperandKind = 'resolved' | 'unresolved' | 'deferred' | 'literal';

/** `exact` — a dotted id written directly. `late` — a bracket term. */
export type CortexOperandBinding = 'exact' | 'late';

export interface CortexAstOperand {
  ns: CortexNamespace;
  kind: CortexOperandKind;
  binding: CortexOperandBinding;
  /** the `dotted_id` slot when `binding === "late"` (D6: a scope hint, not an
   *  id); `null` for `exact`, where the slot IS the id and lives in `surface`. */
  scopeHint: string | null;
  /** the text the model actually wrote: the id for `exact`, the bracket term
   *  for `late`. Never rewritten. */
  surface: string;
  /** canonical resolved id; `null` unless `kind === "resolved"` */
  id: string | null;
  /** the name that id had at resolution time (plan §6.3, drift invalidation) */
  resolvedName: string | null;
  /** `[startOffset, endOffset)` into `source` */
  span: CortexSpan;
}

export interface CortexAstParam {
  value: boolean | number | string;
  /** the `?key=value` form — preserved, never flattened */
  defaulted: boolean;
  span: CortexSpan;
}

export interface CortexAstStage {
  index: number;
  opcode: string;
  mutating: boolean;
  operands: CortexAstOperand[];
  /** a VERBATIM record of what the model emitted (D8) */
  params: Record<string, CortexAstParam>;
  /** computed, never merged into `params`. Normative for Wing. */
  effective: Record<string, boolean>;
  /** ADDITIVE to §3.3: the stage's span, so a consumer can highlight it. */
  span: CortexSpan;
}

export interface CortexAstPipeline {
  /** `null` when the program omitted the optional source */
  source: string | null;
  stages: CortexAstStage[];
}

export interface CortexDeferredRef {
  stage: number;
  operand: number;
  ns: CortexNamespace;
}

/** Stamped by the resolution/report stage — this module cannot know any of it. */
export interface CortexAstBinding {
  ontologyVersion: string;
  databaseId: string;
  opcodeRegistryHash: string;
  validatedAt: string;
  expiresAt: string;
  ttlSeconds: number;
}

export interface CortexAst {
  astVersion: number;
  /** the source verbatim — revalidation at dispatch re-POSTs exactly this */
  source: string;
  pipeline: CortexAstPipeline;
  deferred: CortexDeferredRef[];
  binding?: CortexAstBinding;
}

export interface CortexParseResult {
  ast: CortexAst | null;
  failure: CortexSyntaxFailure | null;
}

/** Parse only — no structural checks, no registry lookups beyond `mutating`.
 *  `analyzeCortex` is what a caller normally wants. */
export function parseCortex(source: string): CortexParseResult {
  const { tree, failure } = parseCortexTree(source);
  if (!tree) return { ast: null, failure };
  return { ast: buildAst(source, tree).ast, failure: null };
}

interface BuiltAst {
  ast: CortexAst;
  /** duplicates dropped while folding `params`, for `duplicate_param` */
  duplicates: { stage: number; key: string; span: CortexSpan }[];
}

function buildAst(source: string, tree: CortexTree): BuiltAst {
  const duplicates: BuiltAst['duplicates'] = [];
  const deferred: CortexDeferredRef[] = [];
  const stages: CortexAstStage[] = tree.stages.map((stage, index) => {
    const spec = getOpcode(stage.opcode);
    const operands: CortexAstOperand[] = [];
    // NULL-PROTOTYPE on purpose. Param keys are model-authored word tokens
    // (`WORD_CHAR` admits `__proto__`, `constructor`, `toString`), and on a
    // plain object literal `params['__proto__'] = {…}` invokes the inherited
    // setter instead of creating an own property: the key vanished from
    // `Object.keys`/JSON, and the `hasOwnProperty` duplicate guard below could
    // never see a second occurrence of it, so `__proto__=a, __proto__=b`
    // silently produced no `duplicate_param` while `limit=1, limit=2` did.
    // A map keyed by untrusted text must not have a prototype.
    const params: Record<string, CortexAstParam> = Object.create(null) as Record<
      string,
      CortexAstParam
    >;

    for (const arg of stage.args) {
      if (arg.kind === 'entity') {
        const late = arg.term !== null;
        const policy = NAMESPACE_POLICY[arg.ns];
        if (policy === 'deferred') {
          deferred.push({ stage: index, operand: operands.length, ns: arg.ns });
        }
        operands.push({
          ns: arg.ns,
          kind: policy === 'deferred' ? 'deferred' : 'unresolved',
          binding: late ? 'late' : 'exact',
          scopeHint: late ? arg.dottedId : null,
          surface: late ? (arg.term as string) : arg.dottedId,
          id: null,
          resolvedName: null,
          span: arg.span,
        });
        continue;
      }
      // DECISION — on a duplicate key the FIRST occurrence is kept in `params`
      // (the record reflects the emission order) and the error is anchored at
      // the later one, which is the token the model has to remove.
      if (Object.prototype.hasOwnProperty.call(params, arg.key)) {
        duplicates.push({ stage: index, key: arg.key, span: arg.span });
        continue;
      }
      params[arg.key] = { value: arg.value.value, defaulted: arg.defaulted, span: arg.span };
    }

    return {
      index,
      opcode: stage.opcode,
      mutating: spec?.mutating ?? false,
      operands,
      params,
      effective: {},
      span: stage.span,
    };
  });

  return {
    ast: {
      astVersion: CORTEX_AST_VERSION,
      source,
      pipeline: { source: tree.source, stages },
      deferred,
    },
    duplicates,
  };
}

// ---------------------------------------------------------------------------
// Structural validation (phase 3)
// ---------------------------------------------------------------------------

export interface CortexAnalysis {
  /** `null` whenever `errors` is non-empty — there is no half-valid program, and
   *  a partial AST is a repair-loop temptation and a training-data hazard. */
  ast: CortexAst | null;
  errors: CortexIssue[];
  /** severity `warning` or `info` */
  warnings: CortexIssue[];
  /** `errors` hit the §3.6 cap of 20 and was cut */
  truncated: boolean;
}

/** Re-exported for the RESOLUTION stage (server/cortex-resolve.ts), which must
 *  build phase-4 entries in the identical shape — including the additive
 *  `line`/`column`. Two constructors would be two contracts. */
export { issue as cortexIssue };

function issue(
  code: CortexIssueCode,
  message: string,
  detail: Record<string, unknown>,
  opts: { source: string; stage?: number | null; span?: CortexSpan | null },
): CortexIssue {
  const span = opts.span ?? null;
  const pos = span ? lineColumnAt(opts.source, span[0]) : null;
  return {
    code,
    severity: CORTEX_ISSUE_SEVERITY[code],
    message,
    stage: opts.stage ?? null,
    offset: span ? span[0] : null,
    length: span ? span[1] - span[0] : null,
    line: pos ? pos.line : null,
    column: pos ? pos.column : null,
    detail,
  };
}

function checkOperandShape(operand: CortexTreeEntity): { reason: string } | null {
  const reserved = RESERVED_SCOPE_WORDS[operand.ns];
  const late = operand.term !== null;

  if (!late) {
    // D6 — the reserved words are legal ONLY in the scope-hint position.
    if (reserved !== undefined && operand.dottedId === reserved) {
      return { reason: 'reserved scope word requires a term' };
    }
    if (operand.ns === 'tax' && !TAX_ID_RE.test(operand.dottedId)) return { reason: 'id shape' };
    if (operand.ns === 'rel' && !REL_VERB_RE.test(operand.dottedId)) return { reason: 'verb shape' };
    // DECISION — `kg:`/`ent:` get NO shape rule beyond the grammar. They are
    // never resolved (D1), so a shape rule would be inventing a registry that
    // §1.4 says does not exist; `db:`/`svc:`/`doc:` get none either, because
    // §5 forbids KEAP from having any opinion about a deferred resource beyond
    // "it is a well-formed dotted id".
    return null;
  }

  if (operand.term === '') return { reason: 'empty term' };
  // D6 — the legal scope hints, per namespace.
  if (operand.ns === 'tax') {
    if (operand.dottedId !== 'node' && !TAX_ID_RE.test(operand.dottedId)) {
      return { reason: 'scope hint must be "node" or a taxonomy id' };
    }
  } else if (operand.ns === 'rel') {
    if (operand.dottedId !== 'verb') return { reason: 'scope hint must be "verb"' };
  } else if (operand.ns === 'kg') {
    if (operand.dottedId !== 'object') return { reason: 'scope hint must be "object"' };
  }
  return null;
}

function checkParamValue(spec: CortexParamSpec, value: CortexValue): boolean {
  switch (spec.type) {
    case 'bool':
      return value.type === 'bool';
    case 'int':
      return value.type === 'int';
    case 'string':
      // A bareword and a quoted string are both strings; a bool or an int
      // written where a string is declared is not silently stringified.
      return value.type === 'string';
    case 'id':
      return value.type === 'string' && TAX_ID_RE.test(String(value.value));
    default:
      return false;
  }
}

/**
 * Tokenize → parse → structural validation. Phases 2 and 3 of §4.3.
 *
 * Returns an AST with every `tax:`/`rel:`/`kg:`/`ent:` operand still
 * `kind: "unresolved"`. The resolution stage runs ONLY when `errors` is empty
 * (a phase with errors does not run the next one) and is what flips those to
 * `resolved`, emits `unknown_operand` / `ambiguous_operand` /
 * `namespace_not_resolvable` / `late_binding_unavailable`, and stamps
 * `ast.binding`.
 */
export function analyzeCortex(source: string): CortexAnalysis {
  const errors: CortexIssue[] = [];
  const warnings: CortexIssue[] = [];
  const at = (span?: CortexSpan | null, stage?: number | null) => ({ source, span, stage });

  // §3.6 — the source cap is checked BEFORE tokenizing. Everything else can
  // wait; there is no reason to scan a megabyte to find out it is a megabyte.
  if (source.length > CORTEX_LIMITS.sourceLength) {
    return {
      ast: null,
      errors: [
        issue(
          'program_too_large',
          'source exceeds the maximum program length',
          { bound: 'source_length', limit: CORTEX_LIMITS.sourceLength, got: source.length },
          at(null, null),
        ),
      ],
      warnings,
      truncated: false,
    };
  }

  const { tree, failure } = parseCortexTree(source);
  if (!tree) {
    const f = failure as CortexSyntaxFailure;
    return {
      ast: null,
      errors: [
        issue(
          'syntax_error',
          `unexpected ${f.found}`,
          { found: f.found, expected: f.expected },
          { source, span: [f.offset, f.offset + f.length], stage: null },
        ),
      ],
      warnings,
      truncated: false,
    };
  }

  const built = buildAst(source, tree);
  const ast = built.ast;

  if (tree.source !== null && !isCortexSource(tree.source)) {
    errors.push(
      issue(
        'unknown_source',
        'unknown pipeline source',
        { source: tree.source, allowed: [...CORTEX_SOURCES] },
        at(tree.sourceSpan, null),
      ),
    );
  }

  if (tree.stages.length > CORTEX_LIMITS.stages) {
    errors.push(
      issue(
        'program_too_large',
        'too many stages in the pipeline',
        { bound: 'stages', limit: CORTEX_LIMITS.stages, got: tree.stages.length },
        at(null, null),
      ),
    );
  }

  let lateBound = 0;
  for (const stage of tree.stages) {
    for (const arg of stage.args) if (arg.kind === 'entity' && arg.term !== null) lateBound += 1;
  }
  if (lateBound > CORTEX_LIMITS.lateBoundOperands) {
    errors.push(
      issue(
        'program_too_large',
        'too many late-bound operands in the program',
        { bound: 'late_bound_operands', limit: CORTEX_LIMITS.lateBoundOperands, got: lateBound },
        at(null, null),
      ),
    );
  }

  tree.stages.forEach((stage, index) => {
    const spec = getOpcode(stage.opcode);
    const astStage = ast.pipeline.stages[index];

    if (!spec) {
      errors.push(
        issue(
          'unknown_opcode',
          'unknown opcode',
          { opcode: stage.opcode, didYouMean: suggestOpcodes(stage.opcode) },
          at(stage.opcodeSpan, index),
        ),
      );
    }

    if (stage.args.length > CORTEX_LIMITS.stageArgs) {
      errors.push(
        issue(
          'program_too_large',
          'too many arguments in one stage',
          { bound: 'stage_args', limit: CORTEX_LIMITS.stageArgs, got: stage.args.length },
          at(stage.span, index),
        ),
      );
    }

    const entities = stage.args.filter((a): a is CortexTreeEntity => a.kind === 'entity');
    const kvs = stage.args.filter((a): a is CortexTreeParam => a.kind === 'kv');

    if (spec && (entities.length < spec.operands.min || entities.length > spec.operands.max)) {
      errors.push(
        issue(
          'arity_error',
          'wrong number of operands',
          {
            opcode: spec.name,
            min: spec.operands.min,
            max: spec.operands.max,
            got: entities.length,
          },
          at(stage.span, index),
        ),
      );
    }

    entities.forEach((operand) => {
      if (operand.dottedId.length > CORTEX_LIMITS.dottedIdLength) {
        errors.push(
          issue(
            'program_too_large',
            'dotted id is too long',
            {
              bound: 'dotted_id_length',
              limit: CORTEX_LIMITS.dottedIdLength,
              got: operand.dottedId.length,
            },
            at(operand.span, index),
          ),
        );
      } else if (operand.segments > CORTEX_LIMITS.dottedIdSegments) {
        errors.push(
          issue(
            'program_too_large',
            'dotted id has too many segments',
            {
              bound: 'dotted_id_segments',
              limit: CORTEX_LIMITS.dottedIdSegments,
              got: operand.segments,
            },
            at(operand.span, index),
          ),
        );
      } else if (operand.term !== null && operand.term.length > CORTEX_LIMITS.termLength) {
        // §3.6 (a cap → `program_too_large`) wins over §5.3's phrasing of the
        // same 128 as a structural check: §3.6 is explicit that EVERY cap
        // reports the bound, the limit and the observed value.
        errors.push(
          issue(
            'program_too_large',
            'bracket term is too long',
            { bound: 'term_length', limit: CORTEX_LIMITS.termLength, got: operand.term.length },
            at(operand.termSpan ?? operand.span, index),
          ),
        );
      } else {
        const bad = checkOperandShape(operand);
        if (bad) {
          errors.push(
            issue(
              'malformed_operand',
              'operand does not match its namespace shape',
              {
                ns: operand.ns,
                surface: operand.term !== null ? operand.term : operand.dottedId,
                reason: bad.reason,
              },
              at(operand.span, index),
            ),
          );
        }
      }

      if (spec && !spec.operands.namespaces.includes(operand.ns)) {
        errors.push(
          issue(
            'namespace_not_accepted',
            'this opcode does not accept operands from that namespace',
            { opcode: spec.name, ns: operand.ns, allowed: [...spec.operands.namespaces] },
            at(operand.span, index),
          ),
        );
      }
    });

    // --- params -------------------------------------------------------------
    for (const dup of built.duplicates.filter((d) => d.stage === index)) {
      errors.push(
        issue('duplicate_param', 'parameter given twice', { key: dup.key }, at(dup.span, index)),
      );
    }

    if (spec) {
      // DECISION — the param set is CLOSED for a stage KEAP owns end to end, and
      // OPEN for a stage carrying a deferred (`db:`/`svc:`/`doc:`) operand.
      //
      // §2.3's registry table gives `insert` exactly three params, but the
      // plan's headline example — `insert(db:products, ?hidden=true,
      // dry_run=true)`, spec test vector 19 — must typecheck, and `hidden` is a
      // COLUMN OF THE products TABLE. §5 forbids KEAP from knowing that
      // resource's schema or columns at all, so rejecting `hidden` would be KEAP
      // asserting a schema it does not have, and would make plan §3's own
      // primer example invalid P2 training material.
      //
      // The rule tracks the two-authority split exactly: an undeclared key on a
      // Wing-owned operand belongs to Wing and is RECORDED verbatim in `params`
      // for phase 2; on a KEAP-owned operand it is `unknown_param`. Declared
      // params (`dry_run`, `commit`, …) are still name- and type-checked in
      // both modes — the pass-through never covers the gate flags.
      const openParams = entities.some((e) => NAMESPACE_POLICY[e.ns] === 'deferred');
      const seen = new Set<string>();
      for (const kv of kvs) {
        if (seen.has(kv.key)) continue; // already reported as duplicate_param
        seen.add(kv.key);
        // OWN properties only. `spec.params` is a plain (frozen) object literal
        // from ./cortex-opcodes, and `Object.freeze` does not remove
        // `Object.prototype`, so an unguarded read resolved every inherited
        // member name — `constructor`, `toString`, `valueOf`, `hasOwnProperty`,
        // `__proto__` — to a truthy value with no `.type`. The `unknown_param`
        // branch below was then unreachable for exactly those keys: they fell
        // through to `checkParamValue`'s `default: return false` and came back
        // as `invalid_param_value` with `expectedType` undefined (dropped by
        // JSON), an entry missing a field §4.2 declares — and, worse, the
        // open-param pass-through for Wing-owned operands was silently
        // unavailable for them, so `insert(db:products, constructor=1)` on a
        // table with a column named `constructor` was rejected outright.
        const paramSpec = Object.prototype.hasOwnProperty.call(spec.params, kv.key)
          ? (spec.params[kv.key] as CortexParamSpec)
          : undefined;
        if (!paramSpec) {
          if (openParams) continue;
          errors.push(
            issue(
              'unknown_param',
              'unknown parameter for this opcode',
              { opcode: spec.name, key: kv.key, allowed: Object.keys(spec.params).sort() },
              at(kv.span, index),
            ),
          );
          continue;
        }
        if (!checkParamValue(paramSpec, kv.value)) {
          errors.push(
            issue(
              'invalid_param_value',
              'parameter value has the wrong type',
              {
                opcode: spec.name,
                key: kv.key,
                expectedType: paramSpec.type,
                // DECISION — `got` is the observed TYPE, not the observed value.
                // `detail` is closed and must carry no incidental information;
                // the value is already in `params`, at a span the error points at.
                got: kv.value.type,
              },
              at(kv.span, index),
            ),
          );
        }
      }
      for (const [key, paramSpec] of Object.entries(spec.params)) {
        if (paramSpec.required && !seen.has(key)) {
          errors.push(
            issue(
              'missing_required_param',
              'required parameter is missing',
              { opcode: spec.name, key },
              at(stage.span, index),
            ),
          );
        }
      }

      // --- §6: report, never inject ----------------------------------------
      if (spec.mutating) {
        const dryRun = astStage.params.dry_run;
        const commit = astStage.params.commit;
        const dryRunBool = typeof dryRun?.value === 'boolean' ? dryRun.value : undefined;
        const commitBool = typeof commit?.value === 'boolean' ? commit.value : undefined;

        let effectiveDryRun: boolean;
        if (dryRunBool !== undefined) {
          // An explicit `dry_run` always wins, including over `commit=true` —
          // when the two disagree the safe reading is the one that does not
          // execute.
          effectiveDryRun = dryRunBool;
        } else if (commitBool !== undefined) {
          effectiveDryRun = !commitBool;
        } else {
          effectiveDryRun = true;
        }
        astStage.effective = { dry_run: effectiveDryRun };

        if (dryRun === undefined && commit === undefined) {
          warnings.push(
            issue(
              'mutating_default_dry_run',
              'mutating stage without an explicit dry_run or commit; dry_run defaults to true',
              { opcode: spec.name },
              at(stage.span, index),
            ),
          );
        }
        // DECISION — §6 says an explicit `dry_run=false` is "still warned", but
        // names no code for it: `mutating_default_dry_run` would be a lie
        // (nothing was defaulted). `dry_run=false` and `commit=true` are the
        // same request — "actually execute this" — so they get the same warning,
        // which is exactly what Wing's confirm gate keys on.
        if (commitBool === true || dryRunBool === false) {
          warnings.push(
            issue(
              'commit_requires_confirm_gate',
              'stage requests real execution; Wing’s confirm gate applies',
              { opcode: spec.name },
              at(stage.span, index),
            ),
          );
        }
      }

    }

    // --- deferred operands (info) ------------------------------------------
    for (const operand of astStage.operands) {
      if (operand.kind !== 'deferred') continue;
      warnings.push(
        issue(
          'deferred_namespace',
          'operand is validated by Wing in phase 2',
          { ns: operand.ns },
          at(operand.span, index),
        ),
      );
    }
  });

  if (ast.deferred.length > 0) {
    warnings.push(
      issue(
        'deferred_program',
        'the program has operands that only Wing can resolve',
        { count: ast.deferred.length },
        at(null, null),
      ),
    );
  }

  // §3.6 — errors are capped at 20. Warnings are not: they are bounded by the
  // stage and arg caps already, and dropping a dry-run warning is the one
  // truncation with a safety cost.
  const truncated = errors.length > CORTEX_LIMITS.errors;
  const capped = truncated ? errors.slice(0, CORTEX_LIMITS.errors) : errors;

  return { ast: capped.length > 0 ? null : ast, errors: capped, warnings, truncated };
}
