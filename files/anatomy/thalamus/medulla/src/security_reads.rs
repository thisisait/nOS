//! Wing's GET /api/v1/advisories[/<id>] and /gitleaks_findings[/<id>] behind the Caddy seam (read set
//! [security]): Api\AdvisoriesPresenter over AdvisoryRepository::list and get, Api\GitleaksPresenter over
//! GitleaksRepository::listFindings and getOne. Both ingest POSTs and /resolve are writes and stay PHP's.
use crate::pulse_reads::{auth, decode, err, keyed, param, php_int, select};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

/// (status, body) for the four paths; None hands back any other path, /resolve and an advisory id the seam
/// does not send (not a positive canonical int: Nette's ?int refuses those and 0 lists, both PHP's).
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    let (advisories, rest) = match path.strip_prefix("/api/v1/advisories") {
        Some(rest) => (true, rest),
        None => (false, path.strip_prefix("/api/v1/gitleaks_findings")?),
    };
    let positive_int = |i: &str| (1..=18).contains(&i.len()) && !i.starts_with('0') && i.bytes().all(|b| b.is_ascii_digit());
    let id = match rest.strip_prefix('/') {
        None if rest.is_empty() => None,
        Some(id) if advisories && positive_int(id) => Some(id.to_owned()),
        Some(id) if !advisories && !id.is_empty() && !id.contains('/') => Some(decode(id, false)),
        _ => return None,
    };
    Some(serve(db, advisories, id, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, advisories: bool, id: Option<String>, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    // Neither presenter declares $bffOperatorReads: the face-bff token reaches none of the four.
    if let Err(refused) = auth(&db, "default", &[], header)? {
        return Ok(refused);
    }
    if let Some(id) = id {
        let (table, missing) = if advisories { ("advisories", "Advisory not found") } else { ("gitleaks_findings", "Finding not found") };
        return Ok(select(&db, &format!("SELECT * FROM {table} WHERE id = ?"), &[&id])?.pop().map_or_else(|| err(404, missing), |row| (200, row)));
    }
    if advisories {
        // doList: array_filter() drops '' and "0", so ?limit=0 is the default 20; (int) is not clamped.
        let set = |v: &String| !v.is_empty() && v != "0";
        let date = param(query, "date").filter(set);
        let limit = param(query, "limit").filter(set).map_or(20, |l| php_int(&l));
        if limit < 0 {
            // ponytail: Nette throws 'Negative offset or limit.' and PHP answers its HTML 500 page; same status, a JSON body here.
            return Ok(err(500, "Negative offset or limit."));
        }
        // The list never carries full_text: the column list is the repository's.
        let cols = "id, filename, title, date, has_critical, has_pentest, scan_cycle, created_at";
        let rows = match &date {
            Some(d) => select(&db, &format!("SELECT {cols} FROM advisories WHERE date = ? ORDER BY date DESC, id DESC LIMIT {limit}"), &[d])?,
            None => select(&db, &format!("SELECT {cols} FROM advisories ORDER BY date DESC, id DESC LIMIT {limit}"), &[])?,
        };
        return Ok((200, json!({"total": rows.len(), "advisories": rows})));
    }
    // listFindings: a filter counts when the parameter is present and not '' ("0" filters); open_only is a truth test.
    let (mut wh, mut args) = (vec!["1".to_owned()], Vec::new());
    for col in ["rule_id", "severity", "scan_id"] {
        if let Some(v) = param(query, col).filter(|v| !v.is_empty()) {
            wh.push(format!("{col} = ?"));
            args.push(v);
        }
    }
    if param(query, "open_only").is_some_and(|v| !v.is_empty() && v != "0") {
        wh.push("resolved_at IS NULL".into());
    }
    let params: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
    let limit = param(query, "limit").map_or(200, |l| php_int(&l)).clamp(1, 500);
    let rows = select(&db, &format!("SELECT * FROM gitleaks_findings WHERE {} ORDER BY created_at DESC LIMIT {limit}", wh.join(" AND ")), &params)?;
    // iterator_to_array() keeps Nette's primary-key keys: an object keyed by id, `[]` when empty.
    // ponytail: members leave key-sorted, PHP's in created_at order; an all-digit id is an int key in PHP. Ids are UUIDs and the one reader counts.
    let findings = rows.into_iter().map(|f| (f["id"].as_str().unwrap_or_default().to_owned(), f)).collect();
    let now = time::OffsetDateTime::now_utc().unix_timestamp();
    Ok((200, json!({"generated_at": crate::pulse::iso(now), "findings": keyed(findings)})))
}
