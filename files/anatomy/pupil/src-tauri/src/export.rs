//! A widget's rows as a CSV file the person asked for: written only on their click, as a new file
//! in their Downloads folder, never over one that is there. The webview builds the text (csv.ts).

use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

const MAX: usize = 4 * 1024 * 1024;

/// `<dir>/<name>.csv`, else `<name>-2.csv` ... `-99`; mode 0600. A name is [A-Za-z0-9_-]{1,64}, so never a path.
pub fn save_csv(dir: &Path, name: &str, csv: &str) -> Result<PathBuf, String> {
    let ok = (1..=64).contains(&name.len()) && name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
    if !ok {
        return Err(format!("a csv name is [A-Za-z0-9_-]{{1,64}}, not {name:?}"));
    }
    if csv.len() > MAX {
        return Err(format!("a csv is at most {MAX} bytes, not {}", csv.len()));
    }
    for n in 1..100 {
        let path = dir.join(if n == 1 { format!("{name}.csv") } else { format!("{name}-{n}.csv") });
        match std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&path) {
            Ok(mut f) => return f.write_all(csv.as_bytes()).map(|_| path.clone()).map_err(|e| format!("{}: {e}", path.display())),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(format!("{}: {e}", path.display())),
        }
    }
    Err(format!("{name}.csv to {name}-99.csv all exist in {}", dir.display()))
}
