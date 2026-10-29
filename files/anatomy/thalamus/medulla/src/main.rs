//! The medulla: one binary for the host organs (ssot/doctrine/medulla.md §1). It carries the thalamus
//! (`medulla thalamus <args>`, or run as `thalamus`/`iris`) and Wing's moved routes (`medulla wing serve`).
//! Run as `nos-<organ>` it is `medulla <organ>`: Activity Monitor and top show the file's name.
use std::process::ExitCode;

mod metrics;
mod pulse;
mod pulse_reads;

fn main() -> ExitCode {
    let mut argv = std::env::args();
    let argv0 = argv.next().unwrap_or_default();
    let args: Vec<String> = argv.collect();
    let name = std::path::Path::new(&argv0).file_name().and_then(|n| n.to_str()).unwrap_or_default();
    match (name.strip_prefix("nos-").unwrap_or(name), args.first().map(String::as_str)) {
        ("thalamus" | "iris", _) => thalamus(&args),
        ("wing", _) => wing(&args),
        ("pulse", _) => pulse::cli(&args),
        (_, Some("thalamus")) => thalamus(&args[1..]),
        (_, Some("wing")) => wing(&args[1..]),
        (_, Some("pulse")) => pulse::cli(&args[1..]),
        (_, Some("state")) => state(&args[1..]),
        (_, Some("halt")) => halt(&args[1..], true),
        (_, Some("resume")) => halt(&args[1..], false),
        (_, Some("pause")) => pause(&args[1..], true),
        (_, Some("unpause")) => pause(&args[1..], false),
        (_, Some("--version")) => {
            println!("medulla {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        _ => usage(),
    }
}

fn usage() -> ExitCode {
    eprintln!("usage: medulla thalamus [serve --data-dir <dir>] | medulla wing serve --db <wing.db> --port <n> | medulla pulse plan --db <wing.db> | medulla state [--json] | medulla halt [--reason <text>] | medulla resume | medulla pause <job> [--reason <text>] | medulla unpause <job> | medulla --version");
    ExitCode::from(2)
}

/// `thalamus serve` on the host also opens Wing's moved routes when the role rendered both keys.
fn thalamus(args: &[String]) -> ExitCode {
    if args.first().map(String::as_str) == Some("serve") {
        let db = std::env::var("NOS_WING_DB");
        let port = std::env::var("MEDULLA_HTTP_PORT").ok().and_then(|p| p.parse::<u16>().ok());
        if let (Ok(db), Some(port)) = (db, port) {
            std::thread::spawn(move || {
                if let Err(e) = metrics::serve(db.into(), port) {
                    eprintln!("medulla wing: {e}");
                }
            });
        }
    }
    thalamus::cli::run(args)
}

/// The set-points and host organs, read-only: the socket's `state` and GET /api/v1/admin/state say the same.
fn state(args: &[String]) -> ExitCode {
    let s = thalamus::state::read();
    match args {
        [] => thalamus::state::lines(&s).iter().for_each(|l| println!("{l}")),
        [j] if j == "--json" => println!("{}", serde_json::to_string(&s).expect("the state always serializes")),
        _ => return usage(),
    }
    ExitCode::SUCCESS
}

/// `medulla halt [--reason …]` / `medulla resume`: the socket's halt and lift_halt, so serve's tier-1 and
/// decider check is the one that applies; this CLI never writes the file. Exit 0 set and recorded, 3 set
/// but NOT recorded, 1 refused (the file untouched), 69 the thalamus did not answer.
fn halt(args: &[String], on: bool) -> ExitCode {
    use nos_contract::wire::ToThalamus;
    let msg = match (on, args) {
        (true, []) => ToThalamus::Halt { reason: None },
        (true, [f, r]) if f == "--reason" => ToThalamus::Halt { reason: Some(r.clone()) },
        (false, []) => ToThalamus::LiftHalt,
        _ => return usage(),
    };
    ask(if on { "halt" } else { "resume" }, &msg)
}

/// `medulla pause <job> [--reason …]` / `medulla unpause <job>`: the socket's setting pulse.paused, one
/// entry; serve stamps who and when. Exits as halt's do.
fn pause(args: &[String], on: bool) -> ExitCode {
    let entry = match (on, args) {
        (true, [_]) => serde_json::json!({}),
        (true, [_, f, r]) if f == "--reason" => serde_json::json!({"reason": r}),
        (false, [_]) => serde_json::Value::Null,
        _ => return usage(),
    };
    let value = serde_json::json!({ args[0].as_str(): entry });
    ask(if on { "pause" } else { "unpause" }, &nos_contract::wire::ToThalamus::Setting { key: "pulse.paused".into(), value })
}

fn ask(verb: &str, msg: &nos_contract::wire::ToThalamus) -> ExitCode {
    use nos_contract::wire::{decode_to_shell, encode, ToShell};
    use std::io::{BufRead, Write};
    let home = std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    let sock = thalamus::serve::socket_path(std::env::var("THALAMUS_SOCKET").ok().as_deref(), &home,
                                            std::path::Path::new(thalamus::serve::SHARED_SOCKET));
    let answer = (|| -> std::io::Result<String> {
        let mut s = std::os::unix::net::UnixStream::connect(&sock)?;
        // Wing's record has 10 s; past this the halt may or may not be set, and the caller reads state.
        s.set_read_timeout(Some(std::time::Duration::from_secs(20)))?;
        s.write_all(encode(msg).as_bytes())?;
        let mut line = String::new();
        std::io::BufReader::new(s).read_line(&mut line)?;
        Ok(line)
    })();
    match answer {
        Err(e) => eprintln!("medulla {verb}: the thalamus did not answer at {}: {e}", sock.display()),
        Ok(l) if l.is_empty() => eprintln!("medulla {verb}: the thalamus closed {} without an answer", sock.display()),
        Ok(l) => match decode_to_shell(&l) {
            ToShell::State(s) => {
                thalamus::state::lines(&s).iter().for_each(|l| println!("{l}"));
                return if s.act.is_some_and(|a| a.recorded) { ExitCode::SUCCESS } else { ExitCode::from(3) };
            }
            ToShell::Refused { reason, .. } => {
                eprintln!("medulla {verb}: refused — {reason}");
                return ExitCode::FAILURE;
            }
            other => eprintln!("medulla {verb}: an answer that is not state: {}", encode(&other).trim_end()),
        },
    }
    ExitCode::from(69)
}

fn wing(args: &[String]) -> ExitCode {
    let flag = |f: &str| args.iter().position(|a| a == f).and_then(|i| args.get(i + 1));
    let port = flag("--port").and_then(|p| p.parse::<u16>().ok());
    match (args.first().map(String::as_str), flag("--db"), port) {
        (Some("serve"), Some(db), Some(port)) => match metrics::serve(db.into(), port) {
            Ok(()) => ExitCode::SUCCESS,
            Err(e) => {
                eprintln!("medulla wing: {e}");
                ExitCode::FAILURE
            }
        },
        _ => usage(),
    }
}
