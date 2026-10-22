//! The medulla: one binary for the host organs (ssot/doctrine/medulla.md §1). Today it carries the
//! thalamus only: `medulla thalamus <args>`, or run as `thalamus`/`iris` (the coexistence copy, or a link).
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut argv = std::env::args();
    let argv0 = argv.next().unwrap_or_default();
    let args: Vec<String> = argv.collect();
    let name = std::path::Path::new(&argv0).file_name().and_then(|n| n.to_str()).unwrap_or_default();
    match (name, args.first().map(String::as_str)) {
        ("thalamus" | "iris", _) => thalamus::cli::run(&args),
        (_, Some("thalamus")) => thalamus::cli::run(&args[1..]),
        (_, Some("--version")) => {
            println!("medulla {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        _ => {
            eprintln!("usage: medulla thalamus [serve --data-dir <dir>] | medulla --version");
            ExitCode::from(2)
        }
    }
}
