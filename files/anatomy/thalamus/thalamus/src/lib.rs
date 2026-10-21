//! The thalamus organ; cli.rs is its CLI (`serve` and the shell), run by main.rs and by the medulla.
// serve's one json! tool list outgrew the default 128 (start_agent + propose_app, 2026-10-21).
#![recursion_limit = "256"]

pub mod binding;
pub mod cli;
pub mod cortex_plan;
pub mod ledger;
pub mod relay;
pub mod septum;
pub mod serve;
pub mod shell;
pub mod store;
