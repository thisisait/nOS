/**
 * cortex-validate — report assembly for `POST /agent/v1/validate`
 * (docs/specs/cortex-validate.md §3.2, §4.3).
 *
 * Runs the four phases in order, and a phase with errors DOES NOT RUN THE NEXT
 * ONE:
 *
 *   1. envelope        zod, in the route (a malformed request is a 400, not a
 *                      report — the report is about a program, and there is no
 *                      program yet)
 *   2. tokenize+parse  EXACTLY ONE `syntax_error` with a position   ┐ cortex-lang
 *   3. structural      all errors collected                         ┘
 *   4. resolution      all errors collected                           cortex-resolve
 *
 * Phases 3 and 4 collect because the repair loop wants every fixable problem in
 * one round-trip. Phase 2 does not, because it cannot do so honestly: error
 * recovery in a hand-written LL(1) parser is guessing, and a resynchronised
 * parse sends the repair loop after phantoms.
 *
 * ZERO SIDE EFFECTS (§7.1) — reads only, all the way down.
 */
import * as db from './db';
import { CORTEX_SCOPE, cortexRegistryHash } from './cortex-opcodes';
import { CORTEX_LIMITS, analyzeCortex, type CortexAst, type CortexIssue } from './cortex-lang';
import { resolveCortexOperands } from './cortex-resolve';
import { cortexOntologyVersion } from './cortex-ontology-version';
import { CORTEX_TTL_DEFAULT_SECONDS } from '../shared/contracts/cortex';

/** The `data` payload of `POST /agent/v1/validate` (§3.2). */
export interface CortexValidateReport {
  /** no entry has `severity: "error"`. `warnings` may still be non-empty. */
  valid: boolean;
  /** KEAP's half only. Wing's is phase 2. */
  phase: 1;
  /** `valid && ast.deferred.length === 0` — a consumer asking "can I dispatch
   *  this without Wing?" reads exactly this field and nothing else. */
  complete: boolean;
  /** the declared validation scope, machine-readable so no consumer has to
   *  infer it — including `authorizes: false`, which is a literal constant so
   *  that no downstream reader can mistake `valid: true` for permission. */
  scope: typeof CORTEX_SCOPE;
  /** `null` whenever `valid === false`. There is no half-valid program: a
   *  partial AST is a repair-loop temptation and a training-data hazard. */
  ast: CortexAst | null;
  errors: CortexIssue[];
  /** severity `warning` or `info` */
  warnings: CortexIssue[];
  /** `errors` hit the §3.6 cap of 20 and was cut. ADDITIVE to §3.2's shape,
   *  required by §3.6 ("then truncated, with `truncated: true` on the report"). */
  truncated: boolean;
}

function invalid(
  errors: CortexIssue[],
  warnings: CortexIssue[],
  truncated: boolean,
): CortexValidateReport {
  return {
    valid: false,
    phase: 1,
    complete: false,
    scope: CORTEX_SCOPE,
    ast: null,
    errors,
    warnings,
    truncated,
  };
}

/**
 * Tokenize → parse → typecheck → resolve. Returns the report; never throws for
 * a bad program, only for a broken database.
 *
 * `ttlSeconds` is already clamped to [60, 3600] by the request schema.
 */
export function validateCortex(
  source: string,
  ttlSeconds: number = CORTEX_TTL_DEFAULT_SECONDS,
): CortexValidateReport {
  const analysis = analyzeCortex(source);
  if (analysis.ast === null || analysis.errors.length > 0) {
    return invalid(analysis.errors, analysis.warnings, analysis.truncated);
  }

  const ast = analysis.ast;
  const resolution = resolveCortexOperands(source, ast);
  if (resolution.length > 0) {
    const truncated = resolution.length > CORTEX_LIMITS.errors;
    return invalid(
      truncated ? resolution.slice(0, CORTEX_LIMITS.errors) : resolution,
      analysis.warnings,
      truncated,
    );
  }

  // --- D5: the binding stamp ------------------------------------------------
  // The TTL is the cheap-path hint; the (ontologyVersion, databaseId,
  // opcodeRegistryHash) triple is the correctness mechanism. Wing's dispatch
  // rule, in order: expired → revalidate; ontologyVersion moved → revalidate;
  // databaseId moved → REJECT, do not revalidate (a different database is a
  // different language, and silently re-resolving against it is the
  // identity-drift failure one layer up); else dispatch.
  const validatedAt = new Date();
  ast.binding = {
    ontologyVersion: cortexOntologyVersion(),
    // '' before initDb() — a value that can never equal a real database id, so
    // Wing's identity comparison fails CLOSED rather than matching by accident.
    databaseId: db.getDbIdentity()?.id ?? '',
    opcodeRegistryHash: cortexRegistryHash(),
    validatedAt: validatedAt.toISOString(),
    expiresAt: new Date(validatedAt.getTime() + ttlSeconds * 1000).toISOString(),
    ttlSeconds,
  };

  return {
    valid: true,
    phase: 1,
    complete: ast.deferred.length === 0,
    scope: CORTEX_SCOPE,
    ast,
    errors: [],
    warnings: analysis.warnings,
    truncated: false,
  };
}
