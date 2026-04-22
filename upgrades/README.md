# nOS Upgrade Recipes

Declarative, replayable, per-service version-bump records. Consumed by
`tasks/upgrade-engine.yml` (via `nos_migrate` action handlers from
`module_utils/nos_upgrade_actions/`).

## Relationship to migrations

| | Migrations (`migrations/`) | Upgrades (`upgrades/`) |
|---|---|---|
| **Changes** | identity / structure | version |
| **Cadence** | one-time | recurring |
| **Matched by** | `applies_if` predicate | `from_regex` vs. installed version |
| **Scope** | cross-service (rebrand, rename) | single service |
| **Rollback** | per step | recipe-level |

Upgrades are close cousins of migrations but live on their own axis. A
migration is applied at most once per install; an upgrade recipe fires every
time a system at version X needs to step to version Y.

## File layout

```
upgrades/
├── README.md
├── _template.yml            # annotated example — copy this
├── grafana.yml              # one file per service (matches manifest id)
├── postgresql.yml
├── mariadb.yml
├── authentik.yml
├── redis.yml
└── infisical.yml
```

File id **must** equal the `service:` key inside it, which **must** equal
the service id used in `state/manifest.yml`.

## Recipe schema

See `state/schema/upgrade.schema.json` for the authoritative JSON Schema.
A recipe is:

```yaml
service: grafana                          # matches manifest id
recipes:
  - id: grafana-11-to-12                  # globally unique
    from_regex: "^11\\."                  # Python regex vs. installed version
    to: "12.0.0"                          # target tag
    severity: breaking                    # patch | minor | breaking | security
    coexistence_supported: true           # if true, engine can use nos_coexistence
    coexistence_port_offset: 10           # new track runs on port + offset
    pre:
      - { id: backup_data, type: backup.volume, src: "...", label: "pre-{{ upgrade_id }}" }
    apply:
      - { id: bump_image_tag, type: compose.set_image_tag, service: grafana, tag: "{{ recipe.to }}" }
    post:
      - { id: wait_healthy, type: http.wait, url: "...", expect_status: 200, timeout_sec: 90 }
    rollback:
      - { id: revert_image_tag, type: compose.set_image_tag, service: grafana, tag: "{{ recipe.from_version_resolved }}" }
      - { id: restore_data,     type: backup.restore,       label: "pre-{{ upgrade_id }}" }
```

## How recipes are selected

1. Engine reads `~/.nos/state.yml` → `state.services.<svc>.installed`.
2. Engine loads `upgrades/<svc>.yml` (if it exists).
3. For each recipe in the file, `re.match(recipe.from_regex, installed)`.
4. All matching recipes run **in ascending `id` order** (alphabetic).
5. Each recipe goes through `pre → apply → post` with its own backup label.
6. If any `post` step fails, the recipe's `rollback` list runs in order.

This means a stack jumping two majors (e.g. Grafana 10 → 12) can chain two
recipes: `grafana-10-to-11` then `grafana-11-to-12`. Each is backed up
separately; each may roll back independently.

## Action types (recipe-specific, defined in `module_utils/nos_upgrade_actions/`)

| Type | Purpose |
|---|---|
| `backup.volume`          | tar+gz the data dir into `~/.nos/backups/<label>.tar.gz` |
| `backup.restore`         | untar a prior backup into the data dir |
| `http.wait`              | poll a URL until status ok, fail on timeout |
| `http.get_all`           | fetch JSON (with optional bearer auth) and persist to disk |
| `compose.set_image_tag`  | in-place edit the rendered compose override, then `docker compose up --wait` |
| `compose.restart_service`| `docker compose restart <service>` |
| `custom.module`          | invoke any Ansible module by name with arbitrary args |

The core migration action types (`fs.*`, `exec.shell`, `noop`) are also
available inside upgrade steps — the dispatcher merges both tables.

## `compose.set_image_tag` caveat

The action edits the rendered override file at
`~/stacks/<stack>/overrides/<service>.yml` in place. This is faster than
re-running the owning role's render task, but it means: **if you change the
compose template and the override gets re-rendered by `stack-up.yml` on a
later playbook run, your manual tag may be overwritten by the role's
defaulted `<service>_version`.** The upgrade engine resolves this by also
writing `services.<svc>.desired` into `~/.nos/state.yml`; the role's render
task should read from state when present. Until that hook lands, operators
should bump `<service>_version` in their own `config.yml` after running an
upgrade. The recipe's final `post` step emits a warning to that effect.

## Backup labels

Every `backup.volume` step uses label `pre-{{ upgrade_id }}-{{ ts }}` where
`ts` is the engine's run timestamp (ISO-8601, second precision). This is
guaranteed unique per run and lets `rollback` steps resolve the exact tarball
without ambiguity.

## Adding a new recipe

1. Create or edit `upgrades/<service>.yml` (one file per service).
2. Add a recipe block with a unique `id`.
3. Write `from_regex` tight enough to not catch adjacent majors (e.g.
   `^15\\.` for Postgres 15, not `^1`).
4. Mark `severity` honestly: `breaking` triggers an operator prompt.
5. Mark `coexistence_supported: true` only for stateful services where
   `nos_coexistence` can clone data (Grafana bind mount, Postgres via
   `pg_dump`, MariaDB via `mariadb-dump`).
6. Validate: `pytest tests/upgrades/ -k schema`.

## Execution tags

```bash
# Scan all services, apply any matching recipes.
ansible-playbook main.yml -K --tags upgrade

# Target a single service / recipe explicitly.
ansible-playbook main.yml -K --tags upgrade \
  -e upgrade_service=grafana \
  -e upgrade_recipe_id=grafana-11-to-12

# Dry run — no side effects, just plan.
ansible-playbook main.yml -K --tags upgrade -e upgrade_dry_run=true
```
