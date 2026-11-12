//! OTLP spans per Iris turn (row thalamus-otel-spans): iris.turn → iris.complete / iris.tool, under the
//! ledger's own trace_id (the session uuid's 32 hex). Attributes are names, durations, a tool's name,
//! the outcome and token counts only: never the person's text, a cell value or a model answer; the
//! ledger stays the place for content. Off unless NOS_OTLP_ENDPOINT is a loopback http URL (Alloy's
//! OTLP/HTTP receiver, 127.0.0.1:4318). Exported on its own thread with a 200 ms budget: a turn never
//! waits on it, and a lost export is lost telemetry, never a lost turn. Hand-rolled OTLP JSON: no crate.

use serde_json::{json, Value};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

static NEXT: AtomicU64 = AtomicU64::new(1);

struct Span { id: String, parent: Option<String>, name: &'static str, start: u128, end: u128, ok: bool, attrs: Vec<(&'static str, Value)> }

pub struct Trace { trace_id: String, endpoint: String, spans: Vec<Span>, tokens: (i64, i64) }

fn now_ns() -> u128 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0)
}

/// 16 hex, unique within the process: time and a counter mixed, never derived from content.
fn span_id() -> String {
    let n = NEXT.fetch_add(1, Ordering::Relaxed);
    format!("{:016x}", (now_ns() as u64).rotate_left(17) ^ n.wrapping_mul(0x9E37_79B9_7F4A_7C15))
}

/// The collector, if the operator set one on loopback; anything else is off (the trace never leaves the host).
pub fn endpoint_from(raw: Option<&str>) -> Option<String> {
    let e = raw?.trim().trim_end_matches('/');
    let rest = e.strip_prefix("http://")?;
    let host = rest.split('/').next()?.rsplit_once(':').map_or(rest, |(h, _)| h);
    matches!(host, "127.0.0.1" | "localhost" | "[::1]").then(|| e.to_string())
}

/// A tool name as a span may carry it: the model chose it, so only a plain identifier passes.
pub fn tool_name(name: &str) -> &str {
    let ok = !name.is_empty() && name.len() <= 40 && name.bytes().all(|b| b.is_ascii_lowercase() || b == b'_');
    if ok { name } else { "unknown" }
}

impl Trace {
    /// Opens the turn's root span, or None when export is off or the session id is not a uuid.
    pub fn start(session: &str, tokens: (i64, i64)) -> Option<Trace> {
        let endpoint = endpoint_from(std::env::var("NOS_OTLP_ENDPOINT").ok().as_deref())?;
        let trace_id = session.replace('-', "");
        if trace_id.len() != 32 || !trace_id.bytes().all(|b| b.is_ascii_hexdigit()) {
            return None;
        }
        let root = Span { id: span_id(), parent: None, name: "iris.turn", start: now_ns(), end: 0, ok: true, attrs: vec![] };
        Some(Trace { trace_id: trace_id.to_ascii_lowercase(), endpoint, spans: vec![root], tokens })
    }

    /// A child of the turn; the index ends it.
    pub fn begin(&mut self, name: &'static str) -> usize {
        let parent = Some(self.spans[0].id.clone());
        self.spans.push(Span { id: span_id(), parent, name, start: now_ns(), end: 0, ok: true, attrs: vec![] });
        self.spans.len() - 1
    }

    pub fn end(&mut self, i: usize, ok: bool, attrs: Vec<(&'static str, Value)>) {
        if let Some(s) = self.spans.get_mut(i).filter(|s| s.end == 0) {
            (s.end, s.ok, s.attrs) = (now_ns(), ok, attrs);
        }
    }

    /// Ends the turn (its token counts are this turn's) and sends the batch; never blocks the caller.
    pub fn finish(mut self, tokens: (i64, i64)) {
        let attrs = vec![("gen_ai.usage.input_tokens", json!(tokens.0 - self.tokens.0)),
                         ("gen_ai.usage.output_tokens", json!(tokens.1 - self.tokens.1))];
        let ok = self.spans.iter().skip(1).all(|s| s.ok);
        self.end(0, ok, attrs);
        let now = now_ns();
        for s in self.spans.iter_mut().filter(|s| s.end == 0) {
            s.end = now; // a span the turn left open (an early return) ends with it
        }
        let (url, body) = (format!("{}/v1/traces", self.endpoint), self.body());
        std::thread::spawn(move || {
            let agent: ureq::Agent = ureq::Agent::config_builder()
                .proxy(None).max_redirects(0).http_status_as_error(false)
                .timeout_global(Some(Duration::from_millis(200))).build().into();
            let _ = agent.post(&url).send_json(&body);
        });
    }

    /// OTLP/HTTP JSON (opentelemetry-proto, trace v1): one resource, one scope, the turn's spans.
    pub fn body(&self) -> Value {
        let attr = |k: &str, v: &Value| match v {
            Value::Number(n) if n.is_i64() => json!({"key": k, "value": {"intValue": n.to_string()}}),
            Value::Bool(b) => json!({"key": k, "value": {"boolValue": b}}),
            v => json!({"key": k, "value": {"stringValue": v.as_str().map_or_else(|| v.to_string(), str::to_string)}}),
        };
        let spans: Vec<Value> = self.spans.iter().map(|s| {
            let mut j = json!({"traceId": self.trace_id, "spanId": s.id, "name": s.name, "kind": 1,
                "startTimeUnixNano": s.start.to_string(), "endTimeUnixNano": s.end.to_string(),
                "attributes": s.attrs.iter().map(|(k, v)| attr(k, v)).collect::<Vec<_>>(),
                "status": {"code": if s.ok { 1 } else { 2 }}});
            if let Some(p) = &s.parent {
                j["parentSpanId"] = json!(p);
            }
            j
        }).collect();
        json!({"resourceSpans": [{"resource": {"attributes": [attr("service.name", &json!("thalamus"))]},
                                  "scopeSpans": [{"scope": {"name": "nos.thalamus"}, "spans": spans}]}]})
    }
}
