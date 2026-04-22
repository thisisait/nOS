# pazny.state_manager

Thin Ansible role that wraps the `nos_state` custom module:

1. ensures `~/.nos/` exists with mode `0700`
2. introspects every service declared in `state/manifest.yml`
3. persists the observed state to `~/.nos/state.yml` (atomic write, merge semantics)
4. prints a compact summary and optionally pushes the state to BoxAPI

This role is a **reader**. It never changes service configuration. It is safe to
run on every playbook invocation; a no-op run simply updates the `generated_at`
timestamp.

## Role variables

| variable                       | default                                                         | purpose                                                              |
|--------------------------------|-----------------------------------------------------------------|----------------------------------------------------------------------|
| `nos_state_dir`                | `{{ ansible_env.HOME }}/.nos`                                   | Directory for state file. Created with `0700`.                       |
| `nos_state_file`               | `{{ nos_state_dir }}/state.yml`                                 | Path to the single-file state document.                              |
| `nos_state_manifest`           | `{{ playbook_dir }}/state/manifest.yml`                         | Source of truth for expected services.                               |
| `nos_state_migrations_dir`     | `{{ playbook_dir }}/migrations`                                 | Read by agent 2; role exposes the default.                           |
| `nos_state_report_stdout`      | `true`                                                          | Print the per-service summary at the end.                            |
| `nos_state_push_boxapi`        | `{{ install_boxapi | default(false) }}`                         | Best-effort POST to `/api/state`.                                    |
| `nos_state_boxapi_url`         | `http://localhost:{{ boxapi_port | default(8099) }}/api/state`  | Override if BoxAPI runs elsewhere.                                    |
| `nos_state_schema_version`     | `1`                                                             | Written into the state document.                                     |
| `nos_state_generator`          | `pazny.state_manager v1.0`                                      | Generator tag in state metadata.                                     |

## Where it fits in the playbook

This role is not wired up by agent 1 (per brief). Integration is a human-operator
step after all agents finish. Expected wiring:

```yaml
# main.yml
pre_tasks:
  - ansible.builtin.import_tasks: tasks/pre-migrate.yml   # agent 1

roles:
  # ... host roles ...

post_tasks:
  - ansible.builtin.import_tasks: tasks/state-report.yml  # agent 1
```

`tasks/state-report.yml` invokes this role.

## Tags

Every task is tagged `always` + `state`, plus one of `introspect`, `persist`,
`report`. Filter with `--tags state` to run the role in isolation.

## Testing

```bash
pytest tests/state_manager/
```

Covers: state roundtrip (read/write/deep-merge), dotted-path get/set/unset,
manifest schema validity, introspect dispatcher, retroactive migration
idempotency (detect predicates false on current host).
