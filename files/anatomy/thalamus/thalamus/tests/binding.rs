//! The thalamus binds a cell the way BindingResolver.php does, against the REAL
//! register (state/habitat/llm-backends.yml) and the real iris cell — never a copy.

use std::path::{Path, PathBuf};
use thalamus::binding::{decide, resolve, size_floor, Decision};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../..")
}

fn register() -> String {
    std::fs::read_to_string(repo().join("state/habitat/llm-backends.yml")).unwrap()
}

/// An env with exactly these pairs set.
fn env<'a>(pairs: &'a [(&'a str, &'a str)]) -> impl Fn(&str) -> Option<String> + 'a {
    move |k| pairs.iter().find(|(n, _)| *n == k).map(|(_, v)| v.to_string())
}

const ARMED: &[(&str, &str)] = &[("NOS_ARMED_BACKENDS", "ollama"), ("NOS_LOCAL_MODEL", "qwen3:14b")];

/// Iris's serving set (operator ruling 2026-10-12): the EU row, armed, its model and its key.
const EU: &[(&str, &str)] = &[("NOS_ARMED_BACKENDS", "mistral-eu"), ("NOS_MISTRAL_MODEL", "mistral-large-latest"),
                              ("nos:mistral_api_key", "sk-eu-test")];

/// A keyless local cell, the shape iris had before it moved to the EU row.
const LOCAL_CELL: &str = "
name: c
model: {primary: openai-local-sonnet, backend: ollama}
gdpr: {processors: [{name: on-device}], transfers_outside_eu: false}
";

/// A cell bound to minimax whose record says the transfer happens (so it may degrade).
const MINIMAX_CELL: &str = "
name: cloudy
model: {primary: claude-sonnet, backend: minimax}
gdpr: {processors: [{name: MiniMax}], transfers_outside_eu: true}
";

fn refused(r: Result<Decision, String>) -> String {
    match r {
        Err(why) => why,
        Ok(d) => panic!("expected a refusal, got {d:?}"),
    }
}

#[test]
fn binding_iris_is_bound_to_mistral_eu_with_its_key() {
    match resolve(&repo(), "iris", env(EU)).unwrap() {
        Decision::Bound(b) => {
            assert_eq!(b.name, "mistral-eu");
            assert_eq!(b.base_url, "https://api.eu.mistral.ai/v1");
            assert_eq!(b.auth_token, "sk-eu-test");
            assert_eq!(b.model_id, "mistral-large-latest");
            assert!(!format!("{b:?}").contains("sk-eu-test"), "Debug prints the key");
        }
        d => panic!("iris armed must bind, got {d:?}"),
    }
}

#[test]
fn binding_iris_without_its_key_refuses_and_names_the_var() {
    let why = refused(resolve(&repo(), "iris", env(&EU[..2])));
    assert!(why.contains("auth_secret") && why.contains("mistral_api_key"), "{why}");
}

#[test]
fn binding_iris_never_degrades_to_ollama() {
    // ollama armed with its model, mistral-eu not armed: iris refuses rather than run anywhere else.
    let e = [ARMED, &EU[1..]].concat();
    let why = refused(resolve(&repo(), "iris", env(&e)));
    assert!(why.contains("not armed") && why.contains("mistral-eu"), "{why}");
}

#[test]
fn binding_a_local_cell_binds_with_no_key() {
    match decide(LOCAL_CELL, &register(), env(ARMED)).unwrap() {
        Decision::Bound(b) => assert_eq!((b.name.as_str(), b.auth_token.as_str()), ("ollama", "")),
        d => panic!("a local cell armed must bind, got {d:?}"),
    }
}

#[test]
fn binding_disarmed_falls_to_the_default_and_names_no_model() {
    let d = decide(MINIMAX_CELL, &register(), env(&[("NOS_MINIMAX_MODEL", "m1")])).unwrap();
    assert!(matches!(d, Decision::Disarmed(ref n) if n == "minimax"), "{d:?}");
}

#[test]
fn binding_iris_disarmed_refuses_rather_than_degrade() {
    let why = refused(resolve(&repo(), "iris", env(&EU[1..])));
    assert!(why.contains("not armed"), "{why}");
}

#[test]
fn binding_armed_with_an_empty_model_env_refuses() {
    let why = refused(resolve(&repo(), "iris", env(&[EU[0], EU[2]])));
    assert!(why.contains("NOS_MISTRAL_MODEL"), "{why}");
}

#[test]
fn binding_opus_tier_refuses() {
    let cell = "name: c\nmodel: {primary: openai-local-opus, backend: ollama}\ngdpr: {processors: [{name: on-device}], transfers_outside_eu: false}\n";
    assert!(refused(decide(cell, &register(), env(ARMED))).contains("tier 'opus'"));
}

#[test]
fn binding_no_tier_word_refuses() {
    let cell = "name: c\nmodel: {primary: openai-gpt4, backend: ollama}\ngdpr: {processors: [{name: on-device}]}\n";
    assert!(refused(decide(cell, &register(), env(ARMED))).contains("no model mapping"));
}

#[test]
fn binding_undeclared_or_default_is_the_default() {
    let none = "name: c\nmodel: {primary: claude-sonnet}\n";
    assert!(matches!(decide(none, &register(), env(ARMED)).unwrap(), Decision::Default));
    let named = "name: c\nmodel: {primary: claude-sonnet, backend: anthropic}\n";
    assert!(matches!(decide(named, &register(), env(ARMED)).unwrap(), Decision::Default));
}

#[test]
fn binding_an_unlisted_backend_refuses_and_no_register_lists_nothing() {
    let cell = "name: c\nmodel: {primary: openai-local-sonnet, backend: nowhere}\n";
    assert!(refused(decide(cell, &register(), env(ARMED))).contains("does not list"));
    // A repo holding the real iris cell but no register: iris must refuse.
    let bare = std::env::temp_dir().join(format!("thalamus-noreg-{}", std::process::id()));
    let cell = bare.join("files/anatomy/agents/iris");
    std::fs::create_dir_all(&cell).unwrap();
    std::fs::copy(repo().join("files/anatomy/agents/iris/agent.yml"), cell.join("agent.yml")).unwrap();
    let why = refused(resolve(&bare, "iris", env(ARMED)));
    std::fs::remove_dir_all(&bare).unwrap();
    assert!(why.contains("does not list"), "{why}");
}

#[test]
fn binding_a_provider_that_does_not_speak_the_protocol_refuses() {
    let cell = "name: c\nmodel: {primary: claude-sonnet, backend: ollama}\ngdpr: {processors: [{name: on-device}]}\n";
    assert!(refused(decide(cell, &register(), env(ARMED))).contains("wire protocol"));
}

#[test]
fn binding_deferred_refuses() {
    let cell = "name: c\nmodel: {primary: openai-local-sonnet, backend: ollama}\nmetadata: {runner_status: deferred}\ngdpr: {processors: [{name: on-device}]}\n";
    assert!(refused(decide(cell, &register(), env(ARMED))).contains("deferred"));
}

#[test]
fn binding_a_record_that_does_not_name_the_processor_refuses() {
    let cell = "name: c\nmodel: {primary: openai-local-sonnet, backend: ollama}\ngdpr: {processors: [{name: Anthropic}]}\n";
    assert!(refused(decide(cell, &register(), env(ARMED))).contains("never names 'on-device'"));
}

#[test]
fn binding_an_eu_only_record_never_routes_off_the_eu() {
    let cell = "name: c\nmodel: {primary: claude-sonnet, backend: minimax}\ngdpr: {processors: [{name: MiniMax}], transfers_outside_eu: false}\n";
    assert!(refused(decide(cell, &register(), env(ARMED))).contains("not EU-resident"));
}

#[test]
fn binding_an_armed_keyed_backend_refuses_without_a_vault() {
    let e = env(&[("NOS_ARMED_BACKENDS", "minimax"), ("NOS_MINIMAX_MODEL", "m1")]);
    assert!(refused(decide(MINIMAX_CELL, &register(), e)).contains("auth_secret"));
}

/// tests/binding-cases.yml: the cases tools/nos_cell_binding.py (the converge preflight) also runs.
#[test]
fn binding_agrees_with_the_shared_cases() {
    use serde_yaml_ng::Value;
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/binding-cases.yml");
    let doc: Value = serde_yaml_ng::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let s = |v: &Value, k: &str| v.get(k).and_then(Value::as_str).unwrap_or_default().to_string();
    let cases = doc["cases"].as_sequence().unwrap();
    assert!(cases.len() >= 10, "the shared cases shrank");
    for case in cases {
        let agent = match case.get("cell").and_then(Value::as_str) {
            Some(c) => std::fs::read_to_string(repo().join("files/anatomy/agents").join(c).join("agent.yml")).unwrap(),
            None => s(case, "agent"),
        };
        let pairs: Vec<(String, String)> = case["env"].as_mapping().unwrap().iter()
            .map(|(k, v)| (k.as_str().unwrap().to_string(), v.as_str().unwrap().to_string())).collect();
        let got = decide(&agent, &register(), |k| pairs.iter().find(|(n, _)| n == k).map(|(_, v)| v.clone()));
        let (name, want) = (s(case, "name"), &case["expect"]);
        match (s(want, "kind").as_str(), got) {
            ("default", Ok(Decision::Default)) => {}
            ("disarmed", Ok(Decision::Disarmed(b))) => assert_eq!(b, s(want, "backend"), "{name}"),
            ("bound", Ok(Decision::Bound(b))) => assert_eq!(b.model_id, s(want, "model_id"), "{name}"),
            ("refused", Err(why)) => assert!(why.contains(&s(want, "contains")), "{name}: {why}"),
            (kind, got) => panic!("{name}: expected {kind}, got {got:?}"),
        }
    }
}


#[test]
fn a_local_binding_carries_a_low_temperature_a_cloud_one_none() {
    // Client bench 2026-10-15: one model scored 9/11 then 6/11 at Ollama's default temperature.
    let local = |extra: &[(&str, &str)]| {
        let mut e = ARMED.to_vec();
        e.extend_from_slice(extra);
        match decide(LOCAL_CELL, &register(), env(&e)).unwrap() { Decision::Bound(b) => b, d => panic!("{d:?}") }
    };
    assert_eq!(local(&[]).temperature, Some(0.3));
    assert_eq!(local(&[("NOS_LOCAL_TEMPERATURE", "0.1")]).temperature, Some(0.1));
    assert_eq!(local(&[("NOS_LOCAL_TEMPERATURE", "warm")]).temperature, Some(0.3), "an unreadable value keeps the default");
    match resolve(&repo(), "iris", env(EU)).unwrap() {
        Decision::Bound(b) => assert_eq!(b.temperature, None, "the cloud row keeps its own default"),
        d => panic!("{d:?}"),
    }
}

#[test]
fn a_local_binding_carries_a_seed_only_when_one_is_set() {
    // A bench run is repeatable only when the sampler is: same seed, same digest, same prompt.
    let local = |extra: &[(&str, &str)]| {
        let mut e = ARMED.to_vec();
        e.extend_from_slice(extra);
        match decide(LOCAL_CELL, &register(), env(&e)).unwrap() { Decision::Bound(b) => b, d => panic!("{d:?}") }
    };
    assert_eq!(local(&[]).seed, None, "no seed unless the operator asks for one");
    assert_eq!(local(&[("NOS_LOCAL_SEED", "")]).seed, None, "the plist's empty default is unset");
    assert_eq!(local(&[("NOS_LOCAL_SEED", "42")]).seed, Some(42));
    assert_eq!(local(&[("NOS_LOCAL_SEED", "lucky")]).seed, None, "an unreadable value is unset");
    // Ollama reads seed as a Go int: past i64::MAX the request is refused before it samples.
    assert_eq!(local(&[("NOS_LOCAL_SEED", "9223372036854775807")]).seed, Some(i64::MAX as u64));
    assert_eq!(local(&[("NOS_LOCAL_SEED", "9223372036854775808")]).seed, None, "out of Ollama's range is unset");
    match resolve(&repo(), "iris", env(&[("NOS_ARMED_BACKENDS", "mistral-eu"), ("NOS_MISTRAL_MODEL", "m"),
                                         ("nos:mistral_api_key", "k"), ("NOS_LOCAL_SEED", "42")])).unwrap() {
        Decision::Bound(b) => assert_eq!(b.seed, None, "a cloud row keeps its own sampler"),
        d => panic!("{d:?}"),
    }
}

/// tests/binding-cases.yml `sizes:` — the floors tools/nos_cell_binding.py and job_readiness.py also judge.
#[test]
fn binding_judges_size_like_the_shared_cases() {
    use serde_yaml_ng::Value;
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/binding-cases.yml");
    let doc: Value = serde_yaml_ng::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let floor = |k: &str| doc["floors"][k].as_f64().unwrap();
    for case in doc["sizes"].as_sequence().unwrap() {
        let s = |k: &str| case.get(k).and_then(Value::as_str).unwrap_or_default().to_string();
        let (got, text) = match size_floor(&s("model"), floor("min_b"), floor("warn_b")) {
            Err(why) => ("refused", why),
            Ok(Some(warn)) => ("warned", warn),
            Ok(None) => ("silent", String::new()),
        };
        assert_eq!(got, s("expect"), "{}: {text}", s("model"));
        assert!(text.contains(&s("contains")), "{}: {text}", s("model"));
    }
}

// --- W5: the rows a person may pick for Iris in a session ---

/// A cell that allows a non-EU row beside the EU one, under an EU claim.
const PICKY_CELL: &str = "
name: c
model: {primary: openai-sonnet, backend: mistral-eu, backends_allowed: [mistral-eu, minimax]}
gdpr: {processors: [{name: Mistral AI SAS}, {name: MiniMax}], transfers_outside_eu: false}
";

#[test]
fn picks_are_the_allowed_rows_each_bound_or_refused_by_the_gates() {
    let iris = std::fs::read_to_string(repo().join("files/anatomy/agents/iris/agent.yml")).unwrap();
    let p = thalamus::binding::picks(&iris, &register(), env(ARMED));
    assert_eq!(p.iter().map(|p| p.row.as_str()).collect::<Vec<_>>(), ["mistral-eu", "ollama", "anthropic-api", "minimax-api"], "backends_allowed, in order");
    assert!(p[0].bound.as_ref().is_err_and(|w| w.contains("not armed")), "an unarmed row is refused: {:?}", p[0].bound);
    assert!(p[1].bound.as_ref().is_ok_and(|b| b.local && b.model_id == "qwen3:14b"), "{:?}", p[1].bound);
    assert_eq!((p[0].processor.as_str(), p[0].outside_eu), ("Mistral AI SAS", false));
    assert_eq!((p[1].processor.as_str(), p[1].outside_eu), ("This host (on-device, Ollama)", false));
}

#[test]
fn a_non_eu_pick_is_refused_by_the_posture() {
    let armed = [("NOS_ARMED_BACKENDS", "mistral-eu minimax"), ("NOS_GDPR_POSTURE", "standard")];
    let p = thalamus::binding::picks(PICKY_CELL, &register(), env(&armed));
    let minimax = p.iter().find(|p| p.row == "minimax").unwrap();
    assert!(minimax.outside_eu && minimax.processor == "MiniMax");
    let why = minimax.bound.as_ref().unwrap_err();
    assert!(why.contains("gdpr_posture") && why.contains("'standard'") && why.contains("minimax"), "{why}");
}

/// Every row iris allows, armed and keyed (ruling 2026-10-17: the two non-EU cloud rows beside the EU ones).
const ALL_ROWS: &[(&str, &str)] = &[("NOS_ARMED_BACKENDS", "mistral-eu ollama anthropic-api minimax-api"),
    ("NOS_MISTRAL_MODEL", "mistral-large-latest"), ("nos:mistral_api_key", "sk-eu-test"), ("NOS_LOCAL_MODEL", "qwen3:14b"),
    ("NOS_ANTHROPIC_API_MODEL", "claude-haiku-5-5"), ("nos:anthropic_api_key", "sk-ant-test"),
    ("NOS_MINIMAX_MODEL", "MiniMax-M2"), ("nos:minimax_api_key", "sk-mm-test")];

fn iris_picks(posture: &str) -> Vec<thalamus::binding::Pick> {
    let iris = std::fs::read_to_string(repo().join("files/anatomy/agents/iris/agent.yml")).unwrap();
    let e = [ALL_ROWS, &[("NOS_GDPR_POSTURE", posture)]].concat();
    thalamus::binding::picks(&iris, &register(), env(&e))
}

#[test]
fn iris_picks_the_non_eu_cloud_rows_only_at_posture_none() {
    let p = iris_picks("none");
    let row = |n: &str| p.iter().find(|p| p.row == n).unwrap_or_else(|| panic!("iris does not allow {n}: {p:?}"));
    let a = row("anthropic-api");
    assert!(a.outside_eu && a.processor.contains("Anthropic"), "{a:?}");
    let b = a.bound.as_ref().unwrap();
    assert_eq!((b.base_url.as_str(), b.model_id.as_str(), b.auth_token.as_str(), b.local),
               ("https://api.anthropic.com/v1", "claude-haiku-5-5", "sk-ant-test", false));
    let m = row("minimax-api");
    assert!(m.outside_eu && m.processor.contains("MiniMax"), "{m:?}");
    let b = m.bound.as_ref().unwrap();
    assert_eq!((b.base_url.as_str(), b.model_id.as_str(), b.auth_token.as_str()), ("https://api.minimax.io/v1", "MiniMax-M2", "sk-mm-test"));
    assert!(row("mistral-eu").bound.is_ok() && row("ollama").bound.is_ok(), "the EU rows still serve");
}

#[test]
fn iris_refuses_the_non_eu_cloud_rows_at_posture_standard() {
    let away: Vec<_> = iris_picks("standard").into_iter().filter(|p| p.row == "anthropic-api" || p.row == "minimax-api").collect();
    assert_eq!(away.len(), 2, "iris allows both non-EU cloud rows");
    for p in &away {
        let why = p.bound.as_ref().unwrap_err();
        assert!(why.contains("gdpr_posture") && why.contains("'standard'") && why.contains(&p.row), "{why}");
    }
    assert_eq!(iris_picks("standard").iter().filter(|p| p.bound.is_ok()).map(|p| p.row.as_str()).collect::<Vec<_>>(),
               ["mistral-eu", "ollama"], "a client host on standard keeps only the EU rows");
}
