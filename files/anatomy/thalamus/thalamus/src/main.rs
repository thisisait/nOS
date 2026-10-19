//! One binary, two modes: `thalamus serve` is the daemon, bare `thalamus` the shell.

use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::{Arc, Mutex};
use thalamus::binding::{self, Decision};
use thalamus::ledger::Ledger;
use thalamus::serve::{self, Server, IDENTITY_MAP};

fn serve_main(args: &[String]) -> Result<(), String> {
    let home = PathBuf::from(std::env::var("HOME").map_err(|_| "HOME is not set")?);
    let repo = PathBuf::from(std::env::var("NOS_REPO_ROOT").map_err(|_| "NOS_REPO_ROOT is not set")?);
    let secret = std::env::var("KEAP_PROXY_SHARED_SECRET").unwrap_or_default();
    // Read once, then gone: no child this process spawns inherits the secret.
    std::env::remove_var("KEAP_PROXY_SHARED_SECRET");
    // Without it KEAP refuses every call: exit, so launchd and the reader show a dead daemon.
    if secret.is_empty() {
        return Err("KEAP_PROXY_SHARED_SECRET is unset or empty".into());
    }
    // The face's door (src/relay.rs), read once and removed the same way; empty = no listener.
    let relay_secret = std::env::var("THALAMUS_RELAY_SECRET").unwrap_or_default();
    std::env::remove_var("THALAMUS_RELAY_SECRET");
    // The role's thalamus_relay_port; no second spelling of it here.
    let relay_port = std::env::var("THALAMUS_RELAY_PORT").ok().and_then(|p| p.parse::<u16>().ok()).filter(|p| *p != 0);
    // The role derives it from nos_data_root; no default, so a bare `serve` cannot write elsewhere.
    let data = match args {
        [flag, dir] if flag == "--data-dir" && !dir.is_empty() => PathBuf::from(dir),
        _ => return Err("usage: thalamus serve --data-dir <dir>".into()),
    };
    let dir_err = |e: std::io::Error| format!("{}: {e}", data.display());
    std::fs::DirBuilder::new().recursive(true).mode(0o700).create(&data).map_err(dir_err)?;
    // create() leaves an existing dir as it was; a wider one would expose the ledger.
    std::fs::set_permissions(&data, std::fs::Permissions::from_mode(0o700)).map_err(dir_err)?;
    let ledger = Ledger::open(&data.join("ledger.db")).map_err(|e| format!("ledger: {e}"))?;
    // The bound row's key (the role renders NOS_SECRET_<VAR> for auth_secret nos:<var>): read
    // once and removed like the proxy secret; it leaves only as the model request's bearer.
    let vault: Vec<(String, String)> = std::env::vars().filter(|(k, _)| k.starts_with("NOS_SECRET_")).collect();
    vault.iter().for_each(|(k, _)| std::env::remove_var(k));
    let lookup = |k: &str| match k.strip_prefix("nos:") {
        Some(var) => vault.iter().find(|(n, _)| *n == format!("NOS_SECRET_{}", var.to_uppercase())).map(|(_, v)| v.clone()),
        None => std::env::var(k).ok(),
    };
    // The role renders both floors (llm_cell_*_params_b); unset = judged only by the converge preflight.
    let floor = |k: &str| std::env::var(k).ok().and_then(|v| v.trim().parse::<f64>().ok());
    let mut warning = None;
    let picks = binding::resolve_picks(&repo, "iris", &lookup);
    let floors = floor("NOS_LLM_MIN_PARAMS_B").map(|min| (min, floor("NOS_LLM_RECOMMENDED_PARAMS_B").unwrap_or(min)));
    let binding = match binding::resolve(&repo, "iris", &lookup) {
        Ok(Decision::Bound(b)) => match floor("NOS_LLM_MIN_PARAMS_B") {
            Some(min) if b.local => binding::size_floor(&b.model_id, min, floor("NOS_LLM_RECOMMENDED_PARAMS_B").unwrap_or(min))
                .map(|w| { warning = w; b }),
            _ => Ok(b),
        },
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
    if let Some(w) = warning {
        eprintln!("thalamus: WARNING {w}");
    }
    // iris_plan: cortex|hybrid (the role renders NOS_IRIS_PLAN, NOS_IRIS_INTENTS, NOS_CORTEX_URL and the RO token
    // as nos:cortex_ro_token); hybrid plans only the turns whose intent is listed.
    let plan = std::env::var("NOS_IRIS_PLAN").unwrap_or_default();
    let planned = plan == "cortex" || plan == "hybrid";
    let cortex = std::env::var("NOS_CORTEX_URL").ok().filter(|u| !u.is_empty() && planned)
        .map(|url| thalamus::cortex_plan::Cortex { url, token: lookup("nos:cortex_ro_token").unwrap_or_default(),
            rich_catalogue: std::env::var("NOS_CORTEX_CATALOGUE").as_deref() == Ok("rich"),
            intents: (plan == "hybrid").then(|| std::env::var("NOS_IRIS_INTENTS").unwrap_or_default().split(',')
                .map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect()) });
    match &cortex {
        Some(c) => eprintln!("thalamus: iris plans in cortex-lang via {}, catalogue {}, {}", c.url,
            if c.rich_catalogue { "rich" } else { "lean" },
            c.intents.as_ref().map_or("every turn".into(), |i| format!("hybrid: {}", i.join(",")))),
        None if planned => eprintln!("thalamus: WARNING iris_plan is {plan} but \
            NOS_CORTEX_URL is unset (install_cortex off?): iris plans with tools"),
        None => {}
    }
    let (deciders, warnings) = serve::deciders(&std::env::var("NOS_DECIDER_EXES").unwrap_or_default());
    warnings.iter().for_each(|w| eprintln!("thalamus: WARNING {w}"));
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
        // Off unless the operator sets thalamus_decider_exes: the role renders it ':'-joined.
        deciders,
        log: Mutex::new(Box::new(std::io::stderr())),
        picks,
        floors,
        cortex,
        data,
    };
    let srv = Arc::new(srv);
    // One line tools/thalamus-status.py reads: bound iff the secret is set. A failed bind keeps the socket serving.
    let port = relay_port.unwrap_or_default();
    let bound = match relay_port {
        Some(p) => thalamus::relay::bind(&relay_secret, p),
        None if relay_secret.is_empty() => Ok(None),
        None => Err(std::io::Error::other("THALAMUS_RELAY_PORT is unset or not a port")),
    };
    match bound {
        Ok(Some(l)) => {
            eprintln!("thalamus: relay bound 127.0.0.1:{port}");
            let door = Arc::new(thalamus::relay::Relay::new(srv.clone(), relay_secret));
            std::thread::spawn(move || thalamus::relay::run(l, door));
        }
        Ok(None) => eprintln!("thalamus: relay closed (no THALAMUS_RELAY_SECRET)"),
        Err(e) => eprintln!("thalamus: relay FAILED 127.0.0.1:{port}: {e}"),
    }
    serve::run(listener, srv);
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("serve") => match serve_main(&args[2..]) {
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
