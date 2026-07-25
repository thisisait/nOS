/**
 * cortex — the request envelope for `POST /agent/v1/validate`
 * (docs/specs/cortex-validate.md §3.1).
 *
 * ONLY the envelope is zod. The Cortex tokenizer/parser is hand-written
 * (server/cortex-lang.ts) — a parser generator would be a new dependency, and
 * zod is already a production dependency used at server/agent.ts:633, so this
 * file adds nothing to package-lock.json.
 *
 * There is deliberately no `{ ast }` input: revalidation at dispatch re-POSTs
 * `ast.source`, which the AST carries verbatim (§3.1, P1 non-goal 13).
 */
import { z } from 'zod';

/** §3.5 — `ttlSeconds` is clamped, never rejected. A caller asking for a day
 *  gets an hour, not a 400: the TTL is a cheap-path hint and the correctness
 *  mechanism is the `(ontologyVersion, databaseId, opcodeRegistryHash)` triple
 *  stamped into `ast.binding`. */
export const CORTEX_TTL_MIN_SECONDS = 60;
export const CORTEX_TTL_MAX_SECONDS = 3600;
export const CORTEX_TTL_DEFAULT_SECONDS = 900;

function clampTtl(seconds: number | undefined): number {
  if (seconds === undefined || !Number.isFinite(seconds)) return CORTEX_TTL_DEFAULT_SECONDS;
  return Math.min(CORTEX_TTL_MAX_SECONDS, Math.max(CORTEX_TTL_MIN_SECONDS, Math.trunc(seconds)));
}

/**
 * The `source` string is NOT length-bounded here on purpose. §3.6's 4096-char
 * cap is a SEMANTIC bound and is reported as a typed `program_too_large` entry
 * inside a 200 report (the repair loop can act on `{bound, limit, got}`; it can
 * do nothing with a bare 400 string). `express.json({limit:'2mb'})`
 * (server/index.ts:82) is the transport ceiling, and `analyzeCortex` checks the
 * length BEFORE tokenizing, so an oversize body is never scanned.
 */
export const cortexValidateRequestSchema = z
  .object({
    source: z.string({
      required_error: 'source required',
      invalid_type_error: 'source must be a string',
    }),
    ttlSeconds: z
      .number({ invalid_type_error: 'ttlSeconds must be a number' })
      .optional(),
  })
  .transform((body) => ({ source: body.source, ttlSeconds: clampTtl(body.ttlSeconds) }));

export type CortexValidateRequest = z.infer<typeof cortexValidateRequestSchema>;
