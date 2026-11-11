# profiles/

A profile is a YAML file of variables layered on top of `default.config.yml` for one run:

```bash
nos -e @profiles/core.yml                                  # one profile
nos -e @profiles/praxis.yml -e @profiles/flash.yml         # several: the later file wins
```

The same files feed the profile builder (`tools/profile-builder-build.py`), the static page that writes a
`config.yml` before the first run.

## The header

Every profile the builder offers starts with two comment lines, read by `profiles()` in the builder:

```yaml
# axis: service-set
# plain: The smallest working nOS — desktop, assistant, memory and dashboard behind SSO.
```

- `axis:` is one of the five below. A file with no `axis:` line is not offered by the page.
- `plain:` is the one sentence the page shows next to the choice. Write it for a person, not an engineer.
- `composes-with:` (optional) names the profiles it is meant to sit beside.

## The five axes

The page asks one question per axis and offers each axis's profiles as the answers (`AXES` in the builder):

| axis | the question | today |
|---|---|---|
| `service-set` | Which set of services do you want to start from? | `core`, `dev-minimal`, `all-on` |
| `use-case` | What will this machine be used for? | `praxis`, `workstation`, `test-users` |
| `policy` | Do you need stricter security rules? | `gov-local` |
| `environment` | Where will nOS run? | `cloud-e2e` |
| `constraint` | Is there anything this hardware cannot do well? | `flash` |

A constraint profile only **subtracts**: it turns services off, never on (`flash.yml` says why). Apply it last.

A profile whose every key is a question one of the page's steps already asks (`test-users`: the People
step's switch) is answered in that step and not offered as an axis choice.

## What a profile holds

- `install_*: true|false` — services on or off (the builder calls these flags).
- any other variable — a knob (a port, a path, a policy switch).
- `nos_synthetic_identities` is read by `main.yml` only; the page never writes it.

## How the layers merge

1. `config.d/*.yml`, then `default.config.yml` — every variable's default.
2. `config.yml` — your choices (gitignored). The builder writes this file.
3. `-e @profiles/<name>.yml` on the command line — extra vars outrank everything, later files outrank earlier ones.

In the builder: for each axis you picked, the profile's knobs are written into `config.yml` under a
`# profiles: <a> + <b>` line; an answer you gave on a step outranks a profile's knob and is written once;
a value equal to its default is left out. Flags go through `settle()`, which also switches on what an
enabled service needs (and tells you), and the page flags a combination the playbook would refuse.

## Adding a profile

1. `profiles/<name>.yml` with the `axis:` and `plain:` header and the variables.
2. Rebuild the page: `tools/profile-builder-build.py --out ~/nos-profile-builder`.
3. `tools/profile-builder-build.py --sweep` runs every combination through the page and exits 1 on a contradiction.
