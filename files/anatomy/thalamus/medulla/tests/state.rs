//! The joint of row medulla-settings (ssot/doctrine/gates.md §7): `medulla state --json`, the
//! thalamus socket's `state` and GET /api/v1/admin/state are one reader, so all three say the same
//! struct — off, then with the halt and the loops pause filed, on. One medulla process opens both
//! the socket and the HTTP door, as `thalamus serve` does on the host with NOS_WING_DB set.
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

struct Served(Child);

impl Drop for Served {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn env<'a>(cmd: &'a mut Command, home: &Path) -> &'a mut Command {
    cmd.env_clear().env("HOME", home).env("NOS_REPO_ROOT", home).env("PATH", std::env::var("PATH").unwrap())
        .env("NOS_HALT_FILE", home.join("halt")).env("NOS_LOOPS_PAUSED_FILE", home.join("loops-paused"))
}

fn cli(home: &Path) -> Value {
    let out = env(&mut Command::new(env!("CARGO_BIN_EXE_medulla")), home).args(["state", "--json"]).output().unwrap();
    assert!(out.status.success(), "medulla state --json: {}", String::from_utf8_lossy(&out.stderr));
    serde_json::from_slice(&out.stdout).unwrap()
}

fn socket(home: &Path) -> Value {
    let mut s = UnixStream::connect(home.join(".nos/thalamus.sock")).unwrap();
    s.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
    s.write_all(b"{\"t\":\"state\"}\n").unwrap();
    let mut line = String::new();
    BufReader::new(s).read_line(&mut line).unwrap();
    let mut v: Value = serde_json::from_str(&line).unwrap();
    assert_eq!(v["t"], "state", "{line}");
    v.as_object_mut().unwrap().remove("t");
    v
}

fn http(port: u16) -> Value {
    let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
    s.write_all(b"GET /api/v1/admin/state HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer reader\r\n\r\n").unwrap();
    let mut raw = String::new();
    s.read_to_string(&mut raw).unwrap();
    let (head, body) = raw.split_once("\r\n\r\n").unwrap();
    assert!(head.starts_with("HTTP/1.1 200"), "{raw}");
    let mut v: Value = serde_json::from_str(body).unwrap();
    // Wing's own two keys ride along (PHP's answer, test_medulla_serves_pulse_reads.py); the struct is the rest.
    let o = v.as_object_mut().unwrap();
    assert!(o.remove("halt_active").is_some() && o.remove("job_counts").is_some(), "{body}");
    v
}

#[test]
fn the_three_doors_say_one_state() {
    let home = std::path::PathBuf::from(format!("/tmp/md-state-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    let me = thalamus::serve::login(unsafe { libc::getuid() }).unwrap();
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {me: {"username": "alice", "groups": ["nos-users"]}}}).to_string()).unwrap();
    let db = home.join("wing.db");
    let hash: String = ring::digest::digest(&ring::digest::SHA256, b"reader").as_ref().iter().map(|b| format!("{b:02x}")).collect();
    rusqlite::Connection::open(&db).unwrap().execute_batch(&format!(
        "CREATE TABLE api_tokens (token TEXT, name TEXT, active INTEGER, scopes TEXT);
         CREATE TABLE pulse_jobs (id TEXT, paused INTEGER, paused_reason TEXT, removed_at TEXT);
         INSERT INTO api_tokens VALUES ('{hash}', 'conductor', 1, 'wing.read');")).unwrap();
    let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
    let _served = Served(env(&mut Command::new(env!("CARGO_BIN_EXE_medulla")), &home)
        .args(["thalamus", "serve", "--data-dir"]).arg(home.join("data"))
        .env("KEAP_PROXY_SHARED_SECRET", "s").env("NOS_WING_DB", &db).env("MEDULLA_HTTP_PORT", port.to_string())
        .stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap());
    for _ in 0..200 {
        if home.join(".nos/thalamus.sock").exists() && TcpStream::connect(("127.0.0.1", port)).is_ok() {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let doors = || {
        let all = [cli(&home), socket(&home), http(port)];
        assert!(all[0] == all[1] && all[1] == all[2], "the doors disagree:\n cli    {}\n socket {}\n http   {}", all[0], all[1], all[2]);
        all[0].clone()
    };

    let off = doors();
    assert_eq!(off["halt"], serde_json::json!({"on": false, "file": home.join("halt").to_str().unwrap()}), "{off}");
    assert_eq!(off["loops_paused"]["on"], false, "{off}");
    assert!(off["organs"].as_array().is_some_and(|o| o.iter().any(|x| x["name"] == "thalamus")), "{off}");

    std::fs::write(home.join("halt"), "{\"by\": \"alice\", \"at\": \"2026-10-28T09:00:00Z\"}\n").unwrap();
    std::fs::write(home.join("loops-paused"), "since: 2026-10-28T09:01:00Z\nreason: upgrade\n").unwrap();
    let on = doors();
    assert_eq!(on["halt"]["on"], true, "{on}");
    assert_eq!(on["halt"]["since"], "2026-10-28T09:00:00Z", "{on}");
    assert_eq!(on["loops_paused"], serde_json::json!({"on": true, "since": "2026-10-28T09:01:00Z", "reason": "upgrade",
        "file": home.join("loops-paused").to_str().unwrap()}), "{on}");
    let _ = std::fs::remove_dir_all(&home);
}
