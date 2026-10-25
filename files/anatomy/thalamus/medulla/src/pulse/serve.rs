//! `medulla pulse serve` (row medulla-scheduler, e): the schedule for the operator's subset of jobs
//! (PULSE_MEDULLA_JOBS, rendered by roles/pazny.pulse from pulse_medulla_jobs; the Python daemon skips
//! exactly those). daemon.py's loop: every PULSE_TICK_INTERVAL_S read Wing's due feed over the nerve,
//! keep the set, PULSE_MAX_CONCURRENT and one run per job in flight, fire each as `run --report`
//! (start claimed first). The halt and the loops pause hold in fire(). SIGTERM drains up to 30 s.
use super::{fire, nerve::Nerve, Job};
use std::collections::{HashMap, HashSet};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

static STOP: AtomicBool = AtomicBool::new(false);

extern "C" fn on_stop(_: libc::c_int) {
    STOP.store(true, Ordering::SeqCst);
}

fn stopped() -> bool {
    STOP.load(Ordering::SeqCst)
}

pub fn serve(nerve: Nerve, set: HashSet<String>, cap: usize, tick: Duration) -> ExitCode {
    let handler = on_stop as extern "C" fn(libc::c_int) as *const () as libc::sighandler_t;
    unsafe {
        libc::signal(libc::SIGTERM, handler);
        libc::signal(libc::SIGINT, handler);
    }
    eprintln!("medulla pulse serve: firing {} job(s) every {:?}, cap {cap}", set.len(), tick);
    let nerve = Arc::new(nerve);
    let mut inflight: HashMap<String, JoinHandle<()>> = HashMap::new();
    while !stopped() {
        inflight.retain(|_, h| !h.is_finished());
        let free = cap.saturating_sub(inflight.len());
        if free > 0 {
            match nerve.due() {
                Ok(due) => {
                    let mine: Vec<_> = due.iter()
                        .filter(|v| v["id"].as_str().is_some_and(|id| set.contains(id) && !inflight.contains_key(id))).take(free).collect();
                    for v in mine {
                        match Job::from_feed(v) {
                            Ok(job) => {
                                let n = nerve.clone();
                                let id = job.id.clone();
                                inflight.insert(id, std::thread::spawn(move || say(fire(&job, Some(&n)))));
                            }
                            Err(e) => eprintln!("medulla pulse serve: {e}"),
                        }
                    }
                }
                Err(e) => eprintln!("medulla pulse serve: {e}"),
            }
        }
        let until = Instant::now() + tick;
        while !stopped() && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(50).min(until.saturating_duration_since(Instant::now())));
        }
    }
    let deadline = Instant::now() + Duration::from_secs(30);
    while inflight.values().any(|h| !h.is_finished()) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    let left = inflight.values().filter(|h| !h.is_finished()).count();
    eprintln!("medulla pulse serve: stopped, {left} run(s) still in flight");
    ExitCode::SUCCESS
}

/// The log line: the outcome, not the tails (Wing holds those).
fn say(r: Result<serde_json::Value, String>) {
    match r {
        Ok(v) => println!("{}", serde_json::json!({"job": v["job"], "run_id": v["run_id"], "exit_code": v["exit_code"],
                                                   "duration_ms": v["duration_ms"], "reported": v["reported"]})),
        Err(e) => eprintln!("medulla pulse serve: {e}"),
    }
}

pub fn cli() -> ExitCode {
    let var = |k: &str| std::env::var(k).unwrap_or_default();
    if var("MEDULLA_PULSE") != "1" {
        eprintln!("medulla pulse serve: off (MEDULLA_PULSE=1 arms it)");
        return ExitCode::from(2);
    }
    let set: HashSet<String> = var("PULSE_MEDULLA_JOBS").split(',').filter(|j| !j.is_empty()).map(String::from).collect();
    if set.is_empty() {
        eprintln!("medulla pulse serve: PULSE_MEDULLA_JOBS is empty, the medulla fires nothing");
        return ExitCode::from(2);
    }
    let nerve = match Nerve::from_env() {
        Ok(n) => n,
        Err(e) => {
            eprintln!("medulla pulse serve: {e}");
            return ExitCode::from(2);
        }
    };
    let cap = var("PULSE_MAX_CONCURRENT").parse().unwrap_or(4);
    let tick = var("PULSE_TICK_INTERVAL_S").parse::<f64>().ok().filter(|t| *t > 0.0).unwrap_or(30.0);
    serve(nerve, set, cap, Duration::from_secs_f64(tick))
}
