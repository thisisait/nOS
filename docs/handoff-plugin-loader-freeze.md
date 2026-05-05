# Handoff: Plugin-loader post_compose freeze — root cause + fix plan

> Written 2026-05-07 after --blank run froze for 18+ minutes at
> `[Core] Plugin loader — post_compose hook`.
> Implement the Option A refactor in a fresh session before re-running.

---

## 1. Root cause (confirmed by process sample)

`files/anatomy/module_utils/load_plugins.py:619` — `_wait_health()` is a
**synchronous HTTP poll**, 60 s default timeout per plugin.

`tasks/stacks/core-up.yml:522` — `post_compose` hook fires for **all enabled
plugins simultaneously** right after `infra` + `observability` stacks come up,
**before** `stack-up.yml` launches iiab / devops / b2b / data.

Impact at the user's config (everything enabled):

| Stack | wait_health plugins | Status during post_compose |
|---|---|---|
| infra | 2 (infisical, portainer) | **UP — resolves immediately** |
| observability | ~5 (grafana, prometheus, loki, tempo, alloy) | **UP — resolves immediately** |
| iiab | 14 | **DOWN — each times out at 60 s** |
| b2b | 6 | DOWN |
| devops | 4 | DOWN |
| data / host | ~9 | DOWN |

**Total freeze: ~33 plugins × 60 s ≈ 33 minutes** (gitlab/erpnext skipped via
feature_flag gate, saves a few). After timeout each plugin is marked
`degraded` (not `failed`) → Ansible task exits 0 — operator sees nothing.

---

## 2. Fix: Option A — `stack_filter` parameter (~35 lines total)

Add an optional `stack_filter: list[str]` param to `run_hook()`. A plugin is
skipped if its `compose_extension.stack` is not in the filter list (or if the
filter is absent — backward-compatible).

### File 1: `files/anatomy/module_utils/load_plugins.py`

**`run_hook()` signature** (line 317):
```python
def run_hook(name: str, plugins: list[Plugin],
-            template_vars: dict | None = None) -> list[HookResult]:
+            template_vars: dict | None = None,
+            stack_filter: list[str] | None = None) -> list[HookResult]:
```

**Inside the loop** (after feature_flag gate, ~line 381):
```python
+       # stack_filter: skip plugins whose compose_extension.stack is not in
+       # the allowed list. Absent stack → treat as "always include".
+       if stack_filter is not None:
+           plugin_stack = (p.manifest.get("compose_extension") or {}).get("stack")
+           if plugin_stack and plugin_stack not in stack_filter:
+               results.append({"plugin": p.name, "status": "skipped",
+                               "note": f"stack_filter: {plugin_stack} not in {stack_filter}"})
+               continue
```

### File 2: `files/anatomy/library/nos_plugin_loader.py`

Module params already include `template_vars`. Add:
```python
stack_filter=dict(type='list', elements='str', required=False, default=None),
```
And pass it through:
```python
results = run_hook(hook, plugins, template_vars=tvars, stack_filter=module.params['stack_filter'])
```

### File 3: `tasks/stacks/core-up.yml` (line 522)

Change the `post_compose` task:
```yaml
- name: "[Core] Plugin loader — post_compose hook"
  nos_plugin_loader:
    hook: post_compose
    plugin_dir: "{{ playbook_dir }}/files/anatomy/plugins"
    template_vars: "{{ vars }}"
+   stack_filter:
+     - infra
+     - observability
```

### File 4: `tasks/stacks/stack-up.yml`

Add a plugin loader call **after** the `async_status` join (line ~220, after all
stacks confirmed healthy):
```yaml
- name: "[Stacks] Plugin loader — post_compose hook (iiab/devops/b2b/data)"
  nos_plugin_loader:
    hook: post_compose
    plugin_dir: "{{ playbook_dir }}/files/anatomy/plugins"
    template_vars: "{{ vars }}"
    stack_filter:
      - iiab
      - devops
      - b2b
      - data
      - voip
      - engineering
      - host
```
Place this **after** the existing `async_status` result checks and **before**
the post-stack role calls (pazny.wing post, pazny.pulse, etc.).

---

## 3. Secondary race conditions (priority order)

These did not cause the freeze but will bite on a fresh blank. Fix after the
stack_filter refactor.

### 3a. Authentik blueprint race (HIGH)

`tasks/core-up.yml` runs `health.yml` (waits for `/health/ready/`) then
immediately applies blueprints. The readiness endpoint returns 200 **before**
internal system blueprints (flows/stages) reconcile. Result:
`!Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]`
resolves `null` → BookStack, HedgeDoc, and other native-OIDC providers get
`authorization_flow: null` → OIDC logins fail silently.

**Fix:** after health.yml, probe the specific flow by slug with a short retry
loop (`uri` + `retries: 30`, `delay: 5`) before applying OIDC blueprints.

### 3b. Pulse → Wing URL is Traefik-routed (MEDIUM)

`files/anatomy/scripts/pulse-run-agent.sh` uses `WING_API_URL` set to
`http://127.0.0.1:{{ wing_port | default(9000) }}` (localhost:9000, correct).
But the conductor Pulse job env in `roles/pazny.wing/tasks/post.yml:198` also
uses `http://127.0.0.1:{{ wing_port }}` — **this is correct** (direct to Wing,
not through Traefik).

Double-check: Pulse must NOT route through Traefik (`wing.pazny.eu`) — forward-auth
middleware would 302 Pulse requests to Authentik login. Localhost is correct.

### 3c. Loki healthcheck wrong (MEDIUM)

`roles/pazny.loki/templates/compose.yml.j2` healthcheck runs `loki -config.file …
-verify-config` — this checks YAML syntax, not HTTP liveness. The service can
fail to bind its port and still pass the healthcheck.

**Fix:** replace with:
```yaml
healthcheck:
  test: ["CMD-SHELL", "wget -qO- http://localhost:3100/ready || exit 1"]
  interval: 10s
  timeout: 5s
  retries: 5
```

### 3d. Tempo healthcheck disabled (LOW)

`roles/pazny.tempo/templates/compose.yml.j2` has `disable: true` on
the healthcheck. `docker compose up --wait` will hang if tempo never becomes
healthy. Re-enable with:
```yaml
test: ["CMD", "bash", "-c", ":>/dev/tcp/127.0.0.1/3200"]
```

### 3e. `stack_filter` None case for `unknown` plugins (LOW)

11 plugins in the count above lack a `compose_extension.stack` field
(prometheus-base, loki-base, tempo-base etc. have it nested differently).
After implementing stack_filter: audit those 11 to ensure they either:
- Get `stack:` added to their `compose_extension:` block, OR
- Are added to the explicit `stack_filter` list in core-up.yml if they belong
  to infra/observability.

Use `grep -rn "stack:" files/anatomy/plugins/*/plugin.yml` to find them.

---

## 4. Config completeness note

`config.yml` is correct as written. Specifically:

- `install_postgresql` is **auto-enabled** by main.yml pre_tasks (line 763)
  when authentik/infisical/outline/miniflux/hedgedoc/metabase/superset are on.
  The comment at config.yml:57 is accurate.
- `redis_docker` is **auto-enabled** by main.yml pre_tasks (line 779) when
  authentik/infisical/outline/bookstack/firefly/onlyoffice/superset/erpnext are on.
  The comment at config.yml:58 is accurate.
- `install_wing: true` and `install_openclaw: true` are **defaults** in
  `default.config.yml` (lines 268, 273) — no need to add them to config.yml.

The only explicit additions for "install everything" over the current config:

```yaml
install_gitlab: true       # 4 GB RAM; will be slow on first init
install_erpnext: true      # first run often needs auto-retry (handled in erpnext_post.yml)
install_jsos: false        # keep off — redundant with Puter
install_iiab_terminal: true
enable_ssh: true
```

---

## 5. Execution sequence (implement in order)

1. **stack_filter in load_plugins.py** (`run_hook` signature + loop guard)
2. **stack_filter in nos_plugin_loader.py** (module param + pass-through)
3. **core-up.yml post_compose** — add `stack_filter: [infra, observability]`
4. **stack-up.yml** — add post_compose call after async_status join
5. **Test:** `ansible-playbook main.yml --syntax-check` then a `--tags core` dry run
6. Secondary: Authentik blueprint race probe (3a)
7. Secondary: Loki healthcheck (3c), Tempo healthcheck (3d)

Gate: run `python3 tools/aggregator-dry-run.py` after 1–4 to confirm 0 field-diffs.

---

## 6. Context pointers

| Topic | Location |
|---|---|
| Plugin loader source | `files/anatomy/module_utils/load_plugins.py` |
| Ansible module wrapper | `files/anatomy/library/nos_plugin_loader.py` |
| core-up.yml post_compose call | line 522 |
| stack-up.yml async join | lines ~195–220 |
| Post-stack role calls | stack-up.yml lines 225–250 |
| wing/post.yml (B1/B2 fixes) | `roles/pazny.wing/tasks/post.yml` |
| active-work.md | punch list items 12 (A10) + 13 (Phase 5) await this |
