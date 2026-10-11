//! The closed component vocabulary the shell renders. Spec:
//! files/anatomy/contracts/thalamus-shell.yml §2. Props are closed: an
//! unknown field is refused, so a producer cannot smuggle a new shape past it.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "props", rename_all = "snake_case", deny_unknown_fields)]
pub enum Component {
    TableResults(TableResults),
    RowDiffApproval(RowDiffApproval),
    InboxList(InboxList),
    ApprovalsList(ApprovalsList),
    RedStatus(RedStatus),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableResults {
    pub table: String,
    pub columns: Vec<String>,
    pub rows: Vec<Row>,
    pub projected: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Row {
    pub __id: String,
    pub cells: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RowDiffApproval {
    pub table: String,
    pub row_id: String,
    pub cells: Vec<CellChange>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellChange {
    pub key: String,
    pub old: Value,
    pub new: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InboxList {
    pub items: Vec<InboxItem>,
    /// Sources the person may not read ("promotions: not yours to moderate"), never shown as empty.
    pub refused: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InboxItem {
    pub id: String,
    pub title: String,
    pub source: String,
    pub created_at: String,
}

/// tools/awaiting-operator.py --json, `items` and `unknown`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ApprovalsList {
    pub items: Vec<ApprovalItem>,
    pub unknown: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ApprovalItem {
    pub kind: String,
    pub severity: String,
    pub age: String,
    pub what: String,
    #[serde(rename = "where")]
    pub where_: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

/// tools/red-status.py --json, the four summary fields.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RedStatus {
    pub red_count: usize,
    pub reds: Vec<String>,
    pub hold_count: usize,
    pub holds: Vec<String>,
}
