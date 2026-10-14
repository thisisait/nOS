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

thread_local! {
    /// A reader's wall clock in the rig: a cold python3 under a parallel suite took over 2 s (CI and
    /// local, 2026-10-14), so a reader that answers gets 10; the timeout test sets its own 2.
    static READER_SECS: std::cell::Cell<u64> = const { std::cell::Cell::new(10) };
}

fn rig_full(name: &str, map: serde_json::Value, keap_bodies: Vec<String>, model_bodies: Vec<String>,
            bound: Option<Binding>) -> Rig {
    rig_at(name, map, fake(keap_bodies), model_bodies, bound)
}

/// The rig over a KEAP already listening at (url, seen): the canned fake or fake_table.
fn rig_at(name: &str, map: serde_json::Value, keap: (String, Seen), model_bodies: Vec<String>,
          bound: Option<Binding>) -> Rig {
    rig_deciders(name, map, keap, model_bodies, bound, vec![])
}

/// rig_at with serve's decider list (NOS_DECIDER_EXES); empty is off.
fn rig_deciders(name: &str, map: serde_json::Value, (keap_url, keap): (String, Seen), model_bodies: Vec<String>,
                bound: Option<Binding>, deciders: Vec<PathBuf>) -> Rig {
    let d = dir(name);
    std::fs::write(d.join("IMPRINT.short.md"), SHORT).unwrap();
    std::fs::write(d.join("IMPRINT.md"), FULL).unwrap();
    let map_path = d.join("identity-map.yml");
    std::fs::write(&map_path, map.to_string()).unwrap();
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
        reader_secs: READER_SECS.with(|c| c.get()),
        tier1: vec!["nos-admins".into()],
        deciders,
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

fn query(args: &str) -> String {
    call("query_rows", args)
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
    {"id": "r1", "values": {"title": "Alpha one", "status": "open", "ordinal": 3}},
    {"id": "r2", "values": {"title": "beta"}},
    {"id": "r3", "values": {"title": "Gamma", "status": "open", "ordinal": 2}}]}}"#;

/// GET /api/tables/todos: the title and column order; rowCount is the owner's, never `total`.
const SCHEMA: &str = r#"{"success": true, "data": {"id": "todos", "title": "Todo list", "rowCount": 99, "schema": {"columns": [
    {"key": "title", "label": "Title", "kind": "text"},
    {"key": "status", "label": "Status", "kind": "select", "options": ["open", "done"]},
    {"key": "ordinal", "label": "Ordinal", "kind": "number"}]}}}"#;

/// A query's KEAP answers (schema, then rows), then `rest`.
fn shown_then(rest: &[&str]) -> Vec<String> {
    [SCHEMA, ROWS].iter().chain(rest).map(|b| b.to_string()).collect()
}

#[test]
fn serve_refuses_a_peer_the_identity_map_does_not_name() {
    let rig = rig("unmapped", serde_json::json!({"logins": {"someone-else": {"username": "bob", "groups": []}}}), ROWS,
        vec![answer("never")]);
    let mut r = BufReader::new(connect(&rig.sock));
    match next(&mut r) {
        Some(ToShell::Refused { reason, .. }) => assert!(reason.contains("identity map"), "{reason}"),
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
    let rig = rig_n("mapped", map, shown_then(&[]), vec![query(r#"{"table": "todos", "q": "ALPHA"}"#), answer("Found one.")]);
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
        Some(ToShell::Render { session: s2, component: Component::TableResults(t), .. }) => {
            assert_eq!(s2, session);
            assert_eq!(t.table, "todos");
            assert!(!t.projected, "substring search is not a projection");
            assert_eq!(t.columns, ["title", "status", "ordinal"], "the schema's column order");
            assert_eq!(t.rows.len(), 1);
            assert_eq!(t.rows[0].__id, "r1");
        }
        other => panic!("expected Render table_results, got {other:?}"),
    }
    assert!(matches!(next(&mut r), Some(ToShell::Text { text, .. }) if text == "Found one."));
    drop(s);
    drop(r);

    let keap = rig.keap.lock().unwrap().clone();
    assert_eq!(keap.len(), 2, "one schema GET, one rows read");
    assert!(keap[0].0.to_ascii_lowercase().starts_with("get /api/tables/todos "), "{}", keap[0].0);
    assert!(keap[1].0.to_ascii_lowercase().starts_with("get /api/tables/todos/rows?limit=500 "), "{}", keap[1].0);
    for (head, _) in &keap {
        let head = head.to_ascii_lowercase();
        for h in ["x-authentik-username: alice smith", "x-authentik-uid: alice-smith",
                  "x-authentik-groups: nos-users,nos-editors", &format!("x-keap-proxy-secret: {SECRET}")] {
            assert!(head.contains(h), "KEAP did not get {h:?}:\n{head}");
        }
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
    let rig = rig_full("bearer", map, shown_then(&[]), vec![query(r#"{"table": "todos", "q": "alpha"}"#),
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
            Some(ToShell::Refused { reason, .. }) => assert!(reason.contains(file), "{name}: {reason}"),
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

/// One turn that shows r1, then proposes `values` for it; returns (stream, reader, session, approval, diff).
fn propose(rig: &Rig) -> (UnixStream, BufReader<UnixStream>, String, String, nos_contract::renderers::RowDiffApproval) {
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    (&s).write_all(encode(&ToThalamus::Turn { session: None, text: "close alpha".into() }).as_bytes()).unwrap();
    let Some(ToShell::Session { session, .. }) = next(&mut r) else { panic!("no session") };
    assert!(matches!(next(&mut r), Some(ToShell::Render { component: Component::TableResults(_), .. })), "the row is shown first");
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

/// The model's side of a turn that edits r1: it queries the row, then proposes.
fn edit_turn() -> Vec<String> {
    vec![query(r#"{"table": "todos", "q": "alpha"}"#), call("propose_row_edit", EDIT), answer("Proposed.")]
}

#[test]
fn approve_posts_the_approved_cells_once_as_the_person() {
    // The query, the proposal's read, commit's re-read, then the POST.
    let rig = rig_n("approve", mapped(), shown_then(&[ROWS, ROWS, POSTED]), edit_turn());
    let (s, mut r, session, approval, diff) = propose(&rig);
    assert_eq!(diff.table, "todos");
    assert_eq!(diff.row_id, "r1");
    // An unchanged cell is not part of the diff, and not part of the write.
    assert_eq!(diff.cells.len(), 1);
    assert_eq!((diff.cells[0].key.as_str(), &diff.cells[0].old, &diff.cells[0].new),
               ("status", &serde_json::json!("open"), &serde_json::json!("done")));
    assert!(posts(&rig).is_empty(), "a proposal wrote before the person decided");

    decide(&s, &approval, Decision::Approve);
    assert!(matches!(next(&mut r), Some(ToShell::TableChanged { ref table, ref row, .. }) if table == "todos" && row == "r1"),
            "the widgets hear the table changed");
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
    let rig = rig_n("reject", mapped(), shown_then(&[ROWS, POSTED]), edit_turn());
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
    // Shown by the query, then gone by the proposal's read; or shown, but a sharing key.
    let gone = r#"{"success": true, "data": {"rows": [{"id": "r2", "values": {"title": "beta"}}]}}"#;
    let sharing = r#"{"table": "todos", "row_id": "r1", "values": {"__sharing": {"public": true}}}"#;
    for (name, args, keap, want) in [("absent", EDIT, gone, "that you can read"), ("sharing", sharing, ROWS, "cannot be edited here")] {
        let rig = rig_n(name, mapped(), shown_then(&[keap, POSTED]),
            vec![query(r#"{"table": "todos", "q": "alpha"}"#), call("propose_row_edit", args), answer("Could not.")]);
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        let got = turn(&s, &mut r, None, "x");
        assert!(!got.iter().any(|m| matches!(m, ToShell::ApprovalRequest { .. })), "{name}: an ApprovalRequest: {got:?}");
        assert!(posts(&rig).is_empty(), "{name}: wrote");
        assert!(rig.model.lock().unwrap()[2].1.contains(want), "{name}: the model was not told {want}");
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
            ToShell::Refused { reason, .. } => assert!(reason.starts_with(want), "{name}: {reason}"),
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
    READER_SECS.with(|c| c.set(2));
    let rig = rig_n("slow", admin(), vec![ROWS.into()], vec![answer("never")]);
    let pidfile = rig.srv.repo.join("grandchild.pid");
    reader(&rig, "awaiting-operator.py", &format!(r#"import subprocess, time
p = subprocess.Popen(["sleep", "60"])
open({pidfile:?}, "w").write(str(p.pid))
time.sleep(60)
"#));
    match raise(&rig, nos_contract::wire::ControlView::Approvals) {
        ToShell::Refused { reason, .. } => assert!(reason.contains("no answer in 2s"), "{reason}"),
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
            ToShell::Refused { reason, .. } => assert_eq!(reason, "not yours to see"),
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
        "function": {"name": "query_rows", "arguments": r#"{"table": "todos", "q": "alpha"}"#}})).collect();
    let nine = serde_json::json!({"choices": [{"message": {"role": "assistant", "content": null, "tool_calls": calls}}]}).to_string();
    let rig = rig_n("cap", mapped(), vec![SCHEMA.into(), ROWS.into()], vec![nine, answer("ok")]);
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
        let rig = rig_n(name, mapped(), vec![SCHEMA.into(), keap.into()], vec![query(r#"{"table": "todos", "q": "alpha"}"#), answer("x")]);
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
        let rig = rig_n(name, mapped(), shown_then(&[ROWS, ROWS, POSTED]), edit_turn());
        let (s, mut r, session, approval, _) = propose(&rig);
        let mut w = &s;
        w.write_all(encode(&ToThalamus::ApprovalDecision { approval: approval.clone(), decision: d,
            note: note.map(str::to_string) }).as_bytes()).unwrap();
        if d == Decision::Approve {
            assert!(matches!(next(&mut r), Some(ToShell::TableChanged { .. })), "{name}: a write says its table changed");
        }
        assert!(matches!(next(&mut r), Some(ToShell::Text { .. })));
        turn(&s, &mut r, Some(session), "and?");
        let body = rig.model.lock().unwrap()[3].1.clone();
        assert!(body.contains(&format!("[thalamus] approval {approval}: {want}")), "{name}: {body}");
    }
}

#[test]
fn one_approval_waits_at_a_time() {
    let two = serde_json::json!({"choices": [{"message": {"role": "assistant", "content": null, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "propose_row_edit", "arguments": EDIT}},
        {"id": "c2", "type": "function", "function": {"name": "propose_row_edit", "arguments": EDIT}}]}}]}).to_string();
    let rig = rig_n("onepending", mapped(), shown_then(&[]), vec![query(r#"{"table": "todos", "q": "alpha"}"#), two, answer("Proposed.")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "close alpha twice");
    let asks = got.iter().filter(|m| matches!(m, ToShell::ApprovalRequest { .. })).count();
    assert_eq!(asks, 1, "{got:?}");
    assert!(rig.model.lock().unwrap()[2].1.contains("an approval is already waiting"));
}

#[test]
fn the_model_may_name_the_roadmap_by_its_alias() {
    // The plist renders NOS_ROADMAP_TABLE_ID from keap_roadmap_table_id; no other alias is mapped.
    std::env::set_var("NOS_ROADMAP_TABLE_ID", "rt-2d49");
    let rig = rig_n("alias", mapped(), vec![SCHEMA.into(), ROWS.into(), SCHEMA.into(), ROWS.into()],
        vec![query(r#"{"table": "roadmap", "q": "alpha"}"#), query(r#"{"table": "current-state", "q": "alpha"}"#), answer("x")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "find alpha on the roadmap");
    assert!(got.iter().any(|m| matches!(m, ToShell::Render { component: Component::TableResults(t), .. } if t.table == "rt-2d49")), "{got:?}");
    let heads: Vec<String> = rig.keap.lock().unwrap().iter().map(|(h, _)| h.clone()).collect();
    assert!(heads[0].starts_with("GET /api/tables/rt-2d49 "), "{}", heads[0]);
    assert!(heads[1].starts_with("GET /api/tables/rt-2d49/rows?"), "{}", heads[1]);
    assert!(heads[2].starts_with("GET /api/tables/current-state "), "{}", heads[2]);
    assert!(heads[3].starts_with("GET /api/tables/current-state/rows?"), "{}", heads[3]);
}

#[test]
fn approve_writes_nothing_over_a_row_that_moved_since_the_proposal() {
    let changed = r#"{"success": true, "data": {"rows": [{"id": "r1", "values": {"title": "Alpha one", "status": "blocked"}}]}}"#;
    let gone = r#"{"success": true, "data": {"rows": [{"id": "r2", "values": {"title": "beta"}}]}}"#;
    for (name, now, want) in [("moved", changed, "changed since"), ("gone", gone, "gone since")] {
        let rig = rig_n(name, mapped(), shown_then(&[ROWS, now, POSTED]), edit_turn());
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
    let rig = rig_n("eye", mapped(), shown_then(&[]), vec![query(r#"{"table": "todos", "q": "alpha"}"#), answer("Found one.")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    (&s).write_all(encode(&ToThalamus::Turn { session: None, text: "find alpha".into() }).as_bytes()).unwrap();
    let got = until_text(&mut r);
    assert_eq!(phases(&got), ["session", "thinking", "tool:query_rows", "render", "thinking", "text"]);
    let session = session_of(&got);
    assert!(matches!(raw(&mut r), Some(ToShell::Activity { session: s2, phase: Phase::Idle }) if s2 == session));
}

#[test]
fn an_approved_edit_says_writing_then_idle() {
    let rig = rig_n("eye-write", mapped(), shown_then(&[ROWS, ROWS, POSTED]), edit_turn());
    let (s, mut r, _, approval, _) = propose(&rig);
    decide(&s, &approval, Decision::Approve);
    let got = phases(&until_text(&mut r));
    assert!(got.ends_with(&["writing".into(), "table_changed".into(), "text".into()]), "{got:?}");
    assert!(matches!(raw(&mut r), Some(ToShell::Activity { phase: Phase::Idle, .. })));
}

// --- pupil I4a: query_rows reads, counts and filters; a proposal needs a row the person saw ---

/// The last tool message of the n-th body the model was sent, as JSON.
fn tool_result(rig: &Rig, n: usize) -> serde_json::Value {
    let body: serde_json::Value = serde_json::from_str(&rig.model.lock().unwrap()[n].1).unwrap();
    let m = body["messages"].as_array().unwrap().iter().rev().find(|m| m["role"] == "tool").expect("a tool message").clone();
    serde_json::from_str(m["content"].as_str().unwrap()).unwrap()
}

/// Every table_results the turn rendered, as its wire props.
fn renders(got: &[ToShell]) -> Vec<serde_json::Value> {
    got.iter().filter_map(|m| match m {
        ToShell::Render { component: c @ Component::TableResults(_), .. } => Some(serde_json::to_value(c).unwrap()["props"].clone()),
        _ => None,
    }).collect()
}

#[test]
fn query_rows_without_q_reads_every_row_and_counts_exactly() {
    // Live 2026-10-12: `q` was required, so the model searched "the" and invented "49 rows".
    let rig = rig_n("count", mapped(), shown_then(&[SCHEMA, ROWS]),
        vec![query(r#"{"table": "todos", "limit": 0}"#), query(r#"{"table": "todos", "q": "  "}"#), answer("3 rows.")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "how many rows?");
    let count = tool_result(&rig, 1);
    assert_eq!((&count["matched"], &count["total"], &count["rows"]), (&serde_json::json!(3), &serde_json::json!(3), &serde_json::json!([])),
               "limit 0 is the exact count, not KEAP's rowCount: {count}");
    let all = tool_result(&rig, 2);
    assert!(all.get("error").is_none(), "a blank q is not an error: {all}");
    assert_eq!(all["rows"].as_array().unwrap().len(), 3, "{all}");
    let shown = renders(&got);
    assert_eq!(shown.len(), 2, "{got:?}");
    assert_eq!((&shown[0]["name"], &shown[0]["query"], &shown[0]["total"]),
               (&serde_json::json!("Todo list"), &serde_json::json!("all rows"), &serde_json::json!(3)), "{}", shown[0]);
}

#[test]
fn query_rows_filters_sorts_projects_and_names_the_table() {
    let rig = rig_n("filter", mapped(), shown_then(&[SCHEMA, ROWS]), vec![
        query(r#"{"table": "todos", "where": [{"column": "status", "op": "eq", "value": "open"}],
                  "order_by": {"column": "ordinal", "dir": "asc"}, "columns": ["title"]}"#),
        query(r#"{"table": "todos", "order_by": {"column": "title", "dir": "desc"}}"#), answer("x")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "open ones, in order");
    let ids = |v: &serde_json::Value| v["rows"].as_array().unwrap().iter().map(|r| r["__id"].as_str().unwrap().to_string()).collect::<Vec<_>>();
    let open = tool_result(&rig, 1);
    assert_eq!(ids(&open), ["r3", "r1"], "status = open, ordinal ascending: {open}");
    assert_eq!((&open["name"], &open["matched"], &open["total"]), (&serde_json::json!("Todo list"), &serde_json::json!(2), &serde_json::json!(3)));
    // The model learns the real status vocabulary from the schema it is handed.
    assert!(open["columns"].to_string().contains(r#""options":["open","done"]"#), "{open}");
    let shown = renders(&got);
    assert_eq!(shown[0]["columns"], serde_json::json!(["title"]), "projected to the asked columns");
    assert!(shown[0]["rows"][0]["cells"].get("status").is_none(), "a cell outside the projection rode along: {}", shown[0]);
    let q = shown[0]["query"].as_str().unwrap();
    assert!(q.contains("status = open") && q.contains("order by ordinal asc") && q.contains("columns title"), "{q}");
    // Strings sort case-insensitively: Gamma, beta, Alpha one.
    assert_eq!(ids(&tool_result(&rig, 2)), ["r3", "r2", "r1"]);
}

#[test]
fn query_rows_on_an_unknown_column_or_value_names_the_real_ones() {
    for (name, args, want) in [
        ("nocol", r#"{"table": "todos", "where": [{"column": "state", "op": "eq", "value": "open"}]}"#,
         "no column `state` in Todo list; columns: title, status, ordinal"),
        ("noval", r#"{"table": "todos", "where": [{"column": "status", "op": "in", "value": ["open", "next"]}]}"#,
         "options: open, done"),
        ("nosort", r#"{"table": "todos", "order_by": {"column": "rank", "dir": "asc"}}"#, "no column `rank`")] {
        let rig = rig_n(name, mapped(), shown_then(&[]), vec![query(args), answer("x")]);
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        let got = turn(&s, &mut r, None, "x");
        assert!(renders(&got).is_empty(), "{name}: a wrong query rendered: {got:?}");
        let e = tool_result(&rig, 1);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(want)), "{name}: {e}");
        assert_eq!(rig.keap.lock().unwrap().len(), 1, "{name}: rows were read for a query the schema refuses");
    }
}

#[test]
fn query_rows_rejects_a_non_string_argument_and_an_unknown_key() {
    // A non-string is not "left out", and where / order_by have no keys beyond the ones declared.
    let cases = [
        ("qtype", r#"{"table": "todos", "q": 1}"#, "`q` is a string"),
        ("dirtype", r#"{"table": "todos", "order_by": {"column": "title", "dir": 1}}"#, "asc or desc"),
        ("valtype", r#"{"table": "todos", "where": [{"column": "ordinal", "op": "eq", "value": 3}]}"#, "value is a string"),
        ("intype", r#"{"table": "todos", "where": [{"column": "title", "op": "in", "value": [1]}]}"#, "list of strings"),
        ("wherekey", r#"{"table": "todos", "where": [{"column": "status", "op": "eq", "value": "open", "note": "x"}]}"#, "note"),
        ("orderkey", r#"{"table": "todos", "order_by": {"column": "title", "dir": "asc", "nulls": "last"}}"#, "nulls"),
    ];
    let mut bad = Vec::new();
    for (name, args, want) in cases {
        let rig = rig_n(name, mapped(), shown_then(&[]), vec![query(args), answer("x")]);
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        let got = turn(&s, &mut r, None, "x");
        let e = tool_result(&rig, 1);
        let msg = e["error"].as_str().unwrap_or("");
        if !msg.contains(want) || !renders(&got).is_empty() || rig.keap.lock().unwrap().len() != 1 {
            bad.push(format!("{name}: {e}"));
        }
    }
    assert!(bad.is_empty(), "query_rows accepted a bad argument:\n{}", bad.join("\n"));
}

#[test]
fn a_proposal_for_a_row_never_shown_is_refused_without_a_read_or_a_card() {
    // Live 2026-10-12: the model called propose_row_edit to look at a row, not to change it.
    let rig = rig_n("probe", mapped(), shown_then(&[ROWS]),
        vec![call("propose_row_edit", EDIT), answer("Could not."),
             query(r#"{"table": "todos", "q": "alpha"}"#), call("propose_row_edit", EDIT), answer("Proposed.")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let first = turn(&s, &mut r, None, "how many rows?");
    assert!(!first.iter().any(|m| matches!(m, ToShell::ApprovalRequest { .. })), "a card for a row never shown: {first:?}");
    assert!(rig.keap.lock().unwrap().is_empty(), "KEAP was read for a refused proposal");
    let e = tool_result(&rig, 1);
    assert!(e["error"].as_str().is_some_and(|e| e.contains("was not shown to the person in this session")), "{e}");
    let second = turn(&s, &mut r, Some(session_of(&first)), "close alpha");
    assert!(second.iter().any(|m| matches!(m, ToShell::ApprovalRequest { .. })), "a shown row is proposed as before: {second:?}");
}

#[test]
fn the_tools_and_prompt_name_query_rows_and_bound_proposals() {
    let rig = rig("prompt", mapped(), ROWS, vec![answer("hi")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    turn(&s, &mut r, None, "hello");
    let p = system_prompt(&rig);
    assert!(p.contains("call query_rows (its total is the exact count)"), "{p}");
    assert!(p.contains("propose_row_edit only for a change the person asked for, never to look at a row"), "{p}");
    let body: serde_json::Value = serde_json::from_str(&rig.model.lock().unwrap()[0].1).unwrap();
    let names: Vec<&str> = body["tools"].as_array().unwrap().iter().map(|t| t["function"]["name"].as_str().unwrap()).collect();
    assert_eq!(names, ["query_rows", "propose_row_edit", "show", "red_status"]);
    assert!(p.contains(&format!("To show structured output call show ({})", serve::SHOW_KINDS.join(", "))), "{p}");
    assert_eq!(body["tools"][0]["function"]["parameters"]["required"], serde_json::json!(["table"]), "q is optional");
}

// --- pupil I4c: the model draws through show, and show can mint nothing ---

fn show(component: serde_json::Value) -> String {
    call("show", &serde_json::json!({"component": component}).to_string())
}

/// Every rendered component of a turn, as its wire JSON.
fn drawn_kinds(got: &[ToShell]) -> Vec<String> {
    got.iter().filter_map(|m| match m {
        ToShell::Render { component, .. } => Some(serde_json::to_value(component).unwrap()["kind"].as_str().unwrap().to_string()),
        _ => None,
    }).collect()
}

#[test]
fn show_renders_a_valid_component_and_refuses_an_invalid_one() {
    let list = serde_json::json!({"kind": "list", "props": {"ordered": true, "items": [{"text": "query", "tone": "ok"}]}});
    let bad = [
        (serde_json::json!({"kind": "pie_chart", "props": {}}), "pie_chart".to_string()),
        (serde_json::json!({"kind": "list", "props": {"ordered": false, "items": [{"text": "x", "html": "<b>"}]}}), "html".to_string()),
        (serde_json::json!({"kind": "table", "props": {"columns": ["a", "b"], "rows": [["x"]]}}), "row 1 has 1 cells".to_string()),
        // Live 2026-10-13: a markdown show was then said again as text; text already draws as markdown.
        (serde_json::json!({"kind": "markdown", "props": {"text": "x"}}), format!(r#"show draws {}, not "markdown""#, serve::SHOW_KINDS.join(", "))),
    ];
    let mut model = vec![show(list)];
    model.extend(bad.iter().map(|(c, _)| show(c.clone())));
    model.push(answer("done"));
    let rig = rig("show", mapped(), ROWS, model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "list the steps");
    assert_eq!(drawn_kinds(&got), ["list"], "only the valid component is drawn: {got:?}");
    assert!(!got.iter().any(|m| matches!(m, ToShell::Refused { .. })), "a refused show is the model's to hear, not a refusal line");
    assert_eq!(tool_result(&rig, 1), serde_json::json!({"shown": "list"}));
    for (i, (_, want)) in bad.iter().enumerate() {
        let e = tool_result(&rig, i + 2);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(want)), "show #{} must be refused naming {want}: {e}", i + 2);
    }
    assert!(rig.keap.lock().unwrap().is_empty(), "show read KEAP");
}

#[test]
fn show_cannot_render_an_approval_or_a_tool_chosen_kind() {
    let chosen = [
        serde_json::json!({"kind": "row_diff_approval", "props": {"table": "todos", "row_id": "r1",
            "cells": [{"key": "status", "old": "open", "new": "done"}]}}),
        serde_json::json!({"kind": "table_results", "props": {"table": "todos", "name": "Todo list", "query": "all rows",
            "matched": 0, "total": 0, "columns": [], "rows": [], "projected": true}}),
        serde_json::json!({"kind": "approvals_list", "props": {"items": [], "unknown": []}}),
        serde_json::json!({"kind": "inbox_list", "props": {"items": [], "refused": []}}),
        serde_json::json!({"kind": "red_status", "props": {"red_count": 0, "reds": [], "hold_count": 0, "holds": []}}),
    ];
    let mut model: Vec<String> = chosen.iter().cloned().map(show).collect();
    model.push(answer("done"));
    let rig = rig("showapproval", mapped(), ROWS, model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "approve it yourself");
    assert!(!got.iter().any(|m| matches!(m, ToShell::ApprovalRequest { .. } | ToShell::Render { .. })),
            "show drew a kind only a tool or an ask may: {got:?}");
    for (i, c) in chosen.iter().enumerate() {
        let e = tool_result(&rig, i + 1);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(&format!("show draws {}, not", serve::SHOW_KINDS.join(", ")))),
                "{}: {e}", c["kind"]);
    }
    let session = session_of(&got);
    assert!(!types_of(&rig.ledger, &session).iter().any(|t| t.contains("approval")), "an approval reached the ledger");
    assert!(rig.keap.lock().unwrap().is_empty(), "show read KEAP");
}

// --- pupil I4d: a chart is drawn within its caps; I5b: six kinds over a named x axis ---

#[test]
fn show_draws_a_chart_and_refuses_a_two_series_pie_or_an_overfull_one() {
    let pts = |n: usize| (0..n).map(|i| serde_json::json!([format!("x{i}"), i])).collect::<Vec<_>>();
    let chart = |kind: &str, x: &str, series: serde_json::Value| serde_json::json!({"kind": "chart", "props": {"chart": kind, "x": x, "series": series}});
    let bar = chart("bar", "category", serde_json::json!([{"name": "a", "points": pts(3)}]));
    let seven: Vec<_> = (0..7).map(|k| serde_json::json!({"name": format!("s{k}"), "points": pts(2)})).collect();
    // At most 8 tool calls a turn; the number and missing-x caps are pinned in renderers.rs and the fixture.
    let bad = [
        (chart("pie", "category", serde_json::json!([{"name": "a", "points": pts(2)}, {"name": "b", "points": pts(2)}])), "exactly 1 series"),
        (chart("bar", "category", serde_json::json!(seven)), "chart series: 7, at most 6"),
        (chart("line", "category", serde_json::json!([{"name": "a", "points": pts(61)}])), "61, at most 60"),
        (chart("line", "category", serde_json::json!([{"name": "a", "points": pts(2)}, {"name": "b", "points": pts(1)}])), "the same x"),
        (chart("bar", "category", serde_json::json!([{"name": "a", "points": [["x", "1"]]}])), "invalid type"),
        (chart("line", "time", serde_json::json!([{"name": "a", "points": [["yesterday", 1]]}])), "is not a date"),
        // Only a widget's chart may be empty (check_allow_empty); the model's has something to plot.
        (chart("bar", "category", serde_json::json!([{"name": "a", "points": []}])), "a chart has no points"),
    ];
    let mut model = vec![show(bar)];
    model.extend(bad.iter().map(|(c, _)| show(c.clone())));
    model.push(answer("done"));
    let rig = rig("chart", mapped(), ROWS, model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "chart it");
    assert_eq!(drawn_kinds(&got), ["chart"], "only the valid chart is drawn: {got:?}");
    assert_eq!(tool_result(&rig, 1), serde_json::json!({"shown": "chart"}));
    for (i, (_, want)) in bad.iter().enumerate() {
        let e = tool_result(&rig, i + 2);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(want)), "show #{} must be refused naming {want}: {e}", i + 2);
    }
}

/// The model is offered every kind the contract decodes, and told x is always a quoted string.
#[test]
fn show_offers_every_chart_kind_and_axis() {
    let schema = serve::show_schema();
    let chart = schema["properties"]["component"]["oneOf"].as_array().unwrap().iter()
        .find(|b| b["properties"]["kind"]["const"] == "chart").unwrap()["properties"]["props"].clone();
    let kinds = ["bar", "stacked_bar", "line", "area", "scatter", "pie"];
    assert_eq!(chart["properties"]["chart"]["enum"], serde_json::json!(kinds));
    assert_eq!(chart["properties"]["x"]["enum"], serde_json::json!(["category", "number", "time"]));
    assert!(chart["required"].as_array().unwrap().contains(&serde_json::json!("x")), "{chart}");
    let shape = serve::SHOW_SHAPE.iter().find(|(k, _)| *k == "chart").unwrap().1;
    for word in kinds.iter().chain(&["category|number|time", "x is a string"]) {
        assert!(shape.contains(word), "SHOW_SHAPE chart lacks {word:?}: {shape}");
    }
    for k in kinds {
        let c = serde_json::json!({"kind": "chart", "props": {"chart": k, "x": "number", "series": [{"name": "a", "points": [["3", 5]]}]}});
        let c: nos_contract::renderers::Component = serde_json::from_value(c).unwrap_or_else(|e| panic!("{k}: {e}"));
        assert_eq!(c.check(), Ok(()), "{k}");
    }
}

// --- live 2026-10-13: a chart by track, the time, a blank answer ---

#[test]
fn query_rows_groups_by_a_column_and_counts_exactly() {
    // Live: "next rows as a chart by track" got 50 of 136 rows and no count per track, so no chart.
    let rig = rig_n("group", mapped(), shown_then(&[]),
        vec![query(r#"{"table": "todos", "group_by": "status"}"#), call("propose_row_edit", r#"{"table": "todos", "row_id": "open", "cells": {"title": "x"}}"#), answer("2 open.")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "how many per status?");
    let g = tool_result(&rig, 1);
    assert_eq!(g["groups"], serde_json::json!([{"value": "open", "count": 2}, {"value": null, "count": 1}]), "{g}");
    assert_eq!((&g["matched"], &g["total"]), (&serde_json::json!(3), &serde_json::json!(3)), "{g}");
    let shown = renders(&got);
    assert_eq!(shown[0]["columns"], serde_json::json!(["status", "count"]), "{}", shown[0]);
    assert!(shown[0]["query"].as_str().unwrap().contains("grouped by status"), "{}", shown[0]);
    // A group is not a row: its value never unlocks a proposal.
    let e = tool_result(&rig, 2);
    assert!(e["error"].as_str().is_some_and(|e| e.contains("was not shown")), "{e}");
}

#[test]
fn a_vector_column_never_reaches_the_model_or_the_screen() {
    // Live: every roadmap row carried a 768-float embedding to the model and a column to the pupil.
    const VSCHEMA: &str = r#"{"success": true, "data": {"title": "Todo list", "schema": {"columns": [
        {"key": "title", "kind": "text"}, {"key": "embedding", "kind": "vector"}]}}}"#;
    const VROWS: &str = r#"{"success": true, "data": {"rows": [{"id": "r1", "values": {"title": "a", "embedding": [0.1, 0.2]}}]}}"#;
    let rig = rig_n("vector", mapped(), vec![VSCHEMA.into(), VROWS.into()], vec![query(r#"{"table": "todos"}"#), answer("x")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "rows");
    let t = tool_result(&rig, 1);
    assert!(!t.to_string().contains("embedding"), "{t}");
    assert!(!serde_json::to_string(&renders(&got)).unwrap().contains("embedding"), "{got:?}");
}

#[test]
fn the_prompt_says_the_time_and_to_admit_what_no_tool_sees() {
    // Live: Iris answered "10:50 UTC" at 05:15 and read "red status" as roadmap rows.
    let rig = rig("now", mapped(), ROWS, vec![answer("hi")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    turn(&s, &mut r, None, "what time is it?");
    let p = system_prompt(&rig);
    let now = p.split("It is now ").nth(1).and_then(|t| t.split(" UTC").next()).unwrap_or_else(|| panic!("{p}"));
    assert!(now.len() == 16 && now.starts_with("20") && &now[10..11] == " ", "YYYY-MM-DD HH:MM, got {now:?}");
    assert!(p.contains("When no tool can see what is asked, say so"), "{p}");
    // Live: after a chart, Iris listed its numbers again and linked a placeholder image.
    assert!(p.contains("never repeat in text what a tool or show already drew"), "{p}");
}

#[test]
fn show_draws_a_tree_and_a_timeline_and_refuses_over_cap() {
    let tree = serde_json::json!({"kind": "tree", "props": {"title": "Roadmap", "nodes": [
        {"label": "nOS", "children": [{"label": "pupil", "note": "the eye"}, {"label": "keap"}]}]}});
    let timeline = serde_json::json!({"kind": "timeline", "props": {"title": "History", "items": [
        {"when": "2026-10-12", "title": "I4a landed", "note": "query_rows"},
        {"when": "2026-10-13", "title": "chart", "hi": true}]}});
    let mut deep = serde_json::json!({"label": "leaf"});
    for i in (0..4).rev() {
        deep = serde_json::json!({"label": format!("n{i}"), "children": [deep]});
    }
    let deep = serde_json::json!({"kind": "tree", "props": {"nodes": [deep]}});
    let nodes: Vec<_> = (0..101).map(|i| serde_json::json!({"label": format!("n{i}")})).collect();
    let wide = serde_json::json!({"kind": "tree", "props": {"nodes": nodes}});
    let items: Vec<_> = (0..31).map(|i| serde_json::json!({"when": format!("d{i}"), "title": format!("t{i}")})).collect();
    let long = serde_json::json!({"kind": "timeline", "props": {"items": items}});
    let bad = [
        (deep, "tree depth: 5, at most 4"),
        (wide, "tree nodes: 101, at most 100"),
        (long, "timeline items: 31, at most 30"),
        (serde_json::json!({"kind": "timeline", "props": {"items": [{"when": "2026-10-05", "until": "2026-10-01", "title": "I5a"}]}}),
         "ends before it starts"),
    ];
    let mut model = vec![show(tree), show(timeline)];
    model.extend(bad.iter().map(|(c, _)| show(c.clone())));
    model.push(answer("done"));
    let rig = rig("treetime", mapped(), ROWS, model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "show the shape");
    assert_eq!(drawn_kinds(&got), ["tree", "timeline"], "only the valid kinds are drawn: {got:?}");
    for (i, (_, want)) in bad.iter().enumerate() {
        let e = tool_result(&rig, i + 3);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(want)), "show #{} must be refused naming {want}: {e}", i + 3);
    }
}

#[test]
fn a_blank_answer_is_said_not_drawn_empty() {
    let rig = rig("blank", mapped(), ROWS, vec![answer("  ")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "chart it");
    assert!(matches!(got.last(), Some(ToShell::Text { text, .. }) if text.contains("no answer")), "{got:?}");
}

#[test]
fn the_prompt_picks_a_component_by_shape_and_a_refusal_shows_it() {
    // A bad field must come back naming that field and the shape the kind accepts.
    let bad = serde_json::json!({"kind": "list", "props": {"ordered": false, "items": [{"text": "x", "html": "<b>"}]}});
    let rig = rig("pick", mapped(), ROWS, vec![show(bad), answer("done")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "hi");
    assert!(drawn_kinds(&got).is_empty(), "a refused show was drawn: {got:?}");
    let p = system_prompt(&rig);
    for line in [
        "count per value -> chart",
        "many rows -> query_rows",
        "one thing -> record",
        "steps -> list",
        "history -> timeline",
        "hierarchy -> tree",
        "Conclusion first, in one line",
        "Never invent data",
        "no numbers, no chart",
        "no visual for small talk or a one-line answer",
    ] {
        assert!(p.contains(line), "prompt missing {line:?}:\n{p}");
    }
    let msg = tool_result(&rig, 1)["error"].as_str().unwrap_or("").to_string();
    assert!(msg.contains("html"), "the refusal must name the field: {msg}");
    assert!(msg.contains("expected shape:"), "the refusal must show the accepted shape: {msg}");
    assert!(msg.contains("items[{text, detail?, tone?"), "the list shape is missing: {msg}");
}

/// The model is offered spans and lanes in both places it reads a shape.
#[test]
fn show_offers_a_timeline_span_and_lane() {
    let schema = serve::show_schema();
    let branch = schema["properties"]["component"]["oneOf"].as_array().unwrap().iter()
        .find(|b| b["properties"]["kind"]["const"] == "timeline").unwrap().clone();
    let item = &branch["properties"]["props"]["properties"]["items"]["items"]["properties"];
    assert_eq!(item["until"]["type"], "string", "{item}");
    assert_eq!(item["lane"]["maxLength"], 40, "{item}");
    let shape = serve::SHOW_SHAPE.iter().find(|(k, _)| *k == "timeline").unwrap().1;
    assert!(shape.contains("until?") && shape.contains("lane?"), "{shape}");
}

#[test]
fn show_draws_a_graph_and_refuses_an_edge_to_nowhere() {
    let graph = serde_json::json!({"kind": "graph", "props": {"title": "Organs", "nodes": [
        {"id": "bone", "label": "Bone", "note": "the bridge"}, {"id": "wing", "label": "Wing", "tone": "warn"}],
        "edges": [{"from": "bone", "to": "wing", "label": "events"}, {"from": "wing", "to": "bone", "dashed": true}]}});
    let nowhere = serde_json::json!({"kind": "graph", "props": {"nodes": [{"id": "a", "label": "A"}],
        "edges": [{"from": "a", "to": "ghost"}]}});
    let nodes: Vec<_> = (0..61).map(|i| serde_json::json!({"id": format!("n{i}"), "label": format!("n{i}")})).collect();
    let wide = serde_json::json!({"kind": "graph", "props": {"nodes": nodes, "edges": []}});
    let bad = [(nowhere, r#"names no node "ghost""#), (wide, "graph nodes: 61, at most 60")];
    let mut model = vec![show(graph)];
    model.extend(bad.iter().map(|(c, _)| show(c.clone())));
    model.push(answer("done"));
    let rig = rig("graph", mapped(), ROWS, model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "show how the organs connect");
    assert_eq!(drawn_kinds(&got), ["graph"], "only the valid graph is drawn: {got:?}");
    for (i, (_, want)) in bad.iter().enumerate() {
        let e = tool_result(&rig, i + 2);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(want)), "show #{} must be refused naming {want}: {e}", i + 2);
    }
    let p = system_prompt(&rig);
    assert!(p.contains("links between things -> graph"), "{p}");
}

/// The model is offered nodes, edges and their caps in both places it reads a shape.
#[test]
fn show_offers_a_graph() {
    let schema = serve::show_schema();
    let branch = schema["properties"]["component"]["oneOf"].as_array().unwrap().iter()
        .find(|b| b["properties"]["kind"]["const"] == "graph").unwrap_or_else(|| panic!("no graph branch")).clone();
    let props = &branch["properties"]["props"]["properties"];
    assert_eq!(props["nodes"]["maxItems"], 60, "{props}");
    assert_eq!(props["edges"]["maxItems"], 120, "{props}");
    assert_eq!(props["nodes"]["items"]["properties"]["id"]["pattern"], "^[A-Za-z0-9_-]{1,64}$", "{props}");
    let shape = serve::SHOW_SHAPE.iter().find(|(k, _)| *k == "graph").unwrap().1;
    assert!(shape.contains("nodes[{id, label, note?, tone?}]") && shape.contains("edges[{from, to, label?, dashed?}]"), "{shape}");
}

// --- genui I5a: one list of show kinds, so a fifth hand-kept copy cannot drift ---

/// The model-facing kinds named in four places in serve.rs and once in the spec must be one set.
#[test]
fn show_kinds_agree_everywhere() {
    let kinds: Vec<&str> = serve::SHOW_KINDS.to_vec();
    let shape: Vec<&str> = serve::SHOW_SHAPE.iter().map(|(k, _)| *k).collect();
    assert_eq!(shape, kinds, "SHOW_SHAPE keys");
    let schema = serve::show_schema();
    let consts: Vec<&str> = schema["properties"]["component"]["oneOf"].as_array().unwrap().iter()
        .map(|b| b["properties"]["kind"]["const"].as_str().unwrap()).collect();
    assert_eq!(consts, kinds, "show_schema oneOf kind consts");
    let spec = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../../contracts/thalamus-shell.yml")).unwrap();
    let spec: serde_yaml_ng::Value = serde_yaml_ng::from_str(&spec).unwrap();
    let tool_chosen = ["table_results", "row_diff_approval", "inbox_list", "approvals_list", "red_status", "markdown", "form"];
    let mut vocab: Vec<String> = spec["components"]["vocabulary"].as_mapping().unwrap().keys()
        .map(|k| k.as_str().unwrap().to_string()).filter(|k| !tool_chosen.contains(&k.as_str())).collect();
    let mut want: Vec<String> = kinds.iter().map(|k| k.to_string()).collect();
    vocab.sort();
    want.sort();
    assert_eq!(vocab, want, "thalamus-shell.yml vocabulary minus the tool-chosen kinds");
}

// --- genui I5e: a widget form is built by serve from the live schema, never by the model ---

/// GET /api/tables/expenses as KEAP answers it: zod fills `required` (default false) on every
/// stored column (keap shared/contracts/table.ts:55, served whole by server/routes.ts:604-619);
/// `when` leaves it out here so an older row still reads as optional.
fn expenses(extra: &str) -> String {
    let many = (0..51).map(|i| format!(r#""o{i}""#)).collect::<Vec<_>>().join(",");
    format!(r#"{{"success": true, "data": {{"id": "expenses", "title": "Expenses", "schema": {{"columns": [
        {{"key": "note", "label": "Note", "kind": "text", "required": false}},
        {{"key": "amount", "label": "Amount", "kind": "number", "required": true}},
        {{"key": "when", "label": "When", "kind": "date"}},
        {{"key": "kind", "label": "Kind", "kind": "select", "required": true, "options": ["food", "travel", "tools"]}},
        {{"key": "paid", "label": "Paid", "kind": "boolean", "required": false}},
        {{"key": "receipt", "label": "Receipt", "kind": "file", "required": false}},
        {{"key": "__shared_with", "label": "Shared", "kind": "json", "required": false}},
        {{"key": "many", "label": "Many", "kind": "select", "required": false, "options": [{many}]}},
        {{"key": "none", "label": "None", "kind": "select", "required": false, "options": []}}{extra}]}}}}}}"#)
}

/// The form serve built, as its wire props without the minted id (checked to be a uuid).
fn built(rig: &Rig, columns: Option<&[&str]>) -> Result<serde_json::Value, String> {
    let cols: Option<Vec<String>> = columns.map(|c| c.iter().map(|s| s.to_string()).collect());
    let f = rig.srv.form_from_schema(&alice(), "expenses", cols.as_deref())?;
    let mut v = serde_json::to_value(Component::Form(f)).unwrap();
    assert_eq!(v["kind"], "form");
    let id = v["props"].as_object_mut().unwrap().remove("form").unwrap();
    assert!(nos_contract::wire::is_uuid(id.as_str().unwrap()), "the form id is a uuid serve minted: {id}");
    Ok(v["props"].clone())
}

#[test]
fn form_from_schema_maps_each_column_to_a_field() {
    let rig = rig("formmap", mapped(), &expenses(""), vec![answer("x")]);
    let f = built(&rig, None).unwrap();
    assert_eq!(f["table"], "expenses");
    assert_eq!(f["title"], "Expenses", "the table's own title, never a model's");
    assert_eq!(f["fields"], serde_json::json!([
        {"key": "note", "label": "Note", "kind": "text", "required": false},
        {"key": "amount", "label": "Amount", "kind": "number", "required": true},
        {"key": "when", "label": "When", "kind": "date", "required": false},
        {"key": "kind", "label": "Kind", "kind": "select", "required": true, "options": ["food", "travel", "tools"]},
        {"key": "paid", "label": "Paid", "kind": "bool", "required": false},
        {"key": "many", "label": "Many", "kind": "text", "required": false},
        {"key": "none", "label": "None", "kind": "text", "required": false}]),
        "boolean is bool; a select of 0 or 51 options is text; __shared_with is dropped");
    assert_eq!(f["omitted"], serde_json::json!([{"key": "receipt", "kind": "file"}]), "an optional file has no field");
    let seen = rig.keap.lock().unwrap().clone();
    assert_eq!(seen.len(), 1, "one schema read, no rows: {seen:?}");
    assert!(seen[0].0.starts_with("GET /api/tables/expenses "), "{}", seen[0].0);
    assert!(seen[0].0.to_ascii_lowercase().contains("x-authentik-username: alice smith"), "read as the person");
}

#[test]
fn form_from_schema_refuses_a_required_column_it_cannot_draw() {
    let rig = rig("formreq", mapped(), &expenses(r#", {"key": "meta", "label": "Meta", "kind": "json", "required": true}"#), vec![answer("x")]);
    assert_eq!(built(&rig, None), Err("column meta (json) is required and has no form field".into()));
}

#[test]
fn form_from_schema_narrows_to_columns_and_keeps_a_required_refusal() {
    let rig = rig("formcols", mapped(), &expenses(""), vec![answer("x")]);
    let f = built(&rig, Some(&["kind", "amount"])).unwrap();
    let keys: Vec<&str> = f["fields"].as_array().unwrap().iter().map(|x| x["key"].as_str().unwrap()).collect();
    assert_eq!(keys, ["amount", "kind"], "the table's order, only the named columns");
    assert_eq!(f["omitted"], serde_json::json!([]), "a column left out by `columns` is not 'not editable here'");
    assert_eq!(built(&rig, Some(&["note"])), Err("column amount (number) is required and has no form field".into()));
    assert_eq!(built(&rig, Some(&["ghost"])), Err("no column `ghost` in Expenses; columns: note, amount, when, kind, paid, receipt, many, none".into()));
}

#[test]
fn show_refuses_form() {
    let form = serde_json::json!({"kind": "form", "props": {"form": "5f0c1b2a-3d4e-4f5a-8b6c-7d8e9f0a1b2c", "table": "expenses",
        "title": "Expenses", "fields": [{"key": "amount", "label": "Amount", "kind": "number", "required": true}], "omitted": []}});
    let rig = rig("showform", mapped(), ROWS, vec![show(form), answer("done")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "give me a form to add an expense");
    assert!(drawn_kinds(&got).is_empty(), "the model drew a form: {got:?}");
    let e = tool_result(&rig, 1);
    assert!(e["error"].as_str().is_some_and(|e| e.contains(r#"not "form""#)), "{e}");
    assert!(rig.keap.lock().unwrap().is_empty(), "show read KEAP");
}

// --- genui I5f: a widget runs as the person without the model; its chart is aggregated here ---

/// KEAP's table routes over one in-memory table: GET the schema, GET the rows paged as KEAP
/// pages them (`limit`, then `cursor` while `nextCursor` is set), POST an upsert that mints an
/// id when none is given. `schema` is the whole GET /api/tables/:id body. Every request is seen.
fn fake_table(schema: &str, rows: Vec<serde_json::Value>) -> ((String, Seen), Arc<Mutex<Vec<serde_json::Value>>>) {
    let info: serde_json::Value = serde_json::from_str(schema).unwrap();
    let base = format!("/api/tables/{}", info["data"]["id"].as_str().unwrap());
    let schema = schema.to_string();
    let table = Arc::new(Mutex::new(rows));
    let held = table.clone();
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", l.local_addr().unwrap());
    let seen: Seen = Arc::default();
    let s = seen.clone();
    std::thread::spawn(move || {
        for c in l.incoming() {
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
            let mut words = head.split_whitespace();
            let (method, target) = (words.next().unwrap_or(""), words.next().unwrap_or(""));
            let (path, query) = target.split_once('?').unwrap_or((target, ""));
            let arg = |k: &str| query.split('&').find_map(|p| p.strip_prefix(&format!("{k}="))).and_then(|v| v.parse::<usize>().ok());
            let mut rows = table.lock().unwrap();
            let (status, out) = match (method, path) {
                ("GET", p) if p == base => (200, schema.clone()),
                ("GET", p) if p == format!("{base}/rows") => {
                    let (from, limit) = (arg("cursor").unwrap_or(0), arg("limit").unwrap_or(50));
                    let to = (from + limit).min(rows.len());
                    let next = (to < rows.len()).then(|| to.to_string());
                    (200, serde_json::json!({"success": true, "data": {"rows": rows[from..to], "nextCursor": next}}).to_string())
                }
                ("POST", p) if p == format!("{base}/rows") => {
                    let b: serde_json::Value = serde_json::from_str(&body).unwrap();
                    let id = b["id"].as_str().map(str::to_string).unwrap_or_else(|| format!("minted-{}", rows.len() + 1));
                    let row = serde_json::json!({"id": id, "values": b["values"]});
                    match rows.iter_mut().find(|r| r["id"] == row["id"]) {
                        Some(r) => *r = row.clone(),
                        None => rows.push(row.clone()),
                    }
                    (200, serde_json::json!({"success": true, "data": row}).to_string())
                }
                _ => (404, r#"{"success": false, "error": "no such route"}"#.to_string()),
            };
            write!(c, "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{out}", out.len())
                .unwrap();
        }
    });
    ((url, seen), held)
}

fn keap_row(id: &str, values: serde_json::Value) -> serde_json::Value {
    serde_json::json!({"id": id, "values": values})
}

/// GET /api/tables/sheet: a select, a number, a date (KEAP: epoch seconds), a text and a count.
const SHEET: &str = r#"{"success": true, "data": {"id": "sheet", "title": "Sheet", "schema": {"columns": [
    {"key": "status", "label": "Status", "kind": "select", "options": ["open", "done"], "required": false},
    {"key": "amount", "label": "Amount", "kind": "number", "required": false},
    {"key": "when", "label": "When", "kind": "date", "required": false},
    {"key": "note", "label": "Note", "kind": "text", "required": false},
    {"key": "n", "label": "N", "kind": "number", "required": false}]}}}"#;

fn send_widget(s: &UnixStream, token: &str, spec: serde_json::Value, trigger: &str) {
    let mut w = s;
    let m = serde_json::json!({"t": "widget", "widget": token, "spec": spec, "trigger": trigger});
    w.write_all(format!("{m}\n").as_bytes()).unwrap();
}

/// (type, task, result) of every ledger event of a session, in order.
fn events(ledger: &std::path::Path, session: &str) -> Vec<(String, String, serde_json::Value)> {
    let db = rusqlite::Connection::open(ledger).unwrap();
    let mut q = db.prepare("SELECT type, COALESCE(task, ''), COALESCE(result_json, 'null') FROM events WHERE run_id = ?1 ORDER BY id").unwrap();
    q.query_map([session], |r| Ok((r.get(0)?, r.get(1)?, r.get::<_, String>(2)?))).unwrap().map(Result::unwrap)
        .map(|(t, k, v)| (t, k, serde_json::from_str(&v).unwrap())).collect()
}

/// One widget run on a fresh connection: (session, the answer as wire JSON).
fn run_widget(rig: &Rig, token: &str, spec: serde_json::Value) -> (String, serde_json::Value) {
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    send_widget(&s, token, spec, "click");
    let session = match next(&mut r) {
        Some(ToShell::Session { session, .. }) => session,
        other => panic!("a widget opens the session first, got {other:?}"),
    };
    (session, serde_json::to_value(next(&mut r).expect("an answer")).unwrap())
}

fn sheet_rig(name: &str, rows: Vec<serde_json::Value>) -> Rig {
    rig_at(name, mapped(), fake_table(SHEET, rows).0, vec![answer("never")], Some(local()))
}

/// The chart a widget spec over `rows` of the sheet answers, as wire props; panics on anything else.
fn widget_chart(name: &str, rows: Vec<serde_json::Value>, spec: serde_json::Value) -> serde_json::Value {
    let rig = sheet_rig(name, rows);
    let (_, w) = run_widget(&rig, "c1", serde_json::json!({"chart": spec}));
    assert_eq!((&w["t"], &w["widget"], &w["component"]["kind"]), (&serde_json::json!("widget"), &serde_json::json!("c1"), &serde_json::json!("chart")),
               "{name}: {w}");
    assert!(rig.model.lock().unwrap().is_empty(), "{name}: a widget asked the model");
    w["component"]["props"].clone()
}

fn points(props: &serde_json::Value) -> Vec<(String, f64)> {
    let series = props["series"].as_array().unwrap();
    assert_eq!(series.len(), 1, "a widget chart is one series: {props}");
    series[0]["points"].as_array().unwrap().iter().map(|p| (p[0].as_str().unwrap().to_string(), p[1].as_f64().unwrap())).collect()
}

fn pts(want: &[(&str, f64)]) -> Vec<(String, f64)> {
    want.iter().map(|(x, y)| (x.to_string(), *y)).collect()
}

fn statuses() -> Vec<serde_json::Value> {
    [("a", "open", 1), ("b", "done", 10), ("c", "open", 2), ("d", "open", 3)].iter()
        .map(|(id, st, n)| keap_row(id, serde_json::json!({"status": st, "amount": n}))).collect()
}

#[test]
fn widget_rows_runs_as_the_person_without_the_model() {
    let rows = vec![keap_row("r1", serde_json::json!({"title": "Alpha one", "status": "open", "ordinal": 3})),
                    keap_row("r2", serde_json::json!({"title": "beta"}))];
    let rig = rig_at("wrows", mapped(), fake_table(SCHEMA, rows).0, vec![call("propose_row_edit", EDIT), answer("x")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    send_widget(&s, "w-1", serde_json::json!({"rows": {"table": "todos"}}), "restore");
    let Some(ToShell::Session { session, .. }) = next(&mut r) else { panic!("no session") };
    let w = serde_json::to_value(next(&mut r).unwrap()).unwrap();
    assert_eq!((&w["t"], &w["session"], &w["widget"]), (&serde_json::json!("widget"), &serde_json::json!(session), &serde_json::json!("w-1")), "{w}");
    let ids: Vec<&str> = w["component"]["props"]["rows"].as_array().unwrap().iter().map(|r| r["__id"].as_str().unwrap()).collect();
    assert_eq!(ids, ["r1", "r2"], "{w}");
    assert!(rig.model.lock().unwrap().is_empty(), "a widget asked the model");
    let ev = events(&rig.ledger, &session);
    let used: Vec<_> = ev.iter().filter(|e| e.0 == "agent_tool_use").collect();
    assert_eq!(used.len(), 1, "{ev:?}");
    assert_eq!(used[0].1, "agent:iris/tool:widget_rows");
    assert_eq!((&used[0].2["table"], &used[0].2["kind"], &used[0].2["trigger"], &used[0].2["widget"]),
               (&serde_json::json!("todos"), &serde_json::json!("rows"), &serde_json::json!("restore"), &serde_json::json!("w-1")), "{:?}", used[0]);
    assert!(ev.iter().any(|e| e.0 == "agent_tool_result" && e.1 == "agent:iris/tool:widget_rows" && e.2["rows"] == serde_json::json!(["r1", "r2"])), "{ev:?}");
    // The model never saw r1, so it may not propose an edit to it.
    turn(&s, &mut r, Some(session), "close alpha");
    let e = tool_result(&rig, 1);
    assert!(e["error"].as_str().is_some_and(|e| e.contains("was not shown to the person")), "{e}");
    assert!(posts(&rig).is_empty());
}

#[test]
fn widget_chart_aggregates_server_side() {
    let count = widget_chart("wcount", statuses(), serde_json::json!({"query": {"table": "sheet"}, "chart": "bar", "x": "status", "op": "count"}));
    assert_eq!(count["x"], "category");
    assert_eq!(count["chart"], "bar");
    assert_eq!(points(&count), pts(&[("open", 3.0), ("done", 1.0)]));
    let sum = widget_chart("wsum", statuses(), serde_json::json!({"query": {"table": "sheet"}, "chart": "pie", "x": "status", "y": "amount", "op": "sum"}));
    assert_eq!(points(&sum), pts(&[("done", 10.0), ("open", 6.0)]), "by value, largest first");
    let avg = widget_chart("wavg", statuses(), serde_json::json!({"query": {"table": "sheet", "where": [{"column": "status", "op": "eq", "value": "open"}]},
        "chart": "bar", "x": "status", "y": "amount", "op": "avg"}));
    assert_eq!(points(&avg), pts(&[("open", 2.0)]), "the query's where narrows the rows first");
    let mut empty = statuses();
    empty.push(keap_row("e", serde_json::json!({"amount": 5})));
    assert_eq!(points(&widget_chart("wempty", empty, serde_json::json!({"query": {"table": "sheet"}, "chart": "bar", "x": "status", "op": "count"}))),
               pts(&[("open", 3.0), ("done", 1.0), ("(empty)", 1.0)]));

    let many: Vec<_> = (0..70).map(|i| keap_row(&format!("m{i}"), serde_json::json!({"note": format!("c{i:02}"), "amount": 70 - i}))).collect();
    let over = points(&widget_chart("wover", many, serde_json::json!({"query": {"table": "sheet"}, "chart": "bar", "x": "note", "y": "amount", "op": "sum"})));
    assert_eq!(over.len(), 60, "59 and other");
    assert_eq!(over[0], ("c00".to_string(), 70.0));
    assert_eq!(over[58], ("c58".to_string(), 12.0));
    assert_eq!(over[59], ("other".to_string(), (1..=11).sum::<i32>() as f64), "the rest is summed into other");

    // A date column is days on a time axis, oldest first: the last 60 days, no "other".
    const DAY0: i64 = 1_785_542_400; // 2026-08-01T00:00:00Z
    let days: Vec<_> = (0..70).flat_map(|d| [0, 3600].map(|t| keap_row(&format!("d{d}-{t}"), serde_json::json!({"when": DAY0 + d * 86_400 + t}))))
        .rev().collect();
    let time = widget_chart("wtime", days, serde_json::json!({"query": {"table": "sheet"}, "chart": "line", "x": "when", "op": "count"}));
    assert_eq!(time["x"], "time");
    let p = points(&time);
    assert_eq!(p.len(), 60);
    assert_eq!((p[0].clone(), p[59].clone()), (("2026-08-11".to_string(), 2.0), ("2026-10-09".to_string(), 2.0)), "two rows a day, bucketed to the UTC day");
    assert!(p.iter().all(|(x, _)| x != "other"), "time has no other");
    assert!(time["title"].as_str().is_some_and(|t| t.contains("last 60 days")), "{time}");

    let nums: Vec<_> = [5, -1, 3, 5].iter().enumerate().map(|(i, n)| keap_row(&format!("n{i}"), serde_json::json!({"n": n}))).collect();
    let num = widget_chart("wnum", nums, serde_json::json!({"query": {"table": "sheet"}, "chart": "line", "x": "n", "op": "count"}));
    assert_eq!(num["x"], "number");
    assert_eq!(points(&num), pts(&[("-1", 1.0), ("3", 1.0), ("5", 2.0)]), "a number x ascending");

    // Nothing matched: one series, no points, which a widget may carry and the model may not.
    let none = widget_chart("wnone", statuses(), serde_json::json!({"query": {"table": "sheet", "q": "nothing like this"},
        "chart": "bar", "x": "status", "op": "count"}));
    assert_eq!(points(&none), vec![]);
}

#[test]
fn widget_refused_names_the_widget() {
    for (name, spec, want) in [
        ("wbadcol", serde_json::json!({"rows": {"table": "sheet", "where": [{"column": "kinds", "op": "eq", "value": "x"}]}}), "no column `kinds`"),
        ("wnoy", serde_json::json!({"chart": {"query": {"table": "sheet"}, "chart": "bar", "x": "status", "op": "sum"}}), "sum needs `y`"),
        ("wtexty", serde_json::json!({"chart": {"query": {"table": "sheet"}, "chart": "bar", "x": "status", "y": "note", "op": "avg"}}), "not a number column"),
        ("wnox", serde_json::json!({"chart": {"query": {"table": "sheet"}, "chart": "bar", "x": "ghost", "op": "count"}}), "no column `ghost`"),
    ] {
        let rig = sheet_rig(name, statuses());
        let (session, w) = run_widget(&rig, "w9", spec);
        assert_eq!((&w["t"], &w["widget"]), (&serde_json::json!("refused"), &serde_json::json!("w9")), "{name}: {w}");
        assert!(w["reason"].as_str().is_some_and(|r| r.contains(want)), "{name}: {w}");
        // The connection is gone by now, so its session_end may or may not have landed.
        let ev: Vec<_> = events(&rig.ledger, &session).into_iter().filter(|e| e.0 != "agent_session_end").collect();
        let kinds: Vec<&str> = ev.iter().map(|e| e.0.as_str()).collect();
        assert_eq!(kinds, ["agent_session_start", "agent_tool_use", "agent_tool_result"], "{name}: {ev:?}");
        assert!(ev[2].2["error"].as_str().is_some_and(|e| e.contains(want)), "{name}: {ev:?}");
        assert!(posts(&rig).is_empty() && rig.model.lock().unwrap().is_empty(), "{name}");
    }
}

#[test]
fn widget_form_expands_the_schema() {
    let rig = rig_at("wform", mapped(), fake_table(&expenses(""), vec![]).0, vec![answer("never")], Some(local()));
    let (session, w) = run_widget(&rig, "f1", serde_json::json!({"form": {"table": "expenses", "columns": ["kind", "amount"]}}));
    assert_eq!((&w["t"], &w["widget"], &w["component"]["kind"]), (&serde_json::json!("widget"), &serde_json::json!("f1"), &serde_json::json!("form")), "{w}");
    let f = &w["component"]["props"];
    assert_eq!((&f["table"], &f["title"]), (&serde_json::json!("expenses"), &serde_json::json!("Expenses")));
    let keys: Vec<&str> = f["fields"].as_array().unwrap().iter().map(|x| x["key"].as_str().unwrap()).collect();
    assert_eq!(keys, ["amount", "kind"]);
    assert!(nos_contract::wire::is_uuid(f["form"].as_str().unwrap()));
    let ev = events(&rig.ledger, &session);
    assert!(ev.iter().any(|e| e.0 == "agent_tool_use" && e.1 == "agent:iris/tool:widget_form" && e.2["table"] == "expenses"), "{ev:?}");
    assert!(ev.iter().all(|e| e.0 != "agent_approval_request"), "building a form asks nothing");
    assert!(posts(&rig).is_empty());
}

#[test]
fn widget_rows_renders_dates_as_days() {
    let rig = sheet_rig("wdays", vec![keap_row("a", serde_json::json!({"when": 1_760_283_000, "amount": 4}))]);
    let (_, w) = run_widget(&rig, "w1", serde_json::json!({"rows": {"table": "sheet"}}));
    let cells = &w["component"]["props"]["rows"][0]["cells"];
    assert_eq!((&cells["when"], &cells["amount"]), (&serde_json::json!("2025-10-12"), &serde_json::json!(4)), "{w}");
}

#[test]
fn a_widget_reads_every_page_of_the_stateful_fake() {
    // The fake pages as KEAP does, so serve's whole-table read is exercised, not one canned body.
    let rows: Vec<_> = (0..1203).map(|i| keap_row(&format!("p{i}"), serde_json::json!({"status": if i % 3 == 0 { "done" } else { "open" }}))).collect();
    let count = widget_chart("wpages", rows, serde_json::json!({"query": {"table": "sheet"}, "chart": "bar", "x": "status", "op": "count"}));
    assert_eq!(points(&count), pts(&[("open", 802.0), ("done", 401.0)]));
}

// --- genui I5g: a widget form's submit is the person's decision; commit() inserts the row ---

fn send_submit(s: &UnixStream, form: &str, widget: &str, values: serde_json::Value) {
    let mut w = s;
    let m = serde_json::json!({"t": "form_submit", "form": form, "widget": widget, "values": values});
    w.write_all(format!("{m}\n").as_bytes()).unwrap();
}

/// A widget form on this connection; its minted form id.
fn open_form(s: &UnixStream, r: &mut BufReader<UnixStream>, token: &str) -> String {
    send_widget(s, token, serde_json::json!({"form": {"table": "expenses"}}), "click");
    loop {
        match next(r) {
            Some(ToShell::Widget { widget, component: Component::Form(f), .. }) if widget == token => return f.form,
            Some(ToShell::Session { .. }) => continue,
            other => panic!("expected the widget form, got {other:?}"),
        }
    }
}

fn same_file(a: &str, b: &std::path::Path) -> bool {
    std::fs::canonicalize(a).ok() == std::fs::canonicalize(b).ok()
}

#[test]
fn form_submit_inserts_through_commit() {
    let ((url, seen), held) = fake_table(&expenses(""), vec![keap_row("e1", serde_json::json!({"kind": "food", "amount": 3}))]);
    let model = vec![query(r#"{"table": "expenses"}"#), call("propose_row_edit", r#"{"table": "expenses", "row_id": "e1", "values": {"amount": 4}}"#),
                     answer("Proposed."), answer("ok")];
    let rig = rig_at("fsubmit", mapped(), (url, seen), model, Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    // A model card waits while the person fills a form: the submit must leave it waiting.
    let got = turn(&s, &mut r, None, "set e1 to 4");
    let session = session_of(&got);
    let card = got.iter().find_map(|m| match m { ToShell::ApprovalRequest { approval, .. } => Some(approval.clone()), _ => None })
        .expect("the model's card waits");
    let form = open_form(&s, &mut r, "f1");
    send_submit(&s, &form, "f1", serde_json::json!({"kind": "tools", "amount": 42, "when": "2026-10-13", "note": "pens", "paid": true}));
    match next(&mut r) {
        Some(ToShell::TableChanged { session: s2, table, row }) => assert_eq!((s2, table, row.as_str()), (session.clone(), "expenses".into(), "minted-2")),
        other => panic!("expected table_changed, got {other:?}"),
    }
    match next(&mut r) {
        Some(ToShell::FormResult { session: s2, widget, form: f2, row }) =>
            assert_eq!((s2, widget.as_str(), f2, row.as_str()), (session.clone(), "f1", form.clone(), "minted-2")),
        other => panic!("expected form_result, got {other:?}"),
    }
    let p = posts(&rig);
    assert_eq!(p.len(), 1, "one insert: {p:?}");
    assert!(p[0].0.starts_with("POST /api/tables/expenses/rows "), "{}", p[0].0);
    assert_eq!(serde_json::from_str::<serde_json::Value>(&p[0].1).unwrap(),
               serde_json::json!({"values": {"kind": "tools", "amount": 42.0, "when": 1_791_849_600, "note": "pens", "paid": true}}),
               "no id (KEAP mints it); the day as its UTC-midnight epoch");
    assert_eq!(held.lock().unwrap().len(), 2, "the fake holds the new row");

    // The model's card is still the one waiting, and its approve takes the update path.
    decide(&s, &card, Decision::Approve);
    assert!(matches!(next(&mut r), Some(ToShell::TableChanged { ref table, ref row, .. }) if table == "expenses" && row == "e1"));
    assert!(matches!(next(&mut r), Some(ToShell::Text { ref text, .. }) if text.contains("row e1 written")));
    let p = posts(&rig);
    assert_eq!(serde_json::from_str::<serde_json::Value>(&p[1].1).unwrap(), serde_json::json!({"id": "e1", "values": {"amount": 4}}));
    // The model hears of its own card and nothing of the form.
    turn(&s, &mut r, Some(session.clone()), "thanks");
    let body: serde_json::Value = serde_json::from_str(&rig.model.lock().unwrap()[3].1).unwrap();
    let said: Vec<&str> = body["messages"].as_array().unwrap().iter().filter_map(|m| m["content"].as_str())
        .filter(|c| c.starts_with("[thalamus]")).collect();
    assert_eq!(said.len(), 1, "{said:?}");
    assert!(said[0].contains(&card) && !body.to_string().contains("minted-2"), "the model heard of the form: {said:?}");

    let ev: Vec<_> = events(&rig.ledger, &session).into_iter().filter(|e| e.1 == "agent:iris/tool:form_submit").collect();
    let kinds: Vec<&str> = ev.iter().map(|e| e.0.as_str()).collect();
    assert_eq!(kinds, ["agent_tool_use", "agent_approval_request", "agent_approval_decision", "agent_tool_result"], "{ev:?}");
    let (req, dec, res) = (&ev[1].2, &ev[2].2, &ev[3].2);
    assert_eq!((&req["op"], &req["table"], req.get("row_id")), (&serde_json::json!("insert"), &serde_json::json!("expenses"), None), "{req}");
    assert!(req["cells"].as_array().unwrap().iter().all(|c| c.get("old").is_none()), "{req}");
    assert!(req["cells"].as_array().unwrap().iter().any(|c| c["key"] == "when" && c["new"] == 1_791_849_600), "{req}");
    assert_eq!((&dec["decision"], &dec["note"], &dec["approval"]), (&serde_json::json!("approve"), &serde_json::json!("form submit"), &req["approval"]));
    assert_eq!(res["row"], "minted-2");
    let me = std::env::current_exe().unwrap();
    for e in [req, dec, res] {
        assert_eq!(e["peer"]["pid"], std::process::id(), "{e}");
        assert!(e["peer"]["exe"].as_str().is_some_and(|x| same_file(x, &me)), "peer.exe is not this test binary: {e}");
    }
    // The card's own decision names its peer too.
    let card_dec = events(&rig.ledger, &session).into_iter()
        .find(|e| e.0 == "agent_approval_decision" && e.1 == "agent:iris/tool:propose_row_edit").expect("the card's decision");
    assert!(card_dec.2["peer"]["exe"].as_str().is_some_and(|x| same_file(x, &me)), "{:?}", card_dec.2);
}

#[test]
fn form_submit_refuses_what_the_form_did_not_offer() {
    let ((url, seen), held) = fake_table(&expenses(""), vec![]);
    let rig = rig_at("frefuse", mapped(), (url, seen), vec![answer("never")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let form = open_form(&s, &mut r, "f1");
    let other = "1b7e6f3a-2c1d-4e5f-8a9b-1c2d3e4f5a6b";
    let ok = serde_json::json!({"kind": "tools", "amount": 42});
    let with = |k: &str, v: serde_json::Value| {
        let mut x = ok.clone();
        x[k] = v;
        x
    };
    let many: serde_json::Map<String, serde_json::Value> = (0..21).map(|i| (format!("k{i}"), serde_json::json!(1))).collect();
    let cases = [
        ("unknown form", other, "f1", ok.clone(), "not a form"),
        ("another widget's form", form.as_str(), "f2", ok.clone(), "not a form"),
        ("unknown key", form.as_str(), "f1", with("ghost", serde_json::json!("x")), "no field `ghost`"),
        ("a sharing key", form.as_str(), "f1", with("__shared_with", serde_json::json!("x")), "no field `__shared_with`"),
        ("an omitted column", form.as_str(), "f1", with("receipt", serde_json::json!("x")), "no field `receipt`"),
        ("select outside options", form.as_str(), "f1", with("kind", serde_json::json!("rent")), "not one of"),
        ("missing required", form.as_str(), "f1", serde_json::json!({"kind": "tools"}), "amount is required"),
        ("a string for a number", form.as_str(), "f1", with("amount", serde_json::json!("abc")), "amount is a number"),
        ("a 4001-char text", form.as_str(), "f1", with("note", serde_json::json!("x".repeat(4001))), "4000"),
        ("not a day", form.as_str(), "f1", with("when", serde_json::json!("2026-02-30")), "YYYY-MM-DD"),
        ("a number for a bool", form.as_str(), "f1", with("paid", serde_json::json!(1)), "paid is true or false"),
        ("21 keys", form.as_str(), "f1", serde_json::Value::Object(many), "at most 20"),
    ];
    for (name, f, w, values, want) in &cases {
        send_submit(&s, f, w, values.clone());
        match next(&mut r) {
            Some(ToShell::Refused { reason, widget }) => {
                assert_eq!(widget.as_deref(), Some(*w), "{name}: {reason}");
                assert!(reason.contains(want), "{name}: {reason}");
            }
            other => panic!("{name}: expected refused, got {other:?}"),
        }
    }
    assert!(posts(&rig).is_empty(), "a refused submit wrote");
    assert!(held.lock().unwrap().is_empty());
    drop((s, r));
    std::thread::sleep(std::time::Duration::from_millis(300));
    let session: String = rusqlite::Connection::open(&rig.ledger).unwrap()
        .query_row("SELECT uuid FROM sessions", [], |r| r.get(0)).unwrap();
    let ev: Vec<_> = events(&rig.ledger, &session).into_iter().filter(|e| e.1 == "agent:iris/tool:form_submit").collect();
    assert_eq!(ev.len(), 2 * cases.len(), "a ToolUse and a ToolResult per refusal: {ev:?}");
    for pair in ev.chunks(2) {
        assert_eq!((pair[0].0.as_str(), pair[1].0.as_str()), ("agent_tool_use", "agent_tool_result"), "{pair:?}");
        assert!(pair[1].2["error"].is_string(), "{pair:?}");
    }
    assert!(events(&rig.ledger, &session).iter().all(|e| !e.0.starts_with("agent_approval")), "a refused submit asked");
}

// --- thalamus-table-changed-broadcast: aliases, ledger-first, the form cap ---

#[test]
fn a_write_to_the_roadmap_says_table_changed_under_its_alias_too() {
    // A widget spec may say "roadmap"; the write lands in its id. Same value as the other alias test.
    std::env::set_var("NOS_ROADMAP_TABLE_ID", "rt-2d49");
    let schema = expenses("").replace(r#""id": "expenses""#, r#""id": "rt-2d49""#);
    let rig = rig_at("falias", mapped(), fake_table(&schema, vec![]).0, vec![answer("never")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    send_widget(&s, "f1", serde_json::json!({"form": {"table": "roadmap"}}), "click");
    let Some(ToShell::Session { .. }) = next(&mut r) else { panic!("no session") };
    let Some(ToShell::Widget { component: Component::Form(f), .. }) = next(&mut r) else { panic!("no form") };
    send_submit(&s, &f.form, "f1", serde_json::json!({"kind": "tools", "amount": 1}));
    let mut said = vec![];
    loop {
        match next(&mut r) {
            Some(ToShell::TableChanged { table, .. }) => said.push(table),
            Some(ToShell::FormResult { .. }) => break,
            other => panic!("expected table_changed or form_result, got {other:?}"),
        }
    }
    assert_eq!(said, ["rt-2d49", "roadmap"], "a widget naming the alias never re-runs");
}

#[test]
fn a_form_submit_is_in_the_ledger_before_the_shell_hears_it() {
    let rig = rig_at("fledger", mapped(), fake_table(&expenses(""), vec![]).0, vec![answer("never")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let form = open_form(&s, &mut r, "f1");
    let session: String = rusqlite::Connection::open(&rig.ledger).unwrap()
        .query_row("SELECT uuid FROM sessions", [], |r| r.get(0)).unwrap();
    // From the insert's POST on, the ledger's write lock is held: a result not yet recorded waits under it.
    let (seen, db) = (rig.keap.clone(), rig.ledger.clone());
    let holder = std::thread::spawn(move || {
        let c = rusqlite::Connection::open(db).unwrap();
        while !seen.lock().unwrap().iter().any(|(h, _)| h.starts_with("POST ")) {}
        c.execute_batch("BEGIN IMMEDIATE").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(500));
        c.execute_batch("ROLLBACK").unwrap();
    });
    send_submit(&s, &form, "f1", serde_json::json!({"kind": "tools", "amount": 1}));
    for want in ["table_changed", "form_result"] {
        let got = next(&mut r).expect("an answer");
        assert_eq!(serde_json::to_value(&got).unwrap()["t"], want);
        let ev = events(&rig.ledger, &session);
        assert!(ev.iter().any(|e| e.0 == "agent_tool_result" && e.1 == "agent:iris/tool:form_submit" && e.2["written"] == true),
                "{want} reached the shell before its result was recorded: {ev:?}");
    }
    holder.join().unwrap();
}

#[test]
fn a_widget_re_run_drops_its_old_form() {
    let rig = rig_at("frerun", mapped(), fake_table(&expenses(""), vec![]).0, vec![answer("never")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let ok = serde_json::json!({"kind": "tools", "amount": 1});
    let refused = |r: &mut BufReader<UnixStream>| match next(r) {
        Some(ToShell::Refused { reason, .. }) => assert!(reason.contains("not a form"), "{reason}"),
        other => panic!("expected refused, got {other:?}"),
    };
    // Re-run as a form: the old id is gone, the new one is the form.
    let old = open_form(&s, &mut r, "f1");
    let new = open_form(&s, &mut r, "f1");
    send_submit(&s, &old, "f1", ok.clone());
    refused(&mut r);
    // Re-run as rows: the form id no longer submits.
    send_widget(&s, "f1", serde_json::json!({"rows": {"table": "expenses"}}), "click");
    assert!(matches!(next(&mut r), Some(ToShell::Widget { component: Component::TableResults(_), .. })));
    send_submit(&s, &new, "f1", ok);
    refused(&mut r);
    assert!(posts(&rig).is_empty(), "a dropped form wrote");
}

#[test]
fn a_session_holds_at_most_24_forms() {
    let rig = rig_at("fcap", mapped(), fake_table(&expenses(""), vec![]).0, vec![answer("never")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    for i in 0..24 {
        open_form(&s, &mut r, &format!("f{i}"));
    }
    // A re-run of one held is not a 25th.
    open_form(&s, &mut r, "f0");
    send_widget(&s, "f24", serde_json::json!({"form": {"table": "expenses"}}), "click");
    match next(&mut r) {
        Some(ToShell::Refused { reason, widget }) => {
            assert_eq!(widget.as_deref(), Some("f24"));
            assert!(reason.contains("24 forms"), "{reason}");
        }
        other => panic!("the 25th form was not refused: {other:?}"),
    }
}

// --- genui I5i: the PoC, offline: form, table and chart over one table, refreshed by a write ---

/// state/fixtures/genui-workspace-poc/<name>: the expenses table the PoC runs over.
fn poc(name: &str) -> String {
    let p = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../state/fixtures/genui-workspace-poc").join(name);
    std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display()))
}

/// The next widget answer for `token`, as wire JSON.
fn widget_answer(r: &mut BufReader<UnixStream>, token: &str) -> serde_json::Value {
    loop {
        let m = serde_json::to_value(next(r).expect("an answer")).unwrap();
        if m["t"] == "session" {
            continue;
        }
        assert_eq!((&m["t"], &m["widget"]), (&serde_json::json!("widget"), &serde_json::json!(token)), "{m}");
        return m["component"].clone();
    }
}

fn poc_chart() -> serde_json::Value {
    serde_json::json!({"chart": {"query": {"table": "expenses"}, "chart": "bar", "x": "kind", "y": "amount", "op": "sum"}})
}

#[test]
fn genui_workspace_poc() {
    let seed: Vec<serde_json::Value> = serde_json::from_str(&poc("expenses.rows.json")).unwrap();
    assert_eq!(seed.len(), 3, "the PoC seeds three rows");
    let ((url, seen), held) = fake_table(&poc("expenses.schema.json"), seed);
    let rig = rig_at("poc", mapped(), (url, seen), vec![answer("never")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());

    // Three widgets, as the person adds them with "+ widget".
    send_widget(&s, "rows", serde_json::json!({"rows": {"table": "expenses"}}), "click");
    let Some(ToShell::Session { session, .. }) = next(&mut r) else { panic!("no session") };
    assert_eq!(widget_answer(&mut r, "rows")["props"]["rows"].as_array().unwrap().len(), 3);
    send_widget(&s, "chart", poc_chart(), "click");
    assert_eq!(widget_answer(&mut r, "chart")["kind"], "chart");
    let form = open_form(&s, &mut r, "form");

    send_submit(&s, &form, "form", serde_json::json!({"kind": "tools", "amount": 42, "when": "2026-10-13"}));
    let row = match next(&mut r) {
        Some(ToShell::TableChanged { table, row, .. }) if table == "expenses" => row,
        other => panic!("expected table_changed, got {other:?}"),
    };
    assert!(matches!(next(&mut r), Some(ToShell::FormResult { ref widget, row: ref r2, .. }) if widget == "form" && *r2 == row));
    let p = posts(&rig);
    assert_eq!(p.len(), 1, "{p:?}");
    let body: serde_json::Value = serde_json::from_str(&p[0].1).unwrap();
    assert!(body.get("id").is_none(), "KEAP mints the id: {body}");
    let stored = held.lock().unwrap().clone();
    assert_eq!(stored.len(), 4, "the fake stored the row");
    assert!(stored.iter().any(|x| x["id"] == row.as_str() && x["values"]["when"] == 1_791_849_600), "{stored:?}");

    // The pupil re-sends the two readers of the table; they answer what the fake now holds.
    send_widget(&s, "rows", serde_json::json!({"rows": {"table": "expenses"}}), "table_changed");
    let table = widget_answer(&mut r, "rows");
    let got = table["props"]["rows"].as_array().unwrap();
    let ids: Vec<&str> = got.iter().map(|x| x["__id"].as_str().unwrap()).collect();
    let want: Vec<&str> = stored.iter().map(|x| x["id"].as_str().unwrap()).collect();
    assert_eq!(ids, want, "{table}");
    let new = got.iter().find(|x| x["__id"] == row.as_str()).unwrap();
    assert_eq!((&new["cells"]["when"], &new["cells"]["kind"]), (&serde_json::json!("2026-10-13"), &serde_json::json!("tools")), "a day, not an epoch");
    send_widget(&s, "chart", poc_chart(), "table_changed");
    let chart = widget_answer(&mut r, "chart");
    let tools: f64 = stored.iter().filter(|x| x["values"]["kind"] == "tools").map(|x| x["values"]["amount"].as_f64().unwrap()).sum();
    assert!(points(&chart["props"]).contains(&("tools".to_string(), tools)), "the chart sums what the fake holds ({tools}): {chart}");
    assert!(rig.model.lock().unwrap().is_empty(), "the PoC asked the model");

    let tools_used: Vec<(String, String, serde_json::Value)> = events(&rig.ledger, &session).into_iter()
        .filter(|e| e.1.starts_with("agent:iris/tool:")).map(|(t, k, v)| (t, k.trim_start_matches("agent:iris/tool:").to_string(), v)).collect();
    let shape: Vec<(&str, &str)> = tools_used.iter().map(|e| (e.0.as_str(), e.1.as_str())).collect();
    let pair = |t| [("agent_tool_use", t), ("agent_tool_result", t)];
    let mut want = vec![];
    for t in ["widget_rows", "widget_chart", "widget_form"] {
        want.extend(pair(t));
    }
    want.extend([("agent_tool_use", "form_submit"), ("agent_approval_request", "form_submit"),
                 ("agent_approval_decision", "form_submit"), ("agent_tool_result", "form_submit")]);
    want.extend(pair("widget_rows"));
    want.extend(pair("widget_chart"));
    assert_eq!(shape, want, "{tools_used:?}");
    for e in &tools_used[7..10] {
        assert_eq!(e.2["peer"]["pid"], std::process::id(), "{e:?}");
    }
    for e in [&tools_used[10], &tools_used[12]] {
        assert_eq!(e.2["trigger"], "table_changed", "{e:?}");
    }
}

// --- genui I6: a render the person may pin; a sourced chart draws KEAP's numbers, not the model's ---

/// Every render of a turn as wire JSON: {component, pin?}.
fn rendered(got: &[ToShell]) -> Vec<serde_json::Value> {
    got.iter().filter(|m| matches!(m, ToShell::Render { .. })).map(|m| serde_json::to_value(m).unwrap()).collect()
}

#[test]
fn a_query_rows_render_carries_its_args_as_a_rows_pin() {
    let args = [r#"{"table": "sheet", "where": [{"column": "status", "op": "eq", "value": "open"}], "order_by": {"column": "amount", "dir": "desc"}, "columns": ["status", "amount"], "limit": 5}"#,
                r#"{"table": "sheet", "group_by": "status"}"#];
    let rig = rig_at("pinrows", mapped(), fake_table(SHEET, statuses()).0, vec![query(args[0]), query(args[1]), answer("x")], Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "open ones, and per status");
    let pins: Vec<serde_json::Value> = rendered(&got).iter().map(|m| m["pin"].clone()).collect();
    let want: Vec<serde_json::Value> = args.iter().map(|a| serde_json::json!({"rows": serde_json::from_str::<serde_json::Value>(a).unwrap()})).collect();
    assert_eq!(pins, want, "the pin is exactly what a widget re-run sends, group_by included");
}

fn sourced(chart: &str, source: serde_json::Value) -> String {
    call("show", &serde_json::json!({"component": {"kind": "chart", "props": {"title": "By status", "chart": chart, "x": "category",
        "series": [{"name": "model", "points": [["open", 999]]}]}}, "source": source}).to_string())
}

#[test]
fn a_sourced_chart_draws_keaps_aggregate_and_carries_a_chart_pin() {
    let source = serde_json::json!({"query": {"table": "sheet"}, "x": "status", "op": "count"});
    let rig = rig_at("pinchart", mapped(), fake_table(SHEET, statuses()).0,
        vec![sourced("pie", source.clone()), answer("Drawn."), call("propose_row_edit", r#"{"table": "sheet", "row_id": "a", "values": {"amount": 4}}"#), answer("x")],
        Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "chart per status");
    let drawn = rendered(&got);
    assert_eq!(drawn.len(), 1, "{got:?}");
    let props = &drawn[0]["component"]["props"];
    assert_eq!(points(props), pts(&[("open", 3.0), ("done", 1.0)]), "the model's 999 is replaced by KEAP's counts: {props}");
    assert_eq!((&props["chart"], &props["title"]), (&serde_json::json!("pie"), &serde_json::json!("By status")), "{props}");
    let mut want = source.clone();
    want["chart"] = serde_json::json!("pie");
    assert_eq!(drawn[0]["pin"], serde_json::json!({"chart": want}), "the pin is the source with the component's chart kind");
    let told = tool_result(&rig, 1);
    assert!(!told.to_string().contains("999"), "{told}");
    // The model is told, in the prompt and the tool, to name the source of a chart of table rows.
    assert!(system_prompt(&rig).contains("pass show's `source`"), "{}", system_prompt(&rig));
    // The shape map must not send a count chart the unsourced way, or it cannot be pinned.
    assert!(system_prompt(&rig).contains("count per value -> chart with show `source` (op count)"), "{}", system_prompt(&rig));
    let offered = &serve::show_schema()["properties"]["source"];
    assert_eq!(offered["required"], serde_json::json!(["query", "x", "op"]), "{offered}");
    assert_eq!(offered["properties"]["op"]["enum"], serde_json::json!(["count", "sum", "avg"]), "{offered}");
    // Recorded like a widget run, before and after; the model was asked once for the show.
    let session = session_of(&got);
    let ev: Vec<_> = events(&rig.ledger, &session).into_iter().filter(|e| e.1 == "agent:iris/tool:show_source").collect();
    let kinds: Vec<&str> = ev.iter().map(|e| e.0.as_str()).collect();
    assert_eq!(kinds, ["agent_tool_use", "agent_tool_result"], "{ev:?}");
    assert_eq!((&ev[0].2["table"], &ev[0].2["op"]), (&serde_json::json!("sheet"), &serde_json::json!("count")), "{:?}", ev[0]);
    // The aggregate read rows the model never saw: none of them may be proposed.
    turn(&s, &mut r, Some(session), "set a to 4");
    let e = tool_result(&rig, 3);
    assert!(e["error"].as_str().is_some_and(|e| e.contains("was not shown to the person")), "{e}");
    assert!(posts(&rig).is_empty());
}

#[test]
fn a_chart_with_a_bad_source_is_refused_and_one_without_has_no_pin() {
    let bad = [
        (serde_json::json!({"query": {"table": "sheet"}, "x": "ghost", "op": "count"}), "pie", "no column `ghost`"),
        (serde_json::json!({"query": {"table": "sheet"}, "x": "status", "op": "sum"}), "pie", "sum needs `y`"),
        (serde_json::json!({"query": {"table": "sheet"}, "x": "status", "op": "count", "chart": "bar"}), "pie", "chart"),
        (serde_json::json!({"query": {"table": "sheet"}, "x": "status", "op": "count"}), "area", "bar, line or pie"),
    ];
    let mut model: Vec<String> = bad.iter().map(|(s, c, _)| sourced(c, s.clone())).collect();
    model.push(show(serde_json::json!({"kind": "chart", "props": {"chart": "bar", "x": "category", "series": [{"name": "m", "points": [["a", 1]]}]}})));
    model.push(answer("done"));
    let rig = rig_at("pinbad", mapped(), fake_table(SHEET, statuses()).0, model, Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "chart it");
    for (i, (_, _, want)) in bad.iter().enumerate() {
        let e = tool_result(&rig, i + 1);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(want)), "source #{i} must be refused naming {want}: {e}");
    }
    let drawn = rendered(&got);
    assert_eq!(drawn.len(), 1, "only the unsourced chart is drawn: {got:?}");
    assert!(drawn[0].get("pin").is_none(), "a chart without a source is a picture, not a pin: {}", drawn[0]);
    assert_eq!(points(&drawn[0]["component"]["props"]), pts(&[("a", 1.0)]), "without a source the model's numbers are drawn");
}

/// A source that is not an object is refused, and the turn goes on: it used to panic serve's
/// connection thread, so the show had no result and the session never ended.
#[test]
fn a_source_that_is_not_an_object_is_refused_and_the_turn_ends() {
    // A string (a double-encoded object too), a number, an array, a bool.
    let bad = [serde_json::json!(r#"{"query": {"table": "sheet"}, "x": "status", "op": "count"}"#), serde_json::json!(7),
               serde_json::json!(["sheet"]), serde_json::json!(true)];
    let mut model: Vec<String> = bad.iter().map(|s| sourced("pie", s.clone())).collect();
    model.push(answer("done"));
    let rig = rig_at("pinnotobj", mapped(), fake_table(SHEET, statuses()).0, model, Some(local()));
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "chart it");
    for i in 0..bad.len() {
        let e = tool_result(&rig, i + 1);
        assert!(e["error"].as_str().is_some_and(|e| e.contains("is an object")), "source #{i} must be refused: {e}");
    }
    assert!(rendered(&got).is_empty(), "{got:?}");
    assert!(got.iter().any(|m| matches!(m, ToShell::Text { text, .. } if text == "done")), "the turn ends: {got:?}");
}

/// A pin and a widget refuse one spec alike: serve::widget runs the pin's check_spec first (I6).
#[test]
fn a_widget_spec_a_pin_would_fail_is_refused_with_the_pin_reason() {
    let rig = sheet_rig("wspec", statuses());
    for (spec, want) in [(serde_json::json!({"rows": {"q": "x"}}), "names no table"),
                         (serde_json::json!({"chart": {"query": {"table": ""}, "chart": "pie", "x": "status", "op": "count"}}), "names no table")] {
        let (_, w) = run_widget(&rig, "w1", spec.clone());
        assert_eq!((&w["t"], &w["widget"]), (&serde_json::json!("refused"), &serde_json::json!("w1")), "{spec}: {w}");
        assert!(w["reason"].as_str().is_some_and(|r| r.contains(want)), "{spec}: {w}");
    }
}

// --- iris-genui-forms step 1: Iris asks at a fork; the answer comes back typed, as data ---

fn ask(multi: bool) -> serde_json::Value {
    let suggested = if multi { serde_json::json!(["todos", "expenses"]) } else { serde_json::json!(["todos"]) };
    serde_json::json!({"kind": "choice", "props": {"question": "Which table should I chart?", "multi": multi, "suggested": suggested,
        "options": [{"label": "todos", "note": "the open work"}, {"label": "expenses"}, {"label": "roadmap"}]}})
}

/// A turn whose model shows `multi`'s choice, then says a line; returns (stream, reader, session, choice id).
fn asked_choice(rig: &Rig) -> (UnixStream, BufReader<UnixStream>, String, String) {
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "chart something");
    let id = got.iter().find_map(|m| match m {
        ToShell::Render { component: Component::Choice(c), pin: None, .. } => c.id.clone(),
        _ => None,
    }).unwrap_or_else(|| panic!("no choice was rendered with an id: {got:?}"));
    assert!(nos_contract::wire::is_uuid(&id), "{id}");
    assert!(matches!(raw(&mut r), Some(ToShell::Activity { phase: Phase::Idle, .. })), "the asking turn ends idle");
    (s, r, session_of(&got), id)
}

fn choose(s: &UnixStream, session: &str, choice: &str, picked: &[&str]) {
    let m = ToThalamus::ChoiceReply { session: session.into(), choice: choice.into(), picked: picked.iter().map(|p| p.to_string()).collect() };
    let mut w = s;
    w.write_all(encode(&m).as_bytes()).unwrap();
}

/// The model's side: show the choice, say a line, then (after the reply) answer.
fn choice_turns(multi: bool) -> Vec<String> {
    vec![show(ask(multi)), answer("Which one?"), answer("Charting it.")]
}

#[test]
fn a_choice_reply_reaches_the_model_as_data_and_iris_goes_on() {
    let rig = rig("choice", mapped(), ROWS, choice_turns(false));
    let (s, mut r, session, id) = asked_choice(&rig);
    assert_eq!(tool_result(&rig, 1)["choice"], serde_json::json!(id), "the model hears the id serve minted");
    choose(&s, &session, &id, &["expenses"]);
    let got = until_text(&mut r);
    assert_eq!(phases(&got), ["thinking", "text"], "the model's next turn runs: {got:?}");
    assert!(matches!(got.last(), Some(ToShell::Text { text, .. }) if text == "Charting it."), "{got:?}");
    assert!(matches!(raw(&mut r), Some(ToShell::Activity { phase: Phase::Idle, .. })));
    assert_eq!(heard(&rig, 2), format!(r#"[thalamus] choice {id}: picked "expenses""#), "a changed pick is not the suggestion");
}

/// The one line the model hears of a reply, exactly; it never carries a word of agreement.
fn heard(rig: &Rig, n: usize) -> String {
    let body: serde_json::Value = serde_json::from_str(&rig.model.lock().unwrap()[n].1).unwrap();
    let said: Vec<String> = body["messages"].as_array().unwrap().iter()
        .filter_map(|m| m["content"].as_str().filter(|c| m["role"] == "user" && c.starts_with("[thalamus] choice ")).map(String::from))
        .collect();
    assert_eq!(said.len(), 1, "one reply line: {said:?}");
    let low = said[0].to_lowercase();
    for word in ["agree", "approv", "accept", "confirm", "consent", "yes", "untouched"] {
        assert!(!low.contains(word), "{word:?} in what the model heard: {}", said[0]);
    }
    said[0].clone()
}

/// A pick equal to the suggestion is not agreement, and not "untouched" either: the pupil
/// preselects it, the terminal does not, and serve cannot tell which one answered.
#[test]
fn a_pick_equal_to_the_suggestion_is_said_as_such_and_no_more() {
    const SAME: &str = "; that is your suggestion, which the pupil preselects, so it may have been left as it was";
    for (name, multi, picked, want) in [
        ("untouched", false, vec!["todos"], format!(r#"picked "todos"{SAME}"#)),
        ("untouched2", true, vec!["expenses", "todos"], format!(r#"picked "expenses", "todos"{SAME}"#)),
    ] {
        let rig = rig(name, mapped(), ROWS, choice_turns(multi));
        let (s, mut r, session, id) = asked_choice(&rig);
        choose(&s, &session, &id, &picked);
        until_text(&mut r);
        assert_eq!(heard(&rig, 2), format!("[thalamus] choice {id}: {want}"), "{name}");
    }
}

#[test]
fn a_choice_reply_the_stored_choice_does_not_allow_is_refused_and_recorded() {
    let unknown = "9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f";
    for (name, multi, choice, picked, want) in [
        ("cunknown", false, Some(unknown), vec!["todos"], "no open choice"),
        ("cnotoffered", false, None, vec!["promotions"], r#""promotions" is not an option of this choice"#),
        ("ctwo", false, None, vec!["todos", "expenses"], "this choice takes one pick, not 2"),
        ("cnone", true, None, vec![], "pick at least one option"),
        ("ctwice", true, None, vec!["todos", "todos"], r#""todos" is picked twice"#),
    ] {
        let rig = rig(name, mapped(), ROWS, choice_turns(multi));
        let (s, mut r, session, id) = asked_choice(&rig);
        choose(&s, &session, choice.unwrap_or(&id), &picked);
        match next(&mut r) {
            Some(ToShell::Refused { reason, widget: None }) => assert!(reason.contains(want), "{name}: {reason}"),
            other => panic!("{name}: the reply was not refused: {other:?}"),
        }
        assert_eq!(rig.model.lock().unwrap().len(), 2, "{name}: a refused reply asked the model");
        let ev = events(&rig.ledger, &session);
        let last = ev.last().unwrap();
        assert_eq!((last.0.as_str(), last.1.as_str()), ("agent_tool_result", "agent:iris/tool:choice_reply"), "{name}: {ev:?}");
        assert!(last.2["error"].as_str().is_some_and(|e| e.contains(want)), "{name}: {last:?}");
    }
}

#[test]
fn a_choice_is_answered_once() {
    let rig = rig("conce", mapped(), ROWS, choice_turns(false));
    let (s, mut r, session, id) = asked_choice(&rig);
    choose(&s, &session, &id, &["roadmap"]);
    until_text(&mut r);
    choose(&s, &session, &id, &["todos"]);
    assert!(matches!(next(&mut r), Some(ToShell::Refused { reason, .. }) if reason.contains("no open choice")));
    assert_eq!(rig.model.lock().unwrap().len(), 3, "a closed choice asked the model again");
}

#[test]
fn a_choice_reply_for_another_session_is_refused() {
    let rig = rig("csession", mapped(), ROWS, choice_turns(false));
    let (s, mut r, _, id) = asked_choice(&rig);
    choose(&s, "9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f", &id, &["todos"]);
    assert!(matches!(next(&mut r), Some(ToShell::Refused { reason, .. }) if reason.contains("not this connection's open session")));
}

/// Ledger-first, and nothing but a label: no approval, no form, no widget, no write, no KEAP call.
#[test]
fn a_choice_reply_is_recorded_first_and_mints_nothing() {
    let rig = rig("cnothing", mapped(), ROWS, choice_turns(false));
    let (s, mut r, session, id) = asked_choice(&rig);
    choose(&s, &session, &id, &["expenses"]);
    let got = until_text(&mut r);
    assert!(!got.iter().any(|m| matches!(m, ToShell::ApprovalRequest { .. } | ToShell::Widget { .. } | ToShell::FormResult { .. }
        | ToShell::TableChanged { .. } | ToShell::Render { .. })), "{got:?}");
    assert!(rig.keap.lock().unwrap().is_empty(), "a choice reached KEAP");
    let ev = events(&rig.ledger, &session);
    assert!(!ev.iter().any(|(t, _, _)| t.contains("approval")), "{ev:?}");
    let at = |t: &str, task: &str| ev.iter().position(|e| e.0 == t && e.1 == task).unwrap_or_else(|| panic!("no {t} {task}: {ev:?}"));
    let (used, result) = (at("agent_tool_use", "agent:iris/tool:choice_reply"), at("agent_tool_result", "agent:iris/tool:choice_reply"));
    let said = ev.iter().rposition(|e| e.0 == "agent_message").unwrap();
    assert!(used < result && result < said, "the reply is in the ledger before Iris answers: {ev:?}");
    assert_eq!(ev[result].2, serde_json::json!({"choice": id, "picked": ["expenses"], "untouched": false}));
    // The show's result names the id it minted, before the render went out.
    assert!(ev.iter().any(|e| e.1 == "agent:iris/tool:show" && e.0 == "agent_tool_result" && e.2["choice"] == serde_json::json!(id)), "{ev:?}");
}

#[test]
fn a_choice_reply_while_an_approval_waits_is_refused() {
    let model = vec![query(r#"{"table": "todos", "q": "alpha"}"#), show(ask(false)), call("propose_row_edit", EDIT), answer("Proposed.")];
    let rig = rig_n("cwaits", mapped(), shown_then(&[ROWS]), model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "close alpha");
    let id = got.iter().find_map(|m| match m { ToShell::Render { component: Component::Choice(c), .. } => c.id.clone(), _ => None }).unwrap();
    assert!(got.iter().any(|m| matches!(m, ToShell::ApprovalRequest { .. })), "{got:?}");
    choose(&s, &session_of(&got), &id, &["todos"]);
    assert!(matches!(next(&mut r), Some(ToShell::Refused { reason, .. }) if reason.contains("an approval is waiting")));
    assert_eq!(rig.model.lock().unwrap().len(), 4, "the reply ran the model while an approval waits");
}

#[test]
fn the_model_sends_no_choice_id_and_holds_four_open_choices() {
    let mut with_id = ask(false);
    with_id["props"]["id"] = serde_json::json!("3c9e1d2f-4a5b-4c6d-8e7f-9a0b1c2d3e4f");
    let mut model = vec![show(with_id)];
    model.extend((0..5).map(|_| show(ask(false))));
    model.push(answer("asked"));
    let rig = rig("cfour", mapped(), ROWS, model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "ask me");
    assert!(tool_result(&rig, 1)["error"].as_str().is_some_and(|e| e.contains("`id` is minted by the thalamus")), "{}", tool_result(&rig, 1));
    let ids: std::collections::HashSet<String> = got.iter().filter_map(|m| match m {
        ToShell::Render { component: Component::Choice(c), .. } => c.id.clone(), _ => None }).collect();
    assert_eq!(ids.len(), 4, "four choices, each its own id: {got:?}");
    let fifth = tool_result(&rig, 6);
    assert!(fifth["error"].as_str().is_some_and(|e| e.contains("this session holds 4 open choices")), "{fifth}");
}

#[test]
fn the_prompt_asks_only_at_a_fork_and_never_for_a_write() {
    let rig = rig("cprompt", mapped(), ROWS, vec![answer("hi")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    turn(&s, &mut r, None, "hello");
    let p = system_prompt(&rig);
    for line in ["show choice only at a fork that changes what you do next", "2-6 options", "mark your pick as suggested",
                 "never for yes or no on a write: that is propose_row_edit's card"] {
        assert!(p.contains(line), "prompt missing {line:?}:\n{p}");
    }
    let shape = serve::SHOW_SHAPE.iter().find(|(k, _)| *k == "choice").map(|(_, s)| *s).unwrap_or("");
    assert!(shape.contains("options[{label, note?}]") && shape.contains("suggested[]"), "{shape}");
}

// --- live 2026-10-13: asked for red status, Iris had no tool and counted roadmap rows instead ---

const RED: &str = r#"import json
print(json.dumps({"sources_read": ["x"], "red_count": 1, "reds": ["pulse job failed"], "hold_count": 0, "holds": []}))
"#;

#[test]
fn iris_reads_red_status_through_the_same_reader() {
    let rig = rig_n("ired", admin(), vec![], vec![call("red_status", "{}"), answer("One red: a pulse job.")]);
    reader(&rig, "red-status.py", RED);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "kolik máme red statusů?");
    assert!(got.iter().any(|m| matches!(m, ToShell::Render { component: Component::RedStatus(x), .. } if x.red_count == 1)), "{got:?}");
    let t = tool_result(&rig, 1);
    assert_eq!((&t["red_count"], &t["reds"][0]), (&serde_json::json!(1), &serde_json::json!("pulse job failed")), "{t}");
    assert!(system_prompt(&rig).contains("call red_status"), "{}", system_prompt(&rig));
}

#[test]
fn an_unreadable_red_status_is_unknown_never_zero() {
    for (name, py) in [("exit", "import sys; sys.exit(3)"), ("garbage", "print('not json')")] {
        let rig = rig_n(name, admin(), vec![], vec![call("red_status", "{}"), answer("x")]);
        reader(&rig, "red-status.py", py);
        let s = connect(&rig.sock);
        let mut r = BufReader::new(s.try_clone().unwrap());
        let got = turn(&s, &mut r, None, "is anything red?");
        assert!(!got.iter().any(|m| matches!(m, ToShell::Render { component: Component::RedStatus(_), .. })), "{name}: drew a red status it could not read");
        let e = tool_result(&rig, 1);
        assert!(e["error"].as_str().is_some_and(|e| e.contains("UNKNOWN")), "{name}: {e}");
    }
}

#[test]
fn red_status_for_iris_is_tier_one_only() {
    let rig = rig_n("ired-tier", mapped(), vec![], vec![call("red_status", "{}"), answer("x")]);
    reader(&rig, "red-status.py", RED);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "red?");
    assert!(!got.iter().any(|m| matches!(m, ToShell::Render { component: Component::RedStatus(_), .. })), "{got:?}");
    assert!(tool_result(&rig, 1)["error"].as_str().is_some_and(|e| e.contains("not yours to see")));
}

// --- iris-genui-change-markers: a dry run's delta, offered in every place the model reads a shape ---

#[test]
fn show_offers_a_delta_on_tree_list_and_record() {
    let schema = serve::show_schema();
    let props = |kind: &str| schema["properties"]["component"]["oneOf"].as_array().unwrap().iter()
        .find(|b| b["properties"]["kind"]["const"] == kind).unwrap()["properties"]["props"].clone();
    let words = serde_json::json!(["added", "removed", "changed"]);
    assert_eq!(props("list")["properties"]["items"]["items"]["properties"]["delta"]["enum"], words);
    let field = props("record")["properties"]["fields"]["items"]["properties"].clone();
    assert_eq!(field["delta"]["enum"], words, "{field}");
    assert!(field["was"]["description"].as_str().is_some_and(|d| d.contains("changed")), "{field}");
    let tree = schema["properties"]["component"]["oneOf"].as_array().unwrap().iter()
        .find(|b| b["properties"]["kind"]["const"] == "tree").unwrap()["description"].as_str().unwrap_or("").to_string();
    assert!(tree.contains("delta?") && tree.contains("an added or removed parent"), "the tree branch says delta and what a child inherits: {tree}");
    for (kind, want) in [("list", "delta?"), ("record", "was?"), ("tree", "delta?")] {
        let shape = serve::SHOW_SHAPE.iter().find(|(k, _)| *k == kind).unwrap().1;
        assert!(shape.contains(want) && shape.contains("added|removed|changed"), "SHOW_SHAPE {kind} lacks {want}: {shape}");
    }
    let rig = rig("delta", mapped(), ROWS, vec![answer("hi")]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    turn(&s, &mut r, None, "hello");
    let p = system_prompt(&rig);
    assert!(p.contains("what an action would change -> mark delta"), "{p}");
}

// --- iris-genui-sequence: who sends what to whom, offered and checked like every show kind ---

#[test]
fn show_draws_a_sequence_and_refuses_an_unknown_participant_or_a_crowd() {
    let path = serde_json::json!({"kind": "sequence", "props": {"participants": ["pupil", "thalamus", "KEAP"], "steps": [
        {"phase": "propose"}, {"from": "pupil", "to": "thalamus", "text": "close the row"},
        {"from": "KEAP", "to": "thalamus", "text": "1 row", "dashed": true}, {"note": "the person decides", "over": ["pupil"]}]}});
    let ghost = serde_json::json!({"kind": "sequence", "props": {"participants": ["a", "b"], "steps": [{"from": "a", "to": "ghost", "text": "m"}]}});
    let crowd: Vec<String> = (0..9).map(|i| format!("p{i}")).collect();
    let crowd = serde_json::json!({"kind": "sequence", "props": {"participants": crowd, "steps": [{"from": "p0", "to": "p1", "text": "m"}]}});
    let bad = [(ghost, r#"names no participant "ghost""#), (crowd, "sequence participants: 9, 2 to 8")];
    let mut model = vec![show(path)];
    model.extend(bad.iter().map(|(c, _)| show(c.clone())));
    model.push(answer("done"));
    let rig = rig("sequence", mapped(), ROWS, model);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let got = turn(&s, &mut r, None, "show how an approval travels");
    assert_eq!(drawn_kinds(&got), ["sequence"], "only the valid sequence is drawn: {got:?}");
    for (i, (_, want)) in bad.iter().enumerate() {
        let e = tool_result(&rig, i + 2);
        assert!(e["error"].as_str().is_some_and(|e| e.contains(want) && e.contains("participants[]")), "show #{} must be refused naming {want}: {e}", i + 2);
    }
    let p = system_prompt(&rig);
    assert!(p.contains("who sends what to whom -> sequence"), "{p}");
}

/// The model is offered participants, the three step shapes and their caps in both places it reads a shape.
#[test]
fn show_offers_a_sequence() {
    let schema = serve::show_schema();
    let branch = schema["properties"]["component"]["oneOf"].as_array().unwrap().iter()
        .find(|b| b["properties"]["kind"]["const"] == "sequence").unwrap_or_else(|| panic!("no sequence branch")).clone();
    let props = &branch["properties"]["props"]["properties"];
    assert_eq!((&props["participants"]["minItems"], &props["participants"]["maxItems"]), (&serde_json::json!(2), &serde_json::json!(8)), "{props}");
    assert_eq!(props["participants"]["items"]["maxLength"], 40, "{props}");
    assert_eq!(props["steps"]["maxItems"], 40, "{props}");
    let shapes: Vec<Vec<String>> = props["steps"]["items"]["oneOf"].as_array().unwrap_or_else(|| panic!("steps offer no shapes: {props}")).iter()
        .map(|b| b["required"].as_array().unwrap().iter().map(|k| k.as_str().unwrap().to_string()).collect()).collect();
    assert_eq!(shapes, [vec!["from", "to", "text"], vec!["note", "over"], vec!["phase"]], "{props}");
    let shape = serve::SHOW_SHAPE.iter().find(|(k, _)| *k == "sequence").unwrap().1;
    for want in ["participants[]", "{from, to, text, dashed?}", "{note, over[]}", "{phase}"] {
        assert!(shape.contains(want), "SHOW_SHAPE sequence lacks {want}: {shape}");
    }
}

// --- row thalamus-pupil-peer-exe: with a decider list set, only a listed executable decides ---

/// A path that names no file until `admit` links it to this test binary (the peer).
fn decider_link(name: &str) -> PathBuf {
    dir(&format!("{name}-exe")).join("nos-pupil")
}

fn admit(link: &std::path::Path) {
    std::os::unix::fs::symlink(std::env::current_exe().unwrap(), link).unwrap();
}

/// The refusals a session's ledger holds for `tool`, each naming the peer.
fn refusals(rig: &Rig, session: &str, tool: &str) -> Vec<serde_json::Value> {
    let me = std::env::current_exe().unwrap();
    let got: Vec<_> = events(&rig.ledger, session).into_iter()
        .filter(|e| e.0 == "agent_tool_result" && e.1 == format!("agent:iris/tool:{tool}") && e.2.get("refused").is_some())
        .map(|e| e.2).collect();
    for e in &got {
        assert_eq!(e["peer"]["pid"], std::process::id(), "{e}");
        assert!(e["peer"]["exe"].as_str().is_some_and(|x| same_file(x, &me)), "the refusal names no peer exe: {e}");
    }
    got
}

#[test]
fn a_decider_refusal_needs_a_listed_resolvable_exe_and_none_when_off() {
    let me = std::env::current_exe().unwrap();
    let link = decider_link("pure");
    let mine = me.to_str().unwrap();
    assert_eq!(serve::decider_refusal(&[], None), None, "an empty list is off: recorded only");
    assert_eq!(serve::decider_refusal(&[], Some("/nowhere")), None);
    assert!(serve::decider_refusal(&[me.clone()], None).is_some(), "an undeterminable exe decides nothing");
    assert!(serve::decider_refusal(&[me.clone()], Some("/nowhere/at/all")).is_some(), "an unresolvable exe decides nothing");
    assert!(serve::decider_refusal(&[link.clone()], Some(mine)).is_some(), "a listed path that names no file admits nobody");
    assert!(serve::decider_refusal(&["relative/exe".into()], Some(mine)).is_some(), "only an absolute entry counts");
    admit(&link);
    assert_eq!(serve::decider_refusal(&[link], Some(mine)), None, "a listed symlink is resolved");
    assert_eq!(serve::decider_refusal(&[me.clone()], Some(mine)), None);
}

#[test]
fn an_unlisted_decider_is_refused_and_the_approval_still_waits() {
    let link = decider_link("adecide");
    let rig = rig_deciders("adecide", mapped(), fake(shown_then(&[ROWS, ROWS, POSTED])), edit_turn(), Some(local()), vec![link.clone()]);
    let (s, mut r, session, approval, _) = propose(&rig);
    decide(&s, &approval, Decision::Approve);
    match next(&mut r) {
        Some(ToShell::Refused { reason, .. }) => assert!(reason.contains("decider"), "{reason}"),
        other => panic!("an unlisted decider must be refused, got {other:?}"),
    }
    assert!(posts(&rig).is_empty(), "a refused decider wrote");
    // Still pending: the same card, from a listed exe, takes the write path.
    admit(&link);
    decide(&s, &approval, Decision::Approve);
    assert!(matches!(next(&mut r), Some(ToShell::TableChanged { ref row, .. }) if row == "r1"));
    assert!(matches!(next(&mut r), Some(ToShell::Text { ref text, .. }) if text.contains("row r1 written")));
    assert_eq!(posts(&rig).len(), 1);
    drop((s, r));
    std::thread::sleep(std::time::Duration::from_millis(300));
    let refused = refusals(&rig, &session, "propose_row_edit");
    assert_eq!(refused.len(), 1, "{refused:?}");
    assert_eq!(refused[0]["for"], serde_json::json!(approval));
    let decisions = events(&rig.ledger, &session).into_iter().filter(|e| e.0 == "agent_approval_decision").count();
    assert_eq!(decisions, 1, "the refused decision is no decision row");
}

#[test]
fn an_unlisted_decider_cannot_submit_a_form_or_answer_a_choice() {
    let link = decider_link("fdecide");
    let ((url, seen), held) = fake_table(&expenses(""), vec![]);
    let rig = rig_deciders("fdecide", mapped(), (url, seen), vec![answer("never")], Some(local()), vec![link.clone()]);
    let s = connect(&rig.sock);
    let mut r = BufReader::new(s.try_clone().unwrap());
    let form = open_form(&s, &mut r, "f1");
    let values = serde_json::json!({"kind": "tools", "amount": 42});
    send_submit(&s, &form, "f1", values.clone());
    match next(&mut r) {
        Some(ToShell::Refused { reason, widget }) => assert!(reason.contains("decider") && widget.as_deref() == Some("f1"), "{reason}"),
        other => panic!("an unlisted decider's submit must be refused, got {other:?}"),
    }
    assert!(posts(&rig).is_empty() && held.lock().unwrap().is_empty(), "a refused submit wrote");
    // The form stays open: a listed exe submits it.
    admit(&link);
    send_submit(&s, &form, "f1", values);
    assert!(matches!(next(&mut r), Some(ToShell::TableChanged { .. })));
    assert!(matches!(next(&mut r), Some(ToShell::FormResult { .. })));
    drop((s, r));
    std::thread::sleep(std::time::Duration::from_millis(300));
    let session: String = rusqlite::Connection::open(&rig.ledger).unwrap()
        .query_row("SELECT uuid FROM sessions", [], |x| x.get(0)).unwrap();
    let refused = refusals(&rig, &session, "form_submit");
    assert_eq!(refused.len(), 1, "{refused:?}");
    assert_eq!(refused[0]["for"], serde_json::json!(form));

    let link = decider_link("cdecide");
    let rig = rig_deciders("cdecide", mapped(), fake(vec![ROWS.into()]), choice_turns(false), Some(local()), vec![link.clone()]);
    let (s, mut r, session, id) = asked_choice(&rig);
    choose(&s, &session, &id, &["expenses"]);
    match next(&mut r) {
        Some(ToShell::Refused { reason, .. }) => assert!(reason.contains("decider"), "{reason}"),
        other => panic!("an unlisted decider's choice must be refused, got {other:?}"),
    }
    assert_eq!(rig.model.lock().unwrap().len(), 2, "a refused choice reached the model");
    admit(&link);
    choose(&s, &session, &id, &["expenses"]);
    assert!(matches!(until_text(&mut r).last(), Some(ToShell::Text { text, .. }) if text == "Charting it."), "the choice stayed open");
    drop((s, r));
    std::thread::sleep(std::time::Duration::from_millis(300));
    assert_eq!(refusals(&rig, &session, "choice_reply").len(), 1);
}

#[test]
fn a_decider_path_is_taken_as_the_kernel_reported_it() {
    // The exe string was read earlier; a symlink swapped into it since must not make it a listed file.
    let d = std::fs::canonicalize(dir("swap")).unwrap();
    std::fs::create_dir_all(d.join("listed")).unwrap();
    std::fs::write(d.join("listed/nos-pupil"), "").unwrap();
    std::os::unix::fs::symlink(d.join("listed"), d.join("own")).unwrap();
    let stale = d.join("own/nos-pupil");
    assert!(serve::decider_refusal(&[d.join("listed/nos-pupil")], stale.to_str()).is_some(), "a stale path resolved onto a listed file");
    assert_eq!(serve::decider_refusal(&[d.join("own/nos-pupil")], d.join("listed/nos-pupil").to_str()), None, "a listed symlink names its target");
}

/// macOS: LOCAL_PEERPID names the process that last used the peer socket, so the sender is
/// checked per decision. Linux SO_PEERCRED names only the connector (serve fails closed there).
#[cfg(target_os = "macos")]
#[test]
fn a_decision_sent_by_an_unlisted_process_on_a_listed_connection_is_refused() {
    let link = decider_link("sender");
    admit(&link);
    let rig = rig_deciders("sender", mapped(), fake(shown_then(&[ROWS, ROWS, POSTED])), edit_turn(), Some(local()), vec![link]);
    let (s, mut r, _session, approval, _) = propose(&rig);
    // The listed test binary connected; an unlisted /bin/sh holding the same socket decides.
    let line = encode(&ToThalamus::ApprovalDecision { approval: approval.clone(), decision: Decision::Approve, note: None });
    let st = std::process::Command::new("/bin/sh").args(["-c", "printf '%s' \"$L\"; sleep 1"]).env("L", &line)
        .stdout(std::process::Stdio::from(std::os::fd::OwnedFd::from(s.try_clone().unwrap()))).status().unwrap();
    assert!(st.success());
    match next(&mut r) {
        Some(ToShell::Refused { reason, .. }) => assert!(reason.contains("decider"), "{reason}"),
        other => panic!("an unlisted sender must be refused, got {other:?}"),
    }
    assert!(posts(&rig).is_empty(), "an unlisted sender's approval wrote");
    decide(&s, &approval, Decision::Approve);
    assert!(matches!(next(&mut r), Some(ToShell::TableChanged { ref row, .. }) if row == "r1"), "the listed sender is still admitted");
}
