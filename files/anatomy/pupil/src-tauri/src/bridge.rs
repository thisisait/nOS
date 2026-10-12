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
    use nos_contract::wire::decode_to_thalamus;
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
        for line in good.iter().chain(&bad) {
            server.write_all(format!("{line}\n").as_bytes()).unwrap();
        }
        server.write_all(b"\xff\xfe not utf-8\n").unwrap();
        drop(server);

        let mut got = Vec::new();
        let why = pump(client, |m| got.push(m));
        assert_eq!(why, "the thalamus closed the connection");
        assert_eq!(got.len(), good.len() + bad.len() + 1, "a line was dropped: {got:?}");
        for (line, m) in good.iter().zip(&got) {
            assert_eq!(serde_json::to_value(m).unwrap(), serde_json::from_str::<Value>(line).unwrap());
        }
        for m in &got[good.len()..] {
            assert!(matches!(m, ToShell::Refused { reason } if !reason.is_empty()), "accepted: {m:?}");
        }
    }
}
