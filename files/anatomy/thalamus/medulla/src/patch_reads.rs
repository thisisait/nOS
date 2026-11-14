//! Wing's GET /api/v1/patches, /patches/<id> and /patches/history behind the Caddy seam (read set [patches]):
//! Api\PatchesPresenter::doList, doGetOne and actionHistory over PatchRepository. POST and PUT, /plan, /apply
//! and /patches/<id>/events stay PHP's.
use crate::notification_reads::json_decode;
use crate::pulse_reads::{auth, decode, err, param, php_int, select};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

enum Read {
    List,
    One(String),
    History,
}

/// (status, body) for the three paths; None hands back any other path (plan, apply, events have a third segment).
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    let rest = path.strip_prefix("/api/v1/patches")?;
    let read = match rest.strip_prefix('/') {
        None if rest.is_empty() => Read::List,
        // PHP's route order: /patches/history is its own action before /patches/<id>.
        Some("history") => Read::History,
        // `$id ? doGetOne : doList`: an id of "0" lists, as PHP's truth test does.
        Some(id) if !id.is_empty() && !id.contains('/') => Some(decode(id, false)).filter(|i| i != "0").map_or(Read::List, Read::One),
        _ => return None,
    };
    Some(serve(db, read, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, read: Read, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    // The presenter declares no $bffOperatorReads: the face-bff token is refused.
    if let Err(refused) = auth(&db, "default", &[], header)? {
        return Ok(refused);
    }
    let given = |k: &str| param(query, k).filter(|v| !v.is_empty());
    let (mut wh, mut args) = (vec!["1".to_owned()], Vec::new());
    let mut filter = |col: &str, v: Option<String>| {
        if let Some(v) = v {
            wh.push(format!("{col} = ?"));
            args.push(v);
        }
    };
    match read {
        Read::One(id) => Ok(select(&db, "SELECT * FROM patches WHERE id = ?", &[&id])?.pop().map_or_else(|| err(404, "Patch not found"), |row| (200, row))),
        Read::List => {
            // The repository's empty() drops "0" as well as ''; a limit applies only when it is above 0.
            filter("status", given("status").filter(|v| v != "0"));
            filter("component_id", given("component_id").filter(|v| v != "0"));
            let limit = given("limit").map_or(0, |l| php_int(&l));
            let tail = if limit > 0 { format!(" LIMIT {}", limit.clamp(1, 500)) } else { String::new() };
            let params: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
            let rows = select(&db, &format!("SELECT * FROM patches WHERE {} ORDER BY created_at DESC{tail}", wh.join(" AND ")), &params)?;
            Ok((200, json!({"patches": rows})))
        }
        Read::History => {
            // actionHistory: a filter counts when the parameter is not '' ("0" filters); limit 1..500, default 50.
            filter("patch_id", given("patch_id"));
            filter("component_id", given("component_id"));
            let limit = param(query, "limit").map_or(50, |l| php_int(&l)).clamp(1, 500);
            let params: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
            let mut items = select(&db, &format!("SELECT * FROM patches_applied WHERE {} ORDER BY applied_at DESC LIMIT {limit}", wh.join(" AND ")), &params)?;
            for item in &mut items {
                // `record` is added only for a non-empty raw_record_json; text that is not JSON makes it null.
                if let Some(raw) = item["raw_record_json"].as_str().map(str::to_owned).filter(|r| !r.is_empty() && r != "0") {
                    item["record"] = json_decode(&raw);
                }
            }
            Ok((200, json!({"items": items})))
        }
    }
}
