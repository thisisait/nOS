//! One binary, two modes: `thalamus serve` is the daemon, bare `thalamus` the shell.
//! Both are empty in this increment; the wire contract lands next.

use std::process::ExitCode;

fn main() -> ExitCode {
    match std::env::args().nth(1).as_deref() {
        Some("serve") => eprintln!("thalamus serve: not built yet"),
        None => eprintln!("thalamus shell: not built yet"),
        Some(other) => {
            eprintln!("thalamus: unknown mode {other:?} (serve, or none for the shell)");
            return ExitCode::from(2);
        }
    }
    ExitCode::FAILURE
}
