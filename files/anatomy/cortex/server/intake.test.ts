import { afterEach, describe, expect, it } from 'vitest';
import express from 'express';
import type { Server } from 'node:http';
import { registerIngestRoutes } from './intake';

/**
 * `/ingest/v1/health` and the store epoch (S2).
 *
 * The consolidator's signature ledger lives in `~/.nos`, OUTSIDE every store,
 * and `deliver()` offers an item only to targets whose recorded signature
 * differs. So a store that is rebuilt while its ledger survives is never re-fed
 * — the source files are unchanged, every signature still matches, and not one
 * `dp-<sha1>` capture row comes back. `~/cortex/data` is documented as
 * expendable ("re-materialises … so removing it loses nothing without a
 * source"), which is true of the taxonomy and false of the captures.
 *
 * The epoch is what lets the FEEDER notice, with no operator and no knowledge of
 * an undocumented state file. Two properties are gated here, and the second is
 * as important as the first: it must be OPAQUE (a digest, never the identity)
 * and it must be OPTIONAL (KEAP's container serves `{status:'OK'}` and must keep
 * working through this exact code path).
 */

let server: Server | null = null;
afterEach(async () => {
  await new Promise<void>((r) => (server ? server.close(() => r()) : r()));
  server = null;
});

async function health(epoch?: string): Promise<Record<string, unknown>> {
  const app = express();
  registerIngestRoutes(app, undefined, epoch);
  server = app.listen(0);
  await new Promise<void>((r) => server!.on('listening', () => r()));
  const port = (server!.address() as { port: number }).port;
  const res = await fetch(`http://127.0.0.1:${port}/ingest/v1/health`);
  expect(res.status).toBe(200);
  return (await res.json()) as Record<string, unknown>;
}

describe('/ingest/v1/health', () => {
  it('publishes the store epoch when the daemon has one', async () => {
    const body = await health('deadbeefdeadbeef');
    expect(body.success).toBe(true);
    expect(body.data).toEqual({ status: 'OK', storeEpoch: 'deadbeefdeadbeef' });
  });

  it('omits the field entirely when there is none — KEAP\'s response, byte for byte', async () => {
    // NOT `storeEpoch: null`. An absent field is what makes the feeder keep its
    // previous behaviour; a null would still be a value to compare and reset on.
    const body = await health();
    expect(body.data).toEqual({ status: 'OK' });
    expect(Object.keys(body.data as object)).toEqual(['status']);
  });
});
