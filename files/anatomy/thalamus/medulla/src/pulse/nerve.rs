//! The nerve from the medulla to the organ that writes the record (row medulla-scheduler, c2; ruling
//! 2026-10-24: the medulla executes, it never writes). Today that organ is Wing's PHP: POST
//! /api/v1/pulse_runs, then /pulse_runs/<id>/finish, the calls pulse/wing_client.py makes, under the
//! medulla's own bearer (wing.write + pulse.run; Wing names the run's actor after it). The token is
//! read from the environment only, never argv, so `ps` never shows it.
use super::exec::RunResult;
use serde_json::{json, Value};
use std::time::Duration;

pub struct Nerve {
    base: String,
    token: String,
    agent: ureq::Agent,
}

impl Nerve {
    pub fn from_env() -> Result<Nerve, String> {
        let token = std::env::var("MEDULLA_WING_TOKEN").ok().filter(|t| !t.is_empty())
            .ok_or("MEDULLA_WING_TOKEN is unset: --report needs the medulla's Wing bearer")?;
        let base = std::env::var("NOS_WING_URL").unwrap_or_else(|_| "http://127.0.0.1:9000".into());
        // No env proxy, no redirects: the bearer goes to Wing's loopback door and nowhere else.
        let agent = ureq::Agent::config_builder().proxy(None).max_redirects(0).http_status_as_error(false)
            .timeout_global(Some(Duration::from_secs(10))).build().into();
        Ok(Nerve { base: base.trim_end_matches('/').to_string(), token, agent })
    }

    fn post(&self, path: &str, body: &Value) -> Result<(), String> {
        let mut r = self.agent.post(format!("{}{path}", self.base))
            .header("Authorization", format!("Bearer {}", self.token))
            .header("User-Agent", "nos-medulla")
            .send_json(body)
            .map_err(|e| format!("Wing unreachable: {e}"))?;
        let code = r.status().as_u16();
        if (200..300).contains(&code) {
            return Ok(());
        }
        let why = r.body_mut().read_json::<Value>().ok().and_then(|v| v["error"].as_str().map(String::from));
        Err(format!("Wing answered {code}{}", why.map(|w| format!(": {w}")).unwrap_or_default()))
    }

    /// The due feed (PulseRepository::listDue): Wing's predicate and clock, the one Python polls too.
    pub fn due(&self) -> Result<Vec<Value>, String> {
        let mut r = self.agent.get(format!("{}/api/v1/pulse_jobs/due", self.base))
            .header("Authorization", format!("Bearer {}", self.token))
            .header("User-Agent", "nos-medulla")
            .call()
            .map_err(|e| format!("Wing unreachable: {e}"))?;
        let code = r.status().as_u16();
        if code != 200 {
            return Err(format!("Wing answered {code} to the due feed"));
        }
        let mut v: Value = r.body_mut().read_json().map_err(|e| format!("due feed: {e}"))?;
        match if v.get("jobs").is_some() { v["jobs"].take() } else { v } {
            Value::Array(jobs) => Ok(jobs),
            _ => Err("due feed: no jobs list".into()),
        }
    }

    /// The claim before the job runs; refused means the job does not run (a run nobody recorded did not happen).
    pub fn start(&self, job: &str, run_id: &str, fired_at: &str) -> Result<(), String> {
        self.post("/api/v1/pulse_runs", &json!({"job_id": job, "run_id": run_id, "fired_at": fired_at, "actor_action_id": run_id}))
    }

    /// The result. duration_ms only when something ran and was timed (wing_client.py: omitted, not zeroed).
    pub fn finish(&self, run_id: &str, r: &RunResult, finished_at: &str, ran: bool) -> Result<(), String> {
        let mut body = json!({"finished_at": finished_at, "exit_code": r.exit_code,
                              "stdout_tail": r.stdout_tail, "stderr_tail": r.stderr_tail});
        if ran {
            body["duration_ms"] = json!(r.duration_ms);
        }
        self.post(&format!("/api/v1/pulse_runs/{run_id}/finish"), &body)
    }
}
