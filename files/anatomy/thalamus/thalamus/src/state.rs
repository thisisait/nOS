//! The estate's runtime set-points and host organs (row medulla-settings).
//! One reader behind three doors: `medulla state`, the socket's `state`, GET /api/v1/admin/state.
//! read() writes nothing; a source it cannot read is null (UNKNOWN), never off. set_halt (increment 2) writes
//! the halt for serve alone, after its tier-1 and decider check; settings.rs (increment 3) the settings.
use nos_contract::wire::{ActRecord, EstateState, Organ, SetPoint};
use std::path::{Path, PathBuf};
use std::process::Command;

/// The labels the roles install (roles/pazny.<organ>/defaults/main.yml *_launchd_label).
const ORGANS: [(&str, &str); 6] = [
    ("thalamus", "eu.thisisait.nos.thalamus"),
    ("wing", "eu.thisisait.nos.wing"),
    ("pulse", "eu.thisisait.nos.pulse"),
    ("medulla-pulse", "eu.thisisait.nos.medulla-pulse"),
    ("bone", "eu.thisisait.nos.bone"),
    ("cortex", "eu.thisisait.nos.cortex"),
];

fn file(var: &str, rel: &str) -> PathBuf {
    std::env::var_os(var).filter(|v| !v.is_empty()).map(PathBuf::from).unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(rel))
}

/// The emergency halt's one file (row medulla-admin-halt): NOS_HALT_FILE, else ~/.nos/halt.
pub fn halt_file() -> PathBuf {
    file("NOS_HALT_FILE", ".nos/halt")
}

/// The loops maintenance pause (`nos loops pause`): NOS_LOOPS_PAUSED_FILE, else ~/.nos/loops-paused.
pub fn loops_paused_file() -> PathBuf {
    file("NOS_LOOPS_PAUSED_FILE", ".nos/loops-paused")
}

pub fn read() -> EstateState {
    let repo = std::env::var_os("NOS_REPO_ROOT").filter(|v| !v.is_empty()).map(PathBuf::from);
    EstateState { halt: set_point(&halt_file()), loops_paused: set_point(&loops_paused_file()), organs: organs(),
                  settings: crate::settings::read(repo.as_deref()), act: None }
}

/// The halt written (increment 2; serve's halt/lift_halt, after its tier-1 and decider check): the shape
/// tools/nos writes, {"by","at"} plus "reason", whole (tmp + rename). A halt already filed is kept as filed,
/// as the shell keeps it; lifting a halt that is not there is done.
pub fn set_halt(on: bool, by: &str, reason: Option<&str>) -> Result<(), String> {
    let path = halt_file();
    let e = |e: std::io::Error| format!("{}: {e}", path.display());
    if !on {
        return match std::fs::remove_file(&path) {
            Err(x) if x.kind() != std::io::ErrorKind::NotFound => Err(e(x)),
            _ => Ok(()),
        };
    }
    if path.is_file() {
        return Ok(());
    }
    std::fs::create_dir_all(path.parent().ok_or("the halt file has no directory")?).map_err(e)?;
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64);
    let mut v = serde_json::json!({"by": by, "at": crate::serve::iso(now)});
    if let Some(r) = reason.map(str::trim).filter(|r| !r.is_empty()) {
        v["reason"] = r.into();
    }
    let tmp = path.with_extension(format!("tmp-{}-{:?}", std::process::id(), std::thread::current().id()).replace(['(', ')'], ""));
    std::fs::write(&tmp, format!("{v}\n")).map_err(e)?;
    std::fs::rename(&tmp, &path).map_err(|x| {
        let _ = std::fs::remove_file(&tmp);
        e(x)
    })
}

/// The act sent over the nerve to the organ that writes the record (ruling 2026-10-25: the medulla sets,
/// Wing records): POST /api/v1/admin/{halt,resume} with the wing-halt bearer, read per act from
/// ~/.nos/secrets.yml as `nos halt` reads it, so no plist holds it. Not recorded is said, never fatal.
/// `by` is the person the kernel named on the socket; Wing records it as operator_username.
pub fn record(on: bool, by: &str, wing_url: &str) -> ActRecord {
    act(if on { "halt" } else { "resume" }, serde_json::json!({"by": by}), wing_url)
}

/// A setting's change, sent as the halt is: POST /api/v1/admin/setting {by, key, change}, which Wing
/// only records (the store is the set-point).
pub fn record_setting(key: &str, change: &serde_json::Value, by: &str, wing_url: &str) -> ActRecord {
    act("setting", serde_json::json!({"by": by, "key": key, "change": change}), wing_url)
}

fn act(verb: &str, body: serde_json::Value, wing_url: &str) -> ActRecord {
    let not = |why: String| ActRecord { recorded: false, why: Some(why) };
    let secrets = PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".nos/secrets.yml");
    let token = std::fs::read_to_string(&secrets).ok().and_then(|t| t.lines().find_map(|l| {
        Some(l.strip_prefix("wing_halt_token:")?.trim().trim_matches(['"', '\'']).to_string())
    }));
    let Some(token) = token.filter(|t| t.len() >= 32 && !t.starts_with("placeholder")) else {
        return not(format!("no wing_halt_token in {} (a converge with --tags wing mints it)", secrets.display()));
    };
    let base = if wing_url.is_empty() { "http://127.0.0.1:9000" } else { wing_url.trim_end_matches('/') };
    let url = format!("{base}/api/v1/admin/{verb}");
    match crate::serve::agent(10).post(&url).header("authorization", &format!("Bearer {token}")).send_json(body) {
        Err(e) => not(format!("Wing did not answer at {url}: {e}")),
        Ok(r) if r.status().is_success() => ActRecord { recorded: true, why: None },
        Ok(r) => not(format!("Wing refused it (HTTP {})", r.status().as_u16())),
    }
}

/// What `medulla state` prints: one line a set-point, one an organ; UNKNOWN said, never hidden.
pub fn lines(s: &EstateState) -> Vec<String> {
    let point = |name: &str, p: &SetPoint| match p.on {
        Some(true) => format!("{name}: ON since {}{} ({})", p.since.as_deref().unwrap_or("?"),
                              p.reason.as_deref().map(|r| format!(" — {r}")).unwrap_or_default(), p.file),
        Some(false) => format!("{name}: off (no file at {})", p.file),
        None => format!("{name}: UNKNOWN ({} unreadable)", p.file),
    };
    let mut out = vec![point("halt", &s.halt), point("loops paused", &s.loops_paused)];
    match &s.settings {
        None => out.push(format!("settings: UNKNOWN ({} unreadable)", crate::settings::GENOME)),
        Some(all) => out.extend(all.iter().map(|(k, v)| match v {
            serde_json::Value::Null => format!("setting {k}: UNKNOWN (its file unreadable, or MEDULLA_DATA_DIR unset)"),
            v => format!("setting {k}: {v}"),
        })),
    }
    out.extend(s.organs.iter().map(|o| {
        let r = match o.running { Some(true) => "running", Some(false) => "stopped", None => "UNKNOWN" };
        format!("organ {}: {r} ({})", o.name, o.label)
    }));
    out.extend(s.act.as_ref().map(|a| match &a.why {
        _ if a.recorded => "act: recorded by Wing".to_string(),
        why => format!("act: NOT recorded — {}", why.as_deref().unwrap_or("Wing did not say why")),
    }));
    out
}

/// On while the file exists, as every scheduler holds; since/reason from the halt's JSON
/// ({"by","at"}) or the pause's `since:` / `reason:` lines.
fn set_point(path: &Path) -> SetPoint {
    let mut p = SetPoint { on: None, since: None, reason: None, file: path.display().to_string() };
    match std::fs::metadata(path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => p.on = Some(false),
        Err(_) => {}
        Ok(m) => p.on = Some(m.is_file()),
    }
    if p.on != Some(true) {
        return p;
    }
    let Ok(text) = std::fs::read_to_string(path) else { return p };
    let words = |v: Option<&str>| v.map(str::trim).filter(|s| !s.is_empty()).map(str::to_owned);
    if let Ok(serde_json::Value::Object(o)) = serde_json::from_str(&text) {
        p.since = words(o.get("at").or(o.get("since")).and_then(|v| v.as_str()));
        p.reason = words(o.get("reason").and_then(|v| v.as_str()));
    } else {
        for line in text.lines() {
            p.since = p.since.take().or_else(|| words(line.strip_prefix("since:")));
            p.reason = p.reason.take().or_else(|| words(line.strip_prefix("reason:")));
        }
    }
    p
}

fn organs() -> Vec<Organ> {
    let running = if cfg!(target_os = "macos") { launchd() } else { systemd() };
    ORGANS.iter().zip(running).map(|((name, label), running)| Organ { name: (*name).into(), label: (*label).into(), running }).collect()
}

fn run(cmd: &str, args: &[&str]) -> Option<String> {
    let out = Command::new(cmd).args(args).output().ok().filter(|o| o.status.success())?;
    String::from_utf8(out.stdout).ok()
}

/// `launchctl list` once: a PID is running, "-" is loaded and stopped; not listed is unknown
/// (another domain, e.g. a system daemon, is not this list's to say).
fn launchd() -> Vec<Option<bool>> {
    let list = run("launchctl", &["list"]);
    ORGANS.iter().map(|(_, label)| {
        let row = list.as_deref()?.lines().map(|l| l.split('\t').collect::<Vec<_>>()).find(|c| c.len() == 3 && c[2] == *label)?;
        Some(row[0] != "-")
    }).collect()
}

/// `systemctl --user show` once: active is running, a loaded unit otherwise is stopped, not-found is unknown.
fn systemd() -> Vec<Option<bool>> {
    let units: Vec<String> = ORGANS.iter().map(|(_, l)| format!("{l}.service")).collect();
    let mut args = vec!["--user", "show", "--property=LoadState,ActiveState"];
    args.extend(units.iter().map(String::as_str));
    let Some(out) = run("systemctl", &args) else { return vec![None; ORGANS.len()] };
    let blocks: Vec<&str> = out.split("\n\n").collect();
    (0..ORGANS.len()).map(|i| {
        let b = blocks.get(i)?;
        let prop = |k: &str| b.lines().find_map(|l| l.strip_prefix(k)?.strip_prefix('='));
        (prop("LoadState")? == "loaded").then(|| prop("ActiveState") == Some("active"))
    }).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_organ_label_is_one_a_role_installs() {
        let roles = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../roles");
        let defaults: String = std::fs::read_dir(&roles).unwrap().flatten()
            .filter_map(|r| std::fs::read_to_string(r.path().join("defaults/main.yml")).ok()).collect();
        for (name, label) in ORGANS {
            assert!(defaults.contains(&format!("_launchd_label: \"{label}\"")), "{name}: no role defaults {label}");
        }
    }

    #[test]
    fn a_set_point_says_what_its_file_says() {
        let dir = std::env::temp_dir().join(format!("thalamus-state-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        assert_eq!(set_point(&dir.join("absent")).on, Some(false));
        assert_eq!(set_point(&dir).on, Some(false), "a directory holds nothing, as the schedulers' is_file says");
        std::fs::write(dir.join("halt"), "{\"by\": \"a\", \"at\": \"T1\"}").unwrap();
        let h = set_point(&dir.join("halt"));
        assert_eq!((h.on, h.since.as_deref(), h.reason), (Some(true), Some("T1"), None));
        std::fs::write(dir.join("lp"), "since: T2\nreason: up grade\n").unwrap();
        let l = set_point(&dir.join("lp"));
        assert_eq!((l.since.as_deref(), l.reason.as_deref()), (Some("T2"), Some("up grade")));
        use std::os::unix::fs::PermissionsExt;
        std::fs::create_dir_all(dir.join("locked")).unwrap();
        std::fs::set_permissions(dir.join("locked"), std::fs::Permissions::from_mode(0o000)).unwrap();
        assert_eq!(set_point(&dir.join("locked/halt")).on, None, "an unreadable source is UNKNOWN, never off");
        std::fs::set_permissions(dir.join("locked"), std::fs::Permissions::from_mode(0o700)).unwrap();
        let _ =std::fs::remove_dir_all(&dir);
    }
}
