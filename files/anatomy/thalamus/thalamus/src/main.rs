//! One binary, two modes: `thalamus serve` is the daemon, bare `thalamus` the shell.

use std::os::unix::fs::DirBuilderExt;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::{Arc, Mutex};
use thalamus::binding::{self, Decision};
use thalamus::ledger::Ledger;
use thalamus::serve::{self, Server, IDENTITY_MAP};

fn serve_main() -> Result<(), String> {
    let home = PathBuf::from(std::env::var("HOME").map_err(|_| "HOME is not set")?);
    let repo = PathBuf::from(std::env::var("NOS_REPO_ROOT").map_err(|_| "NOS_REPO_ROOT is not set")?);
    let secret = std::env::var("KEAP_PROXY_SHARED_SECRET").unwrap_or_default();
    // Read once, then gone: no child this process spawns inherits the secret.
    std::env::remove_var("KEAP_PROXY_SHARED_SECRET");
    // Without it KEAP refuses every call: exit, so launchd and the reader show a dead daemon.
    if secret.is_empty() {
        return Err("KEAP_PROXY_SHARED_SECRET is unset or empty".into());
    }
    let data = home.join("thalamus/data");
    std::fs::DirBuilder::new().recursive(true).mode(0o700).create(&data).map_err(|e| format!("{}: {e}", data.display()))?;
    let ledger = Ledger::open(&data.join("ledger.db")).map_err(|e| format!("ledger: {e}"))?;
    let binding = match binding::resolve(&repo, "iris", |k| std::env::var(k).ok()) {
        Ok(Decision::Bound(b)) => Ok(b),
        Ok(other) => Err(format!("iris has no model: {other:?}")),
        Err(why) => Err(why),
    };
    let sock = home.join(".nos/thalamus.sock");
    let listener = serve::bind(&sock).map_err(|e| format!("{}: {e}", sock.display()))?;
    let keap_url = std::env::var("KEAP_URL").unwrap_or_else(|_| "http://127.0.0.1:8091".into());
    eprintln!("thalamus: {} -> {keap_url} (map ~/{IDENTITY_MAP})", sock.display());
    // One line tools/thalamus-status.py reads from launchd's stderr log; the why stays on it.
    match &binding {
        Ok(b) => eprintln!("thalamus: model bound {}-{}", b.name, b.model_id),
        Err(why) => eprintln!("thalamus: model UNBOUND: {}", why.replace('\n', " ")),
    }
    let srv = Server {
        map: home.join(IDENTITY_MAP),
        keap_url,
        secret,
        ledger: Mutex::new(ledger),
        binding,
        repo,
        reader_secs: serve::READER_SECS,
        // Unset or empty: nobody is tier 1, so the operator views refuse everyone.
        tier1: std::env::var("NOS_TIER1_GROUPS").unwrap_or_default().split(',').filter(|g| !g.is_empty())
            .map(str::to_string).collect(),
        log: Mutex::new(Box::new(std::io::stderr())),
    };
    serve::run(listener, Arc::new(srv));
    Ok(())
}

fn main() -> ExitCode {
    match std::env::args().nth(1).as_deref() {
        Some("serve") => match serve_main() {
            Ok(()) => return ExitCode::SUCCESS,
            Err(why) => eprintln!("thalamus serve: {why}"),
        },
        None => match std::env::var("HOME") {
            Ok(home) => match thalamus::shell::run(&PathBuf::from(home).join(".nos/thalamus.sock")) {
                Ok(()) => return ExitCode::SUCCESS,
                Err(why) => eprintln!("thalamus: {why}"),
            },
            Err(_) => eprintln!("thalamus: HOME is not set"),
        },
        Some(other) => {
            eprintln!("thalamus: unknown mode {other:?} (serve, or none for the shell)");
            return ExitCode::from(2);
        }
    }
    ExitCode::FAILURE
}
