# nOS State

Declarative state layer for nOS. Two files live here:

- **`manifest.yml`** — public, committed, source of truth for *expected*
  system shape. Adds / removes are how you onboard a new service into
  the framework.
- **`schema/*.json`** — JSON Schemas for the runtime state, manifest,
  and migration records. Consumed by tests and agents.

Runtime state is **not** in this directory — it lives at `~/.nos/state.yml`
and is produced per host by `roles/pazny.state_manager/`.

## What each schema guards

| schema                          | validates                                        | owner               |
|---------------------------------|--------------------------------------------------|---------------------|
| `schema/state.schema.json`      | `~/.nos/state.yml`                               | agent 1             |
| `schema/manifest.schema.json`   | `state/manifest.yml`                             | agent 1             |
| `schema/migration.schema.json`  | `migrations/*.yml`                               | agent 1 + agent 2   |
| `schema/upgrade.schema.json`    | `upgrades/*.yml`                                 | agent 6             |
| `schema/event.schema.json`      | payloads from the Ansible callback plugin        | agent 3             |

## Adding a service to the manifest

Open `manifest.yml` and append to the `services:` list. Required keys:

```yaml
- id: my_service          # snake_case, unique
  category: web           # see schema enum
  stack: iiab             # or null for host-native
  install_flag: install_my_service
  version_source: docker_image
  image: myorg/myimage
  container_name: nos-my-service
  port_var: my_service_port
  health_check:
    type: http
    url_template: "http://localhost:{{ my_service_port }}/health"
    expect_status: 200
```

The `nos_state introspect` action walks this list and populates the live
`installed` / `healthy` / `data_path` fields into `~/.nos/state.yml` via the
dispatcher in `module_utils/nos_state_lib.py`.

## State file life cycle

1. **First run (blank host):** `~/.nos/state.yml` is absent. `nos_state read`
   returns the bootstrap skeleton (`empty_state()`) and does NOT error.
2. **`tasks/pre-migrate.yml`** (agent 1) introspects and persists.
3. **`tasks/state-report.yml`** (agent 1) runs in `post_tasks`, bumps
   `generated_at`, records `last_run`, and POSTs the state to Bone so
   Wing's read cache stays fresh.
4. **Migration / upgrade steps** append to `migrations_applied` /
   `upgrades_applied` via `nos_migrate` (agent 2) and `nos_upgrade`
   (agent 6).

File permissions: dir `0700`, file `0600`. Written atomically via
`tempfile + os.replace`.

## Integration hooks exposed by agent 1

Downstream agents import from `module_utils/nos_state_lib.py`:

```python
from ansible.module_utils.nos_state_lib import (
    load_state, dump_state, deep_merge,
    dotted_get, dotted_set, dotted_unset,
    load_manifest, introspect_all,
    empty_state, utcnow_iso, expand_path,
    DEFAULT_STATE_PATH, GENERATOR_ID, CURRENT_SCHEMA_VERSION,
)
```

Ansible-side the public API is the `nos_state` module — see
`library/nos_state.py` for the full argument spec.
