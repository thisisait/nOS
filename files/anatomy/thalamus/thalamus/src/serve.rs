//! `thalamus serve`: newline-delimited JSON on ~/.nos/thalamus.sock (0600). The kernel
//! names the peer (getpeereid), the receptor's ~/.nos/identity-map.yml names the person,
//! and every KEAP call goes to the human door as that person behind the proxy secret
//! only this process holds. A peer the map does not name is refused, never defaulted.

use crate::binding::Binding;
use crate::ledger::{Kind, Ledger, Session};
use nos_contract::renderers::{Component, Row, TableResults};
use nos_contract::wire::{decode_to_thalamus, encode, ToShell, ToThalamus};
use nos_contract::uid;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::os::unix::io::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// The map the receptor renders (roles/pazny.receptor); the thalamus renders none.
pub const IDENTITY_MAP: &str = ".nos/identity-map.yml";
const MAX_LINE: u64 = 1 << 20;
const MAX_TOOL_CALLS: usize = 8;
const MAX_PAGES: usize = 40;

pub struct Server {
    pub map: PathBuf,
    pub keap_url: String,
    pub secret: String,
    pub ledger: Mutex<Ledger>,
    pub binding: Result<Binding, String>,
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
    model: Binding,
    messages: Vec<Value>,
    tokens: (i64, i64),
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

fn tools() -> Value {
    json!([{"type": "function", "function": {"name": "search_rows", "description": SEARCH_ROWS,
        "parameters": {"type": "object", "additionalProperties": false, "required": ["table", "q"], "properties": {
            "table": {"type": "string", "description": "the table id"},
            "q": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20}}}}}])
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
                    if open.is_none() {
                        match self.open(&who, &mut out) {
                            Ok(o) => open = Some(o),
                            Err(why) => {
                                refuse(&mut out, &why);
                                continue;
                            }
                        }
                    }
                    if let Some(o) = open.as_mut() {
                        self.turn(&who, &mut out, o, &text);
                    }
                }
                // ponytail: approvals land in increment 6, control views in 7.
                Ok(_) => refuse(&mut out, "not served yet in this slice"),
            }
        }
        if let Some(o) = open {
            let _ = self.ledger.lock().map(|l| l.end(&o.session, "connection_closed", (Some(o.tokens.0), Some(o.tokens.1))));
            self.say(format!("closed {} for {}", o.session, who.username));
        }
    }

    fn open(&self, who: &Person, out: &mut UnixStream) -> Result<Open, String> {
        let model = self.binding.clone()?;
        let session = mint_uuid().map_err(|e| format!("no session id: {e}"))?;
        let actor = format!("user:{}", who.uid());
        let model_uri = format!("{}-{}", model.name, model.model_id);
        let s = Session { uuid: &session, agent_name: "iris", agent_version: 1, actor: &actor, model_uri: &model_uri };
        self.ledger.lock().map_err(|_| "ledger poisoned".to_string())?.start(&s).map_err(|e| format!("ledger: {e}"))?;
        send(out, &ToShell::Session { session: session.clone(), actor, model_uri });
        let system = format!("You are Iris. You act for {} and see only what they may see.", who.username);
        Ok(Open { session, model, messages: vec![json!({"role": "system", "content": system})], tokens: (0, 0) })
    }

    fn record(&self, o: &Open, kind: Kind, tool: Option<&str>, v: Value) {
        if let Ok(l) = self.ledger.lock() {
            if let Err(e) = l.record(&o.session, kind, tool, &v) {
                drop(l);
                self.say(format!("ledger refused an event of {}: {e}", o.session));
            }
        }
    }

    fn turn(&self, who: &Person, out: &mut UnixStream, o: &mut Open, text: &str) {
        self.record(o, Kind::Message, None, json!({"role": "person", "text": text}));
        o.messages.push(json!({"role": "user", "content": text}));
        let mut calls = 0;
        loop {
            let msg = match self.complete(o) {
                Ok(m) => m,
                Err(why) => return refuse(out, &why),
            };
            o.messages.push(msg.clone());
            let Some(asked) = msg.get("tool_calls").and_then(Value::as_array).filter(|a| !a.is_empty()).cloned() else {
                let text = msg.get("content").and_then(Value::as_str).unwrap_or("").to_string();
                self.record(o, Kind::Message, None, json!({"role": "iris", "text": text}));
                return send(out, &ToShell::Text { session: o.session.clone(), text });
            };
            for call in asked {
                calls += 1;
                if calls > MAX_TOOL_CALLS {
                    let text = format!("Stopped: more than {MAX_TOOL_CALLS} tool calls in one turn.");
                    self.record(o, Kind::Message, None, json!({"role": "thalamus", "text": text}));
                    return send(out, &ToShell::Text { session: o.session.clone(), text });
                }
                let name = call.pointer("/function/name").and_then(Value::as_str).unwrap_or("");
                let args: Value = call.pointer("/function/arguments").and_then(Value::as_str)
                    .and_then(|a| serde_json::from_str(a).ok()).unwrap_or(Value::Null);
                self.record(o, Kind::ToolUse, Some(name), json!({"args": args}));
                let result = match name {
                    "search_rows" => self.search_rows(who, &args),
                    _ => Err(format!("unknown tool {name:?}")),
                };
                let for_model = match result {
                    Ok(t) => {
                        let ids: Vec<&str> = t.rows.iter().map(|r| r.__id.as_str()).collect();
                        self.record(o, Kind::ToolResult, Some(name), json!({"rows": ids}));
                        let v = json!({"table": t.table, "rows": t.rows});
                        send(out, &ToShell::Render { session: o.session.clone(), component: Component::TableResults(t) });
                        v
                    }
                    Err(why) => {
                        self.record(o, Kind::ToolResult, Some(name), json!({"error": why}));
                        json!({"error": why})
                    }
                };
                o.messages.push(json!({"role": "tool", "tool_call_id": call.get("id").cloned().unwrap_or(Value::Null),
                                       "content": for_model.to_string()}));
            }
        }
    }

    /// One chat-completions call; the model gets the conversation, never a KEAP header.
    fn complete(&self, o: &mut Open) -> Result<Value, String> {
        let url = format!("{}/chat/completions", o.model.base_url.trim_end_matches('/'));
        let mut req = agent(300).post(&url);
        if !o.model.auth_token.is_empty() {
            req = req.header("Authorization", &format!("Bearer {}", o.model.auth_token));
        }
        let body = json!({"model": o.model.model_id, "messages": o.messages, "tools": tools()});
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
        if self.secret.is_empty() {
            return Err("the thalamus holds no KEAP proxy secret".into());
        }
        let (mut hits, mut cursor) = (Vec::new(), None::<String>);
        for _ in 0..MAX_PAGES {
            let mut url = format!("{}/api/tables/{}/rows?limit=500", self.keap_url.trim_end_matches('/'), enc(table));
            if let Some(c) = &cursor {
                url += &format!("&cursor={}", enc(c));
            }
            let page = self.keap_get(who, &url)?;
            for r in page.pointer("/data/rows").and_then(Value::as_array).into_iter().flatten() {
                let values = r.get("values").and_then(Value::as_object).cloned().unwrap_or_default();
                if Value::Object(values.clone()).to_string().to_lowercase().contains(&q) {
                    let id = r.get("id").and_then(Value::as_str).unwrap_or_default().to_string();
                    hits.push(Row { __id: id, cells: values.into_iter().collect::<BTreeMap<_, _>>() });
                }
            }
            cursor = page.pointer("/data/nextCursor").and_then(Value::as_str).map(str::to_string);
            if cursor.is_none() {
                break;
            }
        }
        hits.truncate(limit);
        let columns: BTreeSet<String> = hits.iter().flat_map(|r| r.cells.keys().cloned()).collect();
        Ok(TableResults { table: table.to_string(), columns: columns.into_iter().collect(), rows: hits, projected: false })
    }

    /// keapAs() in the face's upstream.ts: the person's headers behind the proxy secret.
    fn keap_get(&self, who: &Person, url: &str) -> Result<Value, String> {
        let t0 = std::time::Instant::now();
        let mut r = agent(30)
            .get(url)
            .header("x-keap-proxy-secret", &self.secret)
            .header("x-authentik-username", &who.username)
            .header("x-authentik-name", &who.username)
            .header("x-authentik-uid", &who.uid())
            .header("x-authentik-groups", &who.groups.join(","))
            .call()
            .map_err(|e| format!("KEAP unreachable: {e}"))?;
        let status = r.status().as_u16();
        // The log names the path, never the query, the headers or the secret.
        let path = url.split('?').next().unwrap_or("").splitn(4, '/').nth(3).unwrap_or("");
        self.say(format!("{status} as {} GET /{path} {}ms", who.username, t0.elapsed().as_millis()));
        let v: Value = r.body_mut().read_json().map_err(|e| format!("KEAP answered {status} with no JSON: {e}"))?;
        if status != 200 {
            let why = v.get("error").and_then(Value::as_str).unwrap_or("").chars().take(300).collect::<String>();
            return Err(format!("KEAP answered {status}: {why}"));
        }
        Ok(v)
    }
}
