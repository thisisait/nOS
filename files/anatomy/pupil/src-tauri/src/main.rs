//! The pupil: Iris's desktop window. It holds no secret and opens no port; the
//! webview reaches the thalamus only through these two commands and the
//! `to_shell` / `link` events (bridge.rs owns the socket and the decoding).
#![cfg_attr(test, allow(dead_code))]

mod bridge;

use nos_contract::wire::ToThalamus;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Default)]
struct Link(Mutex<Option<UnixStream>>);

fn link_event(app: &AppHandle, state: &str, reason: Option<String>) {
    let _ = app.emit("link", serde_json::json!({ "state": state, "reason": reason }));
}

#[tauri::command]
fn connect(app: AppHandle, link: State<'_, Link>) -> Result<(), String> {
    let mut held = link.0.lock().map_err(|e| e.to_string())?;
    if held.is_some() {
        return Ok(());
    }
    let stream = bridge::connect(&bridge::socket_path()?)?;
    let reader = stream.try_clone().map_err(|e| e.to_string())?;
    *held = Some(stream);
    link_event(&app, "connected", None);
    std::thread::spawn(move || {
        let why = bridge::pump(reader, |m| {
            let _ = app.emit("to_shell", m);
        });
        if let Ok(mut held) = app.state::<Link>().0.lock() {
            *held = None;
        }
        link_event(&app, "closed", Some(why));
    });
    Ok(())
}

#[tauri::command]
fn send(msg: ToThalamus, link: State<'_, Link>) -> Result<(), String> {
    let mut held = link.0.lock().map_err(|e| e.to_string())?;
    bridge::send(held.as_mut().ok_or("not connected")?, &msg)
}

// generate_context! needs the built page (../dist); the bridge tests do not.
#[cfg(test)]
fn main() {}

#[cfg(not(test))]
fn main() {
    tauri::Builder::default()
        .manage(Link::default())
        .invoke_handler(tauri::generate_handler![connect, send])
        .run(tauri::generate_context!())
        .expect("the pupil failed to start");
}
