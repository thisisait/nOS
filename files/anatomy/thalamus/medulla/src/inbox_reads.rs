//! Wing's GET /api/v1/inbox/questions[/<uuid>] behind the Caddy seam (read set [inbox]): Api\InboxPresenter's
//! list and poll, read by thalamus::inbox. POST answer and cancel never reach here: the matcher is GET only.
use crate::pulse_reads::{auth, decode, err, param};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;
use thalamus::inbox;

/// (status, body) for the list or one question; None hands any other path back.
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    let uuid = match path.strip_prefix("/api/v1/inbox/questions")? {
        "" => None,
        p => Some(decode(p.strip_prefix('/').filter(|s| !s.is_empty() && !s.contains('/'))?, false)),
    };
    Some(serve(db, uuid, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, uuid: Option<String>, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    // Api\InboxPresenter $bffOperatorReads = ['questions'] (face Inbox app, 2026-11-08).
    if let Err(refused) = auth(&db, "questions", &["questions"], header)? {
        return Ok(refused);
    }
    let now = inbox::now();
    Ok(match uuid {
        Some(u) => inbox::poll(&db, &u, &now)?.map_or_else(|| err(404, "Question not found"), |q| (200, q)),
        None => {
            let agent = param(query, "agent").filter(|a| !a.is_empty());
            (200, json!({"questions": inbox::list_open(&db, agent.as_deref(), &now)?}))
        }
    })
}
