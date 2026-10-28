//! Wing's Pulse reads behind the Caddy seam (row medulla-scheduler, increment d; ruling 2026-10-25):
//! GET /api/v1/pulse_jobs, /pulse_runs, /pulse_runs/summary, /pulse_runs/<id>, with the token lookup,
//! refusals, SQL and JSON of Api\PulsePresenter + PulseRepository; and GET /api/v1/admin/state
//! (Api\AdminPresenter's keys plus the state struct, row medulla-settings). Every write stays PHP's: wing.db
//! opens read-only, so a read here does not stamp api_tokens.last_used_at as PHP's validate() does.
use rusqlite::types::ValueRef;
use rusqlite::{Connection, OpenFlags, OptionalExtension, Row};
use serde_json::{json, Map, Value};
use std::path::Path;
use std::time::Duration;

/// BaseApiPresenter's $bffOperatorReads on PulsePresenter: a Tier-1 person reads these through face-bff.
const OPERATOR_READS: [&str; 3] = ["jobs", "runs", "runSummary"];

/// (status, body) for a path this module serves; None hands the request back (404 at the door).
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    let (action, id) = route(path)?;
    // strtotime()'s grammar is PHP's: a windowed list stays there (the Caddy matcher keeps it too).
    if action == "runs" && id.is_none() && ["since", "until"].iter().any(|k| param(query, k).is_some_and(|v| !v.is_empty())) {
        return None;
    }
    Some(serve(db, action, id, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn route(path: &str) -> Option<(&'static str, Option<String>)> {
    match path.strip_prefix("/api/v1/")? {
        "pulse_jobs" => Some(("jobs", None)),
        "pulse_runs" => Some(("runs", None)),
        "pulse_runs/summary" => Some(("runSummary", None)),
        "admin/state" => Some(("state", None)),
        p => {
            let id = p.strip_prefix("pulse_runs/").filter(|s| !s.is_empty() && !s.contains('/'))?;
            Some(("runs", Some(decode(id, false))))
        }
    }
}

fn serve(db: &Path, action: &str, id: Option<String>, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    if let Err(refused) = auth(&db, action, header)? {
        return Ok(refused);
    }
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64);
    Ok(match (action, id) {
        ("jobs", _) => (200, json!({"generated_at": crate::pulse::iso(now), "jobs": jobs(&db)?})),
        ("runs", Some(id)) => match select(&db, "SELECT * FROM pulse_runs WHERE run_id = ?", &[&id])?.pop() {
            Some(run) => (200, run),
            None => err(404, "Run not found"),
        },
        ("state", _) => (200, admin_state(&db)?),
        ("runs", None) => (200, json!({"generated_at": crate::pulse::iso(now), "runs": runs(&db, query)?})),
        _ => (200, json!({"generated_at": crate::pulse::iso(now), "window_hours": 24, "summaries": summaries(&db, now)?})),
    })
}

/// AdminPresenter::actionState's two keys (isEmergencyHaltActive, jobStateCounts), and beside them
/// the state struct every door of row medulla-settings says (thalamus::state).
fn admin_state(db: &Connection) -> rusqlite::Result<Value> {
    let s = thalamus::state::read();
    let filed = thalamus::state::halt_file().is_file();
    let n = |w: &str| db.query_row(&format!("SELECT COUNT(*) FROM pulse_jobs WHERE removed_at IS NULL{w}"), [], |r| r.get::<_, i64>(0));
    let (unpaused, halted) = (n(" AND paused = 0")?, n(" AND paused = 1 AND paused_reason LIKE 'emergency-halt:%'")?);
    let mut v = serde_json::to_value(&s).expect("the state always serializes");
    v["halt_active"] = (filed || halted > 0).into();
    v["job_counts"] = json!({
        "unpaused": if filed { 0 } else { unpaused }, "emergency_halted": if filed { unpaused } else { 0 } + halted,
        "manually_paused": n(" AND paused = 1 AND paused_reason NOT LIKE 'emergency-halt:%'")?, "total": n("")?,
    });
    Ok(v)
}

fn err(code: u16, msg: &str) -> (u16, Value) {
    (code, json!({"error": msg, "code": code}))
}

/// BaseApiPresenter::startup() for a GET: requireTokenAuth, permits, EndUser, the thalamus and face-bff doors.
pub fn auth(db: &Connection, action: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<Result<(), (u16, Value)>> {
    let Some(token) = header("authorization").and_then(|h| h.strip_prefix("Bearer ").map(str::to_owned)) else {
        return Ok(Err(err(401, "Missing or invalid Authorization header. Use: Authorization: Bearer <token>")));
    };
    let hash: String = ring::digest::digest(&ring::digest::SHA256, token.as_bytes()).as_ref().iter().map(|b| format!("{b:02x}")).collect();
    let row = db
        .query_row("SELECT name, scopes FROM api_tokens WHERE token = ? AND active = 1", [hash], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?))
        })
        .optional()?;
    let Some((name, scopes)) = row else { return Ok(Err(err(401, "Invalid or inactive API token"))) };
    // TokenRepository::permits: NULL/'' is unrestricted; a GET needs wing.read or wing.write.
    let scopes = scopes.unwrap_or_default();
    let granted: Vec<&str> = scopes.split(',').map(|s| s.trim_matches([' ', '\t', '\n', '\r', '\0', '\x0B'])).filter(|s| !s.is_empty() && *s != "0").collect();
    if !granted.is_empty() && !granted.iter().any(|s| *s == "wing.read" || *s == "wing.write") {
        return Ok(Err(err(403, "Token scope does not permit GET on the ops plane")));
    }
    if name != "face-bff" && name != "thalamus" {
        return Ok(Ok(()));
    }
    if !canonical(&header("x-nos-user-uid").unwrap_or_default()) {
        return Ok(Err(err(401, &format!("{name} request without a canonical X-Nos-User-Uid"))));
    }
    if name == "thalamus" {
        return Ok(Err(err(403, "the thalamus token speaks for a person only to start or stop an agent session and read it")));
    }
    if !OPERATOR_READS.contains(&action) {
        return Ok(Err(err(403, "the face-bff token does not reach this action")));
    }
    let groups = header("x-nos-user-groups").unwrap_or_default().to_ascii_lowercase();
    let operator = groups.split([' ', '\t', '\n', '\x0B', '\x0C', '\r', ',', '|']).any(|g| g == "nos-providers" || g == "nos-admins");
    Ok(if operator { Ok(()) } else { Err(err(403, "This estate-wide read is Tier 1 (nos-providers or nos-admins) only")) })
}

/// CanonicalUid::isCanonical: non-empty and already folded (lowercase alnum runs joined by one dash, ≤ 64).
pub fn canonical(uid: &str) -> bool {
    uid.len() <= 64 && !uid.is_empty() && uid.split('-').all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit()))
}

fn value(v: ValueRef) -> Value {
    match v {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(i) => i.into(),
        ValueRef::Real(f) => f.into(),
        ValueRef::Text(t) | ValueRef::Blob(t) => String::from_utf8_lossy(t).into(),
    }
}

fn object(r: &Row, names: &[String]) -> Map<String, Value> {
    names.iter().enumerate().map(|(i, n)| (n.clone(), value(r.get_ref(i).unwrap_or(ValueRef::Null)))).collect()
}

fn select(db: &Connection, sql: &str, params: &[&dyn rusqlite::ToSql]) -> rusqlite::Result<Vec<Value>> {
    let mut st = db.prepare(sql)?;
    let names: Vec<String> = st.column_names().into_iter().map(str::to_owned).collect();
    let mut rs = st.query(params)?;
    let mut out = Vec::new();
    while let Some(r) = rs.next()? {
        out.push(Value::Object(object(r, &names)));
    }
    Ok(out)
}

/// PHP's json_encode of an array keyed by id: `[]` when empty, else an object.
fn keyed(m: Map<String, Value>) -> Value {
    if m.is_empty() { json!([]) } else { Value::Object(m) }
}

/// listJobs() through withoutSecrets(): env_json leaves as its key names only, never a value.
fn jobs(db: &Connection) -> rusqlite::Result<Value> {
    // ponytail: a duplicate or all-digit env key differs from PHP's array_keys; no job declares one.
    let rows = select(db, "SELECT *, CASE WHEN json_valid(env_json) AND json_type(env_json) IN ('object', 'array')
                            THEN (SELECT json_group_array(key) FROM json_each(env_json)) ELSE '[]' END AS \"medulla:env_keys\"
                           FROM pulse_jobs WHERE removed_at IS NULL ORDER BY plugin_name, job_name", &[])?;
    let mut out = Map::new();
    for row in rows {
        let Value::Object(mut job) = row else { continue };
        job.remove("env_json");
        let keys = job.remove("medulla:env_keys").and_then(|k| k.as_str().and_then(|s| serde_json::from_str(s).ok()));
        job.insert("env_keys".into(), keys.unwrap_or(json!([])));
        let id = job.get("id").map(|v| v.as_str().map_or_else(|| v.to_string(), str::to_owned)).unwrap_or_default();
        out.insert(id, Value::Object(job));
    }
    Ok(keyed(out))
}

/// listRuns() without the time window: ?job_id, ?limit (1..500, default 50), ?failed=1|true.
fn runs(db: &Connection, query: &str) -> rusqlite::Result<Value> {
    // ponytail: an array-shaped ?limit[]= reads as 1 in PHP and as absent here.
    let limit = param(query, "limit").map_or(50, |l| php_int(&l)).clamp(1, 500);
    let job = param(query, "job_id").filter(|j| !j.is_empty());
    let failed = matches!(param(query, "failed").as_deref(), Some("1" | "true"));
    let mut sql = String::from("SELECT * FROM pulse_runs");
    let mut wh = Vec::new();
    if job.is_some() {
        wh.push("(job_id = ?)");
    }
    if failed {
        wh.push("(exit_code IS NOT NULL AND exit_code != 0)");
    }
    if !wh.is_empty() {
        sql += &format!(" WHERE {}", wh.join(" AND "));
    }
    sql += &format!(" ORDER BY fired_at DESC LIMIT {limit}");
    let params: Vec<&dyn rusqlite::ToSql> = job.iter().map(|j| j as &dyn rusqlite::ToSql).collect();
    Ok(Value::Array(select(db, &sql, &params)?))
}

/// PulseRepository::findingsExitCodes: a declared "ran, found something" code is not a failure.
fn findings(db: &Connection, job: &str) -> rusqlite::Result<Vec<i64>> {
    let raw: Option<String> = db.query_row("SELECT findings_exit_codes FROM pulse_jobs WHERE id = ?", [job], |r| r.get(0)).optional()?.flatten();
    let items = match raw.and_then(|s| serde_json::from_str::<Value>(&s).ok()) {
        Some(Value::Array(a)) => a,
        Some(Value::Object(o)) => o.into_iter().map(|(_, v)| v).collect(),
        _ => vec![],
    };
    Ok(items.iter().map(php_intval).filter(|c| *c != 0).collect())
}

/// runSummaries(): one entry per job that has ever run; the same three queries as PHP.
fn summaries(db: &Connection, now: i64) -> rusqlite::Result<Value> {
    let mut out = Map::new();
    let latest = "SELECT r.* FROM pulse_runs r
         JOIN (SELECT job_id, MAX(fired_at) AS f FROM pulse_runs GROUP BY job_id) m
           ON r.job_id = m.job_id AND r.fired_at = m.f
         GROUP BY r.job_id
         HAVING r.run_id = MAX(r.run_id)";
    for row in select(db, latest, &[])? {
        let int = |k: &str| row[k].as_i64().map_or(Value::Null, Value::from);
        let id = row["job_id"].as_str().map_or_else(|| row["job_id"].to_string(), str::to_owned);
        out.insert(id, json!({
            "last_run_id": row["run_id"], "last_fired_at": row["fired_at"], "last_finished_at": row["finished_at"],
            "last_exit_code": int("exit_code"), "last_duration_ms": int("duration_ms"), "last_stderr_tail": row["stderr_tail"],
            "runs_window": 0, "fails_window": 0, "consecutive_failures": 0, "window_hours": 24,
        }));
    }
    let mut st = db.prepare("SELECT job_id, exit_code, COUNT(*) AS n FROM pulse_runs WHERE fired_at >= ? AND exit_code IS NOT NULL GROUP BY job_id, exit_code")?;
    let counts: Vec<(String, i64, i64)> = st.query_map([crate::pulse::iso(now - 24 * 3600)], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?.collect::<Result<_, _>>()?;
    for (id, code, n) in counts {
        let skip = code == 0 || findings(db, &id)?.contains(&code);
        if let Some(Value::Object(s)) = out.get_mut(&id) {
            s["runs_window"] = (s["runs_window"].as_i64().unwrap_or(0) + n).into();
            if !skip {
                s["fails_window"] = (s["fails_window"].as_i64().unwrap_or(0) + n).into();
            }
        }
    }
    // Newest first until the first success; an unfinished run (NULL) breaks the streak.
    let mut st = db.prepare("SELECT job_id, exit_code, rn FROM (
           SELECT job_id, exit_code, ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY fired_at DESC) AS rn FROM pulse_runs
         ) WHERE rn <= 20 ORDER BY job_id, rn")?;
    let recent: Vec<(String, Option<i64>)> = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<Result<_, _>>()?;
    let mut closed = std::collections::HashSet::new();
    for (id, code) in recent {
        if closed.contains(&id) {
            continue;
        }
        match (code, out.get_mut(&id)) {
            (None | Some(0), _) => {
                closed.insert(id);
            }
            (Some(_), Some(Value::Object(s))) => s["consecutive_failures"] = (s["consecutive_failures"].as_i64().unwrap_or(0) + 1).into(),
            _ => {}
        }
    }
    Ok(keyed(out))
}

/// One query value, PHP's last-wins, url-decoded with '+' as a space.
pub fn param(query: &str, key: &str) -> Option<String> {
    query.split('&').filter_map(|kv| {
        let (k, v) = kv.split_once('=').unwrap_or((kv, ""));
        (decode(k, true) == key).then(|| decode(v, true))
    }).last()
}

fn decode(s: &str, plus: bool) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let hex = |i: usize| b.get(i).and_then(|c| (*c as char).to_digit(16));
    let mut i = 0;
    while i < b.len() {
        if let (b'%', Some(h), Some(l)) = (b[i], hex(i + 1), hex(i + 2)) {
            out.push((h * 16 + l) as u8);
            i += 3;
            continue;
        }
        out.push(if plus && b[i] == b'+' { b' ' } else { b[i] });
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// PHP 8's (int) "<string>": leading whitespace, then the numeric prefix, else 0.
pub fn php_int(s: &str) -> i64 {
    let s = s.trim_start_matches([' ', '\t', '\n', '\r', '\x0B', '\x0C']);
    let b = s.as_bytes();
    let mut i = usize::from(matches!(b.first(), Some(b'+' | b'-')));
    let digits = |i: &mut usize| {
        let at = *i;
        while b.get(*i).is_some_and(u8::is_ascii_digit) {
            *i += 1;
        }
        *i > at
    };
    let int = digits(&mut i);
    let mut float = false;
    if b.get(i) == Some(&b'.') {
        let mut j = i + 1;
        if digits(&mut j) || int {
            (i, float) = (j, true);
        }
    }
    if !int && !float {
        return 0;
    }
    if matches!(b.get(i), Some(b'e' | b'E')) {
        let mut j = i + 1 + usize::from(matches!(b.get(i + 1), Some(b'+' | b'-')));
        if digits(&mut j) {
            (i, float) = (j, true);
        }
    }
    if float {
        s[..i].parse::<f64>().map_or(0, |f| f as i64)
    } else {
        s[..i].parse::<i64>().unwrap_or(if b[0] == b'-' { i64::MIN } else { i64::MAX })
    }
}

/// PHP's intval() of a decoded JSON value.
fn php_intval(v: &Value) -> i64 {
    match v {
        Value::Number(n) => n.as_i64().unwrap_or_else(|| n.as_f64().map_or(0, |f| f as i64)),
        Value::String(s) => php_int(s),
        Value::Bool(b) => i64::from(*b),
        Value::Array(a) => i64::from(!a.is_empty()),
        Value::Object(o) => i64::from(!o.is_empty()),
        Value::Null => 0,
    }
}
