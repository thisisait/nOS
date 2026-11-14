//! Wing's GET /api/v1/remediation[/<id>] behind the Caddy seam (read set [remediation]):
//! Api\RemediationPresenter::doList and doGet over RemediationRepository::list and get. The scanner's POST and
//! PUT, bulk-status and next-id (it allocates) stay PHP's.
use crate::pulse_reads::{auth, decode, err, param, php_int, select};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

/// (status, body) for the two paths; None hands back any other path, bulk-status and next-id.
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    let rest = path.strip_prefix("/api/v1/remediation")?;
    let id = match rest.strip_prefix('/') {
        None if rest.is_empty() => None,
        Some("bulk-status" | "next-id") => return None,
        // `$id ? doGet : doList`: an id of "0" lists, as PHP's truth test does.
        Some(id) if !id.is_empty() && !id.contains('/') => Some(decode(id, false)).filter(|i| i != "0"),
        _ => return None,
    };
    Some(serve(db, id, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, id: Option<String>, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    // The presenter declares no $bffOperatorReads: the face-bff token is refused.
    if let Err(refused) = auth(&db, "default", &[], header)? {
        return Ok(refused);
    }
    if let Some(id) = id {
        return Ok(select(&db, "SELECT * FROM remediation_items WHERE id = ?", &[&id])?.pop().map_or_else(|| err(404, "Remediation item not found"), |row| (200, row)));
    }
    // doList: array_filter() and the repository's empty() both drop '' and "0", the limit included.
    let set = |v: &String| !v.is_empty() && v != "0";
    let (mut wh, mut args) = (vec!["1".to_owned()], Vec::new());
    for (k, col) in [("status", "status"), ("severity", "severity"), ("component", "component_id")] {
        if let Some(v) = param(query, k).filter(set) {
            wh.push(format!("{col} = ?"));
            args.push(v);
        }
    }
    let wh = wh.join(" AND ");
    let params: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
    let limit = param(query, "limit").filter(set).map_or(100, |l| php_int(&l));
    if limit < 0 {
        // ponytail: Nette throws 'Negative offset or limit.' and PHP answers its HTML 500 page; same status, a JSON body here.
        return Ok(err(500, "Negative offset or limit."));
    }
    let total: i64 = db.query_row(&format!("SELECT COUNT(*) FROM remediation_items WHERE {wh}"), &*params, |r| r.get(0))?;
    let items = select(&db, &format!(
        "SELECT * FROM remediation_items WHERE {wh} ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 \
         WHEN 'MEDIUM' THEN 3 WHEN 'LOW' THEN 4 END, created_at DESC LIMIT {limit}"), &params)?;
    Ok((200, json!({"items": items, "total": total})))
}
