# Gitea — Skills

> Callable actions for Gitea. Each skill is API-first using `openclaw-bot` service account.

## Authentication

- **Method:** Bearer token (Personal Access Token)
- **Token:** `~/agents/tokens/gitea.token`
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

**Trigger:** (internal — used by playbook for openclaw-bot setup)
**Method:** API
**Endpoint:** `POST /api/v1/users/{username}/tokens`
**Input:** `{ "name": "openclaw-token", "scopes": ["all"] }`
**Output:** `{ "id": 1, "name": "openclaw-token", "sha1": "<token>" }`
**Auth:** Basic auth (admin credentials) for initial token creation
