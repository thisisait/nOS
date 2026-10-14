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
    Tree(Tree),
    Timeline(Timeline),
    Graph(Graph),
    Form(Form),
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

fn is_false(b: &bool) -> bool {
    !*b
}

/// Depth 1 is the root. Over 4, or over 100 nodes in the whole tree, is refused.
fn tree_nodes(n: &TreeNode, depth: usize, count: &mut usize) -> Result<(), String> {
    *count += 1;
    if depth > 4 {
        return Err(format!("tree depth: {depth}, at most 4"));
    }
    cap("a tree label", &n.label, NAME_MAX)?;
    if let Some(note) = &n.note {
        cap("a tree note", note, 2000)?;
    }
    n.children.iter().try_for_each(|c| tree_nodes(c, depth + 1, count))
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
                if c.series.iter().all(|s| s.points.is_empty()) {
                    return Err("a chart has no points".into());
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
                        match c.x {
                            Axis::Number if !x.trim().parse::<f64>().is_ok_and(f64::is_finite) || x.trim() != x => {
                                return Err(format!("x {x:?} is not a number (x: number)"))
                            }
                            Axis::Time if !is_date(x) => {
                                return Err(format!("x {x:?} is not a date YYYY-MM-DD[THH:MM:SS(Z|+HH:MM)] (x: time)"))
                            }
                            _ => {}
                        }
                    }
                    xs.extend(own);
                }
                most("chart x labels", xs.len(), 60)?;
                match c.chart {
                    ChartKind::Scatter if c.x == Axis::Category => return Err("a scatter's x is number or time".into()),
                    ChartKind::Pie if c.series.len() != 1 => return Err(format!("a pie has exactly 1 series, not {}", c.series.len())),
                    ChartKind::Pie => {
                        if let Some((x, y)) = c.series[0].points.iter().find(|p| p.1 < 0.0) {
                            return Err(format!("a pie value is below 0: {x} {y}"));
                        }
                    }
                    // A line, an area or a stack joins the same x in every series; a bar or a scatter may leave one out.
                    ChartKind::Line | ChartKind::Area | ChartKind::StackedBar => {
                        let first: Vec<&String> = c.series[0].points.iter().map(|p| &p.0).collect();
                        if c.series.iter().any(|s| s.points.iter().map(|p| &p.0).ne(first.iter().copied())) {
                            let kind = serde_json::to_value(c.chart).ok().and_then(|v| v.as_str().map(str::to_string)).unwrap_or_default();
                            return Err(format!("every series of a {kind} chart has the same x, in the same order"));
                        }
                    }
                    _ => {}
                }
                Ok(())
            }
            Component::Tree(t) => {
                title(&t.title)?;
                if t.nodes.is_empty() {
                    return Err("a tree has no nodes".into());
                }
                let mut count = 0;
                t.nodes.iter().try_for_each(|n| tree_nodes(n, 1, &mut count))?;
                most("tree nodes", count, 100)
            }
            Component::Timeline(t) => {
                title(&t.title)?;
                if t.items.is_empty() {
                    return Err("a timeline has no items".into());
                }
                most("timeline items", t.items.len(), 30)?;
                t.items.iter().try_for_each(|it| {
                    cap("a timeline when", &it.when, NAME_MAX)?;
                    cap("a timeline title", &it.title, 500)?;
                    it.note.as_deref().map_or(Ok(()), |d| cap("a timeline note", d, 2000))?;
                    it.lane.as_deref().map_or(Ok(()), |l| cap("a timeline lane", l, 40))?;
                    let Some(until) = &it.until else { return Ok(()) };
                    cap("a timeline until", until, NAME_MAX)?;
                    match (instant(&it.when), instant(until)) {
                        (Some(w), Some(u)) if u < w => {
                            Err(format!("timeline item {} ends before it starts: until {until} < when {}", it.title, it.when))
                        }
                        _ => Ok(()),
                    }
                })
            }
            Component::Graph(g) => {
                title(&g.title)?;
                if g.nodes.is_empty() {
                    return Err("a graph has no nodes".into());
                }
                most("graph nodes", g.nodes.len(), 60)?;
                most("graph edges", g.edges.len(), 120)?;
                let mut ids = std::collections::BTreeSet::new();
                for n in &g.nodes {
                    let ok = (1..=64).contains(&n.id.len()) && n.id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
                    if !ok {
                        return Err(format!("graph node id {:?} is not [A-Za-z0-9_-]{{1,64}}", n.id));
                    }
                    if !ids.insert(n.id.as_str()) {
                        return Err(format!("graph node id {:?} twice", n.id));
                    }
                    cap("a graph label", &n.label, NAME_MAX)?;
                    n.note.as_deref().map_or(Ok(()), |d| cap("a graph note", d, 2000))?;
                }
                g.edges.iter().try_for_each(|e| {
                    if let Some(end) = [&e.from, &e.to].into_iter().find(|id| !ids.contains(id.as_str())) {
                        return Err(format!("graph edge {} -> {} names no node {end:?}", e.from, e.to));
                    }
                    e.label.as_deref().map_or(Ok(()), |l| cap("a graph edge label", l, NAME_MAX))
                })
            }
            Component::Form(f) => {
                if !crate::wire::is_uuid(&f.form) {
                    return Err(format!("form is not a lowercase uuid: {:?}", f.form));
                }
                if f.table.is_empty() {
                    return Err("a form names no table".into());
                }
                cap("a form table", &f.table, NAME_MAX)?;
                cap("title", &f.title, NAME_MAX)?;
                most("form fields", f.fields.len(), 20)?;
                most("form omitted columns", f.omitted.len(), 40)?;
                let mut keys = std::collections::BTreeSet::new();
                for x in &f.fields {
                    // KEAP reads __ keys as row sharing; a form never writes one.
                    if x.key.is_empty() || x.key.starts_with("__") {
                        return Err(format!("form field {:?} cannot be written here", x.key));
                    }
                    cap("a form field key", &x.key, 64)?;
                    if !keys.insert(x.key.as_str()) {
                        return Err(format!("form field {:?} twice", x.key));
                    }
                    cap("a form field label", &x.label, NAME_MAX)?;
                    x.placeholder.as_deref().map_or(Ok(()), |p| cap("a form placeholder", p, NAME_MAX))?;
                    let options = x.options.as_deref().unwrap_or_default();
                    if x.kind == FieldKind::Select && !(1..=50).contains(&options.len()) {
                        return Err(format!("select field {} has {} options, 1 to 50", x.key, options.len()));
                    }
                    options.iter().try_for_each(|o| cap("a select option", o, NAME_MAX))?;
                    if let (Some(lo), Some(hi)) = (x.min, x.max) {
                        if lo > hi {
                            return Err(format!("number field {}: min {lo} > max {hi}", x.key));
                        }
                    }
                }
                f.omitted.iter().try_for_each(|o| cap("an omitted column", &o.key, 64))
            }
            _ => Ok(()),
        }
    }

    /// A widget's chart may be one series with no points yet ("no rows yet"); the model's may not.
    pub fn check_allow_empty(&self) -> Result<(), String> {
        match self {
            Component::Chart(c) if c.series.len() == 1 && c.series[0].points.is_empty() => {
                c.title.as_deref().map_or(Ok(()), |t| cap("title", t, NAME_MAX))?;
                cap("a series name", &c.series[0].name, NAME_MAX)
            }
            _ => self.check(),
        }
    }
}

/// `YYYY-MM-DD[THH:MM:SS(Z|±HH:MM)]`, a real calendar day; a bare date is UTC midnight. No date crate.
pub fn is_date(s: &str) -> bool {
    let b = s.as_bytes();
    let num = |r: std::ops::Range<usize>| -> Option<u32> {
        let d = b.get(r)?;
        d.iter().all(u8::is_ascii_digit).then(|| d.iter().fold(0, |n, c| n * 10 + u32::from(c - b'0')))
    };
    let at = |i: usize, c: u8| b.get(i) == Some(&c);
    let (Some(y), Some(m), Some(d)) = (num(0..4), num(5..7), num(8..10)) else { return false };
    let leap = y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    let days = [31, if leap { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if !(at(4, b'-') && at(7, b'-') && (1..=12).contains(&m) && d >= 1 && d <= days[m as usize - 1]) {
        return false;
    }
    if b.len() == 10 {
        return true;
    }
    let clock = |i: usize, sep: bool| -> bool {
        matches!((num(i..i + 2), num(i + 3..i + 5)), (Some(h), Some(mi)) if h < 24 && mi < 60) && at(i + 2, b':') && (!sep || at(i + 5, b':'))
    };
    if !(at(10, b'T') && clock(11, true) && num(17..19).is_some_and(|sec| sec < 60)) {
        return false;
    }
    match b.get(19) {
        Some(b'Z') => b.len() == 20,
        Some(b'+' | b'-') => b.len() == 25 && clock(20, false),
        _ => false,
    }
}

/// Seconds since 1970 UTC of an is_date() string; None when it is not one.
fn instant(s: &str) -> Option<i64> {
    if !is_date(s) {
        return None;
    }
    let n = |r: std::ops::Range<usize>| s[r].parse::<i64>().unwrap_or(0);
    // days_from_civil (Hinnant): the day number of y-m-d, 1970-01-01 = 0.
    let (y, m, d) = (n(0..4) - i64::from(n(5..7) <= 2), n(5..7), n(8..10));
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (m + if m > 2 { -3 } else { 9 }) + 2) / 5 + d - 1;
    let days = era * 146_097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719_468;
    if s.len() == 10 {
        return Some(days * 86_400);
    }
    let offset = match &s[19..20] {
        "Z" => 0,
        sign => (n(20..22) * 3600 + n(23..25) * 60) * if sign == "-" { -1 } else { 1 },
    };
    Some(days * 86_400 + n(11..13) * 3600 + n(14..16) * 60 + n(17..19) - offset)
}

/// Values the model plots, drawn as SVG marks or as text. `x` says how to read every x label;
/// the label is a string on the wire whatever the axis.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Chart {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub chart: ChartKind,
    pub x: Axis,
    pub series: Vec<Series>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChartKind {
    Bar,
    StackedBar,
    Line,
    Area,
    Scatter,
    Pie,
}

/// category: labels in order; number: each x parses as a finite f64; time: each x is_date().
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Axis {
    Category,
    Number,
    Time,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Series {
    pub name: String,
    /// (x label, value); JSON has no NaN or infinity, so every value is finite.
    pub points: Vec<(String, f64)>,
}

/// A hierarchy. One root with 2–4 children is drawn as an org chart; otherwise a nested list.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Tree {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub nodes: Vec<TreeNode>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TreeNode {
    pub label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub children: Vec<TreeNode>,
}

/// A history. Every `when` a date: drawn on a time axis, spans and lanes; otherwise in order,
/// horizontal up to 6 items, vertical beyond. `hi` is said as a word.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Timeline {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub items: Vec<TimelineItem>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TimelineItem {
    pub when: String,
    pub title: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "is_false")]
    pub hi: bool,
    /// A span ends here; when both are dates it is not before `when`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub until: Option<String>,
    /// Items that share a lane are drawn on one row of a time-scaled timeline; at most 40 chars.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lane: Option<String>,
}

/// Things and the links between them, drawn as a layered diagram (one column per rank).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Graph {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphNode {
    /// `[A-Za-z0-9_-]{1,64}`, unique in the graph; edges name it.
    pub id: String,
    pub label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tone: Option<Tone>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphEdge {
    pub from: String,
    pub to: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(default, skip_serializing_if = "is_false")]
    pub dashed: bool,
}

/// A widget form serve builds from a table's live schema (form_from_schema); the model never
/// writes one. The pupil draws its own header and button; `title` is the KEAP table's title.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Form {
    /// A uuid serve minted; a submit names it.
    pub form: String,
    pub table: String,
    pub title: String,
    pub fields: Vec<FormField>,
    /// Columns with no form field (a file, a json...), said as "not editable here".
    pub omitted: Vec<Omitted>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FormField {
    pub key: String,
    pub label: String,
    pub kind: FieldKind,
    pub required: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub options: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub placeholder: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FieldKind {
    Text,
    Number,
    Date,
    Select,
    Bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Omitted {
    pub key: String,
    /// The KEAP column kind, as KEAP names it.
    pub kind: String,
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

#[cfg(test)]
mod tests {
    use super::*;

    fn table(columns: usize, rows: usize, cell: &str) -> Component {
        Component::Table(Table {
            title: None,
            columns: (0..columns).map(|i| i.to_string()).collect(),
            rows: vec![vec![Value::String(cell.to_string()); columns]; rows],
        })
    }

    fn list(n: usize) -> Component {
        Component::List(List {
            title: None,
            ordered: false,
            items: (0..n).map(|i| ListItem { text: i.to_string(), detail: None, tone: None }).collect(),
        })
    }

    #[test]
    fn check_rejects_more_than_12_columns() {
        assert!(table(12, 1, "x").check().is_ok());
        assert_eq!(table(13, 1, "x").check(), Err("table columns: 13, at most 12".into()));
    }

    #[test]
    fn check_rejects_more_than_50_rows() {
        assert!(table(1, 50, "x").check().is_ok());
        assert_eq!(table(1, 51, "x").check(), Err("table rows: 51, at most 50".into()));
    }

    #[test]
    fn check_rejects_a_cell_over_2000_chars() {
        assert!(table(1, 1, &"x".repeat(2000)).check().is_ok());
        assert_eq!(table(1, 1, &"x".repeat(2001)).check(), Err("a table cell is over 2000 chars".into()));
    }

    #[test]
    fn check_rejects_more_than_50_list_items() {
        assert!(list(50).check().is_ok());
        assert_eq!(list(51).check(), Err("list items: 51, at most 50".into()));
    }

    fn decode(raw: &str) -> Component {
        serde_json::from_str(raw).unwrap_or_else(|e| panic!("component does not decode: {e}"))
    }

    /// A chain of `depth` nodes, root first.
    fn chain(depth: usize) -> String {
        let mut n = r#"{"label":"leaf"}"#.to_string();
        for i in (0..depth - 1).rev() {
            n = format!(r#"{{"label":"n{i}","children":[{n}]}}"#);
        }
        format!(r#"{{"kind":"tree","props":{{"nodes":[{n}]}}}}"#)
    }

    #[test]
    fn check_rejects_a_tree_deeper_than_4_or_over_100_nodes() {
        let ok = r#"{"kind":"tree","props":{"title":"Roadmap","nodes":[{"label":"nOS","children":[{"label":"pupil","note":"the eye"},{"label":"keap"}]}]}}"#;
        assert!(decode(ok).check().is_ok());
        assert!(decode(&chain(4)).check().is_ok());
        assert_eq!(decode(&chain(5)).check(), Err("tree depth: 5, at most 4".into()));
        let nodes = (0..101).map(|i| format!(r#"{{"label":"n{i}"}}"#)).collect::<Vec<_>>().join(",");
        assert_eq!(decode(&format!(r#"{{"kind":"tree","props":{{"nodes":[{nodes}]}}}}"#)).check(), Err("tree nodes: 101, at most 100".into()));
        assert_eq!(decode(r#"{"kind":"tree","props":{"nodes":[]}}"#).check(), Err("a tree has no nodes".into()));
    }

    #[test]
    fn check_rejects_a_timeline_over_30_items() {
        let ok = r#"{"kind":"timeline","props":{"title":"History","items":[{"when":"2026-10-12","title":"I4a landed","note":"query_rows"},{"when":"2026-10-13","title":"chart","hi":true}]}}"#;
        assert!(decode(ok).check().is_ok());
        let items = |n: usize| (0..n).map(|i| format!(r#"{{"when":"d{i}","title":"t{i}"}}"#)).collect::<Vec<_>>().join(",");
        assert!(decode(&format!(r#"{{"kind":"timeline","props":{{"items":[{}]}}}}"#, items(30))).check().is_ok());
        assert_eq!(decode(&format!(r#"{{"kind":"timeline","props":{{"items":[{}]}}}}"#, items(31))).check(), Err("timeline items: 31, at most 30".into()));
        assert_eq!(decode(r#"{"kind":"timeline","props":{"items":[]}}"#).check(), Err("a timeline has no items".into()));
    }

    fn timeline(items: &str) -> Component {
        decode(&format!(r#"{{"kind":"timeline","props":{{"items":[{items}]}}}}"#))
    }

    #[test]
    fn a_timeline_item_may_span_and_sit_in_a_lane() {
        let spans = timeline(r#"{"when":"2026-10-01","until":"2026-10-05","title":"I5a","lane":"thalamus"},{"when":"2026-10-03","title":"review"}"#);
        assert_eq!(spans.check(), Ok(()));
        assert_eq!(timeline(r#"{"when":"2026-10-01","until":"2026-10-01","title":"a day"}"#).check(), Ok(()), "a span may end where it starts");
        // Not dates, so nothing to compare: the drawing is ordinal.
        assert_eq!(timeline(r#"{"when":"Q3","until":"Q1","title":"later"}"#).check(), Ok(()));
        assert_eq!(timeline(&format!(r#"{{"when":"Q1","title":"t","lane":"{}"}}"#, "l".repeat(40))).check(), Ok(()));
        assert_eq!(timeline(&format!(r#"{{"when":"Q1","title":"t","lane":"{}"}}"#, "l".repeat(41))).check(),
                   Err("a timeline lane is over 40 chars".into()));
    }

    #[test]
    fn check_rejects_until_before_when() {
        assert_eq!(timeline(r#"{"when":"2026-10-05","until":"2026-10-01","title":"I5a"}"#).check(),
                   Err("timeline item I5a ends before it starts: until 2026-10-01 < when 2026-10-05".into()));
        // An offset is an instant: 01:00+02:00 is 23:00Z the day before, so it ends before 23:30Z.
        assert!(timeline(r#"{"when":"2026-10-12T23:30:00Z","until":"2026-10-13T01:00:00+02:00","title":"t"}"#).check().is_err());
        assert_eq!(timeline(r#"{"when":"2026-10-12T22:30:00Z","until":"2026-10-13T01:00:00+02:00","title":"t"}"#).check(), Ok(()));
    }

    fn chart(kind: &str, x: &str, series: &str) -> Component {
        decode(&format!(r#"{{"kind":"chart","props":{{"chart":"{kind}","x":"{x}","series":[{series}]}}}}"#))
    }

    #[test]
    fn every_chart_kind_and_axis_decodes() {
        for kind in ["bar", "stacked_bar", "line", "area", "pie"] {
            assert_eq!(chart(kind, "category", r#"{"name":"a","points":[["x",1],["y",2]]}"#).check(), Ok(()), "{kind}");
        }
        assert_eq!(chart("scatter", "number", r#"{"name":"a","points":[["3",5],["-1.5e2",2]]}"#).check(), Ok(()));
        assert_eq!(chart("line", "time", r#"{"name":"a","points":[["2026-10-12",5],["2026-10-13T08:30:00Z",2]]}"#).check(), Ok(()));
    }

    #[test]
    fn check_rejects_a_number_x_that_is_not_a_number() {
        assert_eq!(chart("scatter", "number", r#"{"name":"a","points":[["abc",1]]}"#).check(),
                   Err(r#"x "abc" is not a number (x: number)"#.into()));
    }

    #[test]
    fn check_rejects_a_time_x_that_is_not_a_date() {
        assert_eq!(chart("line", "time", r#"{"name":"a","points":[["yesterday",1]]}"#).check(),
                   Err(r#"x "yesterday" is not a date YYYY-MM-DD[THH:MM:SS(Z|+HH:MM)] (x: time)"#.into()));
    }

    #[test]
    fn check_rejects_a_scatter_over_categories() {
        assert_eq!(chart("scatter", "category", r#"{"name":"a","points":[["x",1]]}"#).check(),
                   Err("a scatter's x is number or time".into()));
    }

    #[test]
    fn check_rejects_a_pie_with_two_series() {
        let one = r#"{"name":"a","points":[["x",1]]}"#;
        assert_eq!(chart("pie", "category", &format!("{one},{one}")).check(), Err("a pie has exactly 1 series, not 2".into()));
        assert_eq!(chart("pie", "category", r#"{"name":"a","points":[["x",-1]]}"#).check(), Err("a pie value is below 0: x -1".into()));
    }

    #[test]
    fn check_rejects_stacked_or_area_series_that_disagree_on_x() {
        for kind in ["stacked_bar", "area", "line"] {
            let e = chart(kind, "category", r#"{"name":"a","points":[["x",1],["y",2]]},{"name":"b","points":[["y",1],["x",2]]}"#).check();
            assert_eq!(e, Err(format!("every series of a {kind} chart has the same x, in the same order")), "{kind}");
        }
        // A grouped bar may leave an x out.
        assert_eq!(chart("bar", "category", r#"{"name":"a","points":[["x",1],["y",2]]},{"name":"b","points":[["y",1]]}"#).check(), Ok(()));
    }

    #[test]
    fn a_widget_chart_may_be_empty_a_model_chart_may_not() {
        let empty = chart("bar", "category", r#"{"name":"rows","points":[]}"#);
        assert_eq!(empty.check(), Err("a chart has no points".into()));
        assert_eq!(empty.check_allow_empty(), Ok(()));
        let none = decode(r#"{"kind":"chart","props":{"chart":"bar","x":"category","series":[]}}"#);
        assert_eq!(none.check_allow_empty(), Err("a chart has no series".into()));
        // Empty is allowed only as itself; anything else still meets every cap.
        assert!(chart("pie", "category", r#"{"name":"a","points":[["x",1]]},{"name":"b","points":[]}"#).check_allow_empty().is_err());
    }

    #[test]
    fn a_chart_names_its_axis() {
        let raw = r#"{"kind":"chart","props":{"chart":"bar","series":[{"name":"a","points":[["x",1]]}]}}"#;
        assert!(serde_json::from_str::<Component>(raw).is_err(), "x is required on the wire");
    }

    fn graph(nodes: &str, edges: &str) -> Component {
        decode(&format!(r#"{{"kind":"graph","props":{{"title":"Organs","nodes":[{nodes}],"edges":[{edges}]}}}}"#))
    }

    fn nodes(n: usize) -> String {
        (0..n).map(|i| format!(r#"{{"id":"n{i}","label":"node {i}"}}"#)).collect::<Vec<_>>().join(",")
    }

    #[test]
    fn a_graph_is_nodes_and_edges_between_them() {
        let ok = graph(r#"{"id":"bone","label":"Bone","note":"the bridge","tone":"ok"},{"id":"wing","label":"Wing"}"#,
                       r#"{"from":"bone","to":"wing","label":"events"},{"from":"wing","to":"bone","dashed":true}"#);
        assert_eq!(ok.check(), Ok(()));
        assert_eq!(graph(&nodes(1), r#"{"from":"n0","to":"n0"}"#).check(), Ok(()), "a loop is an edge");
        assert_eq!(graph("", "").check(), Err("a graph has no nodes".into()));
    }

    #[test]
    fn check_rejects_a_graph_edge_to_a_missing_node() {
        assert_eq!(graph(&nodes(2), r#"{"from":"n0","to":"ghost"}"#).check(), Err(r#"graph edge n0 -> ghost names no node "ghost""#.into()));
        assert_eq!(graph(&nodes(2), r#"{"from":"ghost","to":"n1"}"#).check(), Err(r#"graph edge ghost -> n1 names no node "ghost""#.into()));
    }

    #[test]
    fn check_rejects_a_graph_over_its_caps() {
        assert_eq!(graph(&nodes(60), "").check(), Ok(()));
        assert_eq!(graph(&nodes(61), "").check(), Err("graph nodes: 61, at most 60".into()));
        let edges = |n: usize| (0..n).map(|i| format!(r#"{{"from":"n{}","to":"n{}"}}"#, i % 60, (i + 1) % 60)).collect::<Vec<_>>().join(",");
        assert_eq!(graph(&nodes(60), &edges(120)).check(), Ok(()));
        assert_eq!(graph(&nodes(60), &edges(121)).check(), Err("graph edges: 121, at most 120".into()));
        assert_eq!(graph(r#"{"id":"a","label":"A"},{"id":"a","label":"B"}"#, "").check(), Err(r#"graph node id "a" twice"#.into()));
        for bad in ["", "a b", "a/b", "ünï", &"x".repeat(65)] {
            let n = format!(r#"{{"id":{},"label":"A"}}"#, serde_json::to_string(bad).unwrap());
            assert_eq!(graph(&n, "").check(), Err(format!("graph node id {bad:?} is not [A-Za-z0-9_-]{{1,64}}")), "{bad:?}");
        }
        assert_eq!(graph(&format!(r#"{{"id":"{}","label":"A"}}"#, "x".repeat(64)), "").check(), Ok(()));
        assert_eq!(graph(&format!(r#"{{"id":"a","label":"{}"}}"#, "l".repeat(121)), "").check(), Err("a graph label is over 120 chars".into()));
        assert_eq!(graph(&format!(r#"{{"id":"a","label":"A","note":"{}"}}"#, "n".repeat(2001)), "").check(), Err("a graph note is over 2000 chars".into()));
        assert_eq!(graph(&nodes(1), &format!(r#"{{"from":"n0","to":"n0","label":"{}"}}"#, "l".repeat(121))).check(),
                   Err("a graph edge label is over 120 chars".into()));
    }

    const FORM_ID: &str = "5f0c1b2a-3d4e-4f5a-8b6c-7d8e9f0a1b2c";

    fn form(fields: &str) -> String {
        format!(r#"{{"kind":"form","props":{{"form":"{FORM_ID}","table":"expenses","title":"Expenses","fields":[{fields}],"omitted":[{{"key":"receipt","kind":"file"}}]}}}}"#)
    }

    fn field(key: &str) -> String {
        format!(r#"{{"key":"{key}","label":"{key}","kind":"text","required":false}}"#)
    }

    #[test]
    fn a_form_is_fields_of_five_kinds() {
        let ok = form(r#"{"key":"note","label":"Note","kind":"text","required":false,"placeholder":"what for"},
            {"key":"amount","label":"Amount","kind":"number","required":true,"min":0,"max":10000},
            {"key":"when","label":"When","kind":"date","required":false},
            {"key":"kind","label":"Kind","kind":"select","required":true,"options":["food","travel","tools"]},
            {"key":"paid","label":"Paid","kind":"bool","required":false}"#);
        assert_eq!(decode(&ok).check(), Ok(()));
        let fields = (0..20).map(|i| field(&format!("f{i}"))).collect::<Vec<_>>().join(",");
        assert_eq!(decode(&form(&fields)).check(), Ok(()), "20 fields is the cap, not over it");
    }

    #[test]
    fn check_rejects_a_form_over_its_caps() {
        let fields = (0..21).map(|i| field(&format!("f{i}"))).collect::<Vec<_>>().join(",");
        assert_eq!(decode(&form(&fields)).check(), Err("form fields: 21, at most 20".into()));
        assert_eq!(decode(&form(&format!("{},{}", field("a"), field("a")))).check(), Err(r#"form field "a" twice"#.into()));
        for bad in ["__shared_with", ""] {
            assert_eq!(decode(&form(&field(bad))).check(), Err(format!("form field {bad:?} cannot be written here")), "{bad:?}");
        }
        let select = |n: usize| {
            let o = (0..n).map(|i| format!(r#""o{i}""#)).collect::<Vec<_>>().join(",");
            form(&format!(r#"{{"key":"s","label":"S","kind":"select","required":true,"options":[{o}]}}"#))
        };
        assert_eq!(decode(&select(50)).check(), Ok(()));
        for n in [0, 51] {
            assert_eq!(decode(&select(n)).check(), Err(format!("select field s has {n} options, 1 to 50")), "{n}");
        }
        let range = form(r#"{"key":"n","label":"N","kind":"number","required":false,"min":5,"max":1}"#);
        assert_eq!(decode(&range).check(), Err("number field n: min 5 > max 1".into()));
        let not_uuid = form(&field("a")).replace(FORM_ID, "latest");
        assert_eq!(decode(&not_uuid).check(), Err(r#"form is not a lowercase uuid: "latest""#.into()));
        let no_table = form(&field("a")).replace(r#""table":"expenses""#, r#""table":"""#);
        assert_eq!(decode(&no_table).check(), Err("a form names no table".into()));
    }

    /// The model has no form: a form is drawn only inside the widget message the person asked for (I5f).
    #[test]
    fn a_render_or_an_approval_carrying_a_form_is_refused() {
        use crate::wire::{decode_to_shell, ToShell};
        let s = "0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b";
        let render = format!(r#"{{"t":"render","session":"{s}","component":{}}}"#, form(&field("a")));
        let ask = format!(r#"{{"t":"approval_request","session":"{s}","approval":"{FORM_ID}","component":{}}}"#, form(&field("a")));
        for line in [render, ask] {
            match decode_to_shell(&line) {
                ToShell::Refused { reason, .. } => assert!(reason.contains("a form is drawn only as a widget the person made"), "{reason}"),
                m => panic!("a form outside a widget was accepted: {m:?}"),
            }
        }
        let fields = (0..21).map(|i| field(&format!("f{i}"))).collect::<Vec<_>>().join(",");
        let over = format!(r#"{{"t":"render","session":"{s}","component":{}}}"#, form(&fields));
        assert!(matches!(decode_to_shell(&over), ToShell::Refused { reason, .. } if reason.contains("form fields: 21")));
    }

    /// A pin is a spec the person may place, so it meets the check a widget message's spec meets (I6).
    #[test]
    fn a_render_whose_pin_fails_widget_validation_is_refused() {
        use crate::wire::{decode_to_shell, decode_to_thalamus, ToShell};
        let s = "0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b";
        let pie = r#"{"kind":"chart","props":{"chart":"pie","x":"category","series":[{"name":"count","points":[["open",2]]}]}}"#;
        let render = |pin: &str| format!(r#"{{"t":"render","session":"{s}","component":{pie},"pin":{pin}}}"#);
        let good = r#"{"chart":{"query":{"table":"todos"},"chart":"pie","x":"status","op":"count"}}"#;
        assert!(matches!(decode_to_shell(&render(good)), ToShell::Render { pin: Some(_), .. }), "a valid pin decodes");
        for (pin, want) in [
            (r#"{"chart":{"query":{"table":"todos"},"chart":"pie","x":"status","op":"sum"}}"#, "sum needs `y`"),
            (r#"{"chart":{"query":{"table":""},"chart":"pie","x":"status","op":"count"}}"#, "names no table"),
            (r#"{"rows":{"q":"x"}}"#, "names no table"),
            (r#"{"rows":["todos"]}"#, "rows spec is an object"),
        ] {
            match decode_to_shell(&render(pin)) {
                ToShell::Refused { reason, .. } => assert!(reason.contains(want), "{pin}: {reason}"),
                m => panic!("a render pinned {pin} was accepted: {m:?}"),
            }
            let widget = format!(r#"{{"t":"widget","widget":"w1","spec":{pin},"trigger":"click"}}"#);
            assert!(decode_to_thalamus(&widget).is_err_and(|e| e.contains(want)), "the same spec as a widget: {pin}");
        }
    }

    /// Through check(), so the matcher is the one a time chart meets.
    fn is_date(x: &str) -> bool {
        chart("line", "time", &format!(r#"{{"name":"a","points":[[{}, 1]]}}"#, serde_json::to_string(x).unwrap())).check().is_ok()
    }

    #[test]
    fn date_matcher_table() {
        for ok in ["2026-10-13", "2024-02-29", "2000-02-29", "2026-12-31T23:59:59Z", "2026-01-01T00:00:00+02:00",
                   "2026-01-01T00:00:00-11:30", "0001-01-01"] {
            assert!(is_date(ok), "{ok} is a date");
        }
        for bad in ["2026-02-30", "2025-02-29", "1900-02-29", "2026-13-01", "2026-00-10", "2026-04-31", "2026-10-1",
                    "26-10-13", "2026/10/13", "2026-10-13T", "2026-10-13T10:00", "2026-10-13T10:00:00", "2026-10-13T24:00:00Z",
                    "2026-10-13T10:60:00Z", "2026-10-13T10:00:60Z", "2026-10-13T10:00:00+2:00", "2026-10-13T10:00:00+24:00",
                    "2026-10-13 10:00:00Z", "2026-10-13T10:00:00.5Z", " 2026-10-13", "２０２６-10-13", "yesterday", ""] {
            assert!(!is_date(bad), "{bad:?} is not a date");
        }
    }
}
