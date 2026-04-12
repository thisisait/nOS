# Wave 2 — Role Migration Design

Status: Wave 2.1 pilot **complete**; Wave 2.2 parallel batch **in progress**. Target branch: `dev`. Pilot scope (done): three roles — `pazny.glasswing`, `pazny.mariadb`, `pazny.grafana`.

This document describes how the devBoxNOS playbook migrates from inline `tasks/` files plus monolithic `templates/stacks/<stack>/docker-compose.yml.j2` files into per-service Ansible roles. It was originally the operational plan for the Wave 2.1 pilot; it has been revised post-pilot to capture the lessons learned and serve as the authoritative spec for the Wave 2.2 parallel batch and all future sprints.

---

## 1. Context & motivation

Wave 1 of the state-declarative refactor landed on `dev`, followed by the Wave 2.1 role-extraction pilot. The relevant commits, top to bottom of `git log dev`:

- `3c2a5d3` — feat(roles): extract grafana into `pazny.grafana` role (Wave 2.1 pilot)
- `9ba0bfc` — feat(roles): extract mariadb into `pazny.mariadb` role (Wave 2.1 pilot)
- `3719258` — feat(roles): extract glasswing into `pazny.glasswing` role (Wave 2.1 pilot)
- `2c4daae` — feat(core-up): enumerate compose overrides for per-role fragments
- `075a79d` — docs: wave 2 role migration design (this doc, initial draft)
- `ec3e3c8` — refactor(verify): data-driven `stack_verify` via health-probes catalog
- `73622b8` — fix(handlers): repair stack paths and add missing `Restart boxapi`
- `8e822a2` — drift detection on mutating `occ` and `psql` tasks via stdout markers
- `10a2bae` — `install_observability` defaults to true in all referring expressions
- `5b3ec90` — `default_admin_email` var, drop `admin@dev.local` literals
- `2a5b0f0` — canonicalize `docker exec` to `compose -p <proj> exec -T <svc>`
- `57017a0` — replace dead-code `changeme_*` fallbacks with prefix templates
- `697517e` — handlers, blank hardening, prefix persistence, stateless secrets
- `4c65ba7` — state-declarative admin password reconverge across all services
- `de7c544` — Galaxy collections + idempotence smoke test (`tests/test-idempotence.sh`)
- `e0ff16e` — Authentik blueprints replace `oidc_setup`

The playbook is idempotent end to end, secrets reconverge declaratively from `global_password_prefix`, `stack_verify.yml` is data-driven via the P0.2 health-probes catalog, and the Wave 2.1 pilot proved the role-extraction pattern end to end. The **structural** refactor is now in progress: extract services into standalone roles so they can be:

1. **Reused across client deployments.** Each Czechbot.eu client box wires together a different subset of the catalogue (HQ vs factory vs sales — see `docs/fleet-architecture.md`). A role-shaped service is something a client playbook can `include_role:` and skip the parts it does not need.
2. **Extracted to per-service Galaxy repos in Wave 3.** When `pazny.mariadb` is a self-contained directory with `defaults/`, `tasks/`, `templates/`, `meta/`, and a README, lifting it into `github.com/pazny/ansible-role-mariadb` is a `git mv` plus a `requirements.yml` entry. The pilot proved this shape works end to end.
3. **Cleaner separation between orchestration and service logic.** `main.yml`, `tasks/stacks/core-up.yml`, and `tasks/stacks/stack-up.yml` are the orchestration spine. They know about ordering, networks, and the always-first invariant — not about MariaDB users or Grafana provisioning paths.

The full multi-wave roadmap lives in `~/.claude/plans/batch-refactor-roadmap.md` (out of repo, planning notes) and the Wave 2.2 parallel-batch plan in `~/.claude/plans/magical-finding-bird.md`. This in-repo doc is the authoritative spec for role-extraction workers: lessons learned, canonical role shape, sequencing contract, testing workflow.

---

## 1a. Wave 2.1 lessons learned (authoritative for Wave 2.2+)

The Wave 2.1 pilot surfaced several patterns that were either ambiguous in the original design or wrong in the "Known gotchas" section. These rows are binding for every subsequent worker — do not re-litigate them.

| Area | Lesson | Implication for Wave 2.2+ |
|---|---|---|
| **Compose include** | The find+merge pattern via `ansible.builtin.find` over `{{ stacks_dir }}/<stack>/overrides/*.yml` plus `{% for f in _overrides.files \| sort(attribute='path') %}-f "{{ f.path }}" {% endfor %}` in the `docker compose` shell command works. `tasks/stacks/core-up.yml` lines 247–320 is the reference implementation. Backward compatible with an empty `overrides/` directory (empty list → no extra `-f` flags). | `tasks/stacks/stack-up.yml` needs the same plumbing for the six non-core stacks (`iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`). This is Wave 2.2 Unit 2's sole deliverable and **must** land before the coordinator wires role calls into stack-up. |
| **Compose networks** | Override fragments do **not** redeclare top-level `networks:`. `infra_net`, `observability_net`, and `{{ stacks_shared_network }}` stay declared in the base compose. Compose merge semantics let overrides reference networks by name as long as some merged file declares them. The original Section 9 guidance (copy the networks stanza into every role fragment) was overly defensive — the pilot proved it unnecessary. | Worker compose templates have no top-level `networks:` key. Only `services.<svc>.networks: [infra_net, "{{ stacks_shared_network }}"]` as a service-scoped list. Any worker who copy-pastes the networks block is wrong. |
| **Tag inheritance** | `--tags mariadb` does not propagate into `include_role` automatically. The pilot wires both `apply: { tags: ['mariadb', 'database'] }` **and** a top-level `tags: ['mariadb', 'database']` on the `include_role` task. Using only one of the two selects the wrong subset of tasks. | Coordinator (Phase B) uses both on every `include_role` in `core-up.yml` / `stack-up.yml`. Verify via `ansible-playbook main.yml --list-tags` before pushing. |
| **Handler ownership** | Shared handlers (`Restart nginx`, `Restart php-fpm`, `Restart alloy`) stay play-level in `main.yml` — any role can `notify:` them. Service-specific handlers (`Restart mariadb`, `Restart grafana`) live in **both** places: play-level in `main.yml` **and** `roles/pazny.<svc>/handlers/main.yml`. The play-level wins when notified from outside the role; the role-local is there for standalone use outside the devBoxNOS playbook. Duplication is intentional and harmless. | Workers copy the service-specific handler into `roles/pazny.<svc>/handlers/main.yml` but do **not** remove the play-level version. Play-level handler pruning is a deliberate follow-up after Wave 2.2 Phase C smoke test passes. |
| **Credentials centralization** | `*_password` entries stay in the top-level `default.credentials.yml` so `global_password_prefix` reconverge works centrally. Role `defaults/main.yml` does **not** redeclare credentials — only neutral config (`*_version`, `*_port`, `*_data_dir`, seed lists with `[]` fallback, mem/cpu limits). | Workers copy only neutral config to role defaults. Do not move `mariadb_root_password` / `grafana_admin_password` / `authentik_postgres_password` / etc. into role defaults. |
| **Role defaults mirror config** | Role `defaults/main.yml` mirrors the `<svc>_*` vars from `default.config.yml` with empty-list fallbacks (`mariadb_databases: []`, `mariadb_users: []`) so the role is self-sufficient when consumed from outside the playbook. The central `default.config.yml` stays single source of truth — Ansible's `vars_files > role defaults` precedence ensures runtime uses the centralized value. | Pattern from `roles/pazny.mariadb/defaults/main.yml` is the template. Role runs cleanly both inside devBoxNOS (uses central vars) and standalone (uses empty-list defaults). |
| **Provisioning / host configs** | Provisioning files that depend on play-level state (`authentik_oidc_*`, service registry, cross-service facts) **stay in `core-up.yml` / `stack-up.yml`**. The role owns only its compose fragment and post-start script. Grafana's `files/observability/grafana/provisioning/*.yml.j2` is the pilot's precedent — those renders are still in `core-up.yml` even though the grafana compose block moved into the role. | Worker migrates per-service code only. Cross-service provisioning (Authentik blueprints, ERPNext bench migrate inside `erpnext_post.yml`, Superset init, Bluesky PDS bridge) stays in `tasks/stacks/` for Wave 2.2. |
| **Override file placement convention** | Every role renders its compose fragment to `{{ stacks_dir }}/<stack>/overrides/<svc>.yml`. The filename is the **service name**, not the role name (e.g. `mariadb.yml`, not `pazny.mariadb.yml`). The `overrides/` directory is created up-front by `core-up.yml` (for infra/observability) and, after Wave 2.2 Unit 2 lands, by `stack-up.yml` (for the six non-core stacks). | Hardcoded convention — workers never invent their own path. Render target string is mechanical: `{{ stacks_dir }}/<owning-stack>/overrides/<svc-name>.yml`. |
| **Role location** | `roles/pazny.*/` in-repo, **not** `galaxy_roles/` or an external Galaxy repo. Wave 3 extraction to `pazny/ansible-role-<svc>` repos via `git filter-repo` is deferred until after Wave 2.2 Phase C smoke test passes. Reason: client boxes still share one playbook; early extraction triples operational overhead (version pinning, per-role CI, requirements.yml churn). | **Lock in**: every Wave 2.2 role lands in `roles/pazny.<svc>/` in this repo. Do not create a `galaxy_roles/` tree or any sibling layout. |
| **Test strategy** | `--tags <svc>` is unreliable as a test until tag inheritance is fixed end to end. Per-worker test contract: `ansible-playbook main.yml --syntax-check` (must pass), `ansible-lint roles/pazny.<svc>/` (must pass at default profile), `yamllint roles/pazny.<svc>/` (must be clean). Full `--blank` smoke test is run **once** by the user after Phase B coordinator integration. | Workers do not run live playbooks. Static validation only. Runtime regressions are exposed in Phase C, not Phase A. |
| **Integration timing** | Wave 2.2 workers never touch `main.yml`, `core-up.yml`, or `stack-up.yml`. Orchestration rewiring is a single atomic coordinator commit in Phase B. The legacy `include_tasks` path keeps running alongside dormant role directories until the coordinator flips the switch. This keeps `--syntax-check` green between worker merges. | Worker PRs squash-merge to `dev` with zero runtime regression. The role dirs sit dormant; the playbook still executes the old task files. |

### Role location — LOCKED decision

See the "Role location" row in the table above. Callout restated because several pre-pilot discussions flirted with `galaxy_roles/` and external Galaxy repos: **all Wave 2.2 roles land in `roles/pazny.<svc>/` in this repo, alongside the existing `pazny.dotfiles`, `pazny.mac.homebrew`, `pazny.mac.mas`, `pazny.mac.dock`**. Galaxy extraction is Wave 3, deferred past the Phase C smoke test.

---

## 2. Compose-include pattern (the critical architectural decision)

### Chosen strategy: Option (a) — per-role compose override files

Each role's `templates/compose.yml.j2` renders to `{{ stacks_dir }}/<stack>/overrides/<svc>.yml`. The orchestrator (`core-up.yml`, `stack-up.yml`) enumerates `overrides/*.yml` at run time with `ansible.builtin.find` and passes each match as an additional `-f` flag to `docker compose`.

Concrete example for the infra stack post-pilot:

```yaml
- name: "[Core] Discover infra compose overrides from roles"
  ansible.builtin.find:
    paths: "{{ stacks_dir }}/infra/overrides"
    patterns: "*.yml"
  register: _infra_overrides
  failed_when: false

- name: "[Core] Build infra compose -f flag list"
  ansible.builtin.set_fact:
    _infra_compose_files: >-
      -f "{{ stacks_dir }}/infra/docker-compose.yml"
      {% for f in (_infra_overrides.files | default([]) | sort(attribute='path')) -%}
      -f "{{ f.path }}"
      {% endfor %}

- name: "[Core] Start INFRA stack (docker compose up --wait)"
  ansible.builtin.shell: >
    {{ docker_bin }} compose
    {{ _infra_compose_files }}
    -p infra
    up -d --remove-orphans --wait --wait-timeout 120
```

Properties of this approach:

- **Base file shrinks.** `templates/stacks/infra/docker-compose.yml.j2` shrinks as services migrate out. Eventually it may contain only the `networks:` declaration (the `infra_net` bridge plus the external `{{ stacks_shared_network }}` reference). That is the steady state — the base file becomes a network declaration the per-service overrides attach to.
- **Backward compatible.** An empty `overrides/` directory means the `find` registers `_infra_overrides.files == []`, no extra `-f` flags are added, and `docker compose` runs with the base file alone — exactly how things work today pre-migration. The pilot can land one role at a time without breaking the others.
- **Sorted enumeration.** `sort(attribute='path')` keeps the merge order deterministic across runs — important for compose key precedence (later `-f` files override earlier ones for scalar fields, deep-merge for maps/lists).
- **Per-service ordering** is still controlled by `core-up.yml` (see Section 5). Compose itself does not promise startup order beyond `depends_on`, and merging files does not change that.

### Option (b) — single merged compose rendered by an orchestrator (REJECTED)

Have a top-level Ansible task collect per-role compose fragments via `lookup('file', ...)` or `include_tasks` and assemble one big `docker-compose.yml` per stack.

Rejected because:
- It adds a rendering layer that has to understand YAML merging semantics, which `docker compose -f` already handles natively.
- It still tightly couples roles to their parent stack — the orchestrator has to know which fragments belong to `infra` vs `observability`.
- It reintroduces the monolithic file under a new name. The whole point of Wave 2 is that no single file should describe more than one service.

### Option (c) — per-service compose projects (REJECTED)

Run each service as its own compose project (`docker compose -p mariadb up`, `docker compose -p grafana up`, …).

Rejected because:
- It explodes the number of running compose projects from ~8 (one per stack) to ~40 (one per service). That breaks `docker compose ls`, Portainer's stack view, and the operator's mental model of "infra is up / iiab is up".
- Cross-service networking would require explicit `external: true` networks linked into every project, instead of the current `stacks_shared_network` that all stacks join. Today a service in `iiab` reaching `mariadb` in `infra` works because both compose projects attach to the same external bridge — Wave 2 must preserve that.
- Volume names and project labels would become the per-service unique key, breaking the assumption that `docker compose -p infra down -v` cleans up everything infra-related.

---

## 3. Canonical role skeleton

Target directory layout for one role, reflecting what the Wave 2.1 pilot actually shipped. `pazny.mariadb` is the exemplar because it has all the interesting pieces: compose fragment, post-start task, service-specific handler, cross-service consumers.

```
roles/pazny.mariadb/
├── defaults/
│   └── main.yml             # neutral config (version, port, data_dir, mem/cpu, empty seed lists)
├── tasks/
│   ├── main.yml             # thin orchestrator: create dirs, render compose override, notify
│   └── post.yml             # post-start: verify connection, drop test DB, create DBs/users
├── templates/
│   └── compose.yml.j2       # services.mariadb: block only — NO top-level networks:
├── handlers/
│   └── main.yml             # role-local Restart mariadb (play-level duplicate wins at runtime)
├── meta/
│   └── main.yml             # collections: [community.mysql], dependencies: []
└── README.md                # variables, dependent services, usage notes
```

### Source map — `pazny.mariadb` (as shipped in commit `9ba0bfc`)

| Role file | Source in pre-pilot repo | Pilot outcome (post-pilot paths) |
|---|---|---|
| `roles/pazny.mariadb/defaults/main.yml` | `mariadb_*` block from `default.config.yml` — neutral config only | Holds `mariadb_version`, `mariadb_port`, `mariadb_data_dir`, `mariadb_mem_limit`, `mariadb_cpus`, plus empty `mariadb_databases: []` / `mariadb_users: []` fallbacks. Credentials (`mariadb_root_password`) stay in `default.credentials.yml`. |
| `roles/pazny.mariadb/tasks/main.yml` | New thin orchestrator | Two tasks: `file: state=directory` for `{{ mariadb_data_dir }}`, then `template: src=compose.yml.j2 dest={{ stacks_dir }}/infra/overrides/mariadb.yml` with `notify: Restart mariadb`. |
| `roles/pazny.mariadb/tasks/post.yml` | Verbatim move from `tasks/iiab/mariadb_setup.yml` | `community.mysql.mysql_info` connection probe with retry loop, `mysql_db` remove-test-db + create-databases, `mysql_user` loop over `mariadb_users`. Invoked from `core-up.yml` via `include_role: tasks_from: post.yml` after `docker compose up infra --wait`. |
| `roles/pazny.mariadb/templates/compose.yml.j2` | Lifted from the `mariadb:` service block in `templates/stacks/infra/docker-compose.yml.j2` | Wrapped in `services:` map. `services.mariadb.networks: [infra_net, "{{ stacks_shared_network }}"]` references by name only — **no top-level `networks:` declaration**. |
| `roles/pazny.mariadb/handlers/main.yml` | Copy of `Restart mariadb` from `main.yml:118` | Role-local duplicate. Play-level handler at `main.yml:118` stays in place and takes precedence at runtime; role-local exists for standalone use. |
| `roles/pazny.mariadb/meta/main.yml` | Extracted from `requirements.yml` | `galaxy_info.namespace: pazny`, `galaxy_info.role_name: mariadb`, `dependencies: []`, `collections: [community.mysql]`. |
| `roles/pazny.mariadb/README.md` | New file | Variables reference, dependent-service catalog, standalone-use notes. |

Invocation from `tasks/stacks/core-up.yml`:

```yaml
- name: "[Core] Render pazny.mariadb compose override + data dir"
  ansible.builtin.include_role:
    name: pazny.mariadb
    apply:
      tags: ['mariadb', 'database']
  when: install_mariadb | default(false)
  tags: ['mariadb', 'database']

# ... later, after `docker compose up infra --wait` ...

- name: "[Core] MariaDB post-start (pazny.mariadb role → tasks/post.yml)"
  ansible.builtin.include_role:
    name: pazny.mariadb
    tasks_from: post.yml
    apply:
      tags: ['mariadb', 'database']
  when:
    - install_mariadb | default(false)
    - _core_infra_enabled | bool
  tags: ['mariadb', 'database']
```

### Source map — `pazny.grafana` (as shipped in commit `3c2a5d3`)

| Role file | Source in pre-pilot repo | Pilot outcome (post-pilot paths) |
|---|---|---|
| `roles/pazny.grafana/defaults/main.yml` | `grafana_*` block from `default.config.yml` — neutral config only | `grafana_version`, `grafana_port`, `grafana_domain`, `grafana_data_dir`, `grafana_admin_user`, `grafana_allow_embedding`, `grafana_analytics`, mem/cpu. `grafana_admin_password` stays in `default.credentials.yml`. |
| `roles/pazny.grafana/tasks/main.yml` | New thin orchestrator | `file: state=directory` for `{{ grafana_data_dir }}`, then render `compose.yml.j2` to `{{ stacks_dir }}/observability/overrides/grafana.yml` with `notify: Restart grafana`. Provisioning file renders **stay in `core-up.yml`** because they depend on `authentik_oidc_*` and service registry facts. |
| `roles/pazny.grafana/tasks/post.yml` | Verbatim move from `tasks/iiab/grafana_admin.yml` | Container health probe via `docker compose -p observability ps -q grafana`, HTTP `/api/health` wait with `uri` retry loop, then `grafana-cli admin reset-admin-password` for declarative password reconverge. Invoked from `core-up.yml` after `docker compose up observability --wait`. |
| `roles/pazny.grafana/templates/compose.yml.j2` | Grafana service block from `templates/stacks/observability/docker-compose.yml.j2` | Wrapped in `services:` map. Preserves OIDC env vars guarded by `{% if install_authentik \| default(false) %}`. References to `authentik_oidc_grafana_client_id` / `_client_secret` still resolve through the centralized `authentik_oidc_apps` registry in `default.config.yml`. `services.grafana.networks: [observability_net, "{{ stacks_shared_network }}"]` by name only — **no top-level `networks:` declaration**. |
| `roles/pazny.grafana/handlers/main.yml` | Copy of `Restart grafana` from `main.yml:141` | Role-local duplicate; play-level handler wins at runtime. |
| `roles/pazny.grafana/meta/main.yml` | New file | `galaxy_info.namespace: pazny`, `galaxy_info.role_name: grafana`, `dependencies: []`, `collections: []`. |
| `roles/pazny.grafana/README.md` | New file | Variables, provisioning-vs-role boundary rationale, standalone-use notes. |

**Grafana-specific pattern note:** the `files/observability/grafana/provisioning/datasources/all.yml.j2` and `files/observability/grafana/provisioning/dashboards/all.yml.j2` renders remain in `core-up.yml` (see the "Deploy Grafana datasources/dashboards provisioning" tasks around lines 208–222). They depend on play-level Authentik/service-registry state and moving them into the role would require plumbing those vars through role parameters — a net loss. This is the canonical example of the "provisioning stays central" rule in the lessons-learned table.

### Source map — `pazny.glasswing` (as shipped in commit `3719258`)

| Role file | Source in pre-pilot repo | Pilot outcome |
|---|---|---|
| `roles/pazny.glasswing/defaults/main.yml` | `glasswing_*` block from `default.config.yml` | `glasswing_domain`, `glasswing_app_dir`, `glasswing_data_dir`, `glasswing_json_source`. |
| `roles/pazny.glasswing/tasks/main.yml` | Verbatim move from `tasks/glasswing.yml` | Rsync of `{{ playbook_dir }}/files/project-glasswing/`, composer install, SQLite DB bootstrap, nginx vhost notify (via play-level `Restart nginx` / `Restart php-fpm`). |
| `roles/pazny.glasswing/meta/main.yml` | New file | `dependencies: []`, `collections: [ansible.posix]` (for `synchronize`). |
| `roles/pazny.glasswing/handlers/main.yml` | — | **Does not exist.** Glasswing relies entirely on play-level shared handlers (`Restart nginx`, `Restart php-fpm`) — the pilot proved that notify from a role to a play-level handler works. No service-specific handler needed. |
| `roles/pazny.glasswing/templates/` | — | **Does not exist.** Glasswing is non-Docker (nginx vhost + PHP-FPM). No compose fragment, no `{{ stacks_dir }}/<stack>/overrides/` render. |
| `files/project-glasswing/` | Unchanged | **Stays in place.** The role rsyncs it from `{{ playbook_dir }}/files/project-glasswing/`; treating it as role `files/` would force every consumer to vendor the Nette PHP app. Same rule applies to jsOS, OpenClaw, iiab-terminal when those migrate in Wave 2.2. |

Glasswing is the template for **task-only roles** (non-Docker, no compose override). The Wave 2.2 `non-docker-services` worker (Unit 13) uses this exact shape for `pazny.jsos`, `pazny.iiab_terminal`, `pazny.openclaw`, `pazny.boxapi`.

### Override file placement convention

Every role's compose render target is a hardcoded pattern — workers do not invent their own paths:

```
{{ stacks_dir }}/<owning-stack>/overrides/<service-name>.yml
```

Examples from the pilot:

| Service | Owning stack | Override file |
|---|---|---|
| `mariadb` | `infra` | `{{ stacks_dir }}/infra/overrides/mariadb.yml` |
| `grafana` | `observability` | `{{ stacks_dir }}/observability/overrides/grafana.yml` |

The `overrides/` subdirectory is created up-front by `core-up.yml`:

```yaml
- name: "[Core] Ensure infra and observability subdirectories exist"
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
    mode: '0755'
  loop:
    - "{{ stacks_dir }}/infra"
    - "{{ stacks_dir }}/infra/overrides"
    - "{{ stacks_dir }}/observability"
    - "{{ stacks_dir }}/observability/overrides"
    # ...
```

After Wave 2.2 Unit 2 lands, `stack-up.yml` will create the equivalent directories for `iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`. Workers for those stacks then render into `{{ stacks_dir }}/<stack>/overrides/<svc>.yml` with zero glue code.

### What stays in the main repo

Do not move into roles:

- **`files/project-<name>/`** — internal app source (Glasswing/jsOS/OpenClaw/iiab-terminal/boxapi). The role rsyncs from `{{ playbook_dir }}/files/project-<name>/`; treating it as role `files/` would force every consumer to vendor the app. Wave 3 extracts these into per-project repos.
- **`default.credentials.yml` / `credentials.yml`** — central secrets. Role defaults reference variables (`{{ mariadb_root_password }}`, `{{ grafana_admin_password }}`, etc.) that resolve through the central credentials file. See Section 7.
- **`requirements.yml`** — authoritative install list for Ansible Galaxy collections. Per-role `meta/main.yml` is documentation plus a soft assert; CI installs from `requirements.yml`.
- **`main.yml`** — play-level handlers (`Restart nginx`, `Restart php-fpm`, shared `Restart <svc>` duplicates) and the role wiring itself.
- **`default.config.yml`** — single source of truth for install toggles (`install_*`, `configure_*`), the `authentik_oidc_apps` registry, RBAC tier maps, and runtime-only play-level vars. Role defaults mirror the neutral subset but do not replace the central file.
- **Cross-service `tasks/stacks/*` orchestrators** — `authentik_blueprints.yml`, `authentik_service_post.yml`, `bluesky_pds_bridge.yml`, and parts of `erpnext_post.yml` / `superset_setup.yml` that touch multiple services or the central registry. These stay in `tasks/stacks/` for Wave 2.2.

---

## 4. Per-service migration order

### Wave 2.1 — pilot (DONE)

1. **`pazny.glasswing`** (commit `3719258`) — simplest first. Non-Docker, no compose override, no post-start surprises, no shared-network coupling. Proved the role wiring: `include_role` from inside `tasks:`, handler visibility, tag inheritance via `apply: { tags: [...] }` + top-level `tags:`. Result: `notify: Restart php-fpm` from a role fires the play-level handler cleanly.
2. **`pazny.mariadb`** (commit `9ba0bfc`, after `2c4daae` added the core-up find+merge plumbing) — introduced the compose-override pattern and the post-start task pattern. MariaDB is the template for every Docker role to come: no provisioning files, no SSO env vars, no host-side configs. Result: override fragment renders to `{{ stacks_dir }}/infra/overrides/mariadb.yml`, `core-up.yml` picks it up via `find`, post-start creates DBs and users against the running container.
3. **`pazny.grafana`** (commit `3c2a5d3`) — added the pieces glasswing and mariadb skipped: post-start admin password reconverge via `grafana-cli`, HTTP health probe, OIDC env vars guarded by `{% if install_authentik %}`. Result: `services.grafana.networks` references `observability_net` and `{{ stacks_shared_network }}` **without** redeclaring the top-level `networks:` key — the original Section 9 "stacks_shared_network gotcha" was overly defensive.

### Wave 2.2 — parallel batch (IN PROGRESS)

The remaining ~35 services are being extracted in parallel by 13 workers. The risk tiering below is the revised view after Wave 2.1 analysis — specifically, **Authentik has been elevated** from the original "High risk" grouping to effectively its own tier because of blueprint ownership (see Unit 5 in `~/.claude/plans/magical-finding-bird.md`), and the "very high risk" category has been collapsed into "high risk" because the first-boot state concerns turn out to be post-start orchestration, not role-boundary problems.

Per-worker dispatch (unit number → services → stack file) lives in `~/.claude/plans/magical-finding-bird.md` Worker Dispatch Summary. Risk tiering is for the coordinator's Phase B integration order (merge low-risk worker PRs first so rebases stay cheap).

**Low risk** (single container, optional post-start, no SSO complications):
- `pazny.uptime_kuma`, `pazny.calibre_web`, `pazny.jellyfin`, `pazny.kiwix`, `pazny.rustfs`, `pazny.vaultwarden`, `pazny.freepbx`, `pazny.qgis_server`, `pazny.outline`, `pazny.freescout`, `pazny.portainer`, `pazny.traefik`, `pazny.offline_maps` (tileserver), `pazny.boxapi`, `pazny.iiab_terminal`

These follow the mariadb/glasswing template almost verbatim. Check per service that the nginx vhost in `templates/nginx/sites-available/` still references the right hostname after the role declares its compose port.

**Medium risk** (foundation services, multiple consumers, post-start setup, some cross-service dependencies):
- `pazny.postgresql`, `pazny.redis`, `pazny.prometheus`, `pazny.loki`, `pazny.tempo`, `pazny.metabase`, `pazny.superset`, `pazny.woodpecker`, `pazny.gitea`, `pazny.gitlab`, `pazny.wordpress`, `pazny.puter`, `pazny.homeassistant`, `pazny.open_webui`, `pazny.jsos`, `pazny.openclaw`

Gotcha: every service that uses `pazny.postgresql` / `pazny.redis` / `pazny.tempo` as a backend reads connection details from variables today living next to the consumer's compose block. No role-to-role contract is being introduced in Wave 2.2 — the consumer still reads `{{ postgresql_admin_user }}` / `{{ redis_password }}` from central config. Worker just moves the compose fragment; connection wiring stays where it is.

**High risk** (cross-service orchestration, schema migrations, post-start hair):
- `pazny.nextcloud`, `pazny.gitea` (already in medium above — duplicated intentionally, see below), `pazny.erpnext`, `pazny.infisical`, `pazny.bluesky_pds`, `pazny.paperclip`, `pazny.n8n`

Gotcha: these services run first-boot migrations (ERPNext `bench migrate`, Nextcloud `occ upgrade`, n8n DB init), have session-based password reconverge loops (FreeScout-style `artisan tinker`), or own state that cannot be re-derived from `credentials.yml` alone (Infisical encryption key, Bluesky PDS rotation key, Paperclip S3 creds in a sub-database). **The role owns only the compose fragment and pre-compose setup.** Post-start scripts stay in `tasks/stacks/` (ERPNext, Bluesky, Paperclip) or in `roles/pazny.<svc>/tasks/post.yml` invoked from `core-up.yml` / `stack-up.yml` via `include_role: tasks_from: post.yml` (Authentik `post.yml`, Infisical `post.yml`).

**Very high risk — Authentik** (the one role that needs its own tier):

`pazny.authentik` was originally grouped with the high-risk tier. Wave 2.1 analysis of the blueprint infrastructure (`tasks/stacks/authentik_blueprints.yml` + three `templates/authentik/blueprints/*.yaml.j2` files + the shared bind-mount path `{{ stacks_dir }}/infra/authentik/blueprints:/blueprints/custom:ro`) shows it deserves its own pass:

- **Blueprint ownership.** Three blueprint templates render to a bind-mount path that the Authentik container reads on startup. Moving the templates into the role means the render task moves too, but the bind-mount path stays in the compose fragment — workers must preserve the exact path string so the compose merge does not drift.
- **Post-start sequencing.** `tasks/stacks/authentik_post.yml` (health check, initial API bootstrap) moves into `roles/pazny.authentik/tasks/post.yml`. But `tasks/stacks/authentik_service_post.yml` (Gitea OAuth2 source patch, Nextcloud `user_oidc` provider setup, Authentik→PDS bridge) **stays in `tasks/stacks/`** because it's cross-service orchestration.
- **Blueprint reapply handler.** `Reapply authentik blueprints` (`main.yml:237-243`) is a notify target for blueprint template changes. It stays play-level for cross-role notify compatibility.
- **`authentik_oidc_apps` registry read-only contract.** The role **reads** the centralized registry from `default.config.yml` via blueprint templates but does **not** own it. Other services' compose fragments reference `authentik_oidc_<svc>_client_id` / `_client_secret` derived vars, which also stay centralized. This is the central rule that prevents `pazny.authentik` from becoming a godrole.

Worker responsible for Authentik (Unit 5 in the Wave 2.2 dispatch matrix) should expect this to be the longest-running PR in the batch. Budget accordingly.

For each tier, the coordinator merges worker PRs in tier order so rebases stay trivial on the shared `templates/stacks/infra/docker-compose.yml.j2` file. Tier order: low risk → medium → high → Authentik.

---

## 5. Post-start sequencing strategy

`core-up.yml` owns a strict sequence that roles depend on:

1. Render compose templates (infra + observability base files).
2. Invoke `pazny.mariadb` / `pazny.grafana` pre-compose render (`include_role: name=pazny.<svc>` — writes `overrides/<svc>.yml`).
3. Enumerate `overrides/*.yml` via `ansible.builtin.find`.
4. `docker compose -f base -f override... -p infra up -d --wait`.
5. MariaDB post-start (`include_role: name=pazny.mariadb tasks_from=post.yml`).
6. PostgreSQL post-start (`include_tasks: tasks/stacks/postgresql_setup.yml`, will become a role call in Wave 2.2).
7. `docker compose -f base -f override... -p observability up -d --wait`.
8. Grafana admin password reconverge (`include_role: name=pazny.grafana tasks_from=post.yml`).
9. Authentik / Infisical / Bluesky PDS post-start.

This ordering matters. Grafana's compose env vars assume the Postgres `grafana` user exists (otherwise the container restart-loops on first boot). Authentik needs the schema ready before its bootstrap user can be created. Bluesky PDS post-start needs the container running before `goat` can hit it. Any sequencing change risks a cascade of first-boot failures that take a `blank=true` rerun to clear.

### Option A — `core-up.yml` keeps sequencing authority (PROVEN in pilot, Wave 2.2 default)

The role's `tasks/main.yml` handles everything that has to happen *before* compose up: directory creation, compose fragment rendering. The role's `tasks/post.yml` handles everything that has to happen *after* compose up: DB users, password reconverge, OIDC client registration.

`core-up.yml` / `stack-up.yml` call them explicitly:

```yaml
- name: "[Core] MariaDB post-start (pazny.mariadb role → tasks/post.yml)"
  ansible.builtin.include_role:
    name: pazny.mariadb
    tasks_from: post.yml
    apply:
      tags: ['mariadb', 'database']
  when:
    - install_mariadb | default(false)
    - _core_infra_enabled | bool
  tags: ['mariadb', 'database']
```

Pros (confirmed):
- Explicit, debuggable. The orchestration spine still answers "what runs in what order" without consulting role metadata.
- Tags work deterministically given the `apply: { tags: [...] }` + top-level `tags:` pattern.
- Worker diff is a mechanical swap (`include_tasks` → `include_role`) done once by the coordinator in Phase B.

Cons (observed):
- `core-up.yml` and `stack-up.yml` grow as roles land. Each new role with a `post.yml` adds two blocks (pre-compose render, post-compose setup). For ~35 Wave 2.2 services, that is ~70 new blocks across the two orchestrator files.

### Option B — meta-dependency-driven sequencing (DEFERRED past Wave 2.2)

Roles declare `meta/main.yml` dependencies (`pazny.grafana` depends_on `pazny.postgresql`). Post-start moves into `tasks/main.yml` with `wait_for` guards on the upstream service's health endpoint. Ansible's role dependency resolver handles ordering.

Cons (same as original draft):
- Subtle race conditions. `wait_for` against a healthcheck endpoint is not the same as "the post-start of the upstream role has completed" — the endpoint may be reachable while the user creation step is still running.
- The Ansible dependency graph mirrors nothing Docker knows about. Healthchecks, `depends_on: condition: service_healthy`, and the actual schema state are all separate signals.
- Hard to debug. When a sequence breaks, the error surfaces deep inside a role with no obvious link to the dependency that was supposed to satisfy it.

**Decision:** Option A for Wave 2.2. Re-evaluate after Phase C smoke test with real data on how big the two orchestrator files have grown.

---

## 6. Testing workflow

Wave 2.1 pilot ran steps 1–4 per role. **Wave 2.2 workers run only steps 1–2.** Live playbook execution (step 3 onwards) is deferred to the Phase B coordinator and the Phase C user smoke test.

### Per-worker contract (Wave 2.2 Phase A)

```bash
# 1. Syntax check — fails fast on YAML / Jinja errors
ansible-playbook main.yml --syntax-check

# 2. Static analysis — role-scoped lint
ansible-lint roles/pazny.<svc>/
yamllint roles/pazny.<svc>/
```

Both must pass before the worker opens its PR. Workers do **not** run `ansible-playbook -K`, `--check`, or `--blank`. The legacy `include_tasks` path keeps the playbook runnable while the role sits dormant; runtime validation is coordinator/user scope.

### Per-coordinator contract (Phase B atomic commit)

```bash
# Same as above, repo-wide
ansible-playbook main.yml --syntax-check
ansible-lint roles/
yamllint roles/

# Tag-graph sanity check — verify the new include_role wrappers selected correctly
ansible-playbook main.yml --list-tags
```

### Phase C user smoke test

Once coordinator integration lands on `dev`:

```bash
# Fresh prefix, wipes everything, reinstalls via new role path
ansible-playbook main.yml -K -e blank=true

# Regression harness — second run must converge to zero changed tasks
./tests/test-idempotence.sh
```

`test-idempotence.sh` (added in Wave 1 commit `de7c544`) runs the playbook twice and asserts the second run reports zero changed tasks. Wave 2.2 keeps it green. Any regressions surfaced in smoke are fix commits directly on `dev` — no Wave 2.2 rollback.

---

## 7. Open questions (all resolved)

These decisions are locked — the Wave 2.1 pilot confirmed each one.

### Role location — see Section 1a

Locked in Section 1a "Role location — LOCKED decision". TL;DR: `roles/pazny.*/` in-repo, not `galaxy_roles/`. Wave 3 Galaxy extraction deferred past Wave 2.2 Phase C.

### Vault and secrets

Credentials stay in top-level `default.credentials.yml` plus the user-overridable `credentials.yml`. Role defaults reference centralized variables (`{{ mariadb_root_password }}`, `{{ grafana_admin_password }}`) which resolve through the central files. Per-role `vars/vault.yml` is **deferred indefinitely** — introducing per-role encryption creates a key-distribution problem that does not exist today. Wave 1's state-declarative password reconverge depends on every service resolving its password through the same `global_password_prefix`; per-role vaults would shard that.

### Module dependencies

Each role declares its required collections in `meta/main.yml` under `collections:`. Pilot example from `roles/pazny.mariadb/meta/main.yml`:

```yaml
---
galaxy_info:
  role_name: mariadb
  namespace: pazny
  author: Pázny
  description: MariaDB in Docker compose override (devBoxNOS infra stack)
  license: MIT
  min_ansible_version: "2.14"
  platforms:
    - name: MacOSX
      versions:
        - all

dependencies: []

collections:
  - community.mysql   # used by mysql_info / mysql_db / mysql_user in tasks/post.yml
```

The top-level `requirements.yml` remains the authoritative install list that CI uses. `meta/main.yml` is documentation plus a graceful-failure hint — if a contributor `include_role`s `pazny.mariadb` from a different playbook without `community.mysql` installed, Ansible surfaces the missing collection at run time.

---

## 8. Rollback plan

### Wave 2.1 pilot (DONE)

Each pilot role landed as a single atomic commit touching:

- The new `roles/pazny.<svc>/` directory and all of its files.
- The rewire in `tasks/stacks/core-up.yml` (for `pazny.mariadb` / `pazny.grafana`) or `main.yml` (for `pazny.glasswing`).
- The deletion of the now-orphaned source file (`tasks/iiab/mariadb_setup.yml`, `tasks/iiab/grafana_admin.yml`, `tasks/glasswing.yml`).
- The shrink of the base compose template — migrated service block removed.

`git revert <commit>` on any pilot commit restores the pre-role state cleanly. This shape worked because the pilot was sequential: one role per commit, each standalone.

### Wave 2.2 parallel batch

The parallel-worker model changes the rollback contract. Worker commits are **dormant**: each adds `roles/pazny.<svc>/` and shrinks the base compose, but does **not** rewire orchestration. The legacy `include_tasks` path in `main.yml` and `tasks/stacks/core-up.yml` / `stack-up.yml` continues to run.

Two rollback boundaries:

1. **Per Phase A worker commit** — `git revert <commit>` removes the role directory and restores the base compose block. Legacy path keeps running as if nothing happened. Safe and isolated; no coordination with other worker commits needed.

2. **Phase B coordinator integration commit** — this is the single atomic ~50+ file commit that wires every new role into `core-up.yml` / `stack-up.yml`, rewires `main.yml`, deletes dead task files, and prunes redundant handlers. `git revert` on this commit puts every role back to dormant simultaneously — the legacy task files come back in one shot, orchestration returns to pre-Wave-2.2 state, and all role directories stay in place (now dormant again).

**Rule:** do not attempt partial reverts of the Phase B commit. It is intentionally one big mechanical change so that rollback is one command.

Regressions found during Phase C smoke are fixed with follow-up commits on `dev`, not by reverting Wave 2.2. The user has explicitly opted out of rollback ("cesty zpět není") — fix forward.

---

## 9. Gotchas (post-pilot, still binding)

The Wave 2.1 pilot confirmed or corrected each of these. Read before starting any Wave 2.2 worker.

### `roles:` vs `tasks:` execution order — CONFIRMED

Ansible runs the play's `roles:` section *before* its `tasks:` section. If `pazny.glasswing` were wired as a top-level role (`- role: pazny.glasswing` in the play's `roles:` list), it would run before `tasks/php.yml` installed the PHP runtime and `composer install` would fail with "command not found".

**Mitigation:** keep all pilot and Wave 2.2 roles inside the existing `tasks:` block via `include_role` / `import_role` or invoke them from `core-up.yml` / `stack-up.yml`. Do **not** add them to the play's top-level `roles:` list until the whole migration is done and the dependency order has been deliberately re-shuffled.

### Handler visibility — CONFIRMED (dual-location pattern)

`notify: Restart php-fpm` from a role task fires the play-level handler in `main.yml:115` only because the play-level handler exists. Handlers inside a role's `handlers/main.yml` are visible only to tasks in that same role unless `listen:` is used.

**Pilot resolution:**
- Shared handlers (`Restart nginx`, `Reload nginx`, `Restart php-fpm`, `Restart alloy`) stay **play-level only** in `main.yml`. Any role can notify them.
- Service-specific handlers (`Restart mariadb`, `Restart grafana`, `Restart authentik`…) live in **both** places: play-level in `main.yml` AND `roles/pazny.<svc>/handlers/main.yml`. The play-level handler wins at runtime; the role-local copy is there so the role is standalone-usable outside devBoxNOS. Duplication is harmless.
- Play-level handler pruning (the eventual removal of duplicates) is deferred until after Wave 2.2 Phase C smoke passes.

### Tag inheritance — CONFIRMED (apply + tags both required)

`--tags mariadb` does not propagate into `include_role` automatically. The pilot uses both:

```yaml
- name: "[Core] MariaDB post-start (pazny.mariadb role → tasks/post.yml)"
  ansible.builtin.include_role:
    name: pazny.mariadb
    tasks_from: post.yml
    apply:
      tags: ['mariadb', 'database']    # propagates tag to child tasks
  when:
    - install_mariadb | default(false)
    - _core_infra_enabled | bool
  tags: ['mariadb', 'database']        # makes the include_role task itself selectable
```

Using only `apply:` or only top-level `tags:` selects the wrong subset. Verify with `ansible-playbook main.yml --list-tags`.

### `stacks_shared_network` reference — CORRECTED (original guidance was wrong)

The original Section 9 claimed role compose fragments had to copy the full `networks:` stanza from the base compose or `docker compose -f base -f override` would complain. **The pilot disproved this.** Both `roles/pazny.mariadb/templates/compose.yml.j2` and `roles/pazny.grafana/templates/compose.yml.j2` reference networks **by name only**, and the merged compose renders cleanly:

```yaml
# CORRECT: role compose fragment
services:
  mariadb:
    # ... image, ports, volumes, env, healthcheck ...
    networks:
      - infra_net
      - {{ stacks_shared_network }}
    # ... mem_limit, cpus ...

# NO top-level networks: key. The base compose
# (templates/stacks/infra/docker-compose.yml.j2) still declares
#   networks:
#     infra_net:
#       driver: bridge
#     {{ stacks_shared_network }}:
#       external: true
# Compose merge semantics let the override reference by name.
```

**Rule:** role compose templates declare only `services.<svc>.networks: [...]`. Do **not** add a top-level `networks:` block to any role compose fragment. The base compose owns the declarations.

### Password variable templating — CONFIRMED

Wave 1's state-declarative password reconverge depends on every `*_password` variable resolving via the same `global_password_prefix`. Role `defaults/main.yml` must **not** redeclare credentials — they stay in `default.credentials.yml` where `global_password_prefix` reconverge works centrally.

**Rule:** role defaults contain only neutral config (version, port, data_dir, mem/cpu, empty seed lists). Every `*_password` stays in the top-level credentials file. If a role is consumed standalone outside devBoxNOS, the consumer passes credentials via `vars:` on the `include_role` call — not via role defaults.

### Compose `services:` map merging — CONFIRMED (delete the stub, don't leave it)

When `docker compose -f base.yml -f override.yml` merges two files, the `services:` keys are deep-merged: scalar fields (image, restart, mem_limit) are overridden by later files, lists (volumes, networks, depends_on) are concatenated, maps (environment) are merged per-key.

**Rule:** after moving a service into a role, the worker **deletes** that service's block from the base compose template. Do not leave a stub as a "safety net" — merge of stub + override produces a phantom config that matches neither file alone and is undebuggable. Replace the deleted block with a Jinja comment pointing to the role:

```jinja
  # --- mariadb service block now owned by roles/pazny.mariadb ---
  # Fragment renders to {{ stacks_dir }}/infra/overrides/mariadb.yml
  # Included via ansible.builtin.find in tasks/stacks/core-up.yml
```

### Override file ordering — NEW (from pilot)

`docker compose -f base -f override1 -f override2` deep-merges in argument order: later files override scalars and append to lists from earlier files. The pilot uses `sort(attribute='path')` over the `find` results to get deterministic alphabetic ordering, so two roles rendering to the same service name (which should never happen) would fail predictably rather than flip on every run.

**Rule:** worker-chosen override filenames are `<service-name>.yml`. Never `00-<svc>.yml` or `z-<svc>.yml` or any other ordering trick — each service owns exactly one override file and merge order does not matter within a single service.

### Blueprint + bind-mount path preservation — NEW (Authentik-specific)

When `pazny.authentik` lands, the compose fragment includes a bind mount `{{ stacks_dir }}/infra/authentik/blueprints:/blueprints/custom:ro`. The blueprint render task (`roles/pazny.authentik/tasks/blueprints.yml`, moved from `tasks/stacks/authentik_blueprints.yml`) writes into that exact host path. If the role changes the path to something role-internal (`{{ role_path }}/files/blueprints` or similar), the bind mount in the compose fragment no longer sees the rendered blueprints and Authentik starts without them.

**Rule:** the Authentik worker preserves the blueprint path as a literal across both the blueprint render task and the compose fragment bind mount. `{{ stacks_dir }}/infra/authentik/blueprints` is the contract; do not parameterize it through role vars without updating both sides atomically.

---

When Wave 2.2 is green, this doc will get a Wave 2.3 / Wave 3 section listing the Galaxy extraction checklist and the per-role CI pipeline spec.
