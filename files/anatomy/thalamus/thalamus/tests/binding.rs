//! The thalamus binds a cell the way BindingResolver.php does, against the REAL
//! register (state/habitat/llm-backends.yml) and the real iris cell — never a copy.

use std::path::{Path, PathBuf};
use thalamus::binding::{decide, resolve, Decision};

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
fn binding_iris_armed_is_bound_to_the_local_model_with_no_key() {
    match resolve(&repo(), "iris", env(ARMED)).unwrap() {
        Decision::Bound(b) => {
            assert_eq!(b.name, "ollama");
            assert_eq!(b.base_url, "http://127.0.0.1:11434/v1");
            assert_eq!(b.auth_token, "");
            assert_eq!(b.model_id, "qwen3:14b");
        }
        d => panic!("iris armed must bind, got {d:?}"),
    }
}

#[test]
fn binding_disarmed_falls_to_the_default_and_names_no_model() {
    let d = decide(MINIMAX_CELL, &register(), env(&[("NOS_MINIMAX_MODEL", "m1")])).unwrap();
    assert!(matches!(d, Decision::Disarmed(ref n) if n == "minimax"), "{d:?}");
}

#[test]
fn binding_iris_disarmed_refuses_rather_than_degrade() {
    let why = refused(resolve(&repo(), "iris", env(&[("NOS_LOCAL_MODEL", "qwen3:14b")])));
    assert!(why.contains("not armed"), "{why}");
}

#[test]
fn binding_armed_with_an_empty_model_env_refuses() {
    let why = refused(resolve(&repo(), "iris", env(&[("NOS_ARMED_BACKENDS", "ollama")])));
    assert!(why.contains("NOS_LOCAL_MODEL"), "{why}");
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
    let why = refused(resolve(Path::new("/nonexistent"), "iris", env(ARMED)));
    assert!(!why.is_empty());
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
