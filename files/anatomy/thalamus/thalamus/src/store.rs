//! What the thalamus holds per person beside the ledger: <data-dir>/people/<uid>/<name>.json, the
//! workspace and the conversation. 0700 dir, 0600 files written whole (tmp + rename), as the pupil's
//! workspace.rs; a file that does not decode is set aside as .broken-<unix seconds> and said.

use serde_json::Value;
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

/// `uid` is canonical ([a-z0-9-], serve::Person::uid), so it never leaves people/.
pub fn path(data: &Path, uid: &str, name: &str) -> PathBuf {
    data.join("people").join(uid).join(format!("{name}.json"))
}

/// None when there is no file; Err (the file set aside) when it does not read or decode.
pub fn read(path: &Path) -> Result<Option<Value>, String> {
    let text = match std::fs::read_to_string(path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        r => r.map_err(|e| format!("unreadable: {e}")),
    };
    text.and_then(|t| serde_json::from_str(&t).map_err(|e| format!("undecodable: {e}"))).map(Some).map_err(|why| {
        let ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        let aside = path.with_extension(format!("json.broken-{ts}"));
        let moved = std::fs::rename(path, &aside).map(|_| format!("; kept as {}", aside.display())).unwrap_or_default();
        format!("{} is broken ({why}){moved}", path.display())
    })
}

pub fn write(path: &Path, v: &Value) -> Result<(), String> {
    let dir = path.parent().ok_or("no directory")?;
    // people/ then people/<uid>/, each set 0700: the umask (bind()'s 0177 while it binds) narrows a mode asked.
    for d in [dir.parent().unwrap_or(dir), dir] {
        let e = |e: std::io::Error| format!("{}: {e}", d.display());
        std::fs::DirBuilder::new().recursive(true).mode(0o700).create(d).map_err(e)?;
        std::fs::set_permissions(d, std::fs::Permissions::from_mode(0o700)).map_err(e)?;
    }
    // Per thread: two connections of one person never share a tmp file.
    let tmp = path.with_extension(format!("json.tmp-{:?}", std::thread::current().id()).replace(['(', ')'], ""));
    let mut f = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&tmp)
        .map_err(|e| format!("{}: {e}", tmp.display()))?;
    f.write_all(v.to_string().as_bytes()).and_then(|_| f.sync_all()).map_err(|e| format!("{}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("{}: {e}", path.display()))
}
