//! Bare `thalamus`: the person's shell. It holds no secret and opens no ledger; it sends
//! what the person typed or pressed, and renders only the closed component vocabulary.
//! Whatever it cannot decode is shown as a refusal (decode_to_shell), never dropped.

use nos_contract::renderers::Component;
use nos_contract::wire::{decode_to_shell, encode, ControlView, Decision, ToShell, ToThalamus};
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

/// One component as plain lines: the same text in the terminal and in its snapshot.
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
                out.push(Line::from(vals.map(|v| fit(&v, COL)).collect::<Vec<_>>().join(" ").trim_end().to_string()));
            }
        }
        Component::RowDiffApproval(d) => {
            out.push(head(format!("edit {} / {} — nothing is written unless you approve", d.table, d.row_id)));
            for ch in &d.cells {
                out.push(Line::from(format!("  {}: {} -> {}", ch.key, shown(&ch.old), shown(&ch.new))));
            }
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
            ToShell::Render { component, .. } => self.lines.extend(component_lines(&component)),
            ToShell::ApprovalRequest { approval, component, .. } => {
                self.pending.push_back((approval, component_lines(&component)));
            }
            ToShell::Refused { reason } => self.lines.push(warn(format!("refused: {reason}"))),
            // The pupil's eye shows it; the terminal's scrollback stays the conversation.
            ToShell::Activity { .. } => {}
        }
    }

    /// The connection is gone: what waits can no longer be decided, and the person is told.
    pub fn closed(&mut self, reason: &str) {
        for (approval, _) in self.pending.drain(..) {
            self.lines.push(warn(format!("not decided, nothing written: approval {approval}")));
        }
        self.apply(ToShell::Refused { reason: reason.into() });
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

pub fn draw(f: &mut Frame, app: &App) {
    let [log, input, keys] = Layout::vertical([Constraint::Min(1), Constraint::Length(1), Constraint::Length(1)]).areas(f.area());
    let prompt = match app.pending.front() {
        None => {
            tail(f, &app.lines, log);
            Line::from(format!("> {}", app.input))
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
                    app.apply(ToShell::Refused { reason: format!("not sent: {e}") });
                }
            }
        }
    })();
    ratatui::restore();
    r.map_err(|e| e.to_string())
}
