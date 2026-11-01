//! The joint of v16 (ssot/doctrine/gates.md §7): a tier-1 person lists the agents' open questions over the
//! thalamus socket from wing.db, and a tier-1 decider's answer is relayed to Wing, which resolves it once:
//! the first answer is answered, the second lost with the answer that won. A peer that is not a decider is
//! refused and Wing hears nothing. Every path is a tempdir; Wing is a stub on a loopback port.
#![cfg_attr(target_os = "linux", allow(dead_code, unused_imports))]
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const Q: &str = "7f3e2d1c-0b9a-4c8d-9e7f-6a5b4c3d2e1f";

struct Served(Child, PathBuf);

impl Drop for Served {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
        let _ = std::fs::remove_dir_all(&self.1);
    }
}

fn env<'a>(cmd: &'a mut Command, home: &Path, wing: u16) -> &'a mut Command {
    cmd.env_clear().env("HOME", home).env("NOS_REPO_ROOT", home).env("PATH", std::env::var("PATH").unwrap())
        .env("NOS_WING_URL", format!("http://127.0.0.1:{wing}"))
}

fn map(home: &Path, groups: &[&str]) {
    let me = thalamus::serve::login(unsafe { libc::getuid() }).unwrap();
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {me: {"username": "alice", "groups": groups}}}).to_string()).unwrap();
}

/// A Wing whose first answer POST wins and every later one loses to it; keeps (request line, bearer, body).
fn wing(seen: Arc<Mutex<Vec<String>>>) -> u16 {
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
        let mut seen = seen.lock().unwrap();
        seen.push(format!("{} {auth} {}", line.rsplit_once(' ').map_or(&*line, |(a, _)| a), String::from_utf8_lossy(&sent).split_whitespace().collect::<String>()));
        let (code, body) = if seen.len() == 1 {
            (200, "{\"result\":\"ok\"}".to_string())
        } else {
            (409, "{\"error\":\"Already answered by alice: yes\",\"code\":409,\"result\":\"already\",\"answer\":\"yes\",\"answered_by\":\"alice\"}".into())
        };
        let _ = (&s).write_all(format!("HTTP/1.1 {code} X\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()).as_bytes());
    });
    port
}

/// A tempdir HOME with a tier-1 alice, the wing-answer bearer and a wing.db holding one open and one answered question.
fn serve(tag: &str, port: u16) -> (PathBuf, Served) {
    let home = PathBuf::from(format!("/tmp/md-q-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    map(&home, &["nos-admins"]);
    std::fs::write(home.join(".nos/secrets.yml"), format!("wing_halt_token: \"{}\"\nwing_answer_token: \"{}\"\n", "h".repeat(64), "a".repeat(64))).unwrap();
    let db = home.join("wing.db");
    rusqlite::Connection::open(&db).unwrap().execute_batch(&format!(
        "CREATE TABLE agent_questions (id INTEGER PRIMARY KEY, uuid TEXT, agent_name TEXT, prompt TEXT, reply_token_sha TEXT,
            status TEXT, answer TEXT, expires_at TEXT, created_at TEXT);
         INSERT INTO agent_questions VALUES (1, '{Q}', 'conductor', 'Apply the upgrade?', 'secret-sha', 'open', NULL, '2099-01-01T00:00:00Z', '2026-11-01 08:00:00');
         INSERT INTO agent_questions VALUES (2, 'a1b2c3d4-0000-4000-8000-000000000002', 'conductor', 'Old one', 'sha', 'answered', 'no', NULL, '2026-10-01 08:00:00');")).unwrap();
    let me = std::fs::canonicalize(env!("CARGO_BIN_EXE_medulla")).unwrap();
    let child = env(&mut Command::new(env!("CARGO_BIN_EXE_medulla")), &home, port)
        .args(["thalamus", "serve", "--data-dir"]).arg(home.join("data"))
        .env("KEAP_PROXY_SHARED_SECRET", "s").env("NOS_TIER1_GROUPS", "nos-admins").env("NOS_DECIDER_EXES", &me)
        .env("NOS_INBOX_DB", &db).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
    for _ in 0..200 {
        if home.join(".nos/thalamus.sock").exists() { break }
        std::thread::sleep(Duration::from_millis(50));
    }
    (home.clone(), Served(child, home))
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
fn a_peer_that_is_no_decider_is_refused_and_wing_hears_nothing() {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let port = wing(seen.clone());
    let (home, _served) = serve("refused", port);
    let v = raw(&home, &format!("{{\"t\":\"answer\",\"uuid\":\"{Q}\",\"answer\":\"yes\"}}\n"));
    assert_eq!(v["t"], "refused", "{v}");
    // The questions read needs tier 1 only: the same peer lists them, without the reply token's hash.
    let v = raw(&home, "{\"t\":\"questions\"}\n");
    assert_eq!(v["t"], "questions", "{v}");
    let items = v["items"].as_array().unwrap();
    assert_eq!((items.len(), items[0]["uuid"].as_str()), (1, Some(Q)), "only the open question: {v}");
    assert!(items[0].get("reply_token_sha").is_none(), "{v}");
    map(&home, &["nos-users"]);
    let v = raw(&home, "{\"t\":\"questions\"}\n");
    assert!(v["t"] == "refused" && v["reason"].as_str().unwrap().contains("tier 1"), "{v}");
    assert!(seen.lock().unwrap().is_empty(), "a refusal reached Wing: {:?}", seen.lock().unwrap());
}

#[cfg(target_os = "macos")]
#[test]
fn a_decider_answers_once_and_the_second_answer_learns_it_lost() {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let port = wing(seen.clone());
    let (home, _served) = serve("decider", port);

    let o = medulla(&home, port, &["questions"]);
    assert!(o.status.success() && said(&o).contains("Apply the upgrade?") && !said(&o).contains("Old one"), "{}", said(&o));

    let o = medulla(&home, port, &["answer", Q, "yes"]);
    assert!(o.status.success() && said(&o).contains("answered"), "{}", said(&o));
    let o = medulla(&home, port, &["answer", Q, "no"]);
    assert_eq!(o.status.code(), Some(3), "{}", said(&o));
    assert!(said(&o).contains("LOST — yes won first"), "{}", said(&o));

    let seen = seen.lock().unwrap();
    assert_eq!(seen.len(), 2, "one POST an answer, never a retry: {seen:?}");
    let body = |a: &str| format!("POST /api/v1/inbox/questions/{Q}/answer Bearer {} {{\"answer\":\"{a}\",\"answered_by\":\"alice\",\"via\":\"medulla\"}}", "a".repeat(64));
    assert_eq!(*seen, vec![body("yes"), body("no")]);

    // No bearer on the host: refused with why, and still never retried.
    std::fs::write(home.join(".nos/secrets.yml"), "wing_halt_token: \"x\"\n").unwrap();
    let o = medulla(&home, port, &["answer", Q, "yes"]);
    assert!(o.status.code() == Some(1) && said(&o).contains("no wing_answer_token"), "{}", said(&o));
    assert_eq!(seen.len(), 2);
}
