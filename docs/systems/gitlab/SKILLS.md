# GitLab — Skills

> Callable actions against the GitLab REST API v4. All require the agent-forge PAT,
> which exists **only when `gitlab_agent_forge: true`**. Endpoints are verified against
> `roles/pazny.gitlab/tasks/post-forge.yml` and `tools/recipe-pr.sh`.

## Authentication

- **Method:** PAT (`PRIVATE-TOKEN` header)
- **Token:** `gitlab_api_token` in `{{ HOME }}/.nos/secrets.yml`
- **Base URL (loopback):** `http://127.0.0.1:8929/api/v4`
- **Header:** `PRIVATE-TOKEN: <token>`

---

## get-user

**Trigger:** "who am I on gitlab", "validate gitlab token", "check gitlab api access"
**Method:** API
**Endpoint:** `GET /api/v4/user`
**Input:** None
**Output:** `{ "id": 1, "username": "...", ... }` (a `200` confirms the PAT is valid; `401`/`403` means mint a new one)

---

## get-project

**Trigger:** "does the nos project exist", "get gitlab project", "find forge project"
**Method:** API
**Endpoint:** `GET /api/v4/projects/<owner>%2F<name>`
**Input:** URL-encoded `<owner>/<name>` (e.g. `root%2FnOS`)
**Output:** Project JSON, or `404` if absent

---

## create-project

**Trigger:** "create the nos forge project", "make an empty gitlab project"
**Method:** API
**Endpoint:** `POST /api/v4/projects`
**Input:**
```json
{
  "name": "nOS",
  "path": "nOS",
  "visibility": "private",
  "initialize_with_readme": false
}
```
**Output:** `201` with the created project JSON. Created empty — trunk is pushed from the host via `tools/sync-trunk-to-gitlab.sh`.

---

## resolve-user

**Trigger:** "find gitlab user by name", "resolve sso username to gitlab id"
**Method:** API
**Endpoint:** `GET /api/v4/users?username=<username>`
**Input:** SSO username
**Output:** `[{ "id": ..., "username": "..." }]` (empty array = the omniauth user has not logged in yet)

---

## grant-maintainer

**Trigger:** "add member to gitlab project", "grant maintainer on nos forge"
**Method:** API
**Endpoint:** `POST /api/v4/projects/<owner>%2F<name>/members`
**Input:**
```json
{ "user_id": 42, "access_level": 40 }
```
**Output:** `201` on add, `409` if already a member (`access_level` 40 = MAINTAINER)

---

## open-merge-request

**Trigger:** "open an MR for an upgrade recipe", "propose a recipe to the forge", "review this upgrade"
**Method:** CLI (host)
**Command:**
```bash
tools/recipe-pr.sh <service> --open-pr --forge gitlab --base dev
```
**Input:** A drafted `upgrades/<service>.yml` recipe
**Output:** Validates the recipe through the authoritative gates, then branches + commits + pushes to the GitLab forge and opens a merge request. Never merges, never force-pushes. Dry-run (validate only) is the default without `--open-pr`.

---

## sync-trunk

**Trigger:** "refresh gitlab trunk from github", "sync dev and master to the forge"
**Method:** CLI (operator host only)
**Command:**
```bash
tools/sync-trunk-to-gitlab.sh          # dev + master
tools/sync-trunk-to-gitlab.sh dev      # just dev
```
**Output:** Fast-forward-only push of trunk from GitHub `origin` to the GitLab forge. Refuses to run if `origin` is not a github.com remote; never force-pushes.
