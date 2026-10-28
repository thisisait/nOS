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
        (_, Some("--version")) => {
            println!("medulla {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        _ => usage(),
    }
}

fn usage() -> ExitCode {
    eprintln!("usage: medulla thalamus [serve --data-dir <dir>] | medulla wing serve --db <wing.db> --port <n> | medulla pulse plan --db <wing.db> | medulla state [--json] | medulla --version");
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
