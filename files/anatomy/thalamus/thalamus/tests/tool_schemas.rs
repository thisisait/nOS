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
