//! The estate's settings (row medulla-settings, increment 3): the set-points state/genome/settings.yml
//! names, held as MEDULLA_DATA_DIR/estate/<name>.json (store.rs writes it: 0700/0600, tmp + rename).
//! serve alone writes one, after its tier-1 and decider check; a reader reads the file and never
//! repairs it. A key the genome does not name is refused.
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

pub const GENOME: &str = "state/genome/settings.yml";

pub struct Setting {
    pub name: String,
    pub scope: String,
    pub kind: String,
    pub default: Value,
    pub tier: u64,
}

pub fn genome(repo: &Path) -> Result<Vec<Setting>, String> {
    let path = repo.join(GENOME);
    let text = std::fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    let doc: Value = serde_yaml_ng::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
    let all = doc["settings"].as_object().ok_or_else(|| format!("{}: no settings map", path.display()))?;
    Ok(all.iter().map(|(name, s)| Setting {
        name: name.clone(),
        scope: s["scope"].as_str().unwrap_or_default().into(),
        kind: s["type"].as_str().unwrap_or_default().into(),
        default: s["default"].clone(),
        tier: s["set_by"]["tier"].as_u64().unwrap_or(0),
    }).collect())
}

/// MEDULLA_DATA_DIR (default.config.yml medulla_data_dir), in the thalamus's, Wing's and medulla-pulse's
/// env; unset is no store.
pub fn data_dir() -> Option<PathBuf> {
    std::env::var_os("MEDULLA_DATA_DIR").filter(|v| !v.is_empty()).map(PathBuf::from)
}

pub fn estate_file(data: &Path, name: &str) -> PathBuf {
    data.join("estate").join(format!("{name}.json"))
}

/// Ok(None) when there is no file; Err when it does not read or decode, the file left as it is.
fn load(path: &Path) -> Result<Option<Value>, String> {
    match std::fs::read_to_string(path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("{}: {e}", path.display())),
        Ok(t) => serde_json::from_str(&t).map(Some).map_err(|e| format!("{} does not decode: {e}", path.display())),
    }
}

/// The state's `settings`: each estate setting's value (its default while no file holds one), null when
/// its file cannot be read or no store is rendered; None when the genome cannot be read.
pub fn read(repo: Option<&Path>) -> Option<BTreeMap<String, Value>> {
    let data = data_dir();
    Some(genome(repo?).ok()?.into_iter().filter(|s| s.scope == "estate").map(|s| {
        let v = match data.as_deref().map(|d| load(&estate_file(d, &s.name))) {
            Some(Ok(Some(v))) => v,
            Some(Ok(None)) => s.default,
            None | Some(Err(_)) => Value::Null,
        };
        (s.name, v)
    }).collect())
}

/// Why `job` is held by pulse.paused, or None. A store that does not read holds every job (fails closed),
/// as PulseRepository::listDue does.
pub fn paused(job: &str) -> Option<String> {
    match load(&estate_file(&data_dir()?, "pulse.paused")) {
        Ok(None) => None,
        Ok(Some(Value::Object(m))) => m.get(job).map(|e| format!("paused by {}", e["by"].as_str().unwrap_or("?"))),
        Ok(Some(_)) => Some("pulse.paused holds no map".into()),
        Err(e) => Some(format!("pulse.paused unreadable ({e})")),
    }
}

/// One store, one writer at a time: a change reads, merges and writes the whole file.
static WRITING: Mutex<()> = Mutex::new(());

/// One change, applied by serve after its tier-1 and decider check. A map setting changes per entry:
/// {entry: {reason?}} sets it stamped {by, at, reason?}, {entry: null} removes it. Returns the change as
/// written, which is what Wing is sent. Refused: a key the genome does not name, a type not served yet,
/// a bad shape, no store, or a file that does not read (left as it is).
pub fn set(repo: &Path, key: &str, change: &Value, by: &str) -> Result<Value, String> {
    let g = genome(repo).map_err(|e| format!("the settings genome is unreadable ({e}), so no key is known"))?;
    let s = g.iter().find(|s| s.name == key).ok_or_else(|| format!("{key} is no setting the genome names ({GENOME})"))?;
    // ponytail: only the estate-map, tier-1 shape is served; a person scope or a scalar adds its branch here.
    if (s.scope.as_str(), s.kind.as_str(), s.tier) != ("estate", "map", 1) {
        return Err(format!("{key} is a {} {} set by tier {}: not served yet", s.scope, s.kind, s.tier));
    }
    let data = data_dir().ok_or("MEDULLA_DATA_DIR is unset (a converge with --tags thalamus renders it), so there is no store")?;
    let change = change.as_object().filter(|c| !c.is_empty() && c.len() <= 50)
        .ok_or_else(|| format!("{key}: a change is an object of 1 to 50 entries"))?;
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64);
    let at = crate::serve::iso(now);
    let mut stamped = Map::new();
    for (entry, v) in change {
        if entry.is_empty() || entry.len() > 128 || !entry.bytes().all(|b| b.is_ascii_alphanumeric() || b":._-".contains(&b)) {
            return Err(format!("{entry:?} is no entry name (letters, digits and :._- up to 128)"));
        }
        let e = match v {
            Value::Null => Value::Null,
            Value::Object(o) if o.keys().all(|k| k == "reason") => {
                let mut e = json!({"by": by, "at": at});
                match o.get("reason") {
                    None => {}
                    Some(Value::String(r)) if r.chars().count() <= 300 && !r.contains('\n') => {
                        if !r.trim().is_empty() {
                            e["reason"] = r.trim().into();
                        }
                    }
                    Some(_) => return Err(format!("{key}.{entry}: a reason is one line of at most 300 chars")),
                }
                e
            }
            _ => return Err(format!("{key}.{entry}: an entry is {{\"reason\"?}} or null; serve names who and when")),
        };
        stamped.insert(entry.clone(), e);
    }
    let _one = WRITING.lock().unwrap_or_else(|p| p.into_inner());
    let path = estate_file(&data, key);
    let mut value = load(&path)?.unwrap_or_else(|| s.default.clone());
    let map = value.as_object_mut().ok_or_else(|| format!("{} holds no map; it is left as it is", path.display()))?;
    for (k, v) in &stamped {
        if v.is_null() {
            map.remove(k);
        } else {
            map.insert(k.clone(), v.clone());
        }
    }
    crate::store::write(&path, &value)?;
    Ok(Value::Object(stamped))
}
