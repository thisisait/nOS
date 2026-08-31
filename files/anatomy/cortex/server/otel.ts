/**
 * OTLP/HTTP trace export for the cortex organ — one span per request, no SDK.
 *
 * ORGAN-ONLY BY DESIGN: this file has no KEAP counterpart and is not
 * upstreamable. KEAP is a Docker service behind Traefik with its own edge
 * telemetry; the cortex organ is a loopback daemon on the host, and the host
 * Alloy on 4318 is the only collector that can see it.
 *
 * WHY HAND-ROLLED. Wing's `App\AgentKit\Telemetry\OtelExporter` and Bone's
 * `otel.py` speak this exact payload in ~100 lines each. `@opentelemetry/sdk-node`
 * plus auto-instrumentations would be the fourth-largest dependency in an organ
 * whose whole requirement is "POST a JSON object per request".
 *
 * WHAT IT IS FOR. Measured 2026-08-31: Tempo held 950 traces and every one was
 * an AgentKit session — none of the three host organs emitted anything. The
 * cortex validate half is the seam agents hit through `/agent/v1/validate`, and
 * "why was that validation slow" had no answer reachable through grafana-mcp.
 *
 * ponytail: fire-and-forget POST per request, 300ms cap, on the response path.
 * A batching processor is more moving parts than this daemon's request volume
 * justifies; revisit if the cap ever shows up in latency.
 */
import { randomBytes } from 'node:crypto';
import type { Request, Response, NextFunction } from 'express';

const ENDPOINT = (process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? 'http://127.0.0.1:4318')
  .replace(/\/+$/, '');
const SERVICE = process.env.OTEL_SERVICE_NAME ?? 'nos.cortex';
const ENABLED = process.env.NOS_CORTEX_TRACING !== '0';

type AttrValue = string | number | boolean;

function kv(key: string, value: AttrValue) {
  if (typeof value === 'boolean') return { key, value: { boolValue: value } };
  if (typeof value === 'number') return { key, value: { intValue: String(value) } };
  return { key, value: { stringValue: value } };
}

/** Never throws and never rejects. Telemetry may not break the response it describes. */
function post(payload: unknown): void {
  fetch(`${ENDPOINT}/v1/traces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(300),
  }).then((r) => r.body?.cancel(), () => undefined).catch(() => undefined);
}

export function exportSpan(opts: {
  name: string; startNanos: bigint; endNanos: bigint;
  attributes: Record<string, AttrValue>; error?: string;
}): void {
  if (!ENABLED) return;
  const span = {
    traceId: randomBytes(16).toString('hex'),
    spanId: randomBytes(8).toString('hex'),
    name: opts.name,
    kind: 2,                                        // SPAN_KIND_SERVER
    startTimeUnixNano: String(opts.startNanos),
    endTimeUnixNano: String(opts.endNanos),
    attributes: Object.entries(opts.attributes).map(([k, v]) => kv(k, v)),
    status: opts.error ? { code: 2, message: opts.error } : { code: 1 },
  };
  post({
    resourceSpans: [{
      resource: { attributes: [kv('service.name', SERVICE), kv('service.namespace', 'nos')] },
      scopeSpans: [{ scope: { name: 'cortex.http' }, spans: [span] }],
    }],
  });
}

/**
 * One span per request. Mounted app-wide: it reads no body and touches no
 * route state, so unlike `jsonBody` it is safe in front of `agentAuth` — and it
 * has to be, or a 401/503 (the two answers that matter most when the agent
 * surface is misconfigured) would emit nothing.
 *
 * The route TEMPLATE is used, never `req.path`: `/agent/v1/objects/:id` keeps
 * Tempo's cardinality bounded at the number of routes rather than the number of
 * object ids. `req.route` is only populated once a handler matched, so a 404
 * falls back to the literal path — which is what you want to see for one.
 */
export function traceRequests() {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!ENABLED) return next();
    const start = process.hrtime.bigint();
    const wall = BigInt(Date.now()) * 1_000_000n;
    res.on('finish', () => {
      const route = (req.route?.path as string | undefined) ?? req.path;
      exportSpan({
        name: `${req.method} ${route}`,
        startNanos: wall,
        endNanos: wall + (process.hrtime.bigint() - start),
        attributes: {
          'http.request.method': req.method,
          'url.path': req.path,
          'http.route': route,
          'http.response.status_code': res.statusCode,
        },
        error: res.statusCode >= 500 ? `HTTP ${res.statusCode}` : undefined,
      });
    });
    next();
  };
}
