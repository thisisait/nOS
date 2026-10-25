//! The Pulse schedule in the medulla (row medulla-scheduler, increments a-c). It never writes: the db
//! opens read-only. `plan`: Wing's next_fire_at beside the medulla's, and the allowlist verdict, per
//! job. `tick --dry-run`: what one Pulse tick would do with each due job. `run <job>`: fires that one
//! job as the daemon would, only with MEDULLA_PULSE=1, and prints the result; no nerve carries it yet.
pub mod allow;
pub mod cron;
pub mod env;
pub mod exec;
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

/// daemon.py::paused_hold: every job while ~/.nos/halt exists, loop:* while ~/.nos/loops-paused does.
fn hold(job: &str) -> Option<&'static str> {
    let home = std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    let loops = std::env::var_os("NOS_LOOPS_PAUSED_FILE").map(std::path::PathBuf::from).unwrap_or(home.join(".nos/loops-paused"));
    if crate::metrics::halt_file().is_file() {
        Some("emergency halt")
    } else if job.starts_with("loop:") && loops.is_file() {
        Some("loops paused")
    } else {
        None
    }
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
        } else if let Some(why) = hold(&id) {
            format!("held (exit 3): {why}")
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

/// A uuid4 from the kernel's random source: run_id, PULSE_RUN_ID and the trace id are one key (daemon.py).
fn uuid4() -> Result<String, String> {
    let mut b = [0u8; 16];
    std::io::Read::read_exact(&mut std::fs::File::open("/dev/urandom").map_err(|e| e.to_string())?, &mut b).map_err(|e| e.to_string())?;
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    let h: String = b.iter().map(|x| format!("{x:02x}")).collect();
    Ok(format!("{}-{}-{}-{}-{}", &h[..8], &h[8..12], &h[12..16], &h[16..20], &h[20..]))
}

/// One job, fired as daemon.py::_run_in_thread does: hold, child env, run, scrub, tails.
/// Refused before anything runs: a runner other than subprocess, and any `secret:` value —
/// the medulla does not read secrets.yml (row secrets-at-rest decides how it will).
pub fn run(db: &str, job: &str) -> Result<serde_json::Value, String> {
    let conn = open(db)?;
    let (runner, command, args, env, max_s): (String, String, String, String, i64) = conn
        .query_row("SELECT runner, command, args_json, env_json, max_runtime_s FROM pulse_jobs WHERE id = ?1 AND removed_at IS NULL",
                   [job], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)))
        .map_err(|e| format!("{job}: {e}"))?;
    if runner != "subprocess" {
        return Err(format!("{job}: runner {runner} is not the medulla's"));
    }
    let args: Vec<String> = serde_json::from_str(&args).map_err(|e| format!("{job}: args_json {e}"))?;
    let env: serde_json::Map<String, serde_json::Value> = serde_json::from_str(&env).map_err(|e| format!("{job}: env_json {e}"))?;
    let mut job_env: Vec<(String, String)> = env.into_iter().map(|(k, v)| (k, v.as_str().unwrap_or_default().to_string())).collect();
    if let Some((k, _)) = job_env.iter().find(|(_, v)| v.starts_with("secret:")) {
        return Err(format!("{job}: {k} is a secret: reference; the medulla does not resolve secrets yet"));
    }
    let run_id = uuid4()?;
    for (k, v) in [("PULSE_RUN_ID", run_id.clone()), ("TRACEPARENT", format!("00-{}-{}-01", run_id.replace('-', ""), &uuid4()?.replace('-', "")[..16]))] {
        if !job_env.iter().any(|(j, _)| j == k) {
            job_env.push((k.to_string(), v)); // setdefault: a job's own value wins
        }
    }
    let r = match hold(job) {
        Some(why) => exec::RunResult { exit_code: 3, duration_ms: 0, stdout_tail: String::new(), timed_out: false,
                                       stderr_tail: format!("PAUSED: {why} — {job} held") },
        None => {
            // Not UTF-8 = not passed: std::env::vars() would panic where Python's os.environ escapes.
            let inherited: Vec<(String, String)> = std::env::vars_os().filter_map(|(k, v)| Some((k.into_string().ok()?, v.into_string().ok()?))).collect();
            let timeout = std::time::Duration::from_secs(max_s.clamp(1, 3600) as u64);
            exec::execute(&command, &args, &env::safe_env(&inherited, &job_env), timeout,
                          std::env::var("HOME").ok().as_deref(), std::env::var("NOS_REPO_ROOT").ok().as_deref())
        }
    };
    Ok(serde_json::json!({"job": job, "run_id": run_id, "actor_id": "medulla", "exit_code": r.exit_code,
        "duration_ms": r.duration_ms, "timed_out": r.timed_out, "stdout_tail": r.stdout_tail, "stderr_tail": r.stderr_tail}))
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
        (Some("run"), Some(db)) => {
            if std::env::var("MEDULLA_PULSE").as_deref() != Ok("1") {
                eprintln!("medulla pulse run: off (MEDULLA_PULSE=1 arms it; Pulse is the scheduler until the cutover)");
                return ExitCode::from(2);
            }
            match args.get(1).filter(|j| !j.starts_with("--")).map(|j| run(db, j)) {
                Some(Ok(v)) => {
                    println!("{v}");
                    ExitCode::SUCCESS
                }
                Some(Err(e)) => {
                    eprintln!("medulla pulse run: {e}");
                    ExitCode::FAILURE
                }
                None => ExitCode::from(2),
            }
        }
        _ => {
            eprintln!("usage: medulla pulse plan|tick --dry-run|run <job> --db <wing.db> [--now <epoch>]  (run needs MEDULLA_PULSE=1)");
            ExitCode::from(2)
        }
    }
}
