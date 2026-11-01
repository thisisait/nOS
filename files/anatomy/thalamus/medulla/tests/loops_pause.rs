//! The joint of the setting loops.paused (state/genome/settings.yml): a tier-1 decider pauses the loops
//! over the socket, serve writes NOS_LOOPS_PAUSED_FILE in the since:/reason: lines `nos loops pause` writes,
//! `medulla state` and `nos loops status` read it as PAUSED, Wing is sent the change, and lifting it
//! deletes the file. A peer that is not a listed decider is refused with the file untouched, on both OSes.
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
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

/// One line on the socket from `exe` (python3 here, so the peer is python3, not this test binary).
fn send(home: &Path, line: &str) -> Value {
    let py = "import socket,sys\ns=socket.socket(socket.AF_UNIX)\ns.connect(sys.argv[1])\ns.sendall(sys.argv[2].encode())\nprint(s.makefile().readline())";
    let o = Command::new("python3").args(["-c", py]).arg(home.join(".nos/thalamus.sock")).arg(line).output().unwrap();
    serde_json::from_slice(&o.stdout).unwrap_or_else(|_| panic!("{}", said(&o)))
}

/// A thalamus serve over a tempdir HOME, alice at tier 1, the listed deciders `deciders`.
fn serve(tag: &str, deciders: &str, port: u16) -> (PathBuf, Served) {
    let home = PathBuf::from(format!("/tmp/md-lp-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    let me = thalamus::serve::login(unsafe { libc::getuid() }).unwrap();
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {&me: {"username": "alice", "groups": ["nos-admins"]}}}).to_string()).unwrap();
    std::fs::write(home.join(".nos/secrets.yml"), format!("wing_halt_token: \"{}\"\n", "h".repeat(64))).unwrap();
    let served = Served(env(&mut Command::new(env!("CARGO_BIN_EXE_medulla")), &home, port)
        .args(["thalamus", "serve", "--data-dir"]).arg(home.join("data"))
        .env("KEAP_PROXY_SHARED_SECRET", "s").env("NOS_TIER1_GROUPS", "nos-admins").env("NOS_DECIDER_EXES", deciders)
        .stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap(), home.clone());
    for _ in 0..200 {
        if home.join(".nos/thalamus.sock").exists() { break }
        std::thread::sleep(Duration::from_millis(50));
    }
    (home, served)
}

#[test]
fn a_peer_that_is_no_decider_does_not_lift_a_pause() {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let port = wing(seen.clone());
    let me = std::fs::canonicalize(env!("CARGO_BIN_EXE_medulla")).unwrap();
    let (home, _served) = serve("refuse", me.to_str().unwrap(), port);
    let file = home.join("loops-paused");
    std::fs::write(&file, "since: 2026-11-01T08:00:00Z\nreason: drill\n").unwrap();
    let (bytes, mtime) = (std::fs::read(&file).unwrap(), std::fs::metadata(&file).unwrap().modified().unwrap());
    for line in ["{\"t\":\"setting\",\"key\":\"loops.paused\",\"value\":null}\n",
                 "{\"t\":\"setting\",\"key\":\"loops.paused\",\"value\":{\"reason\":\"mine\"}}\n"] {
        let v = send(&home, line);
        assert_eq!(v["t"], "refused", "{line}: {v}");
    }
    assert_eq!((std::fs::read(&file).unwrap(), std::fs::metadata(&file).unwrap().modified().unwrap()), (bytes, mtime),
               "a refused peer touched the pause");
    assert!(seen.lock().unwrap().is_empty(), "a refusal reached Wing: {:?}", seen.lock().unwrap());
}

#[cfg(target_os = "macos")]
#[test]
fn a_decider_pauses_the_loops_and_nos_reads_it_as_paused() {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let port = wing(seen.clone());
    let me = std::fs::canonicalize(env!("CARGO_BIN_EXE_medulla")).unwrap();
    let test = std::env::current_exe().unwrap().canonicalize().unwrap();
    let (home, _served) = serve("set", &format!("{}:{}", me.display(), test.display()), port);
    let file = home.join("loops-paused");
    // This test binary is a listed decider here and sends the line itself.
    let raw = |line: &str| -> Value {
        let mut s = std::os::unix::net::UnixStream::connect(home.join(".nos/thalamus.sock")).unwrap();
        s.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
        s.write_all(line.as_bytes()).unwrap();
        let mut back = String::new();
        BufReader::new(s).read_line(&mut back).unwrap();
        serde_json::from_str(&back).unwrap()
    };

    // A reason with a control character could forge a line of the pause file: refused, nothing written.
    let v = raw("{\"t\":\"setting\",\"key\":\"loops.paused\",\"value\":{\"reason\":\"a\\rb\"}}\n");
    assert!(v["t"] == "refused" && v["reason"].as_str().unwrap().contains("one line") && !file.exists(), "{v}");
    let v = raw("{\"t\":\"setting\",\"key\":\"loops.paused\",\"value\":{\"reason\":\"upgrade drill\"}}\n");
    assert_eq!(v["t"], "state", "{v}");
    let text = std::fs::read_to_string(&file).unwrap();
    let since = text.lines().find_map(|l| l.strip_prefix("since: ")).unwrap_or_else(|| panic!("{text}")).to_string();
    assert!(since.len() == 20 && since.ends_with('Z'), "{text}");
    assert_eq!(text, format!("since: {since}\nreason: upgrade drill\n"), "not the lines tools/nos writes");
    let state: Value = serde_json::from_slice(&env(&mut Command::new(&me), &home, port).args(["state", "--json"]).output().unwrap().stdout).unwrap();
    let lp = &state["loops_paused"];
    assert_eq!((&lp["on"], lp["reason"].as_str(), lp["since"].as_str()), (&Value::Bool(true), Some("upgrade drill"), Some(&*since)), "{state}");
    let posts = seen.lock().unwrap().clone();
    assert_eq!(posts.len(), 1, "{posts:?}");
    let (line, body) = posts[0].split_once(' ').map(|(m, r)| r.split_once(' ').map(|(p, b)| (format!("{m} {p}"), b.to_string())).unwrap()).unwrap();
    assert_eq!(line, "POST /api/v1/admin/setting");
    let body: Value = serde_json::from_str(&body).unwrap();
    assert_eq!((body["by"].as_str(), body["key"].as_str()), (Some("alice"), Some("loops.paused")), "{body}");

    // Format parity: the shell's reader reads the medulla's file as a pause.
    let o = env(&mut Command::new("bash"), &home, port).arg(repo().join("tools/nos")).args(["loops", "status"]).output().unwrap();
    assert!(o.status.success() && said(&o).contains("loops: PAUSED") && said(&o).contains("reason: upgrade drill"), "{}", said(&o));

    // Lift: the file goes; lifting a pause that is not there is done.
    for _ in 0..2 {
        let v = raw("{\"t\":\"setting\",\"key\":\"loops.paused\",\"value\":null}\n");
        assert_eq!(v["t"], "state", "{v}");
        assert!(!file.exists());
    }
    assert_eq!(seen.lock().unwrap().len(), 3);
}
