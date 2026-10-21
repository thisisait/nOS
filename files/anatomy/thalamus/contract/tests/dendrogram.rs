//! iris-agent-dendrogram inc.1: an agent run's tree is one root, every parent in it, no cycle.
use nos_contract::renderers::Component;
use serde_json::{json, Value};

fn node(id: &str, parent: Option<&str>) -> Value {
    let mut n = json!({"id": id, "kind": "turn", "name": id, "status": "ok"});
    if let Some(p) = parent {
        n["parent"] = json!(p);
    }
    n
}

fn check(root: &str, nodes: Vec<Value>) -> Result<(), String> {
    let c: Component = serde_json::from_value(json!({"kind": "dendrogram", "props": {"root": root, "nodes": nodes, "hidden": 0}}))
        .map_err(|e| format!("undecodable: {e}"))?;
    c.check()
}

#[test]
fn a_run_tree_with_one_root_draws() {
    let r = check("s", vec![node("s", None), node("t", Some("s")), node("u", Some("t"))]);
    assert_eq!(r, Ok(()));
}

#[test]
fn a_parent_not_in_the_tree_is_refused() {
    let e = check("s", vec![node("s", None), node("t", Some("ghost"))]).unwrap_err();
    assert!(e.contains("parent not in the tree"), "{e}");
}

#[test]
fn two_roots_are_refused() {
    let e = check("s", vec![node("s", None), node("t", None)]).unwrap_err();
    assert!(e.contains("one root"), "{e}");
}

#[test]
fn a_cycle_is_refused() {
    let e = check("s", vec![node("s", None), node("a", Some("b")), node("b", Some("a"))]).unwrap_err();
    assert!(e.contains("cycle"), "{e}");
}

#[test]
fn root_names_the_parentless_node() {
    let e = check("t", vec![node("s", None), node("t", Some("s"))]).unwrap_err();
    assert!(e.contains("root"), "{e}");
}

#[test]
fn over_200_nodes_is_refused() {
    let mut nodes = vec![node("s", None)];
    nodes.extend((0..200).map(|i| node(&format!("n{i}"), Some("s"))));
    let e = check("s", nodes).unwrap_err();
    assert!(e.contains("at most 200"), "{e}");
}

#[test]
fn a_node_that_ends_before_it_starts_is_refused() {
    let mut n = node("s", None);
    n["started"] = json!("2026-10-21T10:00:00Z");
    n["ended"] = json!("2026-10-21T09:00:00Z");
    let e = check("s", vec![n]).unwrap_err();
    assert!(e.contains("ends before it starts"), "{e}");
}
