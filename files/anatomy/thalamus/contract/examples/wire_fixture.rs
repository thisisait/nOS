//! Runs the wire on the thalamus-shell fixture for tests/anatomy/test_thalamus_shell_contract.py:
//! samples decode and re-encode, refused lines decode to `refused` (shell) or Err (thalamus).
use nos_contract::wire::{decode_to_shell, decode_to_thalamus};
use serde_json::{json, Value};

fn main() {
    let path = std::env::args().nth(1).expect("usage: wire_fixture <fixture.json>");
    let fx: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let cases = |k: &str| fx[k].as_array().unwrap().clone();
    let to_value = |r: Result<Value, String>| r.unwrap_or_else(|e| json!({ "error": e }));
    let thal = |line: &str| to_value(decode_to_thalamus(line).map(|m| serde_json::to_value(m).unwrap()));
    let shell = |line: &str| serde_json::to_value(decode_to_shell(line)).unwrap();
    let line = |c: &Value, k: &str| c[k].as_str().unwrap().to_string();
    let msg = |c: &Value| c["msg"].to_string();
    println!("{}", json!({
        "to_thalamus": cases("to_thalamus").iter().map(|c| thal(&msg(c))).collect::<Vec<_>>(),
        "to_shell": cases("to_shell").iter().map(|c| shell(&msg(c))).collect::<Vec<_>>(),
        "refused": cases("refused").iter().map(|c| shell(&line(c, "line"))).collect::<Vec<_>>(),
        "refused_to_thalamus": cases("refused_to_thalamus").iter().map(|c| thal(&line(c, "line"))).collect::<Vec<_>>(),
    }));
}
