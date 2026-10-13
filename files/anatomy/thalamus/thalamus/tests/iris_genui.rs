//! Iris genui shows, drawn by the shell. Each fixture case is a real component:
//! Component::check accepts it, then shell::component_lines draws it. A value the
//! case expects and the renderer drops fails here. Scoring the YAML against itself
//! cannot fail, so this test never reads the expect list back out of the component.

use nos_contract::renderers::Component;
use std::path::Path;

fn repo() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../..")
}

fn shown(c: &Component) -> String {
    thalamus::shell::component_lines(c)
        .iter()
        .map(|l| l.spans.iter().flat_map(|s| s.content.chars()).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn every_fixture_case_is_checked_and_drawn() {
    let path = repo().join("state/fixtures/iris-genui-bench.yml");
    let raw = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let cases: Vec<serde_yaml_ng::Value> = serde_yaml_ng::from_str(&raw).unwrap();
    assert!(!cases.is_empty(), "the fixture has no cases");
    for case in &cases {
        let id = case["id"].as_str().unwrap_or_else(|| panic!("a case has no id"));
        let component: Component = serde_yaml_ng::from_value(case["component"].clone())
            .unwrap_or_else(|e| panic!("{id}: component does not decode: {e}"));
        let kind = serde_json::to_value(&component).unwrap()["kind"].as_str().unwrap().to_string();
        assert_eq!(kind, case["kind"].as_str().unwrap_or(""), "{id}: kind");
        component.check().unwrap_or_else(|e| panic!("{id}: check refused the case: {e}"));
        let drawn = shown(&component);
        let expect = case["expect"].as_sequence().unwrap_or_else(|| panic!("{id}: no expect list"));
        assert!(!expect.is_empty(), "{id}: nothing expected, so a drop cannot fail");
        for bit in expect {
            let bit = bit.as_str().unwrap_or_else(|| panic!("{id}: expect entry is not a string"));
            assert!(!bit.is_empty(), "{id}: an empty expect cannot fail");
            assert!(drawn.contains(bit), "{id}: renderer dropped {bit:?}\n{drawn}");
        }
    }
}

/// A show kind with no bench case is a renderer the bench never draws.
#[test]
fn every_show_kind_has_a_bench_case() {
    let raw = std::fs::read_to_string(repo().join("state/fixtures/iris-genui-bench.yml")).unwrap();
    let cases: Vec<serde_yaml_ng::Value> = serde_yaml_ng::from_str(&raw).unwrap();
    let benched: std::collections::BTreeSet<&str> = cases.iter().filter_map(|c| c["kind"].as_str()).collect();
    let missing: Vec<&str> = thalamus::serve::SHOW_KINDS.iter().copied().filter(|k| !benched.contains(k)).collect();
    assert!(missing.is_empty(), "show kinds with no case in iris-genui-bench.yml: {missing:?}");
}
