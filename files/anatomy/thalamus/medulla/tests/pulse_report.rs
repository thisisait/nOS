//! `medulla pulse run <job> --report` speaks to a fake Wing on a free loopback port: the start is
//! claimed before the job runs and a refused start runs nothing; the finish carries the result; the
//! bearer comes from MEDULLA_WING_TOKEN only (row medulla-scheduler, increment c2). wing.db stays
//! untouched: the medulla executes, the writing organ writes.
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Command, Output};
use std::sync::{Arc, Mutex};

type Seen = Arc<Mutex<Vec<(String, String, String)>>>; // (path, authorization, body)

/// A Wing that answers `code` to every POST and records what it was sent.
fn wing(code: u16) -> (u16, Seen) {
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = l.local_addr().unwrap().port();
    let seen: Seen = Arc::default();
    let rec = seen.clone();
    std::thread::spawn(move || {
        for s in l.incoming().flatten() {
            let mut r = BufReader::new(s.try_clone().unwrap());
            let (mut line, mut auth, mut len) = (String::new(), String::new(), 0usize);
            r.read_line(&mut line).unwrap();
            let path = line.split_whitespace().nth(1).unwrap_or("").to_string();
            loop {
                let mut h = String::new();
                r.read_line(&mut h).unwrap();
                if h.trim().is_empty() {
                    break;
                }
                let (k, v) = h.split_once(':').unwrap_or(("", ""));
                match k.to_ascii_lowercase().as_str() {
                    "authorization" => auth = v.trim().to_string(),
                    "content-length" => len = v.trim().parse().unwrap_or(0),
                    _ => {}
                }
            }
            let mut body = vec![0; len];
            r.read_exact(&mut body).unwrap();
            rec.lock().unwrap().push((path, auth, String::from_utf8_lossy(&body).into()));
            let reply = if code == 200 { r#"{"ok":true}"# } else { r#"{"error":"Recording a Pulse run needs the pulse.run scope"}"# };
            let mut s = s;
            let _ = write!(s, "HTTP/1.1 {code} X\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{reply}", reply.len());
        }
    });
    (port, seen)
}

fn scratch(tag: &str) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;
    let dir = std::env::temp_dir().join(format!("medulla-report-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("repo/tools")).unwrap();
    let script = dir.join("repo/tools/job.sh");
    std::fs::write(&script, "#!/bin/sh\ntouch \"$NOS_SCAN_DIR\"\necho done\nexit 5\n").unwrap();
    std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
    let c = rusqlite::Connection::open(dir.join("wing.db")).unwrap();
    c.execute_batch(&format!(
        "CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, runner TEXT NOT NULL DEFAULT 'subprocess', command TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '[]', env_json TEXT NOT NULL DEFAULT '{{}}', max_runtime_s INTEGER NOT NULL DEFAULT 300,
            removed_at TEXT);
         INSERT INTO pulse_jobs (id, command, env_json) VALUES ('a:job', '{}', '{{\"NOS_SCAN_DIR\": \"{}\"}}');",
        script.display(), dir.join("ran").display()
    ))
    .unwrap();
    dir
}

fn run(dir: &PathBuf, port: Option<u16>, token: Option<&str>) -> Output {
    let mut c = Command::new(env!("CARGO_BIN_EXE_medulla"));
    c.args(["pulse", "run", "a:job", "--report", "--db", dir.join("wing.db").to_str().unwrap()])
        .env("MEDULLA_PULSE", "1")
        .env("HOME", dir)
        .env("NOS_REPO_ROOT", dir.join("repo"))
        .env("NOS_HALT_FILE", dir.join("halt"))
        .env("NOS_LOOPS_PAUSED_FILE", dir.join("loops-paused"))
        .env("NOS_WING_URL", format!("http://127.0.0.1:{}", port.unwrap_or(9)))
        .env_remove("MEDULLA_WING_TOKEN");
    if let Some(t) = token {
        c.env("MEDULLA_WING_TOKEN", t);
    }
    c.output().unwrap()
}

#[test]
fn the_start_is_claimed_first_and_the_finish_carries_the_result() {
    let (port, seen) = wing(200);
    let dir = scratch("ok");
    let before = std::fs::read(dir.join("wing.db")).unwrap();
    let o = run(&dir, Some(port), Some("fake-medulla-token"));
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!((v["exit_code"].as_i64(), v["reported"].as_bool()), (Some(5), Some(true)), "{v}");
    let id = v["run_id"].as_str().unwrap();
    let calls = seen.lock().unwrap().clone();
    assert_eq!(calls.len(), 2, "{calls:?}");
    assert_eq!(calls[0].0, "/api/v1/pulse_runs");
    assert_eq!(calls[1].0, format!("/api/v1/pulse_runs/{id}/finish"));
    assert!(calls.iter().all(|(_, a, _)| a == "Bearer fake-medulla-token"));
    let start: serde_json::Value = serde_json::from_str(&calls[0].2).unwrap();
    assert_eq!((start["job_id"].as_str(), start["run_id"].as_str(), start["actor_action_id"].as_str()), (Some("a:job"), Some(id), Some(id)));
    let fin: serde_json::Value = serde_json::from_str(&calls[1].2).unwrap();
    assert_eq!(fin["exit_code"], 5);
    assert!(fin["stdout_tail"].as_str().unwrap().contains("done") && fin["duration_ms"].is_u64(), "{fin}");
    assert_eq!(std::fs::read(dir.join("wing.db")).unwrap(), before, "the medulla wrote wing.db");
    // The mark rides an allow-listed job env key: the refused cases below assert its absence.
    assert!(dir.join("ran").exists(), "the job did not run, so `ran` absent proves nothing below");
}

#[test]
fn a_start_wing_refuses_runs_nothing() {
    let (port, seen) = wing(403);
    let dir = scratch("refused");
    let o = run(&dir, Some(port), Some("fake-agent-token"));
    assert!(!o.status.success());
    assert!(String::from_utf8_lossy(&o.stderr).contains("not fired") && String::from_utf8_lossy(&o.stderr).contains("403"));
    assert!(!dir.join("ran").exists(), "the job ran although its start was refused");
    assert_eq!(seen.lock().unwrap().len(), 1, "a finish was sent for a run that never started");
}

#[test]
fn no_token_no_report_and_nothing_runs() {
    let dir = scratch("notoken");
    let o = run(&dir, None, None);
    assert_eq!(o.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&o.stderr).contains("MEDULLA_WING_TOKEN"));
    assert!(!dir.join("ran").exists());
}
