# Woodpecker CI — Skills

> Callable actions against the Woodpecker API. All require a Bearer PAT that is
> OAuth-derived (created in the UI after first Gitea login) — it does not exist on a
> fresh blank. Endpoints are verified against `roles/pazny.woodpecker/tasks/post-repo.yml`.

## Authentication

- **Method:** Bearer PAT
- **Token:** `woodpecker_api_token` (Woodpecker UI → User Settings → Personal Access Tokens; persisted in credentials once known)
- **Base URL (loopback):** `http://127.0.0.1:8060/api`
- **Header:** `Authorization: Bearer <token>`

---

## refresh-forge-cache

**Trigger:** "woodpecker can't find my repo", "sync gitea repos into woodpecker", "flush woodpecker forge cache"
**Method:** API
**Endpoint:** `POST /api/user/repos?all=true&flush=true`
**Input:** None (auth header only)
**Output:** `200`/`204` — Woodpecker re-queries Gitea and rebuilds the available-repos cache. A `401` means the PAT is not yet valid (no first login on a fresh DB).

---

## check-repo-active

**Trigger:** "is this repo activated in woodpecker", "check woodpecker repo status"
**Method:** API
**Endpoint:** `GET /api/repos/<owner>/<name>`
**Input:** repo owner + name
**Output:** Repo JSON if active, `404` if not yet activated

---

## activate-repo

**Trigger:** "activate this repo in woodpecker", "enable CI for the nos repo", "turn on woodpecker pipelines"
**Method:** API
**Endpoint:** `POST /api/repos?forge_remote_id=<id>`
**Input:** `<id>` = the Gitea `forge_remote_id` (from `GET <gitea>/api/v1/repos/<owner>/<name>` → `.id`)
**Output:** `200`/`201` on activation, `409` if already active. Enables Gitea webhook delivery so pushes fire the `.woodpecker.yml` pipeline.

---

## get-user

**Trigger:** "validate woodpecker token", "who am I on woodpecker"
**Method:** API
**Endpoint:** `GET /api/user`
**Input:** None
**Output:** The authenticated user JSON (a `200` confirms the PAT is valid)

---

## read-metrics

**Trigger:** "woodpecker pipeline metrics", "check CI pipeline stats"
**Method:** API
**Endpoint:** `GET /metrics`
**Input:** None
**Output:** Prometheus text exposition of `woodpecker_pipeline_*` series. Requires `Authorization: Bearer <woodpecker_prom_token>` (a SEPARATE token from the user PAT — this is the Alloy scrape credential).
