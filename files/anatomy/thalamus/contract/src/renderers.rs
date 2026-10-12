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
    Markdown(Markdown),
    Table(Table),
    List(List),
    Record(Record),
    Chart(Chart),
}

/// Model text as markdown; every consumer draws it as text nodes, never as HTML.
pub const MARKDOWN_MAX: usize = 8000;

/// A value as the shells draw it: a string is itself, anything else JSON (pretty when nested).
pub fn value_text(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        Value::Array(_) | Value::Object(_) => serde_json::to_string_pretty(v).unwrap_or_default(),
        v => v.to_string(),
    }
}

fn cap(what: &str, s: &str, max: usize) -> Result<(), String> {
    if s.chars().count() > max { Err(format!("{what} is over {max} chars")) } else { Ok(()) }
}

fn most(what: &str, n: usize, max: usize) -> Result<(), String> {
    if n > max { Err(format!("{what}: {n}, at most {max}")) } else { Ok(()) }
}

/// Titles, column names and record keys.
const NAME_MAX: usize = 120;

impl Component {
    /// The caps serde cannot say; check_shell refuses a component over them.
    pub fn check(&self) -> Result<(), String> {
        let title = |t: &Option<String>| t.as_deref().map_or(Ok(()), |t| cap("title", t, NAME_MAX));
        match self {
            Component::Markdown(m) => cap("markdown text", &m.text, MARKDOWN_MAX),
            Component::Table(t) => {
                title(&t.title)?;
                most("table columns", t.columns.len(), 12)?;
                most("table rows", t.rows.len(), 50)?;
                t.columns.iter().try_for_each(|c| cap("a column name", c, NAME_MAX))?;
                for (i, r) in t.rows.iter().enumerate() {
                    if r.len() != t.columns.len() {
                        return Err(format!("table row {} has {} cells, not {}", i + 1, r.len(), t.columns.len()));
                    }
                    r.iter().try_for_each(|v| cap("a table cell", &value_text(v), 2000))?;
                }
                Ok(())
            }
            Component::List(l) => {
                title(&l.title)?;
                most("list items", l.items.len(), 50)?;
                l.items.iter().try_for_each(|x| {
                    cap("a list item's text", &x.text, 500)?;
                    x.detail.as_deref().map_or(Ok(()), |d| cap("a list item's detail", d, 2000))
                })
            }
            Component::Record(r) => {
                title(&r.title)?;
                most("record fields", r.fields.len(), 40)?;
                r.fields.iter().try_for_each(|f| {
                    cap("a record key", &f.key, NAME_MAX)?;
                    cap("a record value", &value_text(&f.value), 4000)
                })
            }
            Component::Chart(c) => {
                title(&c.title)?;
                most("chart series", c.series.len(), 6)?;
                if c.series.is_empty() {
                    return Err("a chart has no series".into());
                }
                let mut xs = std::collections::BTreeSet::new();
                for s in &c.series {
                    cap("a series name", &s.name, NAME_MAX)?;
                    most(&format!("series {} points", s.name), s.points.len(), 60)?;
                    let mut own = std::collections::BTreeSet::new();
                    for (x, _) in &s.points {
                        cap("an x label", x, NAME_MAX)?;
                        if !own.insert(x) {
                            return Err(format!("series {} has x {x:?} twice", s.name));
                        }
                    }
                    xs.extend(own);
                }
                most("chart x labels", xs.len(), 60)?;
                // A line joins the same x in every series; a bar may leave one out.
                let first: Vec<&String> = c.series[0].points.iter().map(|p| &p.0).collect();
                if c.chart == ChartKind::Line && c.series.iter().any(|s| s.points.iter().map(|p| &p.0).ne(first.iter().copied())) {
                    return Err("every series of a line chart has the same x, in the same order".into());
                }
                Ok(())
            }
            _ => Ok(()),
        }
    }
}

/// Values the model plots: bar or line, nothing else; drawn as SVG marks or as text.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Chart {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub chart: ChartKind,
    pub series: Vec<Series>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChartKind {
    Bar,
    Line,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Series {
    pub name: String,
    /// (x label, value); JSON has no NaN or infinity, so every value is finite.
    pub points: Vec<(String, f64)>,
}

/// Rows the model shows: `columns` names each cell of every row, in order.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Table {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<Value>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct List {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub items: Vec<ListItem>,
    pub ordered: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ListItem {
    pub text: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tone: Option<Tone>,
}

/// The face's severity words (ui/tone.ts), said as text by both shells.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Tone {
    Ok,
    Info,
    Warn,
    Bad,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub fields: Vec<Field>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Field {
    pub key: String,
    pub value: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Markdown {
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableResults {
    pub table: String,
    /// The table's title, for the header; `table` is its id.
    pub name: String,
    /// What was asked, one line for a person to read; no consumer parses it.
    pub query: String,
    /// Rows after the query, and every row the person may read (the whole-table pull).
    pub matched: usize,
    pub total: usize,
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
