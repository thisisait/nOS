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
                    it.note.as_deref().map_or(Ok(()), |d| cap("a timeline note", d, 2000))
                })
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

/// A history. Horizontal up to 6 items, vertical beyond. `hi` is said as a word.
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
