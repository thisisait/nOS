//! `thalamus serve`: newline-delimited JSON on ~/.nos/thalamus.sock (0600). The kernel
//! names the peer (getpeereid), the receptor's ~/.nos/identity-map.yml names the person,
//! and every KEAP call goes to the human door as that person behind the proxy secret
//! only this process holds. A peer the map does not name is refused, never defaulted.

use crate::binding::Binding;
use crate::ledger::{Kind, Ledger, Session};
use nos_contract::renderers::{ApprovalsList, CellChange, Component, InboxItem, InboxList, RedStatus, Row, RowDiffApproval,
                               TableResults};
use nos_contract::wire::{decode_to_thalamus, encode, ControlView, Decision, Phase, ToShell, ToThalamus};
use nos_contract::uid;
use serde_json::{json, Map, Value};
use std::cmp::Ordering;
use std::collections::{BTreeMap, HashSet};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::os::unix::io::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// The map the receptor renders (roles/pazny.receptor); the thalamus renders none.
pub const IDENTITY_MAP: &str = ".nos/identity-map.yml";
const MAX_LINE: u64 = 1 << 20;
const MAX_TOOL_CALLS: usize = 8;
const MAX_PAGES: usize = 40;
/// How long a control's reader may take before it is killed.
pub const READER_SECS: u64 = 120;

pub struct Server {
    pub map: PathBuf,
    pub keap_url: String,
    pub secret: String,
    pub ledger: Mutex<Ledger>,
    pub binding: Result<Binding, String>,
    /// The checkout whose tools/ readers the approvals and red-status controls run.
    pub repo: PathBuf,
    /// READER_SECS in production; a gate shortens it.
    pub reader_secs: u64,
    /// The groups that see the operator's views (NOS_TIER1_GROUPS, from authentik_rbac_tiers).
    pub tier1: Vec<String>,
    pub log: Mutex<Box<dyn Write + Send>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Person {
    pub username: String,
    pub groups: Vec<String>,
}

impl Person {
    pub fn uid(&self) -> String {
        uid::canonical(&self.username, "", "")
    }
}

/// The login behind a uid, from the password database.
pub fn login(uid: u32) -> Option<String> {
    let mut pw: libc::passwd = unsafe { std::mem::zeroed() };
    let mut buf = vec![0 as libc::c_char; 4096];
    let mut out: *mut libc::passwd = std::ptr::null_mut();
    let rc = unsafe { libc::getpwuid_r(uid, &mut pw, buf.as_mut_ptr(), buf.len(), &mut out) };
    if rc != 0 || out.is_null() {
        return None;
    }
    unsafe { std::ffi::CStr::from_ptr(pw.pw_name) }.to_str().ok().map(str::to_string)
}

fn peer_login(s: &UnixStream) -> Option<String> {
    let (mut uid, mut gid) = (0, 0);
    (unsafe { libc::getpeereid(s.as_raw_fd(), &mut uid, &mut gid) } == 0).then_some(())?;
    login(uid)
}

/// The receptor's loader rules: unknown, unreadable or malformed is None.
pub fn person(login: &str, map: &Path) -> Option<Person> {
    let doc: Value = serde_json::from_str(&std::fs::read_to_string(map).ok()?).ok()?;
    let entry = doc.get("logins")?.get(login)?;
    let ok = |v: &Value| v.as_str().filter(|s| !s.is_empty() && !s.contains(['\r', '\n', ','])).map(str::to_string);
    let username = ok(entry.get("username")?)?;
    let groups = entry.get("groups")?.as_array()?.iter().map(ok).collect::<Option<Vec<_>>>()?;
    Some(Person { username, groups })
}

/// Binds the socket 0600 from birth: no window where another uid may connect.
pub fn bind(path: &Path) -> std::io::Result<UnixListener> {
    // Only a stale socket is removed; any other file at the path is not ours to delete.
    if let Ok(m) = std::fs::symlink_metadata(path) {
        if !m.file_type().is_socket() {
            return Err(std::io::Error::other(format!("{} exists and is not a socket", path.display())));
        }
        std::fs::remove_file(path)?;
    }
    let old = unsafe { libc::umask(0o177) };
    let l = UnixListener::bind(path);
    unsafe { libc::umask(old) };
    let l = l?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(l)
}

pub fn run(listener: UnixListener, srv: Arc<Server>) {
    for conn in listener.incoming().flatten() {
        let srv = srv.clone();
        std::thread::spawn(move || srv.connection(conn));
    }
}

fn agent(timeout: u64) -> ureq::Agent {
    // No env proxy, no redirects: the person's headers and the secret go to KEAP_URL only.
    ureq::Agent::config_builder()
        .proxy(None)
        .max_redirects(0)
        .http_status_as_error(false)
        .timeout_global(Some(Duration::from_secs(timeout)))
        .build()
        .into()
}

/// The one alias the model may use: "roadmap" is NOS_ROADMAP_TABLE_ID (the plist renders
/// keap_roadmap_table_id); any other name is passed to KEAP as the table id it is.
fn table_id(t: &str) -> String {
    match std::env::var("NOS_ROADMAP_TABLE_ID") {
        Ok(id) if t == "roadmap" && !id.is_empty() => id,
        _ => t.to_string(),
    }
}

/// Percent-encodes one path or query component.
fn enc(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

/// One connection's open session: one person, one conversation with the model.
struct Open {
    session: String,
    /// Err (why) when iris is unbound or its imprint is missing: controls still answer, turns are refused.
    model: Result<Binding, String>,
    messages: Vec<Value>,
    tokens: (i64, i64),
    /// Approvals asked and not yet decided; a decision removes its id, so each is decided once.
    pending: HashSet<String>,
    /// (table, row id) of every row a query put in front of the person; only these may be proposed.
    shown: HashSet<(String, String)>,
}

fn send(out: &mut UnixStream, m: &ToShell) {
    let _ = out.write_all(encode(m).as_bytes());
}

/// What this session is doing now; the pupil's eye shows it.
fn activity(out: &mut UnixStream, o: &Open, phase: Phase) {
    send(out, &ToShell::Activity { session: o.session.clone(), phase });
}

fn refuse(out: &mut UnixStream, why: &str) {
    send(out, &ToShell::Refused { reason: why.to_string() });
}

/// A v4 uuid from the kernel's randomness.
fn mint_uuid() -> std::io::Result<String> {
    let mut b = [0u8; 16];
    std::fs::File::open("/dev/urandom")?.read_exact(&mut b)?;
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    let h: String = b.iter().map(|x| format!("{x:02x}")).collect();
    Ok(format!("{}-{}-{}-{}-{}", &h[..8], &h[8..12], &h[12..16], &h[16..20], &h[20..]))
}

const QUERY_ROWS: &str = "Read, count or filter the rows of one DataTable, as the person. Every parameter but \
`table` is optional: no `q` and no `where` is every row, and `limit: 0` counts without rows. In the result, \
`total` is the exact count of rows the person may read, `matched` the count after q and where, and `columns` \
the table's columns with their kinds and select options. Renders table_results to the person; projected is \
false because the thalamus filters by substring and equality, not by meaning.";

const PROPOSE_ROW_EDIT: &str = "Propose new values for cells of one existing row. Renders row_diff_approval: \
the person sees each changed cell old -> new and approves or rejects it. Nothing is written until they \
approve; you are told only that the proposal waits for them. Only for a change the person asked for in this \
conversation, on a row query_rows showed them; never to count, test or look at a row — query_rows does that.";

const SHOW: &str = "Show the person structured output: one component of a closed vocabulary, drawn as text. \
A component outside its shape or caps is refused and you are told why; nothing is drawn. It cannot ask for an \
approval: only propose_row_edit does, and query_rows draws its own table.";

/// The kinds the model may choose; the rest are drawn by a tool or a control, never by show.
/// No markdown: plain text already draws as markdown, and a markdown show was then said again as text.
const SHOW_KINDS: [&str; 4] = ["table", "list", "record", "chart"];

/// One `oneOf` branch per kind; the descriptions are thalamus-shell.yml's vocabulary lines.
fn show_schema() -> Value {
    let title = json!({"type": "string", "maxLength": 120});
    let branch = |kind: &str, about: &str, props: Value| json!({"type": "object", "additionalProperties": false,
        "required": ["kind", "props"], "description": about, "properties": {"kind": {"const": kind}, "props": props}});
    let closed = |required: &[&str], properties: Value| json!({"type": "object", "additionalProperties": false,
        "required": required, "properties": properties});
    json!({"type": "object", "additionalProperties": false, "required": ["component"], "properties": {"component": {"oneOf": [
        branch("table", "rows the model shows: {title?, columns[] <=12, rows[][] <=50, each row as long as columns}",
            closed(&["columns", "rows"], json!({"title": title, "columns": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
                "rows": {"type": "array", "maxItems": 50, "items": {"type": "array"}}}))),
        branch("list", "items the model shows: {title?, ordered, items[{text, detail?, tone? ok|info|warn|bad}] <=50}",
            closed(&["items", "ordered"], json!({"title": title, "ordered": {"type": "boolean"},
                "items": {"type": "array", "maxItems": 50, "items": closed(&["text"], json!({
                    "text": {"type": "string", "maxLength": 500}, "detail": {"type": "string", "maxLength": 2000},
                    "tone": {"enum": ["ok", "info", "warn", "bad"]}}))}}))),
        branch("record", "one thing's fields: {title?, fields[{key, value}] <=40}",
            closed(&["fields"], json!({"title": title, "fields": {"type": "array", "maxItems": 40,
                "items": closed(&["key", "value"], json!({"key": {"type": "string", "maxLength": 120}, "value": {}}))}}))),
        branch("chart", "values plotted as bar or line: {title?, chart bar|line, series[{name, points[[x, number]] <=60}] <=6}; \
a line's series share the same x in the same order",
            closed(&["chart", "series"], json!({"title": title, "chart": {"enum": ["bar", "line"]},
                "series": {"type": "array", "minItems": 1, "maxItems": 6, "items": closed(&["name", "points"], json!({
                    "name": {"type": "string", "maxLength": 120},
                    "points": {"type": "array", "maxItems": 60, "items": {"type": "array", "minItems": 2, "maxItems": 2,
                        "prefixItems": [{"type": "string", "maxLength": 120}, {"type": "number"}]}}}))}})))]}}})
}

const QUERY_KEYS: [&str; 7] = ["table", "q", "where", "columns", "order_by", "limit", "group_by"];
const WHERE_KEYS: [&str; 3] = ["column", "op", "value"];
const ORDER_KEYS: [&str; 2] = ["column", "dir"];
const OPS: [&str; 4] = ["eq", "neq", "in", "contains"];

fn tools() -> Value {
    json!([{"type": "function", "function": {"name": "query_rows", "description": QUERY_ROWS,
        "parameters": {"type": "object", "additionalProperties": false, "required": ["table"], "properties": {
            "table": {"type": "string", "description": "the table id, or \"roadmap\" for the roadmap"},
            "q": {"type": "string", "description": "case-insensitive substring anywhere in the row"},
            "where": {"type": "array", "maxItems": 8, "description": "every condition must hold",
                "items": {"type": "object", "additionalProperties": false, "required": ["column", "op", "value"], "properties": {
                    "column": {"type": "string"}, "op": {"enum": OPS},
                    "value": {"description": "a string; for in, a list of strings"}}}},
            "columns": {"type": "array", "maxItems": 12, "items": {"type": "string"},
                "description": "the column keys to show; default every column, in the table's order"},
            "order_by": {"type": "object", "additionalProperties": false, "required": ["column"], "properties": {
                "column": {"type": "string"}, "dir": {"enum": ["asc", "desc"]}}},
            "limit": {"type": "integer", "minimum": 0, "maximum": 50, "description": "rows returned, default 20; 0 counts only"},
            "group_by": {"type": "string", "description": "a column key: count the matched rows per value of it, instead of rows"}}}}},
        {"type": "function", "function": {"name": "propose_row_edit", "description": PROPOSE_ROW_EDIT,
        "parameters": {"type": "object", "additionalProperties": false, "required": ["table", "row_id", "values"], "properties": {
            "table": {"type": "string", "description": "the table id, or \"roadmap\" for the roadmap"},
            "row_id": {"type": "string", "description": "the row's __id from query_rows"},
            "values": {"type": "object", "description": "column -> new value; null clears the cell"}}}}},
        {"type": "function", "function": {"name": "show", "description": SHOW, "parameters": show_schema()}}])
}

impl Server {
    fn say(&self, line: String) {
        if let Ok(mut l) = self.log.lock() {
            let _ = writeln!(l, "{line}");
        }
    }

    fn connection(&self, mut out: UnixStream) {
        let login = peer_login(&out);
        let who = login.as_deref().and_then(|l| person(l, &self.map));
        let Some(who) = who.filter(|p| !p.uid().is_empty()) else {
            let l = login.unwrap_or_else(|| "unknown uid".into());
            self.say(format!("refused {l}: not in the identity map"));
            return refuse(&mut out, &format!("{l} is not in the identity map"));
        };
        self.say(format!("connected {} as {}", login.as_deref().unwrap_or("?"), who.username));
        let Ok(input) = out.try_clone() else { return };
        let mut input = BufReader::new(input);
        let mut open: Option<Open> = None;
        loop {
            let mut line = String::new();
            match input.by_ref().take(MAX_LINE).read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) if !line.ends_with('\n') => {
                    refuse(&mut out, "line exceeds 1 MiB or is unterminated");
                    break;
                }
                Ok(_) => {}
            }
            match decode_to_thalamus(&line) {
                Err(why) => refuse(&mut out, &why),
                Ok(ToThalamus::Turn { session, text }) => {
                    if session != open.as_ref().map(|o| o.session.clone()) {
                        refuse(&mut out, "session is not this connection's open session");
                        continue;
                    }
                    if let Some(o) = self.ensure(&who, &mut out, &mut open) {
                        self.turn(&who, &mut out, o, &text);
                        // However the turn ended (text, cap, refusal), it is over.
                        activity(&mut out, o, Phase::Idle);
                    }
                }
                Ok(ToThalamus::Control { view }) => {
                    if let Some(o) = self.ensure(&who, &mut out, &mut open) {
                        self.control(&who, &mut out, o, view);
                    }
                }
                Ok(ToThalamus::ApprovalDecision { approval, decision, note }) => match open.as_mut() {
                    Some(o) if o.pending.contains(&approval) => {
                        self.decide(&who, &mut out, o, &approval, decision, note);
                        activity(&mut out, o, Phase::Idle);
                    }
                    _ => refuse(&mut out, "no open approval with that id"),
                },
            }
        }
        if let Some(o) = open {
            let _ = self.ledger.lock().map(|l| l.end(&o.session, "connection_closed", (Some(o.tokens.0), Some(o.tokens.1))));
            self.say(format!("closed {} for {}", o.session, who.username));
        }
    }

    /// The connection's session, opened on its first Turn or Control; None was refused.
    fn ensure<'a>(&self, who: &Person, out: &mut UnixStream, open: &'a mut Option<Open>) -> Option<&'a mut Open> {
        if open.is_none() {
            match self.open(who, out) {
                Ok(o) => *open = Some(o),
                Err(why) => refuse(out, &why),
            }
        }
        open.as_mut()
    }

    fn open(&self, who: &Person, out: &mut UnixStream) -> Result<Open, String> {
        // The imprint the binding calls for: the short render fits a local model's window.
        let imprint = self.binding.clone().and_then(|m| {
            let file = if m.local { "IMPRINT.short.md" } else { "IMPRINT.md" };
            match std::fs::read_to_string(self.repo.join(file)) {
                Ok(t) if !t.trim().is_empty() => Ok((m, t)),
                _ => Err(format!("{file} is missing or empty in {}; iris does not run without it", self.repo.display())),
            }
        });
        if let (Ok(_), Err(why)) = (&self.binding, &imprint) {
            self.say(format!("refusing turns: {why}"));
        }
        let session = mint_uuid().map_err(|e| format!("no session id: {e}"))?;
        let actor = format!("user:{}", who.uid());
        let model_uri = self.binding.as_ref().map_or("unbound".to_string(), |m| format!("{}-{}", m.name, m.model_id));
        let s = Session { uuid: &session, agent_name: "iris", agent_version: 1, actor: &actor, model_uri: &model_uri };
        self.ledger.lock().map_err(|_| "ledger poisoned".to_string())?.start(&s).map_err(|e| format!("ledger: {e}"))?;
        send(out, &ToShell::Session { session: session.clone(), actor, model_uri });
        let iris = format!("You are Iris. You act for {} and see only what they may see. To read, count or filter \
rows of a DataTable call query_rows (its total is the exact count); propose_row_edit only for a change the person \
asked for, never to look at a row. To show structured output call show (table, list, record, \
chart); plain text may use markdown, nothing else. To count per value (for a chart) call query_rows with \
group_by. When no tool can see what is asked, say so; never guess it. Say what you found in a line, and never \
repeat in text what a tool or show already drew. It is now {} UTC.", who.username, now_utc());
        let (model, system) = match imprint {
            Ok((m, t)) => (Ok(m), format!("{}\n\n{iris}", t.trim_end())),
            Err(why) => (Err(why), iris),
        };
        Ok(Open { session, model, messages: vec![json!({"role": "system", "content": system})], tokens: (0, 0),
                  pending: HashSet::new(), shown: HashSet::new() })
    }

    /// One ledger event; the row id, or the reason it was refused (also logged).
    fn record(&self, o: &Open, kind: Kind, tool: Option<&str>, v: Value) -> Result<i64, String> {
        let r = self.ledger.lock().map_err(|_| "ledger poisoned".to_string())
            .and_then(|l| l.record(&o.session, kind, tool, &v).map_err(|e| e.to_string()));
        if let Err(e) = &r {
            self.say(format!("ledger refused an event of {}: {e}", o.session));
        }
        r
    }

    /// Asks the person: the request is in the ledger before the shell sees it, or it is not asked.
    fn ask(&self, o: &mut Open, out: &mut UnixStream, d: RowDiffApproval) -> Result<Value, String> {
        let approval = mint_uuid().map_err(|e| format!("no approval id: {e}"))?;
        self.record(o, Kind::ApprovalRequest, Some("propose_row_edit"),
                    json!({"approval": approval, "table": d.table, "row_id": d.row_id, "cells": d.cells}))?;
        o.pending.insert(approval.clone());
        send(out, &ToShell::ApprovalRequest { session: o.session.clone(), approval: approval.clone(),
                                              component: Component::RowDiffApproval(d) });
        Ok(json!({"approval": approval, "status": "waiting for the person; nothing is written unless they approve"}))
    }

    fn decide(&self, who: &Person, out: &mut UnixStream, o: &mut Open, approval: &str, d: Decision, note: Option<String>) {
        o.pending.remove(approval);
        let said = if d == Decision::Approve { "approve" } else { "reject" };
        let id = match self.record(o, Kind::ApprovalDecision, Some("propose_row_edit"),
                                   json!({"approval": approval, "decision": said, "note": note})) {
            Ok(id) => id,
            Err(why) => return refuse(out, &format!("the decision was not recorded, so nothing is written: {why}")),
        };
        if d == Decision::Approve {
            activity(out, o, Phase::Writing);
        }
        let (text, result, heard) = match d {
            Decision::Reject => ("Rejected: nothing was written.".to_string(), json!({"approval": approval, "written": false}),
                                 format!("rejected: {}", note.as_deref().unwrap_or("no note"))),
            Decision::Approve => match self.commit(who, id) {
                Ok(row) => (format!("Approved: row {row} written."), json!({"approval": approval, "written": true, "row": row}),
                            "approved, row written".to_string()),
                Err(why) => (format!("Approved, but the write failed: {why}"), json!({"approval": approval, "error": why}),
                             format!("approved, but nothing was written: {why}")),
            },
        };
        let _ = self.record(o, Kind::ToolResult, Some("propose_row_edit"), result);
        // The model was told only "waiting"; its next turn starts from what the person did.
        o.messages.push(json!({"role": "user", "content": format!("[thalamus] approval {approval}: {heard}")}));
        send(out, &ToShell::Text { session: o.session.clone(), text });
    }

    /// The only write path. It takes a decision row id and writes exactly what that row's
    /// request showed the person; no approve row in the ledger, no POST.
    pub fn commit(&self, who: &Person, decision: i64) -> Result<String, String> {
        let (actor, table, row_id, values, old) =
            self.ledger.lock().map_err(|_| "ledger poisoned".to_string())?.approved(decision)?;
        if actor != format!("user:{}", who.uid()) {
            return Err("the approval belongs to another person".into());
        }
        // The person approved old -> new; a row that moved since is not what they saw.
        let now = self.rows(who, &table)?.into_iter().find(|(id, _)| *id == row_id).map(|(_, v)| v)
            .ok_or(format!("row {row_id} is gone since the proposal; nothing written"))?;
        if let Some((k, _)) = old.iter().find(|(k, v)| now.get(*k).unwrap_or(&Value::Null) != *v) {
            return Err(format!("cell {k} of row {row_id} changed since the proposal; nothing written"));
        }
        let url = format!("{}/api/tables/{}/rows", self.keap_url.trim_end_matches('/'), enc(&table));
        // ponytail: a write between this re-read and the POST still lands under it; roadmap row
        // keap-conditional-row-update (an if-match on KEAP's side) closes that race.
        self.keap(who, &url, Some(&json!({"id": row_id, "values": values})))?;
        Ok(row_id)
    }

    fn turn(&self, who: &Person, out: &mut UnixStream, o: &mut Open, text: &str) {
        let model = match o.model.clone() {
            Ok(m) => m,
            Err(why) => return refuse(out, &format!("iris has no model: {why}")),
        };
        let _ = self.record(o, Kind::Message, None, json!({"role": "person", "text": text}));
        o.messages.push(json!({"role": "user", "content": text}));
        let mut calls = 0;
        loop {
            activity(out, o, Phase::Thinking);
            let msg = match self.complete(&model, o) {
                Ok(m) => m,
                Err(why) => return refuse(out, &why),
            };
            o.messages.push(msg.clone());
            let Some(asked) = msg.get("tool_calls").and_then(Value::as_array).filter(|a| !a.is_empty()).cloned() else {
                let text = msg.get("content").and_then(Value::as_str).unwrap_or("").to_string();
                let _ = self.record(o, Kind::Message, None, json!({"role": "iris", "text": text}));
                // Live 2026-10-13: a blank answer drew nothing, so the person could not tell it ended.
                let text = if text.trim().is_empty() { "(Iris gave no answer.)".to_string() } else { text };
                return send(out, &ToShell::Text { session: o.session.clone(), text });
            };
            for (i, call) in asked.iter().enumerate() {
                calls += 1;
                if calls > MAX_TOOL_CALLS {
                    // An unanswered call is a shape providers reject (Runner.php compactForSynthesis).
                    for c in &asked[i..] {
                        o.messages.push(json!({"role": "tool", "tool_call_id": c.get("id").cloned().unwrap_or(Value::Null),
                                               "content": json!({"error": "stopped: tool-call cap"}).to_string()}));
                    }
                    let text = format!("Stopped: more than {MAX_TOOL_CALLS} tool calls in one turn.");
                    let _ = self.record(o, Kind::Message, None, json!({"role": "thalamus", "text": text}));
                    return send(out, &ToShell::Text { session: o.session.clone(), text });
                }
                let name = call.pointer("/function/name").and_then(Value::as_str).unwrap_or("");
                let args: Value = call.pointer("/function/arguments").and_then(Value::as_str)
                    .and_then(|a| serde_json::from_str(a).ok()).unwrap_or(Value::Null);
                let _ = self.record(o, Kind::ToolUse, Some(name), json!({"args": args}));
                activity(out, o, Phase::Tool { name: name.to_string() });
                let result = match name {
                    "query_rows" => self.query_rows(who, &args).map(|(t, extra, grouped)| {
                        let ids: Vec<&str> = t.rows.iter().map(|r| r.__id.as_str()).collect();
                        let _ = self.record(o, Kind::ToolResult, Some(name),
                                            json!({"rows": ids, "matched": t.matched, "total": t.total}));
                        // A group is a value, not a row: it never unlocks a proposal.
                        let v = if grouped {
                            json!({"table": t.table, "name": t.name, "matched": t.matched, "total": t.total, "groups": extra})
                        } else {
                            o.shown.extend(t.rows.iter().map(|r| (t.table.clone(), r.__id.clone())));
                            json!({"table": t.table, "name": t.name, "matched": t.matched, "total": t.total,
                                   "columns": extra, "rows": t.rows})
                        };
                        send(out, &ToShell::Render { session: o.session.clone(), component: Component::TableResults(t) });
                        v
                    }),
                    // Its tool_result is written by decide(), once the person has answered.
                    "propose_row_edit" if !o.pending.is_empty() => Err("an approval is already waiting".to_string()),
                    "propose_row_edit" => self.propose_row_edit(who, &args, &o.shown).and_then(|d| self.ask(o, out, d)),
                    "show" => show(&args).map(|c| {
                        let kind = serde_json::to_value(&c).ok().and_then(|v| v["kind"].as_str().map(str::to_string));
                        let v = json!({"shown": kind});
                        let _ = self.record(o, Kind::ToolResult, Some(name), v.clone());
                        send(out, &ToShell::Render { session: o.session.clone(), component: c });
                        v
                    }),
                    _ => Err(format!("unknown tool {name:?}")),
                };
                let for_model = result.unwrap_or_else(|why| {
                    let _ = self.record(o, Kind::ToolResult, Some(name), json!({"error": why}));
                    json!({"error": why})
                });
                o.messages.push(json!({"role": "tool", "tool_call_id": call.get("id").cloned().unwrap_or(Value::Null),
                                       "content": for_model.to_string()}));
            }
        }
    }

    /// One chat-completions call; the model gets the conversation, never a KEAP header.
    fn complete(&self, model: &Binding, o: &mut Open) -> Result<Value, String> {
        let url = format!("{}/chat/completions", model.base_url.trim_end_matches('/'));
        let mut req = agent(300).post(&url);
        if !model.auth_token.is_empty() {
            req = req.header("Authorization", &format!("Bearer {}", model.auth_token));
        }
        let body = json!({"model": model.model_id, "messages": o.messages, "tools": tools()});
        let mut r = req.send_json(&body).map_err(|e| format!("model unreachable: {e}"))?;
        let status = r.status().as_u16();
        let v: Value = r.body_mut().read_json().map_err(|e| format!("model answered {status} with no JSON: {e}"))?;
        if status != 200 {
            return Err(format!("model answered {status}"));
        }
        o.tokens.0 += v.pointer("/usage/prompt_tokens").and_then(Value::as_i64).unwrap_or(0);
        o.tokens.1 += v.pointer("/usage/completion_tokens").and_then(Value::as_i64).unwrap_or(0);
        v.pointer("/choices/0/message").cloned().ok_or_else(|| "model answered without a message".into())
    }

    /// GET /api/tables/:id (title, columns) then every row as the person, filtered, sorted and cut
    /// here: the whole table or an Err, so `total` is exact. Also returns the columns for the model.
    /// The table, then for the model its columns (or, grouped, its groups), and whether it was grouped.
    fn query_rows(&self, who: &Person, args: &Value) -> Result<(TableResults, Value, bool), String> {
        let a = args.as_object().ok_or("query_rows takes an object")?;
        if let Some(k) = a.keys().find(|k| !QUERY_KEYS.contains(&k.as_str())) {
            return Err(format!("query_rows has no parameter `{k}`; it has {}", QUERY_KEYS.join(", ")));
        }
        let given = |k: &str| a.get(k).filter(|v| !v.is_null());
        let alias = given("table").and_then(Value::as_str).filter(|t| !t.is_empty()).ok_or("query_rows needs `table`")?;
        let table = table_id(alias);
        let info = self.keap(who, &format!("{}/api/tables/{}", self.keap_url.trim_end_matches('/'), enc(&table)), None)?;
        let name = info.pointer("/data/title").and_then(Value::as_str).filter(|t| !t.is_empty()).unwrap_or(alias).to_string();
        let schema: Vec<&Map<String, Value>> = info.pointer("/data/schema/columns").and_then(Value::as_array)
            .map(|c| c.iter().filter_map(Value::as_object).filter(|c| c.get("key").is_some_and(Value::is_string))
                // An embedding is for the machine: 768 floats per row to the model, a column of noise on screen.
                .filter(|c| c.get("kind").and_then(Value::as_str) != Some("vector")).collect())
            .filter(|c: &Vec<_>| !c.is_empty()).ok_or(format!("KEAP returned no column schema for {name}"))?;
        let keys: Vec<&str> = schema.iter().filter_map(|c| c.get("key").and_then(Value::as_str)).collect();
        let col = |k: &str| schema.iter().copied().find(|c| c.get("key").and_then(Value::as_str) == Some(k))
            .ok_or(format!("no column `{k}` in {name}; columns: {}", keys.join(", ")));

        let mut said = Vec::new();
        let q = match given("q") {
            None => None,
            Some(Value::String(q)) => {
                let q = q.trim().to_lowercase();
                (!q.is_empty()).then_some(q)
            }
            Some(_) => return Err("`q` is a string".into()),
        };
        if let Some(q) = &q {
            said.push(format!("contains {q:?}"));
        }
        let conds = match given("where") {
            None => &vec![],
            Some(Value::Array(w)) if w.len() <= 8 => w,
            _ => return Err("`where` is a list of at most 8 conditions".into()),
        };
        let mut wh: Vec<(&str, &str, Vec<String>)> = Vec::new();
        for c in conds {
            if let Some(k) = c.as_object().and_then(|o| o.keys().find(|k| !WHERE_KEYS.contains(&k.as_str()))) {
                return Err(format!("a `where` condition has no key `{k}`; it has {}", WHERE_KEYS.join(", ")));
            }
            let k = c.get("column").and_then(Value::as_str).ok_or("a `where` condition needs `column`")?;
            let def = col(k)?;
            let op = c.get("op").and_then(Value::as_str).filter(|o| OPS.contains(o))
                .ok_or(format!("`where` on {k}: op is one of {}", OPS.join(", ")))?;
            let vals: Vec<String> = match (op, c.get("value")) {
                ("in", Some(Value::Array(v))) => v.iter().map(|x| match x.as_str() {
                    Some(s) => Ok(s.to_string()),
                    None => Err(format!("`where` on {k}: in takes a list of strings")),
                }).collect::<Result<Vec<_>, _>>()?,
                ("in", _) => return Err(format!("`where` on {k}: in takes a list of strings")),
                (_, Some(Value::String(s))) => vec![s.clone()],
                _ => return Err(format!("`where` on {k}: value is a string")),
            };
            let options: Option<Vec<&str>> = def.get("options").and_then(Value::as_array)
                .map(|o| o.iter().filter_map(Value::as_str).collect());
            if let (Some(o), true) = (&options, op != "contains") {
                if let Some(bad) = vals.iter().find(|v| !o.contains(&v.as_str())) {
                    return Err(format!("{bad:?} is not a {k} value in {name}; options: {}", o.join(", ")));
                }
            }
            said.push(match op {
                "in" => format!("{k} in [{}]", vals.join(", ")),
                "eq" => format!("{k} = {}", vals[0]),
                "neq" => format!("{k} != {}", vals[0]),
                _ => format!("{k} contains {:?}", vals[0]),
            });
            wh.push((k, op, vals));
        }
        let order = match given("order_by") {
            None => None,
            Some(o) => {
                if let Some(k) = o.as_object().and_then(|obj| obj.keys().find(|k| !ORDER_KEYS.contains(&k.as_str()))) {
                    return Err(format!("`order_by` has no key `{k}`; it has {}", ORDER_KEYS.join(", ")));
                }
                let k = o.get("column").and_then(Value::as_str).ok_or("`order_by` needs `column`")?;
                col(k)?;
                let desc = match o.get("dir") {
                    None => false,
                    Some(Value::String(d)) if d == "asc" => false,
                    Some(Value::String(d)) if d == "desc" => true,
                    Some(d) => return Err(format!("`order_by` dir is asc or desc, not {d}")),
                };
                said.push(format!("order by {k} {}", if desc { "desc" } else { "asc" }));
                Some((k, desc))
            }
        };
        let columns: Vec<String> = match given("columns") {
            None => keys.iter().map(|k| k.to_string()).collect(),
            Some(Value::Array(c)) if c.len() <= 12 => {
                let c = c.iter().map(|k| k.as_str().ok_or("`columns` holds column keys".to_string())
                    .and_then(|k| col(k).map(|_| k.to_string()))).collect::<Result<Vec<_>, _>>()?;
                said.push(format!("columns {}", c.join(", ")));
                c
            }
            _ => return Err("`columns` is a list of at most 12 column keys".into()),
        };
        let group = match given("group_by") {
            None => None,
            Some(Value::String(k)) => {
                col(k)?;
                said.push(format!("grouped by {k}"));
                Some(k.as_str())
            }
            Some(_) => return Err("`group_by` is a column key".into()),
        };
        let limit = match given("limit") {
            None => 20,
            Some(n) => n.as_u64().filter(|n| *n <= 50).ok_or("`limit` is a whole number from 0 to 50")? as usize,
        };

        let mut all = self.rows(who, &table)?;
        for (_, v) in &mut all {
            v.retain(|k, _| keys.contains(&k.as_str()));
        }
        let total = all.len();
        let mut hits: Vec<(String, Map<String, Value>)> = all.into_iter()
            .filter(|(_, v)| q.as_ref().is_none_or(|q| Value::Object(v.clone()).to_string().to_lowercase().contains(q)))
            .filter(|(_, v)| wh.iter().all(|(k, op, vals)| {
                let c = text(v.get(*k).unwrap_or(&Value::Null));
                match *op {
                    "eq" | "in" => vals.contains(&c),
                    "neq" => !vals.contains(&c),
                    _ => c.to_lowercase().contains(&vals[0].to_lowercase()),
                }
            }))
            .collect();
        let matched = hits.len();
        let query = if said.is_empty() { "all rows".to_string() } else { said.join(" · ") };
        if let Some(k) = group {
            let mut counts: Vec<(Value, usize)> = Vec::new();
            for (_, v) in &hits {
                let x = v.get(k).cloned().filter(|x| !x.is_null() && text(x) != "").unwrap_or(Value::Null);
                match counts.iter_mut().find(|(y, _)| *y == x) {
                    Some((_, n)) => *n += 1,
                    None => counts.push((x, 1)),
                }
            }
            counts.sort_by(|a, b| b.1.cmp(&a.1));
            let groups: Vec<Value> = counts.iter().map(|(x, n)| json!({"value": x, "count": n})).collect();
            let rows = counts.into_iter().map(|(x, n)| {
                let id = if x.is_null() { "(empty)".to_string() } else { text(&x) };
                Row { __id: id, cells: BTreeMap::from([(k.to_string(), x), ("count".to_string(), json!(n))]) }
            }).collect();
            let columns = vec![k.to_string(), "count".to_string()];
            return Ok((TableResults { table, name, query, matched, total, columns, rows, projected: false }, Value::Array(groups), true));
        }
        if let Some((k, desc)) = order {
            hits.sort_by(|x, y| by(x.1.get(k), y.1.get(k), desc));
        }
        hits.truncate(limit);
        let rows = hits.into_iter()
            .map(|(id, v)| Row { __id: id, cells: v.into_iter().filter(|(k, _)| columns.contains(k)).collect::<BTreeMap<_, _>>() })
            .collect();
        let for_model: Vec<Value> = schema.iter().map(|c| {
            let mut m = Map::new();
            for k in ["key", "kind", "options"] {
                if let Some(v) = c.get(k) {
                    m.insert(k.into(), v.clone());
                }
            }
            Value::Object(m)
        }).collect();
        Ok((TableResults { table, name, query, matched, total, columns, rows, projected: false }, Value::Array(for_model), false))
    }

    /// Every row of one table the person may read: GET /api/tables/:id/rows, every page.
    /// The whole table or an Err: a row without an id, or more pages than MAX_PAGES, is refused.
    fn rows(&self, who: &Person, table: &str) -> Result<Vec<(String, Map<String, Value>)>, String> {
        let (mut all, mut cursor) = (Vec::new(), None::<String>);
        for _ in 0..MAX_PAGES {
            let mut url = format!("{}/api/tables/{}/rows?limit=500", self.keap_url.trim_end_matches('/'), enc(table));
            if let Some(c) = &cursor {
                url += &format!("&cursor={}", enc(c));
            }
            let page = self.keap(who, &url, None)?;
            for r in page.pointer("/data/rows").and_then(Value::as_array).into_iter().flatten() {
                let id = r.get("id").and_then(Value::as_str).filter(|i| !i.is_empty())
                    .ok_or(format!("KEAP returned a row without an id in {table}"))?;
                all.push((id.to_string(), r.get("values").and_then(Value::as_object).cloned().unwrap_or_default()));
            }
            cursor = page.pointer("/data/nextCursor").and_then(Value::as_str).map(str::to_string);
            if cursor.is_none() {
                return Ok(all);
            }
        }
        Err(format!("{table} exceeds the {MAX_PAGES}-page read cap; refusing a partial table"))
    }

    /// The cell diff of one existing row the person can read; only changed cells survive.
    fn propose_row_edit(&self, who: &Person, args: &Value, shown: &HashSet<(String, String)>) -> Result<RowDiffApproval, String> {
        let s = |k: &str| args.get(k).and_then(Value::as_str).filter(|v| !v.is_empty()).ok_or(format!("propose_row_edit needs `{k}`"));
        let (table, row_id) = (&table_id(s("table")?), s("row_id")?);
        // Live 2026-10-12: a proposal used as a probe. Refused before any read, so no card.
        if !shown.contains(&(table.clone(), row_id.to_string())) {
            return Err(format!("row {row_id} was not shown to the person in this session; query it first"));
        }
        let values = args.get("values").and_then(Value::as_object).filter(|v| !v.is_empty())
            .ok_or("propose_row_edit needs a non-empty `values` object")?;
        // KEAP reads __ keys as row sharing; changing who sees a row is not this tool's to propose.
        if let Some(k) = values.keys().find(|k| k.is_empty() || k.starts_with("__")) {
            return Err(format!("column {k:?} cannot be edited here"));
        }
        let current = self.rows(who, table)?.into_iter().find(|(id, _)| id == row_id).map(|(_, v)| v)
            .ok_or(format!("no row {row_id:?} in {table} that you can read"))?;
        let cells: Vec<CellChange> = values.iter()
            .map(|(k, new)| CellChange { key: k.clone(), old: current.get(k).cloned().unwrap_or(Value::Null), new: new.clone() })
            .filter(|c| c.old != c.new)
            .collect();
        if cells.is_empty() {
            return Err("nothing would change".into());
        }
        Ok(RowDiffApproval { table: table.to_string(), row_id: row_id.to_string(), cells })
    }

    fn as_person<B>(&self, rb: ureq::RequestBuilder<B>, who: &Person) -> ureq::RequestBuilder<B> {
        rb.header("x-keap-proxy-secret", &self.secret)
            .header("x-authentik-username", &who.username)
            .header("x-authentik-name", &who.username)
            .header("x-authentik-uid", &who.uid())
            .header("x-authentik-groups", &who.groups.join(","))
    }

    /// keapAs() in the face's upstream.ts: GET, or POST `body`, as the person; Err unless 200.
    fn keap(&self, who: &Person, url: &str, body: Option<&Value>) -> Result<Value, String> {
        let (status, v) = self.keap_status(who, url, body)?;
        if status != 200 {
            let why = v.get("error").and_then(Value::as_str).unwrap_or("").chars().take(300).collect::<String>();
            return Err(format!("KEAP answered {status}: {why}"));
        }
        Ok(v)
    }

    /// The status and JSON body of one call as the person behind the proxy secret.
    fn keap_status(&self, who: &Person, url: &str, body: Option<&Value>) -> Result<(u16, Value), String> {
        if self.secret.is_empty() {
            return Err("the thalamus holds no KEAP proxy secret".into());
        }
        let t0 = std::time::Instant::now();
        let a = agent(30);
        let (method, sent) = match body {
            None => ("GET", self.as_person(a.get(url), who).call()),
            Some(b) => ("POST", self.as_person(a.post(url), who).send_json(b)),
        };
        let mut r = sent.map_err(|e| format!("KEAP unreachable: {e}"))?;
        let status = r.status().as_u16();
        // The log names the path, never the query, the body, the headers or the secret.
        let path = url.split('?').next().unwrap_or("").splitn(4, '/').nth(3).unwrap_or("");
        self.say(format!("{status} as {} {method} /{path} {}ms", who.username, t0.elapsed().as_millis()));
        let v: Value = r.body_mut().read_json().map_err(|e| format!("KEAP answered {status} with no JSON: {e}"))?;
        Ok((status, v))
    }

    /// A control view, raised by the person; the model is not asked and does not see it.
    fn control(&self, who: &Person, out: &mut UnixStream, o: &mut Open, view: ControlView) {
        let tool = match view {
            ControlView::Inbox => "control_inbox",
            ControlView::Approvals => "control_approvals",
            ControlView::RedStatus => "control_red_status",
        };
        let _ = self.record(o, Kind::ToolUse, Some(tool), json!({}));
        // The readers show the whole estate's queue; only tier 1 sees it. Inbox is per person.
        let tier1 = who.groups.iter().any(|g| self.tier1.contains(g));
        let c = match view {
            ControlView::Inbox => Ok(Component::InboxList(self.inbox(who))),
            _ if !tier1 => Err("not yours to see".to_string()),
            ControlView::Approvals => self.reader("awaiting-operator.py").and_then(|v| {
                let items = serde_json::from_value(v.get("items").cloned().unwrap_or(Value::Null));
                let unknown = serde_json::from_value(v.get("unknown").cloned().unwrap_or(Value::Null));
                match (items, unknown) {
                    (Ok(items), Ok(unknown)) => Ok(Component::ApprovalsList(ApprovalsList { items, unknown })),
                    (Err(e), _) | (_, Err(e)) => Err(format!("awaiting-operator.py: unexpected shape: {e}")),
                }
            }),
            ControlView::RedStatus => self.reader("red-status.py").and_then(|v| {
                let four = ["red_count", "reds", "hold_count", "holds"].map(|k| (k.to_string(), v.get(k).cloned().unwrap_or(Value::Null)));
                serde_json::from_value::<RedStatus>(Value::Object(four.into_iter().collect()))
                    .map(Component::RedStatus).map_err(|e| format!("red-status.py: unexpected shape: {e}"))
            }),
        };
        match c {
            Ok(component) => {
                let _ = self.record(o, Kind::ToolResult, Some(tool), json!({"ok": true}));
                send(out, &ToShell::Render { session: o.session.clone(), component });
            }
            Err(why) => {
                let _ = self.record(o, Kind::ToolResult, Some(tool), json!({"error": why}));
                refuse(out, &why);
            }
        }
    }

    /// `python3 tools/<name> --json` in the repo; Err on a non-zero exit, a timeout or no JSON.
    fn reader(&self, name: &str) -> Result<Value, String> {
        let child = std::process::Command::new("python3").arg(self.repo.join("tools").join(name)).arg("--json")
            .current_dir(&self.repo).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null())
            .process_group(0).spawn().map_err(|e| format!("{name}: {e}"))?;
        let pid = child.id() as libc::pid_t;
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || tx.send(child.wait_with_output()));
        let done = rx.recv_timeout(Duration::from_secs(self.reader_secs)).map_err(|_| {
            // The whole group: a child the reader spawned holds the pipe the waiter reads.
            // ponytail: a reader that setsid()s escapes; the group id could be reused in the
            // instant between a late exit and this kill. A pidfd-style wait closes both.
            unsafe { libc::kill(-pid, libc::SIGKILL) };
            format!("{name}: no answer in {}s", self.reader_secs)
        })?;
        let o = done.map_err(|e| format!("{name}: {e}"))?;
        if !o.status.success() {
            return Err(format!("{name} exited {}", o.status));
        }
        serde_json::from_slice(&o.stdout).map_err(|e| format!("{name}: not JSON: {e}"))
    }

    /// Two sources on the human door, as the person (ruling 3): captures not yet promoted (KEAP
    /// returns an admin everyone's; a rejected one still waits), and the moderation queue.
    /// A source that cannot be read is named in `refused`, never emptied.
    fn inbox(&self, who: &Person) -> InboxList {
        let base = self.keap_url.trim_end_matches('/');
        let (mut items, mut refused) = (Vec::new(), Vec::new());
        match self.keap(who, &format!("{base}/api/metadata"), None).and_then(|v| listed(&v, "/data", "capture")) {
            Ok(i) => items.extend(i),
            Err(why) => refused.push(format!("captures: {why}")),
        }
        match self.keap_status(who, &format!("{base}/api/promotions?status=proposed"), None) {
            Ok((403, _)) => refused.push("promotions: not yours to moderate".into()),
            Ok((200, v)) => match listed(&v, "/data/items", "promotion") {
                Ok(i) => items.extend(i),
                Err(why) => refused.push(format!("promotions: {why}")),
            },
            Ok((status, _)) => refused.push(format!("promotions: KEAP answered {status}")),
            Err(why) => refused.push(format!("promotions: {why}")),
        }
        InboxList { items, refused }
    }
}

/// The model's component, or why not: only a SHOW_KINDS kind, closed props, within its caps.
/// It can only become a Render; an approval is minted by ask() alone.
fn show(args: &Value) -> Result<Component, String> {
    if let Some(k) = args.as_object().and_then(|a| a.keys().find(|k| *k != "component")) {
        return Err(format!("show has no parameter `{k}`; it takes `component`"));
    }
    let kind = args.pointer("/component/kind").and_then(Value::as_str).unwrap_or("");
    if !SHOW_KINDS.contains(&kind) {
        return Err(format!("show draws {}, not {kind:?}", SHOW_KINDS.join(", ")));
    }
    let c = serde_json::from_value::<Component>(args["component"].clone()).map_err(|e| format!("show {kind}: {e}"))?;
    c.check().map_err(|e| format!("show {kind}: {e}"))?;
    Ok(c)
}

/// A cell as text, as the shells show it: null is empty, a string is itself.
fn text(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        v => v.to_string(),
    }
}

/// Nulls last either way; numbers by value and before strings, strings case-insensitively.
fn by(a: Option<&Value>, b: Option<&Value>, desc: bool) -> Ordering {
    let key = |v: Option<&Value>| match v {
        None | Some(Value::Null) => None,
        Some(Value::Number(n)) => Some((0, n.as_f64().unwrap_or(0.0), String::new())),
        Some(v) => Some((1, 0.0, text(v).to_lowercase())),
    };
    match (key(a), key(b)) {
        (None, None) => Ordering::Equal,
        (None, _) => Ordering::Greater,
        (_, None) => Ordering::Less,
        (Some(x), Some(y)) => {
            let o = x.0.cmp(&y.0).then(x.1.total_cmp(&y.1)).then_with(|| x.2.cmp(&y.2));
            if desc { o.reverse() } else { o }
        }
    }
}

/// The waiting entries of one inbox source; a row without an id or title fails the source.
fn listed(v: &Value, at: &str, source: &str) -> Result<Vec<InboxItem>, String> {
    let rows = v.pointer(at).and_then(Value::as_array).ok_or("no list in the answer")?;
    let waiting = |r: &&Value| match source {
        "capture" => r.pointer("/metadata/promotedTo").is_none_or(Value::is_null),
        _ => r.get("status").and_then(Value::as_str) == Some("proposed"),
    };
    rows.iter().filter(waiting).map(|r| {
        let s = |p: &str| r.pointer(p).and_then(Value::as_str).filter(|x| !x.is_empty()).map(str::to_string);
        let id = s("/id").ok_or("a row without an id")?;
        let title = match source {
            "capture" => s("/title"),
            _ => s("/object/name").or_else(|| s("/object/title")).or_else(|| s("/captureId")),
        }.ok_or(format!("row {id} has no title"))?;
        let created_at = match r.get("createdAt") {
            Some(Value::String(t)) => t.clone(),
            Some(Value::Number(n)) => n.as_i64().map_or(n.to_string(), iso),
            _ => String::new(),
        };
        Ok(InboxItem { id, title, source: source.into(), created_at })
    }).collect()
}

/// "YYYY-MM-DD HH:MM" now, for the prompt: a model has no clock and invents one.
fn now_utc() -> String {
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64);
    iso(t)[..16].replace('T', " ")
}

/// Epoch seconds (KEAP's created_at) as UTC ISO 8601; days to civil date per H. Hinnant.
fn iso(t: i64) -> String {
    let (days, secs) = (t.div_euclid(86_400), t.rem_euclid(86_400));
    let z = days + 719_468;
    let (era, doe) = (z.div_euclid(146_097), z.rem_euclid(146_097));
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let (d, m) = (doy - (153 * mp + 2) / 5 + 1, if mp < 10 { mp + 3 } else { mp - 9 });
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", secs / 3600, secs % 3600 / 60, secs % 60)
}

#[test]
fn iso_matches_the_calendar_at_its_edges() {
    for (t, want) in [(0, "1970-01-01T00:00:00Z"), (951_782_400, "2000-02-29T00:00:00Z"),
                      (1_760_000_000, "2025-10-09T08:53:20Z"), (4_102_444_800, "2100-01-01T00:00:00Z")] {
        assert_eq!(iso(t), want);
    }
}

// mistral-eu is https: an agent built without TLS refused it live ("TLS required").
#[test]
fn an_https_backend_gets_a_tls_handshake() {
    let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("https://127.0.0.1:{}/", l.local_addr().unwrap().port());
    std::thread::spawn(move || drop(l.accept()));
    let e = agent(5).get(&url).call().unwrap_err();
    assert!(!matches!(e, ureq::Error::TlsRequired), "{e}");
}
