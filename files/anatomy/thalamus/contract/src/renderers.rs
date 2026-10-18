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
    TableSchemaApproval(TableSchemaApproval),
    ColumnAddApproval(ColumnAddApproval),
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
    Sequence(Sequence),
    Form(Form),
    Choice(Choice),
    Dashboard(Dashboard),
    Kpi(Kpi),
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

/// Depth 1 is the root. Over 4, or over 100 nodes in the whole tree, is refused; so is a node
/// whose delta contradicts an added or removed parent's.
fn tree_nodes(n: &TreeNode, depth: usize, count: &mut usize, parent: Option<Delta>) -> Result<(), String> {
    *count += 1;
    if depth > 4 {
        return Err(format!("tree depth: {depth}, at most 4"));
    }
    cap("a tree label", &n.label, NAME_MAX)?;
    if let Some(note) = &n.note {
        cap("a tree note", note, 2000)?;
    }
    let delta = Delta::inherit(n.delta, parent);
    if let (Some(own), Some(p)) = (n.delta, parent) {
        if delta != Some(own) {
            return Err(format!("tree node {:?} is {} under a {} parent", n.label, own.word(), p.word()));
        }
    }
    n.children.iter().try_for_each(|c| tree_nodes(c, depth + 1, count, delta))
}

/// What an action would do to a tree node, a list item or a record field (iris-genui-change-markers).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Delta {
    Added,
    Removed,
    Changed,
}

impl Delta {
    /// An added or removed parent passes its state down; a changed one passes nothing.
    pub fn inherit(own: Option<Delta>, parent: Option<Delta>) -> Option<Delta> {
        match parent {
            Some(p @ (Delta::Added | Delta::Removed)) => Some(p),
            _ => own,
        }
    }

    pub fn word(self) -> &'static str {
        match self {
            Delta::Added => "added",
            Delta::Removed => "removed",
            Delta::Changed => "changed",
        }
    }

    /// The text mark the terminal prefixes a line with.
    pub fn mark(self) -> char {
        match self {
            Delta::Added => '+',
            Delta::Removed => '-',
            Delta::Changed => '~',
        }
    }
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
                    cap("a record value", &value_text(&f.value), 4000)?;
                    let Some(was) = &f.was else { return Ok(()) };
                    if f.delta != Some(Delta::Changed) {
                        return Err(format!("record field {}: was is only on a changed field", f.key));
                    }
                    cap("a record was", &value_text(was), 4000)
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
                t.nodes.iter().try_for_each(|n| tree_nodes(n, 1, &mut count, None))?;
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
            Component::Sequence(q) => {
                title(&q.title)?;
                if !(2..=8).contains(&q.participants.len()) {
                    return Err(format!("sequence participants: {}, 2 to 8", q.participants.len()));
                }
                let mut seen = std::collections::BTreeSet::new();
                for p in &q.participants {
                    if p.trim().is_empty() {
                        return Err("a sequence participant is empty".into());
                    }
                    cap("a sequence participant", p, 40)?;
                    if !seen.insert(p.as_str()) {
                        return Err(format!("sequence participant {p:?} twice"));
                    }
                }
                if q.steps.is_empty() {
                    return Err("a sequence has no steps".into());
                }
                most("sequence steps", q.steps.len(), 40)?;
                for (i, step) in q.steps.iter().enumerate() {
                    match step {
                        Step::Message { from, to, text, .. } => {
                            if let Some(x) = [from, to].into_iter().find(|x| !seen.contains(x.as_str())) {
                                return Err(format!("sequence step {}: {from} -> {to} names no participant {x:?}", i + 1));
                            }
                            cap("a sequence message", text, NAME_MAX)?;
                        }
                        Step::Note { note, over } => {
                            cap("a sequence note", note, 200)?;
                            if !(1..=2).contains(&over.len()) {
                                return Err(format!("sequence step {}: a note is over {} participants, 1 to 2", i + 1, over.len()));
                            }
                            if let Some(x) = over.iter().find(|x| !seen.contains(x.as_str())) {
                                return Err(format!("sequence step {}: a note over {x:?} names no participant", i + 1));
                            }
                        }
                        Step::Phase { phase } => cap("a sequence phase", phase, 60)?,
                    }
                }
                Ok(())
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
                for (x, w) in f.fields.iter().filter_map(|x| x.when.as_ref().map(|w| (x, w))) {
                    // A hidden field sends nothing, so a required one would make the form unsendable.
                    if x.required {
                        return Err(format!("{} is required, so it is never hidden", x.key));
                    }
                    if w.key == x.key {
                        return Err(format!("{} is shown on itself", x.key));
                    }
                    if !keys.contains(w.key.as_str()) {
                        return Err(format!("{} is shown when `{}`, a field the form does not have", x.key, w.key));
                    }
                    cap("a when value", &w.value, NAME_MAX)?;
                }
                if let Some(k) = f.prefill.iter().flatten().map(|(k, _)| k).find(|k| !keys.contains(k.as_str())) {
                    return Err(format!("the prefill names `{k}`, a field the form does not have"));
                }
                f.omitted.iter().try_for_each(|o| cap("an omitted column", &o.key, 64))
            }
            Component::Choice(c) => {
                if let Some(id) = &c.id {
                    if !crate::wire::is_uuid(id) {
                        return Err(format!("choice id is not a lowercase uuid: {id:?}"));
                    }
                }
                if c.question.trim().is_empty() {
                    return Err("a choice asks no question".into());
                }
                cap("a choice question", &c.question, NAME_MAX)?;
                if c.question.split_whitespace().count() > 15 {
                    return Err("a choice question is over 15 words".into());
                }
                if !(2..=6).contains(&c.options.len()) {
                    return Err(format!("choice options: {}, 2 to 6", c.options.len()));
                }
                let mut seen = std::collections::BTreeSet::new();
                for o in &c.options {
                    if o.label.trim().is_empty() {
                        return Err("a choice option label is empty".into());
                    }
                    cap("a choice option label", &o.label, 60)?;
                    o.note.as_deref().map_or(Ok(()), |n| cap("a choice option note", n, 200))?;
                    if !seen.insert(o.label.trim().to_lowercase()) {
                        return Err(format!("choice option {:?} twice (case and spaces aside)", o.label));
                    }
                }
                if let Some(s) = c.suggested.iter().find(|s| !c.options.iter().any(|o| &o.label == *s)) {
                    return Err(format!("suggested {s:?} is not an option"));
                }
                let distinct: std::collections::BTreeSet<&String> = c.suggested.iter().collect();
                if distinct.len() != c.suggested.len() || (c.multi && c.suggested.is_empty()) || (!c.multi && c.suggested.len() != 1) {
                    return Err(format!("a choice suggests exactly 1 option, not {}; multi suggests 1 or more", c.suggested.len()));
                }
                Ok(())
            }
            Component::Dashboard(d) => {
                if d.name.trim().is_empty() {
                    return Err("a dashboard has no name".into());
                }
                cap("a dashboard name", &d.name, 40)?;
                check_lens(&d.lens)?;
                if !(1..=8).contains(&d.widgets.len()) {
                    return Err(format!("dashboard widgets: {}, 1 to 8", d.widgets.len()));
                }
                for w in &d.widgets {
                    cap("a widget title", &w.title, NAME_MAX)?;
                    crate::wire::check_spec(&w.spec).map_err(|e| format!("widget {:?}: {e}", w.title))?;
                }
                most("dashboard dropped widgets", d.dropped.len(), 8)?;
                d.dropped.iter().try_for_each(|x| cap("a dropped title", &x.title, NAME_MAX).and_then(|_| cap("a dropped why", &x.why, 500)))
            }
            Component::Kpi(k) => {
                if k.title.trim().is_empty() {
                    return Err("a kpi has no title".into());
                }
                cap("title", &k.title, NAME_MAX)?;
                k.unit.as_deref().map_or(Ok(()), |u| cap("a kpi unit", u, 16))?;
                // A digit in the unit reads as part of KEAP's number ("000 Kč" turns 6 into 6 000).
                if k.unit.as_deref().is_some_and(|u| u.chars().any(char::is_numeric)) {
                    return Err("a kpi unit has no digit; the number is the thalamus's".into());
                }
                k.delta_label.as_deref().map_or(Ok(()), |l| cap("a kpi delta label", l, 60))?;
                k.source.as_deref().map_or(Ok(()), |s| cap("a kpi source", s, 200))
            }
            Component::RowDiffApproval(d) => {
                if d.cells.is_empty() {
                    return Err("an approval changes at least one cell".into());
                }
                d.warning.as_deref().map_or(Ok(()), |w| cap("a card warning", w, 400))?;
                match (d.op, &d.lines) {
                    (RowOp::InsertMany, None) => return Err("insert_many carries its lines".into()),
                    (RowOp::InsertMany, Some(l)) => check_lines(l)?,
                    (_, Some(_)) => return Err("only insert_many carries lines".into()),
                    (_, None) => {}
                }
                match (d.op, d.row_id.as_deref()) {
                    (RowOp::InsertMany, Some(id)) if id.is_empty() => Err("an existing parent names its row".into()),
                    (RowOp::InsertMany, Some(_)) if d.cells.iter().any(|c| c.old != c.new) => Err("an existing parent is not changed here".into()),
                    (RowOp::InsertMany, Some(_)) => Ok(()),
                    (RowOp::InsertMany, None) if d.cells.iter().any(|c| !c.old.is_null()) => Err("an insert has no old value".into()),
                    (RowOp::InsertMany, None) => Ok(()),
                    (RowOp::Update, Some(id)) if !id.is_empty() => Ok(()),
                    (RowOp::Update, _) => Err("an update names its row".into()),
                    (RowOp::Insert, Some(_)) => Err("an insert names no row; KEAP mints it".into()),
                    (RowOp::Insert, None) if d.cells.iter().any(|c| !c.old.is_null()) => Err("an insert has no old value".into()),
                    (RowOp::Insert, None) => Ok(()),
                    (RowOp::Delete, Some(id)) if !id.is_empty() => d.cells.iter().try_for_each(|c| match (&c.old, &c.new) {
                        (_, n) if !n.is_null() => Err("a delete leaves every cell empty".into()),
                        (o, _) if o.is_null() => Err("a delete shows each value it removes".into()),
                        _ => Ok(()),
                    }),
                    (RowOp::Delete, _) => Err("a delete names its row".into()),
                }
            }
            Component::TableSchemaApproval(t) => {
                if t.title.trim().is_empty() {
                    return Err("a new table has a title".into());
                }
                cap("a table title", &t.title, 160)?;
                t.description.as_deref().map_or(Ok(()), |d| cap("a table description", d, 2000))?;
                if !(1..=30).contains(&t.columns.len()) {
                    return Err(format!("a table has 1 to 30 columns, not {}", t.columns.len()));
                }
                let twice = |v: &[String]| v.iter().enumerate().find_map(|(i, x)| v[..i].contains(x).then(|| x.clone()));
                if let Some(k) = twice(&t.columns.iter().map(|c| c.key.clone()).collect::<Vec<_>>()) {
                    return Err(format!("column key {k} appears twice"));
                }
                t.columns.iter().try_for_each(check_column)
            }
            Component::ColumnAddApproval(t) => {
                if t.table.trim().is_empty() {
                    return Err("a column add names its table".into());
                }
                if !(1..=30).contains(&t.columns.len()) {
                    return Err(format!("a column add has 1 to 30 new columns, not {}", t.columns.len()));
                }
                let n = t.existing.len() + t.columns.len();
                if n > 120 {
                    return Err(format!("a table has at most 120 columns (KEAP); {} would have {n}", t.title));
                }
                for (i, c) in t.columns.iter().enumerate() {
                    if t.existing.iter().any(|e| e.key == c.key) {
                        return Err(format!("table {} already has a column {}", t.title, c.key));
                    }
                    if t.columns[..i].iter().any(|x| x.key == c.key) {
                        return Err(format!("column key {} appears twice", c.key));
                    }
                    if c.required {
                        return Err(format!("column {}: a column added to a table is optional (its rows have no value for it)", c.key));
                    }
                    check_column(c)?;
                }
                Ok(())
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub delta: Option<Delta>,
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

/// Who sends what to whom, in order: one lifeline per participant, one row per step.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sequence {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub participants: Vec<String>,
    pub steps: Vec<Step>,
}

/// A step is told apart by its fields: {from, to, text, dashed?}, {note, over}, or {phase}.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged, deny_unknown_fields)]
pub enum Step {
    Message {
        from: String,
        to: String,
        text: String,
        /// A reply, drawn dashed.
        #[serde(default, skip_serializing_if = "is_false")]
        dashed: bool,
    },
    Note { note: String, over: Vec<String> },
    Phase { phase: String },
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
    /// Where the person's draft starts, by field key (FormSpec prefill, checked as a submit is); never a value sent.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prefill: Option<serde_json::Map<String, serde_json::Value>>,
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
    /// Drawn and sent only while the condition holds; a required field never carries one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub when: Option<When>,
    /// serve's, never on the wire: a rowRef field's parent table and the row ids its options name.
    #[serde(skip)]
    pub parent: Option<Parent>,
}

/// The parent of a rowRef field: `ids[i]` is the row `options[i]` shows (empty when the field is text).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Parent {
    pub table: String,
    pub display: String,
    pub ids: Vec<String>,
}

/// Another field of the same form holds (eq) or does not hold (neq) `value`, as the pupil's draft says it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct When {
    pub key: String,
    pub op: WhenOp,
    pub value: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WhenOp {
    Eq,
    Neq,
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

/// One number serve computed from a table (show kpi with a source, or a kpi widget); never the model's.
/// `source` says what was totalled over which rows; `delta` is a change the pupil says as an arrow and a sign.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Kpi {
    pub title: String,
    pub value: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub delta: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub delta_label: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
}

/// A tab of widgets Iris offers (offer_dashboard); drawn with "Place here" and "Place on a new tab", it runs nothing
/// until the person places it. `dropped` is every widget serve left out, with why.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dashboard {
    pub name: String,
    pub lens: Vec<Lens>,
    pub widgets: Vec<DashboardWidget>,
    pub dropped: Vec<Dropped>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DashboardWidget {
    pub title: String,
    pub spec: crate::wire::WidgetSpec,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dropped {
    pub title: String,
    pub why: String,
}

/// One tab-wide condition: it joins every rows and chart widget's `where` when the widget is sent,
/// never its saved spec. An empty value is unset. kind and options say how the person picks a value.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lens {
    pub column: String,
    pub op: LensOp,
    pub value: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<FieldKind>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub options: Option<Vec<String>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LensOp {
    Eq,
    Neq,
    Lt,
    Gt,
    Contains,
}

/// One column of a new table as KEAP's createTable takes it (keap shared/contracts/table.ts columnDefSchema).
fn check_column(c: &SchemaColumn) -> Result<(), String> {
    let k = &c.key;
    let snake = c.key.len() <= 64 && c.key.starts_with(|x: char| x.is_ascii_lowercase())
        && c.key.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_');
    if !snake {
        return Err(format!("column key {k:?} is not snake_case ([a-z][a-z0-9_]*, at most 64)"));
    }
    if c.label.trim().is_empty() {
        return Err(format!("column {k} has no label"));
    }
    cap("a column label", &c.label, NAME_MAX)?;
    match (c.kind, &c.options) {
        (ColumnKind::Select, Some(o)) if (1..=50).contains(&o.len()) => {
            if let Some(x) = o.iter().find(|x| x.trim().is_empty() || x.chars().count() > NAME_MAX) {
                return Err(format!("column {k}: option {x:?} is empty or over {NAME_MAX} chars"));
            }
            if let Some(x) = o.iter().enumerate().find_map(|(i, x)| o[..i].contains(x).then_some(x)) {
                return Err(format!("column {k}: option {x:?} appears twice"));
            }
        }
        (ColumnKind::Select, _) => return Err(format!("column {k}: a select has 1 to 50 options")),
        (_, Some(_)) => return Err(format!("column {k}: only a select has options")),
        _ => {}
    }
    let refs = c.ref_table.is_some() || c.ref_title.is_some() || c.ref_display.is_some();
    match c.kind {
        ColumnKind::RowRef if c.ref_table.as_deref().is_none_or(str::is_empty) => Err(format!("column {k}: a rowRef names the table it points into")),
        ColumnKind::RowRef => Ok(()),
        _ if refs => Err(format!("column {k}: only a rowRef points into a table")),
        _ => Ok(()),
    }
}

/// 1 to 20 lines, each writing at least one cell with no old and never the parent's own column.
fn check_lines(l: &Lines) -> Result<(), String> {
    if !(1..=20).contains(&l.rows.len()) {
        return Err(format!("lines: {}, 1 to 20", l.rows.len()));
    }
    if l.ref_key.is_empty() {
        return Err("lines name the column that points at the parent".into());
    }
    l.rows.iter().try_for_each(|r| match r {
        _ if r.is_empty() => Err("a line writes at least one cell".into()),
        _ if r.iter().any(|c| c.key == l.ref_key) => Err(format!("a line's {} is the parent's; serve fills it", l.ref_key)),
        _ if r.iter().any(|c| !c.old.is_null()) => Err("a line has no old value".into()),
        _ => Ok(()),
    })
}

/// At most 4 conditions, each naming a column; a dashboard and a saved tab (workspace-layout.yml) share it.
pub fn check_lens(lens: &[Lens]) -> Result<(), String> {
    most("lens conditions", lens.len(), 4)?;
    lens.iter().try_for_each(|l| {
        if l.column.is_empty() {
            return Err("a lens condition names no column".into());
        }
        cap("a lens column", &l.column, 64)?;
        cap("a lens value", &l.value, NAME_MAX)?;
        let options = l.options.as_deref().unwrap_or_default();
        if l.options.is_some() && !(1..=50).contains(&options.len()) {
            return Err(format!("lens {} has {} options, 1 to 50", l.column, options.len()));
        }
        options.iter().try_for_each(|o| cap("a lens option", o, NAME_MAX))
    })
}

/// A question Iris asks at a fork that changes what she does next. The model never sends `id`:
/// serve mints it and a render carries it; the answer comes back as choice_reply, as data.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Choice {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub question: String,
    pub options: Vec<ChoiceOption>,
    /// Iris's pick, preselected for the person: exactly one label, or one or more when multi.
    pub suggested: Vec<String>,
    pub multi: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChoiceOption {
    pub label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub delta: Option<Delta>,
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub delta: Option<Delta>,
    /// The old value of a changed field; a JSON null reads as absent (ponytail: "was empty" is unsayable).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub was: Option<Value>,
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
    /// The table's title: the person sees WHICH table they write into, not only its id.
    pub title: String,
    pub op: RowOp,
    /// The row an update changes or a delete removes; an insert names none (KEAP mints the id).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub row_id: Option<String>,
    pub cells: Vec<CellChange>,
    /// Tools whose free text the model read this turn; the card head says so (operator ruling Q7).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub read_from: Vec<String>,
    /// insert_many only: the rows written after the parent, each pointing at it by `ref_key`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lines: Option<Lines>,
    /// The row is not the one the person named (local bench 2026-10-16); said in red, never refused.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub warning: Option<String>,
}

/// The line items of one insert_many card (operator ruling Q4): every line, every cell, no old.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lines {
    pub table: String,
    pub title: String,
    /// The rowRef column serve fills with the parent's id; no line carries it.
    pub ref_key: String,
    pub rows: Vec<Vec<CellChange>>,
}

/// A new DataTable under one approval (propose_table_create): what KEAP's POST /api/tables gets.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableSchemaApproval {
    pub title: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    pub columns: Vec<SchemaColumn>,
    pub visibility: Visibility,
}

/// New columns for a table the person can read (propose_column_add): `existing` is the table at the
/// card, shown read-only; serve re-reads it on approve and adds nothing if it moved.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ColumnAddApproval {
    pub table: String,
    pub title: String,
    pub existing: Vec<ExistingColumn>,
    pub columns: Vec<SchemaColumn>,
}

/// A column the table already holds, of any KEAP kind (json, file, ...): shown, never changed.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExistingColumn {
    pub key: String,
    pub label: String,
    pub kind: String,
}

/// Only private: the person owns the new table; sharing is a later step (operator 2026-10-15).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Visibility {
    Private,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SchemaColumn {
    pub key: String,
    pub label: String,
    pub kind: ColumnKind,
    #[serde(default)]
    pub required: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub options: Option<Vec<String>>,
    /// rowRef: the target table's id and title, and its column a row is shown by (KEAP refDisplay).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ref_table: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ref_title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ref_display: Option<String>,
}

/// The KEAP column kinds Iris may create; KEAP's others (json, file, vector, ...) are not hers to make.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ColumnKind {
    Text,
    Number,
    Date,
    Select,
    Boolean,
    RowRef,
}

impl ColumnKind {
    pub fn as_str(self) -> &'static str {
        match self {
            ColumnKind::Text => "text",
            ColumnKind::Number => "number",
            ColumnKind::Date => "date",
            ColumnKind::Select => "select",
            ColumnKind::Boolean => "boolean",
            ColumnKind::RowRef => "rowRef",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RowOp {
    Insert,
    Update,
    /// A parent (new, or an existing row unchanged) and its lines, under one approval.
    InsertMany,
    /// One existing row removed: every value it holds shown old -> null.
    Delete,
}

impl RowOp {
    pub fn as_str(self) -> &'static str {
        match self {
            RowOp::Insert => "insert",
            RowOp::Update => "update",
            RowOp::InsertMany => "insert_many",
            RowOp::Delete => "delete",
        }
    }
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
    use serde_json::json;

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
            items: (0..n).map(|i| ListItem { text: i.to_string(), detail: None, tone: None, delta: None }).collect(),
        })
    }

    fn card(op: RowOp, row_id: Option<&str>, old: Value) -> Component {
        Component::RowDiffApproval(RowDiffApproval {
            table: "t1".into(), title: "Todo list".into(), op, row_id: row_id.map(str::to_string),
            cells: vec![CellChange { key: "status".into(), old, new: json!("done") }], read_from: vec![], lines: None, warning: None,
        })
    }

    #[test]
    fn check_holds_an_approval_to_its_op() {
        assert!(card(RowOp::Update, Some("r1"), json!("open")).check().is_ok());
        assert!(card(RowOp::Update, Some("r1"), Value::Null).check().is_ok(), "an update may fill an empty cell");
        assert!(card(RowOp::Insert, None, Value::Null).check().is_ok());
        assert_eq!(card(RowOp::Update, None, Value::Null).check(), Err("an update names its row".into()));
        assert_eq!(card(RowOp::Update, Some(""), Value::Null).check(), Err("an update names its row".into()));
        assert_eq!(card(RowOp::Insert, Some("r1"), Value::Null).check(), Err("an insert names no row; KEAP mints it".into()));
        assert_eq!(card(RowOp::Insert, None, json!("open")).check(), Err("an insert has no old value".into()));
        let Component::RowDiffApproval(mut d) = card(RowOp::Insert, None, Value::Null) else { unreachable!() };
        d.cells.clear();
        assert_eq!(Component::RowDiffApproval(d).check(), Err("an approval changes at least one cell".into()));
    }

    #[test]
    fn a_delete_card_names_its_row_and_shows_every_value_going() {
        let gone = |row_id: Option<&str>, old: Value, new: Value| Component::RowDiffApproval(RowDiffApproval {
            table: "t1".into(), title: "Todo list".into(), op: RowOp::Delete, row_id: row_id.map(str::to_string),
            cells: vec![CellChange { key: "status".into(), old, new }], read_from: vec![], lines: None, warning: None,
        });
        assert!(gone(Some("r1"), json!("open"), Value::Null).check().is_ok());
        assert_eq!(serde_json::to_value(gone(Some("r1"), json!("open"), Value::Null)).unwrap()["props"]["op"], "delete");
        assert_eq!(gone(None, json!("open"), Value::Null).check(), Err("a delete names its row".into()));
        assert_eq!(gone(Some(""), json!("open"), Value::Null).check(), Err("a delete names its row".into()));
        assert_eq!(gone(Some("r1"), json!("open"), json!("x")).check(), Err("a delete leaves every cell empty".into()));
        assert_eq!(gone(Some("r1"), Value::Null, Value::Null).check(), Err("a delete shows each value it removes".into()));
    }

    fn col(key: &str, kind: ColumnKind) -> SchemaColumn {
        SchemaColumn { key: key.into(), label: key.to_uppercase(), kind, required: false, options: None, ref_table: None, ref_title: None, ref_display: None }
    }

    fn new_table(columns: Vec<SchemaColumn>) -> Component {
        Component::TableSchemaApproval(TableSchemaApproval { title: "Expenses".into(), description: None, columns, visibility: Visibility::Private })
    }

    #[test]
    fn a_table_card_holds_what_keap_creates_and_no_more() {
        let select = SchemaColumn { options: Some(vec!["travel".into(), "food".into()]), ..col("category", ColumnKind::Select) };
        let link = SchemaColumn { ref_table: Some("t-trips".into()), ref_title: Some("Trips".into()), ..col("trip", ColumnKind::RowRef) };
        let ok = new_table(vec![col("item", ColumnKind::Text), col("paid_on", ColumnKind::Date), select.clone(), link.clone()]);
        assert!(ok.check().is_ok(), "{:?}", ok.check());
        let v = serde_json::to_value(&ok).unwrap();
        assert_eq!((v["kind"].as_str(), v["props"]["visibility"].as_str(), v["props"]["columns"][3]["kind"].as_str()),
                   (Some("table_schema_approval"), Some("private"), Some("rowRef")));
        assert!(serde_json::from_value::<Component>(json!({"kind": "table_schema_approval", "props": {"title": "x", "columns": [],
            "visibility": "shared"}})).is_err(), "a create is private; sharing is a later step");
        let refused = |c: Vec<SchemaColumn>| new_table(c).check().unwrap_err();
        assert_eq!(refused(vec![]), "a table has 1 to 30 columns, not 0");
        assert_eq!(refused((0..31).map(|i| col(&format!("c{i}"), ColumnKind::Text)).collect()), "a table has 1 to 30 columns, not 31");
        assert!(refused(vec![col("Item", ColumnKind::Text)]).contains("snake_case"));
        assert!(refused(vec![col("2nd", ColumnKind::Text)]).contains("snake_case"));
        assert!(refused(vec![col("item", ColumnKind::Text), col("item", ColumnKind::Number)]).contains("twice"));
        assert!(refused(vec![col("category", ColumnKind::Select)]).contains("1 to 50 options"));
        assert!(refused(vec![SchemaColumn { options: Some(vec![]), ..select.clone() }]).contains("1 to 50 options"));
        assert!(refused(vec![SchemaColumn { options: Some(vec!["a".into(), "a".into()]), ..select.clone() }]).contains("twice"));
        assert!(refused(vec![SchemaColumn { options: Some(vec!["a".into()]), ..col("item", ColumnKind::Text) }]).contains("only a select"));
        assert!(refused(vec![SchemaColumn { ref_table: None, ..link.clone() }]).contains("names the table"));
        assert!(refused(vec![SchemaColumn { ref_table: Some("t".into()), ..col("item", ColumnKind::Text) }]).contains("only a rowRef"));
        assert!(refused(vec![SchemaColumn { label: " ".into(), ..col("item", ColumnKind::Text) }]).contains("label"));
        let Component::TableSchemaApproval(mut t) = ok else { unreachable!() };
        t.title = " ".into();
        assert_eq!(Component::TableSchemaApproval(t).check(), Err("a new table has a title".into()));
    }

    fn has(key: &str, kind: &str) -> ExistingColumn {
        ExistingColumn { key: key.into(), label: key.to_uppercase(), kind: kind.into() }
    }

    fn add(columns: Vec<SchemaColumn>) -> Component {
        Component::ColumnAddApproval(ColumnAddApproval { table: "expenses".into(), title: "Expenses".into(),
                                                         existing: vec![has("item", "text"), has("blob", "json")], columns })
    }

    #[test]
    fn a_column_add_card_holds_new_optional_columns_beside_the_existing() {
        let ok = add(vec![col("paid_on", ColumnKind::Date), SchemaColumn { options: Some(vec!["a".into()]), ..col("category", ColumnKind::Select) }]);
        assert!(ok.check().is_ok(), "{:?}", ok.check());
        let v = serde_json::to_value(&ok).unwrap();
        assert_eq!((v["kind"].as_str(), v["props"]["existing"][1]["kind"].as_str(), v["props"]["columns"][0]["key"].as_str()),
                   (Some("column_add_approval"), Some("json"), Some("paid_on")));
        let refused = |c: Vec<SchemaColumn>| add(c).check().unwrap_err();
        assert_eq!(refused(vec![]), "a column add has 1 to 30 new columns, not 0");
        assert_eq!(refused((0..31).map(|i| col(&format!("c{i}"), ColumnKind::Text)).collect()), "a column add has 1 to 30 new columns, not 31");
        assert_eq!(refused(vec![col("item", ColumnKind::Number)]), "table Expenses already has a column item");
        assert!(refused(vec![col("note", ColumnKind::Text), col("note", ColumnKind::Text)]).contains("twice"));
        assert!(refused(vec![SchemaColumn { required: true, ..col("note", ColumnKind::Text) }]).contains("optional"));
        assert!(refused(vec![col("Note", ColumnKind::Text)]).contains("snake_case"));
        let Component::ColumnAddApproval(mut t) = ok else { unreachable!() };
        t.existing = (0..119).map(|i| has(&format!("e{i}"), "text")).collect();
        assert!(Component::ColumnAddApproval(t.clone()).check().unwrap_err().contains("at most 120"));
        t.table = String::new();
        assert_eq!(Component::ColumnAddApproval(t).check(), Err("a column add names its table".into()));
    }

    #[test]
    fn an_insert_card_carries_no_row_id_and_keeps_a_null_old() {
        let v = serde_json::to_value(card(RowOp::Insert, None, Value::Null)).unwrap();
        assert_eq!(v["props"]["op"], "insert");
        assert!(v["props"].get("row_id").is_none() && v["props"].get("read_from").is_none());
        assert_eq!(v["props"]["cells"][0].get("old"), Some(&Value::Null), "old stays a plain null, never dropped");
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
        use crate::wire::{check_spec, decode_to_shell, decode_to_thalamus, ToShell, ToThalamus};
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
            // serve::widget runs check_spec first, so the same spec as a widget is refused the same way.
            let Ok(ToThalamus::Widget { spec, .. }) = decode_to_thalamus(&widget) else { panic!("{widget}") };
            assert!(check_spec(&spec).is_err_and(|e| e.contains(want)), "the same spec as a widget: {pin}");
        }
    }

    const CHOICE_ID: &str = "3c9e1d2f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";

    /// Iris's question at a fork (iris-genui-forms step 1); `extra` is spliced into props.
    fn choice(options: &str, suggested: &str, extra: &str) -> Component {
        decode(&format!(r#"{{"kind":"choice","props":{{"question":"Which table should I chart?","options":[{options}],"suggested":[{suggested}],"multi":false{extra}}}}}"#))
    }

    fn opts(n: usize) -> String {
        (0..n).map(|i| format!(r#"{{"label":"o{i}"}}"#)).collect::<Vec<_>>().join(",")
    }

    #[test]
    fn a_choice_is_a_question_and_two_to_six_options() {
        let ok = choice(r#"{"label":"todos","note":"the open work"},{"label":"expenses"}"#, r#""todos""#, "");
        assert_eq!(ok.check(), Ok(()), "the model's choice carries no id");
        assert_eq!(choice(&opts(6), r#""o0""#, "").check(), Ok(()));
        let multi = decode(&format!(r#"{{"kind":"choice","props":{{"question":"Which?","options":[{}],"suggested":["o0","o2"],"multi":true}}}}"#, opts(3)));
        assert_eq!(multi.check(), Ok(()), "multi may suggest more than one");
        assert_eq!(choice(&opts(2), r#""o0""#, &format!(r#","id":"{CHOICE_ID}""#)).check(), Ok(()));
    }

    #[test]
    fn check_rejects_a_choice_over_its_caps() {
        for n in [0, 1, 7] {
            assert_eq!(choice(&opts(n), r#""o0""#, "").check(), Err(format!("choice options: {n}, 2 to 6")), "{n}");
        }
        assert_eq!(choice(r#"{"label":"Todos"},{"label":" todos "}"#, r#""Todos""#, "").check(),
                   Err(r#"choice option " todos " twice (case and spaces aside)"#.into()));
        assert_eq!(choice(r#"{"label":" "},{"label":"b"}"#, r#""b""#, "").check(), Err("a choice option label is empty".into()));
        assert_eq!(choice(&format!(r#"{{"label":"{}"}},{{"label":"b"}}"#, "l".repeat(61)), r#""b""#, "").check(),
                   Err("a choice option label is over 60 chars".into()));
        assert_eq!(choice(&format!(r#"{{"label":"a","note":"{}"}},{{"label":"b"}}"#, "n".repeat(201)), r#""b""#, "").check(),
                   Err("a choice option note is over 200 chars".into()));
        assert_eq!(choice(&opts(2), r#""o9""#, "").check(), Err(r#"suggested "o9" is not an option"#.into()));
        for (s, n) in [("", 0), (r#""o0","o1""#, 2)] {
            assert_eq!(choice(&opts(2), s, "").check(), Err(format!("a choice suggests exactly 1 option, not {n}; multi suggests 1 or more")), "{s}");
        }
        let multi = |s: &str| decode(&format!(r#"{{"kind":"choice","props":{{"question":"Which?","options":[{}],"suggested":[{s}],"multi":true}}}}"#, opts(3)));
        for (s, n) in [("", 0), (r#""o0","o0""#, 2)] {
            assert_eq!(multi(s).check(), Err(format!("a choice suggests exactly 1 option, not {n}; multi suggests 1 or more")), "multi {s}");
        }
        assert_eq!(choice(&opts(2), r#""o0""#, r#","id":"latest""#).check(), Err(r#"choice id is not a lowercase uuid: "latest""#.into()));
        let q =|q: &str| decode(&format!(r#"{{"kind":"choice","props":{{"question":{},"options":[{}],"suggested":["o0"],"multi":false}}}}"#,
                                          serde_json::to_string(q).unwrap(), opts(2)));
        assert_eq!(q(&vec!["w"; 15].join(" ")).check(), Ok(()));
        assert_eq!(q(&vec!["w"; 16].join(" ")).check(), Err("a choice question is over 15 words".into()));
        assert_eq!(q(&"q".repeat(121)).check(), Err("a choice question is over 120 chars".into()));
        assert_eq!(q("  ").check(), Err("a choice asks no question".into()));
    }

    /// A reply is decoded to at most 6 labels of at most 60 chars, before serve looks at the choice.
    #[test]
    fn decode_caps_a_choice_reply() {
        use crate::wire::decode_to_thalamus;
        let s = "0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b";
        let reply = |picked: Vec<String>| decode_to_thalamus(&serde_json::json!({"t": "choice_reply", "session": s, "choice": CHOICE_ID, "picked": picked}).to_string());
        assert!(reply(vec!["l".repeat(60)]).is_ok());
        assert_eq!(reply(vec!["l".repeat(61)]).err(), Some("a picked label is over 60 chars".into()));
        assert!(reply((0..6).map(|i| format!("o{i}")).collect()).is_ok());
        assert_eq!(reply((0..7).map(|i| format!("o{i}")).collect()).err(), Some("a choice reply picks at most 6 labels, not 7".into()));
    }

    /// serve mints the id: a render without one, or a choice in an approval, is refused.
    #[test]
    fn a_choice_render_carries_the_minted_id_and_never_rides_an_approval() {
        use crate::wire::{decode_to_shell, ToShell};
        let s = "0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b";
        let c = |extra: &str| serde_json::to_string(&choice(&opts(2), r#""o0""#, extra)).unwrap();
        let with = c(&format!(r#","id":"{CHOICE_ID}""#));
        assert!(matches!(decode_to_shell(&format!(r#"{{"t":"render","session":"{s}","component":{with}}}"#)), ToShell::Render { .. }));
        for (line, want) in [
            (format!(r#"{{"t":"render","session":"{s}","component":{}}}"#, c("")), "a choice the thalamus sends carries the id it minted"),
            (format!(r#"{{"t":"approval_request","session":"{s}","approval":"{FORM_ID}","component":{with}}}"#), "a choice is asked in a render, never in an approval"),
        ] {
            match decode_to_shell(&line) {
                ToShell::Refused { reason, .. } => assert!(reason.contains(want), "{reason}"),
                m => panic!("accepted: {m:?}"),
            }
        }
    }

    // --- iris-genui-change-markers: what an action would add, remove or change ---

    #[test]
    fn a_tree_list_and_record_may_mark_a_delta() {
        let tree = r#"{"kind":"tree","props":{"nodes":[{"label":"nOS","delta":"changed","children":[
            {"label":"pupil","delta":"added","children":[{"label":"eye"},{"label":"lid","delta":"added"}]},
            {"label":"keak","delta":"removed","children":[{"label":"old"}]},{"label":"wing"}]}]}}"#;
        assert_eq!(decode(tree).check(), Ok(()), "a child may restate its parent's state, or say none");
        let list = r#"{"kind":"list","props":{"ordered":false,"items":[{"text":"a","delta":"added"},{"text":"b","delta":"removed"},{"text":"c","delta":"changed"},{"text":"d"}]}}"#;
        assert_eq!(decode(list).check(), Ok(()));
        let record = r#"{"kind":"record","props":{"fields":[{"key":"status","value":"active","delta":"changed","was":"draft"},
            {"key":"owner","value":"iris","delta":"added"},{"key":"lane","value":"x","delta":"changed"}]}}"#;
        assert_eq!(decode(record).check(), Ok(()), "was is optional on a changed field");
        let back = serde_json::to_string(&decode(record)).unwrap();
        assert!(back.contains(r#""delta":"changed","was":"draft""#), "{back}");
        assert!(!serde_json::to_string(&decode(r#"{"kind":"list","props":{"ordered":false,"items":[{"text":"d"}]}}"#)).unwrap().contains("delta"),
                "no delta is not said on the wire");
    }

    #[test]
    fn check_rejects_a_child_that_contradicts_an_added_or_removed_parent() {
        let under = |parent: &str, child: &str| decode(&format!(
            r#"{{"kind":"tree","props":{{"nodes":[{{"label":"root","delta":"{parent}","children":[{{"label":"mid","children":[{{"label":"leaf","delta":"{child}"}}]}}]}}]}}}}"#));
        for (p, c) in [("removed", "added"), ("removed", "changed"), ("added", "removed"), ("added", "changed")] {
            assert_eq!(under(p, c).check(), Err(format!(r#"tree node "leaf" is {c} under a {p} parent"#)), "{p}/{c}");
        }
        for c in ["added", "removed", "changed"] {
            assert_eq!(under("changed", c).check(), Ok(()), "a changed parent passes nothing down: {c}");
        }
    }

    #[test]
    fn check_rejects_a_was_on_a_field_that_did_not_change() {
        let field = |extra: &str| decode(&format!(r#"{{"kind":"record","props":{{"fields":[{{"key":"status","value":"active"{extra}}}]}}}}"#));
        for extra in [r#","was":"draft""#, r#","delta":"added","was":"draft""#, r#","delta":"removed","was":"draft""#] {
            assert_eq!(field(extra).check(), Err("record field status: was is only on a changed field".into()), "{extra}");
        }
        assert_eq!(field(&format!(r#","delta":"changed","was":"{}""#, "w".repeat(4001))).check(), Err("a record was is over 4000 chars".into()));
        assert!(serde_json::from_str::<Component>(r#"{"kind":"list","props":{"ordered":false,"items":[{"text":"a","delta":"moved"}]}}"#).is_err(),
                "a delta is added, removed or changed");
    }

    // --- iris-genui-sequence: who sends what to whom, in order ---

    /// An approval's path; `steps` is spliced in after the participants.
    fn sequence(participants: &str, steps: &str) -> Component {
        decode(&format!(r#"{{"kind":"sequence","props":{{"title":"An approval","participants":[{participants}],"steps":[{steps}]}}}}"#))
    }

    const PEOPLE: &str = r#""pupil","thalamus","KEAP""#;

    fn names(n: usize) -> String {
        (0..n).map(|i| format!(r#""p{i}""#)).collect::<Vec<_>>().join(",")
    }

    #[test]
    fn a_sequence_is_participants_and_steps_of_three_shapes() {
        let ok = sequence(PEOPLE, r#"{"phase":"propose"},{"from":"pupil","to":"thalamus","text":"close the row"},
            {"from":"KEAP","to":"thalamus","text":"1 row","dashed":true},{"note":"the person decides","over":["pupil"]},
            {"note":"in the ledger","over":["thalamus","KEAP"]},{"from":"thalamus","to":"thalamus","text":"check caps"}"#);
        assert_eq!(ok.check(), Ok(()), "a message to itself is a step");
        let back = serde_json::to_string(&ok).unwrap();
        assert!(back.contains(r#"{"from":"KEAP","to":"thalamus","text":"1 row","dashed":true}"#) && back.contains(r#"{"phase":"propose"}"#), "{back}");
        assert!(!back.contains(r#""dashed":false"#), "a solid message says no dashed: {back}");
        assert_eq!(sequence(&names(8), &(0..40).map(|i| format!(r#"{{"from":"p{}","to":"p{}","text":"m"}}"#, i % 8, (i + 1) % 8)).collect::<Vec<_>>().join(",")).check(), Ok(()),
                   "8 participants and 40 steps is the cap, not over it");
        assert!(serde_json::from_str::<Component>(&serde_json::to_string(&ok).unwrap().replace(r#""phase":"propose""#, r#""phase":"propose","approve":true"#)).is_err(),
                "a step is closed: an unknown field is refused");
    }

    #[test]
    fn check_rejects_a_sequence_over_its_caps() {
        let step = r#"{"from":"p0","to":"p1","text":"m"}"#;
        for n in [0, 1, 9] {
            assert_eq!(sequence(&names(n), step).check(), Err(format!("sequence participants: {n}, 2 to 8")), "{n}");
        }
        assert_eq!(sequence(r#""p0","p1","p0""#, step).check(), Err(r#"sequence participant "p0" twice"#.into()));
        assert_eq!(sequence(r#""p0"," ""#, step).check(), Err("a sequence participant is empty".into()));
        assert_eq!(sequence(&format!(r#""p0","{}""#, "p".repeat(41)), step).check(), Err("a sequence participant is over 40 chars".into()));
        assert_eq!(sequence(&names(2), "").check(), Err("a sequence has no steps".into()));
        assert_eq!(sequence(&names(2), &vec![step; 41].join(",")).check(), Err("sequence steps: 41, at most 40".into()));
        assert_eq!(sequence(&names(2), &format!(r#"{{"from":"p0","to":"p1","text":"{}"}}"#, "t".repeat(121))).check(),
                   Err("a sequence message is over 120 chars".into()));
        assert_eq!(sequence(&names(2), &format!(r#"{{"note":"{}","over":["p0"]}}"#, "n".repeat(201))).check(),
                   Err("a sequence note is over 200 chars".into()));
        assert_eq!(sequence(&names(2), &format!(r#"{{"phase":"{}"}}"#, "f".repeat(61))).check(), Err("a sequence phase is over 60 chars".into()));
        assert_eq!(sequence(&names(2), &format!(r#"{step},{{"phase":"{}"}}"#, "f".repeat(60))).check(), Ok(()));
        let title = decode(&format!(r#"{{"kind":"sequence","props":{{"title":"{}","participants":[{}],"steps":[{step}]}}}}"#, "t".repeat(121), names(2)));
        assert_eq!(title.check(), Err("title is over 120 chars".into()));
    }

    #[test]
    fn check_rejects_a_sequence_step_naming_no_participant() {
        assert_eq!(sequence(PEOPLE, r#"{"from":"pupil","to":"ghost","text":"m"}"#).check(),
                   Err(r#"sequence step 1: pupil -> ghost names no participant "ghost""#.into()));
        assert_eq!(sequence(PEOPLE, r#"{"phase":"p"},{"from":"Pupil","to":"KEAP","text":"m"}"#).check(),
                   Err(r#"sequence step 2: Pupil -> KEAP names no participant "Pupil""#.into()), "a name is matched exactly");
        assert_eq!(sequence(PEOPLE, r#"{"note":"n","over":["pupil","ghost"]}"#).check(),
                   Err(r#"sequence step 1: a note over "ghost" names no participant"#.into()));
        for over in ["", r#""pupil","thalamus","KEAP""#] {
            let n = if over.is_empty() { 0 } else { 3 };
            assert_eq!(sequence(PEOPLE, &format!(r#"{{"note":"n","over":[{over}]}}"#)).check(),
                       Err(format!("sequence step 1: a note is over {n} participants, 1 to 2")), "{over}");
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
