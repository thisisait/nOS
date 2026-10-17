//! tools/oneshot-poc.py validates its plans against state/fixtures/oneshot/thalamus-tools.json:
//! that copy must be serve's tools() byte for byte, or a plan "valid" there is not valid here.
//! THALAMUS_WRITE_TOOLS=1 rewrites the copy after a deliberate schema change.

use std::path::PathBuf;

#[test]
fn the_oneshot_copy_is_serves_tool_list() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../../state/fixtures/oneshot/thalamus-tools.json");
    let want = serde_json::to_string_pretty(&thalamus::serve::tools()).unwrap() + "\n";
    if std::env::var("THALAMUS_WRITE_TOOLS").as_deref() == Ok("1") {
        std::fs::write(&path, &want).unwrap();
    }
    let have = std::fs::read_to_string(&path).unwrap_or_default();
    assert!(have == want, "{} differs from serve::tools(); rerun with THALAMUS_WRITE_TOOLS=1", path.display());
}

/// What Ollama keeps of a tool property (api/types.go ToolProperty, main 2026-10): anyOf, type,
/// items (verbatim), description, enum, properties (each projected again) and required. oneOf,
/// const and additionalProperties are dropped before the model's template ever sees the tool.
fn ollama_kept(p: &serde_json::Value) -> serde_json::Value {
    let mut out = serde_json::Map::new();
    for k in ["type", "items", "description", "enum", "required"] {
        if let Some(v) = p.get(k) {
            out.insert(k.into(), v.clone());
        }
    }
    if let Some(a) = p.get("anyOf").and_then(|a| a.as_array()) {
        out.insert("anyOf".into(), a.iter().map(ollama_kept).collect());
    }
    if let Some(m) = p.get("properties").and_then(|m| m.as_object()) {
        out.insert("properties".into(), m.iter().map(|(k, v)| (k.clone(), ollama_kept(v))).collect());
    }
    out.into()
}

fn said(p: &serde_json::Value, path: &str, bare: &mut Vec<String>) {
    if p.get("type").is_none() && p.get("anyOf").is_none() && p.get("enum").is_none() {
        bare.push(path.into());
    }
    for (k, v) in p.get("properties").and_then(|m| m.as_object()).into_iter().flatten() {
        said(v, &format!("{path}.{k}"), bare);
    }
}

/// Live 2026-10-17, qwen3.5:9b on Ollama: chart 1/9, kpi 0/7, choice 0/7 while the flat card tools
/// passed. show's `component` is a oneOf of const-tagged branches, and Ollama keeps neither, so the
/// model was handed `component: {}` and never saw a kind or a shape. Every property survives the
/// projection with a type, and show's component carries its kinds and each kind's shape.
#[test]
fn every_tool_property_survives_what_ollama_keeps() {
    let mut bare = vec![];
    for t in thalamus::serve::tools().as_array().unwrap() {
        let f = &t["function"];
        said(&ollama_kept(&f["parameters"]), f["name"].as_str().unwrap(), &mut bare);
    }
    assert!(bare.is_empty(), "the model is handed these as {{}} by Ollama: {bare:?}");
    let show = thalamus::serve::tools().as_array().unwrap().iter().find(|t| t["function"]["name"] == "show").unwrap().clone();
    let c = ollama_kept(&show["function"]["parameters"])["properties"]["component"].clone();
    let kinds: Vec<&str> = c["properties"]["kind"]["enum"].as_array().into_iter().flatten().filter_map(|k| k.as_str()).collect();
    assert_eq!(kinds, thalamus::serve::SHOW_KINDS, "the kinds survive as an enum: {c}");
    let told = c.to_string();
    for (kind, shape) in thalamus::serve::SHOW_SHAPE {
        assert!(told.contains(&shape.replace('"', "\\\"")), "{kind}'s shape is not told: {told}");
    }
}
