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
    let mut child = Command::new(env!("CARGO_BIN_EXE_thalamus"))
        .arg("serve").env_clear().env("HOME", &home).env("NOS_REPO_ROOT", &home).env("KEAP_PROXY_SHARED_SECRET", "x")
        .stdout(Stdio::null()).stderr(Stdio::piped()).spawn().unwrap();
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
