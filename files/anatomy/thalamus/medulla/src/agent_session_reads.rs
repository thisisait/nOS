//! Wing's GET /api/v1/agents/<name>/sessions behind the Caddy seam (read set [agent-sessions]):
//! Api\AgentsPresenter::actionSessions over AgentSessionRepository::listRecent(100, name, scope). The POST
//! that starts a session, the one-session detail and the agent catalogue stay PHP's.
use crate::pulse_reads::{auth_scoped, decode, err, select};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

/// AgentsPresenter's $bffActions: any signed-in person through face-bff, narrowed to their own rows below Tier 1.
const BFF_ACTIONS: [&str; 1] = ["sessions"];

/// (status, body) for /api/v1/agents/<name>/sessions; None hands any other path back.
pub fn answer(db: &Path, path: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    let name = path.strip_prefix("/api/v1/agents/")?.strip_suffix("/sessions")?;
    (!name.is_empty() && !name.contains('/')).then(|| serve(db, &decode(name, false), header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, name: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    // The scope is who auth says is asking, never a query parameter: this read takes none.
    let scope = match auth_scoped(&db, "sessions", &[], &BFF_ACTIONS, header)? {
        Ok(scope) => scope,
        Err(refused) => return Ok(refused),
    };
    let rows = match &scope {
        Some(actor) => select(&db, "SELECT * FROM agent_sessions WHERE agent_name = ? AND actor_id = ? ORDER BY id DESC LIMIT 100", &[&name, actor])?,
        None => select(&db, "SELECT * FROM agent_sessions WHERE agent_name = ? ORDER BY id DESC LIMIT 100", &[&name])?,
    };
    Ok((200, json!({"total": rows.len(), "data": rows})))
}
