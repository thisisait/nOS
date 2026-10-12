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
