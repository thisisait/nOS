//! `medulla wing serve` over a scratch wing.db: the exposition PHP's MetricsPresenter emits,
//! 404 for any other path, loopback bind only (ssot/doctrine/medulla.md §5).
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

fn serve(db: &std::path::Path) -> Served {
    let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
    let child = Command::new(env!("CARGO_BIN_EXE_medulla"))
        .args(["wing", "serve", "--db", db.to_str().unwrap(), "--port", &port.to_string()])
        .env("NOS_HALT_FILE", db.with_file_name("halt")) // never the operator's ~/.nos/halt
        .stdout(Stdio::null())
        .spawn()
        .unwrap();
    for _ in 0..100 {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return Served(child, port);
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    panic!("medulla wing serve never listened");
}

fn get(port: u16, path: &str) -> String {
    let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
    write!(s, "GET {path} HTTP/1.1\r\nHost: x\r\n\r\n").unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).unwrap();
    out
}

fn scratch() -> (std::path::PathBuf, std::path::PathBuf) {
    let dir = std::env::temp_dir().join(format!("medulla-metrics-{}-{:?}", std::process::id(), std::thread::current().id()));
    std::fs::create_dir_all(&dir).unwrap();
    let db = dir.join("wing.db");
    let _ = std::fs::remove_file(&db);
    let c = rusqlite::Connection::open(&db).unwrap();
    c.execute_batch(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, type TEXT NOT NULL, result_json TEXT);
         CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0, paused_reason TEXT, removed_at TEXT);
         INSERT INTO events (ts, type, result_json) VALUES
           ('2026-10-21T00:00:00Z', 'e2e_journey_end', '{\"journey\":\"a\\\"b\",\"status\":\"pass\"}'),
           ('2026-10-21T00:00:10Z', 'e2e_journey_end', '{\"journey\":\"a\\\"b\",\"status\":\"pass\"}'),
           ('2026-10-21T00:00:05Z', 'e2e_journey_step', '{\"journey\":\"j\",\"step\":\"s\",\"status\":\"pass\",\"duration_ms\":7}'),
           ('2026-10-21T00:00:06Z', 'e2e_journey_step', '{\"journey\":\"j\",\"step\":\"s\",\"status\":\"pass\",\"duration_ms\":5}');
         INSERT INTO pulse_jobs VALUES ('x', 1, 'emergency-halt:op', NULL), ('y', 0, NULL, NULL), ('z', 0, NULL, '2026-01-01');",
    )
    .unwrap();
    (dir, db)
}

#[test]
fn metrics_match_the_php_exposition() {
    let (dir, db) = scratch();
    let s = serve(&db);
    let r = get(s.1, "/api/v1/metrics");
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    assert!(r.contains("Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"), "{r}");
    assert!(r.contains("Cache-Control: no-store\r\n"), "{r}");
    for line in [
        "nos_e2e_journey_runs_total{journey=\"a\\\"b\",status=\"pass\"} 2",
        "nos_e2e_journey_step_duration_ms_sum{journey=\"j\",step=\"s\",status=\"pass\"} 12",
        "nos_e2e_journey_step_duration_ms_count{journey=\"j\",step=\"s\",status=\"pass\"} 2",
        "nos_e2e_journey_last_run_timestamp{journey=\"a\\\"b\",status=\"pass\"} 1792540810",
        "nos_pulse_jobs{job_id=\"x\",state=\"emergency_halted\"} 1",
        "nos_pulse_jobs{job_id=\"y\",state=\"unpaused\"} 1",
    ] {
        assert!(r.lines().any(|l| l == line), "missing {line}\n{r}");
    }
    assert!(!r.contains("job_id=\"z\""), "a removed job is reported");
    assert!(get(s.1, "/api/v1/other").starts_with("HTTP/1.1 404"));
    let _ = std::fs::remove_dir_all(dir);
}

#[test]
fn the_halt_file_halts_every_job_not_paused_by_hand() {
    let (dir, db) = scratch();
    std::fs::write(db.with_file_name("halt"), "{\"by\":\"op\"}\n").unwrap();
    let s = serve(&db);
    let r = get(s.1, "/api/v1/metrics");
    assert!(r.lines().any(|l| l == "nos_pulse_jobs{job_id=\"y\",state=\"emergency_halted\"} 1"), "{r}");
    let _ = std::fs::remove_dir_all(dir);
}

#[test]
fn it_binds_loopback_only() {
    let (dir, db) = scratch();
    let s = serve(&db);
    // Every non-loopback interface address of this host is refused; the source names the bind.
    assert!(include_str!("../src/metrics.rs").contains("TcpListener::bind((\"127.0.0.1\", port))"));
    let probe = std::net::UdpSocket::bind("0.0.0.0:0").unwrap();
    if probe.connect("10.255.255.255:1").is_ok() {
        let ip = probe.local_addr().unwrap().ip();
        if !ip.is_loopback() && !ip.is_unspecified() {
            assert!(TcpStream::connect_timeout(&(ip, s.1).into(), Duration::from_secs(1)).is_err(), "{ip} reached the door");
        }
    }
    let _ = std::fs::remove_dir_all(dir);
}
