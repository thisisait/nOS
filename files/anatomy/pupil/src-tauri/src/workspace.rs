//! The person's workspace layout, saved under the app data dir. Spec:
//! files/anatomy/contracts/workspace-layout.yml; gate:
//! tests/anatomy/test_workspace_layout_contract.py. No wire message reaches it.

use nos_contract::wire::WidgetSpec;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Layout {
    pub version: u32,
    pub active: String,
    pub chat: Chat,
    pub workspaces: Vec<Workspace>,
}

/// CSS px of the window; the webview clamps it on screen.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Chat {
    pub x: i64,
    pub y: i64,
    pub w: u32,
    pub h: u32,
    pub open: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Workspace {
    pub id: String,
    pub name: String,
    pub widgets: Vec<Widget>,
}

/// Grid units: 12 columns, rows of 40 px.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Widget {
    pub id: String,
    pub title: String,
    pub spec: WidgetSpec,
    pub x: u32,
    pub y: u32,
    pub w: u32,
    pub h: u32,
}

fn id_ok(s: &str) -> bool {
    (1..=64).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

impl Layout {
    pub fn empty() -> Layout {
        Layout {
            version: 1,
            active: "ws1".into(),
            chat: Chat { x: 0, y: 0, w: 0, h: 0, open: true },
            workspaces: vec![Workspace { id: "ws1".into(), name: "Workspace".into(), widgets: vec![] }],
        }
    }

    /// The caps serde cannot say; Err names the first that broke.
    pub fn check(&self) -> Result<(), String> {
        if self.version != 1 {
            return Err(format!("version {} is not 1", self.version));
        }
        if !(1..=12).contains(&self.workspaces.len()) {
            return Err(format!("{} workspaces, 1..12 allowed", self.workspaces.len()));
        }
        let mut ids = HashSet::new();
        for ws in &self.workspaces {
            if !id_ok(&ws.id) || !ids.insert(ws.id.as_str()) {
                return Err(format!("workspace id {:?} is not a unique [A-Za-z0-9_-]{{1,64}}", ws.id));
            }
            if ws.name.chars().count() > 40 {
                return Err(format!("workspace {} name over 40 chars", ws.id));
            }
            if ws.widgets.len() > 24 {
                return Err(format!("workspace {} has {} widgets, 24 allowed", ws.id, ws.widgets.len()));
            }
            for w in &ws.widgets {
                if !id_ok(&w.id) || !ids.insert(w.id.as_str()) {
                    return Err(format!("widget id {:?} is not a unique [A-Za-z0-9_-]{{1,64}}", w.id));
                }
                if w.title.chars().count() > 120 {
                    return Err(format!("widget {} title over 120 chars", w.id));
                }
                if !(2..=12).contains(&w.w) || w.x + w.w > 12 || w.y > 400 || !(2..=40).contains(&w.h) {
                    return Err(format!("widget {} at x{} y{} w{} h{} is outside the 12-column grid", w.id, w.x, w.y, w.w, w.h));
                }
            }
        }
        if !self.workspaces.iter().any(|ws| ws.id == self.active) {
            return Err(format!("active {:?} names no workspace", self.active));
        }
        Ok(())
    }
}

pub fn decode(text: &str) -> Result<Layout, String> {
    let l: Layout = serde_json::from_str(text).map_err(|e| format!("undecodable layout: {e}"))?;
    l.check()?;
    Ok(l)
}

/// No file is one empty workspace; a file that fails to read (invalid UTF-8 too) or decode is
/// renamed `.broken-<unix seconds>` and Err says so, so the caller starts empty and tells the person.
pub fn load(path: &Path) -> Result<Layout, String> {
    let read = match std::fs::read_to_string(path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Layout::empty()),
        r => r.map_err(|e| format!("unreadable: {e}")),
    };
    read.and_then(|text| decode(&text)).map_err(|why| {
        let ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        let aside = path.with_extension(format!("json.broken-{ts}"));
        let moved = std::fs::rename(path, &aside).map(|_| format!("; kept as {}", aside.display())).unwrap_or_default();
        format!("the saved layout was refused ({why}){moved}")
    })
}

/// Checked, then written to a 0600 tmp file and renamed over the old one.
pub fn save(path: &Path, l: &Layout) -> Result<(), String> {
    l.check()?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    }
    let tmp = path.with_extension("json.tmp");
    let body = serde_json::to_vec_pretty(l).map_err(|e| e.to_string())?;
    let mut f = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&tmp)
        .map_err(|e| format!("{}: {e}", tmp.display()))?;
    f.write_all(&body).and_then(|_| f.sync_all()).map_err(|e| format!("{}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("{}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    const FIXTURE: &str = include_str!("../../../contracts/workspace-layout.fixture.json");

    fn cases(key: &str) -> Vec<(String, serde_json::Value)> {
        let fx: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
        fx[key].as_array().unwrap().iter().map(|c| (c["case"].as_str().unwrap().to_string(), c["layout"].clone())).collect()
    }

    #[test]
    fn the_fixture_decodes_and_refuses() {
        for (case, v) in cases("samples") {
            let l = decode(&v.to_string()).unwrap_or_else(|e| panic!("{case}: {e}"));
            assert_eq!(serde_json::to_value(&l).unwrap(), v, "{case} does not re-encode to itself");
        }
        for (case, v) in cases("refused") {
            assert!(decode(&v.to_string()).is_err(), "{case} was accepted");
        }
    }

    #[test]
    fn a_v1_file_loads_as_v2_with_no_lens() {
        // workspace-layout.yml 1 -> 2 (iris-v3 B1): the missing lens is not a reason to set a file aside.
        let (_, mut v) = cases("samples").remove(1);
        v["version"] = 1.into();
        let l = decode(&v.to_string()).unwrap_or_else(|e| panic!("a v1 file was refused: {e}"));
        let back = serde_json::to_value(&l).unwrap();
        assert_eq!(back["version"], 2, "{back}");
        assert!(back["workspaces"].as_array().unwrap().iter().all(|w| w.get("lens").is_none()), "{back}");
    }

    #[test]
    fn the_poc_workspace_decodes() {
        // genui I5i: the layout poc.test.ts restores is one this decoder would load.
        let p = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../state/fixtures/genui-workspace-poc/workspace.json");
        let text = std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display()));
        let l = decode(&text).unwrap();
        assert_eq!(serde_json::to_value(&l).unwrap(), serde_json::from_str::<serde_json::Value>(&text).unwrap());
    }

    #[test]
    fn save_then_load_round_trips_at_0600() {
        let dir = std::env::temp_dir().join(format!("pupil-ws-{}", std::process::id()));
        let path = dir.join("workspaces.json");
        let (_, v) = cases("samples").remove(0);
        let l: Layout = serde_json::from_value(v).unwrap();
        save(&path, &l).unwrap();
        assert_eq!(load(&path).unwrap(), l);
        assert_eq!(std::fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_refused_layout_is_not_saved() {
        let dir = std::env::temp_dir().join(format!("pupil-ws-bad-{}", std::process::id()));
        let path = dir.join("workspaces.json");
        let mut l = Layout::empty();
        l.active = "nowhere".into();
        assert!(save(&path, &l).is_err());
        assert!(!path.exists());
    }

    #[test]
    fn a_broken_file_is_set_aside_and_no_file_is_empty() {
        let dir = std::env::temp_dir().join(format!("pupil-ws-broken-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("workspaces.json");
        assert_eq!(load(&path).unwrap(), Layout::empty());
        std::fs::write(&path, "{not json").unwrap();
        let why = load(&path).unwrap_err();
        assert!(why.contains("refused") && why.contains("broken-"), "{why}");
        assert!(!path.exists(), "the broken file is still where the next load reads it");
        let aside = std::fs::read_dir(&dir).unwrap().filter_map(|e| e.ok()).filter(|e| e.file_name().to_string_lossy().contains(".broken-")).count();
        assert_eq!(aside, 1);
        std::fs::remove_dir_all(dir).unwrap();
    }

    /// One sample layout with `edit` applied: Ok when the decoder takes it.
    fn takes(edit: impl Fn(&mut serde_json::Value)) -> Result<Layout, String> {
        let (_, mut v) = cases("samples").remove(0);
        edit(&mut v);
        decode(&v.to_string())
    }

    #[test]
    fn each_cap_takes_its_edge_and_refuses_one_past() {
        let w0 = |v: &mut serde_json::Value| v["workspaces"][0]["widgets"][0].clone();
        let widgets = |n: usize| move |v: &mut serde_json::Value| {
            let one = w0(v);
            v["workspaces"][0]["widgets"] = (0..n).map(|i| { let mut w = one.clone(); w["id"] = format!("n{i}").into(); w["y"] = (i * 2).into(); w }).collect();
        };
        let set = |ptr: &'static str, val: serde_json::Value| move |v: &mut serde_json::Value| *v.pointer_mut(ptr).unwrap() = val.clone();
        let edges: Vec<(&str, Box<dyn Fn(&mut serde_json::Value)>, Box<dyn Fn(&mut serde_json::Value)>)> = vec![
            ("24 widgets", Box::new(widgets(24)), Box::new(widgets(25))),
            ("title 120", Box::new(set("/workspaces/0/widgets/0/title", "t".repeat(120).into())),
                          Box::new(set("/workspaces/0/widgets/0/title", "t".repeat(121).into()))),
            ("name 40", Box::new(set("/workspaces/0/name", "n".repeat(40).into())), Box::new(set("/workspaces/0/name", "n".repeat(41).into()))),
            ("h 2", Box::new(set("/workspaces/0/widgets/0/h", 2.into())), Box::new(set("/workspaces/0/widgets/0/h", 1.into()))),
            ("h 40", Box::new(set("/workspaces/0/widgets/0/h", 40.into())), Box::new(set("/workspaces/0/widgets/0/h", 41.into()))),
            ("version 1", Box::new(set("/version", 1.into())), Box::new(set("/version", 2.into()))),
            ("id charset", Box::new(set("/workspaces/0/widgets/0/id", "A-z_9".into())), Box::new(set("/workspaces/0/widgets/0/id", "a.b".into()))),
            ("id 64", Box::new(set("/workspaces/0/widgets/0/id", "i".repeat(64).into())), Box::new(set("/workspaces/0/widgets/0/id", "i".repeat(65).into()))),
        ];
        for (cap, edge, past) in &edges {
            takes(edge).unwrap_or_else(|e| panic!("{cap}: the edge was refused: {e}"));
            assert!(takes(past).is_err(), "{cap}: one past the cap was accepted");
        }
    }

    #[test]
    fn an_unreadable_file_is_set_aside_too() {
        // Invalid UTF-8 failed read_to_string, was never renamed, and refused every launch after.
        let dir = std::env::temp_dir().join(format!("pupil-ws-utf8-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("workspaces.json");
        std::fs::write(&path, b"{\"version\": \xff}").unwrap();
        let why = load(&path).unwrap_err();
        assert!(why.contains("broken-"), "{why}");
        assert!(!path.exists(), "the unreadable file is still where the next load reads it");
        assert_eq!(load(&path).unwrap(), Layout::empty(), "the next load starts empty");
        std::fs::remove_dir_all(dir).unwrap();
    }
}
