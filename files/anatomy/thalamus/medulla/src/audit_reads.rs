//! Wing's GET /api/v1/audit/verify behind the Caddy seam (read set [audit]): Api\AuditPresenter's cached
//! verdict from audit_chain_meta. The medulla never holds WING_EVENTS_HMAC_SECRET; the role renders
//! MEDULLA_AUDIT_CHAIN=on|off from the value Wing gets, and without it the answer is 503, never 'off'.
use crate::pulse_reads::{auth, err};
use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde_json::{json, Value};
use std::path::Path;
use std::time::Duration;

/// (status, body) for /api/v1/audit/verify; None hands any other path back.
pub fn answer(db: &Path, path: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    (path == "/api/v1/audit/verify").then(|| serve(db, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    // Api\AuditPresenter $bffOperatorReads = ['verify'] (face Anatomy Wing view, 2026-11-08).
    if let Err(refused) = auth(&db, "verify", &["verify"], header)? {
        return Ok(refused);
    }
    Ok(match std::env::var("MEDULLA_AUDIT_CHAIN").as_deref() {
        Ok("off") => (200, json!({
            "chain": "off", "ok": true, "checked": 0,
            "note": "WING_EVENTS_HMAC_SECRET not set — tamper-evident chain disabled",
        })),
        Ok("on") => {
            // AuditChainRepository::verdict(): a row's (string) v, so NULL reads as ''.
            let meta = |k: &str| db.query_row("SELECT CAST(v AS TEXT) FROM audit_chain_meta WHERE k = ?", [k], |r| r.get::<_, Option<String>>(0))
                .optional().map(|v| v.map(Option::unwrap_or_default));
            let ok = meta("last_verify_ok")?;
            let at = if ok.is_some() { meta("last_verify_at")? } else { None };
            (200, json!({
                "chain": "on", "known": ok.is_some(), "ok": ok.as_deref().map(|v| v == "1"), "verified_at": at,
                "note": if ok.is_some() { Value::Null } else { "no verdict cached yet — the verify Pulse job has not run".into() },
            }))
        }
        _ => err(503, "MEDULLA_AUDIT_CHAIN is not rendered: whether the audit chain is on is UNKNOWN here"),
    })
}
