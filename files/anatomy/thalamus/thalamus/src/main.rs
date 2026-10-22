//! `thalamus serve` is the daemon, bare `thalamus` the shell: src/cli.rs, which the medulla also runs.
fn main() -> std::process::ExitCode {
    thalamus::cli::run(&std::env::args().skip(1).collect::<Vec<_>>())
}
