# Security Review — 2026-05-24 (multi-agent, pre-v0.2-beta)

Five parallel read-only audit agents swept the codebase against the existing
framework (SEC-1..15 resolved, 85-item `remediation-queue.json`). This advisory
records **new** findings only — known/resolved items were excluded by each agent.

**Baseline verdict: solid.** SEC-1 (override mode 0600), SEC-3 (256-bit random
HMAC/data keys), SEC-4 (`~/.nos` 0700), SEC-6 (127.0.0.1 binds), SEC-7
(mass-assignment / public-POST gate), SEC-8 (PHP command allowlist), SEC-9
(Pulse output scrub), SEC-13 (secret persistence 0600) all verified intact.
Constant-time HMAC compares, parameterized SQL, list-form `proc_open`/subprocess,
`escapeshellarg` on the deploy-trigger tag layer — all confirmed. **No true
CRITICALs** after reconciliation (see C-1/C-2 below).

Scope: Wing (PHP/Nette + API + AgentKit), Bone + Pulse (Python), the Ansible
layer (shell/perms/secrets), secrets lifecycle + SSO/IAM, CI/CD + network
exposure.

---

## Dominant theme — prefix-derived secrets under a weak default prefix

The single largest issue is structural: `global_password_prefix` defaults to
`changeme` (`default.config.yml:8`), the blank prompt silently accepts it (no
strength gate), and several secret classes still derive from it rather than
joining the SEC-3 randomization sweep. Findings H-SEC1, M-SEC1, and the
(downgraded) C-1 are all this root cause. **Fixing the prefix-strength gate +
extending the randomization sweep closes most of the review in one stroke.**

---

## HIGH

- **H-SEC1 — OIDC + agent client secrets stay prefix-derived.** 30+ plugin
  `client_secret: "{{ global_password_prefix }}_pw_oidc_<svc>"` (e.g.
  `files/anatomy/plugins/gitea-base/plugin.yml:61`) and 8 agent identities
  (`default.config.yml:1961..2050`, incl. Inspektor `nos:security:write` /
  `nos:pentest:execute` scopes). The `main.yml:1003-1064` sweep randomizes
  HMAC/data keys but NOT these. Under default prefix every one is
  `changeme_pw_oidc_<svc>` — dictionary-guessable confidential secrets.
  → Extend the lazy-regen `set_fact` to randomize `*_oidc_*` + agent client
  secrets when prefix-derived; persist to `~/.nos/secrets.yml`; add a pytest gate.

- **H-PULSE1 — Pulse daemon doesn't re-validate the command allowlist.**
  `files/anatomy/pulse/pulse/daemon.py:118-143` + `runners/subprocess.py:39`
  execute `job["command"]`/`args` verbatim; the SEC-8 allowlist lives ONLY in
  `PulsePresenter.php` (the create path). Any other writer of a `pulse_jobs`
  row (direct SQLite, agents, a future path) gets arbitrary RCE — the SEC-8
  commit itself deferred this. → Port `ALLOWED_COMMAND_PREFIXES`/`BANNED_BASENAMES`/
  arg-regex into `daemon._dispatch` (the boundary that spawns the process).

- **H-ANS1 — ~90 secret-handling tasks lack `no_log: true`.** Admin passwords
  passed as plaintext shell args (e.g. `roles/pazny.grafana/tasks/post.yml:33`,
  `roles/pazny.gitlab/tasks/post.yml:34`, + ~16 more roles). The
  `callback_plugins/wing_telemetry.py` forwards every task `_result` to Wing's
  SQLite; `scrub()` redacts by **key name** only, so passwords inside `cmd`/
  `stdout` strings persist **unredacted** in `wing.db`. → Add `no_log: true` to
  every secret-bearing task; harden `scrub()` to regex-scrub secret substrings
  in `cmd`/`stdout`/`stderr`, not just keys.

- **H-ANS2 — Bluesky PDS bridge: unvalidated `item.email` → shell injection
  (+ no `no_log`).** `tasks/stacks/bluesky_pds_bridge.yml:177-205` interpolates
  `item.email` (straight from an Authentik user attribute) into a `/bin/sh -c`
  string. `item.username` is regex-hardened; email is not → backtick/`$()`
  payload in a malicious account's email executes. → `no_log: true` + validate/
  `| quote` the email (mirror the username regex).

---

## MEDIUM

- **M-SEC1 — No prefix-strength gate.** `main.yml:847-856` accepts the default
  `changeme` on Enter; DB roots (`mariadb/postgresql/redis`), admin passwords,
  and OIDC secrets ride that entropy. MISCONFIG-007 assumed auto-gen covered
  blanks — it doesn't for these classes. → Preflight `fail` when prefix is
  `changeme`/empty/<12 chars (bypass `-e allow_weak_prefix=true` for dev.local).

- **M-DEPLOY1 (was CI C-2) — deploy-trigger bypasses the SEC-6 edge gate + is
  container-reachable.** `DeployTriggerPresenter` extends `BaseApiPresenter`
  (no edge-token), reachable via `host.docker.internal:9000`. Mitigated by the
  random HMAC secret (generic containers can't forge), but defense-in-depth: add
  edge-token/dedicated-auth or bind off the container-reachable interface.

- **M-PULSE2 — child jobs inherit full operator env incl. `WING_API_TOKEN`** +
  accept unvalidated `env` overlay (`subprocess.py:37`, `daemon.py:126`) →
  `DYLD_*`/`LD_*` injection / token exfil. → Minimal allowlisted child env;
  strip secrets; deny loader vars.

- **M-ANS3 — `~/.ansible_askpass` (plaintext sudo pw) cleanup is in
  `post_tasks`** (`main.yml:1492`) → doesn't run on mid-play failure → lingers
  (mode 0700). → Move cleanup to an `always:` block.

- **M-PIPE1 — `risky-shell-pipe`** (the release trigger): 4 confirmed offenders
  lack `set -o pipefail` — `main.yml:552` (Restart wing), `roles/pazny.wing/
  tasks/main.yml:273`, `roles/pazny.mac.homebrew/tasks/main.yml:161`,
  `roles/pazny.nextcloud/tasks/post.yml:53`; + partials lacking
  `executable: /bin/bash` (`roles/pazny.spacetimedb/tasks/post.yml:60,84,100`,
  `tasks/apply-patches.yml:78`). → `set -o pipefail` + bash executable each.

- **M-PUTER1 — Puter `node -e` JS-string interpolation** (`roles/pazny.puter/
  tasks/apps.yml:103`) — latent injection; operator-controlled today. → `| to_json`
  / argv-pass before it's ever fed external data.

- **M-CI1 — Integration job runs untrusted fork-PR code** on the macOS runner
  (no secrets, read-only token — limited). → Gate to same-repo PRs + approval.

---

## LOW

- **L-DEPLOY1 (was CI C-1)** — dead prefix-derived fallback in `wing.plist.j2:83`
  (`nos_deploy_hmac_secret` is always regenerated random). → Drop the
  `+ '_pw_deploy_hmac'` middle term.
- **L-WING1** — EventsPresenter vs DeployTrigger HMAC normalization differ
  (one strips `sha256=`, one doesn't) → factor a shared verify helper.
- **L-WING2** — DI Guzzle client lacks `allow_redirects: false` (the curl probes
  all set it); carries the `WING_API_TOKEN` bearer.
- **L-WING3** — misleading `ProcessPool::$env` docblock (null = inherit, not empty).
- **L-BONE1** — `/api/health/aggregate` uses `verify=False` (SSRF amplification
  if the registry is poisoned).
- **L-BONE2** — dead `BONE_SECRET` still in `bone.plist.j2:34` (retired channel).
- **L-PULSE1** — `max_runtime_s` job-controlled, unclamped.
- **L-CI2** — `claude/**` push branches run integration bypassing PR review.

---

## Open supply-chain note (already tracked)

- **REM-002** (pending) — the Woodpecker agent mounts `/var/run/docker.sock`
  (`roles/pazny.woodpecker/templates/compose.yml.j2:75`) = container→host escape
  primitive. Partially mitigated (no public-repo trigger, no privileged plugins).
  → docker-socket-proxy or rootless backend. Plus: `deploy-tags:` comes from a
  commit footer (the trust boundary is "who can merge to GitHub dev").

---

## Remediation order (proposed)

1. **M-SEC1** prefix-strength gate — highest leverage, closes the whole weak-prefix class at the door.
2. **H-SEC1** randomize OIDC + agent client secrets (sweep extension + gate).
3. **H-ANS1** `no_log` sweep + `scrub()` substring hardening.
4. **H-PULSE1** Pulse daemon-side allowlist.
5. **H-ANS2** Bluesky email validation + `no_log`.
6. **M-PIPE1** pipefail (the release trigger) + the partials.
7. **M-DEPLOY1 / M-PULSE2 / M-ANS3 / M-PUTER1 / M-CI1**, then LOWs.

Positives confirmed: service bind pattern (`services_lan_access` gate, DB loopback,
Redis requirepass), TLS (1.2 floor + HSTS), forward-auth fail-closed, no secrets
in GitHub Actions, AgentKit credential/webhook handling, parameterized SQL.
