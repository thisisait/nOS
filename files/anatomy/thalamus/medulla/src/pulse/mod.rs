//! The Pulse schedule in the medulla (row medulla-scheduler, increment a): it reads and plans, it
//! does not fire and does not write. `medulla pulse plan --db <wing.db> [--now <epoch>]` prints one
//! JSON line per live job: Wing's next_fire_at beside the medulla's, and the allowlist verdict.
pub mod allow;
pub mod cron;

use std::process::ExitCode;

/// PHP's date('c') in UTC: 2026-10-25T10:33:00+00:00.
pub fn iso(t: i64) -> String {
    let d = time::OffsetDateTime::from_unix_timestamp(t).expect("epoch in range");
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}+00:00", d.year(), u8::from(d.month()), d.day(), d.hour(), d.minute(), d.second())
}

pub fn plan(db: &str, now: i64) -> Result<(), String> {
    let conn = rusqlite::Connection::open_with_flags(db, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|e| e.to_string())?;
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
        _ => {
            eprintln!("usage: medulla pulse plan --db <wing.db> [--now <epoch>]");
            ExitCode::from(2)
        }
    }
}
