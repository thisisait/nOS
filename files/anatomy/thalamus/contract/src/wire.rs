//! What crosses ~/.nos/thalamus.sock: newline-delimited JSON, tagged by `t`.
//! Spec: files/anatomy/contracts/thalamus-shell.yml; gate:
//! tests/anatomy/test_thalamus_shell_contract.py.

use crate::renderers::Component;
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
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "t", rename_all = "snake_case", deny_unknown_fields)]
pub enum ToShell {
    Session { session: String, actor: String, model_uri: String },
    Text { session: String, text: String },
    Render { session: String, component: Component },
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
    let ok = (1..=64).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
    if ok { Ok(()) } else { Err(format!("widget is not [A-Za-z0-9_-]{{1,64}}: {s:?}")) }
}

/// The model has no form: one is drawn only inside the widget message the person asked for.
fn not_a_form(c: &Component) -> Result<(), String> {
    match c {
        Component::Form(_) => Err("a form is drawn only as a widget the person made, never in a render or an approval".into()),
        _ => Ok(()),
    }
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
        ToShell::Text { session, .. } | ToShell::Activity { session, .. } => need_uuid("session", session),
        ToShell::Render { session, component } => {
            need_uuid("session", session)?;
            component.check()?;
            not_a_form(component)
        }
        ToShell::ApprovalRequest { session, approval, component } => {
            need_uuid("session", session)?;
            need_uuid("approval", approval)?;
            component.check()?;
            not_a_form(component)
        }
        ToShell::Refused { widget, .. } => widget.as_deref().map_or(Ok(()), need_token),
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
