//! The thalamus ledger (<--data-dir>/ledger.db, from nos_data_root). Its one writer is `thalamus serve`;
//! the shell never opens it. Columns are a subset of Wing's agent_sessions and events,
//! held there by tests/anatomy/test_thalamus_ledger_fields.py. prev_hash/row_hash
//! stay NULL: the audit chain is off in slice 1, which Wing's schema allows.

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{Map, Value};
use std::path::Path;

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    agent_name      TEXT NOT NULL,
    agent_version   INTEGER NOT NULL,
    status          TEXT NOT NULL,
    trigger         TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    trace_id        TEXT NOT NULL,
    model_uri       TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    stop_reason     TEXT,
    tokens_input    INTEGER,
    tokens_output   INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    type            TEXT NOT NULL,
    task            TEXT,
    result_json     TEXT,
    source          TEXT,
    actor_id        TEXT,
    actor_action_id TEXT,
    acted_at        TEXT,
    prev_hash       TEXT,
    row_hash        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
"#;

/// The only event types the thalamus writes; each must be in event-types.yml.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    SessionStart,
    SessionEnd,
    SessionRebind,
    Message,
    ToolUse,
    ToolResult,
    ApprovalRequest,
    ApprovalDecision,
}

impl Kind {
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::SessionStart => "agent_session_start",
            Kind::SessionEnd => "agent_session_end",
            Kind::SessionRebind => "agent_session_rebind",
            Kind::Message => "agent_message",
            Kind::ToolUse => "agent_tool_use",
            Kind::ToolResult => "agent_tool_result",
            Kind::ApprovalRequest => "agent_approval_request",
            Kind::ApprovalDecision => "agent_approval_decision",
        }
    }
}

pub struct Session<'a> {
    pub uuid: &'a str,
    pub agent_name: &'a str,
    pub agent_version: i64,
    pub actor: &'a str,
    pub model_uri: &'a str,
}

/// What a write may do: add a row KEAP names, or change cells of one that exists (the card's op).
pub use nos_contract::renderers::RowOp;
use nos_contract::renderers::{ColumnAddApproval, Component, TableSchemaApproval};

/// One approved write, as the request showed it to the person.
#[derive(Debug)]
pub struct Approved {
    pub actor: String,
    pub table: String,
    pub op: RowOp,
    /// None for an insert.
    pub row_id: Option<String>,
    pub values: Map<String, Value>,
    /// Empty for an insert.
    pub old: Map<String, Value>,
    /// insert_many: the rows written after the parent (values empty for an existing one).
    pub lines: Option<ApprovedLines>,
}

/// Each line's values; `ref_key` gets the parent's id at commit.
#[derive(Debug)]
pub struct ApprovedLines {
    pub table: String,
    pub ref_key: String,
    pub rows: Vec<Map<String, Value>>,
}

pub struct Ledger {
    db: Connection,
}

impl Ledger {
    pub fn open(path: &Path) -> rusqlite::Result<Self> {
        let db = Connection::open(path)?;
        // WAL so a status reader can read while serve writes.
        db.pragma_update_and_check(None, "journal_mode", "WAL", |r| r.get::<_, String>(0))?;
        db.execute_batch(SCHEMA)?;
        Ok(Ledger { db })
    }

    /// Opens a session and writes its agent_session_start. trace_id is the uuid's 32 hex.
    pub fn start(&self, s: &Session) -> rusqlite::Result<i64> {
        let tx = self.db.unchecked_transaction()?;
        tx.execute(
            "INSERT INTO sessions (uuid, agent_name, agent_version, status, trigger, actor_id, trace_id, model_uri, started_at)
             VALUES (?1, ?2, ?3, 'running', 'shell', ?4, ?5, ?6, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            params![s.uuid, s.agent_name, s.agent_version, s.actor, s.uuid.replace('-', ""), s.model_uri],
        )?;
        let id = self.record(s.uuid, Kind::SessionStart, None, &serde_json::json!({"model_uri": s.model_uri}))?;
        tx.commit()?;
        Ok(id)
    }

    /// One event of an open session; the actor comes from the session row, never the caller.
    /// Task is Runner.php's "agent:<name>" or "agent:<name>/tool:<tool>". No open session, no row.
    pub fn record(&self, session: &str, kind: Kind, tool: Option<&str>, result: &Value) -> rusqlite::Result<i64> {
        let n = self.db.execute(
            "INSERT INTO events (ts, run_id, type, task, result_json, source, actor_id, actor_action_id, acted_at)
             SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now'), uuid, ?2, 'agent:' || agent_name || COALESCE('/tool:' || ?3, ''),
                    ?4, 'thalamus', actor_id, uuid, strftime('%Y-%m-%dT%H:%M:%fZ','now')
             FROM sessions WHERE uuid = ?1 AND ended_at IS NULL",
            params![session, kind.as_str(), tool, result.to_string()],
        )?;
        if n == 0 {
            return Err(rusqlite::Error::QueryReturnedNoRows);
        }
        Ok(self.db.last_insert_rowid())
    }

    /// What a decision row approved. Err unless `decision` is an approve row of an open session
    /// answering an earlier request in that session, and the request is a write of a sound shape:
    /// `op` insert (no row_id, no old), update (absent too: row_id and old on every cell), delete
    /// (row_id, old on every cell, every new null; values stay empty) or
    /// insert_many (a new parent, or a row_id shown with old == new, plus approved_lines), and
    /// no key empty or `__` (KEAP reads those as row sharing). Every write passes here.
    pub fn approved(&self, decision: i64) -> Result<Approved, String> {
        let (actor, req) = self.request(decision)?;
        let field = |k: &str| req.get(k).and_then(Value::as_str).map(str::to_string).ok_or(format!("request has no {k}"));
        let op = match req.get("op").map(|o| o.as_str()) {
            None | Some(Some("update")) => RowOp::Update,
            Some(Some("insert")) => RowOp::Insert,
            Some(Some("insert_many")) => RowOp::InsertMany,
            Some(Some("delete")) => RowOp::Delete,
            Some(o) => return Err(format!("request op {o:?} is neither insert, insert_many, update nor delete")),
        };
        let row_id = match op {
            RowOp::Update | RowOp::Delete => Some(field("row_id")?),
            RowOp::Insert if req.get("row_id").is_some() => return Err("an insert names no row".into()),
            RowOp::Insert => None,
            RowOp::InsertMany => req.get("row_id").map(|_| field("row_id")).transpose()?,
        };
        let lines = match (op, req.get("lines")) {
            (RowOp::InsertMany, Some(l)) => Some(approved_lines(l)?),
            (RowOp::InsertMany, None) => return Err("insert_many carries its lines".into()),
            (_, Some(_)) => return Err("only insert_many carries lines".into()),
            (_, None) => None,
        };
        // An existing parent is shown, never written: each cell old == new, and no value goes out.
        let existing = op == RowOp::InsertMany && row_id.is_some();
        let (mut values, mut old) = (Map::new(), Map::new());
        for c in req.get("cells").and_then(Value::as_array).ok_or("request has no cells")? {
            let key = c.get("key").and_then(Value::as_str).ok_or("a cell has no key")?;
            if key.is_empty() || key.starts_with("__") {
                return Err(format!("cell {key:?} cannot be written"));
            }
            let new = c.get("new").cloned().ok_or("a cell has no new value")?;
            match (op, c.get("old")) {
                (_, Some(v)) if existing && *v == new => continue,
                _ if existing => return Err("an existing parent is not changed here".into()),
                (RowOp::Update, Some(v)) => {
                    old.insert(key.to_string(), v.clone());
                }
                (RowOp::Update | RowOp::Delete, None) => return Err("a cell has no old value".into()),
                // A delete writes nothing: each old is what the person saw go, re-read before the DELETE.
                (RowOp::Delete, Some(v)) if new.is_null() => {
                    old.insert(key.to_string(), v.clone());
                    continue;
                }
                (RowOp::Delete, _) => return Err("a delete leaves every cell empty".into()),
                (_, Some(_)) => return Err("an insert has no old value".into()),
                (_, None) => {}
            }
            values.insert(key.to_string(), new);
        }
        if values.is_empty() && old.is_empty() && !existing {
            return Err("a write changes at least one cell".into());
        }
        Ok(Approved { actor, table: field("table")?, op, row_id, values, old, lines })
    }

    /// The request an approve decision answers, in an open session, and the session's actor.
    fn request(&self, decision: i64) -> Result<(String, Value), String> {
        let (actor, said, request): (String, Option<String>, String) = self
            .db
            .query_row(
                "SELECT s.actor_id, json_extract(d.result_json, '$.decision'), r.result_json
                 FROM events d JOIN sessions s ON s.uuid = d.run_id AND s.ended_at IS NULL
                 JOIN events r ON r.run_id = d.run_id AND r.type = ?3 AND r.id < d.id
                      AND json_extract(r.result_json, '$.approval') = json_extract(d.result_json, '$.approval')
                 WHERE d.id = ?1 AND d.type = ?2",
                params![decision, Kind::ApprovalDecision.as_str(), Kind::ApprovalRequest.as_str()],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .map_err(|e| format!("no approval behind event {decision}: {e}"))?;
        if said.as_deref() != Some("approve") {
            return Err(format!("event {decision} is not an approval"));
        }
        let req: Value = serde_json::from_str(&request).map_err(|e| format!("unreadable request: {e}"))?;
        Ok((actor, req))
    }

    /// What a decision approved creating: the table card itself, re-checked as the contract checks it.
    /// Err unless the request is a whole table_schema_approval (private, <=30 columns, KEAP's kinds).
    pub fn approved_table(&self, decision: i64) -> Result<(String, TableSchemaApproval), String> {
        let (actor, mut req) = self.request(decision)?;
        req.as_object_mut().map(|r| r.remove("approval"));
        let t: TableSchemaApproval = serde_json::from_value(req).map_err(|e| format!("the request is no table create: {e}"))?;
        Component::TableSchemaApproval(t.clone()).check()?;
        Ok((actor, t))
    }

    /// What a decision approved adding: the column card itself, re-checked as the contract checks it.
    pub fn approved_columns(&self, decision: i64) -> Result<(String, ColumnAddApproval), String> {
        let (actor, mut req) = self.request(decision)?;
        req.as_object_mut().map(|r| r.remove("approval"));
        let t: ColumnAddApproval = serde_json::from_value(req).map_err(|e| format!("the request is no column add: {e}"))?;
        Component::ColumnAddApproval(t.clone()).check()?;
        Ok((actor, t))
    }

    /// What a decision approved drafting: (actor, the app's name, the YAML the card showed byte for byte).
    pub fn approved_app(&self, decision: i64) -> Result<(String, String, String), String> {
        let (actor, req) = self.request(decision)?;
        let field = |k: &str| req.get(k).and_then(Value::as_str).map(str::to_string).ok_or(format!("the request is no app draft: no {k}"));
        Ok((actor, field("name")?, field("yaml")?))
    }

    /// The loop draft an approve writes: (actor, id, the YAML the card showed), as approved_app.
    pub fn approved_loop(&self, decision: i64) -> Result<(String, String, String), String> {
        let (actor, req) = self.request(decision)?;
        let field = |k: &str| req.get(k).and_then(Value::as_str).map(str::to_string).ok_or(format!("the request is no loop draft: no {k}"));
        Ok((actor, field("id")?, field("yaml")?))
    }

    /// The client a table Iris created was made for: its create's result names `working_for` (D2); None is no client.
    pub fn made_for(&self, actor: &str, table: &str) -> rusqlite::Result<Option<String>> {
        self.db.query_row(
            "SELECT json_extract(result_json, '$.working_for') FROM events WHERE type = 'agent_tool_result'
               AND task LIKE '%/tool:propose_table_create' AND actor_id = ?1 AND json_extract(result_json, '$.table') = ?2
             ORDER BY id DESC LIMIT 1",
            params![actor, table], |r| r.get::<_, Option<String>>(0),
        ).optional().map(Option::flatten)
    }

    /// The person picked another model (W5): the open session's row names the one it now uses.
    pub fn rebind(&self, session: &str, model_uri: &str) -> rusqlite::Result<()> {
        let n = self.db.execute("UPDATE sessions SET model_uri = ?2 WHERE uuid = ?1 AND ended_at IS NULL", params![session, model_uri])?;
        if n == 0 { Err(rusqlite::Error::QueryReturnedNoRows) } else { Ok(()) }
    }

    /// The person's last session, opened again when its connection closed it (connection_closed): its row
    /// runs again and a second agent_session_start says so. Only a closed one is taken, so two live
    /// connections never share a session. (uuid, model_uri, tokens so far), or None.
    pub fn resume(&self, actor: &str, agent: &str) -> rusqlite::Result<Option<(String, String, (i64, i64))>> {
        let last: Option<String> = self.db.query_row(
            "SELECT uuid FROM sessions
             WHERE id = (SELECT max(id) FROM sessions WHERE actor_id = ?1 AND agent_name = ?2) AND stop_reason = 'connection_closed'",
            params![actor, agent], |r| r.get(0),
        ).optional()?;
        last.map_or(Ok(None), |uuid| self.reopen(actor, agent, &uuid))
    }

    /// resume() of one named session of this actor (a workspace tab's, v9): closed by its connection or
    /// switched away from; a cleared one never comes back. (uuid, model_uri, tokens so far), or None.
    pub fn reopen(&self, actor: &str, agent: &str, uuid: &str) -> rusqlite::Result<Option<(String, String, (i64, i64))>> {
        let row: Option<(String, i64, i64)> = self.db.query_row(
            "SELECT model_uri, COALESCE(tokens_input, 0), COALESCE(tokens_output, 0) FROM sessions
             WHERE uuid = ?1 AND actor_id = ?2 AND agent_name = ?3 AND stop_reason IN ('connection_closed', 'switched')",
            params![uuid, actor, agent], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        ).optional()?;
        let Some((model_uri, tin, tout)) = row else { return Ok(None) };
        let uuid = uuid.to_string();
        let tx = self.db.unchecked_transaction()?;
        let n = tx.execute("UPDATE sessions SET status = 'running', ended_at = NULL, stop_reason = NULL
                            WHERE uuid = ?1 AND stop_reason IN ('connection_closed', 'switched')", params![uuid])?;
        if n == 0 {
            return Ok(None);
        }
        self.record(&uuid, Kind::SessionStart, None, &serde_json::json!({"model_uri": model_uri, "resumed": true}))?;
        tx.commit()?;
        Ok(Some((uuid, model_uri, (tin, tout))))
    }

    /// The approvals asked in `session` and never decided, oldest first: (approval, tool, request).
    pub fn open_approvals(&self, session: &str) -> rusqlite::Result<Vec<(String, String, Value)>> {
        let mut q = self.db.prepare(
            "SELECT json_extract(r.result_json, '$.approval'), COALESCE(substr(r.task, instr(r.task, '/tool:') + 6), ''), r.result_json
             FROM events r WHERE r.run_id = ?1 AND r.type = ?2 AND NOT EXISTS (SELECT 1 FROM events d
               WHERE d.run_id = r.run_id AND d.type = ?3 AND json_extract(d.result_json, '$.approval') = json_extract(r.result_json, '$.approval'))
             ORDER BY r.id")?;
        let rows = q.query_map(params![session, Kind::ApprovalRequest.as_str(), Kind::ApprovalDecision.as_str()], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
        })?;
        rows.map(|r| r.map(|(a, t, j)| (a, t, serde_json::from_str(&j).unwrap_or(Value::Null)))).collect()
    }

    /// The last `n` things the person and Iris said in `session` (agent_message person|iris), oldest first.
    pub fn messages(&self, session: &str, n: usize) -> rusqlite::Result<Vec<(String, String)>> {
        let mut q = self.db.prepare(
            "SELECT role, text FROM (SELECT id, json_extract(result_json, '$.role') AS role, json_extract(result_json, '$.text') AS text
               FROM events WHERE run_id = ?1 AND type = ?2 AND json_extract(result_json, '$.role') IN ('person', 'iris')
               AND json_extract(result_json, '$.text') IS NOT NULL ORDER BY id DESC LIMIT ?3) ORDER BY id")?;
        let rows = q.query_map(params![session, Kind::Message.as_str(), n as i64], |r| Ok((r.get(0)?, r.get(1)?)))?;
        rows.collect()
    }

    /// The choices of `session` the person answered (choice_reply's result names the choice).
    pub fn answered_choices(&self, session: &str) -> rusqlite::Result<Vec<String>> {
        let mut q = self.db.prepare(
            "SELECT json_extract(result_json, '$.choice') FROM events WHERE run_id = ?1 AND type = ?2
               AND task LIKE '%/tool:choice_reply' AND json_extract(result_json, '$.choice') IS NOT NULL")?;
        let rows = q.query_map(params![session, Kind::ToolResult.as_str()], |r| r.get(0))?;
        rows.collect()
    }

    /// The scope the person last set in `session` (working_for's result), None when never.
    pub fn last_scope(&self, session: &str) -> rusqlite::Result<Option<Value>> {
        self.db.query_row(
            "SELECT result_json -> '$.scope' FROM events WHERE run_id = ?1 AND type = ?2
               AND task LIKE '%/tool:working_for' AND json_extract(result_json, '$.error') IS NULL
               AND json_extract(result_json, '$.scope') IS NOT NULL ORDER BY id DESC LIMIT 1",
            params![session, Kind::ToolResult.as_str()], |r| r.get::<_, String>(0),
        ).optional().map(|s| s.and_then(|s| serde_json::from_str(&s).ok()))
    }

    /// Writes agent_session_end, then closes the session so nothing more lands in it.
    pub fn end(&self, session: &str, stop_reason: &str, tokens: (Option<i64>, Option<i64>)) -> rusqlite::Result<()> {
        let tx = self.db.unchecked_transaction()?;
        self.record(session, Kind::SessionEnd, None, &serde_json::json!({"stop_reason": stop_reason}))?;
        tx.execute(
            "UPDATE sessions SET status = 'terminated', ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    stop_reason = ?2, tokens_input = ?3, tokens_output = ?4 WHERE uuid = ?1",
            params![session, stop_reason, tokens.0, tokens.1],
        )?;
        tx.commit()
    }
}

/// An insert_many request's lines: 1 to 20, each an insert of at least one cell, none keyed
/// empty, `__` or the parent's own column.
fn approved_lines(l: &Value) -> Result<ApprovedLines, String> {
    let text = |k: &str| l.get(k).and_then(Value::as_str).filter(|v| !v.is_empty()).map(str::to_string).ok_or(format!("lines have no {k}"));
    let (table, ref_key) = (text("table")?, text("ref_key")?);
    if ref_key.starts_with("__") {
        return Err(format!("cell {ref_key:?} cannot be written"));
    }
    let rows = l.get("rows").and_then(Value::as_array).filter(|r| (1..=20).contains(&r.len())).ok_or("lines hold 1 to 20 rows")?;
    let rows = rows.iter().map(|r| {
        let mut values = Map::new();
        for c in r.as_array().ok_or("a line is a list of cells")? {
            let key = c.get("key").and_then(Value::as_str).ok_or("a cell has no key")?;
            if key.is_empty() || key.starts_with("__") || key == ref_key {
                return Err(format!("cell {key:?} cannot be written in a line"));
            }
            if c.get("old").is_some() {
                return Err("an insert has no old value".into());
            }
            values.insert(key.to_string(), c.get("new").cloned().ok_or("a cell has no new value")?);
        }
        if values.is_empty() { Err("a line writes at least one cell".to_string()) } else { Ok(values) }
    }).collect::<Result<_, _>>()?;
    Ok(ApprovedLines { table, ref_key, rows })
}

#[cfg(test)]
mod tests {
    use super::*;

    const UUID: &str = "0b7e6f3a-2c1d-4e5f-8a9b-1c2d3e4f5a6b";

    fn ledger(name: &str) -> (Ledger, std::path::PathBuf) {
        let p = std::env::temp_dir().join(format!("thalamus-ledger-{}-{name}.db", std::process::id()));
        let _ = std::fs::remove_file(&p);
        (Ledger::open(&p).unwrap(), p)
    }

    fn start(l: &Ledger) {
        l.start(&Session { uuid: UUID, agent_name: "iris", agent_version: 1, actor: "user:alice", model_uri: "ollama-qwen" })
            .unwrap();
    }

    #[test]
    fn events_carry_the_sessions_actor_and_task() {
        let (l, _) = ledger("carry");
        start(&l);
        l.record(UUID, Kind::ToolUse, Some("query_rows"), &serde_json::json!({"q": "x"})).unwrap();
        l.end(UUID, "end_turn", (Some(10), Some(3))).unwrap();
        let rows: Vec<(String, String, String, String, String, String)> = l
            .db
            .prepare("SELECT type, task, actor_id, actor_action_id, run_id, source FROM events ORDER BY id")
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?)))
            .unwrap()
            .map(Result::unwrap)
            .collect();
        let types: Vec<&str> = rows.iter().map(|r| r.0.as_str()).collect();
        assert_eq!(types, ["agent_session_start", "agent_tool_use", "agent_session_end"]);
        assert_eq!(rows[1].1, "agent:iris/tool:query_rows");
        assert_eq!(rows[0].1, "agent:iris");
        assert!(rows.iter().all(|r| r.2 == "user:alice" && r.3 == UUID && r.4 == UUID && r.5 == "thalamus"));
        let (status, trace): (String, String) = l
            .db
            .query_row("SELECT status, trace_id FROM sessions WHERE uuid = ?1", [UUID], |r| Ok((r.get(0)?, r.get(1)?)))
            .unwrap();
        assert_eq!(status, "terminated");
        assert_eq!(trace.len(), 32);
    }

    #[test]
    fn no_open_session_no_event() {
        let (l, _) = ledger("orphan");
        assert!(l.record(UUID, Kind::Message, None, &Value::Null).is_err());
        start(&l);
        l.end(UUID, "end_turn", (None, None)).unwrap();
        assert!(l.record(UUID, Kind::Message, None, &Value::Null).is_err());
        let n: i64 = l.db.query_row("SELECT count(*) FROM events", [], |r| r.get(0)).unwrap();
        assert_eq!(n, 2);
    }

    /// A request then its approve in the open session; the decision's row id.
    fn approve(l: &Ledger, approval: &str, req: Value) -> i64 {
        let mut req = req;
        req["approval"] = serde_json::json!(approval);
        l.record(UUID, Kind::ApprovalRequest, Some("form_submit"), &req).unwrap();
        l.record(UUID, Kind::ApprovalDecision, Some("form_submit"), &serde_json::json!({"approval": approval, "decision": "approve"}))
            .unwrap()
    }

    #[test]
    fn approved_columns_is_the_add_card_and_never_a_create() {
        let (l, _) = ledger("column-add");
        start(&l);
        let card = serde_json::json!({"table": "expenses", "title": "Expenses", "existing": [{"key": "item", "label": "Item", "kind": "text"}],
            "columns": [{"key": "paid_on", "label": "Paid on", "kind": "date"}]});
        let d = approve(&l, "c1", card.clone());
        let (actor, t) = l.approved_columns(d).unwrap();
        assert_eq!((actor.as_str(), t.table.as_str(), t.existing[0].key.as_str(), t.columns[0].key.as_str()), ("user:alice", "expenses", "item", "paid_on"));
        assert!(l.approved_table(d).is_err(), "an add card creates no table");
        let create = approve(&l, "c2", serde_json::json!({"title": "X", "visibility": "private", "columns": [{"key": "a", "label": "A", "kind": "text"}]}));
        assert!(l.approved_columns(create).is_err(), "a create card adds no column");
        let mut clash = card.clone();
        clash["columns"][0]["key"] = serde_json::json!("item");
        let mut required = card.clone();
        required["columns"][0]["required"] = serde_json::json!(true);
        for (i, bad) in [clash, required].into_iter().enumerate() {
            let d = approve(&l, &format!("b{i}"), bad);
            assert!(l.approved_columns(d).is_err(), "case {i} was approved as an add");
        }
    }

    #[test]
    fn approved_table_is_the_card_the_person_saw_and_nothing_else() {
        let (l, _) = ledger("table-create");
        start(&l);
        let card = serde_json::json!({"title": "Expenses", "visibility": "private",
            "columns": [{"key": "item", "label": "Item", "kind": "text", "required": true}]});
        let d = approve(&l, "t1", card.clone());
        let (actor, t) = l.approved_table(d).unwrap();
        assert_eq!((actor.as_str(), t.title.as_str(), t.columns[0].key.as_str(), t.columns[0].required), ("user:alice", "Expenses", "item", true));
        assert!(l.approved(d).is_err(), "a table card is no row write");
        let row = approve(&l, "t2", serde_json::json!({"table": "t", "op": "insert", "cells": [{"key": "k", "new": 1}]}));
        assert!(l.approved_table(row).is_err(), "a row card creates no table");
        let mut shared = card.clone();
        shared["visibility"] = serde_json::json!("shared");
        let mut wide = card.clone();
        wide["columns"] = serde_json::json!((0..31).map(|i| serde_json::json!({"key": format!("c{i}"), "label": "C", "kind": "text"})).collect::<Vec<_>>());
        for (i, bad) in [shared, wide].into_iter().enumerate() {
            let d = approve(&l, &format!("b{i}"), bad);
            assert!(l.approved_table(d).is_err(), "case {i} was approved as a create");
        }
        l.record(UUID, Kind::ApprovalRequest, Some("propose_table_create"), &serde_json::json!({"approval": "r1", "title": "X", "visibility": "private",
            "columns": [{"key": "item", "label": "Item", "kind": "text"}]})).unwrap();
        let no = l.record(UUID, Kind::ApprovalDecision, None, &serde_json::json!({"approval": "r1", "decision": "reject"})).unwrap();
        assert!(l.approved_table(no).is_err(), "a reject creates nothing");
    }

    #[test]
    fn approved_defaults_op_to_update() {
        let (l, _) = ledger("op-default");
        start(&l);
        let d = approve(&l, "a1", serde_json::json!({"table": "t", "row_id": "r1", "cells": [{"key": "k", "old": 1, "new": 2}]}));
        let a = l.approved(d).unwrap();
        assert_eq!((a.actor.as_str(), a.table.as_str(), a.op, a.row_id.as_deref()), ("user:alice", "t", RowOp::Update, Some("r1")));
        assert_eq!((Value::Object(a.values), Value::Object(a.old)), (serde_json::json!({"k": 2}), serde_json::json!({"k": 1})));
    }

    #[test]
    fn approved_insert_has_no_row_and_no_old() {
        let (l, _) = ledger("op-insert");
        start(&l);
        let d = approve(&l, "a1", serde_json::json!({"table": "t", "op": "insert", "cells": [{"key": "k", "new": 2}, {"key": "when", "new": 1_791_849_600}]}));
        let a = l.approved(d).unwrap();
        assert_eq!((a.op, a.row_id), (RowOp::Insert, None));
        assert_eq!(Value::Object(a.values), serde_json::json!({"k": 2, "when": 1_791_849_600}));
        assert!(a.old.is_empty());
    }

    #[test]
    fn approved_refuses_a_write_of_the_wrong_shape() {
        let (l, _) = ledger("op-shape");
        start(&l);
        for (i, (why, req)) in [
            ("an insert names a row", serde_json::json!({"table": "t", "op": "insert", "row_id": "r1", "cells": [{"key": "k", "new": 2}]})),
            ("an insert carries an old value", serde_json::json!({"table": "t", "op": "insert", "cells": [{"key": "k", "old": 1, "new": 2}]})),
            ("an insert writes a sharing key", serde_json::json!({"table": "t", "op": "insert", "cells": [{"key": "__shared_with", "new": ["x"]}]})),
            ("an update writes a sharing key", serde_json::json!({"table": "t", "row_id": "r1", "cells": [{"key": "__shared_with", "old": null, "new": ["x"]}]})),
            ("an empty key", serde_json::json!({"table": "t", "op": "insert", "cells": [{"key": "", "new": 2}]})),
            ("an unknown op", serde_json::json!({"table": "t", "op": "delete", "row_id": "r1", "cells": [{"key": "k", "old": 1, "new": 2}]})),
            ("an update without a row", serde_json::json!({"table": "t", "op": "update", "cells": [{"key": "k", "old": 1, "new": 2}]})),
            ("an update without old", serde_json::json!({"table": "t", "row_id": "r1", "cells": [{"key": "k", "new": 2}]})),
            ("an insert of no cells", serde_json::json!({"table": "t", "op": "insert", "cells": []})),
            ("an update of no cells", serde_json::json!({"table": "t", "row_id": "r1", "cells": []})),
        ].into_iter().enumerate() {
            let d = approve(&l, &format!("a{i}"), req);
            assert!(l.approved(d).is_err(), "{why} was approved as a write");
        }
    }

    #[test]
    fn approved_takes_the_card_shaped_records_serve_writes() {
        let (l, _) = ledger("op-card");
        start(&l);
        // ask()'s insert record: the card minus row_id and every old.
        let d = approve(&l, "a1", serde_json::json!({"table": "t", "title": "T", "op": "insert", "read_from": ["inbox"],
            "cells": [{"key": "k", "new": 2}]}));
        assert_eq!(l.approved(d).map(|a| a.op), Ok(RowOp::Insert));
        // An update filling an empty cell: a real null old is present, not absent.
        let d = approve(&l, "a2", serde_json::json!({"table": "t", "title": "T", "op": "update", "row_id": "r1",
            "cells": [{"key": "k", "old": null, "new": 2}]}));
        let a = l.approved(d).unwrap();
        assert_eq!(Value::Object(a.old), serde_json::json!({"k": null}));
    }

    #[test]
    fn approved_delete_keeps_every_old_and_writes_no_value() {
        let (l, _) = ledger("op-delete");
        start(&l);
        let d = approve(&l, "a1", serde_json::json!({"table": "t", "op": "delete", "row_id": "r1",
            "cells": [{"key": "k", "old": 1, "new": null}, {"key": "when", "old": 1_791_849_600, "new": null}]}));
        let a = l.approved(d).unwrap();
        assert_eq!((a.op, a.row_id.as_deref()), (RowOp::Delete, Some("r1")));
        assert!(a.values.is_empty(), "a delete writes no value");
        assert_eq!(Value::Object(a.old), serde_json::json!({"k": 1, "when": 1_791_849_600}));
        for (i, (why, req)) in [
            ("a delete without a row", serde_json::json!({"table": "t", "op": "delete", "cells": [{"key": "k", "old": 1, "new": null}]})),
            ("a delete with a new value", serde_json::json!({"table": "t", "op": "delete", "row_id": "r1", "cells": [{"key": "k", "old": 1, "new": 2}]})),
            ("a delete without old", serde_json::json!({"table": "t", "op": "delete", "row_id": "r1", "cells": [{"key": "k", "new": null}]})),
            ("a delete of no cells", serde_json::json!({"table": "t", "op": "delete", "row_id": "r1", "cells": []})),
        ].into_iter().enumerate() {
            let d = approve(&l, &format!("b{i}"), req);
            assert!(l.approved(d).is_err(), "{why} was approved as a delete");
        }
    }

    #[test]
    fn approved_takes_a_parent_and_its_lines_and_refuses_a_bad_set() {
        let (l, _) = ledger("op-many");
        start(&l);
        let lines = |rows: Value| serde_json::json!({"table": "lines", "title": "Lines", "ref_key": "card", "rows": rows});
        let one = serde_json::json!([[{"key": "item", "new": "a"}]]);
        for (i, req) in [
            serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "new": 2}], "lines": lines(one.clone())}),
            serde_json::json!({"table": "t", "op": "insert_many", "row_id": "r1", "cells": [{"key": "k", "old": 2, "new": 2}], "lines": lines(one.clone())}),
        ].into_iter().enumerate() {
            let d = approve(&l, &format!("ok{i}"), req.clone());
            assert!(l.approved(d).is_ok(), "{req} was refused: {:?}", l.approved(d));
        }
        for (i, (why, req)) in [
            ("no lines", serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "new": 2}]})),
            ("no line", serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "new": 2}], "lines": lines(serde_json::json!([]))})),
            ("an empty line", serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "new": 2}], "lines": lines(serde_json::json!([[]]))})),
            ("a line naming the parent", serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "new": 2}],
                "lines": lines(serde_json::json!([[{"key": "card", "new": "r9"}]]))})),
            ("a line with an old", serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "new": 2}],
                "lines": lines(serde_json::json!([[{"key": "item", "old": "x", "new": "a"}]]))})),
            ("a line sharing", serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "new": 2}],
                "lines": lines(serde_json::json!([[{"key": "__shared_with", "new": ["x"]}]]))})),
            ("a changed existing parent", serde_json::json!({"table": "t", "op": "insert_many", "row_id": "r1",
                "cells": [{"key": "k", "old": 1, "new": 2}], "lines": lines(one.clone())})),
            ("a new parent with an old", serde_json::json!({"table": "t", "op": "insert_many", "cells": [{"key": "k", "old": 1, "new": 2}], "lines": lines(one.clone())})),
            ("lines on an insert", serde_json::json!({"table": "t", "op": "insert", "cells": [{"key": "k", "new": 2}], "lines": lines(one.clone())})),
        ].into_iter().enumerate() {
            let d = approve(&l, &format!("bad{i}"), req);
            assert!(l.approved(d).is_err(), "{why} was approved as a write");
        }
    }

    #[test]
    fn reopening_keeps_the_rows() {
        let (l, p) = ledger("reopen");
        start(&l);
        drop(l);
        let l = Ledger::open(&p).unwrap();
        let n: i64 = l.db.query_row("SELECT count(*) FROM sessions", [], |r| r.get(0)).unwrap();
        assert_eq!(n, 1);
    }
}
