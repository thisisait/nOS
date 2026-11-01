//! The agent inbox, read: AgentQuestionRepository::listOpen and ::poll through public(), one reader for
//! the socket and the HTTP door (read set [inbox]). The caller opens wing.db read-only; an expired poll
//! writes nothing, as PHP's does not. Answer and cancel stay PHP's.
use rusqlite::types::ValueRef;
use rusqlite::Connection;
use serde_json::{Map, Value};

#[derive(Debug)]
pub enum Error {
    Sql(rusqlite::Error),
    /// An expires_at not in the one form ask() writes: whether it passed is UNKNOWN here, never guessed.
    Deadline(String),
}

impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        Error::Sql(e)
    }
}

/// gmdate('Y-m-d\TH:i:s\Z'), the form PHP compares a deadline against.
pub fn now() -> String {
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64);
    crate::serve::iso(t)
}

/// listOpen(): status open, oldest first, at most 100, then past-deadline rows dropped.
pub fn list_open(db: &Connection, agent: Option<&str>, now: &str) -> Result<Vec<Value>, Error> {
    let sql = "SELECT * FROM agent_questions WHERE status = 'open'";
    let rows = match agent {
        Some(a) => select(db, &format!("{sql} AND agent_name = ? ORDER BY created_at ASC LIMIT 100"), &[&a])?,
        None => select(db, &format!("{sql} ORDER BY created_at ASC LIMIT 100"), &[])?,
    };
    let mut out = Vec::new();
    for r in rows {
        if !past_deadline(&r, now)? {
            out.push(Value::Object(r));
        }
    }
    Ok(out)
}

/// poll(): the row, or an open one past its deadline reported as expired with its declared default.
pub fn poll(db: &Connection, uuid: &str, now: &str) -> Result<Option<Value>, Error> {
    let Some(mut r) = select(db, "SELECT * FROM agent_questions WHERE uuid = ?", &[&uuid])?.pop() else { return Ok(None) };
    if r.get("status").and_then(Value::as_str) == Some("open") && past_deadline(&r, now)? {
        r.insert("status".into(), "expired".into());
        r.insert("answer".into(), r.get("default_on_expiry").cloned().unwrap_or(Value::Null));
        r.insert("expired_by_deadline".into(), true.into());
    }
    Ok(Some(Value::Object(r)))
}

/// isPastDeadline(): PHP's string compare, sound only for YYYY-MM-DDTHH:MM:SSZ; NULL and '' are no deadline.
fn past_deadline(r: &Map<String, Value>, now: &str) -> Result<bool, Error> {
    match r.get("expires_at") {
        None | Some(Value::Null) => Ok(false),
        Some(Value::String(s)) if s.is_empty() => Ok(false),
        Some(Value::String(s)) if iso_z(s) => Ok(s.as_str() <= now),
        Some(v) => Err(Error::Deadline(format!("expires_at {v} of question {} is not YYYY-MM-DDTHH:MM:SSZ", r.get("uuid").unwrap_or(&Value::Null)))),
    }
}

fn iso_z(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 20 && b.iter().enumerate().all(|(i, c)| match i {
        4 | 7 => *c == b'-',
        10 => *c == b'T',
        13 | 16 => *c == b':',
        19 => *c == b'Z',
        _ => c.is_ascii_digit(),
    })
}

/// Rows as PHP's toArray() hands them, minus reply_token_sha (public()).
fn select(db: &Connection, sql: &str, params: &[&dyn rusqlite::ToSql]) -> rusqlite::Result<Vec<Map<String, Value>>> {
    let mut st = db.prepare(sql)?;
    let names: Vec<String> = st.column_names().into_iter().map(str::to_owned).collect();
    let mut rs = st.query(params)?;
    let mut out = Vec::new();
    while let Some(r) = rs.next()? {
        let mut row = Map::new();
        for (i, n) in names.iter().enumerate().filter(|(_, n)| *n != "reply_token_sha") {
            row.insert(n.clone(), match r.get_ref(i)? {
                ValueRef::Null => Value::Null,
                ValueRef::Integer(v) => v.into(),
                ValueRef::Real(v) => v.into(),
                ValueRef::Text(t) | ValueRef::Blob(t) => String::from_utf8_lossy(t).into(),
            });
        }
        out.push(row);
    }
    Ok(out)
}
