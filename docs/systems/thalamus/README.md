# Thalamus

> One person at a terminal works with Iris. The model picks the tools; the
> thalamus runs them as that person through KEAP's human door. A write lands
> only after the person approves its cell diff, and every step is in the ledger.

## Quick Reference

| | |
|---|---|
| **Type** | Host organ (non-Docker), one Rust binary in two modes |
| **Daemon** | `thalamus serve` on `~/.nos/thalamus.sock`, mode 0600 |
| **Shell** | `~/thalamus/bin/thalamus` (no argument) |
| **Toggle** | `install_thalamus` (default `false`; needs `install_receptor`) |
| **Map** | the receptor's `~/.nos/identity-map.yml` (`nos_identity_map`) |
| **Cell** | `iris` (`files/anatomy/agents/iris/agent.yml`), on ollama |
| **Manifest id** | `thalamus` |
| **launchd label** | `eu.thisisait.nos.thalamus` (no Linux unit yet) |
| **Ledger** | `~/thalamus/data/ledger.db` (dir 0700) |
| **Logs** | `~/thalamus/log/` (0700) |
| **Reader** | `tools/thalamus-status.py` |

Values from `roles/pazny.thalamus/`, `files/anatomy/thalamus/thalamus/src/`,
`default.config.yml`, `state/manifest.yml`.

## Who is speaking

The kernel names the peer's uid (`getpeereid`). That login is looked up in the
receptor's identity map on every connection. A login that is not there, or a
map that cannot be read, gets `Refused` and the connection closes. Nobody is
ever given a default person. KEAP sees the person's `X-Authentik-*` headers and
the proxy secret; the thalamus is a proxy-secret holder of its own (operator
ruling 2026-10-11), it does not go through the receptor's socket.

## What Iris can do

- `search_rows{table, q, limit<=20}`: every page of rows the person can see,
  filtered by substring, shown as `table_results` with `projected:false`.
- `propose_row_edit{table, row_id, values}`: the cells that change are written
  to the ledger as `agent_approval_request`, then shown as `row_diff_approval`.
  Only an approve decision for that request, in that session, by that person,
  lets the one POST through. Reject writes nothing to KEAP.

The shell raises three views without the model: F2 inbox, F3 approvals
(`tools/awaiting-operator.py`), F4 red status (`tools/red-status.py`).

## The wire and the ledger

The wire is `files/anatomy/contracts/thalamus-shell.yml` (newline-delimited
JSON). The ledger's columns are a subset of Wing's `agent_sessions` and
`events`; the serve process is its only writer.

## Health

`ansible-playbook main.yml --tags receptor,thalamus,verify` runs
`tools/thalamus-status.py --json` and fails on any line that is not OK: the
socket is a socket with mode 0600, the launchd job is loaded, the ledger is
readable in a 0700 dir. The last session is reported, not judged.
