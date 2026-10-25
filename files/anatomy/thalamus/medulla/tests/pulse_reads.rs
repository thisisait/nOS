//! The auth table of the medulla's Pulse reads: BaseApiPresenter::startup()'s outcomes and error
//! words for a GET (tests/anatomy/test_medulla_serves_pulse_reads.py runs PHP beside it).
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

struct Served(Child, u16);

impl Drop for Served {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

const SECRET: &str = "s3cr3t-value-must-not-leak";

fn serve(name: &str) -> (Served, std::path::PathBuf) {
    let dir = std::env::temp_dir().join(format!("medulla-pulse-reads-{}-{name}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let db = dir.join("wing.db");
    let _ = std::fs::remove_file(&db);
    let c = rusqlite::Connection::open(&db).unwrap();
    c.execute_batch(&format!(
        "CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, token TEXT, name TEXT, active INTEGER, scopes TEXT);
         CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, plugin_name TEXT, job_name TEXT, env_json TEXT NOT NULL DEFAULT '{{}}',
           findings_exit_codes TEXT, removed_at TEXT);
         CREATE TABLE pulse_runs (run_id TEXT PRIMARY KEY, job_id TEXT, fired_at TEXT, finished_at TEXT, exit_code INTEGER,
           duration_ms INTEGER, stderr_tail TEXT);
         INSERT INTO pulse_jobs VALUES ('p:a', 'p', 'a', '{{\"WING_API_TOKEN\":\"{SECRET}\",\"PLAIN\":\"x\"}}', NULL, NULL);
         INSERT INTO pulse_runs VALUES ('r1', 'p:a', '2026-10-25T10:00:00+00:00', NULL, NULL, NULL, NULL);"
    ))
    .unwrap();
    let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
    let child = Command::new(env!("CARGO_BIN_EXE_medulla"))
        .args(["wing", "serve", "--db", db.to_str().unwrap(), "--port", &port.to_string()])
        .env("NOS_HALT_FILE", dir.join("halt"))
        .stdout(Stdio::null())
        .spawn()
        .unwrap();
    for _ in 0..100 {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return (Served(child, port), db);
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    panic!("medulla wing serve never listened");
}

fn token(db: &std::path::Path, plain: &str, name: &str, scopes: Option<&str>, active: i64) {
    let c = rusqlite::Connection::open(db).unwrap();
    c.execute("INSERT INTO api_tokens (token, name, active, scopes) VALUES (?, ?, ?, ?)",
        rusqlite::params![sha256_hex(plain), name, active, scopes]).unwrap();
}

fn sha256_hex(s: &str) -> String {
    ring::digest::digest(&ring::digest::SHA256, s.as_bytes()).as_ref().iter().map(|b| format!("{b:02x}")).collect()
}

fn get(port: u16, path: &str, headers: &[(&str, &str)]) -> (u16, String) {
    let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
    let extra: String = headers.iter().map(|(k, v)| format!("{k}: {v}\r\n")).collect();
    write!(s, "GET {path} HTTP/1.1\r\nHost: x\r\n{extra}\r\n").unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).unwrap();
    let code = out[9..12].parse().unwrap();
    (code, out.split_once("\r\n\r\n").unwrap().1.to_owned())
}

#[test]
fn the_auth_table_is_phps() {
    let (s, db) = serve("auth");
    for (plain, name, scopes, active) in [
        ("read", "conductor", Some("wing.read"), 1), ("write", "cortex-executor", Some("wing.write"), 1),
        ("null", "scout", None, 1), ("blank", "blank", Some(" , "), 1), ("halt", "wing-halt", Some("wing.halt"), 1),
        ("gone", "retired", Some("wing.read"), 0), ("bff", "face-bff", Some("wing.operator,wing.write"), 1),
        ("thal", "thalamus", Some("wing.write"), 1),
    ] {
        token(&db, plain, name, scopes, active);
    }
    let missing = "Missing or invalid Authorization header. Use: Authorization: Bearer <token>";
    let t1 = "This estate-wide read is Tier 1 (nos-providers or nos-admins) only";
    let thal = "the thalamus token speaks for a person only to start or stop an agent session and read it";
    let cases: &[(&[(&str, &str)], u16, &str)] = &[
        (&[], 401, missing),
        (&[("Authorization", "bearer read")], 401, missing),
        (&[("Authorization", "Bearer nope")], 401, "Invalid or inactive API token"),
        (&[("Authorization", "Bearer gone")], 401, "Invalid or inactive API token"),
        (&[("Authorization", "Bearer read")], 200, ""),
        (&[("authorization", "Bearer write")], 200, ""),
        (&[("Authorization", "Bearer null")], 200, ""),
        (&[("Authorization", "Bearer blank")], 200, ""),
        (&[("Authorization", "Bearer halt")], 403, "Token scope does not permit GET on the ops plane"),
        (&[("Authorization", "Bearer bff")], 401, "face-bff request without a canonical X-Nos-User-Uid"),
        (&[("Authorization", "Bearer bff"), ("X-Nos-User-Uid", "a--b")], 401, "face-bff request without a canonical X-Nos-User-Uid"),
        (&[("Authorization", "Bearer bff"), ("X-Nos-User-Uid", "alice"), ("X-Nos-User-Groups", "nos-users")], 403, t1),
        (&[("Authorization", "Bearer bff"), ("X-Nos-User-Uid", "alice"), ("X-Nos-User-Groups", "a NOS-PROVIDERS")], 200, ""),
        (&[("Authorization", "Bearer thal")], 401, "thalamus request without a canonical X-Nos-User-Uid"),
        (&[("Authorization", "Bearer thal"), ("X-Nos-User-Uid", "alice"), ("X-Nos-User-Groups", "nos-admins")], 403, thal),
    ];
    for path in ["/api/v1/pulse_jobs", "/api/v1/pulse_runs", "/api/v1/pulse_runs/summary", "/api/v1/pulse_runs/r1"] {
        for (headers, code, error) in cases {
            let (got, body) = get(s.1, path, headers);
            assert_eq!(got, *code, "{path} {headers:?}: {body}");
            assert!(!body.contains(SECRET), "{path} {headers:?} leaked an env value: {body}");
            if !error.is_empty() {
                let v: serde_json::Value = serde_json::from_str(&body).unwrap();
                assert_eq!(v, serde_json::json!({"error": error, "code": code}), "{path} {headers:?}");
            }
        }
    }
    let (_, body) = get(s.1, "/api/v1/pulse_jobs", &[("Authorization", "Bearer read")]);
    let v: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v["jobs"]["p:a"]["env_keys"], serde_json::json!(["WING_API_TOKEN", "PLAIN"]), "{body}");
    assert!(v["jobs"]["p:a"].get("env_json").is_none(), "{body}");
    assert_eq!(get(s.1, "/api/v1/pulse_runs/nope", &[("Authorization", "Bearer read")]).0, 404);
}

#[test]
fn what_stays_phps_is_not_answered_here() {
    let (s, _db) = serve("php");
    // /due hands the daemon env VALUES (PHP's leak, reported, not ported); a window is strtotime()'s.
    for path in ["/api/v1/pulse_jobs/due", "/api/v1/pulse_jobs/p:a", "/api/v1/pulse_runs?since=yesterday", "/api/v1/pulse_runs/r1/finish"] {
        let (code, body) = get(s.1, path, &[("Authorization", "Bearer read")]);
        assert_eq!((code, body.as_str()), (404, "not found\n"), "{path}");
    }
}
