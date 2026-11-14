//! Wing's GET /api/v1/hub/systems and /hub/systems/<id> behind the Caddy seam (read set [hub]):
//! Api\HubPresenter::actionSystems over SystemRepository::list, get, stats and enrich. A GET here is public
//! in PHP (SEC-7), so no bearer is read. ?tree and ?listed are presenter code and stay PHP's, as do POST and /hub/health.
use crate::pulse_reads::{decode, err, param, select};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

/// (status, body) for the two paths; None hands back any other path and a ?tree or ?listed list.
pub fn answer(db: &Path, path: &str, query: &str) -> Option<(u16, Value)> {
    let rest = path.strip_prefix("/api/v1/hub/systems")?;
    let id = match rest.strip_prefix('/') {
        Some(id) if !id.is_empty() && !id.contains('/') => Some(decode(id, false)),
        None if rest.is_empty() => None,
        _ => return None,
    };
    // $req->getQuery('tree') is a truth test: '' and "0" still mean the plain list.
    let truthy = |k: &str| param(query, k).is_some_and(|v| !v.is_empty() && v != "0");
    if id.is_none() && (truthy("tree") || truthy("listed")) {
        return None;
    }
    Some(serve(db, id, query).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, id: Option<String>, query: &str) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    if let Some(id) = id {
        let Some(row) = select(&db, "SELECT * FROM systems WHERE id = ?", &[&id])?.pop() else {
            return Ok(err(404, "System not found"));
        };
        let mut item = enrich(&db, row)?;
        let children = select(&db, "SELECT * FROM systems WHERE parent_id = ? ORDER BY name ASC", &[&id])?;
        item["children"] = children.into_iter().map(|c| enrich(&db, c)).collect::<rusqlite::Result<Vec<_>>>()?.into();
        return Ok((200, item));
    }
    // list(): five filters under PHP's empty() ('' and "0" dropped); health only drops ''.
    let (mut wh, mut args) = (vec!["1".to_owned()], Vec::new());
    for (k, col) in [("category", "category"), ("stack", "stack"), ("priority", "priority"), ("source", "source"), ("type", "type"), ("health", "health_status")] {
        if let Some(v) = param(query, k).filter(|v| !v.is_empty() && (k == "health" || v != "0")) {
            wh.push(format!("{col} = ?"));
            args.push(v);
        }
    }
    // ponytail: an array-shaped ?stack[]= is a SQL IN in Nette and absent here; no caller sends one.
    let params: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
    let rows = select(&db, &format!("SELECT * FROM systems WHERE {} ORDER BY stack ASC, priority DESC, name ASC", wh.join(" AND ")), &params)?;
    let systems = rows.into_iter().map(|r| enrich(&db, r)).collect::<rusqlite::Result<Vec<_>>>()?;
    Ok((200, json!({"total": systems.len(), "systems": systems, "stats": stats(&db)?})))
}

/// enrich(): the row's scan state, its two derived URLs, and `url` filled from them when it is empty().
fn enrich(db: &Connection, mut item: Value) -> rusqlite::Result<Value> {
    let id = item["id"].clone();
    let key: &dyn rusqlite::ToSql = match &id {
        Value::String(s) => s,
        _ => &rusqlite::types::Null,
    };
    item["scan_state"] = select(db, "SELECT * FROM component_scan_state WHERE component_id = ?", &[key])?.pop().unwrap_or(Value::Null);
    let ip = item["port"].as_i64().filter(|p| *p > 0).map(|p| format!("http://127.0.0.1:{p}"));
    let domain = item["domain"].as_str().filter(|d| !d.is_empty() && *d != "0").map(|d| format!("https://{d}"));
    if matches!(&item["url"], Value::Null) || matches!(item["url"].as_str(), Some("" | "0")) {
        item["url"] = domain.clone().or_else(|| ip.clone()).into();
    }
    item["ip_url"] = ip.into();
    item["domain_url"] = domain.into();
    Ok(item)
}

/// SystemRepository::stats(): counts over the whole table, whatever the list was filtered by.
fn stats(db: &Connection) -> rusqlite::Result<Value> {
    let n = |sql: &str| db.query_row(sql, [], |r| r.get::<_, i64>(0));
    let total = n("SELECT COUNT(*) FROM systems WHERE category != 'stack'")?;
    let up = n("SELECT COUNT(*) FROM systems WHERE health_status = 'up' AND category != 'stack'")?;
    let down = n("SELECT COUNT(*) FROM systems WHERE health_status = 'down' AND category != 'stack'")?;
    Ok(json!({
        "total": total, "up": up, "down": down, "unknown": total - up - down,
        "stacks": n("SELECT COUNT(*) FROM systems WHERE category = 'stack'")?,
        "findings": n("SELECT CAST(COALESCE(SUM(findings_count), 0) AS INTEGER) FROM component_scan_state")?,
    }))
}
