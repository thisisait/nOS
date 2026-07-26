/**
 * Embedding source assembly + pending diff + optional live embedder.
 *
 * The embedding PIPELINE is split across the trust boundary on purpose:
 *   - This module (container) knows WHAT to embed: it assembles one canonical
 *     text per embeddable object and hashes it. GET /agent/v1/embeddings/pending
 *     serves the diff (missing or stale vs the stored content_hash).
 *   - The nOS host-side sync job (Pulse: keap-embed-sync) knows HOW to embed:
 *     it calls the host-loopback Ollama and POSTs vectors back. The container
 *     on gated_net can never assume it reaches a host daemon (Mac vs Linux).
 *
 * KEAP_OLLAMA_URL is the optional escape hatch: when the operator wires it
 * (e.g. host.docker.internal on Docker Desktop), free-text queries embed live
 * and /api|/agent/v1 semantic search becomes true vector search. Without it,
 * semantic ops are node-anchored only (node-to-node distance needs no live
 * embedder) and text search falls back to FTS.
 */
import crypto from 'node:crypto';
import * as db from './db';
import { allNodes } from './taxonomy';
import { objectText } from './objects';

export const EMBED_MODEL = process.env.KEAP_EMBED_MODEL ?? 'nomic-embed-text';
export const EMBED_DIM = 768; // must match embeddings.vector F32_BLOB(768)

const OLLAMA_URL = (process.env.KEAP_OLLAMA_URL ?? '').replace(/\/$/, '');

export interface PendingItem {
  kind: db.EmbeddingKind;
  refId: string;
  contentHash: string;
  text: string;
}

function hash(text: string): string {
  return crypto.createHash('sha256').update(text).digest('hex');
}

// ── Canonical embeddable text per kind ────────────────────────────────────────

function nodeText(n: { name: string; path: string; description?: string }): string {
  return [n.name, n.path, n.description ?? ''].filter(Boolean).join('\n');
}

function captureText(c: { title: string; description?: string; url?: string; domain?: string }): string {
  return [c.title, c.description ?? '', c.domain ?? '', c.url ?? ''].filter(Boolean).join('\n');
}

function noteText(nodeName: string | undefined, data: unknown): string {
  // Curated notes are arbitrary JSON — flatten string values, skip structure.
  const parts: string[] = nodeName ? [nodeName] : [];
  const walk = (v: unknown): void => {
    if (typeof v === 'string') parts.push(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(data);
  return parts.join('\n').slice(0, 4000);
}

// ── Sources: every embeddable object with its current text + hash ─────────────

export function allSources(): PendingItem[] {
  const out: PendingItem[] = [];
  const nodeById = new Map(allNodes().map((n) => [n.id, n]));

  for (const n of nodeById.values()) {
    const text = nodeText(n);
    out.push({ kind: 'taxonomy', refId: n.id, contentHash: hash(text), text });
  }
  for (const c of db.getAllMetadataApi('', true)) {
    const text = captureText(c);
    out.push({ kind: 'capture', refId: c.id, contentHash: hash(text), text });
  }
  const notes = db.getTaxonomyMetadata();
  for (const note of Array.isArray(notes) ? notes : []) {
    const text = noteText(nodeById.get(note.id)?.name, note.data);
    out.push({ kind: 'note', refId: note.id, contentHash: hash(text), text });
  }
  for (const o of db.getObjects('', true)) {
    const text = objectText(o);
    out.push({ kind: 'object', refId: o.id, contentHash: hash(text), text });
  }
  return out;
}

/**
 * The sync contract: everything missing or stale, oldest kinds first.
 * Also prunes vectors whose source row is gone, so deleted captures/notes
 * never linger as ghost stars in the explorer.
 */
export function pendingEmbeddings(limit: number): { pending: PendingItem[]; total: number; pruned: number } {
  const sources = allSources();
  let pruned = 0;
  for (const kind of ['taxonomy', 'capture', 'note', 'object'] as const) {
    const live = new Set(sources.filter((s) => s.kind === kind).map((s) => s.refId));
    pruned += db.pruneEmbeddings(kind, live);
  }
  const pending: PendingItem[] = [];
  for (const kind of ['taxonomy', 'capture', 'note', 'object'] as const) {
    const stored = db.getEmbeddingHashes(kind);
    for (const s of sources) {
      if (s.kind !== kind) continue;
      if (stored.get(s.refId) !== s.contentHash) pending.push(s);
    }
  }
  return { pending: pending.slice(0, limit), total: pending.length, pruned };
}

// ── Optional live embedder (KEAP_OLLAMA_URL) ─────────────────────────────────

export function liveEmbedAvailable(): boolean {
  return Boolean(OLLAMA_URL);
}

/** Ollama POST /api/embed response — only the field we read; runtime-guarded below. */
interface OllamaEmbedResponse {
  embeddings?: number[][];
}

/** Embed a free-text query via the operator-wired Ollama; null when unwired/failing. */
export async function embedText(text: string): Promise<number[] | null> {
  if (!OLLAMA_URL) return null;
  try {
    const res = await fetch(`${OLLAMA_URL}/api/embed`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: EMBED_MODEL, input: text }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return null;
    const json = (await res.json()) as OllamaEmbedResponse | null;
    const vec = json?.embeddings?.[0];
    return Array.isArray(vec) && vec.length === EMBED_DIM ? vec : null;
  } catch {
    return null;
  }
}
