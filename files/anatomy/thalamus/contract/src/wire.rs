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
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "t", rename_all = "snake_case", deny_unknown_fields)]
pub enum ToShell {
    Session { session: String, actor: String, model_uri: String },
    Text { session: String, text: String },
    Render { session: String, component: Component },
    ApprovalRequest { session: String, approval: String, component: Component },
    Refused { reason: String },
    /// What the thalamus is doing in this session; the pupil's eye shows it.
    Activity { session: String, phase: Phase },
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

/// The identity invariant on a decoded message; Err names the broken field.
fn check_shell(m: &ToShell) -> Result<(), String> {
    match m {
        ToShell::Session { session, actor, .. } => {
            need_uuid("session", session)?;
            match actor.strip_prefix("user:") {
                Some(u) if uid::is_canonical(u) => Ok(()),
                _ => Err(format!("actor is not user:<canonical uid>: {actor:?}")),
            }
        }
        ToShell::Text { session, .. } | ToShell::Render { session, .. } | ToShell::Activity { session, .. } => {
            need_uuid("session", session)
        }
        ToShell::ApprovalRequest { session, approval, .. } => {
            need_uuid("session", session)?;
            need_uuid("approval", approval)
        }
        ToShell::Refused { .. } => Ok(()),
    }
}

/// The shell's decoder: a line it cannot trust becomes `Refused`, never nothing.
pub fn decode_to_shell(line: &str) -> ToShell {
    let checked = serde_json::from_str::<ToShell>(line)
        .map_err(|e| format!("undecodable message: {e}"))
        .and_then(|m| check_shell(&m).map(|_| m));
    checked.unwrap_or_else(|reason| ToShell::Refused { reason })
}

/// The thalamus's decoder: Err is the reason it answers with `Refused`.
pub fn decode_to_thalamus(line: &str) -> Result<ToThalamus, String> {
    let m: ToThalamus = serde_json::from_str(line).map_err(|e| format!("undecodable message: {e}"))?;
    match &m {
        ToThalamus::Turn { session: Some(s), .. } => need_uuid("session", s)?,
        ToThalamus::ApprovalDecision { approval, .. } => need_uuid("approval", approval)?,
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
