//! `thalamus serve`: newline-delimited JSON on ~/.nos/thalamus.sock (0600). The kernel
//! names the peer (getpeereid), the receptor's ~/.nos/identity-map.yml names the person,
//! and every KEAP call goes to the human door as that person behind the proxy secret
//! only this process holds. A peer the map does not name is refused, never defaulted.

use crate::binding::Binding;
use crate::ledger::{Kind, Ledger, RowOp, Session};
use nos_contract::renderers::{is_date, ApprovalsList, Axis, CellChange, Chart, ChartKind, Choice, Component, FieldKind, Form, FormField,
                               InboxItem, InboxList, Omitted, RedStatus, Row, RowDiffApproval, Series, TableResults};
use nos_contract::wire::{check_spec, decode_to_thalamus, encode, ChartSpec, ControlView, Decision, Op, Phase, ToShell, ToThalamus, Trigger,
                         WidgetChart, WidgetSpec};
use nos_contract::uid;
use serde_json::{json, Map, Value};
use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap, HashSet};
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
    /// NOS_DECIDER_EXES: the executables that may decide; empty records the peer only.
    pub deciders: Vec<PathBuf>,
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

/// The peer process as the kernel names it: {pid, exe}, null where it cannot say. Read per line:
/// on macOS LOCAL_PEERPID is the last process to use the peer socket, i.e. this line's sender.
/// Linux SO_PEERCRED names only the connector, so a set decider list fails closed there.
fn peer(s: &UnixStream) -> Value {
    let pid = peer_pid(s);
    json!({"pid": pid, "exe": pid.and_then(exe_of)})
}

#[cfg(target_os = "macos")]
fn peer_pid(s: &UnixStream) -> Option<i32> {
    let (mut pid, mut len): (libc::pid_t, libc::socklen_t) = (0, std::mem::size_of::<libc::pid_t>() as libc::socklen_t);
    let rc = unsafe { libc::getsockopt(s.as_raw_fd(), libc::SOL_LOCAL, libc::LOCAL_PEERPID, (&mut pid as *mut libc::pid_t).cast(), &mut len) };
    (rc == 0 && pid > 0).then_some(pid)
}

#[cfg(target_os = "linux")]
fn peer_pid(s: &UnixStream) -> Option<i32> {
    let mut c: libc::ucred = unsafe { std::mem::zeroed() };
    let mut len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let rc = unsafe { libc::getsockopt(s.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PEERCRED, (&mut c as *mut libc::ucred).cast(), &mut len) };
    (rc == 0 && c.pid > 0).then_some(c.pid)
}

#[cfg(target_os = "macos")]
fn exe_of(pid: i32) -> Option<String> {
    let mut buf = vec![0u8; libc::PROC_PIDPATHINFO_MAXSIZE as usize];
    let n = unsafe { libc::proc_pidpath(pid, buf.as_mut_ptr().cast(), buf.len() as u32) };
    (n > 0).then(|| String::from_utf8_lossy(&buf[..n as usize]).into_owned())
}

#[cfg(target_os = "linux")]
fn exe_of(pid: i32) -> Option<String> {
    std::fs::read_link(format!("/proc/{pid}/exe")).ok().map(|p| p.to_string_lossy().into_owned())
}

/// Why this peer exe may not decide, or None. An empty list is off (record only); a listed entry
/// counts only when absolute and is canonicalized. The exe is the kernel's resolved path, taken
/// as given: resolving it again would follow a symlink swapped into it since it was read.
pub fn decider_refusal(deciders: &[PathBuf], exe: Option<&str>) -> Option<String> {
    if deciders.is_empty() {
        return None;
    }
    if cfg!(not(target_os = "macos")) {
        return Some("this kernel names the connecting process, not the sender, so no decider is trusted".into());
    }
    let Some(exe) = exe else { return Some("the peer's executable cannot be determined, and only a listed decider decides".into()) };
    let listed = deciders.iter().any(|d| d.is_absolute() && std::fs::canonicalize(d).is_ok_and(|c| c.as_os_str() == exe));
    (!listed).then(|| format!("{exe} is not a listed decider (thalamus_decider_exes)"))
}

#[cfg(target_os = "macos")]
fn peer_login(s: &UnixStream) -> Option<String> {
    let (mut uid, mut gid) = (0, 0);
    (unsafe { libc::getpeereid(s.as_raw_fd(), &mut uid, &mut gid) } == 0).then_some(())?;
    login(uid)
}

/// Linux has no getpeereid: SO_PEERCRED carries the connector's uid (CI builds here).
#[cfg(target_os = "linux")]
fn peer_login(s: &UnixStream) -> Option<String> {
    let mut c: libc::ucred = unsafe { std::mem::zeroed() };
    let mut len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let rc = unsafe { libc::getsockopt(s.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PEERCRED, (&mut c as *mut libc::ucred).cast(), &mut len) };
    (rc == 0).then_some(())?;
    login(c.uid)
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

/// Every name a spec may give `table`: its id, and "roadmap" when that alias resolves to it.
fn table_names(table: &str) -> Vec<String> {
    let mut names = vec![table.to_string()];
    if table != "roadmap" && table_id("roadmap") == table {
        names.push("roadmap".into());
    }
    names
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
    /// The widget forms this session sent, by widget token: a re-run replaces the old form id.
    forms: HashMap<String, Form>,
    /// The choices this session asked and the person has not answered, by the id serve minted.
    choices: HashMap<String, Choice>,
}

/// How many widget forms one session holds open.
const MAX_FORMS: usize = 24;
/// How many unanswered choices one session holds.
const MAX_CHOICES: usize = 4;

/// A query's rows after q and where; group, order and limit ride along unapplied.
struct Matched<'a> {
    table: String,
    name: String,
    /// What was asked, said for a person.
    query: String,
    total: usize,
    schema: Vec<Map<String, Value>>,
    hits: Vec<(String, Map<String, Value>)>,
    group: Option<&'a str>,
    order: Option<(&'a str, bool)>,
    limit: usize,
    columns: Vec<String>,
}

fn send(out: &mut UnixStream, m: &ToShell) {
    let _ = out.write_all(encode(m).as_bytes());
}

/// What this session is doing now; the pupil's eye shows it.
fn activity(out: &mut UnixStream, o: &Open, phase: Phase) {
    send(out, &ToShell::Activity { session: o.session.clone(), phase });
}

/// A write landed in `table` (already in the ledger): this connection's widgets may re-run, under
/// every name a spec may give it. ponytail: this connection only; other shells of the person learn
/// on their next run (roadmap thalamus-table-changed-broadcast).
fn changed(out: &mut UnixStream, o: &Open, table: &str, row: &str) {
    for table in table_names(table) {
        send(out, &ToShell::TableChanged { session: o.session.clone(), table, row: row.to_string() });
    }
}

fn refuse(out: &mut UnixStream, why: &str) {
    send(out, &ToShell::Refused { reason: why.to_string(), widget: None });
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

const RED_STATUS: &str = "What is red on the estate right now, and what is on hold on purpose, from \
tools/red-status.py run as the operator. Renders red_status to the person. Tier 1 only. If it cannot be read, \
the state is UNKNOWN: say so, never zero and never green.";

const SHOW: &str = "Show the person structured output: one component of a closed vocabulary, drawn as text. \
A component outside its shape or caps is refused and you are told why; nothing is drawn. It cannot ask for an \
approval: only propose_row_edit does, and query_rows draws its own table. For a bar, line or pie chart of a \
table's rows pass `source`: the thalamus counts, sums or averages the rows as the person and draws those numbers \
in place of your series, and the person can pin the chart live.";

/// The kinds the model may choose; the rest are drawn by a tool or a control, never by show.
/// No markdown: plain text already draws as markdown, and a markdown show was then said again as text.
pub const SHOW_KINDS: [&str; 9] = ["table", "list", "record", "chart", "tree", "timeline", "graph", "sequence", "choice"];

/// The props a kind accepts, so a refusal can show the shape to retry.
pub const SHOW_SHAPE: &[(&str, &str)] = &[
    ("table", "{title?, columns[] <=12, rows[][] <=50, each row as long as columns}"),
    ("list", "{title?, ordered, items[{text, detail?, tone? ok|info|warn|bad, delta? added|removed|changed}] <=50}"),
    ("record", "{title?, fields[{key, value, delta? added|removed|changed, was?}] <=40}; was is the old value, only when changed"),
    ("chart", "{title?, chart bar|stacked_bar|line|area|scatter|pie, x category|number|time, series[{name, points[[x, number]] <=60}] <=6}; \
x is a string even for number (\"3\") or time (\"2026-10-13\" or \"2026-10-13T08:00:00Z\"); line, area and stacked_bar \
series share the same x in order; scatter needs number or time x; pie is 1 series, values >= 0"),
    ("tree", "{title?, nodes[{label, note?, delta? added|removed|changed, children[]}]}, depth <=4, nodes <=100; \
a child of an added or removed node is that too: leave its delta out"),
    ("timeline", "{title?, items[{when, title, note?, hi?, until?, lane?}] <=30}; when and until as dates \
(\"2026-10-13\") draw a time axis, until not before when; lane groups items on one row, <=40 chars"),
    ("graph", "{title?, nodes[{id, label, note?, tone?}] <=60 (tone ok|info|warn|bad), edges[{from, to, label?, dashed?}] <=120}; \
id is [A-Za-z0-9_-]{1,64} and unique; every edge's from and to name a node id"),
    ("sequence", "{title?, participants[] 2-8 (unique, <=40 chars), steps[] <=40, each {from, to, text, dashed?} (text <=120; \
dashed for a reply) or {note, over[]} (note <=200 over 1-2 participants) or {phase} (<=60)}; from, to and over name participants exactly"),
    ("choice", "{question (<=15 words, <=120 chars), options[{label, note?}] 2-6 (label <=60, unique; note <=200), \
suggested[] (option labels: exactly 1, or 1 or more when multi), multi}; never an id: the thalamus mints it"),
];

fn expected_shape(kind: &str) -> String {
    SHOW_SHAPE.iter().find(|(k, _)| *k == kind).map(|(_, s)| (*s).to_string()).unwrap_or_else(|| {
        SHOW_SHAPE.iter().map(|(k, s)| format!("{k} {s}")).collect::<Vec<_>>().join("; ")
    })
}

/// One `oneOf` branch per kind; the descriptions are thalamus-shell.yml's vocabulary lines.
pub fn show_schema() -> Value {
    let title = json!({"type": "string", "maxLength": 120});
    let delta = json!({"enum": ["added", "removed", "changed"], "description": "what an action would do to it, for a dry run"});
    let branch = |kind: &str, about: &str, props: Value| json!({"type": "object", "additionalProperties": false,
        "required": ["kind", "props"], "description": about, "properties": {"kind": {"const": kind}, "props": props}});
    let closed = |required: &[&str], properties: Value| json!({"type": "object", "additionalProperties": false,
        "required": required, "properties": properties});
    let mut source = closed(&["query", "x", "op"], json!({
        "query": closed(&["table"], json!({"table": {"type": "string", "description": "the table id, or \"roadmap\""},
            "q": {"type": "string"}, "where": {"type": "array", "maxItems": 8, "description": "as query_rows' where"}})),
        "x": {"type": "string", "description": "the column whose values are the chart's x"},
        "y": {"type": "string", "description": "a number column; sum and avg need it"},
        "op": {"enum": ["count", "sum", "avg"]}}));
    source["description"] = json!("for a bar, line or pie chart of a table's rows: what to aggregate; the drawn numbers are KEAP's");
    json!({"type": "object", "additionalProperties": false, "required": ["component"], "properties": {"source": source, "component": {"oneOf": [
        branch("table", "rows the model shows: {title?, columns[] <=12, rows[][] <=50, each row as long as columns}",
            closed(&["columns", "rows"], json!({"title": title, "columns": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
                "rows": {"type": "array", "maxItems": 50, "items": {"type": "array"}}}))),
        branch("list", "items the model shows: {title?, ordered, items[{text, detail?, tone? ok|info|warn|bad, delta?}] <=50}",
            closed(&["items", "ordered"], json!({"title": title, "ordered": {"type": "boolean"},
                "items": {"type": "array", "maxItems": 50, "items": closed(&["text"], json!({
                    "text": {"type": "string", "maxLength": 500}, "detail": {"type": "string", "maxLength": 2000},
                    "tone": {"enum": ["ok", "info", "warn", "bad"]}, "delta": delta}))}}))),
        branch("record", "one thing's fields: {title?, fields[{key, value, delta?, was?}] <=40}",
            closed(&["fields"], json!({"title": title, "fields": {"type": "array", "maxItems": 40,
                "items": closed(&["key", "value"], json!({"key": {"type": "string", "maxLength": 120}, "value": {}, "delta": delta,
                    "was": {"description": "the old value of a changed field; only with delta changed"}}))}}))),
        branch("chart", "values plotted: {title?, chart bar|stacked_bar|line|area|scatter|pie, x category|number|time, \
series[{name, points[[x, number]] <=60}] <=6}; x is always a string (\"3\", \"2026-10-13\"); line, area and stacked_bar series \
share the same x in the same order; scatter needs number or time x; pie is one series of values >= 0",
            closed(&["chart", "x", "series"], json!({"title": title,
                "chart": {"enum": ["bar", "stacked_bar", "line", "area", "scatter", "pie"]},
                "x": {"enum": ["category", "number", "time"], "description": "how to read every x string"},
                "series": {"type": "array", "minItems": 1, "maxItems": 6, "items": closed(&["name", "points"], json!({
                    "name": {"type": "string", "maxLength": 120},
                    "points": {"type": "array", "maxItems": 60, "items": {"type": "array", "minItems": 2, "maxItems": 2,
                        "prefixItems": [{"type": "string", "maxLength": 120}, {"type": "number"}]}}}))}}))),
        branch("tree", "a hierarchy: {title?, nodes[{label, note?, delta?, children[]}]}, depth <=4, at most 100 nodes; \
delta added|removed|changed; a child of an added or removed parent is that too, never the other",
            closed(&["nodes"], json!({"title": title, "nodes": {"type": "array", "maxItems": 100}}))),
        branch("timeline", "a history: {title?, items[{when, title, note?, hi?, until?, lane?}] <=30}; every when a date \
YYYY-MM-DD[THH:MM:SS(Z|+HH:MM)] draws a time axis with until as a span's end (not before when) and lane as its row",
            closed(&["items"], json!({"title": title, "items": {"type": "array", "maxItems": 30, "items": closed(&["when", "title"], json!({
                "when": {"type": "string", "maxLength": 120}, "title": {"type": "string", "maxLength": 500},
                "note": {"type": "string", "maxLength": 2000}, "hi": {"type": "boolean"},
                "until": {"type": "string", "maxLength": 120}, "lane": {"type": "string", "maxLength": 40}}))}}))),
        branch("graph", "things and the links between them: {title?, nodes[{id, label, note?, tone?}] <=60, \
edges[{from, to, label?, dashed?}] <=120}; ids unique, every edge names two node ids; drawn as layered columns",
            closed(&["nodes", "edges"], json!({"title": title,
                "nodes": {"type": "array", "minItems": 1, "maxItems": 60, "items": closed(&["id", "label"], json!({
                    "id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}, "label": {"type": "string", "maxLength": 120},
                    "note": {"type": "string", "maxLength": 2000}, "tone": {"enum": ["ok", "info", "warn", "bad"]}}))},
                "edges": {"type": "array", "maxItems": 120, "items": closed(&["from", "to"], json!({
                    "from": {"type": "string"}, "to": {"type": "string"}, "label": {"type": "string", "maxLength": 120},
                    "dashed": {"type": "boolean"}}))}}))),
        branch("sequence", "who sends what to whom, in order: {title?, participants[] 2-8, steps[] <=40}; a step is a message \
{from, to, text, dashed?} (dashed for a reply), a note {note, over[1-2]} or a phase {phase}; from, to and over name participants",
            closed(&["participants", "steps"], json!({"title": title,
                "participants": {"type": "array", "minItems": 2, "maxItems": 8, "uniqueItems": true, "items": {"type": "string", "minLength": 1, "maxLength": 40}},
                "steps": {"type": "array", "minItems": 1, "maxItems": 40, "items": {"oneOf": [
                    closed(&["from", "to", "text"], json!({"from": {"type": "string"}, "to": {"type": "string"},
                        "text": {"type": "string", "maxLength": 120}, "dashed": {"type": "boolean"}})),
                    closed(&["note", "over"], json!({"note": {"type": "string", "maxLength": 200},
                        "over": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}}})),
                    closed(&["phase"], json!({"phase": {"type": "string", "maxLength": 60}}))]}}}))),
        branch("choice", "a question at a fork that changes what you do next: {question, options[{label, note?}] 2-6, suggested[], \
multi}; suggested names your pick among the options, exactly 1 unless multi; never yes or no on a write",
            closed(&["question", "options", "suggested", "multi"], json!({
                "question": {"type": "string", "maxLength": 120, "description": "at most 15 words"},
                "options": {"type": "array", "minItems": 2, "maxItems": 6, "items": closed(&["label"], json!({
                    "label": {"type": "string", "maxLength": 60}, "note": {"type": "string", "maxLength": 200}}))},
                "suggested": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string"}},
                "multi": {"type": "boolean"}})))]}}})
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
        {"type": "function", "function": {"name": "show", "description": SHOW, "parameters": show_schema()}},
        {"type": "function", "function": {"name": "red_status", "description": RED_STATUS,
        "parameters": {"type": "object", "additionalProperties": false, "properties": {}}}}])
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
            let peer = peer(&out);
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
                Ok(ToThalamus::Widget { widget, spec, trigger }) => {
                    if let Some(o) = self.ensure(&who, &mut out, &mut open) {
                        self.widget(&who, &mut out, o, &widget, &spec, trigger);
                    }
                }
                Ok(ToThalamus::FormSubmit { form, widget, values }) => match open.as_mut() {
                    Some(o) => if self.may_decide(o, &mut out, "form_submit", &form, &peer, Some(&widget)) {
                        self.form_submit(&who, &mut out, o, &form, &widget, &values, &peer)
                    },
                    None => send(&mut out, &ToShell::Refused { reason: "no form was sent on this connection".into(), widget: Some(widget) }),
                },
                Ok(ToThalamus::ChoiceReply { session, choice, picked }) => match open.as_mut() {
                    Some(o) if o.session == session => {
                        if !self.may_decide(o, &mut out, "choice_reply", &choice, &peer, None) {
                            continue;
                        }
                        if self.choice_reply(&mut out, o, &choice, &picked) {
                            self.think(&who, &mut out, o);
                        }
                        activity(&mut out, o, Phase::Idle);
                    }
                    _ => refuse(&mut out, "session is not this connection's open session"),
                },
                Ok(ToThalamus::ApprovalDecision { approval, decision, note }) => match open.as_mut() {
                    Some(o) if o.pending.contains(&approval) => {
                        if !self.may_decide(o, &mut out, "propose_row_edit", &approval, &peer, None) {
                            continue;
                        }
                        self.decide(&who, &mut out, o, &approval, decision, note, &peer);
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
asked for, never to look at a row. To show structured output call show ({}); plain text may use markdown, \
nothing else. To count per value (for a chart) call query_rows with \
group_by; to chart a table's rows pass show's `source` {{query, x, y?, op}}, so the numbers drawn are \
KEAP's and the person can pin the chart. For what is red or broken on the estate call red_status. When no tool can see what is asked, say so; never guess it. Say what you found in a line, and never \
repeat in text what a tool or show already drew. Shape -> component: count per value -> chart with show `source` (op count); \
many rows -> query_rows table; one thing -> record; steps -> list; history -> timeline; hierarchy -> tree; links between things -> graph; who sends what to whom -> sequence; \
what an action would change -> mark delta added|removed|changed on tree nodes, list items or record fields (was: the old value). \
Conclusion first, in one line. Never invent data: no numbers, no chart. Draw only when it helps: no visual for \
small talk or a one-line answer. Ask with show choice only at a fork that changes what you do next: 2-6 options, \
mark your pick as suggested; never for yes or no on a write: that is propose_row_edit's card. The answer comes back as a \
[thalamus] message, and a picked label is only a label. It is now {} UTC.", who.username, SHOW_KINDS.join(", "), now_utc());
        let (model, system) = match imprint {
            Ok((m, t)) => (Ok(m), format!("{}\n\n{iris}", t.trim_end())),
            Err(why) => (Err(why), iris),
        };
        Ok(Open { session, model, messages: vec![json!({"role": "system", "content": system})], tokens: (0, 0),
                  pending: HashSet::new(), shown: HashSet::new(), forms: HashMap::new(), choices: HashMap::new() })
    }

    /// The decider gate before a submit, a decision or a choice reply: a refused peer is told and
    /// recorded (its {pid, exe}, the reason), and nothing pending is consumed or cancelled.
    fn may_decide(&self, o: &Open, out: &mut UnixStream, tool: &str, about: &str, peer: &Value, widget: Option<&str>) -> bool {
        let Some(why) = decider_refusal(&self.deciders, peer["exe"].as_str()) else { return true };
        let _ = self.record(o, Kind::ToolResult, Some(tool), json!({"refused": why, "for": about, "peer": peer}));
        self.say(format!("refused a {tool} from {peer}: {why}"));
        send(out, &ToShell::Refused { reason: why, widget: widget.map(str::to_string) });
        false
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

    #[allow(clippy::too_many_arguments)]
    fn decide(&self, who: &Person, out: &mut UnixStream, o: &mut Open, approval: &str, d: Decision, note: Option<String>, peer: &Value) {
        o.pending.remove(approval);
        let said = if d == Decision::Approve { "approve" } else { "reject" };
        let id = match self.record(o, Kind::ApprovalDecision, Some("propose_row_edit"),
                                   json!({"approval": approval, "decision": said, "note": note, "peer": peer})) {
            Ok(id) => id,
            Err(why) => return refuse(out, &format!("the decision was not recorded, so nothing is written: {why}")),
        };
        if d == Decision::Approve {
            activity(out, o, Phase::Writing);
        }
        let mut written = None;
        let (text, result, heard) = match d {
            Decision::Reject => ("Rejected: nothing was written.".to_string(), json!({"approval": approval, "written": false}),
                                 format!("rejected: {}", note.as_deref().unwrap_or("no note"))),
            Decision::Approve => match self.committed(who, id) {
                Ok((row, table)) => {
                    written = Some((table, row.clone()));
                    (format!("Approved: row {row} written."), json!({"approval": approval, "written": true, "row": row}),
                     "approved, row written".to_string())
                }
                Err(why) => (format!("Approved, but the write failed: {why}"), json!({"approval": approval, "error": why}),
                             format!("approved, but nothing was written: {why}")),
            },
        };
        let _ = self.record(o, Kind::ToolResult, Some("propose_row_edit"), result);
        if let Some((table, row)) = written {
            changed(out, o, &table, &row);
        }
        // The model was told only "waiting"; its next turn starts from what the person did.
        o.messages.push(json!({"role": "user", "content": format!("[thalamus] approval {approval}: {heard}")}));
        send(out, &ToShell::Text { session: o.session.clone(), text });
    }

    /// The only write path. It takes a decision row id and writes exactly what that row's
    /// request showed the person; no approve row in the ledger, no POST. Returns the row's id:
    /// the one updated, or the one KEAP minted for an insert.
    pub fn commit(&self, who: &Person, decision: i64) -> Result<String, String> {
        let a = self.ledger.lock().map_err(|_| "ledger poisoned".to_string())?.approved(decision)?;
        if a.actor != format!("user:{}", who.uid()) {
            return Err("the approval belongs to another person".into());
        }
        let url = format!("{}/api/tables/{}/rows", self.keap_url.trim_end_matches('/'), enc(&a.table));
        let Some(row_id) = a.row_id.filter(|_| a.op == RowOp::Update) else {
            // KEAP mints the id; a body with one would overwrite that row (routes.ts upsert).
            let v = self.keap(who, &url, Some(&json!({"values": a.values})))?;
            return v.pointer("/data/id").and_then(Value::as_str).filter(|i| !i.is_empty()).map(str::to_string)
                .ok_or("KEAP answered the insert without a row id".into());
        };
        let (table, values, old) = (a.table, a.values, a.old);
        // The person approved old -> new; a row that moved since is not what they saw.
        let now = self.rows(who, &table)?.into_iter().find(|(id, _)| *id == row_id).map(|(_, v)| v)
            .ok_or(format!("row {row_id} is gone since the proposal; nothing written"))?;
        if let Some((k, _)) = old.iter().find(|(k, v)| now.get(*k).unwrap_or(&Value::Null) != *v) {
            return Err(format!("cell {k} of row {row_id} changed since the proposal; nothing written"));
        }
        // ponytail: a write between this re-read and the POST still lands under it; roadmap row
        // keap-conditional-row-update (an if-match on KEAP's side) closes that race.
        self.keap(who, &url, Some(&json!({"id": row_id, "values": values})))?;
        Ok(row_id)
    }

    /// commit(), and (row, table): the caller records its result, then says changed().
    fn committed(&self, who: &Person, decision: i64) -> Result<(String, String), String> {
        let row = self.commit(who, decision)?;
        let table = self.ledger.lock().map_err(|_| "ledger poisoned".to_string())?.approved(decision)?.table;
        Ok((row, table))
    }

    /// A widget form's submit: the person typed every value into fields they saw whole, under a
    /// header the model cannot write, so the submit is their decision (genui Q1). Never `decide()`,
    /// never `pending`, never the model's messages: request, decision, commit, result, all
    /// under tool form_submit, each naming the peer.
    #[allow(clippy::too_many_arguments)]
    fn form_submit(&self, who: &Person, out: &mut UnixStream, o: &mut Open, form: &str, widget: &str,
                   values: &Map<String, Value>, peer: &Value) {
        let tool = Some("form_submit");
        let refused = |out: &mut UnixStream, reason: String| send(out, &ToShell::Refused { reason, widget: Some(widget.to_string()) });
        let f = o.forms.get(widget).filter(|f| f.form == form).cloned();
        let keys: Vec<&String> = values.keys().collect();
        let used = json!({"widget": widget, "form": form, "table": f.as_ref().map(|f| &f.table), "keys": keys});
        if let Err(why) = self.record(o, Kind::ToolUse, tool, used) {
            return refused(out, format!("not recorded, so not written: {why}"));
        }
        let fail = |o: &Open, out: &mut UnixStream, why: String| {
            let _ = self.record(o, Kind::ToolResult, tool, json!({"error": why, "peer": peer}));
            refused(out, why);
        };
        let f = match f {
            Some(f) => f,
            None => return fail(o, out, format!("form {form} is not a form this session sent to widget {widget}")),
        };
        let cells = match form_cells(&f, values) {
            Ok(c) => c,
            Err(why) => return fail(o, out, why),
        };
        let approval = match mint_uuid() {
            Ok(a) => a,
            Err(e) => return fail(o, out, format!("no approval id: {e}")),
        };
        let asked = self.record(o, Kind::ApprovalRequest, tool,
                                json!({"approval": approval, "table": f.table, "op": "insert", "cells": cells, "peer": peer}))
            .and_then(|_| self.record(o, Kind::ApprovalDecision, tool,
                                      json!({"approval": approval, "decision": "approve", "note": "form submit", "peer": peer})));
        let id = match asked {
            Ok(id) => id,
            Err(why) => return fail(o, out, format!("the submit was not recorded, so nothing is written: {why}")),
        };
        match self.committed(who, id) {
            Ok((row, table)) => {
                let _ = self.record(o, Kind::ToolResult, tool, json!({"approval": approval, "written": true, "row": row, "peer": peer}));
                changed(out, o, &table, &row);
                send(out, &ToShell::FormResult { session: o.session.clone(), widget: widget.to_string(), form: form.to_string(), row });
            }
            Err(why) => fail(o, out, format!("the row was not written: {why}")),
        }
    }

    /// The person's answer to an open choice, checked against the choice serve stored, recorded,
    /// and handed to the model as data; true when the model's next turn should run. It closes the
    /// choice and nothing else: a label never mints an approval, a form, a widget or a write.
    fn choice_reply(&self, out: &mut UnixStream, o: &mut Open, choice: &str, picked: &[String]) -> bool {
        let tool = Some("choice_reply");
        if let Err(why) = self.record(o, Kind::ToolUse, tool, json!({"choice": choice, "picked": picked})) {
            refuse(out, &format!("not recorded, so not heard: {why}"));
            return false;
        }
        let checked = (|| {
            if !o.pending.is_empty() {
                return Err("an approval is waiting: decide it first".to_string());
            }
            let c = o.choices.get(choice).ok_or(format!("no open choice {choice} in this session"))?;
            if picked.is_empty() {
                return Err("pick at least one option".into());
            }
            if let Some(p) = picked.iter().enumerate().find_map(|(i, p)| picked[..i].contains(p).then_some(p)) {
                return Err(format!("{p:?} is picked twice"));
            }
            if let Some(p) = picked.iter().find(|p| !c.options.iter().any(|x| &x.label == *p)) {
                return Err(format!("{p:?} is not an option of this choice"));
            }
            if picked.len() > 1 && !c.multi {
                return Err(format!("this choice takes one pick, not {}", picked.len()));
            }
            Ok(picked.iter().collect::<HashSet<_>>() == c.suggested.iter().collect::<HashSet<_>>())
        })();
        let same = match checked {
            Ok(u) => u,
            Err(why) => {
                let _ = self.record(o, Kind::ToolResult, tool, json!({"error": why}));
                refuse(out, &why);
                return false;
            }
        };
        let result = json!({"choice": choice, "picked": picked, "untouched": same});
        if let Err(why) = self.record(o, Kind::ToolResult, tool, result) {
            refuse(out, &format!("not recorded, so Iris was not told: {why}"));
            return false;
        }
        o.choices.remove(choice);
        let quoted = |v: &[String]| v.iter().map(|l| json!(l).to_string()).collect::<Vec<_>>().join(", ");
        // Equal is not agreement, nor proof it was left alone: only the pupil preselects.
        let kept = if same { "; that is your suggestion, which the pupil preselects, so it may have been left as it was" } else { "" };
        o.messages.push(json!({"role": "user", "content": format!("[thalamus] choice {choice}: picked {}{kept}", quoted(picked))}));
        true
    }

    fn turn(&self, who: &Person, out: &mut UnixStream, o: &mut Open, text: &str) {
        if let Err(why) = &o.model {
            return refuse(out, &format!("iris has no model: {why}"));
        }
        let _ = self.record(o, Kind::Message, None, json!({"role": "person", "text": text}));
        o.messages.push(json!({"role": "user", "content": text}));
        self.think(who, out, o);
    }

    /// The model's turn over the conversation so far, tool calls and all, until it says text.
    fn think(&self, who: &Person, out: &mut UnixStream, o: &mut Open) {
        let model = match o.model.clone() {
            Ok(m) => m,
            Err(why) => return refuse(out, &format!("iris has no model: {why}")),
        };
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
                        // What a widget of this table re-runs: the arguments that drew it.
                        let pin = WidgetSpec::Rows(Value::Object(args.as_object().into_iter().flatten()
                            .filter(|(_, v)| !v.is_null()).map(|(k, v)| (k.clone(), v.clone())).collect()));
                        send(out, &ToShell::Render { session: o.session.clone(), component: Component::TableResults(t), pin: Some(pin) });
                        v
                    }),
                    // Its tool_result is written by decide(), once the person has answered.
                    "propose_row_edit" if !o.pending.is_empty() => Err("an approval is already waiting".to_string()),
                    "propose_row_edit" => self.propose_row_edit(who, &args, &o.shown).and_then(|d| self.ask(o, out, d)),
                    "show" => show(&args).and_then(|(c, source)| match source {
                        None => Ok((c, None)),
                        Some(src) => self.sourced(who, o, c, src),
                    }).and_then(|(c, pin)| opened(o, c).map(|c| (c, pin))).map(|(c, pin)| {
                        let v = serde_json::to_value(&c).ok();
                        let kind = v.as_ref().and_then(|v| v["kind"].as_str().map(str::to_string));
                        // A sourced chart: the model hears the numbers drawn, which are KEAP's.
                        let v = match (&pin, &c) {
                            (Some(_), _) => json!({"shown": kind, "points": v.map(|v| v["props"]["series"][0]["points"].clone())}),
                            (None, Component::Choice(ch)) => json!({"shown": kind, "choice": ch.id,
                                "status": "asked; the person's answer comes back as a [thalamus] message"}),
                            (None, _) => json!({"shown": kind}),
                        };
                        let _ = self.record(o, Kind::ToolResult, Some(name), v.clone());
                        send(out, &ToShell::Render { session: o.session.clone(), component: c, pin });
                        v
                    }),
                    "red_status" => self.red(who).map_err(|why| format!("{why}; the estate's red state is UNKNOWN, not zero"))
                        .map(|r| {
                            let v = serde_json::to_value(&r).unwrap_or(Value::Null);
                            let _ = self.record(o, Kind::ToolResult, Some(name), v.clone());
                            send(out, &ToShell::Render { session: o.session.clone(), component: Component::RedStatus(r), pin: None });
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
        let Matched { table, name, query, total, schema, mut hits, group, order, limit, columns } = self.matched(who, args)?;
        let matched = hits.len();
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

    /// query_rows' arguments checked against the live schema, and every row they match (after q
    /// and where; before group_by, order_by and limit, which travel along unapplied).
    fn matched<'a>(&self, who: &Person, args: &'a Value) -> Result<Matched<'a>, String> {
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
        let hits: Vec<(String, Map<String, Value>)> = all.into_iter()
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
        let query = if said.is_empty() { "all rows".to_string() } else { said.join(" · ") };
        let schema = schema.into_iter().cloned().collect();
        Ok(Matched { table, name, query, total, schema, hits, group, order, limit, columns })
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

    /// A widget form from the table's live schema, read as the person: one field per text, number,
    /// boolean, date or select column (a select of 0 or over 50 options is text), in the table's
    /// order, narrowed to `columns` when given. `__` columns are dropped; an optional column of any
    /// other kind is listed in `omitted`; a required column the form cannot fill refuses the form.
    pub fn form_from_schema(&self, who: &Person, table: &str, columns: Option<&[String]>) -> Result<Form, String> {
        let table = table_id(table);
        let info = self.keap(who, &format!("{}/api/tables/{}", self.keap_url.trim_end_matches('/'), enc(&table)), None)?;
        let title = info.pointer("/data/title").and_then(Value::as_str).filter(|t| !t.is_empty()).unwrap_or(&table).to_string();
        let schema: Vec<&Map<String, Value>> = info.pointer("/data/schema/columns").and_then(Value::as_array)
            .map(|c| c.iter().filter_map(Value::as_object)
                .filter(|c| c.get("key").and_then(Value::as_str).is_some_and(|k| !k.is_empty() && !k.starts_with("__"))).collect())
            .filter(|c: &Vec<_>| !c.is_empty()).ok_or(format!("KEAP returned no column schema for {title}"))?;
        let s = |c: &Map<String, Value>, k: &str| c.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        let keys: Vec<String> = schema.iter().map(|c| s(c, "key")).collect();
        if let Some(k) = columns.into_iter().flatten().find(|k| !keys.contains(k)) {
            return Err(format!("no column `{k}` in {title}; columns: {}", keys.join(", ")));
        }
        let (mut fields, mut omitted) = (Vec::new(), Vec::new());
        for c in schema {
            let (key, kind) = (s(c, "key"), s(c, "kind"));
            let required = c.get("required").and_then(Value::as_bool).unwrap_or(false);
            let options: Option<Vec<String>> = c.get("options").and_then(Value::as_array)
                .map(|o| o.iter().filter_map(Value::as_str).map(str::to_string).collect());
            let field = match kind.as_str() {
                "text" => Some(FieldKind::Text),
                "number" => Some(FieldKind::Number),
                "boolean" => Some(FieldKind::Bool),
                "date" => Some(FieldKind::Date),
                "select" if options.as_ref().is_some_and(|o| (1..=50).contains(&o.len())) => Some(FieldKind::Select),
                "select" => Some(FieldKind::Text),
                _ => None,
            };
            let wanted = columns.is_none_or(|cols| cols.contains(&key));
            match (field, wanted) {
                (Some(kind), true) => fields.push(FormField {
                    label: Some(s(c, "label")).filter(|l| !l.is_empty()).unwrap_or_else(|| key.clone()),
                    options: options.filter(|_| kind == FieldKind::Select),
                    key, kind, required, min: None, max: None, placeholder: None,
                }),
                // KEAP refuses a row without it, so a form that cannot fill it would only fail later.
                _ if required => return Err(format!("column {key} ({kind}) is required and has no form field")),
                (None, true) => omitted.push(Omitted { key, kind }),
                (_, false) => {}
            }
        }
        let form = mint_uuid().map_err(|e| format!("no form id: {e}"))?;
        let f = Form { form, table, title, fields, omitted };
        Component::Form(f.clone()).check()?;
        Ok(f)
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
    /// red-status.py as the operator: the F4 control and Iris's red_status tool read it the same way.
    fn red(&self, who: &Person) -> Result<RedStatus, String> {
        if !who.groups.iter().any(|g| self.tier1.contains(g)) {
            return Err("not yours to see".into());
        }
        let v = self.reader("red-status.py")?;
        let four = ["red_count", "reds", "hold_count", "holds"].map(|k| (k.to_string(), v.get(k).cloned().unwrap_or(Value::Null)));
        serde_json::from_value::<RedStatus>(Value::Object(four.into_iter().collect()))
            .map_err(|e| format!("red-status.py: unexpected shape: {e}"))
    }

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
            ControlView::RedStatus => self.red(who).map(Component::RedStatus),
        };
        match c {
            Ok(component) => {
                let _ = self.record(o, Kind::ToolResult, Some(tool), json!({"ok": true}));
                send(out, &ToShell::Render { session: o.session.clone(), component, pin: None });
            }
            Err(why) => {
                let _ = self.record(o, Kind::ToolResult, Some(tool), json!({"error": why}));
                refuse(out, &why);
            }
        }
    }

    /// A widget the person placed, run as them without the model. It never extends `shown`: the
    /// model did not see these rows. The ToolUse names the spec and why it ran, before it runs.
    fn widget(&self, who: &Person, out: &mut UnixStream, o: &mut Open, widget: &str, spec: &WidgetSpec, trigger: Trigger) {
        let (tool, mut used) = match spec {
            WidgetSpec::Rows(a) => ("widget_rows", json!({"table": a.get("table"), "kind": "rows"})),
            WidgetSpec::Chart(c) => ("widget_chart", json!({"table": c.query.table, "kind": c.chart, "op": c.op})),
            WidgetSpec::Form(f) => ("widget_form", json!({"table": f.table, "kind": "form"})),
        };
        used["widget"] = json!(widget);
        used["trigger"] = json!(trigger);
        let refused = |out: &mut UnixStream, reason: String| send(out, &ToShell::Refused { reason, widget: Some(widget.to_string()) });
        if let Err(why) = self.record(o, Kind::ToolUse, Some(tool), used) {
            return refused(out, format!("not recorded, so not run: {why}"));
        }
        // A re-run replaces what the token was: its old form id no longer submits.
        o.forms.remove(widget);
        // The check a pin met before the person could place it (wire.rs check_spec).
        let ran = check_spec(spec).and_then(|_| match spec {
            WidgetSpec::Rows(a) => self.widget_rows(who, a),
            WidgetSpec::Chart(c) => self.widget_chart(who, c).map(|c| (Component::Chart(c), json!({"ok": true}))),
            WidgetSpec::Form(_) if o.forms.len() >= MAX_FORMS =>
                Err(format!("this session holds {MAX_FORMS} forms; remove one first")),
            WidgetSpec::Form(f) => self.form_from_schema(who, &f.table, f.columns.as_deref()).map(|f| {
                o.forms.insert(widget.to_string(), f.clone());
                (Component::Form(f.clone()), json!({"form": f.form}))
            }),
        });
        match ran {
            Ok((component, result)) => {
                let _ = self.record(o, Kind::ToolResult, Some(tool), result);
                send(out, &ToShell::Widget { session: o.session.clone(), widget: widget.to_string(), component });
            }
            Err(why) => {
                let _ = self.record(o, Kind::ToolResult, Some(tool), json!({"error": why}));
                refused(out, why);
            }
        }
    }

    /// query_rows as the person, with date cells said as their UTC day (KEAP keeps epoch seconds).
    fn widget_rows(&self, who: &Person, args: &Value) -> Result<(Component, Value), String> {
        let (mut t, columns, grouped) = self.query_rows(who, args)?;
        let dates: Vec<String> = if grouped { vec![] } else {
            columns.as_array().into_iter().flatten().filter(|c| c["kind"] == "date")
                .filter_map(|c| c["key"].as_str().map(str::to_string)).collect()
        };
        for r in &mut t.rows {
            for k in &dates {
                if let Some(day) = r.cells.get(k).and_then(Value::as_f64).map(|t| iso(t.floor() as i64)[..10].to_string()) {
                    r.cells.insert(k.clone(), json!(day));
                }
            }
        }
        let ids: Vec<&str> = t.rows.iter().map(|r| r.__id.as_str()).collect();
        let result = json!({"rows": ids, "matched": t.matched, "total": t.total});
        Ok((Component::TableResults(t), result))
    }

    /// One series over the query's rows, aggregated here (aggregate()); x's column kind picks the axis.
    fn widget_chart(&self, who: &Person, c: &ChartSpec) -> Result<Chart, String> {
        let mut args = json!({"table": c.query.table});
        if let Some(q) = &c.query.q {
            args["q"] = json!(q);
        }
        if let Some(w) = &c.query.where_ {
            args["where"] = w.clone();
        }
        let m = self.matched(who, &args)?;
        let kind_of = |k: &str| {
            m.schema.iter().find(|col| col.get("key").and_then(Value::as_str) == Some(k))
                .map(|col| col.get("kind").and_then(Value::as_str).unwrap_or("").to_string())
                .ok_or_else(|| format!("no column `{k}` in {}; columns: {}", m.name,
                    m.schema.iter().filter_map(|col| col.get("key").and_then(Value::as_str)).collect::<Vec<_>>().join(", ")))
        };
        let op = text(&json!(c.op));
        let axis = match kind_of(&c.x)?.as_str() {
            "number" => Axis::Number,
            "date" => Axis::Time,
            _ => Axis::Category,
        };
        let y = match (c.op, &c.y) {
            (Op::Count, _) => None,
            (_, None) => return Err(format!("{op} needs `y`, a number column")),
            (_, Some(y)) => match kind_of(y)?.as_str() {
                "number" => Some(y.as_str()),
                k => return Err(format!("`{y}` is not a number column ({k}); {op} needs one")),
            },
        };
        let (points, cut) = aggregate(&m.hits, &c.x, axis, y, c.op);
        let name = y.map_or(op.clone(), |y| format!("{op} of {y}"));
        let title = format!("{name} by {}{}", c.x, if cut && axis == Axis::Time { " (last 60 days)" } else { "" });
        let chart = match c.chart {
            WidgetChart::Bar => ChartKind::Bar,
            WidgetChart::Line => ChartKind::Line,
            WidgetChart::Pie => ChartKind::Pie,
        };
        let chart = Chart { title: Some(title), chart, x: axis, series: vec![Series { name, points }] };
        Component::Chart(chart.clone()).check_allow_empty()?;
        Ok(chart)
    }

    /// show's chart drawn from its `source`: the aggregate a chart widget of that spec answers, run as
    /// the person and recorded like a widget run, replaces the model's series. Never extends `shown`.
    fn sourced(&self, who: &Person, o: &Open, c: Component, src: Value) -> Result<(Component, Option<WidgetSpec>), String> {
        let spec = source_spec(&c, src)?;
        let title = match c {
            Component::Chart(model) => model.title,
            _ => None,
        };
        let tool = Some("show_source");
        self.record(o, Kind::ToolUse, tool, json!({"table": spec.query.table, "kind": spec.chart, "op": spec.op}))
            .map_err(|why| format!("not recorded, so not drawn: {why}"))?;
        let pin = WidgetSpec::Chart(spec.clone());
        let drawn = check_spec(&pin).and_then(|_| self.widget_chart(who, &spec)).and_then(|mut chart| {
            chart.title = title.or(chart.title);
            let c = Component::Chart(chart);
            c.check().map_err(|e| format!("the source drew nothing to show ({e})"))?;
            Ok(c)
        });
        let _ = self.record(o, Kind::ToolResult, tool, match &drawn {
            Ok(_) => json!({"ok": true}),
            Err(why) => json!({"error": why}),
        });
        Ok((drawn?, Some(pin)))
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

/// show's `source` as the chart widget spec it pins: the component's chart kind (bar, line or pie
/// only) and the source's query, x, y and op. Err says why, for the model to hear.
pub fn source_spec(c: &Component, src: Value) -> Result<ChartSpec, String> {
    let Component::Chart(model) = c else { return Err("show's `source` is only for a chart".into()) };
    let kind = match model.chart {
        ChartKind::Bar => WidgetChart::Bar,
        ChartKind::Line => WidgetChart::Line,
        ChartKind::Pie => WidgetChart::Pie,
        k => return Err(format!("show's `source` draws a bar, line or pie chart, not {}; drop source or pick one of those",
                                text(&json!(k)))),
    };
    let mut v = src;
    if !v.is_object() {
        return Err(format!("show's `source` is an object {{query {{table, q?, where?}}, x, y?, op}}, not {}", text(&v)));
    }
    if v.get("chart").is_some() {
        return Err("show's `source` has no `chart`; the component's chart names it".into());
    }
    v["chart"] = json!(kind);
    serde_json::from_value(v).map_err(|e| format!("show's `source`: {e}; it is {{query {{table, q?, where?}}, x, y?, op count|sum|avg}}"))
}

/// A choice the model asked, with the id serve mints and stored as open; any other component as it is.
fn opened(o: &mut Open, c: Component) -> Result<Component, String> {
    let Component::Choice(mut ch) = c else { return Ok(c) };
    if o.choices.len() >= MAX_CHOICES {
        return Err(format!("this session holds {MAX_CHOICES} open choices; wait for the person's answer"));
    }
    let id = mint_uuid().map_err(|e| format!("no choice id: {e}"))?;
    ch.id = Some(id.clone());
    o.choices.insert(id, ch.clone());
    Ok(Component::Choice(ch))
}

/// The model's component and its `source`, or why not: only a SHOW_KINDS kind, closed props, within
/// its caps. It can only become a Render; an approval is minted by ask() alone.
fn show(args: &Value) -> Result<(Component, Option<Value>), String> {
    if let Some(k) = args.as_object().and_then(|a| a.keys().find(|k| *k != "component" && *k != "source")) {
        return Err(format!("show has no parameter `{k}`; it takes `component` and, for a chart, `source`; expected shape: {}",
                           expected_shape("")));
    }
    let kind = args.pointer("/component/kind").and_then(Value::as_str).unwrap_or("");
    let shape = expected_shape(kind);
    if !SHOW_KINDS.contains(&kind) {
        return Err(format!("show draws {}, not {kind:?}; expected shape: {shape}", SHOW_KINDS.join(", ")));
    }
    let bad = |e: String| format!("show {kind}: {e}; expected shape: {shape}");
    if kind == "choice" && args.pointer("/component/props/id").is_some() {
        return Err(bad("`id` is minted by the thalamus; leave it out".into()));
    }
    let c = serde_json::from_value::<Component>(args["component"].clone()).map_err(|e| bad(e.to_string()))?;
    c.check().map_err(bad)?;
    Ok((c, args.get("source").filter(|s| !s.is_null()).cloned()))
}

/// One series from matched rows: `op` of `y` per value of `x` (count counts rows; sum and avg
/// read the rows whose `y` is a number). Category: largest first, the 59 largest and "other"
/// past 60; time: the UTC day, oldest first, the last 60 days; number: ascending, the 60 smallest.
/// The bool says rows were cut (time) or folded into "other" (category).
pub fn aggregate(rows: &[(String, Map<String, Value>)], x: &str, axis: Axis, y: Option<&str>, op: Op) -> (Vec<(String, f64)>, bool) {
    let (mut groups, mut at): (Vec<(String, f64, usize)>, HashMap<String, usize>) = Default::default();
    for (_, v) in rows {
        let cell = v.get(x).unwrap_or(&Value::Null);
        let label = match axis {
            Axis::Time => match cell {
                Value::String(s) if is_date(s) => Some(s[..10].to_string()),
                c => c.as_f64().map(|t| iso(t.floor() as i64)[..10].to_string()),
            },
            Axis::Number => cell.as_f64().map(|_| text(cell)),
            Axis::Category => Some(match text(cell) {
                t if t.is_empty() => "(empty)".to_string(),
                t => t.chars().take(120).collect(),
            }),
        };
        let Some(label) = label else { continue };
        let i = *at.entry(label.clone()).or_insert_with(|| {
            groups.push((label, 0.0, 0));
            groups.len() - 1
        });
        match (op, y.and_then(|y| v.get(y)).and_then(Value::as_f64)) {
            (Op::Count, _) => groups[i].2 += 1,
            (_, Some(f)) => (groups[i].1, groups[i].2) = (groups[i].1 + f, groups[i].2 + 1),
            (_, None) => {}
        }
    }
    let value = |g: &(String, f64, usize)| match op {
        Op::Count => g.2 as f64,
        Op::Sum => g.1,
        Op::Avg if g.2 == 0 => 0.0,
        Op::Avg => g.1 / g.2 as f64,
    };
    let cut = groups.len() > 60;
    match axis {
        Axis::Category => {
            groups.sort_by(|a, b| value(b).total_cmp(&value(a)));
            if cut {
                let rest = groups.split_off(59);
                groups.push(rest.into_iter().fold(("other".into(), 0.0, 0), |o, g| (o.0, o.1 + g.1, o.2 + g.2)));
            }
        }
        Axis::Time => {
            groups.sort_by(|a, b| a.0.cmp(&b.0));
            groups.drain(..groups.len().saturating_sub(60));
        }
        Axis::Number => {
            groups.sort_by(|a, b| a.0.parse::<f64>().unwrap_or(0.0).total_cmp(&b.0.parse().unwrap_or(0.0)));
            groups.truncate(60);
        }
    }
    (groups.iter().map(|g| (g.0.clone(), value(g))).collect(), cut)
}

/// A submit's values as the cells of an insert: only the form's fields, each typed as its kind
/// says, every required one present. A date "YYYY-MM-DD" becomes KEAP's epoch seconds.
fn form_cells(f: &Form, values: &Map<String, Value>) -> Result<Vec<Value>, String> {
    if values.len() > 20 {
        return Err(format!("a submit holds at most 20 values, not {}", values.len()));
    }
    if let Some(k) = values.keys().find(|k| !f.fields.iter().any(|x| x.key == **k)) {
        return Err(format!("the form has no field `{k}`"));
    }
    let mut cells = Vec::new();
    for x in &f.fields {
        let Some(v) = values.get(&x.key) else {
            if x.required {
                return Err(format!("{} is required", x.key));
            }
            continue;
        };
        let k = &x.key;
        let new = match (x.kind, v) {
            (FieldKind::Text, Value::String(s)) if s.chars().count() <= 4000 => json!(s),
            (FieldKind::Text, Value::String(_)) => return Err(format!("{k} is at most 4000 characters")),
            (FieldKind::Number, Value::Number(n)) => {
                let n = n.as_f64().filter(|n| n.is_finite()).ok_or(format!("{k} is a number"))?;
                if x.min.is_some_and(|m| n < m) || x.max.is_some_and(|m| n > m) {
                    return Err(format!("{k} is outside its range"));
                }
                json!(n)
            }
            (FieldKind::Number, _) => return Err(format!("{k} is a number")),
            (FieldKind::Bool, Value::Bool(b)) => json!(b),
            (FieldKind::Bool, _) => return Err(format!("{k} is true or false")),
            (FieldKind::Select, Value::String(s)) if x.options.as_ref().is_some_and(|o| o.contains(s)) => json!(s),
            (FieldKind::Select, _) => return Err(format!("{k} is not one of {}", x.options.as_deref().unwrap_or_default().join(", "))),
            (FieldKind::Date, Value::String(s)) => json!(day_epoch(s).ok_or(format!("{k} is a day, YYYY-MM-DD"))?),
            (FieldKind::Date, _) => return Err(format!("{k} is a day, YYYY-MM-DD")),
            (FieldKind::Text, _) => return Err(format!("{k} is text")),
        };
        cells.push(json!({"key": k, "new": new}));
    }
    Ok(cells)
}

/// Days since 1970-01-01 of a proleptic Gregorian date (H. Hinnant), the inverse of iso().
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// "YYYY-MM-DD" as epoch seconds at its UTC midnight; None for anything else or a day that is not.
fn day_epoch(s: &str) -> Option<i64> {
    let b = s.as_bytes();
    let digits = |r: std::ops::Range<usize>| b[r.clone()].iter().all(u8::is_ascii_digit).then(|| s[r].parse::<i64>().ok()).flatten();
    if b.len() != 10 || b[4] != b'-' || b[7] != b'-' {
        return None;
    }
    let (y, m, d) = (digits(0..4)?, digits(5..7)?, digits(8..10)?);
    let t = days_from_civil(y, m, d) * 86_400;
    // A day the calendar does not have (02-30, 13-01) comes back as another day.
    (iso(t)[..10] == *s).then_some(t)
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

#[test]
fn days_from_civil_matches_iso() {
    for t in [0, -86_400, 951_782_400, 1_759_968_000, 1_791_849_600, 4_102_444_800] {
        assert_eq!(day_epoch(&iso(t)[..10]), Some(t), "{}", iso(t));
    }
    assert_eq!(day_epoch("2026-10-13"), Some(1_791_849_600));
    for bad in ["2026-02-29", "2100-02-29", "2026-13-01", "2026-00-10", "2026-10-32", "2026-1-01", "26-10-13", "2026-10-13T00:00:00Z", "abcd-ef-gh", ""] {
        assert_eq!(day_epoch(bad), None, "{bad:?} read as a day");
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
