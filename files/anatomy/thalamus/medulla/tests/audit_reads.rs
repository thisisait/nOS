//! GET /api/v1/audit/verify without MEDULLA_AUDIT_CHAIN (or with a value the role never renders) is
//! 503 UNKNOWN, never chain:'off' (tests/anatomy/test_medulla_serves_audit_verify.py runs PHP beside it).
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

fn serve(name: &str, flag: Option<&str>) -> Served {
    let dir = std::env::temp_dir().join(format!("medulla-audit-reads-{}-{name}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let db = dir.join("wing.db");
    let _ = std::fs::remove_file(&db);
    let hash: String = ring::digest::digest(&ring::digest::SHA256, b"read").as_ref().iter().map(|b| format!("{b:02x}")).collect();
    rusqlite::Connection::open(&db).unwrap().execute_batch(&format!(
        "CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, token TEXT, name TEXT, active INTEGER, scopes TEXT);
         CREATE TABLE audit_chain_meta (k TEXT PRIMARY KEY, v TEXT);
         INSERT INTO api_tokens (token, name, active, scopes) VALUES ('{hash}', 'conductor', 1, 'wing.read');
         INSERT INTO audit_chain_meta VALUES ('last_verify_ok', '1'), ('last_verify_at', '2026-11-01T03:00:00Z');"
    )).unwrap();
    let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_medulla"));
    cmd.args(["wing", "serve", "--db", db.to_str().unwrap(), "--port", &port.to_string()])
        .env("NOS_HALT_FILE", dir.join("halt")).env_remove("MEDULLA_AUDIT_CHAIN").stdout(Stdio::null());
    if let Some(f) = flag {
        cmd.env("MEDULLA_AUDIT_CHAIN", f);
    }
    let child = cmd.spawn().unwrap();
    for _ in 0..100 {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return Served(child, port);
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    panic!("medulla wing serve never listened");
}

fn get(port: u16, bearer: &str) -> (u16, serde_json::Value) {
    let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
    write!(s, "GET /api/v1/audit/verify HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {bearer}\r\n\r\n").unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).unwrap();
    (out[9..12].parse().unwrap(), serde_json::from_str(out.split_once("\r\n\r\n").unwrap().1).unwrap())
}

#[test]
fn an_absent_or_unknown_flag_is_503_not_off() {
    for (name, flag) in [("absent", None), ("empty", Some("")), ("yes", Some("yes"))] {
        let s = serve(name, flag);
        let (code, body) = get(s.1, "read");
        assert_eq!(code, 503, "{name}: {body}");
        assert_eq!(body["code"], 503, "{name}: {body}");
        assert!(body.get("chain").is_none(), "{name}: {body}");
        assert_eq!(get(s.1, "nope").0, 401, "{name}: auth still runs first");
    }
    let s = serve("on", Some("on"));
    let (code, body) = get(s.1, "read");
    assert_eq!((code, body["chain"].as_str(), body["ok"].as_bool()), (200, Some("on"), Some(true)), "{body}");
}
