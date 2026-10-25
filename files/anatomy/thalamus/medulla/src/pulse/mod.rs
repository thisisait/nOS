//! The Pulse schedule in the medulla (row medulla-scheduler, increments a-b): it reads and plans, it
//! does not fire and does not write (the db opens read-only). `plan` prints one JSON line per live
//! job: Wing's next_fire_at beside the medulla's, and the allowlist verdict. `tick --dry-run` prints
//! what one Pulse tick would do with each due job, in the Python daemon's order of checks.
pub mod allow;
pub mod cron;
#[allow(dead_code)] // the fire path (next commit) is its first caller
pub mod redact;

use std::process::ExitCode;

/// PHP's date('c') in UTC: 2026-10-25T10:33:00+00:00.
pub fn iso(t: i64) -> String {
    let d = time::OffsetDateTime::from_unix_timestamp(t).expect("epoch in range");
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}+00:00", d.year(), u8::from(d.month()), d.day(), d.hour(), d.minute(), d.second())
}

pub fn plan(db: &str, now: i64) -> Result<(), String> {
    let conn = open(db)?;
    let mut q = conn
        .prepare("SELECT id, schedule, command, args_json, next_fire_at FROM pulse_jobs WHERE removed_at IS NULL ORDER BY id")
        .map_err(|e| e.to_string())?;
    let rows = q
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?, r.get::<_, Option<String>>(4)?)))
        .map_err(|e| e.to_string())?;
    let (home, repo) = (std::env::var("HOME").ok(), std::env::var("NOS_REPO_ROOT").ok());
    for row in rows {
        let (id, schedule, command, args, wing_next) = row.map_err(|e| e.to_string())?;
        let next = cron::Cron::parse(&schedule).and_then(|c| c.next_after(now).ok_or("no match within 5 years".into()));
        let args: Vec<String> = serde_json::from_str(&args).unwrap_or_default();
        let verdict = allow::validate(&command, &args, home.as_deref(), repo.as_deref());
        println!("{}", serde_json::json!({
            "job": id, "schedule": schedule, "wing_next": wing_next,
            "next": next.as_ref().map(|t| iso(*t)).ok(), "cron_error": next.err(),
            "allowed": verdict.is_ok(), "refused": verdict.err(),
        }));
    }
    Ok(())
}

fn open(db: &str) -> Result<rusqlite::Connection, String> {
    rusqlite::Connection::open_with_flags(db, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|e| e.to_string())
}

/// One tick, judged not fired. Mirrors pulse/daemon.py: tick() takes due[:free_slots], _dispatch()
/// skips a job in flight or a runner it lacks, the run thread holds on ~/.nos/halt and on
/// ~/.nos/loops-paused for loop:*, the runner refuses outside the allowlist (126). In flight here is
/// a pulse_runs row not finished, fired within the 3600 s run ceiling (the daemon's is in memory).
/// Not judged: secret:<name> resolution (rc 255) — the medulla never reads secrets.yml.
pub fn tick(db: &str, now: i64, cap: usize) -> Result<(), String> {
    let conn = open(db)?;
    let q = |sql: &str| conn.prepare(sql).map_err(|e| e.to_string());
    let since = iso(now - 3600);
    let busy: Vec<String> = q("SELECT DISTINCT job_id FROM pulse_runs WHERE finished_at IS NULL AND fired_at >= ?1")?
        .query_map([&since], |r| r.get(0)).map_err(|e| e.to_string())?.collect::<Result<_, _>>().map_err(|e| e.to_string())?;
    let mut due = q("SELECT id, runner, command, args_json, schedule, jitter_min FROM pulse_jobs WHERE paused = 0 AND removed_at IS NULL \
                     AND (next_fire_at IS NULL OR next_fire_at <= ?1) ORDER BY next_fire_at LIMIT 50")?;
    let rows = due
        .query_map([iso(now)], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?, r.get::<_, String>(4)?, r.get::<_, i64>(5)?)))
        .map_err(|e| e.to_string())?;
    let free = cap.saturating_sub(busy.len());
    let halt = crate::metrics::halt_file();
    let loops = std::env::var_os("NOS_LOOPS_PAUSED_FILE").map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".nos/loops-paused"));
    let (home, repo) = (std::env::var("HOME").ok(), std::env::var("NOS_REPO_ROOT").ok());
    for (i, row) in rows.enumerate() {
        let (id, runner, command, args, schedule, jitter) = row.map_err(|e| e.to_string())?;
        let args: Vec<String> = serde_json::from_str(&args).unwrap_or_default();
        let verdict = if i >= free {
            "deferred: concurrency cap".to_string()
        } else if busy.contains(&id) {
            "skipped: already in flight".to_string()
        } else if runner != "subprocess" {
            format!("skipped: runner {runner}")
        } else if halt.is_file() {
            "held (exit 3): emergency halt".to_string()
        } else if id.starts_with("loop:") && loops.is_file() {
            "held (exit 3): loops paused".to_string()
        } else {
            match allow::validate(&command, &args, home.as_deref(), repo.as_deref()) {
                Ok(()) => "would fire".to_string(),
                Err(e) => format!("refused (exit 126): {e}"),
            }
        };
        let next = cron::Cron::parse(&schedule).ok().and_then(|c| c.next_after(now)).map(iso);
        println!("{}", serde_json::json!({"job": id, "verdict": verdict, "next": next, "jitter_max_min": jitter}));
    }
    Ok(())
}

pub fn cli(args: &[String]) -> ExitCode {
    let flag = |f: &str| args.iter().position(|a| a == f).and_then(|i| args.get(i + 1));
    let now = flag("--now").and_then(|n| n.parse().ok()).unwrap_or_else(|| time::OffsetDateTime::now_utc().unix_timestamp());
    match (args.first().map(String::as_str), flag("--db")) {
        (Some("plan"), Some(db)) => match plan(db, now) {
            Ok(()) => ExitCode::SUCCESS,
            Err(e) => {
                eprintln!("medulla pulse: {e}");
                ExitCode::FAILURE
            }
        },
        (Some("tick"), Some(db)) if args.iter().any(|a| a == "--dry-run") => {
            let cap = std::env::var("PULSE_MAX_CONCURRENT").ok().and_then(|c| c.parse().ok()).unwrap_or(4);
            match tick(db, now, cap) {
                Ok(()) => ExitCode::SUCCESS,
                Err(e) => {
                    eprintln!("medulla pulse: {e}");
                    ExitCode::FAILURE
                }
            }
        }
        _ => {
            eprintln!("usage: medulla pulse plan|tick --dry-run --db <wing.db> [--now <epoch>]  (it never fires: no tick without --dry-run yet)");
            ExitCode::from(2)
        }
    }
}
