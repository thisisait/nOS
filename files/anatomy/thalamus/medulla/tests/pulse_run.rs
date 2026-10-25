//! `medulla pulse run <job>` over a scratch wing.db and a scratch repo: off unless MEDULLA_PULSE=1,
//! a held or secret-bearing job never starts, a run's output is scrubbed and carries its run id, and
//! wing.db is unchanged (row medulla-scheduler, increment c; the medulla does not write the record).
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

struct Scratch(PathBuf);

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn scratch(tag: &str) -> Scratch {
    use std::os::unix::fs::PermissionsExt;
    let dir = std::env::temp_dir().join(format!("medulla-run-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("repo/tools")).unwrap();
    let script = dir.join("repo/tools/job.sh");
    // Leaves a mark (so a refusal can prove nothing ran), prints its run id and a fake secret.
    std::fs::write(&script, "#!/bin/sh\ntouch \"$MARK\"\necho \"run=$PULSE_RUN_ID\"\necho \"MY_TOKEN=fakefakefake123\" >&2\nexit 4\n").unwrap();
    std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
    let c = rusqlite::Connection::open(dir.join("wing.db")).unwrap();
    let cmd = script.to_str().unwrap();
    let mark = dir.join("ran").to_str().unwrap().to_string();
    c.execute_batch(&format!(
        "CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, runner TEXT NOT NULL DEFAULT 'subprocess', command TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '[]', env_json TEXT NOT NULL DEFAULT '{{}}', max_runtime_s INTEGER NOT NULL DEFAULT 300,
            removed_at TEXT);
         INSERT INTO pulse_jobs (id, command, env_json) VALUES
           ('a:plain', '{cmd}', '{{\"MARK\": \"{mark}\"}}'),
           ('loop:x',  '{cmd}', '{{\"MARK\": \"{mark}\"}}'),
           ('b:secret', '{cmd}', '{{\"MARK\": \"{mark}\", \"WING_API_TOKEN\": \"secret:wing_api_token\"}}');"
    ))
    .unwrap();
    Scratch(dir)
}

fn run(s: &Path, job: &str, armed: bool, halt: bool, loops: bool) -> Output {
    for (name, on) in [("halt", halt), ("loops-paused", loops)] {
        if on { std::fs::write(s.join(name), "{}").unwrap() } else { let _ = std::fs::remove_file(s.join(name)); }
    }
    let mut c = Command::new(env!("CARGO_BIN_EXE_medulla"));
    c.args(["pulse", "run", job, "--db", s.join("wing.db").to_str().unwrap()])
        .env("HOME", s)
        .env("NOS_REPO_ROOT", s.join("repo"))
        .env("NOS_HALT_FILE", s.join("halt"))
        .env("NOS_LOOPS_PAUSED_FILE", s.join("loops-paused"))
        // The job declares MARK; it reaches the child only because the env allow-list lets declared keys through.
        .env_remove("MEDULLA_PULSE");
    if armed {
        c.env("MEDULLA_PULSE", "1");
    }
    c.output().unwrap()
}

fn json(o: &Output) -> serde_json::Value {
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    serde_json::from_slice(&o.stdout).unwrap()
}

#[test]
fn it_is_off_unless_armed() {
    let s = scratch("off");
    let o = run(&s.0, "a:plain", false, false, false);
    assert_eq!(o.status.code(), Some(2));
    assert!(!s.0.join("ran").exists(), "an unarmed medulla ran a job");
}

#[test]
fn a_run_is_scrubbed_and_carries_its_id() {
    let s = scratch("fire");
    let before = std::fs::read(s.0.join("wing.db")).unwrap();
    let v = json(&run(&s.0, "a:plain", true, false, false));
    assert_eq!(v["exit_code"], 4, "{v}");
    assert_eq!(v["actor_id"], "medulla");
    let id = v["run_id"].as_str().unwrap();
    assert_eq!(v["stdout_tail"].as_str().unwrap().trim(), format!("run={id}"), "PULSE_RUN_ID is the run id");
    let err = v["stderr_tail"].as_str().unwrap();
    assert!(!err.contains("fakefakefake123") && err.contains("MY_TOKEN="), "not scrubbed: {err}");
    assert_eq!(std::fs::read(s.0.join("wing.db")).unwrap(), before, "a run changed wing.db");
}

#[test]
fn a_held_or_secret_job_never_starts() {
    let s = scratch("hold");
    let v = json(&run(&s.0, "a:plain", true, true, false));
    assert_eq!(v["exit_code"], 3);
    assert!(v["stderr_tail"].as_str().unwrap().starts_with("PAUSED: emergency halt"), "{v}");
    let v = json(&run(&s.0, "loop:x", true, false, true));
    assert!(v["stderr_tail"].as_str().unwrap().starts_with("PAUSED: loops paused"), "{v}");
    let o = run(&s.0, "b:secret", true, false, false);
    assert!(!o.status.success() && String::from_utf8_lossy(&o.stderr).contains("secret:"));
    assert!(!s.0.join("ran").exists(), "a held or secret-bearing job ran");
}
