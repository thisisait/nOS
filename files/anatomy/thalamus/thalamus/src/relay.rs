//! The optic nerve: serve's second door, TCP on 127.0.0.1 for the face BFF (row thalamus-web-relay).
//! The first line is one hello, decoded apart from ToThalamus so the wire's enums stay closed:
//! {relay:"face", secret, uid, username, groups, tab}. The secret proves the face sent it; the
//! receptor's identity map must name the person (D1), and its groups are used, never the hello's.
//! After it, the same converse() as the socket. Loopback, one process holds both ends' trust:
//! no HMAC or replay guard (the face-wing.yml replay ruling); a signed hello only off-loopback.

use crate::serve::{self, Server};
use nos_contract::uid;
use nos_contract::wire::{encode, ToShell};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

const HELLO: [&str; 6] = ["relay", "secret", "uid", "username", "groups", "tab"];
const MAX_HELLO: u64 = 8 << 10;
/// A tab that says nothing is closed, not held.
const HELLO_SECS: u64 = 10;
/// How long a new tab waits for the tab it takes over to close its session (then goes on).
const TAKEOVER_SECS: u64 = 5;

pub struct Relay {
    srv: Arc<Server>,
    secret: String,
    tabs: Mutex<Tabs>,
    gone: Condvar,
}

#[derive(Default)]
struct Tabs {
    /// The person's current tab: (connection id, its stream).
    by_uid: HashMap<String, (u64, TcpStream)>,
    /// Connections still running converse().
    live: HashSet<u64>,
    next: u64,
}

/// The door, on loopback only; None when the secret is empty (no face, no port).
pub fn bind(secret: &str, port: u16) -> std::io::Result<Option<TcpListener>> {
    if secret.is_empty() {
        return Ok(None);
    }
    TcpListener::bind(("127.0.0.1", port)).map(Some)
}

pub fn run(listener: TcpListener, relay: Arc<Relay>) {
    for conn in listener.incoming().flatten() {
        let relay = relay.clone();
        std::thread::spawn(move || relay.connection(conn));
    }
}

/// Equal without an early exit on the first differing byte.
fn same(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |d, (x, y)| d | (x ^ y)) == 0
}

fn refuse(out: &mut TcpStream, why: &str) {
    let _ = out.write_all(encode(&ToShell::Refused { reason: why.to_string(), widget: None }).as_bytes());
}

impl Relay {
    pub fn new(srv: Arc<Server>, secret: String) -> Self {
        Relay { srv, secret, tabs: Mutex::default(), gone: Condvar::new() }
    }

    /// The person and tab a hello names, or why not; the reason never carries the secret.
    fn hello(&self, line: &str) -> Result<(serve::Person, String, String, Value), String> {
        let not = || "the first line is not a relay hello".to_string();
        let v: Value = serde_json::from_str(line).map_err(|_| not())?;
        let o = v.as_object().filter(|o| o.len() == HELLO.len() && HELLO.iter().all(|k| o.contains_key(*k))).ok_or_else(not)?;
        let s = |k: &str| o[k].as_str().ok_or_else(not);
        if s("relay")? != "face" {
            return Err(not());
        }
        if self.secret.is_empty() || !same(s("secret")?.as_bytes(), self.secret.as_bytes()) {
            return Err("wrong relay secret".into());
        }
        let groups = o["groups"].clone();
        if !groups.as_array().is_some_and(|g| g.iter().all(Value::is_string)) {
            return Err(not());
        }
        let tab = s("tab")?;
        if tab.is_empty() || tab.len() > 64 || !tab.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
            return Err("the hello's tab is not an id".into());
        }
        let (id, username) = (s("uid")?, s("username")?);
        if !uid::is_canonical(id) {
            return Err(format!("uid {:?} is not canonical", id.chars().take(80).collect::<String>()));
        }
        if uid::canonical(username, "", "") != id {
            return Err(format!("username {:?} does not fold to {id}", username.chars().take(80).collect::<String>()));
        }
        let who = serve::person_by_uid(id, &self.srv.map).ok_or_else(|| format!("{id} is not in the identity map"))?;
        Ok((who, id.to_string(), tab.to_string(), groups))
    }

    fn connection(&self, mut out: TcpStream) {
        let Ok(input) = out.try_clone() else { return };
        let mut input = BufReader::new(input);
        let _ = out.set_read_timeout(Some(Duration::from_secs(HELLO_SECS)));
        let mut line = String::new();
        let read = input.by_ref().take(MAX_HELLO).read_line(&mut line);
        let said = match read {
            Ok(_) if line.ends_with('\n') => self.hello(&line),
            _ => Err("no relay hello".into()),
        };
        let (who, id, tab, groups) = match said {
            Ok(x) => x,
            Err(why) => {
                self.srv.say(format!("refused a relay hello: {why}"));
                refuse(&mut out, &why);
                // Closing over unread bytes is a TCP reset that can beat the refusal: drain, never parse.
                let _ = out.shutdown(Shutdown::Write);
                let _ = out.set_read_timeout(Some(Duration::from_secs(1)));
                let _ = std::io::copy(&mut input.take(MAX_HELLO), &mut std::io::sink());
                return;
            }
        };
        let _ = out.set_read_timeout(None);
        let me = self.take_over(&id, &tab, &out);
        self.srv.say(format!("connected {id} via face tab {tab} (the hello's groups {groups}; the map's are used)"));
        let peer = json!({"via": "face", "tab": tab, "uid": id});
        self.srv.converse(who, input, out, &|| peer.clone());
        let mut t = self.tabs.lock().unwrap_or_else(|p| p.into_inner());
        t.live.remove(&me);
        if t.by_uid.get(&id).is_some_and(|(c, _)| *c == me) {
            t.by_uid.remove(&id);
        }
        self.gone.notify_all();
    }

    /// D3: this tab becomes the person's; the older one is told, closed, and given a moment to end
    /// its session, so a Resume here finds it. ponytail: the refusal is written from this thread
    /// and can interleave with a line the older tab is mid-way through; fan-out is its own row.
    fn take_over(&self, id: &str, tab: &str, out: &TcpStream) -> u64 {
        let mut t = self.tabs.lock().unwrap_or_else(|p| p.into_inner());
        t.next += 1;
        let me = t.next;
        t.live.insert(me);
        let old = match out.try_clone() {
            Ok(c) => t.by_uid.insert(id.to_string(), (me, c)),
            Err(_) => None,
        };
        let Some((was, mut old)) = old else { return me };
        refuse(&mut old, "opened in another tab");
        let _ = old.shutdown(Shutdown::Both);
        self.srv.say(format!("{id}: tab {tab} takes over"));
        let _ = self.gone.wait_timeout_while(t, Duration::from_secs(TAKEOVER_SECS), |t| t.live.contains(&was));
        me
    }
}
