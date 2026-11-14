//! `medulla intents tick`: run the intents Wing filed, under the medulla's own credentials
//! (row wing-apply-through-medulla, slice 1b-ii; rulings 2026-11-11/13/14).
//!
//! The medulla executes, it never writes the record: it asks Wing to pick an intent (Wing stamps
//! picked_at once), runs the verb against Bone with a token only it holds, and reports the outcome to
//! Wing, which records it once. Slice 1 runs one verb, an upgrade's dry run (Bone's POST /plan,
//! nos:upgrades:read). Off unless MEDULLA_EXECUTES_INTENTS=1 (config medulla_executes_intents), held by
//! the halt, and the credentials come from custody only (/etc/nos/medulla.env, the macOS Keychain).

use serde_json::{json, Value};
use std::process::{Command, ExitCode};
use std::time::Duration;

const CUSTODY_FILE: &str = "/etc/nos/medulla.env";
const CLIENT_ID: &str = "nos-medulla";

pub fn cli(args: &[String]) -> ExitCode {
    match args.first().map(String::as_str) {
        Some("tick") if args.len() == 1 => tick(),
        _ => {
            eprintln!("usage: medulla intents tick");
            ExitCode::from(64)
        }
    }
}

fn tick() -> ExitCode {
    if std::env::var("MEDULLA_EXECUTES_INTENTS").as_deref() != Ok("1") {
        println!("intents: off (medulla_executes_intents is false)");
        return ExitCode::SUCCESS;
    }
    match std::fs::metadata(thalamus::state::halt_file()) {
        Ok(_) => {
            println!("intents: held (the halt is on)");
            return ExitCode::SUCCESS;
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => {
            eprintln!("intents: halt UNKNOWN ({e}); nothing run");
            return ExitCode::from(1);
        }
    }
    let (bone_secret, wing_token) = match custody() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("intents: {e}");
            return ExitCode::from(1);
        }
    };
    let http: ureq::Agent = ureq::Agent::config_builder().proxy(None).max_redirects(0).http_status_as_error(false)
        .timeout_global(Some(Duration::from_secs(60))).build().into();
    let wing = env_url("NOS_WING_URL", "http://127.0.0.1:9000");
    let due = match get_json(&http, &format!("{wing}/api/v1/intents/due"), &wing_token) {
        Ok(v) => v["intents"].as_array().cloned().unwrap_or_default(),
        Err(e) => {
            eprintln!("intents: {e}");
            return ExitCode::from(1);
        }
    };
    let mut failed = false;
    for intent in due {
        let uuid = intent["uuid"].as_str().unwrap_or_default().to_string();
        if !nos_contract::wire::is_uuid(&uuid) {
            continue;
        }
        match post_json(&http, &format!("{wing}/api/v1/intents/{uuid}/pick"), &wing_token, &json!({})) {
            Ok((200, _)) => {}
            Ok((409, _)) => continue, // another tick won it
            Ok((code, why)) | Err((code, why)) => {
                eprintln!("intents: pick {uuid}: Wing answered {code} {why}");
                failed = true;
                continue;
            }
        }
        let (rc, summary) = run(&http, &intent, &bone_secret);
        println!("intents: {uuid} {} rc={rc}", intent["verb"].as_str().unwrap_or("?"));
        let body = json!({"rc": rc, "summary": summary});
        match post_json(&http, &format!("{wing}/api/v1/intents/{uuid}/outcome"), &wing_token, &body) {
            Ok((200, _)) => {}
            Ok((code, why)) | Err((code, why)) => {
                eprintln!("intents: outcome {uuid}: Wing answered {code} {why}");
                failed = true;
            }
        }
        failed |= rc != 0;
    }
    if failed { ExitCode::from(1) } else { ExitCode::SUCCESS }
}

/// The verb, run against Bone with the medulla's own token. (rc, summary); never panics.
fn run(http: &ureq::Agent, intent: &Value, bone_secret: &str) -> (i64, String) {
    let plain = |s: &str| !s.is_empty() && s.len() <= 100 && s.bytes().all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b));
    let (service, recipe) = (intent["target"]["service"].as_str().unwrap_or(""), intent["target"]["recipe"].as_str().unwrap_or(""));
    if intent["verb"] != "upgrade.apply" || intent["dry_run"] != true {
        return (2, "slice 1 runs upgrade.apply dry runs only".into());
    }
    if !plain(service) || !plain(recipe) {
        return (2, "target is not a plain service/recipe name".into());
    }
    let token = match bone_token(http, bone_secret) {
        Ok(t) => t,
        Err(e) => return (3, e),
    };
    let url = format!("{}/api/upgrades/{service}/{recipe}/plan", env_url("NOS_BONE_URL", "http://127.0.0.1:8099"));
    match http.post(&url).header("Authorization", format!("Bearer {token}")).header("User-Agent", "nos-medulla").send_empty() {
        Err(e) => (3, format!("Bone unreachable: {e}")),
        Ok(mut r) => {
            let code = r.status().as_u16();
            let text: String = r.body_mut().read_to_string().unwrap_or_default().chars().take(300).collect();
            (if (200..300).contains(&code) { 0 } else { 1 }, format!("dry run (plan) HTTP {code}: {text}"))
        }
    }
}

/// client_credentials for nos-medulla at MEDULLA_AUTHENTIK_TOKEN_URL; the secret never reaches a log.
fn bone_token(http: &ureq::Agent, secret: &str) -> Result<String, String> {
    let url = std::env::var("MEDULLA_AUTHENTIK_TOKEN_URL").ok().filter(|u| u.starts_with("https://") || u.starts_with("http://127."))
        .ok_or("MEDULLA_AUTHENTIK_TOKEN_URL is unset (or not https / loopback): no Bone token")?;
    let mut r = http.post(&url)
        .send_form([("grant_type", "client_credentials"), ("client_id", CLIENT_ID), ("client_secret", secret),
                    ("scope", "nos:upgrades:read")])
        .map_err(|e| format!("Authentik unreachable: {e}"))?;
    let code = r.status().as_u16();
    let v: Value = r.body_mut().read_json().unwrap_or(Value::Null);
    v["access_token"].as_str().filter(|_| code == 200).map(str::to_string)
        .ok_or_else(|| format!("Authentik refused the nos-medulla grant (HTTP {code})"))
}

/// (Bone client secret, wing-intents bearer) from custody; never from ~/.nos/secrets.yml.
fn custody() -> Result<(String, String), String> {
    let pick = |v: Option<String>, name: &str| v.filter(|t| t.len() >= 32)
        .ok_or_else(|| format!("no {name} in the medulla's custody (a converge writes it)"));
    if cfg!(target_os = "macos") {
        let item = |service: &str| Command::new("security")
            .args(["find-generic-password", "-a", "nos", "-s", service, "-w"]).output().ok()
            .filter(|o| o.status.success())
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string());
        return Ok((pick(item("nos.medulla.bone-client-secret"), "bone client secret")?,
                   pick(item("nos.medulla.wing-intents-token"), "wing-intents token")?));
    }
    let text = std::fs::read_to_string(CUSTODY_FILE).map_err(|e| format!("{CUSTODY_FILE} unreadable: {e}"))?;
    let key = |k: &str| text.lines().find_map(|l| l.strip_prefix(k)?.strip_prefix('=').map(|v| v.trim().to_string()));
    Ok((pick(key("MEDULLA_BONE_CLIENT_SECRET"), "bone client secret")?, pick(key("WING_INTENTS_TOKEN"), "wing-intents token")?))
}

fn env_url(var: &str, default: &str) -> String {
    std::env::var(var).ok().filter(|v| !v.is_empty()).unwrap_or_else(|| default.into()).trim_end_matches('/').to_string()
}

fn get_json(http: &ureq::Agent, url: &str, token: &str) -> Result<Value, String> {
    let mut r = http.get(url).header("Authorization", format!("Bearer {token}")).header("User-Agent", "nos-medulla")
        .call().map_err(|e| format!("Wing unreachable at {url}: {e}"))?;
    let code = r.status().as_u16();
    let v: Value = r.body_mut().read_json().unwrap_or(Value::Null);
    if code == 200 { Ok(v) } else { Err(format!("Wing answered {code} at {url}: {}", v["error"].as_str().unwrap_or(""))) }
}

fn post_json(http: &ureq::Agent, url: &str, token: &str, body: &Value) -> Result<(u16, String), (u16, String)> {
    let mut r = http.post(url).header("Authorization", format!("Bearer {token}")).header("User-Agent", "nos-medulla")
        .send_json(body).map_err(|e| (0, format!("unreachable: {e}")))?;
    let code = r.status().as_u16();
    let v: Value = r.body_mut().read_json().unwrap_or(Value::Null);
    Ok((code, v["error"].as_str().unwrap_or("").to_string()))
}
