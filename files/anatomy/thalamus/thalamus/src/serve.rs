//! `thalamus serve`: newline-delimited JSON on ~/.nos/thalamus.sock (0600). The kernel
//! names the peer (getpeereid), the receptor's ~/.nos/identity-map.yml names the person,
//! and every KEAP call goes to the human door as that person behind the proxy secret
//! only this process holds. A peer the map does not name is refused, never defaulted.

use crate::binding::Binding;
use crate::ledger::{Kind, Ledger, Session};
use nos_contract::renderers::{ApprovalsList, CellChange, Component, InboxItem, InboxList, RedStatus, Row, RowDiffApproval,
                               TableResults};
use nos_contract::wire::{decode_to_thalamus, encode, ControlView, Decision, ToShell, ToThalamus};
use nos_contract::uid;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::os::unix::io::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
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
    /// None when iris is unbound: controls still answer, turns are refused.
    model: Option<Binding>,
    messages: Vec<Value>,
    tokens: (i64, i64),
    /// Approvals asked and not yet decided; a decision removes its id, so each is decided once.
    pending: HashSet<String>,
}

fn send(out: &mut UnixStream, m: &ToShell) {
    let _ = out.write_all(encode(m).as_bytes());
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

const SEARCH_ROWS: &str = "Find rows in one DataTable whose cells contain `q` (case-insensitive substring, \
read as the person). Renders table_results: the matching rows, shown to the person as a table; \
projected is false because this is a substring match, not a semantic search.";

const PROPOSE_ROW_EDIT: &str = "Propose new values for cells of one existing row. Renders row_diff_approval: \
the person sees each changed cell old -> new and approves or rejects it. Nothing is written until they \
approve; you are told only that the proposal waits for them.";

fn tools() -> Value {
    json!([{"type": "function", "function": {"name": "search_rows", "description": SEARCH_ROWS,
        "parameters": {"type": "object", "additionalProperties": false, "required": ["table", "q"], "properties": {
            "table": {"type": "string", "description": "the table id"},
            "q": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20}}}}},
        {"type": "function", "function": {"name": "propose_row_edit", "description": PROPOSE_ROW_EDIT,
        "parameters": {"type": "object", "additionalProperties": false, "required": ["table", "row_id", "values"], "properties": {
            "table": {"type": "string", "description": "the table id"},
            "row_id": {"type": "string", "description": "the row's __id from search_rows"},
            "values": {"type": "object", "description": "column -> new value; null clears the cell"}}}}}])
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
                    }
                }
                Ok(ToThalamus::Control { view }) => {
                    if let Some(o) = self.ensure(&who, &mut out, &mut open) {
                        self.control(&who, &mut out, o, view);
                    }
                }
                Ok(ToThalamus::ApprovalDecision { approval, decision, note }) => match open.as_mut() {
                    Some(o) if o.pending.contains(&approval) => self.decide(&who, &mut out, o, &approval, decision, note),
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
        let model = self.binding.clone().ok();
        let session = mint_uuid().map_err(|e| format!("no session id: {e}"))?;
        let actor = format!("user:{}", who.uid());
        let model_uri = model.as_ref().map_or("unbound".to_string(), |m| format!("{}-{}", m.name, m.model_id));
        let s = Session { uuid: &session, agent_name: "iris", agent_version: 1, actor: &actor, model_uri: &model_uri };
        self.ledger.lock().map_err(|_| "ledger poisoned".to_string())?.start(&s).map_err(|e| format!("ledger: {e}"))?;
        send(out, &ToShell::Session { session: session.clone(), actor, model_uri });
        let system = format!("You are Iris. You act for {} and see only what they may see.", who.username);
        Ok(Open { session, model, messages: vec![json!({"role": "system", "content": system})], tokens: (0, 0),
                  pending: HashSet::new() })
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
        let (text, result) = match d {
            Decision::Reject => ("Rejected: nothing was written.".to_string(), json!({"approval": approval, "written": false})),
            Decision::Approve => match self.commit(who, id) {
                Ok(row) => (format!("Approved: row {row} written."), json!({"approval": approval, "written": true, "row": row})),
                Err(why) => (format!("Approved, but the write failed: {why}"), json!({"approval": approval, "error": why})),
            },
        };
        let _ = self.record(o, Kind::ToolResult, Some("propose_row_edit"), result);
        send(out, &ToShell::Text { session: o.session.clone(), text });
    }

    /// The only write path. It takes a decision row id and writes exactly what that row's
    /// request showed the person; no approve row in the ledger, no POST.
    pub fn commit(&self, who: &Person, decision: i64) -> Result<String, String> {
        let (actor, table, row_id, values) = self.ledger.lock().map_err(|_| "ledger poisoned".to_string())?.approved(decision)?;
        if actor != format!("user:{}", who.uid()) {
            return Err("the approval belongs to another person".into());
        }
        let url = format!("{}/api/tables/{}/rows", self.keap_url.trim_end_matches('/'), enc(&table));
        // ponytail: KEAP upserts, so a row deleted since the proposal is recreated; needs an if-match on KEAP's side.
        self.keap(who, &url, Some(&json!({"id": row_id, "values": values})))?;
        Ok(row_id)
    }

    fn turn(&self, who: &Person, out: &mut UnixStream, o: &mut Open, text: &str) {
        let Some(model) = o.model.clone() else {
            let why = self.binding.as_ref().err().cloned().unwrap_or_default();
            return refuse(out, &format!("iris has no model: {why}"));
        };
        let _ = self.record(o, Kind::Message, None, json!({"role": "person", "text": text}));
        o.messages.push(json!({"role": "user", "content": text}));
        let mut calls = 0;
        loop {
            let msg = match self.complete(&model, o) {
                Ok(m) => m,
                Err(why) => return refuse(out, &why),
            };
            o.messages.push(msg.clone());
            let Some(asked) = msg.get("tool_calls").and_then(Value::as_array).filter(|a| !a.is_empty()).cloned() else {
                let text = msg.get("content").and_then(Value::as_str).unwrap_or("").to_string();
                let _ = self.record(o, Kind::Message, None, json!({"role": "iris", "text": text}));
                return send(out, &ToShell::Text { session: o.session.clone(), text });
            };
            for call in asked {
                calls += 1;
                if calls > MAX_TOOL_CALLS {
                    let text = format!("Stopped: more than {MAX_TOOL_CALLS} tool calls in one turn.");
                    let _ = self.record(o, Kind::Message, None, json!({"role": "thalamus", "text": text}));
                    return send(out, &ToShell::Text { session: o.session.clone(), text });
                }
                let name = call.pointer("/function/name").and_then(Value::as_str).unwrap_or("");
                let args: Value = call.pointer("/function/arguments").and_then(Value::as_str)
                    .and_then(|a| serde_json::from_str(a).ok()).unwrap_or(Value::Null);
                let _ = self.record(o, Kind::ToolUse, Some(name), json!({"args": args}));
                let result = match name {
                    "search_rows" => self.search_rows(who, &args).map(|t| {
                        let ids: Vec<&str> = t.rows.iter().map(|r| r.__id.as_str()).collect();
                        let _ = self.record(o, Kind::ToolResult, Some(name), json!({"rows": ids}));
                        let v = json!({"table": t.table, "rows": t.rows});
                        send(out, &ToShell::Render { session: o.session.clone(), component: Component::TableResults(t) });
                        v
                    }),
                    // Its tool_result is written by decide(), once the person has answered.
                    "propose_row_edit" => self.propose_row_edit(who, &args).and_then(|d| self.ask(o, out, d)),
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

    /// GET /api/tables/:id/rows as the person, every page, then a substring filter.
    fn search_rows(&self, who: &Person, args: &Value) -> Result<TableResults, String> {
        let table = args.get("table").and_then(Value::as_str).filter(|t| !t.is_empty()).ok_or("search_rows needs `table`")?;
        let q = args.get("q").and_then(Value::as_str).map(|q| q.trim().to_lowercase()).filter(|q| !q.is_empty())
            .ok_or("search_rows needs `q`")?;
        let limit = args.get("limit").and_then(Value::as_u64).unwrap_or(20).clamp(1, 20) as usize;
        let mut hits: Vec<Row> = self.rows(who, table)?.into_iter()
            .filter(|(_, v)| Value::Object(v.clone()).to_string().to_lowercase().contains(&q))
            .map(|(id, v)| Row { __id: id, cells: v.into_iter().collect::<BTreeMap<_, _>>() })
            .collect();
        hits.truncate(limit);
        let columns: BTreeSet<String> = hits.iter().flat_map(|r| r.cells.keys().cloned()).collect();
        Ok(TableResults { table: table.to_string(), columns: columns.into_iter().collect(), rows: hits, projected: false })
    }

    /// Every row of one table the person may read: GET /api/tables/:id/rows, every page.
    fn rows(&self, who: &Person, table: &str) -> Result<Vec<(String, Map<String, Value>)>, String> {
        let (mut all, mut cursor) = (Vec::new(), None::<String>);
        for _ in 0..MAX_PAGES {
            let mut url = format!("{}/api/tables/{}/rows?limit=500", self.keap_url.trim_end_matches('/'), enc(table));
            if let Some(c) = &cursor {
                url += &format!("&cursor={}", enc(c));
            }
            let page = self.keap(who, &url, None)?;
            for r in page.pointer("/data/rows").and_then(Value::as_array).into_iter().flatten() {
                let id = r.get("id").and_then(Value::as_str).unwrap_or_default().to_string();
                all.push((id, r.get("values").and_then(Value::as_object).cloned().unwrap_or_default()));
            }
            cursor = page.pointer("/data/nextCursor").and_then(Value::as_str).map(str::to_string);
            if cursor.is_none() {
                break;
            }
        }
        Ok(all)
    }

    /// The cell diff of one existing row the person can read; only changed cells survive.
    fn propose_row_edit(&self, who: &Person, args: &Value) -> Result<RowDiffApproval, String> {
        let s = |k: &str| args.get(k).and_then(Value::as_str).filter(|v| !v.is_empty()).ok_or(format!("propose_row_edit needs `{k}`"));
        let (table, row_id) = (s("table")?, s("row_id")?);
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
        let c = match view {
            ControlView::Inbox => Ok(Component::InboxList(self.inbox(who))),
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
            .spawn().map_err(|e| format!("{name}: {e}"))?;
        let pid = child.id() as libc::pid_t;
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || tx.send(child.wait_with_output()));
        let done = rx.recv_timeout(Duration::from_secs(self.reader_secs)).map_err(|_| {
            unsafe { libc::kill(pid, libc::SIGKILL) };
            format!("{name}: no answer in {}s", self.reader_secs)
        })?;
        let o = done.map_err(|e| format!("{name}: {e}"))?;
        if !o.status.success() {
            return Err(format!("{name} exited {}", o.status));
        }
        serde_json::from_slice(&o.stdout).map_err(|e| format!("{name}: not JSON: {e}"))
    }

    /// Two sources on the human door, as the person: own captures not yet promoted, and the
    /// moderation queue. A source that cannot be read is named in `refused`, never emptied.
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
        // ponytail: an epoch createdAt is shown as its number; format it when a person asks.
        let created_at = match r.get("createdAt") {
            Some(Value::String(t)) => t.clone(),
            Some(n @ Value::Number(_)) => n.to_string(),
            _ => String::new(),
        };
        Ok(InboxItem { id, title, source: source.into(), created_at })
    }).collect()
}
