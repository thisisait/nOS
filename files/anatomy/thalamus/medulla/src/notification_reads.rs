//! Wing's GET /api/v1/notifications behind the Caddy seam (read set [notifications]): Api\NotificationsPresenter
//! over NotificationRepository::query + hydrate. Bone inserts and PHP marks read; neither reaches here.
use crate::pulse_reads::{auth, err, param, php_int, select};
use rusqlite::{Connection, OpenFlags};
use serde::de::{Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{json, Map, Value};
use std::path::Path;
use std::time::Duration;

/// NotificationsPresenter's $bffOperatorReads: the face Anatomy view reads the inbox as a Tier-1 person.
const OPERATOR_READS: [&str; 1] = ["default"];

/// (status, body) for /api/v1/notifications; None hands any other path back.
pub fn answer(db: &Path, path: &str, query: &str, header: &dyn Fn(&str) -> Option<String>) -> Option<(u16, Value)> {
    (path == "/api/v1/notifications").then(|| serve(db, query, header).unwrap_or_else(|e| err(500, &e.to_string())))
}

fn serve(db: &Path, query: &str, header: &dyn Fn(&str) -> Option<String>) -> rusqlite::Result<(u16, Value)> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    if let Err(refused) = auth(&db, "default", &OPERATOR_READS, header)? {
        return Ok(refused);
    }
    // The presenter drops '' and the repository's empty() drops "0" too; target_actor_id is only ?? 'operator'.
    let set = |k: &str| param(query, k).filter(|v| !v.is_empty());
    let mut wh = vec!["target_actor_id = ?".to_owned()];
    let mut args = vec![set("target_actor_id").unwrap_or_else(|| "operator".into())];
    if !matches!(param(query, "unread_only").as_deref(), None | Some("" | "0")) {
        wh.extend(["wing_inbox_read_at IS NULL".into(), "superseded_at IS NULL".into()]);
    }
    for (k, clause) in [("severity", "severity = ?"), ("since", "created_at >= ?"), ("actor_action_id", "actor_action_id = ?")] {
        if let Some(v) = set(k).filter(|v| v != "0") {
            wh.push(clause.into());
            args.push(v);
        }
    }
    let wh = wh.join(" AND ");
    let params: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
    // ponytail: an array-shaped ?severity[]= is a SQL IN in Nette and absent here; no caller sends one.
    let limit = param(query, "limit").map_or(100, |l| php_int(&l)).clamp(1, 500);
    let total: i64 = db.query_row(&format!("SELECT COUNT(*) FROM notifications WHERE {wh}"), &*params, |r| r.get(0))?;
    let mut items = select(&db, &format!("SELECT * FROM notifications WHERE {wh} ORDER BY id DESC LIMIT {limit}"), &params)?;
    for n in &mut items {
        for (raw, key) in [("channels_json", "channels"), ("metadata_json", "metadata")] {
            n[key] = decoded(n[raw].as_str().unwrap_or_default());
        }
    }
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_secs() as i64);
    Ok((200, json!({"generated_at": crate::pulse::iso(now), "notifications": items, "total": total})))
}

/// hydrate(): json_decode($s, true) when it yields an array, else []; PHP's arrays re-encode as json_encode would.
fn decoded(s: &str) -> Value {
    // ponytail: PHP nests to 512, serde_json to 128; a row between the two decodes there and is [] here.
    match serde_json::from_str::<Php>(s) {
        Ok(Php(v @ (Value::Array(_) | Value::Object(_)))) => v,
        _ => json!([]),
    }
}

/// One json_decode(.., true) value: an object keyed 0..n-1 in document order (or empty) is a list, and an
/// integer past PHP_INT_MAX is a float. Duplicate keys: the last value wins, at the first one's place.
struct Php(Value);

impl<'de> Deserialize<'de> for Php {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(PhpVisitor).map(Php)
    }
}

struct PhpVisitor;

impl<'de> Visitor<'de> for PhpVisitor {
    type Value = Value;
    fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str("JSON")
    }
    fn visit_unit<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_bool<E>(self, b: bool) -> Result<Value, E> {
        Ok(b.into())
    }
    fn visit_i64<E>(self, n: i64) -> Result<Value, E> {
        Ok(n.into())
    }
    fn visit_u64<E>(self, n: u64) -> Result<Value, E> {
        Ok(i64::try_from(n).map_or_else(|_| (n as f64).into(), Value::from))
    }
    fn visit_f64<E>(self, n: f64) -> Result<Value, E> {
        Ok(n.into())
    }
    fn visit_str<E>(self, s: &str) -> Result<Value, E> {
        Ok(s.into())
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Value, A::Error> {
        let mut out = Vec::new();
        while let Some(Php(v)) = a.next_element()? {
            out.push(v);
        }
        Ok(Value::Array(out))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut a: A) -> Result<Value, A::Error> {
        let mut out: Vec<(String, Value)> = Vec::new();
        while let Some((k, Php(v))) = a.next_entry::<String, Php>()? {
            match out.iter_mut().find(|(have, _)| *have == k) {
                Some(slot) => slot.1 = v,
                None => out.push((k, v)),
            }
        }
        Ok(if out.iter().enumerate().all(|(i, (k, _))| *k == i.to_string()) {
            Value::Array(out.into_iter().map(|(_, v)| v).collect())
        } else {
            Value::Object(out.into_iter().collect::<Map<_, _>>())
        })
    }
}
