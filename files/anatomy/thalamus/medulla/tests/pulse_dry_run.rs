//! `medulla pulse tick --dry-run` over a scratch wing.db: each due job gets the verdict the Python
//! daemon would reach, in its order (cap, in flight, runner, halt, loops pause, allowlist), and the
//! db is byte-for-byte unchanged afterwards (row medulla-scheduler, increment b; the medulla does not write).
use std::path::{Path, PathBuf};
use std::process::Command;

const NOW: i64 = 1_792_060_397; // 2026-10-15T10:33:17Z

fn scratch(tag: &str) -> (PathBuf, PathBuf) {
    let dir = std::env::temp_dir().join(format!("medulla-tick-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let db = dir.join("wing.db");
    let c = rusqlite::Connection::open(&db).unwrap();
    // The columns the tick reads, as files/anatomy/wing/bin/init-db.php declares them.
    c.execute_batch(
        "CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, runner TEXT NOT NULL DEFAULT 'subprocess', command TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '[]', schedule TEXT NOT NULL, jitter_min INTEGER NOT NULL DEFAULT 0,
            paused INTEGER NOT NULL DEFAULT 0, next_fire_at TEXT, removed_at TEXT);
         CREATE TABLE pulse_runs (run_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, fired_at TEXT NOT NULL, finished_at TEXT);
         INSERT INTO pulse_jobs (id, runner, command, schedule, jitter_min, paused, next_fire_at, removed_at) VALUES
           ('a:fires',    'subprocess', '/r/tools/a.py',   '*/15 * * * *', 2, 0, '2026-10-15T10:30:00+00:00', NULL),
           ('b:busy',     'subprocess', '/r/tools/b.py',   '0 * * * *',    0, 0, '2026-10-15T10:00:00+00:00', NULL),
           ('c:agent',    'agent',      '/r/tools/c.py',   '0 * * * *',    0, 0, '2026-10-15T10:01:00+00:00', NULL),
           ('d:planted',  'subprocess', '/tmp/x.py',       '0 * * * *',    0, 0, '2026-10-15T10:02:00+00:00', NULL),
           ('loop:check', 'subprocess', '/r/tools/l.py',   '0 * * * *',    0, 0, '2026-10-15T10:03:00+00:00', NULL),
           ('e:paused',   'subprocess', '/r/tools/e.py',   '0 * * * *',    0, 1, '2026-10-15T09:00:00+00:00', NULL),
           ('f:removed',  'subprocess', '/r/tools/f.py',   '0 * * * *',    0, 0, '2026-10-15T09:00:00+00:00', '2026-10-01'),
           ('g:later',    'subprocess', '/r/tools/g.py',   '0 * * * *',    0, 0, '2026-10-15T11:00:00+00:00', NULL);
         INSERT INTO pulse_runs VALUES ('r1', 'b:busy', '2026-10-15T10:00:01+00:00', NULL),
                                       ('r2', 'a:fires', '2026-10-15T08:00:00+00:00', NULL);",
    )
    .unwrap();
    (dir, db)
}

/// job -> verdict; the cap is passed so the test can push jobs past it.
fn tick(dir: &Path, db: &Path, cap: &str, halt: bool, loops: bool) -> Vec<(String, String)> {
    let touch = |name: &str, on: bool| {
        let p = dir.join(name);
        if on { std::fs::write(&p, "{}").unwrap() } else { let _ = std::fs::remove_file(&p); }
        p
    };
    let out = Command::new(env!("CARGO_BIN_EXE_medulla"))
        .args(["pulse", "tick", "--dry-run", "--db", db.to_str().unwrap(), "--now", &NOW.to_string()])
        .env("NOS_HALT_FILE", touch("halt", halt))
        .env("NOS_LOOPS_PAUSED_FILE", touch("loops-paused", loops))
        .env("NOS_REPO_ROOT", "/r")
        .env("HOME", dir)
        .env("PULSE_MAX_CONCURRENT", cap)
        .output()
        .unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    String::from_utf8(out.stdout).unwrap().lines().map(|l| {
        let v: serde_json::Value = serde_json::from_str(l).unwrap();
        (v["job"].as_str().unwrap().to_string(), v["verdict"].as_str().unwrap().to_string())
    }).collect()
}

fn verdict<'a>(v: &'a [(String, String)], job: &str) -> &'a str {
    v.iter().find(|(j, _)| j == job).map(|(_, x)| x.as_str()).unwrap_or("not due")
}

#[test]
fn each_due_job_gets_the_daemons_verdict() {
    let (dir, db) = scratch("verdicts");
    let before = std::fs::read(&db).unwrap();
    let v = tick(&dir, &db, "8", false, true);
    assert_eq!(verdict(&v, "a:fires"), "would fire", "a run open since 08:00 is past the 3600 s ceiling");
    assert_eq!(verdict(&v, "b:busy"), "skipped: already in flight");
    assert_eq!(verdict(&v, "c:agent"), "skipped: runner agent");
    assert!(verdict(&v, "d:planted").starts_with("refused (exit 126)"), "{v:?}");
    assert_eq!(verdict(&v, "loop:check"), "held (exit 3): loops paused");
    for gone in ["e:paused", "f:removed", "g:later"] {
        assert_eq!(verdict(&v, gone), "not due", "{gone}");
    }
    assert_eq!(std::fs::read(&db).unwrap(), before, "a dry run changed wing.db");
}

#[test]
fn the_halt_holds_every_job_and_the_cap_defers() {
    let (dir, db) = scratch("halt");
    let v = tick(&dir, &db, "8", true, false);
    assert_eq!(verdict(&v, "a:fires"), "held (exit 3): emergency halt");
    assert_eq!(verdict(&v, "loop:check"), "held (exit 3): emergency halt");
    // cap 2, one run in flight: one slot, given in next_fire_at order (b:busy first, skipped).
    let v = tick(&dir, &db, "2", false, false);
    assert_eq!(v[0], ("b:busy".into(), "skipped: already in flight".into()));
    assert!(v[1..].iter().all(|(_, x)| x == "deferred: concurrency cap"), "{v:?}");
}
