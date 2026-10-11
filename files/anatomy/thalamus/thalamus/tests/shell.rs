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
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../contracts/thalamus-shell.fixture.json");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
    v["to_shell"].as_array().unwrap().iter()
        .map(|c| (c["case"].as_str().unwrap().to_string(), decode_to_shell(&c["msg"].to_string())))
        .collect()
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
    for (case, msg) in fixture() {
        let c = match msg {
            ToShell::Render { component, .. } | ToShell::ApprovalRequest { component, .. } => component,
            ToShell::Refused { reason } if case == "refusal" => { assert!(!reason.is_empty()); continue }
            ToShell::Refused { reason } => panic!("{case}: the fixture no longer decodes: {reason}"),
            _ => continue,
        };
        let kind = serde_json::to_value(&c).unwrap()["kind"].as_str().unwrap().to_string();
        let mut t = Terminal::new(TestBackend::new(80, 10)).unwrap();
        t.draw(|f| f.render_widget(Paragraph::new(shell::component_lines(&c)), f.area())).unwrap();
        snapshot(&kind, &text(&t));
        kinds.push(kind);
    }
    kinds.sort();
    assert_eq!(kinds, ["approvals_list", "inbox_list", "red_status", "row_diff_approval", "table_results"],
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
