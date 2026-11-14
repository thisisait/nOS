//! Wing's GET /api/v1/scan/state and /scan/cycles behind the Caddy seam (read set [scan]): Api\ScanPresenter
//! over ScanStateRepository::getState and getCycles. Starting a cycle and every PUT (component, config,
//! rotation, probe completion) are writes and stay PHP's.
use crate::notification_reads::json_decode;
use crate::pulse_reads::{auth, err, param, php_int, select};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

/// (status, body) for the two paths; None hands any other path back.
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    let state = match path {
        "/api/v1/scan/state" => true,
        "/api/v1/scan/cycles" => false,
        _ => return None,
    };
    Some(serve(db, state, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

/// `if (isset($row[col])) $row[col] = json_decode($row[col], true) ?? []`: NULL stays null, text that does not
/// decode (or decodes to null) is an empty list.
fn decode_col(row: &mut Value, col: &str) {
    if let Some(raw) = row[col].as_str().map(str::to_owned) {
        let v = json_decode(&raw);
        row[col] = if v.is_null() { json!([]) } else { v };
    }
}

fn serve(db: &Path, state: bool, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    // The presenter declares no $bffOperatorReads: the face-bff token is refused.
    if let Err(refused) = auth(&db, "default", &[], header)? {
        return Ok(refused);
    }
    if !state {
        // (int) ($limit ?? 10), not clamped: 0 (and "abc", and '') is an empty page.
        let limit = param(query, "limit").map_or(10, |l| php_int(&l));
        if limit < 0 {
            // ponytail: Nette throws 'Negative offset or limit.' and PHP answers its HTML 500 page; same status, a JSON body here.
            return Ok(err(500, "Negative offset or limit."));
        }
        let mut cycles = select(&db, &format!("SELECT * FROM scan_cycles ORDER BY cycle_number DESC LIMIT {limit}"), &[])?;
        cycles.iter_mut().for_each(|c| decode_col(c, "batch_components"));
        return Ok((200, json!({"cycles": cycles})));
    }
    // No config row is PHP's empty array, which encodes as a list.
    let mut config = select(&db, "SELECT * FROM scan_config WHERE id = 1", &[])?.pop().unwrap_or_else(|| json!([]));
    if config.is_object() {
        decode_col(&mut config, "next_batch");
    }
    // `$configArr['next_batch'] ?? []`: the decoded value again at the top level, [] when NULL or absent.
    let next_batch = config.get("next_batch").filter(|v| !v.is_null()).cloned().unwrap_or_else(|| json!([]));
    let latest = select(&db, "SELECT cycle_number, completed_at, started_at FROM scan_cycles ORDER BY cycle_number DESC LIMIT 1", &[])?.pop();
    let (latest_cycle, latest_cycle_at) = latest.map_or((json!(0), Value::Null), |c| {
        let at = if c["completed_at"].is_null() { &c["started_at"] } else { &c["completed_at"] };
        (c["cycle_number"].clone(), at.as_str().map_or_else(|| at.to_string(), str::to_owned).into())
    });
    let probes = select(&db, "SELECT * FROM attack_probes ORDER BY cycle_mod ASC", &[])?;
    Ok((200, json!({"config": config, "next_batch": next_batch, "latest_cycle": latest_cycle, "latest_cycle_at": latest_cycle_at, "attack_probes": probes})))
}
