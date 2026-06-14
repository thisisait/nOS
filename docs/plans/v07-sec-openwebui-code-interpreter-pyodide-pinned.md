# v0.7 SEC — Open WebUI code-interpreter: pin pyodide engine (gate the pin)

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Owner item: REM-054 / PENTEST-003 — Open WebUI code-interpreter module-blocking bypass
Severity: HIGH (config_change)
Related: REM-055 (multi-hop tool-call retry cap — already gated)

---

## 1. Problem / why

REM-054 (PENTEST-003) found that Open WebUI's code-interpreter module-blocking
mechanism is **trivially bypassable** when the **server-side `jupyter` engine** is
used: a `_real_import` reference leaks into execution scope, so LLM-generated code
can undo the import restrictions, and the default `CODE_INTERPRETER_BLOCKED_MODULES`
is empty. With prompt injection this is server-side RCE. The accepted mitigation is
to **keep the browser-sandboxed `pyodide` engine** (client-side WASM, no host reach)
and never switch to `jupyter` — pinned explicitly so a future config merge can't flip
it.

That env pin **already exists in the tree**:

- `roles/pazny.open_webui/templates/compose.yml.j2` lines 36–46 set
  `CODE_INTERPRETER_ENGINE: "pyodide"` with a comment naming REM-054/REM-055.
- `docs/llm/security/remediation-queue.json` marks **REM-054 `status: resolved`**
  (`resolved_at: 2026-05-31`).

**The gap this item closes:** the pin is **NOT pinned by any pytest anatomy gate.**
Its sibling REM-055 (retry cap) has `tests/anatomy/test_openwebui_tool_call_retries_capped.py`;
the pyodide pin (REM-054) has nothing. A grep proves it:

```
$ grep -rl "CODE_INTERPRETER\|pyodide\|REM-054" tests/ files/anatomy/  # → no matches
```

So a careless edit to the compose template (or a "modernise the engine" refactor)
could silently flip `pyodide → jupyter`, regress REM-054 from `resolved` to exposed,
and **no CI gate would catch it**. Per the project hard rule — *every code fix ships
with an anatomy gate or it is a PLAN, not a fix* — REM-054 is currently an **ungated
"resolved"**, which is exactly the silent-regression shape the gate doctrine exists
to prevent.

A secondary, defense-in-depth gap: the finding's mitigation (2) recommends setting
`CODE_INTERPRETER_BLOCKED_MODULES` with a comprehensive list **even as belt-and-braces**.
nOS sets it nowhere. Because pyodide is client-side this is not load-bearing today, but
it costs nothing and means a single accidental engine flip is not a single point of
failure.

### Honest scope note

This item is primarily a **gate + hardening** task, not a behavioural fix — the
runtime is already safe. We are converting an **ungated resolved** finding into a
**gated resolved** one, plus adding cheap defense-in-depth and documenting a real
operational caveat (persistent-config). No live-system change; repo-only.

---

## 2. Files / roles to touch

| File | Change |
|------|--------|
| `tests/anatomy/test_openwebui_code_interpreter_pyodide.py` | **NEW** — the gate. Pins the pyodide engine env + the `default(...)` override shape + REM-054 not-pending. |
| `roles/pazny.open_webui/templates/compose.yml.j2` | Route the engine through an operator-override var (`openwebui_code_interpreter_engine`, default `pyodide`); add `CODE_INTERPRETER_BLOCKED_MODULES` defense-in-depth env (only meaningful if jupyter is ever forced, harmless on pyodide). |
| `roles/pazny.open_webui/defaults/main.yml` | Add `openwebui_code_interpreter_engine: "pyodide"` + `openwebui_code_interpreter_blocked_modules` default (role default = source of truth for this stack-up role). |
| `docs/llm/security/remediation-queue.json` | Append the gate-pin sentence to REM-054's `remediation_detail` (mirror the REM-055 convention: `… Pinned by tests/anatomy/test_openwebui_code_interpreter_pyodide.py.`). Keep `status: resolved`. |
| `files/anatomy/plugins/open-webui-base/templates/open-webui-base.compose.yml.j2` | **No change** — the engine pin stays in the role template (consistent with where it lives today; the plugin overlay is OIDC/CA only). Documented here so a reviewer doesn't expect it there. |

### Do NOT touch (and why)

- `default.config.yml` / `default.credentials.yml` — adding a var there pulls it into
  the **core-up `{{ vars }}` eager-resolve namespace** (the stock-Jinja trap). The
  override var is consumed only by a **stack-up role** (open_webui is in the `iiab`
  stack, rendered after core-up), so its home is **`roles/pazny.open_webui/defaults/main.yml`**.
  Keeping it out of the two config files sidesteps the trap entirely. (Note: the
  existing `openwebui_max_tool_call_retries` is *also* only referenced via
  `| default(5)` with no definition anywhere and renders fine for the same reason —
  this plan does not regress that, but see Risks §4 for the latent-cleanup option.)

---

## 3. Approach

### 3a. The gate (the load-bearing deliverable)

New `tests/anatomy/test_openwebui_code_interpreter_pyodide.py`, modelled 1:1 on the
existing `test_openwebui_tool_call_retries_capped.py` (same repo-root resolution, same
queue-parsing helper, same offline/fast shape — no Docker, no live system). It pins:

1. **`test_engine_env_var_present`** — `CODE_INTERPRETER_ENGINE` appears in
   `roles/pazny.open_webui/templates/compose.yml.j2`.
2. **`test_engine_defaults_to_pyodide_not_jupyter`** — the rendered value expression
   resolves to `pyodide` by default and **never** literal `jupyter`. Regex-match the
   env line; assert `pyodide` is the default (directly or via
   `openwebui_code_interpreter_engine | default('pyodide')`); belt-and-braces assert
   the line does not hardcode `jupyter`.
3. **`test_blocked_modules_env_present`** — `CODE_INTERPRETER_BLOCKED_MODULES` is set
   (defense-in-depth from mitigation (2)); assert the default list is non-empty.
4. **`test_rem_054_not_pending`** — REM-054 exists in the queue and
   `status != "pending"` (reuse the REM-055 test's queue-parse helper verbatim).

Each assertion carries a message naming REM-054 and the file, matching house style.

### 3b. Operator-override the engine (so the gate has a clean shape to pin)

Today line 41 is a bare literal `CODE_INTERPRETER_ENGINE: "pyodide"`. To match the
REM-055 pattern (operator-overridable, gate asserts the *default*), change it to:

```jinja2
      CODE_INTERPRETER_ENGINE: "{{ openwebui_code_interpreter_engine | default('pyodide') }}"
```

with `openwebui_code_interpreter_engine: "pyodide"` in `defaults/main.yml`. This keeps
the secure default, lets a high-trust operator opt into `jupyter` *deliberately* via
`config.yml` (eyes-open, documented), and gives the gate a stable `default('pyodide')`
shape to assert — the same contract the REM-055 gate uses for the retry cap.

### 3c. Defense-in-depth blocked-modules

Add (role template, alongside the engine line):

```jinja2
      # Belt-and-braces (REM-054 mitigation 2): even though pyodide is
      # client-side, ship a non-empty server-side module blocklist so a
      # deliberate jupyter opt-in is not a single point of failure.
      CODE_INTERPRETER_BLOCKED_MODULES: "{{ openwebui_code_interpreter_blocked_modules | default('os,sys,subprocess,socket,shutil,pathlib,ctypes,multiprocessing,importlib,__builtin__,builtins') }}"
```

Exact list is a starting point — finalise against upstream's documented escape set at
implementation time (Context7 `/open-webui/open-webui` `config.py` was 502-ing during
planning; re-query before committing). Harmless on pyodide; load-bearing only if an
operator forces jupyter.

### 3d. Queue housekeeping

Append to REM-054 `remediation_detail`, mirroring REM-055's exact closing form:
`… Pinned by tests/anatomy/test_openwebui_code_interpreter_pyodide.py.` Status stays
`resolved` (it already was — we are gating, not re-opening).

---

## 4. Risks

1. **Persistent-config caveat (the real operational risk).** Open WebUI's
   code-interpreter settings are **persistent config**: the env var seeds the value on
   **first container boot**, then it is stored in the DB and editable in Admin →
   Settings. The compose template itself flags this for `TOOL_SERVER_CONNECTIONS`
   (line 49: *"nacte pri prvnim startu a ulozi do DB"*). **Consequence:** on an
   already-provisioned tenant, flipping the env from jupyter→pyodide may NOT take effect
   without `ENABLE_PERSISTENT_CONFIG=false` (or a manual Admin-UI change / data reset).
   - *Mitigation:* document this in the role README + the gate docstring. Do **NOT**
     set `ENABLE_PERSISTENT_CONFIG=false` blindly — it would also wipe operator UI
     customisations on every converge. For nОS the default is `pyodide` from the very
     first blank, so a fresh install is correct; the caveat only matters for an operator
     who *already* set jupyter in the UI. The gate covers the **declared default**
     (what a blank install gets), which is the in-scope, repo-ownable surface.
2. **Blocked-modules list wrong/incomplete.** Mitigating an incomplete blocklist gives
   false confidence — but only on the jupyter path, which nOS does not use. Mark the
   list as a starting point in the comment; the *primary* control remains the pyodide
   pin. Re-query upstream before committing the exact list.
3. **Gate over-fits the template text.** Use tolerant regex (whitespace-insensitive,
   match the value expression not the whole line) so a cosmetic reorder doesn't red the
   gate. Copy the REM-055 gate's regex discipline.
4. **Latent `| default()`-only vars (out of scope, noted).** Both
   `openwebui_max_tool_call_retries` and the new `openwebui_code_interpreter_engine`
   are referenced only via `| default(...)` and defined only in role defaults. For a
   **stack-up** role this is safe (renders after core-up). It would only bite if
   open_webui were ever moved to core-up. Not changing it here; flagged for the
   maintainer. The new var follows the **identical** safe pattern as the existing one,
   so it introduces no new trap.

---

## 5. Gates it needs (NON-NEGOTIABLE)

- **NEW** `tests/anatomy/test_openwebui_code_interpreter_pyodide.py` — the four pins in
  §3a. This is the deliverable that turns REM-054 from ungated→gated.
- Existing `tests/anatomy/test_openwebui_tool_call_retries_capped.py` must stay green
  (we edit the same template; the retry-cap line is untouched).
- Existing `tests/anatomy/test_config_stock_jinja_only.py` must stay green (no new var
  added to `default.config.yml`/`default.credentials.yml`/`tests/config.yml`, so the
  every-ref-resolves-before-core-up gate is unaffected — verify anyway).
- `ansible-playbook main.yml --syntax-check` clean.
- Full `tests/anatomy/` suite green.

---

## 6. Verification recipe

```bash
# 0. On the branch
git rev-parse --abbrev-ref HEAD          # → feat/v0.7-overnight

# 1. The new gate passes
python3 -m pytest tests/anatomy/test_openwebui_code_interpreter_pyodide.py -q

# 2. The sibling gate still green (same template edited)
python3 -m pytest tests/anatomy/test_openwebui_tool_call_retries_capped.py -q

# 3. Stock-Jinja trap gate unaffected
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 4. Full anatomy suite
python3 -m pytest tests/anatomy/ -q

# 5. Syntax-check clean
ansible-playbook main.yml --syntax-check

# 6. Negative-control: prove the gate actually bites.
#    Temporarily flip the engine default to jupyter and confirm RED, then revert.
sed -i.bak "s/default('pyodide')/default('jupyter')/" \
  roles/pazny.open_webui/templates/compose.yml.j2
python3 -m pytest tests/anatomy/test_openwebui_code_interpreter_pyodide.py -q  # MUST fail
mv roles/pazny.open_webui/templates/compose.yml.j2.bak \
  roles/pazny.open_webui/templates/compose.yml.j2
python3 -m pytest tests/anatomy/test_openwebui_code_interpreter_pyodide.py -q  # green again

# 7. (Read-only, optional) confirm the live container is on pyodide — NEVER mutate.
docker inspect iiab-open-webui-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep -i CODE_INTERPRETER || echo "env seeded at first boot; check Admin → Settings"
```

Step 6 (negative control) is the proof the gate is load-bearing, not decorative —
without it a passing gate could be a tautology.

---

## 7. Commit (branch only — never push)

```
fix(open-webui): gate pyodide code-interpreter pin (REM-054)

- REM-054 pyodide pin was in-tree + resolved but ungated — a config
  merge could silently flip to the RCE-prone jupyter engine.
- Route engine via openwebui_code_interpreter_engine (default pyodide),
  add belt-and-braces CODE_INTERPRETER_BLOCKED_MODULES.
- New gate test_openwebui_code_interpreter_pyodide.py pins engine
  default + blocklist + REM-054 not-pending.
- Queue: note the gate on REM-054 (status stays resolved).
```

Conventional Commits, subject 49 chars, surgeon-tone body, no Co-Authored-By, no
`--author`. Lands on `feat/v0.7-overnight` only.
