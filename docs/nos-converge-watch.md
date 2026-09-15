# nos converge watch

Living ledger. After every `nos`, append a **Recap** and revise the backlog.
Latest green: **2026-09-15** `p=32933`. OpenClaw pin and apex D4 fail-fast
held. Speed backlog (S1–S7) is unblocked.

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

### 2026-09-14 `p=54800` — green (~22 min)

```
ok=1589 changed=108 unreachable=0 failed=0 skipped=2286
```

Source: local `dev` @ `6a7b97fd` + uncommitted CI follow-up (Coolify LIA,
tools README, roadmap index, pytest ratchet). 18:48:36–19:10:19.
Baseline 13 Sep: `ok=1584 changed=98 skipped=2284` ~21 min.

**Stop:** `green`. Apex preflight `--check` at 18:48:45; later
`build.py --require-signed` served. OpenClaw keg=daemon=pin 0.34.0.
nos-smoke **46/46**. Face 302, apex 200.

SLOW (none moved vs last green; cask detect did not fire):

| s | task |
|---|---|
| 147 | health-wait leftover includes (wave-2 tick 2) — S2; 13 Sep was 146 s |
| 113 | Bone HMAC self-test (fourth consecutive) — S3 |
| 34 | apps_runner `docker manifest inspect` — S7 |
| 31 | restic repo initialized — S7 |
| 28 | apps health-wait leftover tick 0 — S2 |
| 27 | tofu-authentik reconcile preflight |
| 27 | mcp_gateway token verify — S7 |
| 23 | Wing GDPR upsert — S7 |
| 21 | keap caddy-sessions slug scan |

### 2026-09-14 `p=14457` — failed at OpenClaw (~8 min)

```
ok=477  changed=33  unreachable=0  failed=1  skipped=370
```

Source: local `dev` @ `2a975bfc` (device gateway + S7). Host + core + tofu
apply ran; OpenClaw refused; device-gateway role did not.

**Stop:** `pazny.openclaw` keg-vs-daemon refuse. Linked keg **and** daemon
were 0.34.0 (`tools/brew-pin-status.py` AT-PIN). Message `drift keg=
srv=0.34.0` — empty keg. Cause: skipped re-resolve still `register:`'d
`_ollama_keg` and wiped the first resolve. Tofu heartbeat `FAILED -
RETRYING` is not this fail.

Device login still blocked on the next green past OpenClaw.

### 2026-09-14 `p=64644` — failed at Cortex (~8 min)

```
ok=524  changed=39  unreachable=0  failed=1  skipped=388
```

Source: local `dev` @ `5f5185ce` (keg skip-wipe). OpenClaw keg gate held.
Device-gateway launchd rendered and bootstrapped. Loopback `/health` 200.

**Stop:** `pazny.cortex` `store:materialise` — `keap_selfmodel_gen` has no
`SYSTEM_EN` for slug `device-gateway` (manifest id `device_gateway`). Taxonomy
refuses filler. Tofu apply had already passed.

### 2026-09-14 `p=13240` — green (~18 min)

```
ok=1273 changed=106 unreachable=0 failed=0 skipped=719
```

Source: local `dev` @ `6699b900`. 21:24:00–21:42:16. Baseline 13 Sep
`ok=1584 skipped=2284` ~21 min; last green `p=54800` `ok=1589 skipped=2286`
~22 min.

**Stop:** `green`. Keg gate held. Cortex materialise accepted `device-gateway`.
Device-gateway launchd running. Loopback and `https://device.pazny.eu/health`
both `{"ok": true}` 200.

ok/skipped dropped vs last green — leftover health-wait includes (S2) are
the likely missing ticks, not a short play.

### 2026-09-15 `p=32933` — green (~18.5 min)

```
ok=1271 changed=104 unreachable=0 failed=0 skipped=725
```

Source: local `dev` @ `8de64840`. 15:53:26–16:11:57. Same band as `p=13240`
(~18 min); still well under the 13 Sep ~21 min baseline.

**Stop:** `green`. Tofu apply ran. Device-gateway copied to `~/device-gateway`
and the launchd handler restarted (`WorkingDirectory` runtime). KEAP seeded
`device-client` schema with no rows (empty-seed skip fired). Loopback and
`https://device.pazny.eu/health` 200. KEAP `GET /tables/device-client` 200.
`/device` is the Authentik auth flow (302 → default-authentication), not a
white 404.

Pairing runtime (handheld QR after this apply) is still the operator's next
reader — this recap does not close that.

---

## Backlog — after green

Ranked. Next pass is measurements, then the smallest structural cut that
removes a row, not a pile of micro-edits.

### S1. Ollama pin decides — cut in tree 2026-09-14; skip-wipe 2026-09-14

Install was already `present` (2026-08-27). p=11902 failed because brew had
linked 0.34.0 outside the run while 0.33.3 was still in the cellar, and the
refuse said re-pin. Cut: Homebrew Keg API links the pin keg; refuse only if
that cannot. Gate `test_ollama_pin_decides.py`.

p=14457: pin matched, skipped re-resolve still registered `_ollama_keg` and
emptied it; drift gate refused `keg=` vs daemon 0.34.0. Cut: keep first
resolve unless the pin switch actually linked. Next `nos` is the reader.

### S2. Health-wait leftover includes — cut in tree 2026-09-14

Looped `include_tasks` never short-circuits. Cut: `health-tick.yml`
re-includes itself while `not _wait_done`. Gate: a ready tick does not
schedule the rest of the budget. Next `nos` is the reader (p=54800: 147 s
after wave-2 ALL_READY).

### S3. Bone HMAC 113 s was plugin-loader vars — cut in tree 2026-09-14

`hmac_selftest.py` is 0.13 s. The 112.7 s was eager-finalize of live `vars`
on `nos_plugin_loader` post_compose. Cut: snapshot `nos_plugin_ctx` before
compose registers bloat it; every loader passes that fact. Gate
`test_plugin_loader_ctx_is_a_snapshot.py`. Next `nos` is the reader (gap
between bone post and post_compose).

### S4. Detect running cask apps — cut in tree 2026-09-14

One `brew info --cask --json=v2` for the outdated list, then pgrep. Gate
`test_cask_detect_is_one_brew_info.py`. Did not fire on p=54800; next `nos`
with outdated casks is the reader.

### S5. Global `become = True` + `interpreter_python = auto` — cut in tree 2026-09-15

`ansible.cfg` `become = False`; play `ansible_python_interpreter: "{{ ansible_playbook_python }}"`; inventory no longer pins Homebrew python3. Dnsmasq restart and blank brew-stop declare `become: true`. Gate `test_ansible_cfg_is_not_auto_become.py`. Next `nos` is the reader (interpreter in the log, brew prefix, Ollama keg `become: false`).

### S6. Host layer on a source-only bump — cut in tree 2026-09-14

CLT tagged `homebrew` so `--skip-tags homebrew` skips Xcode tools with brew. Gate `test_converge_host_skip_tags.py`. Organs/stacks stay off the skip list. Next `nos --skip-tags homebrew,...` is the reader.

### S7. Smaller — cuts in tree 2026-09-14; next `nos` is the reader

- `docker manifest inspect` sequential — local `image inspect` first (`test_apps_image_probe_asks_local_first.py`).
- restic "is repo initialized" — `cat config`, not `snapshots` (`test_restic_init_check_is_cat_config.py`).
- mcp_gateway token verify — persist once (`test_mcp_grafana_token_is_not_reminted.py`).
- keap empty-seed GET — skip when `rows: []` (`test_keap_empty_seed_skips_row_fetch.py`). Reader: `p=32933` device-client "No row WHERE-guard".
- Wing GDPR upsert — one `--json=-` (`test_gdpr_upsert_is_one_invocation.py`).
- `~/.nos/ansible.log` rotation in `nos` before ansible opens it (`test_ansible_log_rotates_before_converge.py`).

S0 closed on `p=54800`. Pairing registry `table:device-client` landed
withheld (SYSTEM 23→24). Re-sign via `tools/apex-sign.py` when the operator
reads the withheld `table:device*` set.
