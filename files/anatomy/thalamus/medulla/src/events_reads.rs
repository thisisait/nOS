//! Wing's GET /api/v1/events behind the Caddy seam (read set [events]): Api\EventsPresenter::listEvents over
//! EventRepository::query. The HMAC POST is a write and stays PHP's; row_hash and prev_hash leave as stored.
use crate::notification_reads::json_decode;
use crate::pulse_reads::{auth, err, param, php_int, select};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

/// EventsPresenter's $bffOperatorReads: the face Anatomy view reads the spine as a Tier-1 person.
const OPERATOR_READS: [&str; 1] = ["default"];

/// listEvents' filters, each its own column. patch_id is in the repository and never passed by the presenter.
const FILTERS: [(&str, &str); 9] = [
    ("run_id", "run_id = ?"), ("type", "type = ?"), ("since", "ts >= ?"), ("migration_id", "migration_id = ?"),
    ("upgrade_id", "upgrade_id = ?"), ("coexist_svc", "coexist_svc = ?"), ("source", "source = ?"),
    ("actor_id", "actor_id = ?"), ("actor_action_id", "actor_action_id = ?"),
];

/// (status, body) for /api/v1/events; None hands any other path back.
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    (path == "/api/v1/events").then(|| serve(db, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    if let Err(refused) = auth(&db, "default", &OPERATOR_READS, header)? {
        return Ok(refused);
    }
    // PHP's empty(): array_filter() and the repository both drop '' and "0".
    let set = |v: &String| !v.is_empty() && v != "0";
    let (mut wh, mut args) = (vec!["1".to_owned()], Vec::new());
    for (k, clause) in FILTERS {
        if let Some(v) = param(query, k).filter(set) {
            wh.push(clause.into());
            args.push(v);
        }
    }
    let wh = wh.join(" AND ");
    let params: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
    // ponytail: an array-shaped ?type[]= is a SQL IN in Nette and absent here; no caller sends one.
    let limit = param(query, "limit").map_or(100, |l| php_int(&l)).clamp(1, 500);
    let total: i64 = db.query_row(&format!("SELECT COUNT(*) FROM events WHERE {wh}"), &*params, |r| r.get(0))?;
    let mut items = select(&db, &format!("SELECT * FROM events WHERE {wh} ORDER BY id DESC LIMIT {limit}"), &params)?;
    for e in &mut items {
        // An empty result_json adds no key; text that is not JSON adds `result: null`, as json_decode does.
        if let Some(raw) = e["result_json"].as_str().map(str::to_owned).filter(set) {
            e["result"] = json_decode(&raw);
        }
    }
    Ok((200, json!({"items": items, "total": total})))
}
