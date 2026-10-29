//! The joint of row medulla-settings, increment 3 (ssot/doctrine/gates.md §7): a tier-1 decider pauses a
//! job over the socket (`medulla pause`), the store file holds it, both schedulers' readers hold it —
//! `medulla pulse run` and Wing's due feed (PulseRepository::listDue under php, when php and Wing's
//! vendor/ are here) — Wing is sent the change, unpause lets it run; a peer that is not a listed decider
//! or not tier 1, a key the genome does not name and a bad change are refused with the file untouched.
#![cfg_attr(target_os = "linux", allow(dead_code, unused_imports))]
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;

struct Served(Child, PathBuf);

impl Drop for Served {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
        let _ = std::fs::remove_dir_all(&self.1);
    }
}

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../..").canonicalize().unwrap()
}

fn env<'a>(cmd: &'a mut Command, home: &Path, wing: u16) -> &'a mut Command {
    cmd.env_clear().env("HOME", home).env("NOS_REPO_ROOT", repo()).env("PATH", std::env::var("PATH").unwrap())
        .env("NOS_HALT_FILE", home.join("halt")).env("NOS_LOOPS_PAUSED_FILE", home.join("loops-paused"))
        .env("MEDULLA_DATA_DIR", home.join("medulla")).env("NOS_WING_URL", format!("http://127.0.0.1:{wing}"))
}

/// A Wing that answers 200 and keeps (method path, body) of each request.
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
        let line = head.first().cloned().unwrap_or_default();
        seen.lock().unwrap().push(format!("{} {}", line.rsplit_once(' ').map_or(&*line, |(a, _)| a), String::from_utf8_lossy(&sent)));
        let _ = (&s).write_all(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: 2\r\nconnection: close\r\n\r\n{}");
    });
    port
}

fn said(o: &Output) -> String {
    format!("exit {:?}\n{}{}", o.status.code(), String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr))
}

/// The test binary, listed as a decider here, sends a line no CLI would.
fn raw(home: &Path, line: &str) -> Value {
    let mut s = UnixStream::connect(home.join(".nos/thalamus.sock")).unwrap();
    s.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
    s.write_all(line.as_bytes()).unwrap();
    let mut back = String::new();
    BufReader::new(s).read_line(&mut back).unwrap();
    serde_json::from_str(&back).unwrap()
}

/// PulseRepository::listDue of this tree over `db`, with the env Wing's plist renders; None when php or
/// Wing's vendor/ is not on this host (said, not hidden).
fn php_due(db: &Path, home: &Path) -> Option<Vec<String>> {
    let wing = repo().join("files/anatomy/wing");
    let autoload = wing.join("vendor/autoload.php");
    if !autoload.exists() || Command::new("php").arg("-v").output().is_err() {
        eprintln!("settings joint: PHP's due feed NOT exercised (no php or no {})", autoload.display());
        return None;
    }
    let code = r#"require $argv[1];
require getcwd() . '/app/Model/PulseRepository.php';
$pdo = new Nette\Database\Connection('sqlite:' . $argv[2]);
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
echo json_encode(array_column((new App\Model\PulseRepository($db))->listDue(), 'id'));"#;
    let o = Command::new("php").current_dir(&wing).env("MEDULLA_DATA_DIR", home.join("medulla"))
        .env("NOS_HALT_FILE", home.join("halt")).args(["-r", code]).arg(&autoload).arg(db).output().unwrap();
    assert!(o.status.success(), "php: {}", said(&o));
    Some(serde_json::from_slice(&o.stdout).unwrap())
}

#[cfg(target_os = "linux")]
#[test]
fn on_linux_no_decider_is_trusted_to_pause() {
    let why = thalamus::serve::decider_refusal(&[PathBuf::from("/bin/sh")], Some("/bin/sh"));
    assert!(why.as_deref().is_some_and(|w| w.contains("connecting process")), "{why:?}");
}

#[cfg(target_os = "macos")]
#[test]
fn a_decider_pauses_a_job_both_schedulers_hold_it_and_no_one_else_sets_it() {
    let home = PathBuf::from(format!("/tmp/md-set-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    let me = thalamus::serve::login(unsafe { libc::getuid() }).unwrap();
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {&me: {"username": "alice", "groups": ["nos-admins"]}}}).to_string()).unwrap();
    std::fs::write(home.join(".nos/secrets.yml"), format!("wing_halt_token: \"{}\"\n", "h".repeat(64))).unwrap();
    let job = home.join(".nos/job.sh"); // HOME_TREES: the allowlist admits ~/.nos/
    std::fs::write(&job, "#!/bin/sh\nexit 0\n").unwrap();
    std::fs::set_permissions(&job, std::os::unix::fs::PermissionsExt::from_mode(0o755)).unwrap();
    // Wing's own schema when php can build it (init-db.php), else the columns `pulse run` reads.
    let db = home.join("wing.db");
    let built = Command::new("php").arg(repo().join("files/anatomy/wing/bin/init-db.php")).arg(format!("--data-dir={}", home.display()))
        .output().is_ok_and(|o| o.status.success());
    let c = rusqlite::Connection::open(&db).unwrap();
    if !built {
        c.execute_batch("CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, plugin_name TEXT, job_name TEXT, runner TEXT NOT NULL DEFAULT 'subprocess',
            command TEXT NOT NULL, args_json TEXT NOT NULL DEFAULT '[]', env_json TEXT NOT NULL DEFAULT '{}', schedule TEXT NOT NULL DEFAULT '* * * * *',
            max_runtime_s INTEGER NOT NULL DEFAULT 300, paused INTEGER NOT NULL DEFAULT 0, removed_at TEXT, next_fire_at TEXT);").unwrap();
    }
    for id in ["a:plain", "b:other"] {
        let (plugin, name) = id.split_once(':').unwrap();
        c.execute("INSERT INTO pulse_jobs (id, plugin_name, job_name, command, schedule) VALUES (?1, ?2, ?3, ?4, '* * * * *')",
                  rusqlite::params![id, plugin, name, job.to_str().unwrap()]).unwrap();
    }
    drop(c);
    let seen = Arc::new(Mutex::new(Vec::new()));
    let port = wing(seen.clone());
    let medulla = std::fs::canonicalize(env!("CARGO_BIN_EXE_medulla")).unwrap();
    let _served = Served(env(&mut Command::new(&medulla), &home, port)
        .args(["thalamus", "serve", "--data-dir"]).arg(home.join("data"))
        .env("KEAP_PROXY_SHARED_SECRET", "s").env("NOS_TIER1_GROUPS", "nos-admins")
        .env("NOS_DECIDER_EXES", format!("{}:{}", medulla.display(), std::env::current_exe().unwrap().canonicalize().unwrap().display()))
        .stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap(), home.clone());
    for _ in 0..200 {
        if home.join(".nos/thalamus.sock").exists() { break }
        std::thread::sleep(Duration::from_millis(50));
    }
    let run = |args: &[&str]| env(&mut Command::new(&medulla), &home, port).args(args).output().unwrap();
    let fired = |id: &str| -> Value {
        let o = env(&mut Command::new(&medulla), &home, port).env("MEDULLA_PULSE", "1")
            .args(["pulse", "run", id, "--db", db.to_str().unwrap()]).output().unwrap();
        serde_json::from_slice(&o.stdout).unwrap_or_else(|_| panic!("{}", said(&o)))
    };
    let store = home.join("medulla/estate/pulse.paused.json");
    let file = || -> Value { serde_json::from_str(&std::fs::read_to_string(&store).unwrap()).unwrap() };

    // A decider at tier 1 pauses: the store holds who, when and why, 0600 in 0700; Wing hears the change.
    let o = run(&["pause", "a:plain", "--reason", "vendor outage"]);
    assert!(o.status.success() && said(&o).contains("recorded"), "{}", said(&o));
    let f = file();
    assert_eq!((f["a:plain"]["by"].as_str(), f["a:plain"]["reason"].as_str()), (Some("alice"), Some("vendor outage")), "{f}");
    assert!(f["a:plain"]["at"].as_str().is_some_and(|a| a.len() == 20 && a.ends_with('Z')), "{f}");
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(std::fs::metadata(&store).unwrap().permissions().mode() & 0o777, 0o600);
    assert_eq!(std::fs::metadata(store.parent().unwrap()).unwrap().permissions().mode() & 0o777, 0o700);
    let last = seen.lock().unwrap().last().cloned().unwrap();
    let (line, body) = last.split_once(' ').map(|(m, r)| r.split_once(' ').map(|(p, b)| (format!("{m} {p}"), b.to_string())).unwrap()).unwrap();
    assert_eq!(line, "POST /api/v1/admin/setting");
    let body: Value = serde_json::from_str(&body).unwrap();
    assert_eq!((body["by"].as_str(), body["key"].as_str(), &body["change"]["a:plain"]), (Some("alice"), Some("pulse.paused"), &f["a:plain"]), "{body}");
    let state: Value = serde_json::from_slice(&run(&["state", "--json"]).stdout).unwrap();
    assert_eq!(state["settings"]["pulse.paused"], f, "{state}");

    // Both schedulers hold it: the medulla's run, and Wing's due feed that Pulse and the medulla poll.
    assert!(fired("a:plain")["stderr_tail"].as_str().unwrap().starts_with("PAUSED: paused by alice"));
    assert_eq!(fired("b:other")["exit_code"], 0, "a pause of one job held another");
    if let Some(due) = php_due(&db, &home) {
        assert_eq!(due, vec!["b:other".to_string()], "Wing's due feed served a paused job");
    }
    let before = std::fs::read(&store).unwrap();
    let n = seen.lock().unwrap().len();

    // Not a listed decider (python3 here): refused.
    let py = "import socket,sys\ns=socket.socket(socket.AF_UNIX)\ns.connect(sys.argv[1])\ns.sendall(sys.argv[2].encode())\nprint(s.makefile().readline())";
    let o = Command::new("python3").args(["-c", py]).arg(home.join(".nos/thalamus.sock"))
        .arg("{\"t\":\"setting\",\"key\":\"pulse.paused\",\"value\":{\"a:plain\":null}}\n").output().unwrap();
    let v: Value = serde_json::from_slice(&o.stdout).unwrap_or_else(|_| panic!("{}", said(&o)));
    assert!(v["t"] == "refused" && v["reason"].as_str().unwrap().contains("not a listed decider"), "{v}");
    // A listed decider (this test binary): a key the genome does not name, a change that names who, a reason of two lines.
    for (line, why) in [("{\"t\":\"setting\",\"key\":\"pulse.speed\",\"value\":{\"a:plain\":null}}\n", "no setting the genome names"),
                        ("{\"t\":\"setting\",\"key\":\"pulse.paused\",\"value\":{\"a:plain\":{\"by\":\"bob\"}}}\n", "serve names who and when"),
                        ("{\"t\":\"setting\",\"key\":\"pulse.paused\",\"value\":{\"a:plain\":{\"reason\":\"a\\nb\"}}}\n", "one line")] {
        let v = raw(&home, line);
        assert!(v["t"] == "refused" && v["reason"].as_str().unwrap().contains(why), "{line}: {v}");
    }
    // Not tier 1, at the decider: refused.
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {&me: {"username": "alice", "groups": ["nos-users"]}}}).to_string()).unwrap();
    let o = run(&["unpause", "a:plain"]);
    assert!(o.status.code() == Some(1) && said(&o).contains("tier 1"), "{}", said(&o));
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {&me: {"username": "alice", "groups": ["nos-admins"]}}}).to_string()).unwrap();
    assert_eq!(std::fs::read(&store).unwrap(), before, "a refused change touched the store");
    assert_eq!(seen.lock().unwrap().len(), n, "a refusal reached Wing: {:?}", seen.lock().unwrap());

    // Unpause: the entry leaves the file, the job runs, the due feed serves it again.
    let o = run(&["unpause", "a:plain"]);
    assert!(o.status.success(), "{}", said(&o));
    assert_eq!(file(), serde_json::json!({}));
    assert_eq!(fired("a:plain")["exit_code"], 0, "an unpaused job is still held");
    if let Some(mut due) = php_due(&db, &home) {
        due.sort();
        assert_eq!(due, vec!["a:plain".to_string(), "b:other".to_string()]);
    }
}
