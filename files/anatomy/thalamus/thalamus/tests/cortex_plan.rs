//! Iris plans in cortex-lang (src/cortex_plan.rs): the model's one pipeline, validated by a fake
//! cortex organ, becomes the thalamus's own tool calls, run as today; anything the mapper cannot
//! carry falls back to plain tool calling with "[thalamus] cortex plan refused: ...".
//! Cases: state/fixtures/cortex-plan/cases.yml.

use nos_contract::wire::{decode_to_shell, encode, Scope, ToShell, ToThalamus};
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use thalamus::binding::Binding;
use thalamus::cortex_plan::{self, Cortex};
use thalamus::ledger::Ledger;
use thalamus::serve::{self, Server};

type Seen = Arc<Mutex<Vec<(String, String)>>>;
type Handler = Box<dyn Fn(&str, &str, &str, usize) -> (u16, String) + Send>;

/// A loopback HTTP/1.1 listener: handler(method, path, body, n-th request) answers; every request is seen.
fn listen(handler: Handler) -> (String, Seen) {
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", l.local_addr().unwrap());
    let seen: Seen = Arc::default();
    let s = seen.clone();
    std::thread::spawn(move || {
        for (n, c) in l.incoming().enumerate() {
            let mut c = c.unwrap();
            let mut r = BufReader::new(c.try_clone().unwrap());
            let mut head = String::new();
            loop {
                let mut line = String::new();
                if r.read_line(&mut line).unwrap() == 0 || line == "\r\n" {
                    break;
                }
                head.push_str(&line);
            }
            let len = head.lines()
                .find_map(|h| h.to_ascii_lowercase().strip_prefix("content-length:").map(|v| v.trim().parse().unwrap()))
                .unwrap_or(0);
            let mut body = vec![0; len];
            r.read_exact(&mut body).unwrap();
            let body = String::from_utf8(body).unwrap();
            s.lock().unwrap().push((head.clone(), body.clone()));
            let mut w = head.split_whitespace();
            let (method, target) = (w.next().unwrap_or("").to_string(), w.next().unwrap_or("").to_string());
            let path = target.split('?').next().unwrap_or("");
            let (status, out) = handler(&method, path, &body, n);
            write!(c, "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{out}", out.len())
                .unwrap();
        }
    });
    (url, seen)
}

fn table(id: &str, title: &str, cols: Value) -> Value {
    json!({"id": id, "title": title, "schema": {"columns": cols}})
}

/// KEAP's table routes over the fixture's tables, read-only: a write would be a defect here.
fn keap(extra: Vec<(Value, Value)>) -> (String, Seen) {
    let mut tables = vec![
        (table("todos", "Todos", json!([{"key": "title", "label": "Title", "kind": "text"},
            {"key": "status", "label": "Status", "kind": "select", "options": ["open", "done"]},
            {"key": "amount", "label": "Amount", "kind": "number"}, {"key": "track", "label": "Track", "kind": "text"}])),
         json!([{"id": "t1", "values": {"title": "Write spec", "status": "open", "amount": 3, "track": "core"}},
                {"id": "t2", "values": {"title": "Ship it", "status": "done", "amount": 5, "track": "core"}},
                {"id": "t3", "values": {"title": "Review", "status": "open", "amount": 2, "track": "face"}}])),
        (table("engram", "Engram", json!([{"key": "note", "label": "Note", "kind": "text"}])),
         json!([{"id": "e1", "values": {"note": "my own thought"}}])),
        (table("party", "Parties", json!([{"key": "slug", "label": "Slug", "kind": "text"},
            {"key": "legal_name", "label": "Legal name", "kind": "text"}, {"key": "role", "label": "Role", "kind": "text"}])),
         json!([{"id": "acme", "values": {"slug": "acme", "legal_name": "ACME s.r.o.", "role": "client"}}])),
    ];
    tables.extend(extra);
    listen(Box::new(move |method, path, _, _| {
        let ok = |d: Value| (200, json!({"success": true, "data": d}).to_string());
        if method != "GET" {
            return (405, r#"{"success": false, "error": "the gate's KEAP is read-only"}"#.into());
        }
        if path == "/api/tables" {
            return ok(json!(tables.iter().map(|(t, _)| json!({"id": t["id"], "title": t["title"]})).collect::<Vec<_>>()));
        }
        for (t, rows) in &tables {
            let base = format!("/api/tables/{}", t["id"].as_str().unwrap());
            if path == base {
                return ok(t.clone());
            }
            if path == format!("{base}/rows") {
                return ok(json!({"rows": rows, "nextCursor": null}));
            }
        }
        (404, r#"{"success": false, "error": "no such table"}"#.into())
    }))
}

/// The validator's report for one flat stage list, shaped as the organ's (cortex-validate.ts).
fn report(source: &str, stages: &Value, hash: &str, errors: &[String]) -> String {
    if !errors.is_empty() {
        let errs: Vec<Value> = errors.iter().map(|m| json!({"code": "unknown_param", "severity": "error", "message": m})).collect();
        return json!({"success": true, "data": {"valid": false, "ast": null, "errors": errs, "warnings": []}}).to_string();
    }
    let st: Vec<Value> = stages.as_array().unwrap().iter().enumerate().map(|(i, s)| {
        let operands: Vec<Value> = s["operand"].as_str().map(|o| {
            let (ns, id) = o.split_once(':').unwrap();
            json!({"ns": ns, "kind": "deferred", "binding": "exact", "scopeHint": null, "surface": id, "id": null})
        }).into_iter().collect();
        let params: serde_json::Map<String, Value> = s["params"].as_object().unwrap().iter()
            .map(|(k, v)| (k.clone(), json!({"value": v, "defaulted": false}))).collect();
        json!({"index": i, "opcode": s["op"], "mutating": false, "operands": operands, "params": params, "effective": {}})
    }).collect();
    json!({"success": true, "data": {"valid": true, "complete": false, "errors": [], "warnings": [],
        "ast": {"astVersion": 1, "source": source, "pipeline": {"source": null, "stages": st}, "deferred": [],
                "binding": {"opcodeRegistryHash": hash}}}}).to_string()
}

/// The fake cortex organ: each known source answers its case's report; a wrong token is a 401.
fn organ(known: Vec<(String, Value, String, Vec<String>)>) -> (String, Seen) {
    listen(Box::new(move |method, path, body, _| {
        if (method, path) != ("POST", "/agent/v1/validate") {
            return (404, "{}".into());
        }
        let src = serde_json::from_str::<Value>(body).unwrap()["source"].as_str().unwrap_or("").to_string();
        match known.iter().find(|k| k.0 == src) {
            Some((s, st, h, e)) => (200, report(s, st, h, e)),
            None => (200, report(&src, &json!([]), "", &[format!("syntax_error: the gate's organ does not know {src:?}")])),
        }
    }))
}

fn say(content: &str) -> String {
    json!({"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {"prompt_tokens": 9, "completion_tokens": 2}}).to_string()
}

fn call(tool: &str, args: Value) -> String {
    json!({"choices": [{"message": {"role": "assistant", "content": null, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": tool, "arguments": args.to_string()}}]}}]}).to_string()
}

/// The model answers its bodies in order (the last repeats); "!<status> " leads a non-200.
fn model(bodies: Vec<String>) -> (String, Seen) {
    listen(Box::new(move |_, _, _, n| {
        let b = &bodies[n.min(bodies.len() - 1)];
        match b.strip_prefix('!') {
            Some(rest) => {
                let (s, out) = rest.split_once(' ').unwrap();
                (s.parse().unwrap(), out.to_string())
            }
            None => (200, b.clone()),
        }
    }))
}

fn me() -> String {
    serve::login(unsafe { libc::getuid() }).expect("the test runs as a real login")
}

struct Rig {
    sock: PathBuf,
    ledger: PathBuf,
    model: Seen,
    keap: Seen,
}

fn binding(name: &str, local: bool) -> Binding {
    Binding { name: name.into(), base_url: String::new(), auth_token: String::new(), model_id: "m".into(), local,
              temperature: local.then_some(0.3) }
}

fn rig(name: &str, b: Binding, models: Vec<String>, cortex: Option<String>) -> Rig {
    rig_cx(name, b, models, cortex.map(|url| Cortex { url, token: "cx-ro-token".into(), rich_catalogue: false, intents: None }), vec![])
}

/// A rig whose KEAP holds `extra` tables after the fixture's three.
fn rig_cx(name: &str, b: Binding, models: Vec<String>, cortex: Option<Cortex>, extra: Vec<(Value, Value)>) -> Rig {
    let d = PathBuf::from(format!("/tmp/thc-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    for p in [d.clone(), d.join("state"), d.join("state/keap-tables")] {
        std::fs::create_dir_all(&p).unwrap();
        std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    std::fs::write(d.join("IMPRINT.short.md"), "# Imprint (short)\n").unwrap();
    std::fs::write(d.join("IMPRINT.md"), "# Imprint\n").unwrap();
    for (t, scope) in [("todos", "none"), ("engram", "personal"), ("party", "self")] {
        std::fs::write(d.join(format!("state/keap-tables/{t}.table.yml")), format!("client_scope: {scope}\n")).unwrap();
    }
    let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../..");
    std::fs::copy(repo.join("state/cortex-lang.gbnf"), d.join("state/cortex-lang.gbnf")).unwrap();
    let map = d.join("identity-map.yml");
    std::fs::write(&map, json!({"logins": {me(): {"username": "Alice Smith", "groups": ["nos-users"]}}}).to_string()).unwrap();
    let (model_url, model) = model(models);
    let (keap_url, keap) = keap(extra);
    let ledger = d.join("ledger.db");
    let srv = Server {
        map,
        keap_url,
        secret: "s3cret".into(),
        ledger: Mutex::new(Ledger::open(&ledger).unwrap()),
        binding: Ok(Binding { base_url: model_url, ..b }),
        repo: d.clone(),
        reader_secs: 10,
        tier1: vec![],
        deciders: vec![],
        log: Mutex::new(Box::new(std::io::sink())),
        picks: vec![],
        floors: None,
        cortex,
        data: d.clone(),
    };
    let sock = d.join("t.sock");
    let listener = serve::bind(&sock, 0o600).unwrap();
    std::thread::spawn(move || serve::run(listener, Arc::new(srv)));
    Rig { sock, ledger, model, keap }
}

fn next(r: &mut BufReader<UnixStream>) -> Option<ToShell> {
    loop {
        let mut line = String::new();
        if r.read_line(&mut line).unwrap() == 0 {
            return None;
        }
        match decode_to_shell(&line) {
            ToShell::Activity { .. } => continue,
            m => return Some(m),
        }
    }
}

/// One turn (after an optional working_for); the session and everything said until its end.
fn turn(rig: &Rig, working_for: Option<&str>, text: &str) -> (String, Vec<ToShell>) {
    let s = UnixStream::connect(&rig.sock).unwrap();
    s.set_read_timeout(Some(std::time::Duration::from_secs(10))).unwrap();
    let mut r = BufReader::new(s.try_clone().unwrap());
    let mut session = None;
    if let Some(c) = working_for {
        (&s).write_all(encode(&ToThalamus::WorkingFor { scope: Scope::Client(c.into()) }).as_bytes()).unwrap();
        loop {
            match next(&mut r) {
                Some(ToShell::Session { session: id, .. }) => session = Some(id),
                Some(ToShell::WorkingFor { .. }) => break,
                other => panic!("working_for was not set: {other:?}"),
            }
        }
    }
    (&s).write_all(encode(&ToThalamus::Turn { session: session.clone(), text: text.into() }).as_bytes()).unwrap();
    let mut got = vec![];
    while let Some(m) = next(&mut r) {
        if let ToShell::Session { session: id, .. } = &m {
            session = Some(id.clone());
        }
        let end = matches!(m, ToShell::Text { .. } | ToShell::Refused { .. });
        got.push(m);
        if end {
            break;
        }
    }
    drop((s, r));
    std::thread::sleep(std::time::Duration::from_millis(200));
    (session.expect("a session"), got)
}

/// ("<event type>:<tool>", result) of the session's tool events, in order.
fn tools(rig: &Rig, session: &str) -> Vec<(String, Value)> {
    let db = rusqlite::Connection::open(&rig.ledger).unwrap();
    let mut q = db.prepare("SELECT type, COALESCE(task, ''), COALESCE(result_json, 'null') FROM events WHERE run_id = ?1 ORDER BY id").unwrap();
    q.query_map([session], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))).unwrap().map(Result::unwrap)
        .filter_map(|(k, t, v)| Some((format!("{k}:{}", t.split_once("/tool:")?.1), serde_json::from_str(&v).unwrap()))).collect()
}

fn models_said(rig: &Rig) -> Vec<Value> {
    rig.model.lock().unwrap().iter().map(|(_, b)| serde_json::from_str(b).unwrap()).collect()
}

fn cases() -> Vec<Value> {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../state/fixtures/cortex-plan/cases.yml");
    let doc: Value = serde_yaml_ng::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    doc["cases"].as_array().unwrap().clone()
}

fn known(cases: &[Value]) -> Vec<(String, Value, String, Vec<String>)> {
    cases.iter().map(|c| (c["pipeline"].as_str().unwrap().to_string(), c["stages"].clone(),
        c["registry_hash"].as_str().unwrap_or(cortex_plan::REGISTRY_HASH).to_string(),
        c["errors"].as_array().map(|e| e.iter().map(|m| m.as_str().unwrap().to_string()).collect()).unwrap_or_default())).collect()
}

/// A plan row with each sha256 it names shown as "hex" (64 lowercase hex), so the row still compares whole:
/// tools/iris-bench.py reads primer_sha256 and grammar_sha256 into a run's provenance.
fn fingerprinted(v: &Value) -> Value {
    let mut v = v.clone();
    for k in ["primer_sha256", "grammar_sha256"] {
        if let Some(h) = v.get(k).and_then(Value::as_str).filter(|h| h.len() == 64 && h.chars().all(|c| matches!(c, '0'..='9' | 'a'..='f'))) {
            let _ = h;
            v[k] = json!("hex");
        }
    }
    // the catalogue the plan saw: sha256 of its table lines, first 16 hex, and the table ids it held
    if v.get("catalogue_digest").and_then(Value::as_str).is_some_and(|h| h.len() == 16 && h.chars().all(|c| matches!(c, '0'..='9' | 'a'..='f'))) {
        v["catalogue_digest"] = json!("hex16");
    }
    if v.get("catalogue_tables").and_then(Value::as_array).is_some_and(|t| !t.is_empty() && t.iter().all(Value::is_string)) {
        v["catalogue_tables"] = json!("ids");
    }
    v
}

#[test]
fn every_fixture_stage_list_renders_to_its_pipeline() {
    for c in cases() {
        let stages = cortex_plan::stages_of(&json!({"stages": c["stages"]})).unwrap();
        assert_eq!(cortex_plan::render(&stages), c["pipeline"].as_str().unwrap(), "{}", c["name"]);
    }
}

#[test]
fn every_fixture_pipeline_runs_as_its_tool_calls_or_falls_back() {
    let all = cases();
    let (organ_url, organ_seen) = organ(known(&all));
    for (i, c) in all.iter().enumerate() {
        let name = c["name"].as_str().unwrap();
        let planned = say(&json!({"stages": c["stages"]}).to_string());
        // The plan, a repair when the organ refuses, then: the tool path's query (same_as_tool) or the answer.
        let mut bodies = vec![planned.clone()];
        // a repair round follows an organ refusal and a mapper refusal; a registry mismatch has none
        let repaired = c.get("errors").is_some() || (c.get("refused").is_some() && c.get("registry_hash").is_none());
        if repaired {
            bodies.push(planned);
        }
        if let Some(t) = c.get("same_as_tool") {
            bodies.push(call("query_rows", t.clone()));
        }
        bodies.push(say("done"));
        let rig = rig(&format!("c{i}"), binding("ollama", true), bodies, Some(organ_url.clone()));
        let (session, got) = turn(&rig, c["working_for"].as_str(), "the person's question");
        assert!(matches!(got.last(), Some(ToShell::Text { text, .. }) if text == "done"), "{name}: the turn ended in the answer: {got:?}");
        let ev = tools(&rig, &session);
        let uses: Vec<&Value> = ev.iter().filter(|(t, _)| t.ends_with("tool_use:cortex_plan")).map(|e| &e.1).collect();
        assert_eq!(fingerprinted(uses[0]), json!({"source": c["pipeline"], "engine": "ollama-json-schema", "constrained": true,
            "primer_sha256": "hex", "grammar_sha256": "hex", "catalogue": "lean",
            "catalogue_digest": "hex16", "catalogue_tables": "ids"}), "{name}");
        let results: Vec<&Value> = ev.iter().filter(|(t, _)| t.ends_with("tool_result:cortex_plan")).map(|e| &e.1).collect();
        let last = *results.last().unwrap_or_else(|| panic!("{name}: no cortex_plan result: {ev:?}"));
        let said = models_said(&rig);
        if let Some(t) = c["primer_lacks"].as_str() {
            let primer = said[0]["messages"][0]["content"].as_str().unwrap();
            assert!(primer.contains("- todos ") && !primer.contains(t), "{name}: the catalogue shows only what the septum shows: {primer}");
        }
        let ran: Vec<Value> = ev.iter().filter(|(t, _)| t.starts_with("agent_tool_use:") && !t.ends_with(":cortex_plan") && !t.ends_with(":show_source"))
            .map(|(t, v)| json!([t.rsplit(':').next().unwrap(), v["args"]])).collect();
        if let Some(why) = c["refused"].as_str() {
            assert!(last["fallback"].as_str().is_some_and(|f| f.contains(why)), "{name}: fallback {last}");
            let plans = 1 + usize::from(repaired);
            let heard: String = said[plans]["messages"].as_array().unwrap().iter()
                .filter_map(|m| m["content"].as_str()).filter(|t| t.starts_with("[thalamus]")).collect();
            assert!(heard.contains(&format!("[thalamus] cortex plan refused: {why}")), "{name}: the model hears why: {heard}");
            assert!(said[plans..].iter().all(|b| b.get("tools").is_some()), "{name}: the fallback is plain tool calling");
            if c.get("same_as_tool").is_some() {
                // The tool path's error for the same table, as the model heard it, is the same text.
                let tool_err = said.last().unwrap()["messages"].as_array().unwrap().iter().rev()
                    .find(|m| m["role"] == "tool").unwrap()["content"].as_str().unwrap().to_string();
                assert!(tool_err.contains(why), "{name}: the tool path says it the same way: {tool_err}");
            } else {
                assert!(ran.is_empty(), "{name}: a refused plan runs nothing: {ran:?}");
            }
        } else {
            assert_eq!(last["valid"], json!(true), "{name}: {last}");
            assert_eq!(last["registry_hash"], json!(cortex_plan::REGISTRY_HASH), "{name}");
            assert_eq!(json!(ran), c["calls"], "{name}: the mapped calls ran, in order");
            assert_eq!(last["plan"], c["calls"], "{name}: the ledger keeps the plan");
            let errs: Vec<&(String, Value)> = ev.iter().filter(|(t, v)| t.starts_with("agent_tool_result:") && v.get("error").is_some()).collect();
            assert!(errs.is_empty(), "{name}: a mapped call failed: {errs:?}");
            assert_eq!(said.len(), 2, "{name}: one plan call and one answer call");
            assert!(said[0].get("tools").is_none(), "{name}: the plan call offers no tools");
        }
        assert!(rig.keap.lock().unwrap().iter().all(|(h, _)| h.starts_with("GET ")), "{name}: nothing was written");
    }
    assert!(organ_seen.lock().unwrap().iter().all(|(h, _)| h.to_lowercase().contains("authorization: bearer cx-ro-token")),
            "every validate carries the RO token");
}

#[test]
fn the_unconstrained_engine_repairs_once_with_the_validators_errors() {
    let good = "get(db:todos, limit=5) | filter(where=\"status eq open\")";
    let all = cases();
    let mut k = known(&all);
    k.push(("get(db:todos, colour=red)".into(), json!([]), String::new(), vec!["unknown_param: get has no param colour".into()]));
    let (organ_url, _) = organ(k);
    let rig = rig("repair", binding("mistral-eu", false),
                  vec![say("```\nget(db:todos, colour=red)\n```"), say(good), say("done")], Some(organ_url));
    let (session, _) = turn(&rig, None, "open todos");
    let said = models_said(&rig);
    assert!(said[0].get("grammar").is_none() && said[0].get("response_format").is_none(), "a cloud row is unconstrained");
    assert!(said[1].to_string().contains("unknown_param: get has no param colour"), "the repair hears the errors");
    let ev = tools(&rig, &session);
    let uses: Vec<&Value> = ev.iter().filter(|(t, _)| t.ends_with("tool_use:cortex_plan")).map(|e| &e.1).collect();
    assert_eq!(uses.len(), 2);
    assert_eq!(fingerprinted(uses[0]), json!({"source": "get(db:todos, colour=red)", "engine": "unconstrained", "constrained": false,
        "primer_sha256": "hex", "grammar_sha256": null, "catalogue": "lean",
        "catalogue_digest": "hex16", "catalogue_tables": "ids"}), "the fence is stripped; an unconstrained plan has no grammar");
    assert!(ev.iter().any(|(t, v)| t.ends_with("tool_use:query_rows") && v["args"]["limit"] == 5), "the repaired plan ran: {ev:?}");
}

#[test]
fn llamacpp_sends_the_grammar_and_ollama_falls_to_unconstrained_on_501() {
    let good = "get(db:todos, limit=5) | filter(where=\"status eq open\")";
    let (organ_url, _) = organ(known(&cases()));
    let rig1 = rig("gbnf", binding("llamacpp", true), vec![say(good), say("done")], Some(organ_url.clone()));
    let (s1, _) = turn(&rig1, None, "open todos");
    let said = models_said(&rig1);
    let gbnf = std::fs::read_to_string(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../state/cortex-lang.gbnf")).unwrap();
    assert_eq!(said[0]["grammar"], json!(gbnf), "llama.cpp gets the GBNF per request");
    assert!(tools(&rig1, &s1).iter().any(|(t, v)| t.ends_with(":cortex_plan") && v["engine"] == "llamacpp-gbnf" && v["constrained"] == true));

    // Ollama MLX answers 501 to any format: the same plan, unconstrained.
    let rig2 = rig("mlx", binding("ollama", true), vec!["!501 {\"error\": \"format not supported\"}".into(), say(good), say("done")], Some(organ_url));
    let (s2, _) = turn(&rig2, None, "open todos");
    let said = models_said(&rig2);
    assert!(said[0].get("response_format").is_some() && said[1].get("response_format").is_none(), "constrained, then not");
    let ev = tools(&rig2, &s2);
    assert!(ev.iter().any(|(t, v)| t.ends_with("tool_use:cortex_plan") && v["engine"] == "unconstrained"), "{ev:?}");
    assert!(ev.iter().any(|(t, _)| t.ends_with("tool_use:query_rows")), "the plan ran: {ev:?}");
}

#[test]
fn an_organ_that_is_down_turns_the_path_off_for_the_turn() {
    let dead = { let l = TcpListener::bind("127.0.0.1:0").unwrap(); format!("http://{}", l.local_addr().unwrap()) };
    let rig = rig("down", binding("ollama", true), vec![say("{\"stages\": [{\"op\": \"get\", \"operand\": \"db:todos\", \"params\": {}}]}"),
                  say("done")], Some(dead));
    let (session, got) = turn(&rig, None, "todos");
    assert!(matches!(got.last(), Some(ToShell::Text { text, .. }) if text == "done"));
    let said = models_said(&rig);
    assert!(said[1].to_string().contains("[thalamus] cortex plan refused: the cortex organ is unreachable"), "{}", said[1]);
    let ev = tools(&rig, &session);
    assert!(ev.iter().any(|(t, v)| t.ends_with("tool_result:cortex_plan") && v["valid"] == false), "{ev:?}");
}

#[test]
fn without_a_cortex_the_turn_is_plain_tool_calling() {
    let rig = rig("off", binding("ollama", true), vec![say("done")], None);
    let (session, _) = turn(&rig, None, "todos");
    assert_eq!(models_said(&rig).len(), 1, "no plan call");
    assert!(tools(&rig, &session).iter().all(|(t, _)| !t.ends_with(":cortex_plan")));
}

#[test]
fn the_mini_syntaxes_parse_and_refuse_by_shape() {
    assert_eq!(cortex_plan::parse_where("Book owner eq ACME s.r.o.").unwrap(), ("Book owner".into(), "eq".into(), json!("ACME s.r.o.")));
    assert_eq!(cortex_plan::parse_where("amount between 2, 5").unwrap(), ("amount".into(), "between".into(), json!(["2", "5"])));
    assert_eq!(cortex_plan::parse_where("when after 2026-10-01").unwrap().1, "after");
    assert!(cortex_plan::parse_where("eq open").is_err() && cortex_plan::parse_where("status").is_err());
    assert_eq!(cortex_plan::parse_set("a=1; b = x=y ;c=").unwrap(), vec![("a".into(), "1".into()), ("b".into(), "x=y".into()), ("c".into(), String::new())]);
    assert!(cortex_plan::parse_set("a").is_err() && cortex_plan::parse_set("").is_err() && cortex_plan::parse_set("a=1;a=2").is_err());
}

/// Live 2026-10-17, hermes3:8b under the JSON schema: `get(db="assay-suppliers")` - the table went
/// into params because the schema allowed any param key, so every plan failed "wrong number of
/// operands". The schema closes the param names to the v3 ones the mapper reads and shapes the operand.
#[test]
fn the_ast_schema_leaves_no_room_for_a_table_in_params() {
    let s = cortex_plan::ast_schema();
    let item = &s["properties"]["stages"]["items"];
    let params = &item["properties"]["params"];
    assert_eq!(params["additionalProperties"], json!(false), "params must be a closed set: {params}");
    let names: Vec<&str> = params["properties"].as_object().unwrap().keys().map(String::as_str).collect();
    for k in ["limit", "fields", "where", "q", "by", "dir", "op", "y", "kind", "chart", "x", "title", "unit", "set"] {
        assert!(names.contains(&k), "{k} missing from {names:?}");
    }
    assert!(!names.contains(&"db"), "db is an operand, never a param");
    let required: Vec<&str> = item["required"].as_array().unwrap().iter().filter_map(Value::as_str).collect();
    assert!(required.contains(&"operand"), "the operand is always written (empty when the stage takes none)");
    assert_eq!(item["properties"]["operand"]["pattern"], json!("^(db:[A-Za-z0-9_.-]+)?$"));
}

/// Live 2026-10-17 after the closed schema: hermes3:8b fills every param it may, so a count came
/// as aggregate(op="count", y="") and the mapper read "" as a column name and refused. An empty
/// param is an unset one.
#[test]
fn an_empty_param_is_an_unset_one() {
    let st = cortex_plan::stages_of(&json!({"stages": [
        {"op": "get", "operand": "db:t", "params": {"limit": 5, "fields": ""}},
        {"op": "filter", "operand": "", "params": {"where": "status eq next", "q": ""}},
        {"op": "aggregate", "operand": "", "params": {"op": "count", "y": "", "by": ""}}]})).unwrap();
    let p = cortex_plan::plan(None, &st).expect("a count with empty y and by plans");
    assert_eq!(p.agg, Some(("count".to_string(), None, None)), "{:?}", p.agg);
    assert!(p.q.is_none() && p.fields.is_empty());
}

/// One opcode's declaration in the organ's registry (cortex-opcodes.ts), read from the source:
/// (operand min, operand namespaces, param names, required param names). Spread param sets
/// (MUTATION_PARAMS) are not read: the plan schema never offers dry_run, commit or idempotency_key.
fn registry_op(name: &str) -> (u32, Vec<String>, Vec<String>, Vec<String>) {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../cortex/server/cortex-opcodes.ts");
    let src = std::fs::read_to_string(path).unwrap();
    let reg = &src[src.find("export const CORTEX_OPCODES").unwrap()..];
    let at = reg.find(&format!("name: '{name}'")).unwrap_or_else(|| panic!("{name} is not in the registry"));
    let block = &reg[at..];
    let block = &block[..block[1..].find("name: '").map_or(block.len(), |e| e + 1)];
    let ops = &block[block.find("operands: {").unwrap()..];
    let min: u32 = ops["operands: { min: ".len()..].split(',').next().unwrap().trim().parse().unwrap();
    let ns = &ops[ops.find('[').unwrap() + 1..ops.find(']').unwrap()];
    let ns = ns.split(',').map(|n| n.trim().trim_matches('\'').to_string()).filter(|n| !n.is_empty()).collect();
    let (mut params, mut required) = (vec![], vec![]);
    for line in block.lines().map(str::trim) {
        if let Some((k, rest)) = line.split_once(": { type: '") {
            params.push(k.to_string());
            if rest.contains("required: true") {
                required.push(k.to_string());
            }
        }
    }
    (min, ns, params, required)
}

/// Organ probe 2026-10-17: the flat schema offered every param and a db: operand on every stage, but
/// the organ's registry is per opcode - filter(db:todos, ...) is namespace_not_accepted, filter(limit=0)
/// unknown_param, aggregate(by=status) missing_required_param. A model that fills what it may (e742ad1,
/// e3d6898) writes exactly those. Each opcode's branch offers only what the registry declares for it.
#[test]
fn the_ast_schema_offers_each_opcode_only_what_the_registry_takes() {
    let s = cortex_plan::ast_schema();
    let branches = s["properties"]["stages"]["items"]["anyOf"].as_array().expect("one anyOf branch per opcode");
    let ops: Vec<&str> = branches.iter().filter_map(|b| b["properties"]["op"]["const"].as_str()).collect();
    assert_eq!(ops, ["get", "filter", "rank", "aggregate", "show", "insert", "update", "delete"]);
    for b in branches {
        let op = b["properties"]["op"]["const"].as_str().unwrap();
        let (min, ns, params, required) = registry_op(op);
        assert_eq!(b["additionalProperties"], json!(false), "{op}: {b}");
        let p = &b["properties"]["params"];
        assert_eq!(p["additionalProperties"], json!(false), "{op}: params are closed: {p}");
        for k in p["properties"].as_object().unwrap().keys() {
            assert!(params.contains(k), "{op}: the schema offers `{k}`, the registry takes {params:?}");
        }
        let req: Vec<&str> = p["required"].as_array().into_iter().flatten().filter_map(Value::as_str).collect();
        for k in &required {
            assert!(req.contains(&k.as_str()), "{op}: the registry requires `{k}`, the schema lets it out: {p}");
            assert!(p["properties"][k].get("enum").is_some() || p["properties"][k].get("minLength").is_some(),
                    "{op}: a required `{k}` is never \"\" (e3d6898 reads \"\" as unset): {p}");
        }
        let operand = &b["properties"]["operand"];
        // the lexer's dotted id: a dot only between two segments (organ probe: db:a..b and db:.a are syntax errors)
        if !ns.contains(&"db".to_string()) {
            assert_eq!(operand, &json!({"const": ""}), "{op} takes no db: operand ({ns:?})");
        } else if min >= 1 {
            assert_eq!(operand["pattern"], json!(DB), "{op} needs its db: table");
        } else {
            assert_eq!(operand["pattern"], json!(DB_OR_NONE), "{op} takes a db: table or none");
        }
    }
}

const DB: &str = "^db:[A-Za-z0-9_-]+(\\.[A-Za-z0-9_-]+)*$";
const DB_OR_NONE: &str = "^(db:[A-Za-z0-9_-]+(\\.[A-Za-z0-9_-]+)*)?$";

/// Organ probe 2026-10-17: a stage with a db: operand has open params at the organ, so
/// get(db:todos, where="status eq open") | aggregate(op="count") is valid there - and the mapper,
/// reading only limit and fields on get, dropped the where and counted every row as KEAP's number.
/// A param the mapper does not read is refused by name, never dropped.
#[test]
fn a_param_the_mapper_does_not_read_is_refused_not_dropped() {
    let stage = |op: &str, operand: Option<&str>, params: Value| cortex_plan::Stage {
        op: op.into(), operand: operand.map(str::to_string), params: params.as_object().unwrap().clone() };
    for (st, key) in [
        (vec![stage("get", Some("db:todos"), json!({"where": "status eq open"})), stage("aggregate", None, json!({"op": "count"}))], "where"),
        (vec![stage("aggregate", Some("db:todos"), json!({"op": "count", "where": "status eq open"}))], "where"),
        (vec![stage("get", Some("db:todos"), json!({"colour": "red"}))], "colour"),
        (vec![stage("get", Some("db:todos"), json!({})), stage("show", None, json!({"kind": "chart", "by": "status"}))], "by"),
    ] {
        let err = cortex_plan::plan(None, &st).err().unwrap_or_else(|| panic!("{key} was dropped: {st:?}"));
        assert!(err.contains(&format!("takes no {key}=: it would be dropped, not run")), "the refusal names {key}: {err}");
    }
    // the card is the gate: a write's dry_run and commit are read as nothing, on purpose (module doc)
    let w = vec![stage("get", Some("db:todos"), json!({})), stage("filter", None, json!({"where": "title eq Review"})),
                 stage("delete", Some("db:todos"), json!({"dry_run": true}))];
    assert!(cortex_plan::plan(None, &w).is_ok());
}

/// The organ's own words for a refusal (cortex-lang.ts issue()): a generic message, the useful part in
/// `detail` and `stage`. The repair round forwarded only `message`, so the model heard "required
/// parameter is missing" with no opcode and no key, and failed the same way again.
#[test]
fn the_repair_round_hears_which_stage_and_key_the_organ_refused() {
    let bad = "get(db:todos) | filter(where=\"status eq open\", limit=5) | aggregate(by=\"status\")";
    let good = "get(db:todos, limit=5) | filter(where=\"status eq open\")";
    let goods = known(&cases());
    let (organ_url, _) = listen(Box::new(move |_, _, body, _| {
        let src = serde_json::from_str::<Value>(body).unwrap()["source"].as_str().unwrap_or("").to_string();
        if src == bad {
            let errs = json!([
                {"code": "unknown_param", "severity": "error", "message": "unknown parameter for this opcode", "stage": 1,
                 "offset": 40, "length": 7, "line": 1, "column": 41, "detail": {"opcode": "filter", "key": "limit", "allowed": ["q", "where"]}},
                {"code": "missing_required_param", "severity": "error", "message": "required parameter is missing", "stage": 2,
                 "offset": 57, "length": 22, "line": 1, "column": 58, "detail": {"opcode": "aggregate", "key": "op"}}]);
            return (200, json!({"success": true, "data": {"valid": false, "ast": null, "errors": errs, "warnings": []}}).to_string());
        }
        let (s, st, h, e) = goods.iter().find(|k| k.0 == src).cloned().unwrap_or((src.clone(), json!([]), String::new(), vec!["unknown".into()]));
        (200, report(&s, &st, &h, &e))
    }));
    let rig = rig("detail", binding("mistral-eu", false), vec![say(bad), say(good), say("done")], Some(organ_url));
    turn(&rig, None, "open todos");
    let repair = models_said(&rig)[1]["messages"].as_array().unwrap().last().unwrap()["content"].as_str().unwrap().to_string();
    for want in ["unknown_param", "filter()", "`limit`", "allowed: q, where", "missing_required_param", "aggregate()", "`op`", "stage 2", "stage 3"] {
        assert!(repair.contains(want), "the repair names {want}: {repair}");
    }
}

/// The mapper's refusals are the repairable kind ("no column `stat` in Todos; columns: ..."), the
/// commonest small-model slip, but only the organ's got the repair round: a wrong column fell back.
#[test]
fn a_mapper_refusal_gets_the_repair_round() {
    let bad = "get(db:todos) | filter(where=\"stat eq open\")";
    let good = "get(db:todos, limit=5) | filter(where=\"status eq open\")";
    let mut k = known(&cases());
    k.push((bad.into(), json!([{"op": "get", "operand": "db:todos", "params": {}}, {"op": "filter", "params": {"where": "stat eq open"}}]),
            cortex_plan::REGISTRY_HASH.into(), vec![]));
    let (organ_url, _) = organ(k);
    let rig = rig("maprepair", binding("mistral-eu", false), vec![say(bad), say(good), say("done")], Some(organ_url));
    let (session, _) = turn(&rig, None, "open todos");
    let said = models_said(&rig);
    assert!(said[1].get("tools").is_none() && said[1].to_string().contains("no column `stat` in Todos"), "the repair hears the mapper: {}", said[1]);
    let ev = tools(&rig, &session);
    let last = ev.iter().rev().find(|(t, _)| t.ends_with("tool_result:cortex_plan")).unwrap();
    assert_eq!(last.1["valid"], json!(true), "{ev:?}");
    assert!(ev.iter().any(|(t, v)| t.ends_with("tool_use:query_rows") && v["args"]["limit"] == 5), "the repaired plan ran: {ev:?}");

    // free text skips the closed schema and a db: stage's params are open at the organ, so a foreign
    // param reaches the mapper: refused twice, the turn falls back, never runs with the where dropped
    let foreign = "get(db:todos, where=\"status eq open\") | aggregate(op=\"count\")";
    let mut k = known(&cases());
    k.push((foreign.into(), json!([{"op": "get", "operand": "db:todos", "params": {"where": "status eq open"}},
            {"op": "aggregate", "params": {"op": "count"}}]), cortex_plan::REGISTRY_HASH.into(), vec![]));
    let (organ_url, _) = organ(k);
    let fr = self::rig("foreign", binding("mistral-eu", false), vec![say(foreign), say(foreign), say("done")], Some(organ_url));
    let (session, _) = turn(&fr, None, "open todos");
    let why = "get() takes no where=: it would be dropped, not run";
    let said = models_said(&fr);
    assert!(said[1].get("tools").is_none() && said[1].to_string().contains(why), "the repair hears the refusal: {}", said[1]);
    assert!(said[2].get("tools").is_some(), "the fallback is plain tool calling");
    let ev = tools(&fr, &session);
    let last = ev.iter().rev().find(|(t, _)| t.ends_with("tool_result:cortex_plan")).unwrap();
    assert!(last.1["fallback"].as_str().is_some_and(|f| f.contains(why)), "fallback {}", last.1);
    assert!(!ev.iter().any(|(t, _)| t.ends_with("tool_use:query_rows")), "a refused plan runs nothing: {ev:?}");
}

/// Organ probe 2026-10-17: a free-text answer (Ollama MLX, a cloud row) is read by extract(), and its
/// first line was the plan - so a fenced pipeline split over lines ran as its first stage alone, valid
/// and wrong, and a line of prose before it burned the repair round.
#[test]
fn a_free_text_plan_is_read_whole() {
    let three = "```\nget(db:todos)\n| filter(where=\"status eq open\")\n| show(kind=\"chart\", chart=\"bar\")\n```";
    assert_eq!(cortex_plan::extract(three), "get(db:todos) | filter(where=\"status eq open\") | show(kind=\"chart\", chart=\"bar\")");
    assert_eq!(cortex_plan::extract("Here is the plan:\n\nget(db:todos, limit=5) | rank(by=\"amount\")\nThat lists them."),
               "get(db:todos, limit=5) | rank(by=\"amount\")");
    assert_eq!(cortex_plan::extract("get(db:todos)"), "get(db:todos)");
}

/// The lexer types a bare -?\d+ as int and allows only ASCII [A-Za-z0-9_/-] in a bare word: rank(by=počet),
/// filter(q=2024) and show(title=2024) are refused (probe 2026-10-17). The primer teaches the quoted form only.
#[test]
fn the_primer_quotes_every_string_value() {
    let p = cortex_plan::primer(cortex_plan::Engine::Free, "- todos \"Todos\": title:text");
    for line in p.lines().filter(|l| l.contains('(') && !l.starts_with("Tables")) {
        let (mut quoted, mut depth, chars): (bool, i32, Vec<char>) = (false, 0, line.chars().collect());
        for (i, c) in chars.iter().enumerate() {
            match c {
                '"' => quoted = !quoted,
                '(' if !quoted => depth += 1,
                ')' if !quoted => depth -= 1,
                '=' if !quoted && depth > 0 => {
                    let next = chars.get(i + 1).copied().unwrap_or(' ');
                    assert!(next == '"' || next.is_ascii_digit() || next == 'N', "a bare value after `=`: {line}");
                }
                _ => {}
            }
        }
    }
}

/// A model writes the where mini-syntax as it writes SQL or JSON: 'open' in single quotes (kept, so it
/// matched nothing), `amount > 5`, `status = open` and `Status EQ open` (all refused) - probe 2026-10-17.
#[test]
fn a_where_reads_the_shapes_a_model_writes() {
    let w = |s: &str| cortex_plan::parse_where(s).unwrap_or_else(|e| panic!("{s}: {e}"));
    assert_eq!(w("status eq 'open'"), ("status".into(), "eq".into(), json!("open")));
    assert_eq!(w("amount > 5"), ("amount".into(), "gt".into(), json!("5")));
    assert_eq!(w("amount < 5").1, "lt");
    assert_eq!(w("status = open"), ("status".into(), "eq".into(), json!("open")));
    assert_eq!(w("status != done").1, "neq");
    assert_eq!(w("Status EQ open"), ("Status".into(), "eq".into(), json!("open")));
    // query_rows has no inclusive lt or gt: >= is refused with the syntax, never read as >
    assert!(cortex_plan::parse_where("amount >= 5").is_err());
}

/// Every plan fallback said why in free text only, so a bench could not tell the organ being down
/// (no verdict on the model) from the model writing a plan nothing runs: fallback_kind says which.
#[test]
fn a_fallback_says_whether_the_model_or_the_estate_failed() {
    let dead = { let l = TcpListener::bind("127.0.0.1:0").unwrap(); format!("http://{}", l.local_addr().unwrap()) };
    let rig1 = rig("kinddown", binding("ollama", true), vec![say("{\"stages\": [{\"op\": \"get\", \"operand\": \"db:todos\", \"params\": {}}]}"),
                   say("done")], Some(dead));
    let (s1, _) = turn(&rig1, None, "todos");
    let r1: Vec<Value> = tools(&rig1, &s1).into_iter().filter(|(t, _)| t.ends_with("tool_result:cortex_plan")).map(|e| e.1).collect();
    assert_eq!(r1.last().unwrap()["fallback_kind"], "infra", "{r1:?}");
    let (organ_url, _) = organ(known(&cases()));
    let rig2 = rig("kindmodel", binding("ollama", true), vec![say("not json at all"), say("done")], Some(organ_url));
    let (s2, _) = turn(&rig2, None, "todos");
    let r2: Vec<Value> = tools(&rig2, &s2).into_iter().filter(|(t, _)| t.ends_with("tool_result:cortex_plan")).map(|e| e.1).collect();
    assert_eq!(r2.last().unwrap()["fallback_kind"], "model", "{r2:?}");
}

/// tools/iris-bench.py compares a plan to its expectation up to how it names the table: the plan row
/// says which table the mapper resolved, by the name the model said, its id and its title.
#[test]
fn a_plan_row_names_the_table_it_resolved() {
    let all = cases();
    let c = all.iter().find(|c| c["name"] == "a title and labels resolve, rank orders and cuts").unwrap();
    let (organ_url, _) = organ(known(&all));
    let rig = rig("tablerow", binding("ollama", true), vec![say(&json!({"stages": c["stages"]}).to_string()), say("done")], Some(organ_url));
    let (session, _) = turn(&rig, None, "todos by amount");
    let ev = tools(&rig, &session);
    let last = ev.iter().rev().find(|(t, _)| t.ends_with("tool_result:cortex_plan")).unwrap();
    assert_eq!(last.1["table"], json!({"said": "Todos", "id": "todos", "title": "Todos"}), "{ev:?}");
    // The plan's catalogue: lean (key:kind) unless NOS_CORTEX_CATALOGUE=rich; the row says which (iris-bench reads it).
    let prompt = |r: &Rig| models_said(r)[0]["messages"][0]["content"].as_str().unwrap().to_string();
    let used = |r: &Rig, s: &str| tools(r, s).into_iter().find(|(t, _)| t.ends_with("tool_use:cortex_plan")).unwrap().1["catalogue"].clone();
    assert!(prompt(&rig).contains("- todos \"Todos\": title:text, status:select, amount:number, track:text\n"), "{}", prompt(&rig));
    assert_eq!(used(&rig, &session), "lean");
    let (organ_url, _) = organ(known(&all));
    let rich = rig_cx("tablerich", binding("ollama", true), vec![say(&json!({"stages": c["stages"]}).to_string()), say("done")],
                      Some(Cortex { url: organ_url, token: "cx-ro-token".into(), rich_catalogue: true, intents: None }), vec![]);
    let (s2, _) = turn(&rich, None, "todos by amount");
    assert!(prompt(&rich).contains("status:select \"Status\" (open|done)"), "{}", prompt(&rich));
    assert_eq!(used(&rich, &s2), "rich");
    // The shell's catalogue (its marks) is rich either way.
    let s = UnixStream::connect(&rig.sock).unwrap();
    s.set_read_timeout(Some(std::time::Duration::from_secs(10))).unwrap();
    let mut r = BufReader::new(s.try_clone().unwrap());
    (&s).write_all(encode(&ToThalamus::Catalogue).as_bytes()).unwrap();
    let tables = loop {
        match next(&mut r) {
            Some(ToShell::Catalogue { tables, .. }) => break tables,
            Some(_) => continue,
            None => panic!("no catalogue"),
        }
    };
    let status = tables.iter().find(|t| t.id == "todos").unwrap().columns.iter().find(|c| c.key == "status").unwrap();
    assert_eq!((status.label.as_deref(), status.options.as_deref()), (Some("Status"), Some(&["open".to_string(), "done".into()][..])));
}

/// Live 2026-10-18 the cortex path fell 85->70/283 with 31 bare `get(db:t, limit=N)` plans: the plan
/// saw the first 12 tables in KEAP's order, so a table the person named could be cut. A table the turn
/// names (id, title or column label, folded) goes in first; the plan row says which catalogue it saw.
#[test]
fn a_table_the_turn_names_is_in_the_plan_catalogue_even_when_13th() {
    let all = cases();
    let c = all.iter().find(|c| c["name"] == "a title and labels resolve, rank orders and cuts").unwrap();
    let (organ_url, _) = organ(known(&all));
    // todos, engram, party, nine fillers: the stock table is the 13th in KEAP's order
    let mut extra: Vec<(Value, Value)> = (1..=9).map(|i| (table(&format!("filler-{i:02}"), &format!("Filler {i}"),
        json!([{"key": "x", "label": "X", "kind": "text"}])), json!([]))).collect();
    extra.push((table("whs-stock", "Skladové zásoby", json!([{"key": "bin", "label": "Regál", "kind": "text"},
        {"key": "qty", "label": "Qty", "kind": "number"}])), json!([])));
    let plan = say(&json!({"stages": c["stages"]}).to_string());
    let cx = || Some(Cortex { url: organ_url.clone(), token: "cx-ro-token".into(), rich_catalogue: false, intents: None });
    let catalogue = |r: &Rig| models_said(r)[0]["messages"][0]["content"].as_str().unwrap().split_once("Tables:\n").unwrap().1.to_string();
    let row = |r: &Rig, s: &str| tools(r, s).into_iter().find(|(t, _)| t.ends_with("tool_use:cortex_plan")).unwrap().1;
    // by its title (diacritics folded), by a column label, by its id
    for (i, text) in ["Nakresli graf SKLADOVE zasoby podle bin", "rows by Regál", "chart of whs-stock"].iter().enumerate() {
        let rig = rig_cx(&format!("named{i}"), binding("ollama", true), vec![plan.clone(), say("done")], cx(), extra.clone());
        let (session, _) = turn(&rig, None, text);
        let cat = catalogue(&rig);
        assert!(cat.starts_with("- whs-stock \"Skladové zásoby\": bin:text, qty:number\n"), "{text}: the named table goes first: {cat}");
        assert_eq!(cat.lines().count(), 12, "{text}: the cap stays 12: {cat}");
        let r = row(&rig, &session);
        let ids: Vec<&str> = r["catalogue_tables"].as_array().unwrap().iter().filter_map(Value::as_str).collect();
        assert_eq!((ids.len(), ids[0], ids[1]), (12, "whs-stock", "todos"), "{text}: named first, then KEAP's order: {ids:?}");
        assert!(!ids.contains(&"filler-09"), "{text}: the last in order is the one cut: {ids:?}");
        assert_eq!(r["catalogue_digest"], json!(cortex_plan::sha256_hex(&cat)[..16]), "{text}: the digest is of the table lines");
    }
    // A turn that names none keeps today's order: the first 12.
    let rig = rig_cx("named-none", binding("ollama", true), vec![plan, say("done")], cx(), extra);
    let (session, _) = turn(&rig, None, "something else");
    let r = row(&rig, &session);
    let ids: Vec<&str> = r["catalogue_tables"].as_array().unwrap().iter().filter_map(Value::as_str).collect();
    assert_eq!((ids.len(), ids[0], ids[11]), (12, "todos", "filler-09"), "{ids:?}");
}

const INTENTS: [&str; 4] = ["chart", "kpi", "top-n", "insert-row"];
/// Kinds where cortex lost to tools (nos-assay 2026-10-18/19): never planned, whatever the words.
const NEVER_CORTEX: [&str; 3] = ["injection", "cannot-see", "edit-row"];

/// iris_plan: hybrid routes a turn by its own words before any model call. The 284 standard-tier
/// prompts of nos-assay (frozen in state/fixtures/iris-route/prompts.yml) against their kinds: each
/// cortex intent is recalled at 0.9 or more, and no injection, cannot-see or edit-row turn plans.
#[test]
fn the_route_recalls_the_cortex_intents_and_never_plans_the_losing_kinds() {
    route_matrix("prompts.yml", 0.9);
}

/// The same matrix on prompts route() was not tuned on: tools/assay-gen.py under a new seed, every
/// case whose text is in prompts.yml dropped (state/fixtures/iris-route/holdout.yml). Recall 0.85.
#[test]
fn the_route_holds_on_prompts_it_was_not_tuned_on() {
    route_matrix("holdout.yml", 0.85);
}

fn route_matrix(fixture: &str, floor: f64) {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../state/fixtures/iris-route").join(fixture);
    let doc: Value = serde_yaml_ng::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let intents: Vec<String> = INTENTS.iter().map(|s| s.to_string()).collect();
    // kind -> (routed intent or "tools" -> n)
    let mut m: std::collections::BTreeMap<String, std::collections::BTreeMap<String, usize>> = Default::default();
    let mut wrong = vec![];
    for c in doc["cases"].as_array().unwrap() {
        let kind = c["kind"].as_str().unwrap();
        let routes: Vec<_> = c["turns"].as_array().unwrap().iter().map(|t| cortex_plan::route(t.as_str().unwrap(), &intents)).collect();
        let got = routes.iter().find_map(|(r, i, _)| (*r == "cortex").then(|| i.unwrap())).unwrap_or("tools");
        *m.entry(kind.into()).or_default().entry(got.into()).or_default() += 1;
        if got != if INTENTS.contains(&kind) { kind } else { "tools" } {
            wrong.push(format!("{kind} -> {got}: {} {:?}", c["turns"], routes.iter().map(|r| &r.2).collect::<Vec<_>>()));
        }
    }
    eprintln!("route confusion on {fixture} (kind: routed -> n):");
    m.iter().for_each(|(k, v)| eprintln!("  {k:<14} {v:?}"));
    wrong.iter().for_each(|w| eprintln!("  miss {w}"));
    for k in INTENTS {
        let row = &m[k];
        let recall = row.get(k).copied().unwrap_or(0) as f64 / row.values().sum::<usize>() as f64;
        assert!(recall >= floor, "{fixture} {k}: recall {recall:.2} < {floor}: {row:?}");
    }
    for k in NEVER_CORTEX {
        assert_eq!(m[k].keys().collect::<Vec<_>>(), vec!["tools"], "{fixture} {k} is never planned: {:?}", m[k]);
    }
}

fn hybrid_rig(name: &str, models: Vec<String>) -> Rig {
    let (organ_url, _) = organ(known(&cases()));
    rig_cx(name, binding("ollama", true), models, Some(Cortex { url: organ_url, token: "cx-ro-token".into(), rich_catalogue: false,
        intents: Some(INTENTS.iter().map(|s| s.to_string()).collect()) }), vec![])
}

#[test]
fn hybrid_a_chart_turn_plans_and_the_ledger_says_cortex() {
    let all = cases();
    let c = all.iter().find(|c| c["name"] == "a title and labels resolve, rank orders and cuts").unwrap();
    let rig = hybrid_rig("hy-chart", vec![say(&json!({"stages": c["stages"]}).to_string()), say("done")]);
    let (session, got) = turn(&rig, None, "Nakresli sloupcový graf todos podle status");
    assert!(matches!(got.last(), Some(ToShell::Text { text, .. }) if text == "done"), "{got:?}");
    let said = models_said(&rig);
    assert!(said[0].get("tools").is_none() && said.len() == 2, "one plan call, then the answer: {said:?}");
    let ev = tools(&rig, &session);
    let route: Vec<&Value> = ev.iter().filter(|(t, _)| t == "agent_tool_result:route").map(|e| &e.1).collect();
    assert_eq!(route.len(), 1, "one route row per turn: {ev:?}");
    assert_eq!((&route[0]["route"], &route[0]["intent"]), (&json!("cortex"), &json!("chart")), "{}", route[0]);
    assert!(route[0]["matched"].as_array().is_some_and(|m| !m.is_empty()), "the words it matched: {}", route[0]);
    assert!(ev.iter().any(|(t, v)| t == "agent_tool_result:cortex_plan" && v["valid"] == true), "the plan ran: {ev:?}");
}

#[test]
fn hybrid_an_edit_turn_makes_no_plan_call_and_the_ledger_says_tools() {
    let rig = hybrid_rig("hy-edit", vec![say("done")]);
    let (session, _) = turn(&rig, None, "Nastav řádku Review status na done.");
    let said = models_said(&rig);
    assert!(said.len() == 1 && said[0].get("tools").is_some(), "no plan call: the turn is plain tool calling: {said:?}");
    let ev = tools(&rig, &session);
    assert!(ev.iter().all(|(t, _)| !t.ends_with(":cortex_plan")), "{ev:?}");
    let route: Vec<&Value> = ev.iter().filter(|(t, _)| t == "agent_tool_result:route").map(|e| &e.1).collect();
    assert_eq!(route.len(), 1, "{ev:?}");
    assert_eq!((&route[0]["route"], &route[0]["intent"]), (&json!("tools"), &Value::Null), "{}", route[0]);
}

#[test]
fn a_json_schema_server_is_planned_constrained() {
    use thalamus::cortex_plan::Engine;
    // Ollama GGUF and vLLM both honour response_format json_schema; anything else is free text.
    assert_eq!(Engine::of("ollama"), Engine::JsonSchema);
    assert_eq!(Engine::of("vllm"), Engine::JsonSchema);
    assert_eq!(Engine::of("mistral-eu"), Engine::Free);
}
