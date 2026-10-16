//! The septum (D2): whom the person works for in one session. Each table def's `client_scope`
//! (state/keap-tables; vocabulary and reader: tools/septum-status.py) says whose its rows are; serve
//! keeps one client's rows, hides a personal table or another client's, and says which by name.

use serde_json::{Map, Value};
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Clone, PartialEq)]
pub struct Septum {
    /// The client party as (id, name); None is the person's own data.
    pub client: Option<(String, String)>,
    /// Table id (the def's file stem) to its client_scope.
    scopes: HashMap<String, String>,
    /// (table, column) to the table a rowRef column points into.
    refs: HashMap<(String, String), String>,
    /// Every party of role client, by id and by slug, to its (id, name).
    clients: HashMap<String, (String, String)>,
}

impl Septum {
    /// The defs in `dir` and the person's party rows; `want` None is personal, Some a client by id, slug or name.
    pub fn new(dir: &Path, parties: &[(String, Map<String, Value>)], want: Option<&str>) -> Result<Septum, String> {
        let unreadable = |e: String| format!("the table defs in {} are unreadable ({e}), so nothing could be hidden: the scope is not set", dir.display());
        let (mut scopes, mut refs) = (HashMap::new(), HashMap::new());
        for e in std::fs::read_dir(dir).map_err(|e| unreadable(e.to_string()))?.flatten() {
            let file = e.file_name().to_string_lossy().into_owned();
            let Some(table) = file.strip_suffix(".table.yml") else { continue };
            let def: Value = std::fs::read_to_string(e.path()).map_err(|e| e.to_string())
                .and_then(|t| serde_yaml_ng::from_str(&t).map_err(|e| e.to_string()))
                .map_err(|e| unreadable(format!("{file}: {e}")))?;
            let scope = def["client_scope"].as_str().ok_or_else(|| unreadable(format!("{file} declares no client_scope")))?;
            scopes.insert(table.to_string(), scope.to_string());
            for c in def.pointer("/schema/columns").and_then(Value::as_array).into_iter().flatten() {
                if let (Some(k), Some(t)) = (c["key"].as_str(), c["refTable"].as_str()) {
                    refs.insert((table.to_string(), k.to_string()), t.to_string());
                }
            }
        }
        if scopes.is_empty() {
            return Err(unreadable("no *.table.yml".into()));
        }
        let (mut clients, mut named) = (HashMap::new(), Vec::new());
        for (id, v) in parties.iter().filter(|(_, v)| v.get("role").and_then(Value::as_str) == Some("client")) {
            let name = v.get("legal_name").and_then(Value::as_str).filter(|n| !n.trim().is_empty()).unwrap_or(id);
            let both = (id.clone(), name.to_string());
            if let Some(slug) = v.get("slug").and_then(Value::as_str).filter(|s| !s.is_empty()) {
                clients.insert(slug.to_string(), both.clone());
            }
            clients.insert(id.clone(), both.clone());
            named.push(both);
        }
        let client = match want.map(str::trim) {
            None => None,
            Some(w) => Some(clients.get(w).cloned().or_else(|| named.iter().find(|(_, n)| n.eq_ignore_ascii_case(w)).cloned())
                .ok_or_else(|| {
                    let all: Vec<String> = named.iter().map(|(i, n)| format!("{n} ({i})")).collect();
                    format!("no client `{w}`; clients: {}", if all.is_empty() { "none".into() } else { all.join(", ") })
                })?),
        };
        Ok(Septum { client, scopes, refs, clients })
    }

    /// What both shells show: the client's name, or "personal".
    pub fn name(&self) -> String {
        self.client.as_ref().map_or("personal".into(), |c| c.1.clone())
    }

    pub fn said(&self) -> String {
        self.client.as_ref().map_or("on personal data".into(), |c| format!("for {}", c.1))
    }

    pub fn declares(&self, table: &str) -> bool {
        self.scopes.contains_key(table)
    }

    pub fn scope(&self, table: &str) -> &str {
        self.scopes.get(table).map_or("", String::as_str)
    }

    /// Rows of `table` walk to a party (self, book_owner, rowRef:<column>): each is kept or not.
    pub fn walks(&self, table: &str) -> bool {
        let s = self.scope(table);
        s == "self" || s == "book_owner" || s.starts_with("rowRef:")
    }

    /// Why `table` is not shown in this scope; `made_for` is the client a table Iris created was made for.
    pub fn hides(&self, table: &str, made_for: Option<&str>) -> Option<String> {
        let why = match (self.scopes.get(table).map(String::as_str), &self.client) {
            (Some("none"), _) | (Some("personal"), None) => return None,
            _ if self.walks(table) => return None,
            (Some("personal"), Some(_)) => "personal".to_string(),
            (Some(s), _) => format!("declared client_scope {s}, which names no owner"),
            (None, c) => match (made_for, c) {
                (Some(m), Some((id, _))) if m == id => return None,
                (Some(m), _) => format!("{}'s", self.clients.get(m).map_or(m, |c| c.1.as_str())),
                (None, None) => return None,
                (None, Some(_)) => "yours and declared by no table def, so personal".into(),
            },
        };
        Some(format!("{why}; hidden while you work {}", self.said()))
    }

    /// The client a cell names (a party id or slug); None for a counterparty, the own firm or nothing.
    pub fn client_of(&self, v: &str) -> Option<String> {
        self.clients.get(v).map(|c| c.0.clone())
    }

    /// The column a walk follows out of `table`, and the table it points into.
    pub fn step(&self, table: &str) -> Option<(String, String)> {
        let col = match self.scope(table) {
            "book_owner" => "book_owner",
            s => s.strip_prefix("rowRef:")?,
        };
        let parent = self.refs.get(&(table.to_string(), col.to_string())).cloned().unwrap_or_else(|| "party".into());
        Some((col.to_string(), parent))
    }

    /// A row whose walk ended at `owner` (a client id, or None) is kept: that client's, or (personal) no client's.
    pub fn keeps(&self, owner: Option<&str>) -> bool {
        match &self.client {
            Some((id, _)) => owner == Some(id.as_str()),
            None => owner.is_none(),
        }
    }
}
