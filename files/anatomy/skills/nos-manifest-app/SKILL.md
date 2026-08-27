---
name: nos-manifest-app
description: Author a Tier-2 nOS app as apps/<name>.yml — the manifest the apps_runner deploys. Covers the GDPR Article 30 block the parser refuses to deploy without, magic tokens, and the smoke-parse that must pass before a converge.
version: 1.0.0
license: MIT
platforms: [macos, linux]
metadata:
  nos:
    # Operator-only. Authoring an app decides what personal data a service may
    # hold and on what legal basis — a question whose caller should be a person.
    # `main` gets it regardless; no autonomous runner needs it.
    audience: []
prerequisites:
  commands: [python3, git]
---

# Authoring an nOS manifest app

A manifest app is a self-hosted service that gets a `apps/<name>.yml` file and
no code. `pazny.apps_runner` discovers it, validates it, resolves its tokens,
renders one merged compose override, brings the `apps` stack up and fires the
post-hooks — routing, SSO, secrets, observability, service registry, GDPR
register. **You describe the service; the runner derives the wiring.**

## When to use

- A long-tail service that does not merit a full `roles/pazny.<name>/` role.
- Importing a Coolify template (`tools/import-coolify-template.py` rewrites
  their `${SERVICE_*}` tokens into ours and scaffolds the `gdpr:` block with
  `TODO` sentinels you must replace).

## When NOT to use

- Anything in `infra` or `observability`. Those are always-first, always-required
  and belong to roles.
- A service needing post-start API calls, DB migrations or admin bootstrapping —
  that is `roles/pazny.<name>/tasks/post.yml`, not a manifest.
- Editing a service that already has a role. Two definitions of one service is
  the defect this estate keeps paying for; find the role instead.

## The one rule that is not advice

**The parser refuses a manifest without a complete `gdpr:` block.** Not a
warning, not a lint — the deploy does not happen. Purpose, `legal_basis` (an
enum), data categories, data subjects, a retention horizon, processors, and the
EU-residency flag. Article 30 compliance is part of the deploy gate by design.

Do not attempt to satisfy it with plausible-sounding text. `legal_basis` is an
enum and will reject an invented member; a retention horizon of "as long as
necessary" is not a horizon. If you do not know a service's lawful basis, that
is a question for the operator, not a field to fill.

## The loop

```bash
cp apps/_template.yml apps/myapp.yml
$EDITOR apps/myapp.yml

# Smoke-parse BEFORE you converge. This is the same parser the runner uses,
# so a pass here is the real answer, not a rehearsal of one.
PYTHONPATH=files/anatomy python3 -m module_utils.nos_app_parser apps/myapp.yml
```

Only when that exits clean:

```bash
ansible-playbook main.yml --tags apps
```

Never hand-edit anything under `~/stacks/apps/` to make a service work. That
directory is rendered output; the next converge overwrites it and the fix
vanishes with no trace of why it was ever there.

## What you get without asking

Declare the service; do **not** hand-write these, because the runner already
derives them and a second declaration is how they drift:

- **Traefik routing** — labels are generated from the manifest.
- **SSO** — an `authentik:` block becomes a provider + application. Pick the
  mode honestly: `native_oidc` only if the service really consumes OIDC itself,
  `forward_auth` if you are only gating access. Claiming `native_oidc` for a
  service whose OIDC does not exist is a live example in this tree (FreeScout).
- **Secrets** — magic tokens resolve at render; never paste a literal.
- **Observability, Kuma monitor, service registry, Bone audit event.**

## Before you say it is done

```bash
python3 -m pytest tests/anatomy -q        # the shape
tools/red-status.py                        # what is red right now
```

A container that started is not a service that works. `docs/hidden_fees/08` is
this estate's own record of a health probe reporting `0/0 ready` for a stack
that had failed to come up — absence read as success, green for weeks.

## Where the authority actually lives

- `apps/_template.yml` — the shape, with every field commented.
- `files/anatomy/module_utils/nos_app_parser` — **the enforcement.** When this
  document and that parser disagree, the parser is right and this file is a bug.
- `docs/tier2-app-onboarding.md` — the long-form operator guide.
- `docs/coolify-import.md` — the import path.
