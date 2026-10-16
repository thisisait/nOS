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
| **Cell** | `iris` (`files/anatomy/agents/iris/agent.yml`), on `mistral-eu` (Mistral Large, EU endpoint; ruling 2026-10-12) |
| **Manifest id** | `thalamus` |
| **launchd label** | `eu.thisisait.nos.thalamus` (no Linux unit yet) |
| **Ledger** | `{nos_data_root}/platform/services/thalamus/data/ledger.db` (dir 0700; `thalamus_data_dir`, passed as `serve --data-dir`) |
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

- `query_rows{table, q?, where?, columns?, order_by?, limit 0..50}`: one
  `GET /api/tables/:id` for the title and columns, then every page of rows the
  person can see, filtered, sorted and cut in the thalamus (never a partial
  table). Shown as `table_results` with `name`, `query`, `matched` and `total`
  (the exact count of readable rows, never KEAP's `rowCount`), `projected:false`.
  `group_by` (+ `op`, `y`) counts, sums or averages per value; `op` without
  `group_by` is one total over every matched row. A `where` may be `between`
  `[from, to]` (inclusive), and a date column takes `today` … `this_year`,
  resolved on the host's calendar and said resolved in `query`. An exact text miss adds a `hint`.
- `propose_row_edit{table, row_id, values}`: refused unless a `query_rows` in
  this session showed that row (no KEAP read, no card). The cells that change are written
  to the ledger as `agent_approval_request`, then shown as `row_diff_approval`.
  Only an approve decision for that request, in that session, by that person,
  lets the one POST through. Reject writes nothing to KEAP.
- `propose_table_create{title, description?, columns}`: a new DataTable, private to
  the person, as one `table_schema_approval` card (every column's kind, options,
  required). At most 30 columns of text, number, date, select (1-50 options), bool
  or rowRef (to a table the person can read, by title); a bare label is a text
  column and key/label casing is repaired, anything else is refused with why. A
  title the person already has is refused. Approve POSTs `/api/tables` as the
  person, reads it back, and the session can insert into it at once.
- `propose_column_add{table, columns}`: new columns for a table this session queried
  or created, as one `column_add_approval` card (the table's columns read-only, then
  the new ones). Columns as in a create, never required (existing rows get no
  value); a key the table has is refused. Approve re-reads the table and adds
  nothing if its columns moved, PATCHes the whole list as the person (a 403 is said),
  reads it back, and the new columns take values at once.
- `show{component}`: draws one component of `SHOW_KINDS` (serve.rs; among them
  `chart` in six kinds over a category, number or time axis, `timeline`, `graph`;
  inline SVG in the pupil, values as text in the terminal) the model builds. Unknown fields and over-cap components are refused (`Component::check`,
  also in every shell's decoder) and only the model hears why. It can never draw
  an approval or a kind a tool or a control draws. A `kpi` (one number on a tile) is
  drawn only with `source {query, op, y?}`: serve computes the total, drops any number
  the model sent, and pins `{kpi}` so the tile re-runs. A rows widget exports the rows
  it shows as CSV (pupil `csv.ts`, formula cells apostrophed) to a new file in Downloads.

The shell raises three views without the model: F2 inbox, F3 approvals
(`tools/awaiting-operator.py`), F4 red status (`tools/red-status.py`).

## Whom the person works for (the septum)

`/for <client>`, `/for personal` or `/for all` (terminal and pupil composer) sends
`working_for`. serve resolves the client against the party rows of role `client`
(an unknown one is refused, naming the clients), reads each table def's
`client_scope` from `state/keap-tables` (`src/septum.rs`, the vocabulary of
`tools/septum-status.py`), records the switch in the ledger and forgets the rows
shown before. Reads then honour it: a `book_owner`, `self` or `rowRef:` table keeps
that client's rows only (personal: no client's) and the query says so; a personal
table, a table Iris made for another client, or one no def declares is hidden from
query_rows, widgets, forms and dashboard offers, and list_tables names it as hidden.
A table Iris creates while working for a client is that client's (the create's
ledger result names it). Both shells show the scope on the turn and on the card; a
switch is refused while a card waits. An insert or edit whose row would be another
client's (or personal) names whose in its title and warning (after a misnamed-row
warning, joined) and is written only on a second approve. `search_memory` for a
client keeps the shared taxonomy only: a capture, note or object is the person's (or
its hit does not say whose), so it is dropped and the result says "hidden by scope: n";
on personal data nothing is dropped (KEAP 2.1.0 search returns no DataTable rows).
`inbox` for a client reads no captures and names them as refused ("personal");
the moderation queue (proposed promotions) is still shown.
serve holds the wall per connection; the pupil says it again on a reconnect and re-runs
its widgets when it changes. Not yet covered: rowRef selects in forms (they list every
parent row), and an insert_many's lines (only the parent row is walked).

## Widgets and forms

A widget is a spec the pupil stores in its workspace layout
(`files/anatomy/contracts/workspace-layout.yml`) and re-runs as the person over a
`widget` message, without the model: `rows` (a `query_rows`), `chart` (serve
groups and sums, counts or averages one column server side) or `form` (built by
serve from the live KEAP schema; the model has no form). A widget run never
extends what the model was shown, and each one is a ToolUse/ToolResult pair
(`widget_rows|widget_chart|widget_form`) with its spec and `trigger`.

Submitting a widget form is the person's decision: under tool `form_submit` the
ledger gets the request (`op: insert`), the decision and the result, each with
the peer's `{pid, exe}`; `commit()` does the one
POST, and the shell gets `form_result` and `table_changed`.

Who may decide: `thalamus_decider_exes` (role default `[]`, off: the peer is only
recorded). When the operator sets it in `config.yml` — recommended
`[thalamus_pupil_exe, thalamus_bin]`, the pupil and the y/n terminal shell — serve
refuses a `form_submit`, `approval_decision` or `choice_reply` sent by any other
executable, or one it cannot name. The sender is read per line (macOS `LOCAL_PEERPID`,
the last process to use the socket) and its kernel path is compared to the
canonicalized entries; on Linux a set list refuses every decision. The refusal is said, recorded
with the peer and reason, and the approval, form or choice stays open. The pupil then
re-runs the widgets on the active tab that read that table; the rest go stale
until their tab is shown. The whole path runs offline in
`tests/anatomy/test_genui_workspace_poc.py` over `state/fixtures/genui-workspace-poc/`.

With the list set, a client not on it (`tools/iris-bench.py`, any python socket client)
gets a `refused` for its decision and no `idle`. A mis-set list admits nobody, so the role refuses it at render (a string, an empty,
relative or `:` entry, or a path that names no file once the pupil is built) and serve warns
at start (`serve::deciders`).

What path identity cannot stop: anything that runs code inside a listed binary. Both are
signed with the local identity but without the hardened runtime (`codesign --options
runtime`), so `DYLD_INSERT_LIBRARIES` or a debugger attach by the same user still decides
as the pupil, and so does whoever can replace the file at a listed path. The list stops
another program from sending a decision; it is not a defence against code running as you.
Turning the hardened runtime on is an open operator decision (it must be tried live against
the pupil's webview first).

## The model

`serve` binds iris at start as `BindingResolver.php` does (`src/binding.rs`).
Iris's whole serving set is the `mistral-eu` row, so a disarmed row, an empty
`mistral_model` or a missing key refuses; it never degrades to another backend.
A host may instead choose the on-device row (ruling 2026-10-14): `iris_backend: ollama`
with `install_ollama`, `ollama_enabled` and an `ollama_model` of at least
`llm_cell_min_params_b` (3). `llm_on_host: true` (the default, ruling 2026-10-16) sets all
of that with `qwen3:4b`; under `llm_cell_recommended_params_b` (8) the preflight and `serve`
print a WARN. It is a choice the record allows (`model.backends_allowed`), not a fallback;
the preflight then judges the local model, and `serve` judges it again at start.
The key: the role renders the var behind the row's `auth_secret`
(`mistral_api_key`) into the 0600 plist as `NOS_SECRET_MISTRAL_API_KEY`. The
binary reads it once and removes it from its env. The key leaves only as the
`Authorization: Bearer` on requests to the bound `base_url`.
The system prompt starts with the imprint: `IMPRINT.md` for a cloud row,
`IMPRINT.short.md` for a local one. If that file is missing or empty, turns
are refused and the log says which file. The reader's model line shows why a
model is unbound.

The person may pick another model for the session (W5): the pupil's header select or
`/model` in the terminal sends `model_options`; serve offers every `backends_allowed` row
that is armed and passes the binding gates and `gdpr_posture` (a non-EU row only under
`none`), a local row once per model ollama has pulled (`GET /v1/models`) over the floor
(below 3B left out, below 8B with a warning). Each option names its processor and whether
the turns leave the EU; `refused` says what was left out and why. `model_pick` (`/model <n>`)
is judged again, refused by name if not offered, recorded (`agent_session_rebind`:
`from_model_uri`, `to_model_uri`, `by: person`, reason, plus backend, model, processor,
`transfers_outside_eu`; the session row's `model_uri` follows) and binds from the next turn,
imprint included; that turn's first model request carries one system line naming the move.
A refused pick stays `agent_tool_result` tool `model`. A new session starts on
the host's `iris_backend`. The live Art-30 record (`nos_gdpr.effective_records`) names every
row a person could pick, not only the host's choice.

## The wire and the ledger

The wire is `files/anatomy/contracts/thalamus-shell.yml` (newline-delimited
JSON). The ledger's columns are a subset of Wing's `agent_sessions` and
`events`; the serve process is its only writer.

## Health

`ansible-playbook main.yml --tags receptor,thalamus,verify` runs
`tools/thalamus-status.py --json` and fails on any line that is not OK: the
socket is a socket with mode 0600, the launchd job is loaded, the ledger is
readable in a 0700 dir. The last session is reported, not judged.
