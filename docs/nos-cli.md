# `nos` CLI — operator reference

`nos` is the operator entry point for nOS: a thin bash wrapper (`tools/nos`)
around `ansible-playbook main.yml` that adds the **removal ladder**
(`remove=none|data|deep|all`), the **dry-run-by-default** consent surface, and
the non-interactive `-y` path. Everything it does is expressible as raw
`ansible-playbook` extra-vars — the CLI is convenience + refusal ergonomics,
the playbook-side asserts are the real guards.

## Install & bootstrap

- The playbook installs `tools/nos` into `{{ nos_cli_install_dir }}`
  (macOS: `{{ homebrew_prefix }}/bin/nos`; Linux: `~/.local/bin/nos`) via
  `tasks/nos-cli.yml` (`--tags nos-cli`), atomically (`copy`, temp-write +
  rename).
- **Bootstrap:** the first run on a fresh machine is
  `ansible-playbook main.yml` by hand from the checkout — that run installs
  `nos`; subsequent runs are just `nos`.
- **Checkout resolution:** `nos` finds the playbook checkout via, in order:
  1. `~/.nos/nos-cli.env` (written by the installer — records `NOS_SRC=<checkout>`),
  2. an exported `$NOS_SRC`,
  3. the `~/projects/nOS` fallback.
  After `nos --remove=all` (which deletes `~/.nos` and with it `nos-cli.env`),
  the fallback chain is what keeps an installed `nos` usable — export
  `NOS_SRC` or keep the checkout at `~/projects/nOS`.
- **Version handshake:** `nos` always passes `-e nos_cli_version=1`; the
  playbook refuses versions below `nos_cli_version_floor` so a stale installed
  `nos` can never emit vocabulary a future playbook no longer reads.

## Usage

```
nos [-y] [--remove=none|data|deep|all] [--confirm] [--leave]
    [--print-cmd] [-h|--help] [--version] [ansible-args...]

  (no flags)        converge:  ansible-playbook main.yml
  --remove=LEVEL    removal ladder (D1). WITHOUT --confirm/-y this is the
                    playbook DRY RUN: prints the resolved removal inventory
                    and stops, exit 0. (D2)
  --confirm         execute the removal INTERACTIVELY: all pauses fire
                    (ENTER gate, prefix prompt, source pause).  -> -e confirm=true
  -y, --yes         execute NON-INTERACTIVELY: confirm + skip every pause +
                    neutralise vars_prompt (D4). Never rotates the prefix (D3).
  --leave           stop after removal completes — no reconverge. (D1)
  --print-cmd       print the resolved ansible-playbook argv and exit 0.
  everything else   passed through to ansible-playbook VERBATIM (-e, --check,
                    --diff, -v, --limit, --skip-tags*, --tags*).
                    *refused when combined with --remove — see exit codes.
```

**The ladder (D1):**

| Level | Scope |
|---|---|
| `none` | converge only (default; every ordinary run) |
| `data` | today's blank scope: derived state (docker, dbs, service data, configs). SOURCE (`~/nos/tenants/**` user files) and images KEPT. |
| `deep` | data + docker images/build cache + brew/npm/pip caches (today's `flush=deep` scope; `~/.ollama` still opt-in via `flush_ollama`) |
| `all` | deep + user SOURCE: the full uninstall source set (`nos_data_root`, `~/.nos`, `~/bone`, `~/pulse`, `~/wing`, `~/keap`, hermes dirs, `~/.openclaw`, service registry). With `leave=false` this then REINSTALLS from zero. |

**Flag-ordering rule:** `nos` flags come BEFORE any passthrough tokens. The
parser stops at the first unrecognised token (or `--`) and passes the rest to
ansible verbatim — a `--remove=*` found INSIDE the passthrough is refused
(exit 64, "put `--remove` before passthrough tokens"), never silently ignored.

## `nos dtt` — DataTables ops (not a converge)

`nos dtt <verb>` runs the roadmap/DataTables tools **from `$NOS_SRC`**, so an
installed `nos` reaches them from **any shell, branch, or cwd** — you never call
`tools/foo.py` by path (which only exists inside a pulled checkout). They operate
over the **private seed repo** (`NOS_SEED_DIR`, passed through your env) and the
live table. This is the systemic home for the operator directive "define
plans/specs via a skill + dtt".

```
nos dtt capture --slug <s> --title "<t>" --track <track> --task-type <type> \
                --status <status> [--parent <s>] [--when <YYYY-MM-DD>] \
                [--refs "…"] --body "<prose>"   # file an idea/plan/spec (dtt-capture skill)
nos dtt seed [--dry-run] [--sync]    # insert / reconcile the table from the seed files
nos dtt status [--all|--track T]     # read the board
nos dtt update --slug <s> --status … # move a row's CLAIM
nos dtt verify --slug <s>            # write a row's VERDICT (an exit code, not an arg)
nos dtt extract [--write]            # one-time: live table -> per-row seed files
```

- **Set `NOS_SEED_DIR`** to your private seed repo (export it in your shell
  profile once); `nos dtt` inherits it. Default `~/nos-seed`.
- `nos dtt` needs `$NOS_SRC` to be a **pulled** checkout — a tool added on a
  branch is reachable only after that branch is pulled into `$NOS_SRC` (the same
  repo≠running-system lag as a converge). The CLI says so if the tool is absent.
- The git-owned/table-owned split holds: `capture` writes the file
  (title/parent/track/refs/body); `update`/`verify` move status/verdict. Never
  rewrite a filed row to change its status.

## Flag → extra-var mapping

| CLI | emits | note |
|---|---|---|
| *(no `--remove`)* | *(nothing)* | never emits `-e remove=none` — an explicit extra-var would outrank the shim's `set_fact` and silently neuter a passthrough legacy `-e blank=true` |
| `--remove=data\|deep\|all` | `-e remove=<level>` | |
| `--remove=none` | *(nothing)* | accepted for symmetry, emits nothing |
| `--confirm` | `-e confirm=true` | |
| `-y` / `--yes` | `-e confirm=true -e assume_yes=true`, redirects stdin `</dev/null`, and emits `-e nos_sudo_password=''` **only when the operator passthrough contains no `nos_sudo_password=` token** | `yes` is a YAML-1.1 truthy literal, hence the var is named `assume_yes` — the one naming exception |
| `--leave` | `-e leave=true` | |
| *(always)* | `-e nos_cli_version=1` | version handshake |

The CLI's own `-e` emissions are appended **after** the operator passthrough
(last `-e` wins in ansible; the CLI's resolved intent is the last word).
`--print-cmd` shows the final ordering.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success; also `--print-cmd`, `--help`, `--version`, and a playbook dry run |
| *n* | whatever `ansible-playbook` returned, verbatim |
| 64 | usage error: unknown `--remove` level (case-sensitive — `--remove=DATA` is refused here, and the playbook independently hard-fails on it), bare `--remove`, `--leave` without `--remove`, `--confirm` together with `-y`, or a `--remove=*` token inside the passthrough |
| 65 | refused combination: `--remove=<not none>` together with `--tags`/`--skip-tags` anywhere in the passthrough (R4 — the playbook-side assert is the backstop; the CLI refuses first) |

## `-y` (non-interactive) removal — sudo-path requirement

A `-y` removal escalates (`become:` in blank-reset + the remove-source loop)
with an EMPTY become password unless you provide one. It therefore **requires
a sudo path**: a NOPASSWD sudoers rule, a live sudo ticket (`sudo -v` right
before), or an explicit `-e nos_sudo_password=<real>` (the CLI never clobbers
an operator-passed one). Without any of these, the playbook's non-interactive
sudo preflight REFUSES up-front — before any teardown, never mid-wipe.

## Where to run a removal FROM (operator environment)

Run a removal from a terminal **outside the IDE** — Terminal.app, iTerm, or a
`tmux` session you can detach — never an editor's integrated terminal.

A removal ends in a full bring-up: ~50 containers whose RAM pressure alone can
make macOS terminate a heavy GUI app. When the editor dies it takes its
integrated terminal with it, and with it the controlling `ansible-playbook`
session — leaving a half-applied run. `tmux` also survives the SSH/terminal
drop, which a removal is long enough to meet.

This is a property of the operator's machine, not of the playbook, so no gate
can hold it. What the playbook itself does to the host session is bounded and
measured: the GUI killalls (`killall Dock` / `killall Finder`,
`tasks/macos-defaults.yml`) and the `sshd` `launchctl kickstart` handler in
`main.yml`. There is **no `reboot`, no `shutdown`, and no Docker-daemon
restart** in nOS's own tasks (the vendored `osx-command-line-tools` role's
`softwareupdate -i` can trigger an OS update, but `--tags upgrade` does not
reach it). The killalls defer by default (`defer_gui_restarts: true`,
`default.config.yml`), so a normal or blank run no longer flickers the GUI
mid-run, and `--tags upgrade` is provably free of all of them — gate
`tests/anatomy/test_upgrade_tag_host_quiet.py`. Background:
`docs/archive/upgrade-reset-scope-and-session-safety.md` §Run-hardening.

## Durable prefix advice

Put `global_password_prefix` in your gitignored `credentials.yml` — that is
the durable form. The run-mode phase also persists a fresh-machine explicit
`-e global_password_prefix=<x>` into `credentials.yml` automatically, so a
later bare run cannot silently flip back to `changeme`. `-y` never rotates the
prefix; a fresh machine with no prefix and no interactive terminal is refused.

## Verify scope — honesty note

The post-removal verify (R5) stats the CONTRACTED path set: `_blank_dirs` +
service registry + secrets + the ollama opt-in + the `remove=all` source set,
plus a docker named-volume probe. Non-path teardown steps that are
`failed_when: false` by design (e.g. the `/etc/resolver/dev.local` removal in
`blank-reset.yml`) are OUTSIDE the verify and can silently survive under `-y`.

---

## Invocation matrix

Legend: ENTER = blank-reset pause (not-assume_yes-gated); SRC-PAUSE =
remove-source pause; PREFIX = rotation prompt (ENTER = keep); SUDO =
`vars_prompt` (fires unless `-e nos_sudo_password=` passed; `-y` neutralises it).

### New vocabulary — via `nos`

| Invocation | Resolved argv (beyond `ansible-playbook main.yml -e nos_cli_version=1`) | Behavior |
|---|---|---|
| `nos` | — | ordinary converge. SUDO prompts. |
| `nos --tags keap` | `--tags keap` | tag-filtered converge (passthrough) |
| `nos --check` / `nos -e x=y` | verbatim passthrough | as ansible |
| `nos --remove=data` | `-e remove=data` | DRY RUN: prints data-level inventory (real post-override paths) + preserved list, `end_play`, exit 0. Nothing removed. SUDO still prompts (pre-phase). |
| `nos --remove=deep` | `-e remove=deep` | DRY RUN, deep inventory |
| `nos --remove=all` | `-e remove=all` | DRY RUN, all inventory incl. `~/nos/tenants/**` user files + GOV audit-chain warning |
| `nos --remove=data --confirm` | `-e remove=data -e confirm=true` | interactive execute: SUDO → PREFIX (rotate or ENTER-keep) → ENTER → blank-reset → verify (R5) → reconverge. ≡ today's `blank=true`. |
| `nos --remove=deep --confirm` | `-e remove=deep -e confirm=true` | as above + flush-deep before verify. ≡ today's `flush=deep`. |
| `nos --remove=all --confirm` | `-e remove=all -e confirm=true` | inventory print (EXECUTE header) → SUDO → PREFIX → ENTER → blank-reset → flush-deep → SRC-PAUSE → source removal → verify → **reconverge from data-zero**. The persist-and-reuse identity group (incl. the bluesky PLC rotation key) SURVIVES in memory and re-persists — only the 7 destructive keys regen. Full identity reset needs `--leave` + a later fresh run. |
| `nos --remove=data -y` | `-e remove=data -e confirm=true -e assume_yes=true [-e nos_sudo_password='' if none passed]` `</dev/null` | non-interactive wipe+reconverge: no SUDO, no PREFIX (prefix NEVER changes), no ENTER. **Requires a sudo path** (above); without one the preflight REFUSES before any teardown. Fails before the removal phase on a fresh machine without an explicit prefix. |
| `nos --remove=all -y --leave` | `+ -e leave=true` | non-interactive full teardown: data+deep+source → verify → end_play. Machine handoff in one command. Same sudo-path requirement. Full identity reset (nothing re-persists). |
| `nos --remove=all --confirm --leave` | | interactive teardown (3 gates), then stop — closest analog of today's confirmed uninstall PLUS image prune (new-vocab `all` includes deep). Full identity reset. |
| `nos --remove=deep --leave -y` | | wipe + images, stop, no reconverge. Same sudo-path requirement. |
| `nos --remove=data --tags iiab` | — | **CLI exit 65** (refused; R4) |
| `nos --tags iiab --remove=data` (removal flag AFTER the first passthrough token) | — | **CLI exit 64** — post-parse scan finds `--remove=*` inside the passthrough and refuses with "put --remove before passthrough tokens". No ordering lets a removal request bypass both refusals. |
| `nos --leave` | — | **CLI exit 64** (leave without remove) |
| `nos --remove=DATA` | — | **CLI exit 64**; raw `-e remove=DATA` also hard-fails in the playbook |
| `nos --print-cmd --remove=all -y` | prints argv, exit 0 | nothing executed |

### New vocabulary — raw `ansible-playbook` (protected equally)

| Invocation | Behavior |
|---|---|
| `ansible-playbook main.yml -e remove=data` | DRY RUN + end_play (identical to `nos --remove=data`, minus the CLI version var) |
| `... -e remove=data -e confirm=true` | interactive execute (SUDO, PREFIX, ENTER) |
| `... -e remove=all -e confirm=true -e assume_yes=true -e nos_sudo_password='' </dev/null` | non-interactive full removal + reconverge — **only with a NOPASSWD rule or live sudo ticket** (the become password is empty); otherwise the preflight refuses before teardown. With a real password: `-e nos_sudo_password=<real>` instead of `''`. |
| `... -e remove=garbage` (any off-allowlist/case/empty) | **hard assert FAIL** — never a silent converge (fail closed) |
| `... -e remove=data --tags iiab` | **hard assert FAIL** (R4 — the assert is `always`-tagged so it cannot itself be filtered) |
| `... -e leave=true` (alone) | **hard assert FAIL** (no green no-op) |
| `... -e remove=all -e confirm=true -e leave=true` | interactive teardown then stop |

### Legacy vocabulary — via the shim (transition window)

| Invocation | Shimmed to | Behavior vs today |
|---|---|---|
| `ansible-playbook main.yml -e blank=true` | `remove=data confirm=true` | **identical**: SUDO, PREFIX prompt, ENTER gate, blank-reset, reconverge — plus the new R5 verify and the pre-teardown inventory print. **Named delta (O3):** `-e blank=true --tags X` / `--skip-tags stacks` flips from "tag-filtered blank executes" (today) to a hard R4 FAIL — run legacy removals without tag restriction. |
| `... -e flush=true` | `remove=data confirm=true` | identical |
| `... -e flush=deep` | `remove=deep confirm=true` | identical + verify; the banner names the level |
| `... -e flush=deep -e flush_ollama=true` | + passthrough | identical |
| `... -e blank=false` / `-e flush=false` / `-e uninstall=false` | *(no mapping)* | ordinary converge |
| `... -e uninstall=true` | `remove=all leave=true confirm=true _compat_uninstall=true` | **the one locked delta:** was print-only dry run; now executes behind SUDO + PREFIX + ENTER + SRC-PAUSE. **Scope** identical to today's confirmed uninstall: blank-reset once + source removal, **no image prune**, end_play after verify. Consent-shape deltas: (a) the confirmed-run plan print is the inventory (EXECUTE header) — fires before any pause/teardown; (b) the SRC-PAUSE fires AFTER derived-state teardown, not before all destruction. Old dry-run: `-e uninstall=true -e confirm=false` (extra-var wins over the shim's set_fact). |
| `... -e uninstall=true -e confirm_uninstall=true` | same (`confirm_uninstall` accepted-and-ignored; it does NOT force confirm against an explicit `-e confirm=false`, which stays a dry run) | today's execute path, one typed flag fewer |
| `... -e blank=true -e remove=none` | — | **hard FAIL** (mixed vocabulary that disagrees) |
| `... -e blank=false -e remove=data -e confirm=true` | — | **hard FAIL** (falsy-blank-mix assert — the extra-var `blank=false` would shadow the derived gate and a confirmed removal would complete green having removed nothing) |
| `... -e destroy_state=true` (alone) | *(not a removal — untouched)* | 7-key regen only, as today |
| `nos -e blank=true` | passthrough → shim | same as raw legacy row; works because the CLI never emits `remove=none` |

### Guard surfaces

| Invocation | Behavior |
|---|---|
| `tools/nos-stacks.sh core -e remove=data` (any removal/confirm token) | exit 2, refused |
| `tools/nos-stacks.sh stacks -e retention_confirm=true` (also `export_confirm`/`forget_confirm`/`restore_auto_confirm`/`upgrade_confirmed`) | **NOT refused** — the `confirm=true` glob is anchored, so the documented GDPR/backup/restore workflow tokens keep working through the launcher |
| `tools/nos-upgrade-detached.sh ... -e remove=all ...` | refused |
| `ansible-bridge.sh run-tag blank` / `run-tag uninstall` / `run-tag reset` | exit 1 (BLOCKED/not-ALLOWED); the bridge has no extra-var surface at all |

## Proving the ladder — the staged first execution (2026-08-19)

The removal ladder has NEVER run, not once — no removal artefacts exist in
`~/.nos`. "Fully replicable — one command wipes everything and reinstalls
from scratch" is the project's central claim, and an untested removal path is
an unproven claim. This is the staged, reversible sequence that earns it.
Every stage is an OPERATOR act from a real terminal (the sudo pre-phase
refuses agents and IDE shells alike — see "Where to run a removal FROM").
Each stage has an evidence gate; do not climb without it.

**What a factory reset / SSD wipe would add: nothing.** Measured 2026-08-19:
zero `devboxnos-*` launchd bundles, no `~/.devboxnos`, 22 GB of ordinary
reclaimable Docker cache. The host is not rotten; the ladder is what is
unproven. The true from-nothing proof belongs to the portable-SSD replication
epic (a second Mac), which proves it without destroying the primary.

### Stage 0 — a backup that is PROVEN restorable (gate for everything below)

- The weekly `backup:backup-restore-drill` last failed; the next scheduled
  run is Sunday 04:00. A green drill — or a supervised manual restore of
  `wing.db`, the KEAP corpus, and one service DB into a scratch dir — is the
  entry ticket. A backup nobody has restored is a hope, not a backup.
- Snapshot the irreplaceables explicitly: `wing.db` (audit chain, loop
  ledger incl. 2026-08-19 history, agent sessions), KEAP corpus + review
  queue, Nextcloud/user files on `/Volumes/SSD1TB`, Vaultwarden, Infisical,
  `~/.nos/secrets.yml`.
- Baseline readers green/quiet: `tools/red-status.py`,
  `tools/identity-status.py`, `tools/rem-status.py`.

### Stage 1 — dry runs (no risk, still never done)

Run all three: `nos --remove=data`, `--remove=deep`, `--remove=all`.
Evidence gate: the printed inventories are READ, and (a) external-path
entries (`/Volumes/SSD1TB`, `/Volumes/KINGSTON`) appear with real
post-override paths, (b) the preserved list matches expectation, (c) the
known allowlist gap is checked by name — KEAP paths must appear in the
inventory (the blank allowlist has historically missed services; a wipe that
skips a service is drift, not mercy). Anything surprising stops the ladder
here and becomes a fix.

### Stage 2 — `nos --remove=data --confirm` (today's blank, ENTER-keep prefix)

WHAT IS LOST: every service's runtime data — Authentik users beyond the
declared roster (all invited users + their Infisical/Stalwart provisioning),
Gitea repos incl. the local `pzny` mirror, Woodpecker history + agent rows,
observability history, Wing's `wing.db`. Source, images, `~/nos` tenant
user-files survive.
Evidence gate: reconverge `failed=0` → `nos-smoke --strict` green →
`tools/identity-status.py` shows every declared identity ok and exactly ONE
Woodpecker agent row → restore ONE dataset from the Stage-0 backup (KEAP
corpus or a Nextcloud dir) and verify content — restore is the other half of
the claim.

### Stage 3 — `nos --remove=deep --confirm`

Adds image/build-cache/brew/npm/pip flush; the marginal loss is ~90 GB of
re-pull time, not data. Evidence gate: same greens as Stage 2 on a cold
image cache.

### Stage 4 — `nos --remove=all --confirm` (or `-y --leave` + fresh run for
full identity reset)

WHAT IS LOST beyond Stage 3: the user SOURCE set (`~/nos` tenants incl.
`~/nos/tenants/**` user files, `~/.nos`, `~/wing`, …); with `--leave` +
fresh run, the persist-and-reuse identity group too (incl. the Bluesky PLC
rotation key — federation identity is not recoverable). Evidence gate: R5
absence verify green → reconverge from data-zero `failed=0` → smoke green.
This stage, passed, is what a non-beta release claim stands on.

### What a blank does NOT restore, because nothing declares it

- `woodpecker_api_token` — an OAuth-derived PAT a human mints in the UI; the
  new server DB does not know the old token. Until re-minted,
  `tools/loop-review.py` reads CI as INDETERMINATE and the agent-row sweep
  skips (both say so rather than passing).
- Gitea/GitLab PATs of the same shape (`gitea_api_token` re-mints only via
  the `gitea_agent_forge` toggle; `gitlab_api_token` is manual).
- Anything living only in a realm: manually-created Grafana dashboards,
  Uptime-Kuma monitors beyond the plugin-provisioned set, KEAP ingestion
  bundles prepared-but-not-applied, invited users (the roster in
  `nos_identities` is the floor that reconverges; invited population is not).
- Hand-edited `config.yml` / `credentials.yml` SURVIVE (gitignored files in
  the source checkout, outside every removal scope except a manual repo
  delete) — but their realm-side counterparts (the OAuth apps, the PATs the
  values point at) do not. A value that survives pointing at a realm object
  that did not is the post-blank trap to check first.
