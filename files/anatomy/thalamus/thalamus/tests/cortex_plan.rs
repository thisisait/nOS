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
fn keap() -> (String, Seen) {
    let tables = vec![
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
    let (keap_url, keap) = keap();
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
        cortex: cortex.map(|url| Cortex { url, token: "cx-ro-token".into() }),
    };
    let sock = d.join("t.sock");
    let listener = serve::bind(&sock).unwrap();
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
        if c.get("errors").is_some() {
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
        assert_eq!(uses[0], &json!({"source": c["pipeline"], "engine": "ollama-json-schema", "constrained": true}), "{name}");
        let results: Vec<&Value> = ev.iter().filter(|(t, _)| t.ends_with("tool_result:cortex_plan")).map(|e| &e.1).collect();
        let last = *results.last().unwrap_or_else(|| panic!("{name}: no cortex_plan result: {ev:?}"));
        let said = models_said(&rig);
        let ran: Vec<Value> = ev.iter().filter(|(t, _)| t.starts_with("agent_tool_use:") && !t.ends_with(":cortex_plan") && !t.ends_with(":show_source"))
            .map(|(t, v)| json!([t.rsplit(':').next().unwrap(), v["args"]])).collect();
        if let Some(why) = c["refused"].as_str() {
            assert!(last["fallback"].as_str().is_some_and(|f| f.contains(why)), "{name}: fallback {last}");
            let heard = said[1 + usize::from(c.get("errors").is_some())].to_string();
            assert!(heard.contains(&format!("[thalamus] cortex plan refused: {why}")), "{name}: the model hears why: {heard}");
            assert!(said[1..].iter().all(|b| b.get("tools").is_some()), "{name}: the fallback is plain tool calling");
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
    assert_eq!(uses[0], &json!({"source": "get(db:todos, colour=red)", "engine": "unconstrained", "constrained": false}), "the fence is stripped");
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
