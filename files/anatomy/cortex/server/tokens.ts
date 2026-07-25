/**
 * Bearer service tokens — the three-tier split, shared by the agent surface
 * (server/agent.ts) and the ingest surface (server/intake.ts):
 *
 *   KEAP_AGENT_TOKEN_RO       read the corpus (taxonomy, search, lint, objects)
 *   KEAP_AGENT_TOKEN_RW       read + the allowlisted writes (captures, objects,
 *                             embeddings, verdicts)
 *   KEAP_AGENT_TOKEN_CAPTURE  WRITE-ONLY INTAKE — POST /ingest/v1/capture and
 *                             nothing else. This is the DEVICE tier (AR glasses,
 *                             mobile companions, field sensors): a lost/extracted
 *                             device token can feed the review queue but can
 *                             never read the knowledge base or touch the corpus.
 *
 * RW implies capture (a full agent may ingest); capture implies nothing else.
 */
import crypto from 'node:crypto';

export const TOKEN_RO = process.env.KEAP_AGENT_TOKEN_RO ?? null;
export const TOKEN_RW = process.env.KEAP_AGENT_TOKEN_RW ?? null;
export const TOKEN_CAPTURE = process.env.KEAP_AGENT_TOKEN_CAPTURE ?? null;

export function tokenEquals(a: string, b: string): boolean {
  const ha = crypto.createHash('sha256').update(a).digest();
  const hb = crypto.createHash('sha256').update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
}

export function bearerOf(authorization: string | undefined): string | null {
  const auth = authorization ?? '';
  return auth.startsWith('Bearer ') ? auth.slice(7) : null;
}
