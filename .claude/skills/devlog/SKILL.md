---
name: devlog
description: Read, author, and publish nOS devlog entries across the repo-committed nos-core namespace and the on-site WordPress namespaces (site, tenant/*, machine/*, user/*). Use for narrative history, session write-ups, and the pre-release review ceremony. Doctrine in docs/devlog/README.md.
---

# /devlog — nOS devlog operations

Modes: `read` | `new` | `post` | `release`. Infer the mode from the request;
default to `read` when only a question is asked.

## Shared rules (all modes)

- Doctrine source: `docs/devlog/README.md`. nos-core = repo SoT (files,
  committed, playbook-synced to WP); on-site namespaces = WP DB SoT (REST).
- **Every WordPress write goes through `tools/devlog-post.py`** —
  never raw curl, never the admin account. The helper emits the Bone audit event
  (actor_id=agent:devlog); skipping it breaks the audit doctrine.
- Entry ids are `<YYYY-MM-DD>-<slug>`, equal to the filename stem, immutable.
  Never rename an entry file — a rename is delete+create on the WP side.
- Body tone: surgeon-style narrative — what was touched, what symptom drove
  it, what structurally changed, what pins it. One entry per topic per day.
- Never print secret values (`~/.nos/secrets.yml` is the credential source).

## read

- nos-core: read `docs/devlog/nos-core/<YYYY>/*.md` directly (or
  `state/devlog-bundle.jsonl` for the machine view). Prefer files over WP.
- On-site namespaces: `GET http://127.0.0.1:<wordpress_port>/wp-json/wp/v2/posts`
  filtered by the namespace category (categories live under parent `devlog`;
  `/` flattens to `-`). Auth: Basic with `wordpress_devlog_bot_user` +
  `wordpress_devlog_app_password` from `~/.nos/secrets.yml`. Read-only GETs
  need no Bone event.

## new (nos-core authoring)

1. Scaffold `docs/devlog/nos-core/<YYYY>/<YYYY-MM-DD>-<slug>.md` with the
   frontmatter schema from `docs/devlog/README.md` (required: id, title,
   date, namespace: nos-core, summary; optional: tags, release, status,
   actors, related).
2. Write the body from the session's actual work (git log, RELEASE.md,
   conversation context).
3. Run `tools/devlog-compile.py` and remind the operator to commit BOTH the
   entry and `state/devlog-bundle.jsonl` (the freshness gate
   `tests/anatomy/test_devlog_bundle.py` fails otherwise).
4. WordPress picks it up on the next playbook run (`--tags devlog` for just
   the sync).

## post (on-site namespaces)

Call `tools/devlog-post.py --namespace <ns> --title "..." --body-file <md>
[--tags a,b] [--status publish|draft] [--summary "..."]`. Valid namespaces:
`site`, `tenant/<x>`, `machine/<x>`, `user/<x>`. The helper refuses
`nos-core` (exit 2) by design — author a file instead (see `new`).

## release (pre-release 2nd-level review ceremony)

The narrative half of the release gate (mechanics live in
`tools/devlog-release.sh`):

1. Read `git log <last-tag>..dev --oneline`, the session's devlog entries,
   `docs/active-work.md`, and `RELEASE.md`.
2. **Consolidate docs:** any plan/handoff completed since the last release
   moves to `docs/archive/` (grep for inbound references first and repoint
   them — the rule in `docs/archive/README.md`); extract still-open leftovers
   into `docs/active-work.md` (keep it ≤150 lines).
3. Draft or refresh the `release-vX.Y` nos-core entry — this IS the release
   blog post (frontmatter `release: vX.Y-beta`).
4. Update `RELEASE.md` with the matching `## vX.Y` section.
5. Recompile: `tools/devlog-compile.py`.
6. Hand off to the operator: run `tools/devlog-release.sh vX.Y-beta` (
   pre-flight checks), then the standard flow — `tools/ci-local.sh` →
   dev→master PR → admin rebase merge → tag push (which auto-publishes the
   GH Pages devlog) → `gh release create`.
