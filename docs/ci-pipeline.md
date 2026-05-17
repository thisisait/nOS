# Local CI — Gitea mirror + Woodpecker pipeline (A16, 2026-05-17)

Self-hosted CI that mirrors GitHub → local Gitea on a 10-minute pull
interval, then fires the `.woodpecker.yml` pipeline on every push. Four
required test stages, one optional notification stage. No host-side
deploy in this iteration — deploy stays operator-triggered.

## Flow

```
git push origin <branch>                  (developer machine)
        │
        ▼
GitHub:thisisait/nOS  ──┐
                        │  pull-mirror (10 min poll)
                        ▼
Local Gitea (devops stack)  ──── webhook ───► Woodpecker
                                                │
                                                ▼
                                        composer validate
                                        php -l
                                        pytest anatomy gates
                                        ansible-playbook --syntax-check
                                                │
                                                ▼ (on dev/pzny only)
                                        POST /api/v1/notifications
                                        → Wing /inbox
```

## Activation

The autowiring is **off by default**. To turn it on:

1. **Bring up the devops stack** with Gitea + Woodpecker:

   ```yaml
   # config.yml
   install_gitea: true
   install_woodpecker: true
   ```

2. **Run the playbook once** to provision both services. Log in to
   Gitea and Woodpecker UIs at the URLs printed by the post-run
   service-registry (`git.<tld>`, `ci.<tld>`).

3. **Provision the two API tokens** (one-time):

   - **Gitea:** Profile → Settings → Applications → "Generate New Token"
     - Name: `nos-autowire`
     - Scopes: `write:repository`, `write:admin`
     - Copy the resulting token.

   - **Woodpecker:** User → Settings → "Personal Access Tokens" →
     Generate New Token. Copy it.

   Then add both to `credentials.yml`:

   ```yaml
   gitea_api_token: "<paste>"
   woodpecker_api_token: "<paste>"
   ```

4. **Flip the autowire toggles**:

   ```yaml
   # config.yml
   install_gitea_autowire_nos: true
   install_woodpecker_autowire_nos: true
   ```

5. **Re-run the playbook**:

   ```bash
   ansible-playbook main.yml --tags gitea,woodpecker
   ```

   The Gitea task creates `nOS` as a pull-mirror from
   `https://github.com/thisisait/nOS.git`; the Woodpecker task activates
   the same repo so its webhook fires the pipeline.

6. **Verify**: push any commit to `dev` on GitHub, wait ≤10 minutes for
   the Gitea mirror to pick it up, then check `https://ci.<tld>` — the
   pipeline run should appear under `<gitea-admin>/nOS`.

## Pipeline contract (`.woodpecker.yml`)

| Step             | Image                | What it does                                       |
|------------------|----------------------|----------------------------------------------------|
| composer-validate| `composer:2`         | `composer validate --strict` on Wing               |
| php-lint         | `php:8.5-cli-alpine` | `php -l` on every `.php` in Wing                   |
| pytest-anatomy   | `python:3.11-slim`   | `pytest tests/anatomy/` — all anatomy gates        |
| ansible-syntax   | `python:3.11-slim`   | `ansible-playbook main.yml --syntax-check`         |
| notify-green     | `curlimages/curl`    | POST to Wing /api/v1/notifications (dev/pzny only) |

Anatomy gate `test_ci_pipeline.py::test_woodpecker_pipeline_carries_required_test_steps`
pins the four required test steps; dropping one will fail CI on the
anatomy step itself before the missing step is ever reached.

## Secrets (Woodpecker UI)

Two optional secrets enable the notify-green step:

| Secret name       | Value                                            |
|-------------------|--------------------------------------------------|
| `wing_api_url`    | `https://wing.<tld>` (no trailing slash)         |
| `wing_api_token`  | A Wing bearer token scoped `nos:notifications`   |

If either is absent, the notify step prints a one-line skip message and
exits 0 — pipeline stays green. Configure via Woodpecker UI: Repo
Settings → Secrets → New Secret, restrict to events `push`.

## Deploy is operator-triggered (by design, for now)

The pipeline does **not** SSH into the host or rsync into `~/wing/app/`,
`~/bone/`, etc. Two reasons:

1. **Security** — granting the agent container write access to host
   playbook artefacts is a real blast-radius increase. The current
   manual step (`ansible-playbook main.yml --tags <stack>` after CI
   goes green) keeps the deploy decision human-gated.

2. **Idempotence** — the playbook IS the deploy mechanism. A separate
   "deploy" step in CI would duplicate logic that already lives in the
   role tasks (composer install, init-db, launchd bootout/bootstrap).
   When we eventually automate, we'll call the playbook itself from CI,
   not reimplement its steps.

When this changes (post-A16), it'll be a separate `deploy:` stage
gated on `branch == dev` or `branch == pzny` with a host-side trigger
endpoint (Wing `/api/v1/deploy-trigger` HMAC) firing
`ansible-playbook main.yml --tags <stack>` as a subprocess.

## Branch policy

- `master` — pipeline runs as test-only validation. No deploy. New
  commits land via PR from `dev`.
- `dev` — pipeline runs all five stages including notify. This is the
  integration branch + the canonical "looks green for next release" pointer.
- `pzny` — operator-local cross-feature workspace. Pushed only to local
  Gitea (the GitHub pre-push hook in `tools/git-hooks/pre-push` blocks
  pushing pzny to `origin`). Pipeline + notify behave identically to dev.
- `feat/*`, `fix/*` — test stages run; notify step skipped (only fires
  on dev/pzny).

## Pinned contracts (anatomy gates)

Run: `python3 -m pytest tests/anatomy/test_ci_pipeline.py -v`.

Pins (alphabetical):

- Credentials stubs present (`gitea_api_token`, `woodpecker_api_token`)
- Gitea `post-repo.yml` task — fails-closed on missing token, uses
  `/api/v1/repos/migrate` with `mirror: true`
- Pipeline YAML is valid + carries 4 required test steps
- pytest step targets `tests/anatomy/`
- Role defaults declare all autowire vars
- stack-up.yml wires `pazny.woodpecker post`
- Woodpecker `post-repo.yml` task — idempotent (checks before activate),
  uses `forge_remote_id` (v3 convention)

## Deferred (next batch)

- **Auto-deploy on dev/pzny push** — Wing `/api/v1/deploy-trigger` HMAC
  endpoint + `ansible-playbook` subprocess + notification on completion
- **Gitea OAuth2 app auto-provisioning** — today operator creates the
  Woodpecker↔Gitea OAuth2 app manually (`woodpecker_gitea_client` +
  `woodpecker_gitea_secret` in credentials.yml); a future Gitea CLI call
  could mint them via `gitea admin oauth2 create`
- **API token auto-generation** — `gitea admin user generate-access-token`
  + Woodpecker CLI token mint, replacing the operator UI step
- **Push-mirror back to GitHub from Gitea** — for `pzny` collaboration
  later, currently pzny is local-only
