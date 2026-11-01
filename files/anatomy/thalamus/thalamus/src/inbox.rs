//! The agent inbox, read: AgentQuestionRepository::listOpen and ::poll through public(), one reader for
//! the socket and the HTTP door (read set [inbox]). The caller opens wing.db read-only; an expired poll
//! writes nothing, as PHP's does not. Answer and cancel stay PHP's: relay() only carries an answer to Wing.
use nos_contract::wire::{AnswerOutcome, ToShell};
use rusqlite::types::ValueRef;
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Map, Value};

/// The socket's `questions` (v16): wing.db at NOS_INBOX_DB, else NOS_WING_DB, opened read-only.
pub fn open_questions(agent: Option<&str>) -> Result<Vec<Map<String, Value>>, String> {
    let var = |k| std::env::var(k).ok().filter(|v| !v.is_empty());
    let db = var("NOS_INBOX_DB").or_else(|| var("NOS_WING_DB")).ok_or("the inbox is UNKNOWN here: neither NOS_INBOX_DB nor NOS_WING_DB names wing.db")?;
    let read = || -> Result<Vec<Value>, Error> {
        let c = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
        c.busy_timeout(std::time::Duration::from_secs(5))?;
        list_open(&c, agent, &now())
    };
    match read() {
        Ok(rows) => Ok(rows.into_iter().filter_map(|r| match r { Value::Object(m) => Some(m), _ => None }).collect()),
        Err(Error::Sql(e)) => Err(format!("the inbox {db} does not read: {e}")),
        Err(Error::Deadline(why)) => Err(format!("{why}: whether it has passed is UNKNOWN here")),
    }
}

/// One answer carried to Wing, whose conditional UPDATE resolves it once (Api\InboxPresenter::actionAnswer),
/// with the wing-answer bearer read per act. Never retried: what Wing said is the outcome.
pub fn relay(uuid: &str, answer: &str, by: &str, wing_url: &str) -> ToShell {
    let done = |outcome, winning_answer: Option<String>, why: Option<String>| ToShell::AnswerResult { uuid: uuid.into(), outcome, winning_answer, why };
    let token = match crate::state::bearer("wing_answer_token") {
        Ok(t) => t,
        Err(why) => return done(AnswerOutcome::Refused, None, Some(why)),
    };
    let url = format!("{}/api/v1/inbox/questions/{uuid}/answer", crate::state::wing_base(wing_url));
    let body = json!({"answer": answer, "answered_by": by, "via": "medulla"});
    match crate::serve::agent(10).post(&url).header("authorization", &format!("Bearer {token}")).send_json(body) {
        Err(e) => done(AnswerOutcome::Refused, None, Some(format!("Wing did not answer at {url}: {e}"))),
        Ok(mut r) => {
            let code = r.status().as_u16();
            let v: Value = r.body_mut().read_json().unwrap_or(Value::Null);
            let said = v["error"].as_str().map(|e| format!(": {e}")).unwrap_or_default();
            match (code, v["result"].as_str()) {
                (200, _) => done(AnswerOutcome::Answered, None, None),
                (409, Some("expired")) => done(AnswerOutcome::Expired, None, None),
                (409, _) => done(AnswerOutcome::Lost, v["answer"].as_str().map(str::to_string), None),
                _ => done(AnswerOutcome::Refused, None, Some(format!("Wing refused it (HTTP {code}){said}"))),
            }
        }
    }
}

/// gmdate('Y-m-d\TH:i:s\Z'), the form PHP compares a deadline against.
pub fn now() -> String {
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64);
    crate::serve::iso(t)
}

/// What the terminal and `medulla questions|answer` print for the two v16 answers.
pub fn lines(m: &ToShell) -> Vec<String> {
    let s = |q: &Map<String, Value>, k: &str| q.get(k).and_then(Value::as_str).unwrap_or("?").to_string();
    match m {
        ToShell::Questions { items } if items.is_empty() => vec!["no agent question waits".into()],
        ToShell::Questions { items } => std::iter::once(format!("{} agent question(s) wait:", items.len()))
            .chain(items.iter().map(|q| format!("  {} {} ({}): {}{}", s(q, "uuid"), s(q, "agent_name"), s(q, "severity"), s(q, "prompt"),
                q.get("expires_at").and_then(Value::as_str).map(|e| format!(" — until {e}, then {}", s(q, "default_on_expiry"))).unwrap_or_default())))
            .collect(),
        ToShell::AnswerResult { uuid, outcome, winning_answer, why } => vec![match outcome {
            AnswerOutcome::Answered => format!("answer {uuid}: answered, recorded by Wing"),
            AnswerOutcome::Lost => format!("answer {uuid}: LOST — {} won first", winning_answer.as_deref().unwrap_or("another answer")),
            AnswerOutcome::Expired => format!("answer {uuid}: EXPIRED — the deadline passed, the agent took its default"),
            AnswerOutcome::Refused => format!("answer {uuid}: REFUSED — {}", why.as_deref().unwrap_or("Wing did not say why")),
        }],
        _ => vec![],
    }
}

/// listOpen(): status open, oldest first, at most 100, then past-deadline rows dropped.
pub fn list_open(db: &Connection, agent: Option<&str>, now: &str) -> rusqlite::Result<Vec<Value>> {
    let sql = "SELECT * FROM agent_questions WHERE status = 'open'";
    let rows = match agent {
        Some(a) => select(db, &format!("{sql} AND agent_name = ? ORDER BY created_at ASC LIMIT 100"), &[&a])?,
        None => select(db, &format!("{sql} ORDER BY created_at ASC LIMIT 100"), &[])?,
    };
    let mut out = Vec::new();
    for r in rows {
        if !past_deadline(&r, now) {
            out.push(Value::Object(r));
        }
    }
    Ok(out)
}

/// poll(): the row, or an open one past its deadline reported as expired with its declared default.
pub fn poll(db: &Connection, uuid: &str, now: &str) -> rusqlite::Result<Option<Value>> {
    let Some(mut r) = select(db, "SELECT * FROM agent_questions WHERE uuid = ?", &[&uuid])?.pop() else { return Ok(None) };
    if r.get("status").and_then(Value::as_str) == Some("open") && past_deadline(&r, now) {
        r.insert("status".into(), "expired".into());
        r.insert("answer".into(), r.get("default_on_expiry").cloned().unwrap_or(Value::Null));
        r.insert("expired_by_deadline".into(), true.into());
    }
    Ok(Some(Value::Object(r)))
}

/// isPastDeadline(): PHP's lexical compare of any non-empty string, sound or not; NULL and '' are no deadline.
fn past_deadline(r: &Map<String, Value>, now: &str) -> bool {
    matches!(r.get("expires_at"), Some(Value::String(s)) if !s.is_empty() && s.as_str() <= now)
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
