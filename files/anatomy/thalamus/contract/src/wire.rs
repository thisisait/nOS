//! What crosses ~/.nos/thalamus.sock: newline-delimited JSON, tagged by `t`.
//! Spec: files/anatomy/contracts/thalamus-shell.yml; gate:
//! tests/anatomy/test_thalamus_shell_contract.py.

use crate::renderers::{Component, Dropped, SavedDashboard, When};
use crate::uid;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "t", rename_all = "snake_case", deny_unknown_fields)]
pub enum ToThalamus {
    Turn { session: Option<String>, text: String },
    ApprovalDecision { approval: String, decision: Decision, note: Option<String> },
    Control { view: ControlView },
    /// A widget the person placed: serve runs `spec` as them, without the model (genui I5f).
    Widget { widget: String, spec: WidgetSpec, trigger: Trigger },
    /// The person's submit of a widget form serve sent (genui I5g): it is their decision to add the row.
    FormSubmit { form: String, widget: String, values: serde_json::Map<String, serde_json::Value> },
    /// The person's answer to a choice serve rendered: labels only, never a decision to write.
    ChoiceReply { session: String, choice: String, picked: Vec<String> },
    /// The person's click on Place: the thalamus keeps the dashboard in KEAP as theirs.
    DashboardSave { dashboard: SavedDashboard },
    /// The pupil asks for the person's saved dashboards; it names no one.
    DashboardList {},
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "t", rename_all = "snake_case", deny_unknown_fields)]
pub enum ToShell {
    Session { session: String, actor: String, model_uri: String },
    Text { session: String, text: String },
    /// `pin`: the spec a widget of this render would re-run; only serve sets it (genui I6).
    Render {
        session: String,
        component: Component,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        pin: Option<WidgetSpec>,
    },
    ApprovalRequest { session: String, approval: String, component: Component },
    /// `widget` names the widget whose run was refused; absent for anything else.
    Refused {
        reason: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        widget: Option<String>,
    },
    /// What the thalamus is doing in this session; the pupil's eye shows it.
    Activity { session: String, phase: Phase },
    /// A widget's answer: table_results, a chart (which may have no points yet) or a form.
    Widget { session: String, widget: String, component: Component },
    /// A widget form's row was written; `row` is the id KEAP minted.
    FormResult { session: String, widget: String, form: String, row: String },
    /// A write this connection approved landed in `table`; its widgets may re-run.
    TableChanged { session: String, table: String, row: String },
    /// The person's own dashboards in KEAP (at most 12); a row that does not decode is left out with why.
    Dashboards { session: String, dashboards: Vec<SavedDashboard>, left_out: Vec<Dropped> },
    /// A placed dashboard was written; `row` is the id KEAP minted.
    DashboardSaved { session: String, slug: String, row: String },
}

/// What a widget re-runs: exactly one of rows (query_rows' arguments), a chart, a form.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum WidgetSpec {
    Rows(serde_json::Value),
    Chart(ChartSpec),
    Form(FormSpec),
}

/// One series aggregated by serve: `op` of `y` per value of `x`; count needs no `y`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChartSpec {
    pub query: ChartQuery,
    pub chart: WidgetChart,
    pub x: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub y: Option<String>,
    pub op: Op,
}

/// The rows a chart reads: query_rows' table, q and where.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChartQuery {
    pub table: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub q: Option<String>,
    #[serde(default, rename = "where", skip_serializing_if = "Option::is_none")]
    pub where_: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WidgetChart {
    Bar,
    Line,
    Pie,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Op {
    Count,
    Sum,
    Avg,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FormSpec {
    pub table: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub columns: Option<Vec<String>>,
    /// The draft's first values by field key; serve checks them as a submit (form_cells).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prefill: Option<serde_json::Map<String, serde_json::Value>>,
    /// By field key, the condition that field is drawn on; only an optional field takes one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub when: Option<std::collections::BTreeMap<String, When>>,
}

/// Why a widget ran: the person clicked, a layout was restored, or a write changed its table.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Trigger {
    Click,
    Restore,
    TableChanged,
}

/// One step of a turn: "thinking" | {"tool": {"name": ..}} | "writing" | "idle".
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum Phase {
    Thinking,
    Tool { name: String },
    Writing,
    Idle,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    Approve,
    Reject,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlView {
    Inbox,
    Approvals,
    RedStatus,
}

/// Lowercase hyphenated uuid (8-4-4-4-12): the only id the thalamus mints.
pub fn is_uuid(s: &str) -> bool {
    s.len() == 36
        && s.char_indices().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => c == '-',
            _ => c.is_ascii_digit() || ('a'..='f').contains(&c),
        })
}

fn need_uuid(field: &str, s: &str) -> Result<(), String> {
    if is_uuid(s) { Ok(()) } else { Err(format!("{field} is not a lowercase uuid: {s:?}")) }
}

/// The pupil's correlation token, echoed back; never a thalamus id.
fn need_token(s: &str) -> Result<(), String> {
    if is_token(s) { Ok(()) } else { Err(format!("widget is not [A-Za-z0-9_-]{{1,64}}: {s:?}")) }
}

/// [A-Za-z0-9_-]{1,64}: a widget token, and a workspace id (a saved dashboard's slug).
pub fn is_token(s: &str) -> bool {
    (1..=64).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// The model has no form: one is drawn only inside the widget message the person asked for.
fn not_a_form(c: &Component) -> Result<(), String> {
    match c {
        Component::Form(_) => Err("a form is drawn only as a widget the person made, never in a render or an approval".into()),
        _ => Ok(()),
    }
}

/// What a widget spec needs before serve runs it (serve::widget) or the pupil may pin it
/// (check_shell): a table, and `y` for sum or avg. Column names need the live schema; serve checks those.
pub fn check_spec(spec: &WidgetSpec) -> Result<(), String> {
    let table = match spec {
        WidgetSpec::Rows(v) => v.as_object().ok_or("a rows spec is an object of query_rows arguments")?
            .get("table").and_then(serde_json::Value::as_str).unwrap_or(""),
        WidgetSpec::Chart(c) => {
            if c.op != Op::Count && c.y.as_deref().is_none_or(str::is_empty) {
                return Err(format!("{} needs `y`, a number column", if c.op == Op::Sum { "sum" } else { "avg" }));
            }
            &c.query.table
        }
        WidgetSpec::Form(f) => &f.table,
    };
    if table.is_empty() { Err("a widget spec names no table".into()) } else { Ok(()) }
}

/// The identity invariant and the component caps on a decoded message; Err names what broke.
fn check_shell(m: &ToShell) -> Result<(), String> {
    match m {
        ToShell::Session { session, actor, .. } => {
            need_uuid("session", session)?;
            match actor.strip_prefix("user:") {
                Some(u) if uid::is_canonical(u) => Ok(()),
                _ => Err(format!("actor is not user:<canonical uid>: {actor:?}")),
            }
        }
        ToShell::Text { session, .. } | ToShell::Activity { session, .. } | ToShell::TableChanged { session, .. } => {
            need_uuid("session", session)
        }
        ToShell::FormResult { session, widget, form, .. } => {
            need_uuid("session", session)?;
            need_token(widget)?;
            need_uuid("form", form)
        }
        ToShell::Render { session, component, pin } => {
            need_uuid("session", session)?;
            component.check()?;
            not_a_form(component)?;
            if matches!(component, Component::Choice(c) if c.id.is_none()) {
                return Err("a choice the thalamus sends carries the id it minted".into());
            }
            pin.as_ref().map_or(Ok(()), check_spec)
        }
        ToShell::ApprovalRequest { session, approval, component } => {
            need_uuid("session", session)?;
            need_uuid("approval", approval)?;
            component.check()?;
            not_a_form(component)?;
            match component {
                Component::Choice(_) => Err("a choice is asked in a render, never in an approval".into()),
                Component::Dashboard(_) => Err("a dashboard is offered in a render, never in an approval".into()),
                _ => Ok(()),
            }
        }
        ToShell::Refused { widget, .. } => widget.as_deref().map_or(Ok(()), need_token),
        ToShell::Dashboards { session, dashboards, left_out } => {
            need_uuid("session", session)?;
            if dashboards.len() > 12 || left_out.len() > 50 {
                return Err(format!("dashboards: {} listed, {} left out; at most 12 and 50", dashboards.len(), left_out.len()));
            }
            dashboards.iter().try_for_each(SavedDashboard::check)
        }
        ToShell::DashboardSaved { session, slug, .. } => {
            need_uuid("session", session)?;
            if is_token(slug) { Ok(()) } else { Err(format!("dashboard slug is not [A-Za-z0-9_-]{{1,64}}: {slug:?}")) }
        }
        ToShell::Widget { session, widget, component } => {
            need_uuid("session", session)?;
            need_token(widget)?;
            match component {
                Component::Chart(_) => component.check_allow_empty(),
                Component::TableResults(_) | Component::Form(_) => component.check(),
                _ => Err("a widget carries table_results, a chart or a form".into()),
            }
        }
    }
}

/// The shell's decoder: a line it cannot trust becomes `Refused`, never nothing.
pub fn decode_to_shell(line: &str) -> ToShell {
    let checked = serde_json::from_str::<ToShell>(line)
        .map_err(|e| format!("undecodable message: {e}"))
        .and_then(|m| check_shell(&m).map(|_| m));
    checked.unwrap_or_else(|reason| ToShell::Refused { reason, widget: None })
}

/// The thalamus's decoder: Err is the reason it answers with `Refused`.
pub fn decode_to_thalamus(line: &str) -> Result<ToThalamus, String> {
    let m: ToThalamus = serde_json::from_str(line).map_err(|e| format!("undecodable message: {e}"))?;
    match &m {
        ToThalamus::Turn { session: Some(s), .. } => need_uuid("session", s)?,
        ToThalamus::ApprovalDecision { approval, .. } => need_uuid("approval", approval)?,
        ToThalamus::Widget { widget, .. } => need_token(widget)?,
        ToThalamus::FormSubmit { form, widget, values } => {
            need_uuid("form", form)?;
            need_token(widget)?;
            if let Some((k, _)) = values.iter().find(|(_, v)| !(v.is_string() || v.is_number() || v.is_boolean())) {
                return Err(format!("form value {k:?} is not a string, number or bool"));
            }
        }
        ToThalamus::ChoiceReply { session, choice, picked } => {
            need_uuid("session", session)?;
            need_uuid("choice", choice)?;
            if picked.len() > 6 {
                return Err(format!("a choice reply picks at most 6 labels, not {}", picked.len()));
            }
            if picked.iter().any(|l| l.chars().count() > 60) {
                return Err("a picked label is over 60 chars".into());
            }
        }
        ToThalamus::DashboardSave { dashboard } => dashboard.check()?,
        _ => {}
    }
    Ok(m)
}

/// One message, one line.
pub fn encode<T: Serialize>(m: &T) -> String {
    let mut s = serde_json::to_string(m).expect("wire types always serialize");
    s.push('\n');
    s
}
