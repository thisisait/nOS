//! The pupil: Iris's desktop window. It holds no secret and opens no port; the
//! webview reaches the thalamus only through these two commands and the
//! `to_shell` / `link` events (bridge.rs owns the socket and the decoding).
#![cfg_attr(test, allow(dead_code))]

use nos_contract::wire::ToThalamus;
use nos_pupil::bridge;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};

/// The open socket and what it is waiting on; both go when the link closes.
#[derive(Default)]
struct Link(Mutex<Option<(UnixStream, bridge::Pending)>>);

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
    *held = Some((stream, bridge::Pending::default()));
    link_event(&app, "connected", None);
    std::thread::spawn(move || {
        let why = bridge::pump(reader, |m| {
            // Recorded before the webview sees it, so a decision is never ahead of its request.
            if let Some((_, p)) = app.state::<Link>().0.lock().ok().as_mut().and_then(|h| h.as_mut()) {
                p.saw(&m);
            }
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
    let (stream, pending) = held.as_mut().ok_or("not connected")?;
    pending.admit(&msg)?;
    bridge::send(stream, &msg)
}

// generate_context! needs the built page (../dist); the bridge tests do not.
#[cfg(test)]
fn main() {}

#[cfg(test)]
mod launch_hook {
    use super::focus_on_launch;

    /// Stores the hook and drops the builder. No context, so no window opens.
    #[test]
    fn focus_on_launch_is_a_setup_hook() {
        let _ = tauri::Builder::default().setup(focus_on_launch);
    }
}

/// Focus the main window once it exists.
///
/// macOS activates the app in applicationDidFinishLaunching. This window is
/// built later, on Ready. Creation orders it front and does not activate, so
/// the first launch sometimes stays behind. set_focus does both, once.
fn focus_on_launch(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let window = app.get_webview_window("main").expect("main window");
    window.set_focus()?;
    Ok(())
}

#[cfg(not(test))]
fn main() {
    tauri::Builder::default()
        .manage(Link::default())
        .invoke_handler(tauri::generate_handler![connect, send])
        .setup(focus_on_launch)
        .run(tauri::generate_context!())
        .expect("the pupil failed to start");
}
