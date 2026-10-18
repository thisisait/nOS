//! `thalamus serve` as launchd runs it: a daemon that could not reach KEAP must not look up.

use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

#[test]
fn serve_refuses_to_start_without_the_proxy_secret() {
    let home = std::path::PathBuf::from(format!("/tmp/th-{}-nosecret", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    for secret in [None, Some("")] {
        let mut cmd = Command::new(env!("CARGO_BIN_EXE_thalamus"));
        cmd.arg("serve").env_clear().env("HOME", &home).env("NOS_REPO_ROOT", &home)
            .stdout(Stdio::null()).stderr(Stdio::piped());
        if let Some(s) = secret {
            cmd.env("KEAP_PROXY_SHARED_SECRET", s);
        }
        let mut child = cmd.spawn().unwrap();
        let t = Instant::now();
        while child.try_wait().unwrap().is_none() && t.elapsed() < Duration::from_secs(5) {
            std::thread::sleep(Duration::from_millis(50));
        }
        let Some(status) = child.try_wait().unwrap() else {
            child.kill().unwrap();
            panic!("serve kept running with secret {secret:?}: every KEAP call would be refused");
        };
        assert!(!status.success());
        let mut err = String::new();
        std::io::Read::read_to_string(&mut child.stderr.take().unwrap(), &mut err).unwrap();
        assert!(err.contains("KEAP_PROXY_SHARED_SECRET"), "{err}");
        assert!(!home.join(".nos/thalamus.sock").exists(), "no socket for a daemon that cannot serve");
    }
}

#[test]
fn serve_without_a_model_says_so_on_one_line_the_reader_parses() {
    // tools/thalamus-status.py reads the last "thalamus: model " line of launchd's stderr log.
    let home = std::path::PathBuf::from(format!("/tmp/th-{}-nomodel", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    let data = home.join("data");
    let mut child = serve_with(&home, &["--data-dir".as_ref(), data.as_os_str()]);
    let err = child.stderr.take().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for l in std::io::BufRead::lines(std::io::BufReader::new(err)).map_while(Result::ok) {
            if l.starts_with("thalamus: model ") {
                let _ = tx.send(l);
            }
        }
    });
    let got = rx.recv_timeout(Duration::from_secs(5));
    child.kill().unwrap();
    let line = got.expect("serve printed no `thalamus: model ` line");
    assert!(line.starts_with("thalamus: model UNBOUND: ") && line.contains("agent.yml"), "{line}");
}

const KEY: &str = "sk-eu-main-key-5d0a";

/// A HOME whose repo holds the real iris cell and register, and a red-status reader that
/// writes the env it inherited to <home>/child-env.json.
fn iris_home(name: &str) -> std::path::PathBuf {
    let home = std::path::PathBuf::from(format!("/tmp/th-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    let real = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../..");
    for f in ["files/anatomy/agents/iris/agent.yml", "state/habitat/llm-backends.yml"] {
        std::fs::create_dir_all(home.join(f).parent().unwrap()).unwrap();
        std::fs::copy(real.join(f), home.join(f)).unwrap();
    }
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    std::fs::create_dir_all(home.join("tools")).unwrap();
    std::fs::write(home.join("tools/red-status.py"), format!(
        "import json, os\nopen({:?}, 'w').write(json.dumps(dict(os.environ)))\n\
         print(json.dumps({{'red_count': 0, 'reds': [], 'hold_count': 0, 'holds': []}}))\n",
        home.join("child-env.json"))).unwrap();
    let me = thalamus::serve::login(unsafe { libc::getuid() }).unwrap();
    std::fs::write(home.join(".nos/identity-map.yml"),
        serde_json::json!({"logins": {me: {"username": "alice", "groups": ["nos-admins"]}}}).to_string()).unwrap();
    home
}

/// serve as the plist runs it with iris armed on mistral-eu; `key` is the plist's NOS_SECRET_ var.
fn serve_iris(home: &std::path::Path, key: Option<&str>) -> (std::process::Child, std::sync::mpsc::Receiver<String>,
                                                             std::sync::Arc<std::sync::Mutex<String>>) {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_thalamus"));
    cmd.arg("serve").arg("--data-dir").arg(home.join("data")).env_clear().env("HOME", home)
        .env("NOS_REPO_ROOT", home).env("PATH", std::env::var("PATH").unwrap()).env("KEAP_PROXY_SHARED_SECRET", "s")
        .env("NOS_ARMED_BACKENDS", "mistral-eu").env("NOS_MISTRAL_MODEL", "mistral-large-latest")
        .env("NOS_TIER1_GROUPS", "nos-admins").stdout(Stdio::null()).stderr(Stdio::piped());
    if let Some(k) = key {
        cmd.env("NOS_SECRET_MISTRAL_API_KEY", k);
    }
    let mut child = cmd.spawn().unwrap();
    let err = child.stderr.take().unwrap();
    let all = std::sync::Arc::new(std::sync::Mutex::new(String::new()));
    let (tx, rx) = std::sync::mpsc::channel();
    let sink = all.clone();
    std::thread::spawn(move || {
        for l in std::io::BufRead::lines(std::io::BufReader::new(err)).map_while(Result::ok) {
            sink.lock().unwrap().push_str(&format!("{l}\n"));
            if l.starts_with("thalamus: model ") {
                let _ = tx.send(l);
            }
        }
    });
    (child, rx, all)
}

#[test]
fn serve_binds_iris_from_the_plist_key_and_no_child_inherits_it() {
    use std::io::{BufRead, Write};
    let home = iris_home("irisbound");
    let (mut child, rx, all) = serve_iris(&home, Some(KEY));
    let line = rx.recv_timeout(Duration::from_secs(5));
    let sock = home.join(".nos/thalamus.sock");
    let t = Instant::now();
    while !sock.exists() && t.elapsed() < Duration::from_secs(5) {
        std::thread::sleep(Duration::from_millis(50));
    }
    // A control spawns a reader: it must see neither the model key nor the proxy secret.
    let answered = std::os::unix::net::UnixStream::connect(&sock).map(|mut s| {
        s.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
        let msg = nos_contract::wire::encode(&nos_contract::wire::ToThalamus::Control {
            view: nos_contract::wire::ControlView::RedStatus });
        s.write_all(msg.as_bytes()).unwrap();
        let mut r = std::io::BufReader::new(s);
        let mut l = String::new();
        for _ in 0..2 {
            l.clear();
            r.read_line(&mut l).unwrap();
        }
        l
    });
    child.kill().unwrap();
    child.wait().unwrap();
    let line = line.expect("serve printed no `thalamus: model ` line");
    assert_eq!(line, "thalamus: model bound mistral-eu-mistral-large-latest");
    let answered = answered.expect("the socket answers");
    assert!(answered.contains("red_status"), "{answered}");
    let env: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(home.join("child-env.json")).unwrap()).unwrap();
    let env = env.as_object().unwrap();
    assert!(!env.keys().any(|k| k.starts_with("NOS_SECRET_") || k == "KEAP_PROXY_SHARED_SECRET"), "{:?}", env.keys());
    assert!(!env.values().any(|v| v.as_str().unwrap_or("").contains(KEY)), "a child inherited the key");
    assert!(!all.lock().unwrap().contains(KEY), "the key reached the log");
    let _ = std::fs::remove_dir_all(&home);
}

const RELAY: &str = "relay-main-secret-77b3";

/// T10 + T7 (row thalamus-web-relay): the relay door is bound only with a secret, on loopback,
/// said on one `thalamus: relay ` line; the secret is read once, so no child and no log has it.
#[test]
fn serve_binds_the_relay_only_with_a_secret_and_no_child_inherits_it() {
    use std::io::{BufRead, Write};
    // The free port is closed before serve binds it, so a parallel test can take it in between:
    // a relay FAILED line, or a door some other listener answers, retries on a fresh port.
    for secret in [None, Some(""), Some(RELAY)] { for attempt in 0..5 {
        let home = iris_home(&format!("relay{}", secret.map_or(0, str::len)));
        let port = std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let mut cmd = Command::new(env!("CARGO_BIN_EXE_thalamus"));
        cmd.arg("serve").arg("--data-dir").arg(home.join("data")).env_clear().env("HOME", &home)
            .env("NOS_REPO_ROOT", &home).env("PATH", std::env::var("PATH").unwrap()).env("KEAP_PROXY_SHARED_SECRET", "s")
            .env("NOS_TIER1_GROUPS", "nos-admins").env("THALAMUS_RELAY_PORT", port.to_string())
            .stdout(Stdio::null()).stderr(Stdio::piped());
        if let Some(s) = secret {
            cmd.env("THALAMUS_RELAY_SECRET", s);
        }
        let mut child = cmd.spawn().unwrap();
        let err = child.stderr.take().unwrap();
        let all = std::sync::Arc::new(std::sync::Mutex::new(String::new()));
        let (tx, rx) = std::sync::mpsc::channel();
        let sink = all.clone();
        std::thread::spawn(move || {
            for l in std::io::BufReader::new(err).lines().map_while(Result::ok) {
                sink.lock().unwrap().push_str(&format!("{l}\n"));
                if l.starts_with("thalamus: relay ") {
                    let _ = tx.send(l);
                }
            }
        });
        let line = rx.recv_timeout(Duration::from_secs(5));
        let door = std::net::TcpStream::connect(("127.0.0.1", port));
        // A control spawns a reader: it must not see the relay secret.
        let sock = home.join(".nos/thalamus.sock");
        let answered = std::os::unix::net::UnixStream::connect(&sock).map(|mut s| {
            s.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
            s.write_all(nos_contract::wire::encode(&nos_contract::wire::ToThalamus::Control {
                view: nos_contract::wire::ControlView::RedStatus }).as_bytes()).unwrap();
            let mut r = std::io::BufReader::new(s);
            let mut l = String::new();
            for _ in 0..2 {
                l.clear();
                r.read_line(&mut l).unwrap();
            }
            l
        });
        child.kill().unwrap();
        child.wait().unwrap();
        let line = line.unwrap_or_else(|_| panic!("serve printed no `thalamus: relay ` line with secret {secret:?}"));
        let raced = if secret == Some(RELAY) { line.starts_with("thalamus: relay FAILED") } else { door.is_ok() };
        if raced && attempt < 4 {
            let _ = std::fs::remove_dir_all(&home);
            continue;
        }
        if secret == Some(RELAY) {
            assert_eq!(line, format!("thalamus: relay bound 127.0.0.1:{port}"));
            assert!(door.is_ok(), "the relay is not accepting");
        } else {
            assert!(line.starts_with("thalamus: relay closed"), "{line}");
            assert!(door.is_err(), "a relay with secret {secret:?} accepted a connection");
        }
        assert!(answered.expect("the socket answers").contains("red_status"));
        let env: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(home.join("child-env.json")).unwrap()).unwrap();
        let env = env.as_object().unwrap();
        assert!(!env.contains_key("THALAMUS_RELAY_SECRET"), "a child inherited the relay secret var");
        assert!(!env.values().any(|v| v.as_str().unwrap_or("").contains(RELAY)), "a child inherited the relay secret");
        assert!(!all.lock().unwrap().contains(RELAY), "the relay secret reached the log");
        let _ = std::fs::remove_dir_all(&home);
        break;
    } }
}

#[test]
fn serve_without_the_key_says_which_var_on_the_model_line() {
    let home = iris_home("irisnokey");
    let (mut child, rx, _) = serve_iris(&home, None);
    let line = rx.recv_timeout(Duration::from_secs(5));
    child.kill().unwrap();
    child.wait().unwrap();
    let line = line.expect("serve printed no `thalamus: model ` line");
    assert!(line.starts_with("thalamus: model UNBOUND: ") && line.contains("mistral_api_key")
            && line.contains("credentials.yml"), "{line}");
    let _ = std::fs::remove_dir_all(&home);
}

fn serve_with(home: &std::path::Path, args: &[&std::ffi::OsStr]) -> std::process::Child {
    Command::new(env!("CARGO_BIN_EXE_thalamus"))
        .arg("serve").args(args).env_clear().env("HOME", home).env("NOS_REPO_ROOT", home)
        .env("KEAP_PROXY_SHARED_SECRET", "s").stdout(Stdio::null()).stderr(Stdio::piped())
        .spawn().unwrap()
}

#[test]
fn serve_refuses_to_guess_a_data_dir() {
    // No home-relative default: the ledger lives where the role (nos_data_root) says, or nowhere.
    let home = std::path::PathBuf::from(format!("/tmp/th-{}-nodata", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    let mut child = serve_with(&home, &[]);
    let t = Instant::now();
    while child.try_wait().unwrap().is_none() && t.elapsed() < Duration::from_secs(5) {
        std::thread::sleep(Duration::from_millis(50));
    }
    let Some(status) = child.try_wait().unwrap() else {
        child.kill().unwrap();
        panic!("serve ran without --data-dir");
    };
    assert!(!status.success());
    let mut err = String::new();
    std::io::Read::read_to_string(&mut child.stderr.take().unwrap(), &mut err).unwrap();
    assert!(err.contains("--data-dir"), "{err}");
    assert!(!home.join("thalamus").exists(), "no ledger dir under HOME");
    assert!(!home.join(".nos/thalamus.sock").exists(), "no socket for a daemon with no ledger");
}

#[test]
fn serve_opens_the_ledger_in_the_given_dir_and_tightens_it_to_0700() {
    use std::os::unix::fs::PermissionsExt;
    let home = std::path::PathBuf::from(format!("/tmp/th-{}-data", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".nos")).unwrap();
    let data = home.join("nos/platform/services/thalamus/data");
    std::fs::create_dir_all(&data).unwrap();
    std::fs::set_permissions(&data, std::fs::Permissions::from_mode(0o755)).unwrap();
    let mut child = serve_with(&home, &["--data-dir".as_ref(), data.as_os_str()]);
    let t = Instant::now();
    while !home.join(".nos/thalamus.sock").exists() && t.elapsed() < Duration::from_secs(5) {
        if child.try_wait().unwrap().is_some() {
            let mut err = String::new();
            std::io::Read::read_to_string(&mut child.stderr.take().unwrap(), &mut err).unwrap();
            panic!("serve exited: {err}");
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    child.kill().unwrap();
    child.wait().unwrap();
    assert!(data.join("ledger.db").exists(), "the ledger opens in --data-dir");
    assert_eq!(std::fs::metadata(&data).unwrap().permissions().mode() & 0o777, 0o700,
               "a pre-existing wider data dir is tightened, not trusted");
    assert!(!home.join("thalamus").exists(), "nothing under the old ~/thalamus/data");
    let _ = std::fs::remove_dir_all(&home);
}
