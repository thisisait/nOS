# Local CI — Gitea mirror + Woodpecker pipeline (A16, 2026-05-17)

> **Status (2026-05-20):** end-to-end live on pazny.eu. First pipeline run
> ignited by the A16 cosmetic commit — GitHub push → Gitea mirror →
> Woodpecker pipeline → 5 test stages, all green.
>
> **A17 (2026-05-20):** mirror auto-trigger. Default poll interval cut to
> **1 minute** (was 10 min), and `tools/nos-push` triggers Gitea mirror-sync
> via API immediately after every successful `git push` — pipeline now
> fires within ~2 seconds of the push completing.

## Pushing — use `tools/nos-push`, not raw `git push`

```bash
tools/nos-push                       # push current branch to origin + sync
tools/nos-push origin dev            # push dev explicitly
tools/nos-push --force-with-lease    # safe force push
tools/nos-push --skip-sync           # opt out of mirror trigger (raw push)
```

The wrapper still uses your normal `git config` (remote name, credentials,
hooks). It just adds the `POST /api/v1/repos/<owner>/<repo>/mirror-sync`
call after a successful push. Failures in the sync call are non-fatal —
the underlying push always succeeds first, and the 1-min Gitea poll
covers raw `git push` as a safety net.

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

## Auto-deploy on `dev` (A17, 2026-05-20)

When CI goes green on a `dev` push AND the commit message carries a
`deploy-tags:` footer, the pipeline's last step posts to Wing's
`/api/v1/deploy-trigger` (HMAC-signed). Wing validates, spawns
`ansible-playbook main.yml --tags <tags>` as a detached subprocess, and
returns 202. Completion notification lands in Wing `/inbox`.

### How to ship a change with auto-deploy

```bash
git commit -m "feat(wing): add tenant filter

deploy-tags: wing"
tools/nos-push origin dev
```

The footer `deploy-tags: wing` triggers auto-deploy of the `wing` tag
after CI passes. Multiple comma-separated tags allowed:
`deploy-tags: wing,bone,gitea`. **No footer = no auto-deploy** — safe
default for docs / test commits.

### Security model (defense in depth)

1. **HMAC** (`NOS_DEPLOY_HMAC_SECRET`) — pipeline signs; Wing verifies
2. **±5-min timestamp window** — captured signatures can't be replayed
3. **Branch allowlist** — only `dev` and `pzny` auto-deploy. `master`
   is operator-manual (linear history is the audit boundary)
4. **Tag allowlist** — only roles that do NOT need sudo are accepted.
   Tags like `homebrew`, `dotfiles`, `mac.*`, `autostart`, `ssh`,
   `secrets` are explicitly REJECTED. Allowlist source-of-truth:
   `DeployTriggerPresenter::ALLOWED_TAGS`
5. **Concurrency lock** — `tools/deploy-from-ci.sh` uses an mkdir-based
   lock; second trigger while deploying → "skipped, lock held"
6. **UUID-tracked logs** — `~/.nos/deploys/<uuid>.log` per deploy;
   notification in `/inbox` links to it

### Operator secret provisioning

Two secrets must exist in Woodpecker UI:

| Secret name              | Value                                                |
|--------------------------|------------------------------------------------------|
| `wing_deploy_url`        | `https://wing.<tld>/api/v1/deploy-trigger`           |
| `nos_deploy_hmac_secret` | Same value as `NOS_DEPLOY_HMAC_SECRET` env on Wing   |

Wing's env is set by `pazny.wing/templates/wing.plist.j2` from the
`nos_deploy_hmac_secret` var (default:
`{{ global_password_prefix }}_pw_deploy_hmac`). Copy that resolved value
into the Woodpecker secret. **Restrict the secret to events: push** so
pull-request pipelines from forks can't read it.

### Manual smoke (without going through CI)

```bash
TS=$(date +%s)
UUID=$(uuidgen | tr 'A-Z' 'a-z')
SECRET="$(grep nos_deploy_hmac_secret ~/.nos/secrets.yml | cut -d'"' -f2)"
BODY=$(printf '{"branch":"dev","commit":"%s","deploy_uuid":"%s","source":"manual","tags":["wing"],"ts":%s}' \
  "$(git rev-parse HEAD)" "$UUID" "$TS")
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $NF}')
curl -X POST -H "Content-Type: application/json" \
  -H "X-Wing-Timestamp: $TS" \
  -H "X-Wing-Signature: $SIG" \
  --data "$BODY" \
  https://wing.<tld>/api/v1/deploy-trigger
# Expect 202 + {deploy_uuid, log_path}
# Tail: ~/.nos/deploys/<uuid>.log
```

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
