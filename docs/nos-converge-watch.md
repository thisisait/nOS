# nos converge watch

Living ledger. After every `nos`, append a **Recap** and revise the backlog.
Speed backlog waits on `failed=0`. OpenClaw is past. Apex D4 + fail-fast are
in this tree (`table:device*` withheld; `build.py --check` in pre_tasks).
Next `nos` from local `dev` should die in seconds if the ruling cannot serve,
not at stack-up.

Tracker: dtt `converge-watch` (`nos dtt capture --slug converge-watch --update`).
This file is the measurements; the row is the claim.

## How to append

1. PLAY RECAP line (ok / changed / failed / skipped / duration vs previous green).
2. The task that stopped the run, or `green`.
3. New SLOW (≥20 s) vs the last green profile — only if the number moved.
4. Tick or rewrite one backlog row. Do not grow a second list.

Baseline green: **2026-09-13** `ok=1584 changed=98 failed=0 skipped=2284` ~21 min
(`p=75080`, 15:31:50–15:53:05).

---

## Recaps

### 2026-09-14 `p=11902` — failed at OpenClaw (~9 min)

```
ok=618  changed=29  unreachable=0  failed=1  skipped=1158
```

Source: local `dev` @ `23e32f1b` (SSOT constitution). Host + core + tofu ran;
stack-up / iiab / face did not.

**Stop:** `pazny.openclaw` — linked keg **0.34.0**, pin **0.33.3**, daemon still
0.33.3, no shadowing tap. Same class as 2026-09-05 (`1b7c5a08`). Fix this run:
re-record `ollama_version: "0.34.0"`. Next converge must also pick up the
keg-vs-daemon reload (daemon was still 0.33.3 at refusal).

`tools/brew-pin-status.py`: `TOO-FRESH` 0.34.0 (0 d vs 30 d window). Adopted
anyway because the keg is already linked; lagging would mean `brew` unlink, not
a pin edit.

SLOW this fragment (full profile truncated by the fail):

| s | task |
|---|---|
| 113 | Bone HMAC self-test (repeat of 13 Sep — same number) |
| 55 | Detect running cask apps (`brew info --json` per outdated cask) |
| 27 | tofu-authentik reconcile preflight summary (13 Sep: 28 s) |
| 20 | homebrew `file:` on `homebrew_brew_bin_path` (`changed` every run) |
| 20 | health-wait leftover `include_tasks` after ALL_READY (infra/observability tick 0/80) |

### 2026-09-14 `p=69097` — failed at apex (~10 min)

```
ok=759  changed=46  unreachable=0  failed=1  skipped=1239
```

Source: local `dev` @ `aade9c63` (ollama pin 0.34.0). Host + core + tofu +
OpenClaw + stack compose-up ran; iiab health-wait / face did not.

**Stop:** `pazny.apex` `build.py --require-signed` rc=2. Ruling itself is
SIGNED (`apex ruling v1 SIGNED by Pázny`). Gate: UNRULED nodes
`table:device`, `table:device-extraction` (ruling D4: published set frozen).
Those two landed in the anatomy graph with the SSOT/device-tables wave; apex
will refuse until they are ruled or the graph drops them.

**OpenClaw:** pin matched; keg-vs-daemon reload ran; model pull ok. S1 still
open as the *next* brew bump.

SLOW this fragment (cask detect did not fire):

| s | task |
|---|---|
| 113 | Bone HMAC self-test (third consecutive run, same number) |
| 26 | tofu-authentik reconcile preflight summary |
| 20 | homebrew `file:` on `homebrew_brew_bin_path` |

---

## Backlog — after green

Ranked. Next pass is measurements, then the smallest structural cut that
removes a row, not a pile of micro-edits.

### S1. Ollama recorder fails the run it updates

`state: latest` moves the keg; the pin is a record; the record then refuses.
Every Homebrew ollama release costs exactly one converge. Either the pin
**decides** (drop `latest`, install the recorded version) or the record
**follows** (write the keg back, do not fail). What cannot hold is a recorder
that fails for being out of date — already named on the `ollama_version` line.

### S2. Health-wait always iterates the full tick budget

`tasks/stacks/wait-stacks-healthy.yml`: `when:` on looped `include_tasks` does
not short-circuit. Inner `not _wait_done` skips probe/sleep; Ansible still
pays ~80 empty includes per wait (`stack_up_wait_timeout` 1200 → tick N/80).
This run: ~20 s after observability ALL_READY on tick 0. 13 Sep: 146 s on
"Record tick 2". Cheapest cut: one task `until: ALL_READY` + `retries`/`delay`,
or `--wait` on `stack-health-probe.py`. Heartbeat can stay.

### S3. Bone HMAC self-test = 113 s three times

`roles/pazny.bone/files/hmac_selftest.py` has HTTP timeout 5 s. 113 s is
Bone/launchd (or the become/python wrap), not HMAC. Measure; reload already
only on `DESYNC`.

### S4. Detect running cask apps = 55 s

Per-cask `brew info --cask --json=v2`. One batched `brew info --cask --json=v2
cask1 cask2 …`. Escape hatch: `homebrew_cask_auto_upgrade: false` in
`config.yml` for a doctrine-only converge.

### S5. Global `become = True` + `interpreter_python = auto`

`ansible.cfg`. Every task sudo; become modules run Homebrew Python 3.14,
controller pyenv 3.13.13. Default become false; pin the interpreter.

### S6. Host layer on a source-only bump

CLT / brew / cask / pip / npm always run. A profile or `--skip-tags` for
organs+stacks would have saved the first ~5–8 min of this SSOT test (and
still hit the ollama gate).

### S7. Smaller

- `docker manifest inspect` sequential (~33 s last green) — local `image inspect` first.
- restic "is repo initialized" ~31 s.
- mcp_gateway token verify ~27 s.
- keap seed-slug scan ~22 s.
- Wing GDPR upsert ~22 s.
- `~/.nos/ansible.log` ~250 MB, no rotation.

Parked until S1–S3 have a builder: do not start a speed epic mid-red.

### S0. Apex D4 must fail in pre_tasks, not at stack-up

Measured p=69097: Ansible `REFUSE unsigned` said SIGNED; `build.py` then
exit 2 on UNRULED `table:device` / `table:device-extraction`. Those gates
now run as `build.py --require-signed --check` right after `config.yml` is
loaded. The two tables are withheld like every other `table:` node
(published set unchanged; re-sign via `tools/apex-sign.py` when you read it).
