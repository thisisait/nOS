//! The thalamus CLI, two modes: `thalamus serve` is the daemon, bare `thalamus` the shell.
//! Called by src/main.rs and by the medulla (`medulla thalamus …`, or argv[0] `thalamus`/`iris`).

use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::{Arc, Mutex};
use crate::binding::{self, Decision};
use crate::ledger::Ledger;
use crate::serve::{self, Server, IDENTITY_MAP};

/// THALAMUS_SOCKET for both modes; THALAMUS_SOCKET_SHARED=1 opens it 0666 — the peer's uid
/// still has to be in the identity map, so a wider mode admits no one the map does not name.
fn socket_path(home: &std::path::Path) -> PathBuf {
    serve::socket_path(std::env::var("THALAMUS_SOCKET").ok().as_deref(), home, std::path::Path::new(serve::SHARED_SOCKET))
}

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
    let sock = socket_path(&home);
    let shared = std::env::var("THALAMUS_SOCKET_SHARED").is_ok_and(|v| v == "1");
    let listener = serve::bind(&sock, if shared { 0o666 } else { 0o600 }).map_err(|e| format!("{}: {e}", sock.display()))?;
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
        .map(|url| crate::cortex_plan::Cortex { url, token: lookup("nos:cortex_ro_token").unwrap_or_default(),
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
        tier1: groups("NOS_TIER1_GROUPS"),
        tier2: groups("NOS_TIER2_GROUPS"),
        // Off unless the operator sets thalamus_decider_exes: the role renders it ':'-joined.
        deciders,
        log: Mutex::new(Box::new(std::io::stderr())),
        picks,
        floors,
        cortex,
        data,
        // iris_knowledge_tree_max; the contract carries at most KNOWLEDGE_MAX.
        tree_max: std::env::var("NOS_IRIS_KNOWLEDGE_TREE_MAX").ok().and_then(|v| v.trim().parse().ok())
            .unwrap_or(50usize).clamp(1, nos_contract::renderers::KNOWLEDGE_MAX),
        // start_agent's door: the role renders all three with thalamus_wing_api_token, or none.
        wing: serve::WingDoor {
            url: std::env::var("NOS_WING_URL").unwrap_or_default(),
            token: lookup("nos:wing_token").unwrap_or_default(),
            agents: std::env::var("NOS_IRIS_STARTABLE_AGENTS").unwrap_or_default().split(',').map(str::trim)
                .filter(|a| !a.is_empty()).map(str::to_string).collect(),
        },
    };
    let srv = Arc::new(srv);
    // One line tools/thalamus-status.py reads: bound iff the secret is set. A failed bind keeps the socket serving.
    let port = relay_port.unwrap_or_default();
    let bound = match relay_port {
        Some(p) => crate::relay::bind(&relay_secret, p),
        None if relay_secret.is_empty() => Ok(None),
        None => Err(std::io::Error::other("THALAMUS_RELAY_PORT is unset or not a port")),
    };
    match bound {
        Ok(Some(l)) => {
            // The address the socket actually holds (THALAMUS_RELAY_HOST may move it to docker0).
            let at = l.local_addr().map(|a| a.to_string()).unwrap_or_else(|_| format!("?:{port}"));
            eprintln!("thalamus: relay bound {at}");
            let door = Arc::new(crate::relay::Relay::new(srv.clone(), relay_secret));
            std::thread::spawn(move || crate::relay::run(l, door));
        }
        Ok(None) => eprintln!("thalamus: relay closed (no THALAMUS_RELAY_SECRET)"),
        // The socket keeps serving, and the door is retried: on Linux it binds docker0's
        // address, which exists only once Docker is up — a boot-order race, not a fault.
        Err(e) => {
            let host = std::env::var("THALAMUS_RELAY_HOST").unwrap_or_else(|_| "127.0.0.1".into());
            eprintln!("thalamus: relay FAILED {host}:{port}: {e} — retrying every 5 s");
            if let Some(p) = relay_port {
                let srv = srv.clone();
                std::thread::spawn(move || loop {
                    std::thread::sleep(std::time::Duration::from_secs(5));
                    if let Ok(Some(l)) = crate::relay::bind(&relay_secret, p) {
                        let at = l.local_addr().map(|a| a.to_string()).unwrap_or_else(|_| format!("?:{p}"));
                        eprintln!("thalamus: relay bound {at}");
                        let door = Arc::new(crate::relay::Relay::new(srv, relay_secret));
                        crate::relay::run(l, door);
                        return;
                    }
                });
            }
        }
    }
    serve::run(listener, srv);
    Ok(())
}

/// `args` are the words after the program name.
pub fn run(args: &[String]) -> ExitCode {
    match args.first().map(String::as_str) {
        Some("serve") => match serve_main(&args[1..]) {
            Ok(()) => return ExitCode::SUCCESS,
            Err(why) => eprintln!("thalamus serve: {why}"),
        },
        None => match std::env::var("HOME") {
            Ok(home) => match crate::shell::run(&socket_path(&PathBuf::from(home))) {
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

/// A comma-joined group list from the environment; unset or empty is nobody.
fn groups(var: &str) -> Vec<String> {
    std::env::var(var).unwrap_or_default().split(',').filter(|g| !g.is_empty()).map(str::to_string).collect()
}
