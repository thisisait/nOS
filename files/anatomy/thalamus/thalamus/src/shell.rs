//! Bare `thalamus`: the person's shell. It holds no secret and opens no ledger; it sends
//! what the person typed or pressed, and renders only the closed component vocabulary.
//! Whatever it cannot decode is shown as a refusal (decode_to_shell), never dropped.

use nos_contract::renderers::{Choice, Component, Dendrogram, Delta, KnowledgeTree, RunStatus, LensOp, RowOp, SchemaColumn, Step, Tone, TreeNode, WhenOp};
use nos_contract::wire::{decode_to_shell, encode, ControlView, Decision, ModelOption, Scope, ToShell, ToThalamus, WidgetSpec};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Frame;
use serde_json::Value;
use std::cell::Cell;
use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

const MAX_LINE: u64 = 1 << 20;
const COL: usize = 24;
const KEYS: &str = "Enter send · F2 /inbox · F3 /approvals · F4 /red · Ctrl-C quit";

#[derive(Default)]
pub struct App {
    pub session: Option<String>,
    pub lines: Vec<Line<'static>>,
    pub input: String,
    /// Approvals waiting for y or n, oldest first, with their lines; only the first is
    /// shown and decided. While any waits, no turn is sent.
    pub pending: VecDeque<(String, Vec<Line<'static>>)>,
    /// Whether the last frame showed the whole first approval; y needs it.
    shown_whole: Cell<bool>,
    /// Choices asked and not yet answered, as (#n, session, choice); /choose answers the
    /// latest, /choose #n that one. `asked` numbers them, never reused in a run.
    choices: Vec<(usize, String, Choice)>,
    asked: usize,
    /// Whom the person works for, as serve said it (working_for); None is no wall.
    scope: Option<String>,
    /// The models serve last offered (model_options); /model <n> picks the n-th.
    models: Vec<ModelOption>,
}

/// Hard-wraps to `w` columns, so no part of a value is ever cut off the screen.
fn wrap(lines: &[Line<'static>], w: usize) -> Vec<Line<'static>> {
    let mut out = Vec::new();
    for l in lines {
        let style = l.spans.first().map_or(l.style, |s| l.style.patch(s.style));
        let (mut row, mut used) = (String::new(), 0);
        for c in l.spans.iter().flat_map(|s| s.content.chars()) {
            let c = if c.is_control() { '\u{fffd}' } else { c };
            let cw = Span::raw(c.to_string()).width();
            if used + cw > w.max(1) && !row.is_empty() {
                out.push(Line::styled(std::mem::take(&mut row), style));
                used = 0;
            }
            row.push(c);
            used += cw;
        }
        out.push(Line::styled(row, style));
    }
    out
}

/// The last lines of `lines` that fit `area`, wrapped.
fn tail(f: &mut Frame, lines: &[Line<'static>], area: Rect) {
    let all = wrap(lines, area.width as usize);
    let skip = all.len().saturating_sub(area.height as usize);
    f.render_widget(Paragraph::new(all[skip..].to_vec()), area);
}

fn head(s: String) -> Line<'static> {
    Line::styled(s, Style::new().add_modifier(Modifier::BOLD))
}

fn warn(s: String) -> Line<'static> {
    Line::styled(s, Style::new().fg(Color::Red))
}

fn cell(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        v => v.to_string(),
    }
}

/// A diff side: an empty cell must not look like an empty string.
fn shown(v: &Value) -> String {
    if v.is_null() { "(empty)".into() } else { v.to_string() }
}

fn fit(s: &str, w: usize) -> String {
    let s = s.replace(['\n', '\r', '\t'], " ");
    if s.chars().count() <= w { format!("{s:w$}") } else { s.chars().take(w - 1).chain(['…']).collect() }
}

/// A cell that fits the column stays padded. A longer one is kept whole; `wrap` breaks it.
fn cell_col(s: &str) -> String {
    let s = s.replace(['\n', '\r', '\t'], " ");
    if s.chars().count() <= COL { format!("{s:COL$}") } else { s }
}

/// One component as plain lines: the same text in the terminal and in its snapshot.
/// A line's first column: + - ~ for what an action would do to it, a space when nothing.
fn marked(d: Option<Delta>) -> char {
    d.map_or(' ', Delta::mark)
}

/// One column of a table or column card: key (label): kind, required, options, where a rowRef points.
fn column_said(c: &SchemaColumn) -> String {
    let mut s = format!("{} ({}): {}", c.key, c.label, c.kind.as_str());
    if c.required {
        s += ", required";
    }
    if let Some(o) = &c.options {
        s += &format!(" of {}", o.join(", "));
    }
    if let Some(r) = &c.ref_table {
        s += &format!(" -> {} ({r})", c.ref_title.as_deref().unwrap_or(r));
    }
    if let Some(d) = &c.ref_display {
        s += &format!(", shown by {d}");
    }
    s
}

pub fn component_lines(c: &Component) -> Vec<Line<'static>> {
    let mut out = Vec::new();
    match c {
        Component::TableResults(t) => {
            let how = if t.projected { "semantic" } else { "substring match, not semantic" };
            out.push(head(format!("{} — {} of {} matched ({} rows) · {how}", t.name, t.rows.len(), t.matched, t.total)));
            out.push(Line::styled(format!("  {}", t.query), Style::new().fg(Color::DarkGray)));
            let cols: Vec<&str> = std::iter::once("__id").chain(t.columns.iter().map(String::as_str)).collect();
            out.push(Line::from(cols.iter().map(|c| fit(c, COL)).collect::<Vec<_>>().join(" ").trim_end().to_string()));
            for r in &t.rows {
                let vals = std::iter::once(r.__id.clone())
                    .chain(t.columns.iter().map(|k| r.cells.get(k).map(cell).unwrap_or_default()));
                out.push(Line::from(vals.map(|v| cell_col(&v)).collect::<Vec<_>>().join(" ").trim_end().to_string()));
            }
        }
        Component::RowDiffApproval(d) => {
            let what = match &d.row_id {
                Some(row) => format!("{} {} ({}) / {row}", d.op.as_str(), d.title, d.table),
                None => format!("{} a new row in {} ({})", d.op.as_str(), d.title, d.table),
            };
            out.push(head(format!("{what} — nothing is written unless you approve")));
            out.extend(d.warning.iter().map(|w| warn(format!("  ! {w}"))));
            if d.op == RowOp::Delete {
                out.push(warn("  approve deletes the whole row: every value below is gone".into()));
            }
            if !d.read_from.is_empty() {
                out.push(warn(format!("  contains text from {}", d.read_from.join(", "))));
            }
            for ch in &d.cells {
                // An existing parent is shown as it is; its lines are what is written.
                out.push(Line::from(match (&d.row_id, d.op) {
                    (Some(_), RowOp::InsertMany) => format!("  {}: {} (unchanged)", ch.key, shown(&ch.new)),
                    (_, RowOp::Delete) => format!("  {}: {} -> (deleted)", ch.key, shown(&ch.old)),
                    _ => format!("  {}: {} -> {}", ch.key, shown(&ch.old), shown(&ch.new)),
                }));
            }
            if let Some(l) = &d.lines {
                for (i, row) in l.rows.iter().enumerate() {
                    out.push(head(format!("  + line {} of {} in {} ({}), its {} -> the row above", i + 1, l.rows.len(), l.title, l.table, l.ref_key)));
                    out.extend(row.iter().map(|ch| Line::from(format!("    {}: {} -> {}", ch.key, shown(&ch.old), shown(&ch.new)))));
                }
            }
        }
        Component::TableSchemaApproval(t) => {
            out.push(head(format!("create table {}, private to you — nothing is created unless you approve", t.title)));
            out.extend(t.description.iter().map(|d| Line::from(format!("  {d}"))));
            out.extend(t.columns.iter().map(|c| Line::from(format!("  {}", column_said(c)))));
        }
        Component::ColumnAddApproval(t) => {
            out.push(head(format!("add columns to {} ({}) — nothing is added unless you approve", t.title, t.table)));
            out.extend(t.existing.iter().map(|c| Line::from(format!("  has {} ({}): {}", c.key, c.label, c.kind))));
            out.extend(t.columns.iter().map(|c| Line::from(format!("  + {}", column_said(c)))));
            out.push(Line::from("  existing rows get no value in the new columns"));
        }
        Component::InboxList(i) => {
            out.push(head(format!("inbox — {} waiting", i.items.len())));
            for x in &i.items {
                out.push(Line::from(format!("  {:10} {}  {}  ({})", x.source, fit(&x.title, 40).trim_end(), x.created_at, x.id)));
            }
            out.extend(i.refused.iter().map(|r| warn(format!("  ? {r}"))));
        }
        Component::ApprovalsList(a) => {
            out.push(head(format!("{} awaiting you", a.items.len())));
            for x in &a.items {
                out.push(Line::from(format!("  {:9} {:8} {:>4}  {}", x.kind, x.severity.to_uppercase(), x.age, x.what)));
                let note = x.note.as_deref().map(|n| format!(" · {n}")).unwrap_or_default();
                out.push(Line::from(format!("  {:25}{}{note}", "", x.where_)));
            }
            out.extend(a.unknown.iter().map(|u| warn(format!("  ? source unreadable, so its state is UNKNOWN not empty: {u}"))));
        }
        Component::RedStatus(r) => {
            out.push(head(if r.red_count == 0 { "nothing red".into() } else { format!("{} red", r.red_count) }));
            out.extend(r.reds.iter().map(|x| warn(format!("  ✗ {x}"))));
            if r.hold_count > 0 {
                out.push(Line::from(format!("{} on hold (intentional)", r.hold_count)));
                out.extend(r.holds.iter().map(|x| Line::from(format!("  ⏸ {x}"))));
            }
        }
        // Raw lines: the terminal draws no markup, so the markup is the honest text.
        Component::Markdown(m) => out.extend(m.text.lines().map(|l| Line::from(l.to_string()))),
        Component::Table(t) => {
            out.extend(t.title.clone().map(head));
            out.push(Line::from(t.columns.iter().map(|c| fit(c, COL)).collect::<Vec<_>>().join(" ").trim_end().to_string()));
            for r in &t.rows {
                out.push(Line::from(r.iter().map(|v| cell_col(&cell(v))).collect::<Vec<_>>().join(" ").trim_end().to_string()));
            }
        }
        Component::List(l) => {
            out.extend(l.title.clone().map(head));
            for (i, x) in l.items.iter().enumerate() {
                let mark = if l.ordered { format!("{}.", i + 1) } else { "-".into() };
                let tone = x.tone.map(|t| format!("[{}] ", cell(&serde_json::to_value(t).unwrap_or_default()))).unwrap_or_default();
                let detail = x.detail.as_deref().map(|d| format!(" — {d}")).unwrap_or_default();
                let line = format!("{} {mark} {tone}{}{detail}", marked(x.delta), x.text);
                out.push(if matches!(x.tone, Some(Tone::Warn | Tone::Bad)) { warn(line) } else { Line::from(line) });
            }
        }
        Component::Record(r) => {
            out.extend(r.title.clone().map(head));
            for f in &r.fields {
                let was = f.was.as_ref().map(|w| format!("{} -> ", cell(w))).unwrap_or_default();
                out.push(Line::from(format!("{} {}: {was}{}", marked(f.delta), f.key, cell(&f.value))));
            }
        }
        // A terminal draws no chart; every value is said as text.
        Component::Chart(c) => {
            let kind = cell(&serde_json::to_value(c.chart).unwrap_or_default());
            let axis = cell(&serde_json::to_value(c.x).unwrap_or_default());
            let title = c.title.as_deref().map(|t| format!(" {t}")).unwrap_or_default();
            out.push(head(format!("{kind} chart{title}: {} series over {axis} x, not drawn here", c.series.len())));
            for s in &c.series {
                let pts: Vec<String> = s.points.iter().map(|(x, y)| format!("{x}={y}")).collect();
                let pts = if pts.is_empty() { "(no rows yet)".to_string() } else { pts.join(", ") };
                out.push(Line::from(format!("  {}: {pts}", s.name)));
            }
        }
        // A limb that writes on the face's screen: the limb, its own line, every param.
        Component::ActionApproval(a) => {
            out.push(head(format!("{}.{} on the face — nothing is done unless you approve", a.app, a.action)));
            out.push(Line::from(format!("  {}", a.says)));
            out.extend(a.params.iter().map(|(k, v)| Line::from(format!("  {k}: {}", shown(v)))));
        }
        // The number serve computed, its change in words, and what it totalled.
        Component::Kpi(k) => {
            let unit = k.unit.as_deref().map(|u| format!(" {u}")).unwrap_or_default();
            out.push(head(format!("{}: {}{unit}", k.title, k.value)));
            if let Some(d) = k.delta {
                let word = if d > 0.0 { "up" } else if d < 0.0 { "down" } else { "unchanged" };
                let label = k.delta_label.as_deref().map(|l| format!(" {l}")).unwrap_or_default();
                out.push(Line::from(format!("  {word} {}{label}", d.abs())));
            }
            out.extend(k.source.as_ref().map(|s| Line::from(format!("  from {s}"))));
        }
        Component::Tree(t) => {
            out.extend(t.title.clone().map(head));
            fn walk(out: &mut Vec<Line<'static>>, n: &TreeNode, depth: usize, parent: Option<Delta>) {
                let note = n.note.as_deref().map(|d| format!(" — {d}")).unwrap_or_default();
                let delta = Delta::inherit(n.delta, parent);
                out.push(Line::from(format!("{} {}{}{note}", marked(delta), "  ".repeat(depth - 1), n.label)));
                for c in &n.children {
                    walk(out, c, depth + 1, delta);
                }
            }
            for n in &t.nodes {
                walk(&mut out, n, 1, None);
            }
        }
        Component::Timeline(t) => {
            out.extend(t.title.clone().map(head));
            for it in &t.items {
                let note = it.note.as_deref().map(|d| format!(" — {d}")).unwrap_or_default();
                let hi = if it.hi { " hi" } else { "" };
                let until = it.until.as_deref().map(|u| format!(" → {u}")).unwrap_or_default();
                let lane = it.lane.as_deref().map(|l| format!(" [{l}]")).unwrap_or_default();
                out.push(Line::from(format!("  {}{until}  {}{note}{hi}{lane}", it.when, it.title)));
            }
        }
        // Filled in the pupil only: the terminal says what it asks, and Enter sends nothing.
        Component::Form(f) => {
            out.push(head(format!("form {} (table {}): fill it in the pupil", f.title, f.table)));
            for x in &f.fields {
                let kind = cell(&serde_json::to_value(x.kind).unwrap_or_default());
                let req = if x.required { ", required" } else { "" };
                let opts = x.options.as_ref().map(|o| format!(", options {}", o.join("|"))).unwrap_or_default();
                let pre = f.prefill.as_ref().and_then(|p| p.get(&x.key)).map(|v| format!(", prefilled {}", cell(v))).unwrap_or_default();
                let when = x.when.as_ref().map(|w| format!(", shown when {} {} {}", w.key, if w.op == WhenOp::Eq { "=" } else { "!=" }, w.value))
                    .unwrap_or_default();
                out.push(Line::from(format!("  {} ({kind}{req}{opts}{pre}{when})", x.label)));
            }
            if !f.omitted.is_empty() {
                let o: Vec<String> = f.omitted.iter().map(|o| format!("{} ({})", o.key, o.kind)).collect();
                out.push(Line::styled(format!("  not editable here: {}", o.join(", ")), Style::new().fg(Color::DarkGray)));
            }
        }
        // Placed in the pupil only: the terminal says the offer; nothing here places or runs it.
        Component::Dashboard(d) => {
            out.push(head(format!("dashboard {}: {} widgets, place it in the pupil", d.name, d.widgets.len())));
            if !d.lens.is_empty() {
                let op = |o: LensOp| match o { LensOp::Eq => "=", LensOp::Neq => "!=", LensOp::Lt => "<", LensOp::Gt => ">", LensOp::Contains => "contains" };
                let l: Vec<String> = d.lens.iter()
                    .map(|l| format!("{} {} {}", l.column, op(l.op), if l.value.is_empty() { "(unset)" } else { &l.value })).collect();
                out.push(Line::from(format!("  lens: {}", l.join("; "))));
            }
            for w in &d.widgets {
                out.push(Line::from(match &w.spec {
                    WidgetSpec::Rows(a) => format!("  rows: {} (table {})", w.title, a.get("table").map(cell).unwrap_or_default()),
                    WidgetSpec::Chart(c) => {
                        let (kind, op) = (cell(&serde_json::to_value(c.chart).unwrap_or_default()), cell(&serde_json::to_value(c.op).unwrap_or_default()));
                        let what = c.y.as_ref().map_or(op.clone(), |y| format!("{op} of {y}"));
                        format!("  chart: {} ({kind}, {what} by {}, table {})", w.title, c.x, c.query.table)
                    }
                    WidgetSpec::Form(f) => format!("  form: {} (table {})", w.title, f.table),
                    WidgetSpec::Kpi(k) => {
                        let op = cell(&serde_json::to_value(k.op).unwrap_or_default());
                        let what = k.y.as_ref().map_or(op.clone(), |y| format!("{op} of {y}"));
                        format!("  kpi: {} ({what}, table {})", w.title, k.query.table)
                    }
                    WidgetSpec::Knowledge(k) => format!("  knowledge: {} (node {})", w.title, k.node),
                }));
            }
            out.extend(d.dropped.iter().map(|x| warn(format!("  left out: {} — {}", x.title, x.why))));
        }
        // Answered here with /choose; the pupil draws radios.
        Component::Choice(c) => {
            out.push(head(format!("? {}", c.question)));
            for (i, o) in c.options.iter().enumerate() {
                let note = o.note.as_deref().map(|n| format!(" — {n}")).unwrap_or_default();
                let mark = if c.suggested.contains(&o.label) { " (suggested)" } else { "" };
                out.push(Line::from(format!("  {}. {}{note}{mark}", i + 1, o.label)));
            }
            let how = if c.multi { "/choose 1,3 (one or more)" } else { "/choose <number>" };
            out.push(Line::styled(format!("  answer with {how}"), Style::new().fg(Color::DarkGray)));
        }
        // A terminal draws no lifelines: messages as A -> B: text, notes and phases indented.
        Component::Sequence(q) => {
            out.extend(q.title.clone().map(head));
            out.push(Line::from(format!("participants: {}", q.participants.join(", "))));
            for step in &q.steps {
                out.push(Line::from(match step {
                    Step::Message { from, to, text, dashed } => format!("{from} {} {to}: {text}", if *dashed { "-->" } else { "->" }),
                    Step::Note { note, over } => format!("  note {}: {note}", over.join(", ")),
                    Step::Phase { phase } => format!("  == {phase} =="),
                }));
            }
        }
        // One indented line a node, under its parent; the focus marked, the cap's rest said.
        Component::KnowledgeTree(k) => {
            out.extend(k.title.clone().map(head));
            fn walk(k: &KnowledgeTree, parent: Option<&str>, depth: usize, out: &mut Vec<Line<'static>>) {
                for n in k.nodes.iter().filter(|n| n.parent.as_deref() == parent && depth < k.nodes.len()) {
                    let mark = if n.id == k.focus { "> " } else { "" };
                    let kids = n.child_count.map(|c| format!(" ({c} under it)")).unwrap_or_default();
                    let text = n.text.as_deref().map(|t| format!(" — {t}")).unwrap_or_default();
                    out.push(Line::from(format!("{}{mark}{} {}{kids}{text}", "  ".repeat(depth + 1), n.id, n.name)));
                    walk(k, Some(&n.id), depth + 1, out);
                }
            }
            walk(k, None, 0, &mut out);
            if k.hidden > 0 {
                out.push(Line::styled(format!("  {} more not drawn", k.hidden), Style::new().fg(Color::DarkGray)));
            }
        }
        // An agent run: one indented line a node under its parent, its status a word, the cap's rest said.
        Component::Dendrogram(d) => {
            out.extend(d.title.clone().map(head));
            fn walk(d: &Dendrogram, parent: Option<&str>, depth: usize, out: &mut Vec<Line<'static>>) {
                let word = |v: serde_json::Value| v.as_str().unwrap_or_default().to_string();
                for n in d.nodes.iter().filter(|n| n.parent.as_deref() == parent && depth < d.nodes.len()) {
                    let (kind, status) = (word(serde_json::json!(n.kind)), word(serde_json::json!(n.status)));
                    let tokens = n.tokens.map(|t| format!(" ({t} tokens)")).unwrap_or_default();
                    let note = n.note.as_deref().map(|t| format!(" — {t}")).unwrap_or_default();
                    let line = format!("{}{kind} {} [{status}]{tokens}{note}", "  ".repeat(depth + 1), n.name);
                    out.push(if n.status == RunStatus::Bad { warn(line) } else { Line::from(line) });
                    walk(d, Some(&n.id), depth + 1, out);
                }
            }
            walk(d, None, 0, &mut out);
            if d.hidden > 0 {
                out.push(Line::styled(format!("  {} more not drawn", d.hidden), Style::new().fg(Color::DarkGray)));
            }
        }
        // The tone is a word in brackets; warn and bad are drawn as warnings.
        Component::Callout(c) => {
            let tone = cell(&serde_json::to_value(c.tone).unwrap_or_default());
            let line = format!("Iris says [{tone}] {}", c.title);
            out.push(if matches!(c.tone, Tone::Warn | Tone::Bad) { warn(line) } else { head(line) });
            out.extend(c.text.lines().map(|l| Line::from(format!("  {l}"))));
        }
        // Each step's status as Iris says it (pending or active), a word, numbered in order.
        Component::Steps(p) => {
            out.extend(p.title.clone().map(head));
            for (i, x) in p.items.iter().enumerate() {
                let status = cell(&serde_json::to_value(x.status).unwrap_or_default());
                let detail = x.detail.as_deref().map(|d| format!(" — {d}")).unwrap_or_default();
                let line = format!("  {}. [{status}] {}{detail}", i + 1, x.title);
                out.push(Line::from(line));
            }
        }
        Component::Sources(x) => {
            out.push(head(x.title.clone().unwrap_or_else(|| "sources".into())));
            for i in &x.items {
                let name = i.name.as_deref().unwrap_or(&i.table);
                let note = i.note.as_deref().map(|n| format!(" — {n}")).unwrap_or_default();
                out.push(Line::from(format!("  {name} ({}) / {}{note}", i.table, i.row)));
            }
        }
        // Text the person may type next; the terminal sends nothing for them.
        Component::FollowUp(f) => {
            out.push(Line::styled("you could ask:".to_string(), Style::new().fg(Color::DarkGray)));
            out.extend(f.prompts.iter().map(|p| Line::from(format!("  > {p}"))));
        }
        // A terminal draws no diagram; every node and edge is said as text.
        Component::Graph(g) => {
            out.extend(g.title.clone().map(head));
            out.push(Line::from("nodes:"));
            for n in &g.nodes {
                let note = n.note.as_deref().map(|d| format!(" — {d}")).unwrap_or_default();
                let tone = n.tone.map(|t| format!(" [{}]", cell(&serde_json::to_value(t).unwrap_or_default()))).unwrap_or_default();
                let line = format!("  {} {}{note}{tone}", n.id, n.label);
                out.push(if matches!(n.tone, Some(Tone::Warn | Tone::Bad)) { warn(line) } else { Line::from(line) });
            }
            out.push(Line::from("edges:"));
            for e in &g.edges {
                let arrow = if e.dashed { "- ->" } else { "->" };
                let label = e.label.as_deref().map(|l| format!(" ({l})")).unwrap_or_default();
                out.push(Line::from(format!("  {} {arrow} {}{label}", e.from, e.to)));
            }
        }
    }
    out
}

impl App {
    pub fn apply(&mut self, m: ToShell) {
        match m {
            ToShell::Session { session, actor, model_uri } => {
                self.lines.push(Line::styled(format!("session {session} as {actor} ({model_uri})"), Style::new().fg(Color::DarkGray)));
                self.session = Some(session);
            }
            ToShell::Text { text, .. } => self.lines.extend(text.lines().map(|l| Line::from(format!("iris: {l}")))),
            ToShell::Render { session, component, pin } => {
                self.lines.extend(component_lines(&component));
                if let Component::Choice(c) = component {
                    self.asked += 1;
                    let n = self.asked;
                    self.lines.push(Line::styled(format!("  choice #{n}: /choose #{n} <number> answers this one"), Style::new().fg(Color::DarkGray)));
                    self.choices.push((n, session, c));
                }
                // The workspace is the pupil's; here a pin is only said.
                if pin.is_some() {
                    self.lines.push(Line::styled("(pinnable in the pupil)", Style::new().fg(Color::DarkGray)));
                }
            }
            ToShell::ApprovalRequest { approval, component, .. } => {
                let mut lines = component_lines(&component);
                // serve refuses a switch while a card waits, so the scope now is the one it was asked under.
                if let Some(s) = &self.scope {
                    lines.insert(1.min(lines.len()), warn(format!("  asked for {s}")));
                }
                self.pending.push_back((approval, lines));
            }
            ToShell::WorkingFor { scope, name, .. } => {
                self.scope = (scope != Scope::All).then(|| name.clone());
                self.lines.push(head(match scope {
                    Scope::All => "working for everything (no wall)".to_string(),
                    Scope::Personal => "working on personal data".to_string(),
                    Scope::Client(_) => format!("working for {name}"),
                }));
            }
            ToShell::ModelOptions { options, refused, .. } => {
                self.lines.push(head("models for this session; a pick takes effect on the next turn:".into()));
                for (n, o) in options.iter().enumerate() {
                    let eu = if o.transfers_outside_eu { "LEAVES THE EU" } else { "in the EU" };
                    let now = if o.current { " (current)" } else { "" };
                    self.lines.push(Line::from(format!("  {}. {} {} — {}, {eu}{now}", n + 1, o.backend, o.model, o.processor)));
                    self.lines.extend(o.warning.as_ref().map(|w| warn(format!("     {w}"))));
                }
                self.lines.extend(refused.iter().map(|r| Line::styled(format!("  not offered: {r}"), Style::new().fg(Color::DarkGray))));
                self.models = options;
            }
            ToShell::Refused { reason, widget: None } => self.lines.push(warn(format!("refused: {reason}"))),
            ToShell::Refused { reason, widget: Some(w) } => self.lines.push(warn(format!("refused (widget {w}): {reason}"))),
            // The terminal has no workspace: a widget's answer joins the scrollback under its token.
            ToShell::Widget { widget, component, .. } => {
                self.lines.push(Line::styled(format!("widget {widget}:"), Style::new().fg(Color::DarkGray)));
                self.lines.extend(component_lines(&component));
            }
            ToShell::FormResult { widget, row, .. } => self.lines.push(Line::from(format!("widget {widget}: row {row} added"))),
            ToShell::TableChanged { table, row, .. } => {
                self.lines.push(Line::styled(format!("table {table} changed (row {row})"), Style::new().fg(Color::DarkGray)));
            }
            // The pupil's eye shows it; the terminal's scrollback stays the conversation.
            ToShell::Activity { .. } => {}
            ToShell::Said { text, .. } => self.lines.push(Line::styled(format!("you: {text}"), Style::new().fg(Color::Cyan))),
            ToShell::Replay { log, open, .. } => {
                self.lines.push(head(format!("resumed: {} lines of this session", log.len())));
                for m in log {
                    match m {
                        // A decided card or an answered choice is history: drawn, never asked again.
                        ToShell::ApprovalRequest { approval, component, .. } if !open.contains(&approval) => self.lines.extend(component_lines(&component)),
                        ToShell::Render { component: c @ Component::Choice(_), .. }
                            if !matches!(&c, Component::Choice(ch) if ch.id.as_ref().is_some_and(|i| open.contains(i))) => self.lines.extend(component_lines(&c)),
                        m => self.apply(m),
                    }
                }
            }
            // The workspace is the pupil's, and so are the marks a catalogue draws.
            ToShell::Workspace { .. } | ToShell::Catalogue { .. } | ToShell::ModelState { .. } => {}
            ToShell::State(s) => self.lines.extend(crate::state::lines(&s).into_iter().map(Line::from)),
            // The terminal declares no limbs, so serve sends it no act: one that arrives is said, never done.
            ToShell::Act { app, action, .. } => self.lines.push(warn(format!("refused: an act {app}.{action}, but this shell has no limbs"))),
        }
    }

    /// The connection is gone: what waits can no longer be decided, and the person is told.
    pub fn closed(&mut self, reason: &str) {
        for (approval, _) in self.pending.drain(..) {
            self.lines.push(warn(format!("not decided, nothing written: approval {approval}")));
        }
        self.apply(ToShell::Refused { reason: reason.into(), widget: None });
    }

    /// One key; Some is the message to send. The controls answer at any time.
    pub fn key(&mut self, k: KeyEvent) -> Option<ToThalamus> {
        let control = |view| Some(ToThalamus::Control { view });
        match k.code {
            KeyCode::F(2) => return control(ControlView::Inbox),
            KeyCode::F(3) => return control(ControlView::Approvals),
            KeyCode::F(4) => return control(ControlView::RedStatus),
            _ => {}
        }
        if !self.pending.is_empty() {
            let decision = match k.code {
                KeyCode::Char('y') if self.shown_whole.get() => Decision::Approve,
                KeyCode::Char('n') => Decision::Reject,
                _ => return None,
            };
            let (approval, shown) = self.pending.pop_front()?;
            self.shown_whole.set(false);
            self.lines.extend(shown);
            self.lines.push(Line::from(format!("you: {}", if decision == Decision::Approve { "approve" } else { "reject" })));
            return Some(ToThalamus::ApprovalDecision { approval, decision, note: None });
        }
        match k.code {
            KeyCode::Char(c) if !k.modifiers.contains(KeyModifiers::CONTROL) => {
                self.input.push(c);
                None
            }
            KeyCode::Backspace => {
                self.input.pop();
                None
            }
            KeyCode::Enter => {
                let text = std::mem::take(&mut self.input).trim().to_string();
                match text.as_str() {
                    "" => None,
                    "/inbox" => control(ControlView::Inbox),
                    "/approvals" => control(ControlView::Approvals),
                    "/red" => control(ControlView::RedStatus),
                    t if t == "/choose" || t.starts_with("/choose ") => self.choose(&t["/choose".len()..]),
                    "/model" => Some(ToThalamus::ModelOptions),
                    t if t.starts_with("/model ") => {
                        let arg = t["/model".len()..].trim();
                        let picked = match arg.split_once(' ') {
                            Some((backend, model)) => Some((backend.to_string(), model.trim().to_string())),
                            None => arg.parse::<usize>().ok().and_then(|n| self.models.get(n.wrapping_sub(1)))
                                .map(|o| (o.backend.clone(), o.model.clone())),
                        };
                        if picked.is_none() {
                            self.lines.push(warn("not sent: /model lists the models; /model <n> or /model <backend> <model> picks one".into()));
                        }
                        picked.map(|(backend, model)| ToThalamus::ModelPick { backend, model })
                    }
                    t if t == "/for" || t.starts_with("/for ") => {
                        let scope = match t["/for".len()..].trim() {
                            "" => {
                                self.lines.push(warn("not sent: /for <client>, /for personal or /for all".into()));
                                return None;
                            }
                            "all" => Scope::All,
                            "personal" => Scope::Personal,
                            c => Scope::Client(c.to_string()),
                        };
                        Some(ToThalamus::WorkingFor { scope })
                    }
                    _ => {
                        self.lines.push(Line::styled(format!("you: {text}"), Style::new().fg(Color::Cyan)));
                        Some(ToThalamus::Turn { session: self.session.clone(), text })
                    }
                }
            }
            _ => None,
        }
    }
}

impl App {
    /// `/choose 2` (or `1,3` when multi) answers the latest open choice with those labels, once;
    /// `/choose #1 2` answers choice #1.
    fn choose(&mut self, arg: &str) -> Option<ToThalamus> {
        let (at, arg) = match arg.trim().strip_prefix('#') {
            None => (self.choices.len().checked_sub(1), arg),
            Some(rest) => {
                let (n, arg) = rest.split_once(' ').unwrap_or((rest, ""));
                let at = n.parse().ok().and_then(|n: usize| self.choices.iter().position(|x| x.0 == n));
                if at.is_none() {
                    self.lines.push(warn(format!("no open choice #{n}")));
                    return None;
                }
                (at, arg)
            }
        };
        let Some(at) = at else {
            self.lines.push(warn("no open choice to answer".into()));
            return None;
        };
        let c = &self.choices[at].2;
        let n = c.options.len();
        let nums: Option<Vec<usize>> = arg.split(',').map(|x| x.trim().parse().ok().filter(|i| (1..=n).contains(i))).collect();
        let ok = nums.filter(|v| (v.len() == 1 || c.multi) && v.iter().enumerate().all(|(i, x)| !v[..i].contains(x)));
        let Some(nums) = ok else {
            let how = if c.multi { format!("one or more of 1-{n}, like 1,3") } else { format!("one number, 1-{n}") };
            self.lines.push(warn(format!("not sent: /choose takes {how}")));
            return None;
        };
        let (_, session, c) = self.choices.remove(at);
        let picked: Vec<String> = nums.iter().map(|i| c.options[i - 1].label.clone()).collect();
        self.lines.push(Line::styled(format!("you: {}", picked.join(", ")), Style::new().fg(Color::Cyan)));
        Some(ToThalamus::ChoiceReply { session, choice: c.id?, picked })
    }
}

pub fn draw(f: &mut Frame, app: &App) {
    let [log, input, keys] = Layout::vertical([Constraint::Min(1), Constraint::Length(1), Constraint::Length(1)]).areas(f.area());
    let prompt = match app.pending.front() {
        None => {
            tail(f, &app.lines, log);
            let at = app.scope.as_ref().map(|s| format!("[{s}] ")).unwrap_or_default();
            Line::from(format!("{at}> {}", app.input))
        }
        // The approval is pinned from its header down; the scrollback gets what is left.
        Some((_, shown)) => {
            let diff = wrap(shown, log.width as usize);
            let whole = diff.len() <= log.height as usize;
            app.shown_whole.set(whole);
            let [top, rest] = Layout::vertical([Constraint::Length(diff.len().min(log.height as usize) as u16), Constraint::Min(0)])
                .areas(log);
            f.render_widget(Paragraph::new(diff), top);
            tail(f, &app.lines, rest);
            let of = if app.pending.len() > 1 { format!(" (1 of {})", app.pending.len()) } else { String::new() };
            let ask = if whole { format!("approve this edit{of}? y / n") }
                      else { format!("this edit{of} does not fit: enlarge the terminal, or n rejects it") };
            Line::styled(ask, Style::new().fg(Color::Yellow).add_modifier(Modifier::BOLD))
        }
    };
    f.render_widget(Paragraph::new(prompt), input);
    f.render_widget(Paragraph::new(Line::styled(KEYS, Style::new().fg(Color::DarkGray))), keys);
}

/// The shell against the thalamus socket, until Ctrl-C, Ctrl-D or the thalamus closes.
pub fn run(sock: &Path) -> Result<(), String> {
    let mut out = UnixStream::connect(sock).map_err(|e| format!("{}: {e}", sock.display()))?;
    let input = out.try_clone().map_err(|e| e.to_string())?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut r = BufReader::new(input);
        loop {
            let mut line = String::new();
            match r.by_ref().take(MAX_LINE).read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if tx.send(Some(decode_to_shell(&line))).is_err() {
                        break;
                    }
                }
            }
        }
        let _ = tx.send(None);
    });
    let mut term = ratatui::init();
    let mut app = App::default();
    let r = (|| -> std::io::Result<()> {
        loop {
            while let Ok(m) = rx.try_recv() {
                match m {
                    Some(m) => app.apply(m),
                    None => app.closed("the thalamus closed the connection"),
                }
            }
            term.draw(|f| draw(f, &app))?;
            if !event::poll(Duration::from_millis(100))? {
                continue;
            }
            let Event::Key(k) = event::read()? else { continue };
            if k.kind != KeyEventKind::Press {
                continue;
            }
            if k.modifiers.contains(KeyModifiers::CONTROL) && matches!(k.code, KeyCode::Char('c' | 'd')) {
                return Ok(());
            }
            if let Some(m) = app.key(k) {
                if let Err(e) = out.write_all(encode(&m).as_bytes()) {
                    app.apply(ToShell::Refused { reason: format!("not sent: {e}"), widget: None });
                }
            }
        }
    })();
    ratatui::restore();
    r.map_err(|e| e.to_string())
}
