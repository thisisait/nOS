//! One binary, two modes: `thalamus serve` is the daemon, bare `thalamus` the shell.
//! The shell lands in increment 7.

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
    eprintln!("thalamus: {} -> {keap_url} (map ~/{IDENTITY_MAP}, secret {}, model {})", sock.display(),
              if secret.is_empty() { "UNSET" } else { "set" },
              binding.as_ref().map(|b| b.model_id.as_str()).unwrap_or("REFUSED"));
    let srv = Server {
        map: home.join(IDENTITY_MAP),
        keap_url,
        secret,
        ledger: Mutex::new(ledger),
        binding,
        repo,
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
        None => eprintln!("thalamus shell: not built yet"),
        Some(other) => {
            eprintln!("thalamus: unknown mode {other:?} (serve, or none for the shell)");
            return ExitCode::from(2);
        }
    }
    ExitCode::FAILURE
}
