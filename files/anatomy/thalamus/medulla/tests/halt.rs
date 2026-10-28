//! The joint of row medulla-settings, increment 2 (ssot/doctrine/gates.md §7): a tier-1 decider halts
//! and lifts the halt over the thalamus socket (`medulla halt`/`resume`), the readers — state.rs and the
//! pulse hold — see it, Wing is sent the act, and a peer that is not tier 1 or not a listed decider is
//! refused with the file untouched. Every path is a tempdir; Wing is a stub on a loopback port.
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::process::{Child, Command, Output, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;

struct Served(Child);

impl Drop for Served {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn env<'a>(cmd: &'a mut Command, home: &Path, wing: u16) -> &'a mut Command {
    cmd.env_clear().env("HOME", home).env("NOS_REPO_ROOT", home).env("PATH", std::env::var("PATH").unwrap())
        .env("NOS_HALT_FILE", home.join("halt")).env("NOS_LOOPS_PAUSED_FILE", home.join("loops-paused"))
        .env("NOS_WING_URL", format!("http://127.0.0.1:{wing}"))
}

fn map(home: &Path, groups: &[&str]) {
    let me = thalamus::serve::login(unsafe { libc::getuid() }).unwrap();
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {me: {"username": "alice", "groups": groups}}}).to_string()).unwrap();
}

/// A Wing that answers every request with `code` and keeps (method path, bearer, body).
fn wing(code: Arc<Mutex<u16>>, seen: Arc<Mutex<Vec<String>>>) -> u16 {
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = l.local_addr().unwrap().port();
    std::thread::spawn(move || for s in l.incoming().flatten() {
        let mut r = BufReader::new(s.try_clone().unwrap());
        let mut head = Vec::new();
        loop {
            let mut line = String::new();
            if r.read_line(&mut line).unwrap_or(0) == 0 || line == "\r\n" { break }
            head.push(line.trim_end().to_string());
        }
        let len = head.iter().find_map(|h| h.to_lowercase().strip_prefix("content-length:").map(|v| v.trim().parse::<usize>().unwrap_or(0))).unwrap_or(0);
        let mut sent = vec![0; len];
        let _ = r.read_exact(&mut sent);
        let auth = head.iter().find_map(|h| h.strip_prefix("authorization: ").or(h.strip_prefix("Authorization: "))).unwrap_or("-");
        let line = head.first().cloned().unwrap_or_default();
        seen.lock().unwrap().push(format!("{} {auth} {}", line.rsplit_once(' ').map_or(&*line, |(a, _)| a), String::from_utf8_lossy(&sent).split_whitespace().collect::<String>()));
        let body = "{\"halt_active\": true}";
        let _ = (&s).write_all(format!("HTTP/1.1 {} X\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            *code.lock().unwrap(), body.len()).as_bytes());
    });
    port
}

fn medulla(home: &Path, port: u16, args: &[&str]) -> Output {
    env(&mut Command::new(env!("CARGO_BIN_EXE_medulla")), home, port).args(args).output().unwrap()
}

fn said(o: &Output) -> String {
    format!("exit {:?}\n{}{}", o.status.code(), String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr))
}

/// The test binary is no listed decider: it sends a line itself, as any socket client could.
fn raw(home: &Path, line: &str) -> Value {
    let mut s = UnixStream::connect(home.join(".nos/thalamus.sock")).unwrap();
    s.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
    s.write_all(line.as_bytes()).unwrap();
    let mut back = String::new();
    BufReader::new(s).read_line(&mut back).unwrap();
    serde_json::from_str(&back).unwrap()
}

#[test]
fn a_decider_halts_and_resumes_and_no_one_else_does() {
    let home = std::path::PathBuf::from(format!("/tmp/md-halt-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    map(&home, &["nos-admins"]);
    std::fs::write(home.join(".nos/secrets.yml"), format!("wing_api_token: \"agent\"\nwing_halt_token: \"{}\"\n", "h".repeat(64))).unwrap();
    let db = home.join("wing.db");
    let job = home.join("tools/job.sh");
    std::fs::create_dir_all(home.join("tools")).unwrap();
    std::fs::write(&job, "#!/bin/sh\nexit 0\n").unwrap();
    std::fs::set_permissions(&job, std::os::unix::fs::PermissionsExt::from_mode(0o755)).unwrap();
    rusqlite::Connection::open(&db).unwrap().execute_batch(&format!(
        "CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, runner TEXT NOT NULL DEFAULT 'subprocess', command TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '[]', env_json TEXT NOT NULL DEFAULT '{{}}', max_runtime_s INTEGER NOT NULL DEFAULT 300,
            removed_at TEXT);
         INSERT INTO pulse_jobs (id, command) VALUES ('a:plain', '{}');", job.display())).unwrap();
    let (code, seen) = (Arc::new(Mutex::new(200)), Arc::new(Mutex::new(Vec::new())));
    let port = wing(code.clone(), seen.clone());
    let me = std::fs::canonicalize(env!("CARGO_BIN_EXE_medulla")).unwrap();
    let _served = Served(env(&mut Command::new(env!("CARGO_BIN_EXE_medulla")), &home, port)
        .args(["thalamus", "serve", "--data-dir"]).arg(home.join("data"))
        .env("KEAP_PROXY_SHARED_SECRET", "s").env("NOS_TIER1_GROUPS", "nos-admins").env("NOS_DECIDER_EXES", &me)
        .stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap());
    for _ in 0..200 {
        if home.join(".nos/thalamus.sock").exists() { break }
        std::thread::sleep(Duration::from_millis(50));
    }
    let state = || -> Value { serde_json::from_slice(&medulla(&home, port, &["state", "--json"]).stdout).unwrap() };
    let held = || -> Value {
        let o = env(&mut Command::new(env!("CARGO_BIN_EXE_medulla")), &home, port).env("MEDULLA_PULSE", "1")
            .args(["pulse", "run", "a:plain", "--db", db.to_str().unwrap()]).output().unwrap();
        serde_json::from_slice(&o.stdout).unwrap_or_else(|_| panic!("{}", said(&o)))
    };

    // A decider at tier 1 halts: the file in the shape tools/nos writes, the readers see it, Wing hears it.
    let o = medulla(&home, port, &["halt", "--reason", "drill"]);
    assert!(o.status.success(), "{}", said(&o));
    assert!(said(&o).contains("recorded"), "{}", said(&o));
    let f: Value = serde_json::from_str(&std::fs::read_to_string(home.join("halt")).unwrap()).unwrap();
    assert_eq!((f["by"].as_str(), f["reason"].as_str()), (Some("alice"), Some("drill")), "{f}");
    assert!(f["at"].as_str().is_some_and(|a| a.len() == 20 && a.ends_with('Z')), "{f}");
    assert_eq!((state()["halt"]["on"].clone(), state()["halt"]["reason"].clone()), (Value::Bool(true), "drill".into()));
    assert!(held()["stderr_tail"].as_str().unwrap().starts_with("PAUSED: emergency halt"));
    assert_eq!(seen.lock().unwrap().last().cloned(), Some(format!("POST /api/v1/admin/halt Bearer {} {{\"by\":\"alice\"}}", "h".repeat(64))));
    let before = std::fs::read(home.join("halt")).unwrap();

    // Not a listed decider (this test binary), then not tier 1: refused, the file as it was.
    let v = raw(&home, "{\"t\":\"lift_halt\"}\n");
    assert!(v["t"] == "refused" && v["reason"].as_str().unwrap().contains("not a listed decider"), "{v}");
    map(&home, &["nos-users"]);
    let o = medulla(&home, port, &["resume"]);
    assert!(!o.status.success() && said(&o).contains("tier 1"), "{}", said(&o));
    assert_eq!(std::fs::read(home.join("halt")).unwrap(), before, "a refused peer changed the halt");
    assert_eq!(seen.lock().unwrap().len(), 1, "a refusal reached Wing: {:?}", seen.lock().unwrap());

    // Wing refuses the record: the resume still takes effect, and says it is not recorded.
    map(&home, &["nos-admins"]);
    *code.lock().unwrap() = 403;
    let o = medulla(&home, port, &["resume"]);
    assert_eq!(o.status.code(), Some(3), "{}", said(&o));
    assert!(said(&o).contains("NOT recorded") && said(&o).contains("403"), "{}", said(&o));
    assert!(!home.join("halt").exists());
    assert_eq!(state()["halt"]["on"], false);
    assert_eq!(held()["exit_code"], 0, "a lifted halt still holds the job");
    assert_eq!(seen.lock().unwrap().last().cloned(), Some(format!("POST /api/v1/admin/resume Bearer {} {{\"by\":\"alice\"}}", "h".repeat(64))));
    let _ = std::fs::remove_dir_all(&home);
}
