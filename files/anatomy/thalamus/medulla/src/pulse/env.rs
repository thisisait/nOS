//! The child's environment, second copy of pulse/runners/subprocess.py::_safe_env: inherited env minus
//! secret-shaped keys, plus the job env's allow-listed keys. test_pulse_command_allowlist pins both.
pub const JOB_ENV_KEYS: &[&str] = &[
    "BONE_API_URL", "CORTEX_AGENT_TOKEN_CAPTURE", "CORTEX_AGENT_TOKEN_RO", "CORTEX_AGENT_TOKEN_RW", "CORTEX_API_URL",
    "DISPATCH_BATCH_LIMIT", "DISPATCH_DIGEST_FLUSH", "DISPATCH_MAIL_DIGEST_FLOOR", "DRIFT_STALE_HOURS",
    "GITLEAKS_MIN_SEVERITY", "KEAP_AGENT_TOKEN_CAPTURE", "KEAP_AGENT_TOKEN_RO", "KEAP_AGENT_TOKEN_RW",
    "KEAP_API_URL", "MAIL_FROM", "MAIL_HOST", "MAIL_PASSWORD", "MAIL_PORT", "MAIL_RECIPIENT", "MAIL_TLS_MODE",
    "MAIL_TLS_VERIFY", "MAIL_USERNAME", "N8N_API_KEY", "NOS_AGENT_CLIENT_ID", "NOS_AGENT_CLIENT_SECRET",
    "NOS_AGENT_NAME", "NOS_AGENT_PROFILE", "NOS_AGENT_TASK", "NOS_AUTHENTIK_URL", "NOS_CONSOLIDATE_DB_EXCLUDE",
    "NOS_CONSOLIDATE_FS_ROOTS", "NOS_COST_TALLY_FLOOR_USD", "NOS_COST_TALLY_WINDOW_H", "NOS_MARIADB_ROOT_PASSWORD",
    "NOS_NOTIFY_ACTOR", "NOS_NOTIFY_BIN", "NOS_NOTIFY_ORIGIN", "NOS_REPO", "NOS_SCAN_DIR", "NOS_TOFU_DIR",
    "NTFY_PUBLISH_PASSWORD", "NTFY_PUBLISH_USER", "NTFY_URL", "OLLAMA_URL", "PROMETHEUS_URL", "REPO_DIR",
    "VULNSCAN_SECURITY_DIR", "WING_API_TOKEN", "WING_API_URL", "WING_DATA_DIR", "WING_DB_PATH",
    "WING_EVENTS_HMAC_SECRET", "WING_EVENTS_HMAC_SECRET_RETIRED",
];
pub const DAEMON_ENV_KEYS: &[&str] = &["PULSE_RUN_ID", "TRACEPARENT"];
const SECRET_PARTS: &[&str] = &["SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "ANTHROPIC", "HMAC", "API_KEY"];

/// `_SECRET_KEY_RE.search(k)` under re.I: Python also folds ſ→S, K (Kelvin)→K, İ/ı→I, and its `$`
/// matches before one trailing newline. Both kept: a key Python strips, the medulla strips.
pub(crate) fn secret_key(k: &str) -> bool {
    let up: String = k
        .chars()
        .map(|c| match c {
            'ſ' => 'S',
            '\u{212a}' => 'K',
            'İ' | 'ı' => 'I',
            c => c.to_ascii_uppercase(),
        })
        .collect();
    SECRET_PARTS.iter().any(|p| up.contains(p)) || up.ends_with("_KEY") || up.ends_with("_KEY\n")
}

/// Pure: the caller passes std::env::vars(). A job key overrides an inherited one in place (dict order).
pub fn safe_env(inherited: &[(String, String)], job_env: &[(String, String)]) -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = inherited.iter().filter(|(k, _)| !secret_key(k)).cloned().collect();
    let allowed = |k: &str| JOB_ENV_KEYS.contains(&k) || DAEMON_ENV_KEYS.contains(&k);
    for (k, v) in job_env.iter().filter(|(k, _)| allowed(k)) {
        match env.iter_mut().find(|(e, _)| e == k) {
            Some(slot) => slot.1 = v.clone(),
            None => env.push((k.clone(), v.clone())),
        }
    }
    env
}

#[cfg(test)]
mod tests {
    /// The cases test_pulse_command_allowlist runs through the Python _safe_env, from one file.
    #[test]
    fn the_shared_cases() {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../../../../../tests/fixtures/pulse_env.json")).unwrap();
        let pairs = |p: &serde_json::Value| -> Vec<(String, String)> {
            p.as_array().unwrap().iter().map(|kv| (kv[0].as_str().unwrap().into(), kv[1].as_str().unwrap().into())).collect()
        };
        for c in v.as_array().unwrap() {
            assert_eq!(super::safe_env(&pairs(&c["inherited"]), &pairs(&c["job"])), pairs(&c["expected"]), "{}", c["why"]);
        }
    }
}
