//! What crosses ~/.nos/thalamus.sock: newline-delimited JSON, tagged by `t`.
//! Spec: files/anatomy/contracts/thalamus-shell.yml; gate:
//! tests/anatomy/test_thalamus_shell_contract.py.

use crate::renderers::{Component, When};
use crate::uid;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

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
    /// Whom the person works for in this session (the septum): every table read honours it.
    WorkingFor { scope: Scope },
    /// Which models Iris may use in this session (W5); serve answers model_options.
    ModelOptions,
    /// The person's pick for this session: serve judges it again and rebinds from the next turn.
    ModelPick { backend: String, model: String },
    /// Opens this connection's session as the person's last one its connection closed, then `replay`;
    /// a fresh one when there is none. Asked, never imposed: a bare first message opens a fresh session.
    /// With `workspace` (v9): that workspace tab's own session, switched to from the open one.
    Resume {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        workspace: Option<String>,
    },
    /// The person's /clear (v9): the tab's session ends and a fresh one opens for it.
    Clear,
    /// The person's /branch (v9): `workspace`, a tab the shell just added, opens a session from this one's conversation.
    Branch { workspace: String },
    /// The person's Stop (v9): the running turn of `session` ends before its next model or tool call.
    Stop { session: String },
    /// The person's workspace document as the thalamus holds it; serve answers `workspace`.
    WorkspaceLoad,
    /// The person's whole workspace document, replacing the one held: a JSON object (need_doc).
    WorkspaceSave { doc: serde_json::Value },
    /// The shell asks for the person's catalogue, to mark their input; serve answers `catalogue`, again after working_for.
    Catalogue,
    /// What the face lets Iris do on its screen (face/src/lib/limbs/types.ts Limb); replaces any earlier list.
    Limbs { limbs: Vec<Limb> },
    /// The face's answer to an `act`: ok and what it returned, or why not.
    Acted {
        act: String,
        ok: bool,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        result: Option<serde_json::Value>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        reason: Option<String>,
    },
}

/// One (app, action) the face declares; `writes` puts it behind an action_approval card.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Limb {
    pub app: String,
    pub action: String,
    pub params: BTreeMap<String, ParamSpec>,
    pub writes: bool,
    pub says: String,
}

/// A limb param: its type, an enum's values, and whether it must be given (types.ts ParamSpec).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParamSpec {
    #[serde(rename = "type")]
    pub kind: ParamKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub values: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub required: Option<bool>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParamKind {
    String,
    Number,
    Boolean,
    Enum,
}

/// Why `params` do not pass a limb's spec (an unknown name, a required one missing, a misfit), or None:
/// the rule face/src/lib/limbs/dispatch.ts badParam applies on the other side.
pub fn check_params(spec: &BTreeMap<String, ParamSpec>, params: &serde_json::Map<String, serde_json::Value>) -> Option<String> {
    if let Some(k) = params.keys().find(|k| !spec.contains_key(*k)) {
        return Some(format!("unknown param {k}"));
    }
    spec.iter().find_map(|(k, s)| {
        let fits = |v: &serde_json::Value| match s.kind {
            ParamKind::String => v.is_string(),
            ParamKind::Number => v.is_number(),
            ParamKind::Boolean => v.is_boolean(),
            ParamKind::Enum => v.as_str().is_some_and(|x| s.values.iter().flatten().any(|o| o == x)),
        };
        match params.get(k) {
            None if s.required == Some(true) => Some(format!("missing param {k}")),
            Some(v) if !fits(v) => Some(format!("bad param {k}")),
            _ => None,
        }
    })
}

/// One table of the person's catalogue: what their input is marked against (face/src/lib/iris/marks.ts).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CatalogueTable {
    pub id: String,
    pub title: String,
    pub columns: Vec<CatalogueColumn>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CatalogueColumn {
    pub key: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    pub kind: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub options: Option<Vec<String>>,
}

/// One model the person may pick: who processes the turns, whether they leave the EU, and
/// `warning` when it is below the recommended size (it runs, badly).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelOption {
    pub backend: String,
    pub model: String,
    pub processor: String,
    pub transfers_outside_eu: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub warning: Option<String>,
    pub current: bool,
}

/// all: no wall (a session before one is said); personal; or one client party (id, slug or name).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Scope {
    All,
    Personal,
    Client(String),
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
    /// The scope serve set, the client resolved to its party id; `name` is what both shells show.
    WorkingFor { session: String, scope: Scope, name: String },
    /// What the session may bind (`current` is its binding); `refused` says each one left out and why.
    ModelOptions { session: String, options: Vec<ModelOption>, refused: Vec<String> },
    /// The person's own turn, as a replay redraws it.
    Said { session: String, text: String },
    /// A resumed session's chat, oldest first; `open` names its approvals and choices still waiting.
    Replay { session: String, log: Vec<ToShell>, open: Vec<String> },
    /// The person's workspace document; None when the thalamus holds none.
    Workspace { doc: Option<serde_json::Value> },
    /// The tables the person may read under the scope, to mark their input (asked by `catalogue`).
    Catalogue { session: String, tables: Vec<CatalogueTable> },
    /// Iris takes a declared limb on the face's screen; the face answers `acted` with this `act`.
    Act { session: String, act: String, app: String, action: String, params: serde_json::Map<String, serde_json::Value> },
    /// Whether the session's local model is in memory (Ollama /api/ps, v9); said when it changes, never for a remote one.
    ModelState { session: String, loaded: bool },
}

/// A workspace document's cap, serialized: it rides one line of at most 1 MiB.
pub const MAX_WORKSPACE: usize = 512 << 10;
/// The most lines a replay redraws.
pub const MAX_REPLAY: usize = 200;

/// What a widget re-runs: exactly one of rows (query_rows' arguments), a chart, a form, a kpi.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum WidgetSpec {
    Rows(serde_json::Value),
    Chart(ChartSpec),
    Form(FormSpec),
    Kpi(KpiSpec),
    Knowledge(KnowledgeSpec),
}

/// The tree around one taxonomy node, read by serve as the person (v10).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeSpec {
    pub node: String,
}

/// One total by serve: `op` of `y` over the query's rows (query_rows with op and no group_by).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KpiSpec {
    pub query: ChartQuery,
    pub op: Op,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub y: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
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
    let ok = (1..=64).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
    if ok { Ok(()) } else { Err(format!("widget is not [A-Za-z0-9_-]{{1,64}}: {s:?}")) }
}

/// A workspace tab's id as the shell minted it ([A-Za-z0-9_-]{1,64}): it names a file under people/<uid>/.
fn need_tab(s: &str) -> Result<(), String> {
    need_token(s).map_err(|_| format!("workspace is not [A-Za-z0-9_-]{{1,64}}: {s:?}"))
}

fn need_scope(s: &Scope) -> Result<(), String> {
    match s {
        Scope::Client(c) if c.trim().is_empty() || c.chars().count() > 120 => Err("a client is named by 1-120 chars".into()),
        _ => Ok(()),
    }
}

/// A pick names a register row (lowercase, digits, '-') and a model id of 1-200 chars.
fn need_model(backend: &str, model: &str) -> Result<(), String> {
    let row = (1..=64).contains(&backend.len()) && backend.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-');
    if !row {
        return Err(format!("backend is not a register row name: {backend:?}"));
    }
    if model.trim().is_empty() || model.chars().count() > 200 { Err("a model is named by 1-200 chars".into()) } else { Ok(()) }
}

/// A workspace document is a JSON object of at most MAX_WORKSPACE bytes; its shape is the shell's.
fn need_doc(doc: &serde_json::Value) -> Result<(), String> {
    let n = doc.to_string().len();
    match doc {
        serde_json::Value::Object(_) if n <= MAX_WORKSPACE => Ok(()),
        serde_json::Value::Object(_) => Err(format!("a workspace is at most {MAX_WORKSPACE} bytes, not {n}")),
        _ => Err("a workspace is a JSON object".into()),
    }
}

/// A limb's app, action or param name: [a-z0-9_-]{1,64}.
fn need_name(what: &str, s: &str) -> Result<(), String> {
    let ok = (1..=64).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-');
    if ok { Ok(()) } else { Err(format!("{what} is not [a-z0-9_-]{{1,64}}: {s:?}")) }
}

/// An act's params are flat: at most 16 strings, numbers and bools, as a limb's spec types them.
pub fn check_flat(params: &serde_json::Map<String, serde_json::Value>) -> Result<(), String> {
    if params.len() > 16 {
        return Err("an act takes at most 16 params".into());
    }
    match params.iter().find(|(_, v)| !(v.is_string() || v.is_number() || v.is_boolean())) {
        Some((k, _)) => Err(format!("param {k:?} is not a string, number or bool")),
        None => params.keys().try_for_each(|k| need_name("a param", k)),
    }
}

fn need_limbs(limbs: &[Limb]) -> Result<(), String> {
    if limbs.len() > 64 {
        return Err(format!("a face declares at most 64 limbs, not {}", limbs.len()));
    }
    for (i, l) in limbs.iter().enumerate() {
        need_name("an app", &l.app)?;
        need_name("an action", &l.action)?;
        let at = format!("{}.{}", l.app, l.action);
        if limbs[..i].iter().any(|x| x.app == l.app && x.action == l.action) {
            return Err(format!("{at} is declared twice"));
        }
        if l.says.trim().is_empty() || l.says.chars().count() > 200 {
            return Err(format!("{at} says what it does in 1-200 chars"));
        }
        if l.params.len() > 16 {
            return Err(format!("{at} takes at most 16 params"));
        }
        for (k, p) in &l.params {
            need_name("a param", k)?;
            match (p.kind, &p.values) {
                (ParamKind::Enum, Some(v)) if (1..=50).contains(&v.len()) && v.iter().all(|x| (1..=60).contains(&x.chars().count())) => {}
                (ParamKind::Enum, _) => return Err(format!("{at} param {k}: an enum has 1-50 values of 1-60 chars")),
                (_, Some(_)) => return Err(format!("{at} param {k}: only an enum has values")),
                (_, None) => {}
            }
        }
    }
    Ok(())
}

fn need_catalogue(tables: &[CatalogueTable]) -> Result<(), String> {
    let name = |what: &str, s: &str| if s.trim().is_empty() || s.chars().count() > 200 { Err(format!("{what} is 1-200 chars")) } else { Ok(()) };
    if tables.len() > 64 {
        return Err("a catalogue holds at most 64 tables".into());
    }
    tables.iter().try_for_each(|t| {
        name("a catalogue table id", &t.id)?;
        name("a catalogue table title", &t.title)?;
        if t.columns.len() > 120 {
            return Err(format!("table {} has at most 120 columns", t.id));
        }
        t.columns.iter().try_for_each(|c| {
            name("a catalogue column key", &c.key)?;
            name("a catalogue column kind", &c.kind)?;
            c.label.as_deref().map_or(Ok(()), |l| name("a catalogue column label", l))?;
            match &c.options {
                Some(o) if o.len() > 200 || o.iter().any(|x| x.chars().count() > 200) => Err(format!("column {} has at most 200 options of 200 chars", c.key)),
                _ => Ok(()),
            }
        })
    })
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
        WidgetSpec::Kpi(k) => {
            if k.op != Op::Count && k.y.as_deref().is_none_or(str::is_empty) {
                return Err(format!("{} needs `y`, a number column", if k.op == Op::Sum { "sum" } else { "avg" }));
            }
            &k.query.table
        }
        WidgetSpec::Knowledge(k) => return crate::renderers::need_node_id(&k.node),
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
        ToShell::Text { session, .. } | ToShell::Activity { session, .. } | ToShell::TableChanged { session, .. }
        | ToShell::Said { session, .. } | ToShell::ModelState { session, .. } => {
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
            if matches!(component, Component::ActionApproval(_)) {
                return Err("an action is asked only as an approval, never drawn as a render".into());
            }
            if matches!(component, Component::Sources(x) if x.items.iter().any(|i| i.name.is_none())) {
                return Err("a source the thalamus sends carries the table name it resolved".into());
            }
            if matches!(component, Component::Choice(c) if c.id.is_none()) {
                return Err("a choice the thalamus sends carries the id it minted".into());
            }
            // The number is serve's: a kpi is drawn only beside the total that re-runs it.
            if matches!(component, Component::Kpi(_)) && !matches!(pin, Some(WidgetSpec::Kpi(_))) {
                return Err("a kpi render carries the kpi pin serve computed it from".into());
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
                Component::Kpi(_) => Err("a kpi is drawn in a render or a widget, never in an approval".into()),
                Component::KnowledgeTree(_) => Err("a knowledge tree is drawn in a render or a widget, never in an approval".into()),
                Component::Dendrogram(_) => Err("a run tree is drawn in a render, never in an approval".into()),
                Component::Callout(_) | Component::Steps(_) | Component::Sources(_) | Component::FollowUp(_) => {
                    Err("a callout, steps, sources or follow_up is drawn in a render, never in an approval".into())
                }
                _ => Ok(()),
            }
        }
        ToShell::Refused { widget, .. } => widget.as_deref().map_or(Ok(()), need_token),
        ToShell::WorkingFor { session, scope, name } => {
            need_uuid("session", session)?;
            need_scope(scope)?;
            if name.trim().is_empty() || name.chars().count() > 200 { Err("a scope is said by a name of 1-200 chars".into()) } else { Ok(()) }
        }
        ToShell::ModelOptions { session, options, refused } => {
            need_uuid("session", session)?;
            if options.len() > 64 || refused.len() > 64 {
                return Err("model_options holds at most 64 options and 64 refusals".into());
            }
            if options.iter().filter(|o| o.current).count() > 1 {
                return Err("at most one model is current".into());
            }
            options.iter().try_for_each(|o| {
                need_model(&o.backend, &o.model)?;
                if o.processor.trim().is_empty() { Err(format!("{} {} names no processor", o.backend, o.model)) } else { Ok(()) }
            })
        }
        ToShell::Replay { session, log, open } => {
            need_uuid("session", session)?;
            if log.len() > MAX_REPLAY || open.len() > 64 {
                return Err(format!("a replay holds at most {MAX_REPLAY} lines and 64 open ids"));
            }
            open.iter().try_for_each(|id| need_uuid("open", id))?;
            log.iter().try_for_each(|m| {
                let of = match m {
                    ToShell::Said { session, .. } | ToShell::Text { session, .. } | ToShell::Render { session, .. }
                    | ToShell::ApprovalRequest { session, .. } => Some(session),
                    ToShell::Refused { widget: None, .. } => None,
                    _ => return Err("a replay holds said, text, render, approval_request and refused only".to_string()),
                };
                if of.is_some_and(|s| s != session) {
                    return Err("a replayed line is of another session".into());
                }
                check_shell(m)
            })
        }
        ToShell::Workspace { doc } => doc.as_ref().map_or(Ok(()), need_doc),
        ToShell::Catalogue { session, tables } => {
            need_uuid("session", session)?;
            need_catalogue(tables)
        }
        ToShell::Act { session, act, app, action, params } => {
            need_uuid("session", session)?;
            need_uuid("act", act)?;
            need_name("an app", app)?;
            need_name("an action", action)?;
            check_flat(params)
        }
        ToShell::Widget { session, widget, component } => {
            need_uuid("session", session)?;
            need_token(widget)?;
            match component {
                Component::Chart(_) => component.check_allow_empty(),
                Component::TableResults(_) | Component::Form(_) | Component::Kpi(_) | Component::KnowledgeTree(_) => component.check(),
                _ => Err("a widget carries table_results, a chart, a form, a kpi or a knowledge tree".into()),
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
        ToThalamus::Turn { session: Some(s), .. } | ToThalamus::Stop { session: s } => need_uuid("session", s)?,
        ToThalamus::Resume { workspace: Some(w) } | ToThalamus::Branch { workspace: w } => need_tab(w)?,
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
        ToThalamus::WorkingFor { scope } => need_scope(scope)?,
        ToThalamus::ModelPick { backend, model } => need_model(backend, model)?,
        ToThalamus::WorkspaceSave { doc } => need_doc(doc)?,
        ToThalamus::Limbs { limbs } => need_limbs(limbs)?,
        ToThalamus::Acted { act, reason, .. } => {
            need_uuid("act", act)?;
            if reason.as_ref().is_some_and(|r| r.chars().count() > 2000) {
                return Err("an acted reason is at most 2000 chars".into());
            }
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_workspace_over_its_cap_is_refused_both_ways() {
        let big = serde_json::json!({"pad": "x".repeat(MAX_WORKSPACE)});
        let save = encode(&ToThalamus::WorkspaceSave { doc: big.clone() });
        assert!(decode_to_thalamus(&save).unwrap_err().contains("at most"));
        assert!(matches!(decode_to_shell(&encode(&ToShell::Workspace { doc: Some(big) })), ToShell::Refused { .. }));
        assert!(decode_to_thalamus(&encode(&ToThalamus::WorkspaceSave { doc: serde_json::json!({"version": 2}) })).is_ok());
    }

    #[test]
    fn a_replay_over_its_cap_is_refused() {
        let s = "0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b".to_string();
        let line = |n: usize| encode(&ToShell::Replay { session: s.clone(),
            log: (0..n).map(|i| ToShell::Said { session: s.clone(), text: i.to_string() }).collect(), open: vec![] });
        assert!(matches!(decode_to_shell(&line(MAX_REPLAY)), ToShell::Replay { .. }));
        assert!(matches!(decode_to_shell(&line(MAX_REPLAY + 1)), ToShell::Refused { .. }));
    }
}
