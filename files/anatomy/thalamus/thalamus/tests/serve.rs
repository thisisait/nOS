//! `thalamus serve` against a fake KEAP and a fake model on loopback: the kernel
//! names the peer, the receptor's identity map names the person, and KEAP sees
//! that person and the proxy secret — which no log, ledger or model ever sees.

use nos_contract::renderers::Component;
use nos_contract::wire::{decode_to_shell, encode, Decision, Phase, ToShell, ToThalamus};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use thalamus::binding::Binding;
use thalamus::ledger::{Kind, Ledger};
use thalamus::serve::{self, Server};

const SECRET: &str = "s3cret-proxy-hop-7f1e";

/// Requests a fake listener saw: (head, body).
type Seen = Arc<Mutex<Vec<(String, String)>>>;

/// An HTTP/1.1 listener that answers the n-th request with the n-th body (the last repeats).
fn fake(bodies: Vec<String>) -> (String, Seen) {
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
            let len = head
                .lines()
                .find_map(|h| h.to_ascii_lowercase().strip_prefix("content-length:").map(|v| v.trim().parse().unwrap()))
                .unwrap_or(0);
            let mut body = vec![0; len];
            r.read_exact(&mut body).unwrap();
            s.lock().unwrap().push((head, String::from_utf8(body).unwrap()));
            // A body may lead with "!<status> " to answer with that status.
            let out = &bodies[n.min(bodies.len() - 1)];
            let (status, out) = match out.strip_prefix('!') {
                Some(rest) => rest.split_once(' ').unwrap(),
                None => ("200", out.as_str()),
            };
            write!(c, "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{out}", out.len())
                .unwrap();
        }
    });
    (url, seen)
}

#[derive(Clone, Default)]
struct Log(Arc<Mutex<Vec<u8>>>);
impl Write for Log {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

fn dir(name: &str) -> PathBuf {
    // Short: a unix socket path is capped near 104 bytes on macOS.
    let d = PathBuf::from(format!("/tmp/th-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    // bind()'s umask is process-wide: a dir made by a racing test thread is born 0600.
    std::fs::set_permissions(&d, std::fs::Permissions::from_mode(0o700)).unwrap();
    d
}

fn me() -> String {
    serve::login(unsafe { libc::getuid() }).expect("the test runs as a real login")
}

struct Rig {
    sock: PathBuf,
    ledger: PathBuf,
    log: Log,
    keap: Seen,
    model: Seen,
    srv: Arc<Server>,
}

fn rig(name: &str, map: serde_json::Value, keap_body: &str, model_bodies: Vec<String>) -> Rig {
    rig_n(name, map, vec![keap_body.to_string()], model_bodies)
}

fn rig_n(name: &str, map: serde_json::Value, keap_bodies: Vec<String>, model_bodies: Vec<String>) -> Rig {
    rig_full(name, map, keap_bodies, model_bodies, Some(local()))
}

/// A binding as the resolver makes it from the real register; rig_full points base_url at the fake.
fn bound(cell: &str, env: &[(&str, &str)]) -> Binding {
    let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../..");
    let register = std::fs::read_to_string(repo.join("state/habitat/llm-backends.yml")).unwrap();
    let cell = match cell {
        "iris" => std::fs::read_to_string(repo.join("files/anatomy/agents/iris/agent.yml")).unwrap(),
        inline => inline.to_string(),
    };
    match thalamus::binding::decide(&cell, &register, |k| env.iter().find(|(n, _)| *n == k).map(|(_, v)| v.to_string())) {
        Ok(thalamus::binding::Decision::Bound(b)) => b,
        other => panic!("the rig's binding did not bind: {other:?}"),
    }
}

/// A keyless local cell on ollama.
fn local() -> Binding {
    bound("name: c\nmodel: {primary: openai-local-sonnet, backend: ollama}\ngdpr: {processors: [{name: on-device}]}\n",
          &[("NOS_ARMED_BACKENDS", "ollama"), ("NOS_LOCAL_MODEL", "qwen3:14b")])
}

const KEY: &str = "sk-eu-model-key-91c2";

/// Iris's cloud binding (mistral-eu), keyed.
fn cloud() -> Binding {
    bound("iris", &[("NOS_ARMED_BACKENDS", "mistral-eu"), ("NOS_MISTRAL_MODEL", "mistral-large-latest"),
                    ("nos:mistral_api_key", KEY)])
}

const SHORT: &str = "# Imprint (short)\nSHORT-IMPRINT-MARK\n";
const FULL: &str = "# Imprint\nFULL-IMPRINT-MARK\n";

fn rig_full(name: &str, map: serde_json::Value, keap_bodies: Vec<String>, model_bodies: Vec<String>,
            bound: Option<Binding>) -> Rig {
    let d = dir(name);
    std::fs::write(d.join("IMPRINT.short.md"), SHORT).unwrap();
    std::fs::write(d.join("IMPRINT.md"), FULL).unwrap();
    let map_path = d.join("identity-map.yml");
    std::fs::write(&map_path, map.to_string()).unwrap();
    let (keap_url, keap) = fake(keap_bodies);
    let (model_url, model) = fake(model_bodies);
    let log = Log::default();
    let ledger = d.join("ledger.db");
    let srv = Server {
        map: map_path,
        keap_url,
        secret: SECRET.into(),
        ledger: Mutex::new(Ledger::open(&ledger).unwrap()),
        binding: bound.map(|b| Binding { base_url: model_url, ..b }).ok_or_else(|| "iris is disarmed".into()),
        repo: d.clone(),
        reader_secs: 2,
        tier1: vec!["nos-admins".into()],
        log: Mutex::new(Box::new(log.clone())),
    };
    let sock = d.join("t.sock");
    let listener = serve::bind(&sock).unwrap();
    let srv = Arc::new(srv);
    let run = srv.clone();
    std::thread::spawn(move || serve::run(listener, run));
    Rig { sock, ledger, log, keap, model, srv }
}

/// A client that fails instead of hanging when serve forgets to answer or to close.
fn connect(sock: &std::path::Path) -> UnixStream {
    let s = UnixStream::connect(sock).unwrap();
    s.set_read_timeout(Some(std::time::Duration::from_secs(10))).unwrap();
    s
}

/// The next message, activity included.
fn raw(r: &mut BufReader<UnixStream>) -> Option<ToShell> {
    let mut line = String::new();
    (r.read_line(&mut line).unwrap() > 0).then(|| decode_to_shell(&line))
}

/// The next message the conversation is made of; activity is the eye's, not the log's.
fn next(r: &mut BufReader<UnixStream>) -> Option<ToShell> {
    loop {
        match raw(r) {
            Some(ToShell::Activity { .. }) => continue,
            m => return m,
        }
    }
}

fn tool_call(args: &str) -> String {
    call("search_rows", args)
}

fn call(tool: &str, args: &str) -> String {
    serde_json::json!({"choices": [{"message": {"role": "assistant", "content": null, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": tool, "arguments": args}}]}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 4}})
    .to_string()
}

fn answer(text: &str) -> String {
    serde_json::json!({"choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 3}})
    .to_string()
}

const ROWS: &str = r#"{"success": true, "data": {"rows": [
    {"id": "r1", "values": {"title": "Alpha one", "status": "open"}},
    {"id": "r2", "values": {"title": "beta"}}]}}"#;

#[test]
fn serve_refuses_a_peer_the_identity_map_does_not_name() {
    let rig = rig("unmapped", serde_json::json!({"logins": {"someone-else": {"username": "bob", "groups": []}}}), ROWS,
        vec![answer("never")]);
    let mut r = BufReader::new(connect(&rig.sock));
    match next(&mut r) {
        Some(ToShell::Refused { reason }) => assert!(reason.contains("identity map"), "{reason}"),
        other => panic!("an unmapped peer must be refused, got {other:?}"),
    }
    assert!(next(&mut r).is_none(), "the refused connection is closed");
    assert!(rig.keap.lock().unwrap().is_empty(), "an unmapped peer reached KEAP");
    assert!(rig.model.lock().unwrap().is_empty(), "an unmapped peer reached the model");
}

#[test]
fn serve_refuses_a_map_it_cannot_read() {
    // username present, groups not a list: the receptor's loader refuses it, so does this one.
    let rig = rig("malformed", serde_json::json!({"logins": {me(): {"username": "alice", "groups": "nos-users"}}}), ROWS,
        vec![answer("never")]);
    let mut r = BufReader::new(connect(&rig.sock));
    assert!(matches!(next(&mut r), Some(ToShell::Refused { .. })));
    assert!(next(&mut r).is_none());
}

#[test]
fn serve_searches_as_the_mapped_person_and_never_spills_the_secret() {
    let map = serde_json::json!({"logins": {me(): {"username": "Alice Smith", "groups": ["nos-users", "nos-editors"]}}});
    let rig = rig("mapped", map, ROWS, vec![tool_call(r#"{"table": "todos", "q": "ALPHA"}"#), answer("Found one.")]);
    assert_eq!(std::fs::metadata(&rig.sock).unwrap().permissions().mode() & 0o777, 0o600);

    let mut s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    s.write_all(b"not json\n").unwrap();
    assert!(matches!(next(&mut r), Some(ToShell::Refused { .. })), "an undecodable line is refused, not dropped");
    s.write_all(encode(&ToThalamus::Turn { session: None, text: "find alpha".into() }).as_bytes()).unwrap();

    let session = match next(&mut r) {
        Some(ToShell::Session { session, actor, model_uri }) => {
            assert_eq!(actor, "user:alice-smith");
            assert_eq!(model_uri, "ollama-qwen3:14b");
            session
        }
        other => panic!("expected Session, got {other:?}"),
    };
    match next(&mut r) {
        Some(ToShell::Render { session: s2, component: Component::TableResults(t) }) => {
            assert_eq!(s2, session);
            assert_eq!(t.table, "todos");
            assert!(!t.projected, "substring search is not a projection");
            assert_eq!(t.columns, ["status", "title"]);
            assert_eq!(t.rows.len(), 1);
            assert_eq!(t.rows[0].__id, "r1");
        }
        other => panic!("expected Render table_results, got {other:?}"),
    }
    assert!(matches!(next(&mut r), Some(ToShell::Text { text, .. }) if text == "Found one."));
    drop(s);
    drop(r);

    let keap = rig.keap.lock().unwrap().clone();
    assert_eq!(keap.len(), 1);
    let head = keap[0].0.to_ascii_lowercase();
    assert!(head.starts_with("get /api/tables/todos/rows?limit=500 "), "{head}");
    for h in ["x-authentik-username: alice smith", "x-authentik-uid: alice-smith",
              "x-authentik-groups: nos-users,nos-editors", &format!("x-keap-proxy-secret: {SECRET}")] {
        assert!(head.contains(h), "KEAP did not get {h:?}:\n{head}");
    }
    let model = rig.model.lock().unwrap().clone();
    assert_eq!(model.len(), 2);
    assert!(model.iter().all(|(h, b)| !h.contains(SECRET) && !b.contains(SECRET)), "the model saw the proxy secret");
    assert!(model[1].1.contains("Alpha one"), "the tool result reaches the model");

    // The session ends when the connection does; the ledger then holds the whole turn.
    std::thread::sleep(std::time::Duration::from_millis(300));
    let log = String::from_utf8(rig.log.0.lock().unwrap().clone()).unwrap();
    assert!(log.contains("as Alice Smith"), "serve logs who it served:\n{log}");
    assert!(!log.contains(SECRET), "the proxy secret reached the log");
    let db = rusqlite::Connection::open(&rig.ledger).unwrap();
    let types: Vec<String> = db
        .prepare("SELECT type FROM events WHERE run_id = ?1 ORDER BY id").unwrap()
        .query_map([&session], |r| r.get(0)).unwrap().map(Result::unwrap).collect();
    assert_eq!(types, ["agent_session_start", "agent_message", "agent_tool_use", "agent_tool_result",
                       "agent_message", "agent_session_end"]);
    let dump: String = db
        .prepare("SELECT COALESCE(result_json, '') || task FROM events").unwrap()
        .query_map([], |r| r.get::<_, String>(0)).unwrap().map(Result::unwrap).collect();
    assert!(!dump.contains(SECRET), "the proxy secret reached the ledger");
}

#[test]
fn a_keyed_model_gets_the_bearer_and_nothing_else_sees_the_key() {
    let map = serde_json::json!({"logins": {me(): {"username": "alice", "groups": ["nos-users"]}}});
    let rig = rig_full("bearer", map, vec![ROWS.into()], vec![tool_call(r#"{"table": "todos", "q": "alpha"}"#),
        answer("Found.")], Some(cloud()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "find alpha");
    let session = session_of(&got);
    assert!(got.iter().any(|m| matches!(m, ToShell::Session { model_uri, .. } if model_uri == "mistral-eu-mistral-large-latest")));
    drop(s);
    drop(r);
    std::thread::sleep(std::time::Duration::from_millis(300));

    let model = rig.model.lock().unwrap().clone();
    assert_eq!(model.len(), 2);
    for (head, body) in &model {
        assert!(head.to_ascii_lowercase().contains(&format!("authorization: bearer {}", KEY.to_ascii_lowercase())), "{head}");
        assert!(!body.contains(KEY), "the key reached the model's messages");
    }
    let keap = rig.keap.lock().unwrap().clone();
    assert!(keap.iter().all(|(h, b)| !h.contains(KEY) && !b.contains(KEY)), "KEAP saw the model key");
    let log = String::from_utf8(rig.log.0.lock().unwrap().clone()).unwrap();
    assert!(!log.contains(KEY), "the model key reached the log:\n{log}");
    assert!(types_of(&rig.ledger, &session).len() >= 4, "the turn is in the ledger");
    // Every byte of the ledger and its journal, not one column: no table holds the key.
    for f in std::fs::read_dir(rig.ledger.parent().unwrap()).unwrap().map(|e| e.unwrap().path()) {
        if f.to_string_lossy().contains("ledger.db") {
            let bytes = std::fs::read(&f).unwrap();
            assert!(!bytes.windows(KEY.len()).any(|w| w == KEY.as_bytes()), "the model key reached {}", f.display());
        }
    }
}

#[test]
fn a_local_model_gets_no_authorization_header() {
    let rig = rig("nobearer", mapped(), ROWS, vec![answer("hi")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    turn(&s, &mut r, None, "hello");
    let model = rig.model.lock().unwrap().clone();
    assert!(model.iter().all(|(h, _)| !h.to_ascii_lowercase().contains("authorization:")), "{model:?}");
}

/// The system message of the first request the model saw.
fn system_prompt(rig: &Rig) -> String {
    let body: serde_json::Value = serde_json::from_str(&rig.model.lock().unwrap()[0].1).unwrap();
    assert_eq!(body["messages"][0]["role"], "system");
    body["messages"][0]["content"].as_str().unwrap().to_string()
}

#[test]
fn the_prompt_carries_the_imprint_the_binding_calls_for() {
    // Local model: the short imprint fits its window. Cloud (Mistral Large): the whole one.
    for (name, b, want, not) in [("implocal", local(), SHORT, FULL), ("impcloud", cloud(), FULL, SHORT)] {
        let rig = rig_full(name, mapped(), vec![ROWS.into()], vec![answer("hi")], Some(b));
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        turn(&s, &mut r, None, "hello");
        let p = system_prompt(&rig);
        assert!(p.starts_with(want), "{name}: the prompt does not lead with its imprint:\n{p}");
        assert!(!p.contains(not.lines().nth(1).unwrap()), "{name}: the other imprint rode along");
        assert!(p.contains("You are Iris. You act for Alice Smith and see only what they may see."), "{p}");
    }
}

#[test]
fn a_missing_imprint_refuses_the_turn_and_says_so() {
    for (name, b, file) in [("noimpl", local(), "IMPRINT.short.md"), ("noimpc", cloud(), "IMPRINT.md")] {
        let rig = rig_full(name, mapped(), vec![ROWS.into()], vec![answer("never")], Some(b));
        std::fs::write(rig.srv.repo.join(file), " \n").unwrap(); // empty is missing
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        let got = turn(&s, &mut r, None, "hello");
        match got.last() {
            Some(ToShell::Refused { reason }) => assert!(reason.contains(file), "{name}: {reason}"),
            other => panic!("{name}: a turn without its imprint must be refused, got {other:?}"),
        }
        assert!(rig.model.lock().unwrap().is_empty(), "{name}: the model was called without its imprint");
        let log = String::from_utf8(rig.log.0.lock().unwrap().clone()).unwrap();
        assert!(log.contains(file), "{name}: the log does not name the missing imprint:\n{log}");
    }
}

// --- increment 6: a write renderer cannot commit without the approval event ---

const POSTED: &str = r#"{"success": true, "data": {"id": "r1", "values": {"title": "Alpha one", "status": "done"}}}"#;

fn mapped() -> serde_json::Value {
    serde_json::json!({"logins": {me(): {"username": "Alice Smith", "groups": ["nos-users"]}}})
}

/// A person in a tier-1 group: the approvals and red-status controls answer them.
fn admin() -> serde_json::Value {
    serde_json::json!({"logins": {me(): {"username": "Alice Smith", "groups": ["nos-users", "nos-admins"]}}})
}

fn alice() -> serve::Person {
    serve::Person { username: "Alice Smith".into(), groups: vec!["nos-users".into()] }
}

fn types_of(ledger: &std::path::Path, session: &str) -> Vec<String> {
    let db = rusqlite::Connection::open(ledger).unwrap();
    let mut q = db.prepare("SELECT type FROM events WHERE run_id = ?1 ORDER BY id").unwrap();
    q.query_map([session], |r| r.get(0)).unwrap().map(Result::unwrap).collect()
}

/// One turn that proposes `values` for r1; returns (stream, reader, session, approval, diff).
fn propose(rig: &Rig) -> (UnixStream, BufReader<UnixStream>, String, String, nos_contract::renderers::RowDiffApproval) {
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    (&s).write_all(encode(&ToThalamus::Turn { session: None, text: "close alpha".into() }).as_bytes()).unwrap();
    let Some(ToShell::Session { session, .. }) = next(&mut r) else { panic!("no session") };
    let (approval, diff) = match next(&mut r) {
        Some(ToShell::ApprovalRequest { session: s2, approval, component: Component::RowDiffApproval(d) }) => {
            assert_eq!(s2, session);
            (approval, d)
        }
        other => panic!("expected ApprovalRequest row_diff_approval, got {other:?}"),
    };
    assert!(matches!(next(&mut r), Some(ToShell::Text { .. })), "the model's turn ends while the person decides");
    (s, r, session, approval, diff)
}

fn decide(s: &UnixStream, approval: &str, d: Decision) {
    let mut s = s;
    s.write_all(encode(&ToThalamus::ApprovalDecision { approval: approval.into(), decision: d, note: None }).as_bytes())
        .unwrap();
}

fn posts(rig: &Rig) -> Vec<(String, String)> {
    rig.keap.lock().unwrap().iter().filter(|(h, _)| h.starts_with("POST ")).cloned().collect()
}

const EDIT: &str = r#"{"table": "todos", "row_id": "r1", "values": {"status": "done", "title": "Alpha one"}}"#;

#[test]
fn approve_posts_the_approved_cells_once_as_the_person() {
    // The proposal's read, commit's re-read, then the POST.
    let rig = rig_n("approve", mapped(), vec![ROWS.into(), ROWS.into(), POSTED.into()],
        vec![call("propose_row_edit", EDIT), answer("Proposed.")]);
    let (s, mut r, session, approval, diff) = propose(&rig);
    assert_eq!(diff.table, "todos");
    assert_eq!(diff.row_id, "r1");
    // An unchanged cell is not part of the diff, and not part of the write.
    assert_eq!(diff.cells.len(), 1);
    assert_eq!((diff.cells[0].key.as_str(), &diff.cells[0].old, &diff.cells[0].new),
               ("status", &serde_json::json!("open"), &serde_json::json!("done")));
    assert!(posts(&rig).is_empty(), "a proposal wrote before the person decided");

    decide(&s, &approval, Decision::Approve);
    assert!(matches!(next(&mut r), Some(ToShell::Text { .. })), "the person hears the write landed");
    decide(&s, &approval, Decision::Approve);
    assert!(matches!(next(&mut r), Some(ToShell::Refused { .. })), "a second decision is refused");

    let p = posts(&rig);
    assert_eq!(p.len(), 1, "Approve POSTs exactly once");
    let head = p[0].0.to_ascii_lowercase();
    assert!(head.starts_with("post /api/tables/todos/rows "), "{head}");
    assert!(head.contains("x-authentik-username: alice smith") && head.contains(&format!("x-keap-proxy-secret: {SECRET}")));
    let body: serde_json::Value = serde_json::from_str(&p[0].1).unwrap();
    assert_eq!(body, serde_json::json!({"id": "r1", "values": {"status": "done"}}));
    drop((s, r));
    std::thread::sleep(std::time::Duration::from_millis(300));
    let t = types_of(&rig.ledger, &session);
    let req = t.iter().position(|x| x == "agent_approval_request").expect("ledger has the request");
    let dec = t.iter().position(|x| x == "agent_approval_decision").expect("ledger has the decision");
    assert!(req < dec);
}

#[test]
fn reject_never_posts() {
    let rig = rig_n("reject", mapped(), vec![ROWS.into(), POSTED.into()],
        vec![call("propose_row_edit", EDIT), answer("Proposed.")]);
    let (s, mut r, session, approval, _) = propose(&rig);
    decide(&s, &approval, Decision::Reject);
    assert!(matches!(next(&mut r), Some(ToShell::Text { .. })));
    drop((s, r));
    std::thread::sleep(std::time::Duration::from_millis(300));
    assert!(posts(&rig).is_empty(), "Reject wrote to KEAP");
    let t = types_of(&rig.ledger, &session);
    assert!(t.contains(&"agent_approval_request".into()) && t.contains(&"agent_approval_decision".into()), "{t:?}");
}

#[test]
fn a_decision_for_an_unknown_approval_is_refused() {
    let rig = rig_n("unknown", mapped(), vec![ROWS.into()], vec![answer("hi")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    decide(&s, "0b7e6f3a-2c1d-4e5f-8a9b-1c2d3e4f5a6b", Decision::Approve);
    assert!(matches!(next(&mut r), Some(ToShell::Refused { .. })));
    assert!(posts(&rig).is_empty());
}

#[test]
fn a_proposal_for_a_row_the_person_cannot_read_or_a_sharing_key_never_asks() {
    for (name, args) in [("absent", r#"{"table": "todos", "row_id": "nope", "values": {"status": "done"}}"#),
                         ("sharing", r#"{"table": "todos", "row_id": "r1", "values": {"__sharing": {"public": true}}}"#)] {
        let rig = rig_n(name, mapped(), vec![ROWS.into(), POSTED.into()],
            vec![call("propose_row_edit", args), answer("Could not.")]);
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        (&s).write_all(encode(&ToThalamus::Turn { session: None, text: "x".into() }).as_bytes()).unwrap();
        assert!(matches!(next(&mut r), Some(ToShell::Session { .. })));
        assert!(matches!(next(&mut r), Some(ToShell::Text { .. })), "{name}: no ApprovalRequest");
        assert!(posts(&rig).is_empty(), "{name}: wrote");
    }
}

#[test]
fn commit_without_a_decision_row_is_err() {
    let rig = rig_n("commit", mapped(), vec![ROWS.into(), POSTED.into()], vec![answer("hi")]);
    let who = alice();
    assert!(rig.srv.commit(&who, 4242).is_err(), "no row at all");
    let uuid = "0b7e6f3a-2c1d-4e5f-8a9b-1c2d3e4f5a6b";
    let approval = "1b7e6f3a-2c1d-4e5f-8a9b-1c2d3e4f5a6b";
    let (req, rej) = {
        let l = rig.srv.ledger.lock().unwrap();
        l.start(&thalamus::ledger::Session { uuid, agent_name: "iris", agent_version: 1, actor: "user:alice-smith",
            model_uri: "ollama-qwen" }).unwrap();
        let req = l.record(uuid, Kind::ApprovalRequest, Some("propose_row_edit"), &serde_json::json!({
            "approval": approval, "table": "todos", "row_id": "r1",
            "cells": [{"key": "status", "old": "open", "new": "done"}]})).unwrap();
        let rej = l.record(uuid, Kind::ApprovalDecision, Some("propose_row_edit"),
            &serde_json::json!({"approval": approval, "decision": "reject"})).unwrap();
        (req, rej)
    };
    assert!(rig.srv.commit(&who, req).is_err(), "a request row is not a decision");
    assert!(rig.srv.commit(&who, rej).is_err(), "a rejection is not an approval");
    let orphan = rig.srv.ledger.lock().unwrap().record(uuid, Kind::ApprovalDecision, Some("propose_row_edit"),
        &serde_json::json!({"approval": "2b7e6f3a-2c1d-4e5f-8a9b-1c2d3e4f5a6b", "decision": "approve"})).unwrap();
    assert!(rig.srv.commit(&who, orphan).is_err(), "an approval of no request");
    assert!(posts(&rig).is_empty(), "commit wrote without an approval");
    let ok = rig.srv.ledger.lock().unwrap().record(uuid, Kind::ApprovalDecision, Some("propose_row_edit"),
        &serde_json::json!({"approval": approval, "decision": "approve"})).unwrap();
    assert!(rig.srv.commit(&who, ok).is_ok());
    assert_eq!(posts(&rig).len(), 1);
}

// --- increment 7: the three controls, raised without the model ---

fn reader(rig: &Rig, name: &str, py: &str) {
    let tools = rig.srv.repo.join("tools");
    std::fs::create_dir_all(&tools).unwrap();
    std::fs::set_permissions(&tools, std::fs::Permissions::from_mode(0o700)).unwrap(); // bind()'s umask, as in dir()
    std::fs::write(tools.join(name), py).unwrap();
}

/// Raises one control on a fresh connection; returns what came after the Session.
fn raise(rig: &Rig, view: nos_contract::wire::ControlView) -> ToShell {
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    (&s).write_all(encode(&ToThalamus::Control { view }).as_bytes()).unwrap();
    assert!(matches!(next(&mut r), Some(ToShell::Session { .. })), "a control opens the session");
    next(&mut r).expect("an answer to the control")
}

const AWAITING: &str = r#"import json, sys
assert sys.argv[1:] == ["--json"]
print(json.dumps({"generated_at": "x", "unknown": ["gitlab: unreadable"], "items": [
    {"kind": "signature", "severity": "high", "age": "-", "what": "ruling unsigned", "where": "ruling.yml", "note": None}]}))
"#;

#[test]
fn approvals_runs_the_awaiting_reader_without_the_model() {
    // Disarmed model: a control still answers, because the model is not involved.
    let rig = rig_full("approvals", admin(), vec![ROWS.into()], vec![answer("never")], None);
    reader(&rig, "awaiting-operator.py", AWAITING);
    match raise(&rig, nos_contract::wire::ControlView::Approvals) {
        ToShell::Render { component: Component::ApprovalsList(a), .. } => {
            assert_eq!(a.unknown, ["gitlab: unreadable"], "UNKNOWN sources reach the person");
            assert_eq!(a.items.len(), 1);
            assert_eq!(a.items[0].what, "ruling unsigned");
        }
        other => panic!("expected approvals_list, got {other:?}"),
    }
    assert!(rig.model.lock().unwrap().is_empty(), "a control reached the model");
}

#[test]
fn red_status_runs_the_red_reader() {
    let rig = rig_n("red", admin(), vec![ROWS.into()], vec![answer("never")]);
    reader(&rig, "red-status.py", r#"import json
print(json.dumps({"sources_read": ["x"], "red_count": 1, "reds": ["pulse job failed"], "hold_count": 0, "holds": []}))
"#);
    match raise(&rig, nos_contract::wire::ControlView::RedStatus) {
        ToShell::Render { component: Component::RedStatus(r), .. } => {
            assert_eq!((r.red_count, r.reds.as_slice(), r.hold_count), (1, &["pulse job failed".to_string()][..], 0));
        }
        other => panic!("expected red_status, got {other:?}"),
    }
}

#[test]
fn a_reader_that_fails_or_lies_is_refused_never_empty() {
    for (name, py, want) in [("exit", "import sys; sys.exit(3)", "awaiting-operator.py exited"),
                             ("garbage", "print('not json')", "awaiting-operator.py: not JSON"),
                             ("shape", "import json; print(json.dumps({'items': [{'kind': 'x'}], 'unknown': []}))",
                              "awaiting-operator.py: unexpected shape")] {
        let rig = rig_n(name, admin(), vec![ROWS.into()], vec![answer("never")]);
        reader(&rig, "awaiting-operator.py", py);
        match raise(&rig, nos_contract::wire::ControlView::Approvals) {
            // The reason names the reader's own failure, so a missing python3 or script cannot pass.
            ToShell::Refused { reason } => assert!(reason.starts_with(want), "{name}: {reason}"),
            other => panic!("{name}: expected a refusal, got {other:?}"),
        }
    }
}

#[test]
fn a_control_is_a_tool_use_and_result_pair_in_the_ledger() {
    let rig = rig_n("pair", admin(), vec![ROWS.into()], vec![answer("never")]);
    reader(&rig, "awaiting-operator.py", AWAITING);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    (&s).write_all(encode(&ToThalamus::Control { view: nos_contract::wire::ControlView::Approvals }).as_bytes()).unwrap();
    let Some(ToShell::Session { session, .. }) = next(&mut r) else { panic!("no session") };
    assert!(matches!(next(&mut r), Some(ToShell::Render { .. })));
    let db = rusqlite::Connection::open(&rig.ledger).unwrap();
    let mut q = db.prepare("SELECT type, task FROM events WHERE run_id = ?1 AND task LIKE '%/tool:%' ORDER BY id").unwrap();
    let got: Vec<(String, String)> = q.query_map([&session], |x| Ok((x.get(0)?, x.get(1)?))).unwrap().map(Result::unwrap).collect();
    let pair = |t: &str| (t.to_string(), "agent:iris/tool:control_approvals".to_string());
    assert_eq!(got, [pair("agent_tool_use"), pair("agent_tool_result")]);
}

#[test]
fn a_reader_that_times_out_is_killed_with_what_it_spawned() {
    let rig = rig_n("slow", admin(), vec![ROWS.into()], vec![answer("never")]);
    let pidfile = rig.srv.repo.join("grandchild.pid");
    reader(&rig, "awaiting-operator.py", &format!(r#"import subprocess, time
p = subprocess.Popen(["sleep", "60"])
open({pidfile:?}, "w").write(str(p.pid))
time.sleep(60)
"#));
    match raise(&rig, nos_contract::wire::ControlView::Approvals) {
        ToShell::Refused { reason } => assert!(reason.contains("no answer in 2s"), "{reason}"),
        other => panic!("expected a timeout refusal, got {other:?}"),
    }
    let pid: i32 = std::fs::read_to_string(&pidfile).unwrap().parse().unwrap();
    let alive = || unsafe { libc::kill(pid, 0) } == 0;
    for _ in 0..40 {
        if !alive() {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    unsafe { libc::kill(pid, libc::SIGKILL) };
    panic!("the reader's child {pid} outlived the timeout and holds its pipe");
}

#[test]
fn approvals_and_red_status_are_tier_one_only() {
    let rig = rig_n("tier", mapped(), vec![ROWS.into()], vec![answer("never")]);
    reader(&rig, "awaiting-operator.py", AWAITING);
    reader(&rig, "red-status.py", r#"import json
print(json.dumps({"red_count": 0, "reds": [], "hold_count": 0, "holds": []}))
"#);
    for view in [nos_contract::wire::ControlView::Approvals, nos_contract::wire::ControlView::RedStatus] {
        match raise(&rig, view) {
            ToShell::Refused { reason } => assert_eq!(reason, "not yours to see"),
            other => panic!("a nos-users person saw the operator's queue: {other:?}"),
        }
    }
}

const CAPTURES: &str = r#"{"success": true, "data": [
    {"id": "cap-1", "title": "HKDF notes", "createdAt": 1760000000, "metadata": null},
    {"id": "cap-2", "title": "promoted already", "createdAt": 1760000001, "metadata": {"promotedTo": "obj-9"}}]}"#;

#[test]
fn inbox_shows_waiting_captures_and_names_the_queue_it_may_not_moderate() {
    let rig = rig_n("inbox", mapped(), vec![CAPTURES.into(), r#"!403 {"success": false, "error": "admin privileges required"}"#.into()],
        vec![answer("never")]);
    match raise(&rig, nos_contract::wire::ControlView::Inbox) {
        ToShell::Render { component: Component::InboxList(i), .. } => {
            let ids: Vec<&str> = i.items.iter().map(|x| x.id.as_str()).collect();
            assert_eq!(ids, ["cap-1"], "a promoted capture no longer waits");
            assert_eq!(i.items[0].source, "capture");
            assert_eq!(i.items[0].created_at, "2025-10-09T08:53:20Z", "KEAP's epoch seconds are shown as a raw number");
            assert_eq!(i.refused, ["promotions: not yours to moderate"], "a 403 is a refusal, never an empty queue");
        }
        other => panic!("expected inbox_list, got {other:?}"),
    }
    let keap = rig.keap.lock().unwrap().clone();
    assert_eq!(keap.len(), 2);
    assert!(keap[0].0.starts_with("GET /api/metadata "), "{}", keap[0].0);
    assert!(keap[1].0.starts_with("GET /api/promotions?status=proposed "), "{}", keap[1].0);
    assert!(keap.iter().all(|(h, _)| h.to_ascii_lowercase().contains("x-authentik-username: alice smith")), "not as the person");
}

#[test]
fn inbox_for_a_moderator_holds_the_proposed_promotions() {
    let promos = r#"{"success": true, "data": {"policy": "local", "items": [
        {"id": "pr-1", "status": "proposed", "captureId": "cap-1", "object": {"name": "HKDF"}, "createdAt": "2026-10-11"}]}}"#;
    let rig = rig_n("moder", mapped(), vec![CAPTURES.into(), promos.into()], vec![answer("never")]);
    match raise(&rig, nos_contract::wire::ControlView::Inbox) {
        ToShell::Render { component: Component::InboxList(i), .. } => {
            assert!(i.refused.is_empty(), "{:?}", i.refused);
            assert!(i.items.iter().any(|x| x.id == "pr-1" && x.source == "promotion" && x.title == "HKDF"), "{:?}", i.items);
        }
        other => panic!("expected inbox_list, got {other:?}"),
    }
}

#[test]
fn an_unreadable_capture_source_is_named_not_emptied() {
    let rig = rig_n("capfail", mapped(), vec!["!500 {\"success\": false, \"error\": \"db\"}".into()], vec![answer("never")]);
    match raise(&rig, nos_contract::wire::ControlView::Inbox) {
        ToShell::Render { component: Component::InboxList(i), .. } => {
            assert!(i.items.is_empty());
            assert!(i.refused.iter().any(|r| r.starts_with("captures: ")), "{:?}", i.refused);
        }
        other => panic!("expected inbox_list, got {other:?}"),
    }
}

// --- review 2026-10-12: what the model is told when the thalamus stops it ---

/// Every tool message's call id in the n-th body the model was sent.
fn tool_ids(rig: &Rig, n: usize) -> Vec<String> {
    let body: serde_json::Value = serde_json::from_str(&rig.model.lock().unwrap()[n].1).unwrap();
    body["messages"].as_array().unwrap().iter().filter(|m| m["role"] == "tool")
        .map(|m| m["tool_call_id"].as_str().unwrap_or("").to_string()).collect()
}

/// Sends one Turn and reads until the turn's Text or Refused.
fn turn(s: &UnixStream, r: &mut BufReader<UnixStream>, session: Option<String>, text: &str) -> Vec<ToShell> {
    let mut w = s;
    w.write_all(encode(&ToThalamus::Turn { session, text: text.into() }).as_bytes()).unwrap();
    let mut got = Vec::new();
    while let Some(m) = next(r) {
        let end = matches!(m, ToShell::Text { .. } | ToShell::Refused { .. });
        got.push(m);
        if end {
            break;
        }
    }
    got
}

fn session_of(got: &[ToShell]) -> String {
    got.iter().find_map(|m| match m { ToShell::Session { session, .. } => Some(session.clone()), _ => None }).unwrap()
}

#[test]
fn a_stopped_turn_answers_every_call_it_was_asked() {
    // Nine calls in one message; the cap is eight. An unanswered call is a shape providers reject.
    let calls: Vec<_> = (0..9).map(|i| serde_json::json!({"id": format!("c{i}"), "type": "function",
        "function": {"name": "search_rows", "arguments": r#"{"table": "todos", "q": "alpha"}"#}})).collect();
    let nine = serde_json::json!({"choices": [{"message": {"role": "assistant", "content": null, "tool_calls": calls}}]}).to_string();
    let rig = rig_n("cap", mapped(), vec![ROWS.into()], vec![nine, answer("ok")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let first = turn(&s, &mut r, None, "go");
    assert!(matches!(first.last(), Some(ToShell::Text { text, .. }) if text.starts_with("Stopped")), "{first:?}");
    turn(&s, &mut r, Some(session_of(&first)), "again");
    let want: Vec<String> = (0..9).map(|i| format!("c{i}")).collect();
    assert_eq!(tool_ids(&rig, 1), want, "every call the model made has its tool message");
    assert!(rig.model.lock().unwrap()[1].1.contains("stopped: tool-call cap"));
}

#[test]
fn a_table_read_that_cannot_be_whole_is_an_error_not_a_short_answer() {
    let endless = r#"{"success": true, "data": {"rows": [{"id": "r1", "values": {"title": "Alpha"}}], "nextCursor": "more"}}"#;
    let no_id = r#"{"success": true, "data": {"rows": [{"values": {"title": "Alpha"}}]}}"#;
    for (name, keap, want) in [("noid", no_id, "without an id"), ("pages", endless, "exceeds")] {
        let rig = rig_n(name, mapped(), vec![keap.into()], vec![tool_call(r#"{"table": "todos", "q": "alpha"}"#), answer("x")]);
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        let got = turn(&s, &mut r, None, "find alpha");
        assert!(!got.iter().any(|m| matches!(m, ToShell::Render { .. })), "{name}: a partial table was shown: {got:?}");
        let body = rig.model.lock().unwrap()[1].1.clone();
        assert!(body.contains(want), "{name}: the model was not told: {body}");
    }
}

#[test]
fn the_model_hears_how_the_person_decided() {
    for (name, d, note, want) in [("heard-yes", Decision::Approve, None, "approved, row written"),
                                  ("heard-no", Decision::Reject, Some("not yet"), "rejected: not yet")] {
        let rig = rig_n(name, mapped(), vec![ROWS.into(), ROWS.into(), POSTED.into()],
            vec![call("propose_row_edit", EDIT), answer("Proposed.")]);
        let (s, mut r, session, approval, _) = propose(&rig);
        let mut w = &s;
        w.write_all(encode(&ToThalamus::ApprovalDecision { approval: approval.clone(), decision: d,
            note: note.map(str::to_string) }).as_bytes()).unwrap();
        assert!(matches!(next(&mut r), Some(ToShell::Text { .. })));
        turn(&s, &mut r, Some(session), "and?");
        let body = rig.model.lock().unwrap()[2].1.clone();
        assert!(body.contains(&format!("[thalamus] approval {approval}: {want}")), "{name}: {body}");
    }
}

#[test]
fn one_approval_waits_at_a_time() {
    let two = serde_json::json!({"choices": [{"message": {"role": "assistant", "content": null, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "propose_row_edit", "arguments": EDIT}},
        {"id": "c2", "type": "function", "function": {"name": "propose_row_edit", "arguments": EDIT}}]}}]}).to_string();
    let rig = rig_n("onepending", mapped(), vec![ROWS.into()], vec![two, answer("Proposed.")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "close alpha twice");
    let asks = got.iter().filter(|m| matches!(m, ToShell::ApprovalRequest { .. })).count();
    assert_eq!(asks, 1, "{got:?}");
    assert!(rig.model.lock().unwrap()[1].1.contains("an approval is already waiting"));
}

#[test]
fn the_model_may_name_the_roadmap_by_its_alias() {
    // The plist renders NOS_ROADMAP_TABLE_ID from keap_roadmap_table_id; no other alias is mapped.
    std::env::set_var("NOS_ROADMAP_TABLE_ID", "rt-2d49");
    let rig = rig_n("alias", mapped(), vec![ROWS.into()],
        vec![tool_call(r#"{"table": "roadmap", "q": "alpha"}"#), tool_call(r#"{"table": "current-state", "q": "alpha"}"#), answer("x")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "find alpha on the roadmap");
    assert!(got.iter().any(|m| matches!(m, ToShell::Render { component: Component::TableResults(t), .. } if t.table == "rt-2d49")), "{got:?}");
    let heads: Vec<String> = rig.keap.lock().unwrap().iter().map(|(h, _)| h.clone()).collect();
    assert!(heads[0].starts_with("GET /api/tables/rt-2d49/rows?"), "{}", heads[0]);
    assert!(heads[1].starts_with("GET /api/tables/current-state/rows?"), "{}", heads[1]);
}

#[test]
fn approve_writes_nothing_over_a_row_that_moved_since_the_proposal() {
    let changed = r#"{"success": true, "data": {"rows": [{"id": "r1", "values": {"title": "Alpha one", "status": "blocked"}}]}}"#;
    let gone = r#"{"success": true, "data": {"rows": [{"id": "r2", "values": {"title": "beta"}}]}}"#;
    for (name, now, want) in [("moved", changed, "changed since"), ("gone", gone, "gone since")] {
        let rig = rig_n(name, mapped(), vec![ROWS.into(), now.into(), POSTED.into()],
            vec![call("propose_row_edit", EDIT), answer("Proposed.")]);
        let (s, mut r, session, approval, _) = propose(&rig);
        decide(&s, &approval, Decision::Approve);
        assert!(matches!(next(&mut r), Some(ToShell::Text { text, .. }) if text.contains(want)), "{name}");
        assert!(posts(&rig).is_empty(), "{name}: wrote over a row the person did not see");
        let db = rusqlite::Connection::open(&rig.ledger).unwrap();
        let why: String = db.query_row("SELECT result_json FROM events WHERE run_id = ?1 AND type = 'agent_tool_result' \
            AND task LIKE '%propose_row_edit' ORDER BY id DESC LIMIT 1", [&session], |x| x.get(0)).unwrap();
        assert!(why.contains(want), "{name}: the ledger does not say why: {why}");
    }
}

// --- the eye (pupil I3): serve says what it is doing, every step of a turn ---

fn phases(got: &[ToShell]) -> Vec<String> {
    got.iter().map(|m| match m {
        ToShell::Activity { phase: Phase::Tool { name }, .. } => format!("tool:{name}"),
        ToShell::Activity { phase, .. } => serde_json::to_value(phase).unwrap().as_str().unwrap().to_string(),
        m => serde_json::to_value(m).unwrap()["t"].as_str().unwrap().to_string(),
    }).collect()
}

/// Raw messages up to and including the next Text or Refused.
fn until_text(r: &mut BufReader<UnixStream>) -> Vec<ToShell> {
    let mut got = Vec::new();
    while let Some(m) = raw(r) {
        let end = matches!(m, ToShell::Text { .. } | ToShell::Refused { .. });
        got.push(m);
        if end {
            break;
        }
    }
    got
}

#[test]
fn a_turn_says_thinking_before_its_text_and_idle_at_the_end() {
    let rig = rig("eye", mapped(), ROWS, vec![tool_call(r#"{"table": "todos", "q": "alpha"}"#), answer("Found one.")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    (&s).write_all(encode(&ToThalamus::Turn { session: None, text: "find alpha".into() }).as_bytes()).unwrap();
    let got = until_text(&mut r);
    assert_eq!(phases(&got), ["session", "thinking", "tool:search_rows", "render", "thinking", "text"]);
    let session = session_of(&got);
    assert!(matches!(raw(&mut r), Some(ToShell::Activity { session: s2, phase: Phase::Idle }) if s2 == session));
}

#[test]
fn an_approved_edit_says_writing_then_idle() {
    let rig = rig_n("eye-write", mapped(), vec![ROWS.into(), ROWS.into(), POSTED.into()],
        vec![call("propose_row_edit", EDIT), answer("Proposed.")]);
    let (s, mut r, _, approval, _) = propose(&rig);
    decide(&s, &approval, Decision::Approve);
    let got = phases(&until_text(&mut r));
    assert!(got.ends_with(&["writing".into(), "text".into()]), "{got:?}");
    assert!(matches!(raw(&mut r), Some(ToShell::Activity { phase: Phase::Idle, .. })));
}
