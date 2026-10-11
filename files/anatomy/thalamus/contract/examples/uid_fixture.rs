//! Runs the crate on the face-wing fixture for tests/anatomy/test_face_wing_contract.py.
use nos_contract::uid;
use serde_json::{json, Value};

fn main() {
    let path = std::env::args().nth(1).expect("usage: uid_fixture <fixture.json>");
    let fx: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let s = |v: &Value, k: &str| v[k].as_str().unwrap_or("").to_string();
    let fold: Vec<String> = fx["fold"].as_array().unwrap().iter().map(|c| uid::fold(&s(c, "in"))).collect();
    let claims: Vec<String> = fx["claims"].as_array().unwrap().iter()
        .map(|c| uid::canonical(&s(c, "username"), &s(c, "email"), &s(c, "raw_uid"))).collect();
    let refuses: Vec<bool> = fx["not_canonical"].as_array().unwrap().iter()
        .map(|u| !uid::is_canonical(u.as_str().unwrap_or(""))).collect();
    println!("{}", json!({"fold": fold, "claims": claims, "refuses": refuses}));
}
