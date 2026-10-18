//! The person's workspace layout, saved under the app data dir. Spec:
//! files/anatomy/contracts/workspace-layout.yml; gate:
//! tests/anatomy/test_workspace_layout_contract.py. No wire message reaches it.

use nos_contract::renderers::{check_lens, Lens};
use nos_contract::wire::WidgetSpec;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
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
    /// Reserved for nested boards: checked (exists, no cycle, depth <= 6), not drawn yet.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent: Option<String>,
    /// The tab's shared filter (a dashboard's lens); the webview merges it at send time.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub lens: Vec<Lens>,
    /// Where the canvas was left: the screen px of world 0,0, and the zoom.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub view: Option<View>,
    pub items: Vec<Item>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct View {
    pub x: i64,
    pub y: i64,
    pub zoom: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Widget,
    Heading,
    Frame,
}

/// World px. A widget has a title and a spec, a heading a text, a frame a title.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Item {
    pub id: String,
    pub kind: Kind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spec: Option<WidgetSpec>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    pub x: i64,
    pub y: i64,
    pub w: i64,
    pub h: i64,
}

/// A v1/v2 file: widgets in grid units (12 columns, rows of 40 px). Read only, never written.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Old {
    version: u32,
    active: String,
    chat: Chat,
    workspaces: Vec<OldSpace>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OldSpace {
    id: String,
    name: String,
    #[serde(default)]
    lens: Vec<Lens>,
    widgets: Vec<OldWidget>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OldWidget {
    id: String,
    title: String,
    spec: WidgetSpec,
    x: u32,
    y: u32,
    w: u32,
    h: u32,
}

/// Grid units as world px: a column was 100 px on a 1232 px panel, a row 40 px + an 8 px gap.
impl From<Old> for Layout {
    fn from(o: Old) -> Layout {
        let items = |ws: Vec<OldWidget>| {
            ws.into_iter()
                .map(|w| Item {
                    id: w.id,
                    kind: Kind::Widget,
                    title: Some(w.title),
                    spec: Some(w.spec),
                    text: None,
                    x: i64::from(w.x) * 100,
                    y: i64::from(w.y) * 48,
                    w: i64::from(w.w) * 100 - 8,
                    h: i64::from(w.h) * 48 - 8,
                })
                .collect()
        };
        Layout {
            version: 3,
            active: o.active,
            chat: o.chat,
            workspaces: o
                .workspaces
                .into_iter()
                .map(|s| Workspace { id: s.id, name: s.name, parent: None, lens: s.lens, view: None, items: items(s.widgets) })
                .collect(),
        }
    }
}

fn id_ok(s: &str) -> bool {
    (1..=64).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn text_ok(s: &Option<String>) -> bool {
    s.as_ref().is_some_and(|t| t.chars().count() <= 120)
}

impl Item {
    fn check(&self) -> Result<(), String> {
        let (title, spec, text) = (self.title.is_some(), self.spec.is_some(), self.text.is_some());
        let shaped = match self.kind {
            Kind::Widget => text_ok(&self.title) && spec && !text,
            Kind::Heading => text_ok(&self.text) && !title && !spec,
            Kind::Frame => text_ok(&self.title) && !spec && !text,
        };
        if !shaped {
            return Err(format!("item {} is not a {:?} (widget: title + spec; heading: text; frame: title; each at most 120 chars)", self.id, self.kind));
        }
        if self.x.abs() > 100_000 || self.y.abs() > 100_000 || !(80..=4000).contains(&self.w) || !(32..=4000).contains(&self.h) {
            return Err(format!("item {} at x{} y{} w{} h{} is outside |x|,|y| <= 100000, w 80..4000, h 32..4000", self.id, self.x, self.y, self.w, self.h));
        }
        Ok(())
    }
}

impl Layout {
    pub fn empty() -> Layout {
        Layout {
            version: 3,
            active: "ws1".into(),
            chat: Chat { x: 0, y: 0, w: 0, h: 0, open: true },
            workspaces: vec![Workspace { id: "ws1".into(), name: "Workspace".into(), parent: None, lens: vec![], view: None, items: vec![] }],
        }
    }

    /// The caps serde cannot say; Err names the first that broke.
    pub fn check(&self) -> Result<(), String> {
        if self.version != 3 {
            return Err(format!("version {} is not 3", self.version));
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
            check_lens(&ws.lens).map_err(|e| format!("workspace {}: {e}", ws.id))?;
            if let Some(v) = &ws.view {
                if !(0.1..=4.0).contains(&v.zoom) || v.x.abs() > 1_000_000 || v.y.abs() > 1_000_000 {
                    return Err(format!("workspace {} view {v:?} is outside zoom 0.1..4, |x|,|y| <= 1000000", ws.id));
                }
            }
            if ws.items.len() > 64 {
                return Err(format!("workspace {} has {} items, 64 allowed", ws.id, ws.items.len()));
            }
            let widgets = ws.items.iter().filter(|i| i.kind == Kind::Widget).count();
            if widgets > 24 {
                return Err(format!("workspace {} has {widgets} widgets, 24 allowed", ws.id));
            }
            for i in &ws.items {
                if !id_ok(&i.id) || !ids.insert(i.id.as_str()) {
                    return Err(format!("item id {:?} is not a unique [A-Za-z0-9_-]{{1,64}}", i.id));
                }
                i.check()?;
            }
        }
        let parent: HashMap<&str, Option<&str>> = self.workspaces.iter().map(|w| (w.id.as_str(), w.parent.as_deref())).collect();
        for ws in &self.workspaces {
            let (mut at, mut depth) = (ws.id.as_str(), 1);
            while let Some(up) = parent[at] {
                if !parent.contains_key(up) {
                    return Err(format!("workspace {} has parent {up:?}, which names no workspace", ws.id));
                }
                depth += 1;
                if depth > 6 {
                    return Err(format!("workspace {} is nested deeper than 6, or in a cycle", ws.id));
                }
                at = up;
            }
        }
        if !self.workspaces.iter().any(|ws| ws.id == self.active) {
            return Err(format!("active {:?} names no workspace", self.active));
        }
        Ok(())
    }
}

/// A version 1 or 2 file loads as version 3 (workspace-layout.yml): grid units become world px.
pub fn decode(text: &str) -> Result<Layout, String> {
    let v: serde_json::Value = serde_json::from_str(text).map_err(|e| format!("undecodable layout: {e}"))?;
    let l: Layout = match v.get("version").and_then(|n| n.as_u64()) {
        Some(1 | 2) => serde_json::from_value::<Old>(v).map(Layout::from),
        _ => serde_json::from_value(v),
    }
    .map_err(|e| format!("undecodable layout: {e}"))?;
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
        // The same v2 bytes workspace.test.ts migrates: each loads as its v3, which saves.
        let fx: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
        let migrated = fx["migrated"].as_array().unwrap();
        assert!(!migrated.is_empty(), "no v2 sample to migrate");
        for c in migrated {
            let l = decode(&c["v2"].to_string()).unwrap_or_else(|e| panic!("{}: {e}", c["case"]));
            assert_eq!(serde_json::to_value(&l).unwrap(), c["v3"], "{}", c["case"]);
        }
    }

    #[test]
    fn a_v1_or_v2_file_loads_as_v3() {
        // workspace-layout.yml 1 -> 2 -> 3: grid units become world px; the file is not set aside.
        let fx: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
        let (mut v1, v3) = (fx["migrated"][1]["v2"].clone(), fx["migrated"][1]["v3"].clone());
        v1["version"] = 1.into();
        let l = decode(&v1.to_string()).unwrap_or_else(|e| panic!("a v1 file was refused: {e}"));
        assert_eq!(serde_json::to_value(&l).unwrap(), v3);
        let mut v4 = v3.clone();
        v4["version"] = 4.into();
        assert!(decode(&v4.to_string()).is_err(), "a version this pupil does not know was accepted");
    }

    #[test]
    fn the_poc_workspace_decodes() {
        // genui I5i: the layout poc.test.ts restores is one this decoder would load (a v2 file, as v3).
        let p = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../state/fixtures/genui-workspace-poc/workspace.json");
        let text = std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display()));
        let l = decode(&text).unwrap();
        let kinds: Vec<_> = l.workspaces[0].items.iter().map(|i| i.kind).collect();
        assert_eq!(kinds, [Kind::Widget; 3]);
        assert_eq!(decode(&serde_json::to_string(&l).unwrap()).unwrap(), l, "the v3 it became loads as itself");
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
        let i0 = |v: &mut serde_json::Value| v["workspaces"][0]["items"][0].clone();
        let items = |n: usize, kind: &'static str| move |v: &mut serde_json::Value| {
            let one = i0(v);
            v["workspaces"][0]["items"] = (0..n).map(|i| {
                let mut w = one.clone();
                w["id"] = format!("n{i}").into();
                if kind == "heading" && i >= 24 {
                    w = serde_json::json!({"id": format!("n{i}"), "kind": "heading", "text": "h", "x": 0, "y": 0, "w": 80, "h": 32});
                }
                w
            }).collect();
        };
        let lens = |n: usize| move |v: &mut serde_json::Value| v["workspaces"][0]["lens"] = vec![serde_json::json!({"column": "kind", "op": "eq", "value": ""}); n].into();
        let set = |ptr: &'static str, val: serde_json::Value| move |v: &mut serde_json::Value| *v.pointer_mut(ptr).unwrap() = val.clone();
        let zoom = |z: f64| move |v: &mut serde_json::Value| v["workspaces"][0]["view"] = serde_json::json!({"x": 0, "y": 0, "zoom": z});
        let edges: Vec<(&str, Box<dyn Fn(&mut serde_json::Value)>, Box<dyn Fn(&mut serde_json::Value)>)> = vec![
            ("24 widgets", Box::new(items(24, "widget")), Box::new(items(25, "widget"))),
            ("64 items", Box::new(items(64, "heading")), Box::new(items(65, "heading"))),
            ("title 120", Box::new(set("/workspaces/0/items/0/title", "t".repeat(120).into())),
                          Box::new(set("/workspaces/0/items/0/title", "t".repeat(121).into()))),
            ("name 40", Box::new(set("/workspaces/0/name", "n".repeat(40).into())), Box::new(set("/workspaces/0/name", "n".repeat(41).into()))),
            ("w 80", Box::new(set("/workspaces/0/items/0/w", 80.into())), Box::new(set("/workspaces/0/items/0/w", 79.into()))),
            ("h 32", Box::new(set("/workspaces/0/items/0/h", 32.into())), Box::new(set("/workspaces/0/items/0/h", 31.into()))),
            ("h 4000", Box::new(set("/workspaces/0/items/0/h", 4000.into())), Box::new(set("/workspaces/0/items/0/h", 4001.into()))),
            ("x -100000", Box::new(set("/workspaces/0/items/0/x", (-100_000).into())), Box::new(set("/workspaces/0/items/0/x", (-100_001).into()))),
            ("zoom 0.1", Box::new(zoom(0.1)), Box::new(zoom(0.09))),
            ("version 3", Box::new(set("/version", 3.into())), Box::new(set("/version", 4.into()))),
            ("lens 4", Box::new(lens(4)), Box::new(lens(5))),
            ("id charset", Box::new(set("/workspaces/0/items/0/id", "A-z_9".into())), Box::new(set("/workspaces/0/items/0/id", "a.b".into()))),
            ("id 64", Box::new(set("/workspaces/0/items/0/id", "i".repeat(64).into())), Box::new(set("/workspaces/0/items/0/id", "i".repeat(65).into()))),
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
