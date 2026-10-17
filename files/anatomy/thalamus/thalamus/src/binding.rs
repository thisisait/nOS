//! A cell's `model.backend` resolved into a Binding, or refused — the gates of
//! files/anatomy/wing/app/AgentKit/LLMClient/BindingResolver.php, in its order.
//! The vault is the caller's env: `nos:<var>` is asked of it like any other name
//! (main.rs answers it from the plist's NOS_SECRET_<VAR>, read once). An empty
//! answer refuses, which is what the PHP resolver does when the key resolves to nothing.

use serde_yaml_ng::Value;
use std::path::Path;

#[derive(Clone, PartialEq)]
pub struct Binding {
    pub name: String,
    pub base_url: String,
    pub auth_token: String,
    pub model_id: String,
    /// The row's `local: true`: the model runs on this host (serve picks the short imprint).
    pub local: bool,
    /// A local row's sampling temperature (NOS_LOCAL_TEMPERATURE, default 0.3); None leaves a cloud row's own.
    pub temperature: Option<f64>,
}

/// Never prints the key: a Binding is logged and panicked over.
impl std::fmt::Debug for Binding {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let key = if self.auth_token.is_empty() { "none" } else { "set" };
        write!(f, "Binding {{ name: {:?}, base_url: {:?}, auth_token: {key}, model_id: {:?}, local: {} }}",
               self.name, self.base_url, self.model_id, self.local)
    }
}

/// Default and Disarmed name no model: the thalamus has no default adapter, so
/// only Bound can serve a turn.
#[derive(Debug, PartialEq)]
pub enum Decision {
    Default,
    Disarmed(String),
    Bound(Binding),
}

/// Reads files/anatomy/agents/<cell>/agent.yml and the register under `repo`.
pub fn resolve(repo: &Path, cell: &str, env: impl Fn(&str) -> Option<String>) -> Result<Decision, String> {
    let path = repo.join("files/anatomy/agents").join(cell).join("agent.yml");
    let agent = std::fs::read_to_string(&path).map_err(|e| format!("cell '{cell}': {}: {e}", path.display()))?;
    // No register file → nothing non-default resolves (the PHP fail-closed shape).
    let register = std::fs::read_to_string(repo.join("state/habitat/llm-backends.yml")).unwrap_or_default();
    decide(&agent, &register, env)
}

fn at<'a>(v: &'a Value, path: &[&str]) -> &'a Value {
    path.iter().fold(v, |v, k| v.get(*k).unwrap_or(&Value::Null))
}

fn text(v: &Value, path: &[&str]) -> String {
    at(v, path).as_str().unwrap_or_default().to_string()
}

pub fn decide(agent_yml: &str, register_yml: &str, env: impl Fn(&str) -> Option<String>) -> Result<Decision, String> {
    let agent: Value = serde_yaml_ng::from_str(agent_yml).map_err(|e| format!("agent.yml: {e}"))?;
    let register: Value = if register_yml.trim().is_empty() {
        Value::Null
    } else {
        serde_yaml_ng::from_str(register_yml).map_err(|e| format!("llm-backends.yml: {e}"))?
    };
    let name = text(&agent, &["name"]);
    let uri = text(&agent, &["model", "primary"]);
    let Some(own) = at(&agent, &["model", "backend"]).as_str() else {
        return Ok(Decision::Default);
    };
    // A host's explicit choice of row (NOS_CELL_BACKEND, ruling 2026-10-14): only one the record allows,
    // and then judged by every gate below — a choice, never a fallback.
    let chosen = env("NOS_CELL_BACKEND").unwrap_or_default();
    let declared = if chosen.trim().is_empty() { own } else {
        let allowed: Vec<&str> = at(&agent, &["model", "backends_allowed"]).as_sequence()
            .map(|v| v.iter().filter_map(Value::as_str).collect()).unwrap_or_default();
        if !allowed.contains(&chosen.trim()) {
            return Err(format!("agent '{name}' may bind only {}; this host chose '{}'",
                               if allowed.is_empty() { own.to_string() } else { allowed.join(", ") }, chosen.trim()));
        }
        allowed.into_iter().find(|b| *b == chosen.trim()).unwrap_or(own)
    };
    let spec = at(&register, &["backends", declared]);
    if spec.is_null() {
        return Err(format!("agent '{name}' declares backend '{declared}', which state/habitat/llm-backends.yml does not list"));
    }
    if spec.get("default").and_then(Value::as_bool) == Some(true) {
        return Ok(Decision::Default);
    }

    // Gate 7 — the provider (before the first '-') must speak the row's protocol.
    let (provider, tail) = uri.split_once('-').unwrap_or(("", uri.get(1..).unwrap_or("")));
    let speaks = match provider {
        "claude" | "anthropic" => "anthropic",
        "openai" | "openclaw" => "openai",
        _ => "",
    };
    let protocol = spec.get("protocol").and_then(Value::as_str).unwrap_or("anthropic");
    if speaks != protocol {
        return Err(format!("agent '{name}': provider '{provider}' does not speak backend '{declared}'s wire protocol '{protocol}'"));
    }

    // Gate 5 — a deferred cell's record is truthful only while it never runs.
    if text(&agent, &["metadata", "runner_status"]).to_lowercase() == "deferred" {
        return Err(format!("agent '{name}' is runner_status=deferred; refusing to bind it"));
    }

    // Gates 4 + 8 — the cell's own Article-30 record must cover this row.
    let processors = at(&agent, &["gdpr", "processors"]).as_sequence().cloned().unwrap_or_default();
    let matcher = text(spec, &["processor_match"]);
    if matcher.is_empty() || !processors.iter().any(|p| text(p, &["name"]).contains(&matcher)) {
        return Err(format!("agent '{name}' routes to '{declared}' but its own gdpr.processors never names '{matcher}'"));
    }
    let eu_only = at(&agent, &["gdpr", "transfers_outside_eu"]).as_bool() == Some(false) && !processors.is_empty();
    // Gate 8 — an EU-claiming record reaches a non-EU row only where the host's gdpr_posture is none
    // (ruling 2026-10-17); nos_gdpr.effective_records then records the transfer.
    let posture = env("NOS_GDPR_POSTURE").filter(|p| !p.trim().is_empty()).unwrap_or_else(|| "standard".into());
    if eu_only && at(spec, &["residency", "eu"]).as_bool() != Some(true) && posture.trim() != "none" {
        return Err(format!("agent '{name}' declares transfers_outside_eu: false but routes to '{declared}', which is not \
                            EU-resident, and gdpr_posture is '{}': a non-EU row serves only under gdpr_posture: none", posture.trim()));
    }

    // Gate 6 — the tier word in the URI tail; opus maps to null by ruling 1.
    let tier = tail
        .split(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))
        .find(|w| matches!(*w, "haiku" | "sonnet" | "opus" | "vision"))
        .unwrap_or(tail);
    let Some(model_env) = at(spec, &["model_env", tier]).as_str().map(str::to_string) else {
        return Err(format!("agent '{name}' (tier '{tier}', from '{uri}') has no model mapping on backend '{declared}'"));
    };

    // Gate 3 — not armed is not an error, unless the record forbids degrading.
    let armed = env("NOS_ARMED_BACKENDS").unwrap_or_default();
    if !armed.split_whitespace().any(|b| b == declared) {
        if eu_only {
            return Err(format!("agent '{name}' declares transfers_outside_eu: false and its backend '{declared}' is not armed"));
        }
        return Ok(Decision::Disarmed(declared.to_string()));
    }
    let model_id = env(&model_env).unwrap_or_default();
    if model_id.is_empty() {
        return Err(format!("backend '{declared}' is armed but {model_env} is empty; refusing to send a blank model id"));
    }

    // Gate 7 (key half) — a key, unless the row is local and names none.
    let local = spec.get("local").and_then(Value::as_bool) == Some(true);
    let secret = text(spec, &["auth_secret"]);
    let auth_token = if secret.is_empty() { String::new() } else { env(&secret).unwrap_or_default() };
    if auth_token.is_empty() && (!local || !secret.is_empty()) {
        let var = secret.strip_prefix("nos:").unwrap_or(&secret);
        return Err(format!("backend '{declared}' is armed but its auth_secret '{secret}' resolves to nothing: \
                            set {var} in credentials.yml and converge"));
    }
    Ok(Decision::Bound(Binding {
        name: declared.to_string(),
        base_url: text(spec, &["base_url"]),
        auth_token,
        model_id,
        local,
        // Client bench 2026-10-15: one model scored 9/11 then 6/11 at Ollama's default temperature.
        temperature: local.then(|| env("NOS_LOCAL_TEMPERATURE").and_then(|t| t.trim().parse::<f64>().ok())
            .filter(|t| (0.0..=2.0).contains(t)).unwrap_or(0.3)),
    }))
}

/// One row of the cell's model.backends_allowed as this host could serve it (W5: the person's
/// per-session pick): who processes the turns, whether they leave the EU, the binding or why not.
#[derive(Debug, Clone)]
pub struct Pick {
    pub row: String,
    pub processor: String,
    pub outside_eu: bool,
    pub bound: Result<Binding, String>,
}

/// Every allowed row judged as if the host had chosen it, plus gdpr_posture: a non-EU row serves
/// only under none (tools/nos_cell_binding.py requirement).
pub fn picks(agent_yml: &str, register_yml: &str, env: impl Fn(&str) -> Option<String>) -> Vec<Pick> {
    let (Ok(agent), Ok(register)) = (serde_yaml_ng::from_str::<Value>(agent_yml), serde_yaml_ng::from_str::<Value>(register_yml)) else {
        return vec![];
    };
    let posture = env("NOS_GDPR_POSTURE").filter(|p| !p.trim().is_empty()).unwrap_or_else(|| "standard".into());
    let processors = at(&agent, &["gdpr", "processors"]).as_sequence().cloned().unwrap_or_default();
    let allowed = at(&agent, &["model", "backends_allowed"]).as_sequence().cloned().unwrap_or_default();
    allowed.iter().filter_map(Value::as_str).map(|row| {
        let spec = at(&register, &["backends", row]);
        let matcher = text(spec, &["processor_match"]);
        let processor = processors.iter().map(|p| text(p, &["name"])).find(|n| !matcher.is_empty() && n.contains(&matcher)).unwrap_or(matcher);
        let outside_eu = at(spec, &["residency", "eu"]).as_bool() != Some(true);
        let bound = if outside_eu && posture.trim() != "none" {
            Err(format!("'{row}' is not EU-resident and gdpr_posture is '{}': a non-EU row serves only under gdpr_posture: none",
                        posture.trim()))
        } else {
            match decide(agent_yml, register_yml, |k| if k == "NOS_CELL_BACKEND" { Some(row.to_string()) } else { env(k) }) {
                Ok(Decision::Bound(b)) => Ok(b),
                Ok(Decision::Disarmed(_)) => Err(format!("'{row}' is not armed on this host")),
                Ok(Decision::Default) => Err(format!("'{row}' is the default row, which the thalamus cannot serve")),
                Err(why) => Err(why),
            }
        };
        Pick { row: row.to_string(), processor, outside_eu, bound }
    }).collect()
}

/// Reads the cell and the register under `repo` as resolve() does; none readable, no picks.
pub fn resolve_picks(repo: &Path, cell: &str, env: impl Fn(&str) -> Option<String>) -> Vec<Pick> {
    let agent = std::fs::read_to_string(repo.join("files/anatomy/agents").join(cell).join("agent.yml")).unwrap_or_default();
    let register = std::fs::read_to_string(repo.join("state/habitat/llm-backends.yml")).unwrap_or_default();
    picks(&agent, &register, env)
}

/// Parameters in billions from an ollama tag (qwen3:14b -> 14, mixtral:8x7b -> 56); None = unknown.
/// tools/nos_cell_binding.py params_b: the first `-`/`_` segment of the tag that reads [Nx]N[.N]b|m.
pub fn params_b(model: &str) -> Option<f64> {
    let whole = |s: &str| (!s.is_empty() && s.bytes().all(|c| c.is_ascii_digit())).then(|| s.parse::<f64>().ok()).flatten();
    let (_, tag) = model.rsplit_once(':')?;
    tag.split(['-', '_']).find_map(|seg| {
        let div = match seg.bytes().last()? { b'b' | b'B' => 1.0, b'm' | b'M' => 1000.0, _ => return None };
        let num = &seg[..seg.len() - 1];
        let (times, n) = match num.split_once(['x', 'X']) { Some((t, n)) => (whole(t)?, n), None => (1.0, num) };
        let (a, b) = n.split_once('.').unwrap_or((n, "0"));
        whole(a)?;
        whole(b)?;
        Some(n.parse::<f64>().ok()? * times / div)
    })
}

/// The size floors (llm_cell_min_params_b refuses, llm_cell_recommended_params_b warns), the
/// texts of tools/nos_cell_binding.py size_floor: Err = refused, Ok(Some) = a warning, Ok(None) = fine.
pub fn size_floor(model: &str, min_b: f64, warn_b: f64) -> Result<Option<String>, String> {
    let Some(size) = params_b(model) else {
        return Err(format!("the size of '{model}' is UNKNOWN (no NNb in its tag), so it cannot be shown to be at least {min_b}B"));
    };
    if size < min_b {
        return Err(format!("'{model}' has {size}B parameters, below the {min_b}B minimum (llm_cell_min_params_b)"));
    }
    Ok((size < warn_b).then(|| format!("'{model}' has {size}B parameters, below the {warn_b}B recommended \
                                         (llm_cell_recommended_params_b): it runs, badly")))
}
