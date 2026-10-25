//! `medulla pulse serve` against a fake Wing (row medulla-scheduler, e): it fires only the jobs in
//! PULSE_MEDULLA_JOBS, never one outside it, one run per job while it is in flight, holds every job
//! under ~/.nos/halt, and drains a run in flight on SIGTERM. The fake advances a job (drops it from
//! the due feed) on its finish, as Wing's recordFinish moves next_fire_at.
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[derive(Default)]
struct Wing {
    due: Vec<serde_json::Value>,
    starts: Vec<serde_json::Value>,
    finishes: Vec<(String, serde_json::Value)>,
    auth: Vec<String>,
}
type Shared = Arc<Mutex<Wing>>;

fn wing(due: Vec<serde_json::Value>) -> (u16, Shared) {
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = l.local_addr().unwrap().port();
    let w: Shared = Arc::new(Mutex::new(Wing { due, ..Default::default() }));
    let st = w.clone();
    std::thread::spawn(move || {
        for s in l.incoming().flatten() {
            let mut r = BufReader::new(s.try_clone().unwrap());
            let (mut line, mut auth, mut len) = (String::new(), String::new(), 0usize);
            if r.read_line(&mut line).is_err() {
                continue;
            }
            let mut words = line.split_whitespace();
            let (method, path) = (words.next().unwrap_or("").to_string(), words.next().unwrap_or("").to_string());
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
            let body: serde_json::Value = serde_json::from_slice(&body).unwrap_or_default();
            let mut w = st.lock().unwrap();
            w.auth.push(auth);
            let reply = match (method.as_str(), path.as_str()) {
                ("GET", "/api/v1/pulse_jobs/due") => serde_json::json!({"generated_at": "x", "jobs": w.due}),
                ("POST", "/api/v1/pulse_runs") => {
                    w.starts.push(body);
                    serde_json::json!({"accepted": true})
                }
                ("POST", p) if p.ends_with("/finish") => {
                    let run_id = p.trim_start_matches("/api/v1/pulse_runs/").trim_end_matches("/finish").to_string();
                    let job = w.starts.iter().find(|s| s["run_id"] == run_id.as_str()).map(|s| s["job_id"].clone());
                    w.due.retain(|j| Some(&j["id"]) != job.as_ref());
                    w.finishes.push((job.and_then(|j| j.as_str().map(String::from)).unwrap_or_default(), body));
                    serde_json::json!({"ok": true})
                }
                _ => serde_json::json!({}),
            };
            drop(w);
            let reply = reply.to_string();
            let mut s = s;
            let _ = write!(s, "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{reply}", reply.len());
        }
    });
    (port, w)
}

/// A scratch HOME + repo; each job script touches `<script>.ran` and sleeps `secs`.
fn scratch(tag: &str, jobs: &[(&str, f32)]) -> (PathBuf, Vec<serde_json::Value>) {
    use std::os::unix::fs::PermissionsExt;
    let dir = std::env::temp_dir().join(format!("medulla-serve-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("repo/tools")).unwrap();
    let feed = jobs.iter().map(|(id, secs)| {
        let script = dir.join("repo/tools").join(id.replace(':', "-"));
        std::fs::write(&script, format!("#!/bin/sh\ntouch \"$0.ran\"\nsleep {secs}\necho done\n")).unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
        serde_json::json!({"id": id, "runner": "subprocess", "command": script, "args": [], "env": [], "max_runtime_s": 30})
    }).collect();
    (dir, feed)
}

fn ran(dir: &Path, id: &str) -> bool {
    dir.join("repo/tools").join(format!("{}.ran", id.replace(':', "-"))).exists()
}

fn serve(dir: &Path, port: u16, set: &str) -> Child {
    Command::new(env!("CARGO_BIN_EXE_medulla"))
        .args(["pulse", "serve"])
        .env("MEDULLA_PULSE", "1")
        .env("MEDULLA_WING_TOKEN", "fake-medulla-token")
        .env("PULSE_MEDULLA_JOBS", set)
        .env("PULSE_TICK_INTERVAL_S", "0.2")
        .env("HOME", dir)
        .env("NOS_REPO_ROOT", dir.join("repo"))
        .env("NOS_HALT_FILE", dir.join("halt"))
        .env("NOS_LOOPS_PAUSED_FILE", dir.join("loops-paused"))
        .env("NOS_WING_URL", format!("http://127.0.0.1:{port}"))
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap()
}

fn until(what: &str, secs: u64, f: impl Fn() -> bool) {
    let end = Instant::now() + Duration::from_secs(secs);
    while !f() {
        assert!(Instant::now() < end, "timed out waiting for: {what}");
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn term(mut c: Child) -> std::process::ExitStatus {
    unsafe { libc::kill(c.id() as i32, libc::SIGTERM) };
    let end = Instant::now() + Duration::from_secs(35);
    loop {
        if let Some(s) = c.try_wait().unwrap() {
            return s;
        }
        assert!(Instant::now() < end, "serve did not stop on SIGTERM");
        std::thread::sleep(Duration::from_millis(50));
    }
}

#[test]
fn it_fires_only_its_set_once_per_flight_and_drains_on_sigterm() {
    let (dir, feed) = scratch("set", &[("a:slow", 1.5), ("b:theirs", 0.0)]);
    let (port, w) = wing(feed);
    let c = serve(&dir, port, "a:slow,z:absent");
    until("the start of a:slow", 10, || !w.lock().unwrap().starts.is_empty());
    std::thread::sleep(Duration::from_millis(700)); // ~3 ticks while a:slow is in flight
    let st = term(c);
    assert!(st.success(), "{st:?}");
    let w = w.lock().unwrap();
    let jobs: Vec<&str> = w.starts.iter().map(|s| s["job_id"].as_str().unwrap()).collect();
    assert_eq!(jobs, ["a:slow"], "fired outside its set, or twice while in flight");
    assert!(!ran(&dir, "b:theirs"), "ran a job that is the Python daemon's");
    assert_eq!(w.finishes.len(), 1, "SIGTERM did not drain the run in flight");
    assert_eq!((w.finishes[0].0.as_str(), w.finishes[0].1["exit_code"].as_i64()), ("a:slow", Some(0)));
    assert!(w.auth.iter().all(|a| a == "Bearer fake-medulla-token"));
}

#[test]
fn the_halt_holds_every_job() {
    let (dir, feed) = scratch("halt", &[("a:job", 0.0)]);
    std::fs::write(dir.join("halt"), "test").unwrap();
    let (port, w) = wing(feed);
    let c = serve(&dir, port, "a:job");
    until("the held finish", 10, || !w.lock().unwrap().finishes.is_empty());
    assert!(term(c).success());
    let w = w.lock().unwrap();
    assert_eq!(w.finishes[0].1["exit_code"], 3, "{:?}", w.finishes);
    assert!(w.finishes[0].1["stderr_tail"].as_str().unwrap().contains("emergency halt"));
    assert!(!ran(&dir, "a:job"), "a job ran under the halt");
}

#[test]
fn an_empty_set_fires_nothing_and_says_so() {
    let (dir, _) = scratch("empty", &[]);
    let o = Command::new(env!("CARGO_BIN_EXE_medulla")).args(["pulse", "serve"])
        .env("MEDULLA_PULSE", "1").env("MEDULLA_WING_TOKEN", "t").env("PULSE_MEDULLA_JOBS", "").env("HOME", &dir)
        .output().unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&o.stderr).contains("PULSE_MEDULLA_JOBS is empty"));
}
