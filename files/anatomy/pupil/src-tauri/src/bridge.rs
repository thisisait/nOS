//! The pupil's only way to the thalamus: ~/.nos/thalamus.sock, opened as the logged-in
//! user (the thalamus names the person from the peer's uid). Every line is decoded with
//! decode_to_shell before the webview sees it, so a line it cannot trust arrives as
//! Refused, never dropped (thalamus-shell.yml, invariant `visibility`).

use nos_contract::wire::{decode_to_shell, encode, ToShell, ToThalamus};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};

/// One line's cap, as the terminal shell's (shell.rs MAX_LINE).
const MAX_LINE: u64 = 1 << 20;

pub fn socket_path() -> Result<PathBuf, String> {
    std::env::var_os("HOME")
        .map(|h| PathBuf::from(h).join(".nos/thalamus.sock"))
        .ok_or_else(|| "HOME is not set".into())
}

pub fn connect(sock: &Path) -> Result<UnixStream, String> {
    UnixStream::connect(sock).map_err(|e| format!("{}: {e}", sock.display()))
}

pub fn send(w: &mut impl Write, m: &ToThalamus) -> Result<(), String> {
    w.write_all(encode(m).as_bytes()).map_err(|e| format!("send failed: {e}"))
}

/// The approvals this connection was asked and has not answered, oldest first. The bridge,
/// not the webview, refuses a turn while one waits and any decision but the oldest's, once
/// (shell.rs:30-32, 173-179); serve refuses only an id it is not waiting on (serve.rs:237).
#[derive(Default)]
pub struct Pending(std::collections::VecDeque<String>);

impl Pending {
    pub fn saw(&mut self, m: &ToShell) {
        if let ToShell::ApprovalRequest { approval, .. } = m {
            self.0.push_back(approval.clone());
        }
    }

    pub fn admit(&mut self, m: &ToThalamus) -> Result<(), String> {
        match m {
            ToThalamus::Turn { .. } if !self.0.is_empty() => Err("an approval is waiting: decide it first".into()),
            ToThalamus::ApprovalDecision { approval, .. } if self.0.front() != Some(approval) => {
                Err(format!("approval {approval} is not the oldest waiting one"))
            }
            ToThalamus::ApprovalDecision { .. } => {
                self.0.pop_front();
                Ok(())
            }
            _ => Ok(()),
        }
    }
}

/// Emits every line, decoded, until the socket ends; returns why it ended.
pub fn pump(stream: UnixStream, mut emit: impl FnMut(ToShell)) -> String {
    let mut r = BufReader::new(stream);
    loop {
        let mut buf = Vec::new();
        match r.by_ref().take(MAX_LINE).read_until(b'\n', &mut buf) {
            Ok(0) => return "the thalamus closed the connection".into(),
            Ok(_) => emit(match std::str::from_utf8(&buf) {
                Ok(line) => decode_to_shell(line),
                Err(e) => ToShell::Refused { reason: format!("undecodable message: not UTF-8 ({e})") },
            }),
            Err(e) => return format!("read failed: {e}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nos_contract::wire::{decode_to_thalamus, ControlView, Decision};
    use serde_json::Value;
    use std::os::unix::net::UnixListener;

    const FIXTURE: &str = include_str!("../../../contracts/thalamus-shell.fixture.json");

    /// A fake thalamus on a throwaway socket: the bridge connects by path, as in the app.
    fn fake(name: &str) -> (UnixListener, UnixStream) {
        let sock = std::env::temp_dir().join(format!("pupil-{}-{name}.sock", std::process::id()));
        let _ = std::fs::remove_file(&sock);
        let l = UnixListener::bind(&sock).unwrap();
        let client = connect(&sock).unwrap();
        let _ = std::fs::remove_file(&sock);
        (l, client)
    }

    #[test]
    fn a_turn_round_trips_through_the_socket() {
        let (l, mut client) = fake("turn");
        let (server, _) = l.accept().unwrap();
        let turn = ToThalamus::Turn { session: None, text: "find rows about backups".into() };
        send(&mut client, &turn).unwrap();
        let mut line = String::new();
        BufReader::new(server).read_line(&mut line).unwrap();
        assert_eq!(decode_to_thalamus(&line).unwrap(), turn);
    }

    #[test]
    fn every_fixture_line_arrives_and_none_is_dropped() {
        let fx: Value = serde_json::from_str(FIXTURE).unwrap();
        let good: Vec<String> = fx["to_shell"].as_array().unwrap().iter().map(|c| c["msg"].to_string()).collect();
        let bad: Vec<String> = fx["refused"].as_array().unwrap().iter().map(|c| c["line"].as_str().unwrap().to_owned()).collect();
        let (l, client) = fake("fixture");
        let (mut server, _) = l.accept().unwrap();
        // Written beside the read: the fixture outgrew the socket buffer (an 8001-char line) and deadlocked.
        let lines: Vec<String> = good.iter().chain(&bad).cloned().collect();
        let writer = std::thread::spawn(move || {
            for line in lines {
                server.write_all(format!("{line}\n").as_bytes()).unwrap();
            }
            server.write_all(b"\xff\xfe not utf-8\n").unwrap();
        });

        let mut got = Vec::new();
        let why = pump(client, |m| got.push(m));
        writer.join().unwrap();
        assert_eq!(why, "the thalamus closed the connection");
        assert_eq!(got.len(), good.len() + bad.len() + 1, "a line was dropped: {got:?}");
        for (line, m) in good.iter().zip(&got) {
            assert_eq!(serde_json::to_value(m).unwrap(), serde_json::from_str::<Value>(line).unwrap());
        }
        for m in &got[good.len()..] {
            assert!(matches!(m, ToShell::Refused { reason } if !reason.is_empty()), "accepted: {m:?}");
        }
    }

    fn asked(p: &mut Pending, id: &str) {
        let c = serde_json::json!({ "kind": "red_status", "props": { "red_count": 0, "reds": [], "hold_count": 0, "holds": [] } });
        p.saw(&serde_json::from_value(serde_json::json!({ "t": "approval_request", "session": "s", "approval": id, "component": c })).unwrap());
    }
    fn decision(id: &str) -> ToThalamus {
        ToThalamus::ApprovalDecision { approval: id.into(), decision: Decision::Reject, note: None }
    }

    #[test]
    fn pending_admits_one_decision_per_id_oldest_first() {
        let mut p = Pending::default();
        asked(&mut p, "a");
        asked(&mut p, "b");
        assert!(p.admit(&decision("b")).is_err(), "decided out of order");
        assert!(p.admit(&decision("a")).is_ok());
        assert!(p.admit(&decision("a")).is_err(), "decided twice");
        assert!(p.admit(&decision("never-asked")).is_err());
    }

    #[test]
    fn pending_refuses_a_turn_while_one_waits_but_not_a_control() {
        let mut p = Pending::default();
        let turn = ToThalamus::Turn { session: None, text: "hi".into() };
        assert!(p.admit(&turn).is_ok());
        asked(&mut p, "a");
        assert!(p.admit(&turn).is_err(), "a turn went out while an approval waits (shell.rs:173)");
        assert!(p.admit(&ToThalamus::Control { view: ControlView::Inbox }).is_ok());
        assert!(p.admit(&decision("a")).is_ok());
        assert!(p.admit(&turn).is_ok());
    }
}
