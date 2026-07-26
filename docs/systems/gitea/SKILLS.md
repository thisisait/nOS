# Gitea — Skills

> Callable actions for Gitea. Each skill is API-first using the `nos-agent-forge` token (admin-owned, scope `write:repository`).

## Authentication

- **Method:** Bearer token (Personal Access Token)
- **Token:** `~/.nos/secrets.yml::gitea_api_token` — minted by `post-forge.yml` when `gitea_agent_forge: true`
- **Base URL:** `https://git.dev.local`
- **Header:** `Authorization: token <token>`

---

## list-repos

**Trigger:** "list repositories", "show my repos", "what repos exist"
**Method:** API
**Endpoint:** `GET /api/v1/repos/search`
**Input:** Query params: `q` (search), `limit`, `page`
**Output:** `{ "data": [{ "id": 1, "name": "...", "full_name": "...", "clone_url": "..." }] }`

---

## create-repo

**Trigger:** "create repository", "new repo for [name]"
**Method:** API
**Endpoint:** `POST /api/v1/user/repos`
**Input:**
```json
{
  "name": "repo-name",
  "description": "...",
  "private": false,
  "auto_init": true,
  "default_branch": "main"
}
```
**Output:** Repository object with clone URL

---

## list-issues

**Trigger:** "show issues", "list open issues in [repo]"
**Method:** API
**Endpoint:** `GET /api/v1/repos/{owner}/{repo}/issues`
**Input:** Query params: `state` (open/closed), `labels`, `milestone`
**Output:** `[{ "id": 1, "number": 1, "title": "...", "state": "open", "body": "..." }]`

---

## create-issue

**Trigger:** "create issue", "file bug", "open ticket for [description]"
**Method:** API
**Endpoint:** `POST /api/v1/repos/{owner}/{repo}/issues`
**Input:** `{ "title": "...", "body": "...", "labels": [1, 2] }`
**Output:** Created issue object

---

## create-pull-request

**Trigger:** "create PR", "open pull request", "merge [branch] into [base]"
**Method:** API
**Endpoint:** `POST /api/v1/repos/{owner}/{repo}/pulls`
**Input:** `{ "title": "...", "body": "...", "head": "feature-branch", "base": "main" }`
**Output:** Created PR object

---

## manage-webhooks

**Trigger:** "add webhook", "list webhooks", "notify on push"
**Method:** API
**Endpoint:** `GET/POST /api/v1/repos/{owner}/{repo}/hooks`
**Input:** `{ "type": "gitea", "config": { "url": "https://...", "content_type": "json" }, "events": ["push", "pull_request"] }`
**Output:** Webhook object with ID

---

## get-commit-log

**Trigger:** "show recent commits", "what changed in [repo]"
**Method:** API
**Endpoint:** `GET /api/v1/repos/{owner}/{repo}/git/commits?sha={branch}&limit=10`
**Input:** Branch name, limit
**Output:** `[{ "sha": "...", "message": "...", "author": {...}, "created": "..." }]`

---

## create-api-token

**Trigger:** (internal — used by `post-forge.yml` to mint the agent-forge token)
**Method:** API
**Endpoint:** `POST /api/v1/users/{username}/tokens`
**Input:** `{ "name": "nos-agent-forge", "scopes": ["write:repository"] }` (`gitea_agent_forge_token_name` / `gitea_agent_forge_token_scopes`)
**Output:** `{ "id": 1, "name": "nos-agent-forge", "sha1": "<token>" }` — the value is shown once, so the role persists it to `~/.nos/secrets.yml`
**Auth:** Basic auth (admin credentials) over `127.0.0.1` for initial token creation
