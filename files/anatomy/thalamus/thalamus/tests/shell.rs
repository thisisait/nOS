//! The shell, fixture-driven: every component in the contract fixture renders to a
//! committed snapshot, and the keys turn into exactly the wire messages they name.
//! A missing snapshot fails; THALAMUS_SNAPSHOTS=update rewrites them for review.

use nos_contract::wire::{decode_to_shell, ControlView, Decision, ToShell, ToThalamus};
use ratatui::backend::TestBackend;
use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::widgets::Paragraph;
use ratatui::Terminal;
use std::path::PathBuf;
use thalamus::shell::{self, App};

fn fixture() -> Vec<(String, ToShell)> {
    samples().into_iter().map(|(case, msg)| (case, decode_to_shell(&msg.to_string()))).collect()
}

/// The to_shell samples as the fixture writes them: (case, msg).
fn samples() -> Vec<(String, serde_json::Value)> {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../contracts/thalamus-shell.fixture.json");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
    v["to_shell"].as_array().unwrap().iter().map(|c| (c["case"].as_str().unwrap().to_string(), c["msg"].clone())).collect()
}

fn text(t: &Terminal<TestBackend>) -> String {
    let b = t.backend().buffer();
    (0..b.area.height)
        .map(|y| (0..b.area.width).map(|x| b[(x, y)].symbol()).collect::<String>().trim_end().to_string() + "\n")
        .collect()
}

fn snapshot(name: &str, got: &str) {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/snapshots").join(format!("{name}.txt"));
    if std::env::var("THALAMUS_SNAPSHOTS").as_deref() == Ok("update") {
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        return std::fs::write(&p, got).unwrap();
    }
    let want = std::fs::read_to_string(&p).unwrap_or_else(|_| panic!("no snapshot {}; review and commit one", p.display()));
    assert_eq!(got, want, "{name} drifted from its snapshot");
}

#[test]
fn every_fixture_component_matches_its_snapshot() {
    let mut kinds = Vec::new();
    for ((case, msg), (_, sample)) in fixture().into_iter().zip(samples()) {
        let c = match msg {
            ToShell::Render { component, .. } | ToShell::ApprovalRequest { component, .. } => component,
            // A refusal the fixture holds as a sample decodes to itself; any other refusal is a sample that broke.
            ToShell::Refused { .. } if serde_json::to_value(&msg).unwrap() == sample => continue,
            ToShell::Refused { reason, .. } => panic!("{case}: the fixture no longer decodes: {reason}"),
            _ => continue,
        };
        let kind = serde_json::to_value(&c).unwrap()["kind"].as_str().unwrap().to_string();
        let mut t = Terminal::new(TestBackend::new(80, 10)).unwrap();
        t.draw(|f| f.render_widget(Paragraph::new(shell::component_lines(&c)), f.area())).unwrap();
        // A kind's second sample (the insert card) is its own snapshot.
        let n = kinds.iter().filter(|k| **k == kind).count();
        snapshot(&if n == 0 { kind.clone() } else { format!("{kind}.{}", n + 1) }, &text(&t));
        kinds.push(kind);
    }
    kinds.sort();
    kinds.dedup();
    assert_eq!(kinds, ["approvals_list", "chart", "choice", "dashboard", "graph", "inbox_list", "list", "markdown", "record", "red_status", "row_diff_approval", "sequence", "table",
                       "table_results", "timeline", "tree"],
               "one snapshot per component in the closed vocabulary");
}

#[test]
fn the_whole_shell_after_the_fixture_matches_its_snapshot() {
    let mut app = App::default();
    for (_, m) in fixture() {
        app.apply(m);
    }
    let mut t = Terminal::new(TestBackend::new(80, 40)).unwrap();
    t.draw(|f| shell::draw(f, &app)).unwrap();
    let got = text(&t);
    assert!(got.contains("login carol has no row in the identity map"), "a refusal is shown, never dropped");
    snapshot("app", &got);
}

fn key(c: KeyCode) -> KeyEvent {
    KeyEvent::new(c, KeyModifiers::NONE)
}

fn typed(app: &mut App, s: &str) -> Option<ToThalamus> {
    for ch in s.chars() {
        assert!(app.key(key(KeyCode::Char(ch))).is_none(), "a typed character sends nothing");
    }
    app.key(key(KeyCode::Enter))
}

const SESSION: &str = "0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b";
const APPROVAL: &str = "7d1c2b3a-4e5f-4a6b-9c8d-1e2f3a4b5c6d";

#[test]
fn a_turn_carries_the_session_the_thalamus_opened() {
    let mut app = App::default();
    assert_eq!(typed(&mut app, "find backups"), Some(ToThalamus::Turn { session: None, text: "find backups".into() }));
    assert!(app.key(key(KeyCode::Enter)).is_none(), "an empty line sends nothing");
    app.apply(ToShell::Session { session: SESSION.into(), actor: "user:pazny".into(), model_uri: "ollama-qwen3".into() });
    assert_eq!(typed(&mut app, "close it"), Some(ToThalamus::Turn { session: Some(SESSION.into()), text: "close it".into() }));
}

#[test]
fn the_three_controls_have_keys_and_words() {
    let mut app = App::default();
    for (k, v) in [(2, ControlView::Inbox), (3, ControlView::Approvals), (4, ControlView::RedStatus)] {
        assert_eq!(app.key(key(KeyCode::F(k))), Some(ToThalamus::Control { view: v }), "F{k}");
    }
    for (w, v) in [("/inbox", ControlView::Inbox), ("/approvals", ControlView::Approvals), ("/red", ControlView::RedStatus)] {
        assert_eq!(typed(&mut app, w), Some(ToThalamus::Control { view: v }), "{w}");
    }
}

fn asked() -> App {
    let mut app = App::default();
    let (_, m) = fixture().into_iter().find(|(c, _)| c == "a row edit awaits approval").unwrap();
    app.apply(m);
    drawn(&app, 80, 24);
    app
}

#[test]
fn an_approval_is_decided_by_y_or_n_once() {
    let mut app = asked();
    assert!(app.key(key(KeyCode::Char('x'))).is_none(), "while an approval waits, other keys send nothing");
    assert!(app.key(key(KeyCode::Enter)).is_none(), "no turn while an approval waits");
    assert_eq!(app.key(key(KeyCode::Char('y'))),
               Some(ToThalamus::ApprovalDecision { approval: APPROVAL.into(), decision: Decision::Approve, note: None }));
    assert!(app.key(key(KeyCode::Char('y'))).is_none(), "an approval is decided once");
    let mut app = asked();
    assert_eq!(app.key(key(KeyCode::Char('n'))),
               Some(ToThalamus::ApprovalDecision { approval: APPROVAL.into(), decision: Decision::Reject, note: None }));
}

// --- the approval shows all it approves, or y approves nothing ---

fn flat(t: &Terminal<TestBackend>) -> String {
    let b = t.backend().buffer();
    b.content().iter().map(|c| c.symbol()).collect()
}

fn diff_of(approval: &str, cells: &[(&str, serde_json::Value)]) -> ToShell {
    use nos_contract::renderers::{CellChange, Component, RowDiffApproval, RowOp};
    let cells = cells.iter().map(|(k, v)| CellChange { key: k.to_string(), old: serde_json::Value::Null, new: v.clone() }).collect();
    ToShell::ApprovalRequest { session: SESSION.into(), approval: approval.into(),
                               component: Component::RowDiffApproval(RowDiffApproval { table: "todos".into(), title: "Todo list".into(),
                                   op: RowOp::Update, row_id: Some("r1".into()), cells, read_from: vec![], lines: None }) }
}

fn drawn(app: &App, w: u16, h: u16) -> Terminal<TestBackend> {
    let mut t = Terminal::new(TestBackend::new(w, h)).unwrap();
    t.draw(|f| shell::draw(f, app)).unwrap();
    t
}

#[test]
fn a_table_cell_at_the_2000_limit_is_wrapped_not_cut() {
    use nos_contract::renderers::{Component, Table};
    let body = format!("{}ENDMARKER", "a".repeat(2000 - "ENDMARKER".len()));
    assert_eq!(body.chars().count(), 2000);
    let component = Component::Table(Table {
        title: None,
        columns: vec!["note".into()],
        rows: vec![vec![serde_json::json!(body)]],
    });
    component.check().expect("2000 chars is a legal cell");
    let mut app = App::default();
    app.apply(ToShell::Render { session: SESSION.into(), component, pin: None });
    let screen = flat(&drawn(&app, 80, 40));
    assert!(screen.contains("ENDMARKER"), "the cell was cut to 24; its tail is gone");
}

#[test]
fn a_long_value_is_wrapped_never_cut_off() {
    let mut app = App::default();
    app.apply(diff_of(APPROVAL, &[("notes", serde_json::json!(format!("{} DROP EVERYTHING", "x".repeat(90))))]));
    assert!(flat(&drawn(&app, 80, 10)).contains("DROP EVERYTHING"), "the new value is not on screen, yet y approves it");
}

#[test]
fn an_approval_taller_than_the_screen_keeps_its_header_and_y_waits() {
    let mut app = App::default();
    for i in 0..30 {
        app.apply(ToShell::Text { session: SESSION.into(), text: format!("noise {i}") });
    }
    let cells: Vec<(String, serde_json::Value)> = (0..20).map(|i| (format!("c{i}"), serde_json::json!(i))).collect();
    let cells: Vec<(&str, serde_json::Value)> = cells.iter().map(|(k, v)| (k.as_str(), v.clone())).collect();
    app.apply(diff_of(APPROVAL, &cells));
    let small = flat(&drawn(&app, 80, 10));
    assert!(small.contains("update Todo list (todos) / r1"), "the header of the edit scrolled away");
    assert!(app.key(key(KeyCode::Char('y'))).is_none(), "y approved cells that were not on screen");
    drawn(&app, 80, 40);
    assert_eq!(app.key(key(KeyCode::Char('y'))),
               Some(ToThalamus::ApprovalDecision { approval: APPROVAL.into(), decision: Decision::Approve, note: None }));
}

// --- several approvals in one turn: each is shown and decided on its own ---

const SECOND: &str = "8e2d3c4b-5f6a-4b7c-8d9e-2f3a4b5c6d7e";

#[test]
fn two_approvals_are_decided_one_at_a_time_in_order() {
    let mut app = App::default();
    app.apply(diff_of(APPROVAL, &[("first_cell", serde_json::json!("one"))]));
    app.apply(diff_of(SECOND, &[("second_cell", serde_json::json!("two"))]));
    let screen = flat(&drawn(&app, 80, 20));
    assert!(screen.contains("first_cell") && !screen.contains("second_cell"), "both diffs above one y / n");
    assert!(screen.contains("1 of 2"), "the person is not told another edit waits");
    assert_eq!(app.key(key(KeyCode::Char('y'))),
               Some(ToThalamus::ApprovalDecision { approval: APPROVAL.into(), decision: Decision::Approve, note: None }),
               "y decided an edit other than the one on screen");
    let screen = flat(&drawn(&app, 80, 20));
    assert!(screen.contains("approve this edit? y / n") && screen.contains("second_cell"), "the second edit is not asked");
    assert_eq!(app.key(key(KeyCode::Char('n'))),
               Some(ToThalamus::ApprovalDecision { approval: SECOND.into(), decision: Decision::Reject, note: None }));
    assert!(app.pending.is_empty(), "an approval stayed pending after both were decided");
}

#[test]
fn the_controls_answer_while_an_approval_waits() {
    let mut app = asked();
    for (k, v) in [(2, ControlView::Inbox), (3, ControlView::Approvals), (4, ControlView::RedStatus)] {
        assert_eq!(app.key(key(KeyCode::F(k))), Some(ToThalamus::Control { view: v }), "F{k} while an approval waits");
    }
    assert_eq!(app.pending.len(), 1, "a control decided the approval");
}

#[test]
fn a_closed_connection_releases_what_waits_and_says_so() {
    let mut app = asked();
    app.closed("the thalamus closed the connection");
    assert!(app.pending.is_empty(), "the shell stays locked on an approval nobody can decide");
    assert!(flat(&drawn(&app, 80, 24)).contains("not decided"), "the undecided edit is dropped silently");
}

/// A widget's chart before its table has a row says so, not an empty line.
#[test]
fn an_empty_chart_says_no_rows_yet() {
    let c: nos_contract::renderers::Component = serde_json::from_str(
        r#"{"kind":"chart","props":{"chart":"bar","x":"category","series":[{"name":"rows","points":[]}]}}"#).unwrap();
    let lines: Vec<String> = shell::component_lines(&c).iter().map(|l| l.to_string()).collect();
    assert_eq!(lines, ["bar chart: 1 series over category x, not drawn here", "  rows: (no rows yet)"]);
}

/// A widget form is filled in the pupil; the terminal says what it asks and nothing more.
#[test]
fn a_form_is_said_as_its_fields_and_filled_in_the_pupil() {
    let c: nos_contract::renderers::Component = serde_json::from_str(r#"{"kind":"form","props":{
        "form":"5f0c1b2a-3d4e-4f5a-8b6c-7d8e9f0a1b2c","table":"expenses","title":"Expenses","fields":[
        {"key":"when","label":"When","kind":"date","required":false},
        {"key":"kind","label":"Kind","kind":"select","required":true,"options":["food","travel","tools"]},
        {"key":"amount","label":"Amount","kind":"number","required":true},
        {"key":"paid","label":"Paid","kind":"bool","required":false}],
        "omitted":[{"key":"receipt","kind":"file"}]}}"#).unwrap();
    let mut t = Terminal::new(TestBackend::new(80, 10)).unwrap();
    t.draw(|f| f.render_widget(Paragraph::new(shell::component_lines(&c)), f.area())).unwrap();
    snapshot("form", &text(&t));
}

#[test]
fn a_widget_is_said_under_its_token() {
    let mut app = App::default();
    for (case, m) in fixture() {
        if case.starts_with("a widget") || case == "a refused widget names it" {
            app.apply(m);
        }
    }
    let said: String = app.lines.iter().map(|l| format!("{l}\n")).collect();
    for want in ["widget w4:", "form Expenses (table expenses): fill it in the pupil", "widget w5:", "  count: (no rows yet)",
                 "widget w-expenses_1:", "refused (widget w2): no column `kinds` in Expenses"] {
        assert!(said.contains(want), "{want:?} not in:\n{said}");
    }
    assert!(!said.contains("undecodable"), "{said}");
}

#[test]
fn a_form_result_and_a_table_change_are_said() {
    let mut app = App::default();
    for (case, m) in fixture() {
        if case == "a widget form added a row" || case == "a write changed a table" {
            app.apply(m);
        }
    }
    let said: String = app.lines.iter().map(|l| format!("{l}\n")).collect();
    assert_eq!(said, "widget w4: row e3 added\ntable expenses changed (row e3)\n");
}

/// The terminal places nothing: an offered dashboard is said, each widget and what was left out, and where to place it.
#[test]
fn an_offered_dashboard_is_said_and_placed_in_the_pupil() {
    let (_, m) = fixture().into_iter().find(|(case, _)| case == "Iris offers a dashboard").expect("the fixture's dashboard");
    let ToShell::Render { component, .. } = m else { panic!("the dashboard sample no longer decodes: {m:?}") };
    let said: String = shell::component_lines(&component).iter().map(|l| format!("{l}\n")).collect();
    for want in ["dashboard Bench board: 3 widgets, place it in the pupil", "  lens: track = platform; due < (unset)",
                 "  rows: Next rows (table iris-bench-2)", "  chart: Points by track (bar, sum of points by track, table iris-bench-2)",
                 "  form: Add a row (table iris-bench-2)", "  left out: By owner — no column `owner` in iris-bench-2"] {
        assert!(said.contains(want), "{want:?} not in:\n{said}");
    }
}

/// The terminal has no workspace: a pin is one muted line, and an unpinned render says nothing of it (genui I6).
#[test]
fn a_pinnable_render_is_one_muted_line() {
    let mut app = App::default();
    for (case, m) in fixture() {
        if ["search results", "a chart the model shows", "a table the model shows"].contains(&case.as_str()) {
            app.apply(m);
        }
    }
    let pinned: Vec<_> = app.lines.iter().filter(|l| l.to_string() == "(pinnable in the pupil)").collect();
    assert_eq!(pinned.len(), 2, "one line per pinned render, none for the table");
    assert!(pinned.iter().all(|l| l.style.fg == Some(ratatui::style::Color::DarkGray)), "{pinned:?}");
}

const CHOICE: &str = "3c9e1d2f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";

fn choice_app() -> App {
    let mut app = App::default();
    let (_, m) = fixture().into_iter().find(|(c, _)| c == "Iris asks at a fork").unwrap();
    app.apply(m);
    app
}

/// iris-genui-forms step 1: the terminal numbers the options, marks the suggestion, and
/// answers with /choose; the reply names the choice and the labels, nothing else.
#[test]
fn a_choice_is_answered_by_its_number_once() {
    let mut app = choice_app();
    let shown = flat(&drawn(&app, 80, 24));
    assert!(shown.contains("1. todos — the open work, by status (suggested)"), "{shown}");
    assert!(shown.contains("/choose"), "{shown}");
    for bad in ["/choose 9", "/choose 0", "/choose 1,2", "/choose x", "/choose"] {
        assert_eq!(typed(&mut app, bad), None, "{bad} sent a reply");
    }
    assert_eq!(typed(&mut app, "/choose 2"),
               Some(ToThalamus::ChoiceReply { session: SESSION.into(), choice: CHOICE.into(), picked: vec!["expenses".into()] }));
    assert!(flat(&drawn(&app, 80, 24)).contains("you: expenses"));
    assert_eq!(typed(&mut app, "/choose 1"), None, "a choice is answered once");
    assert!(flat(&drawn(&app, 80, 24)).contains("no open choice"));
}

#[test]
fn a_multi_choice_takes_several_numbers() {
    let m = serde_json::json!({"t": "render", "session": SESSION, "component": {"kind": "choice", "props": {"id": CHOICE,
        "question": "Which tracks?", "options": [{"label": "pupil"}, {"label": "thalamus"}, {"label": "keap"}],
        "suggested": ["pupil", "thalamus"], "multi": true}}});
    let mut app = App::default();
    app.apply(decode_to_shell(&m.to_string()));
    assert!(flat(&drawn(&app, 80, 24)).contains("2. thalamus (suggested)"));
    assert_eq!(typed(&mut app, "/choose 1,1"), None, "a number twice");
    assert_eq!(typed(&mut app, "/choose 1, 3"),
               Some(ToThalamus::ChoiceReply { session: SESSION.into(), choice: CHOICE.into(), picked: vec!["pupil".into(), "keap".into()] }));
}

/// Up to four choices may be open: each is numbered, and /choose #n answers that one, not the latest.
#[test]
fn an_open_choice_is_answered_by_its_own_number() {
    const OTHER: &str = "4d0f2e3a-5b6c-4d7e-8f90-a1b2c3d4e5f6";
    let mut app = App::default();
    for (id, q) in [(CHOICE, "Which table?"), (OTHER, "Which chart?")] {
        let m = serde_json::json!({"t": "render", "session": SESSION, "component": {"kind": "choice", "props": {"id": id,
            "question": q, "options": [{"label": "a"}, {"label": "b"}], "suggested": ["a"], "multi": false}}});
        app.apply(decode_to_shell(&m.to_string()));
    }
    let shown = flat(&drawn(&app, 80, 24));
    assert!(shown.contains("choice #1") && shown.contains("choice #2"), "{shown}");
    for bad in ["/choose #3 1", "/choose #0 1", "/choose #x 1", "/choose #1", "/choose #1 3"] {
        assert_eq!(typed(&mut app, bad), None, "{bad} sent a reply");
    }
    let reply = |choice: &str, l: &str| Some(ToThalamus::ChoiceReply { session: SESSION.into(), choice: choice.into(), picked: vec![l.into()] });
    assert_eq!(typed(&mut app, "/choose #1 2"), reply(CHOICE, "b"), "#1 is the first asked, not the latest");
    assert_eq!(typed(&mut app, "/choose #1 1"), None, "#1 is answered once");
    assert!(flat(&drawn(&app, 80, 24)).contains("no open choice #1"));
    assert_eq!(typed(&mut app, "/choose 1"), reply(OTHER, "a"), "a bare /choose still answers the latest");
}

#[test]
fn a_choice_waits_while_an_approval_does() {
    let mut app = choice_app();
    let (_, m) = fixture().into_iter().find(|(c, _)| c == "a row edit awaits approval").unwrap();
    app.apply(m);
    drawn(&app, 80, 24);
    assert_eq!(typed(&mut app, "/choose 2"), None, "a reply went out while an approval waits");
}

#[test]
fn an_insert_card_names_its_table_and_what_the_model_read() {
    let (_, m) = fixture().into_iter().find(|(c, _)| c == "a new row awaits approval").unwrap();
    let ToShell::ApprovalRequest { component, .. } = m else { panic!("not an approval") };
    let lines: Vec<String> = shell::component_lines(&component).iter().map(|l| l.to_string()).collect();
    assert_eq!(lines[0], "insert a new row in Expenses (expenses) — nothing is written unless you approve");
    assert_eq!(lines[1].trim(), "contains text from search_memory");
}

/// The terminal keeps no dashboards: a list or a save the pupil asked for is said, what was left out with why.
#[test]
fn saved_dashboards_are_said_as_text() {
    let mut app = App::default();
    for (case, m) in fixture() {
        if case == "the person's dashboards from KEAP" || case == "a placed dashboard was saved" {
            app.apply(m);
        }
    }
    let said: String = app.lines.iter().map(|l| format!("{l}\n")).collect();
    assert_eq!(said, "dashboards in KEAP: Bench board (wsbench1, 2 widgets)\n\
                      \x20 left out: Old board — widget \"x\": a widget spec names no table\n\
                      dashboard wsbench1 saved in KEAP (row d1)\n");
}

/// iris-v3 B2: a form says what it starts with and when a field shows; the pupil holds the draft.
#[test]
fn a_form_says_its_prefill_and_when_a_field_shows() {
    let (_, m) = fixture().into_iter().find(|(case, _)| case == "a widget form").expect("the fixture's form");
    let ToShell::Widget { component, .. } = m else { panic!("the form sample no longer decodes: {m:?}") };
    let said: String = shell::component_lines(&component).iter().map(|l| format!("{l}\n")).collect();
    for want in ["  When (date, prefilled 2026-10-20)", "  Kind (select, required, options food|travel|tools, prefilled travel)",
                 "  Paid (bool, shown when kind != food)"] {
        assert!(said.contains(want), "{want:?} not in:\n{said}");
    }
}
