//! A copy of the medulla named `nos-<organ>` is `medulla <organ>`: the process shows the organ's name
//! (tests/anatomy/test_a_host_job_runs_under_its_organ_name.py), the CLI behind it is unchanged.
use std::path::{Path, PathBuf};
use std::process::Command;

fn named(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("medulla-names-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let to = dir.join(name);
    std::fs::copy(env!("CARGO_BIN_EXE_medulla"), &to).unwrap();
    to
}

fn run(exe: &Path, args: &[&str]) -> (Option<i32>, String, String) {
    let out = Command::new(exe).args(args).output().unwrap();
    (out.status.code(), String::from_utf8_lossy(&out.stdout).into_owned(), String::from_utf8_lossy(&out.stderr).into_owned())
}

#[test]
fn nos_pulse_is_medulla_pulse() {
    let db = std::env::temp_dir().join("medulla-names-no-such.db");
    let db = db.to_str().unwrap();
    let by_name = run(&named("nos-pulse"), &["plan", "--db", db]);
    let by_arg = run(Path::new(env!("CARGO_BIN_EXE_medulla")), &["pulse", "plan", "--db", db]);
    assert!(by_name.2.starts_with("medulla pulse"), "{by_name:?}");
    assert_eq!(by_name, by_arg);
}

#[test]
fn nos_medulla_is_the_medulla_and_an_unknown_name_falls_through() {
    assert!(run(&named("nos-medulla"), &["--version"]).1.starts_with("medulla "));
    let (code, _, err) = run(&named("nos-wing"), &[]);
    assert_eq!(code, Some(2), "nos-wing with no args is `medulla wing`'s usage: {err}");
    assert_eq!(run(&named("nos-nothing"), &["plan"]).0, Some(2));
}
