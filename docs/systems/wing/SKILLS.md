# Wing — Skills

> Callable actions on the Wing dashboard API. Base URL `https://wing.<tenant_domain>/api/v1/` (or `http://localhost:9000/api/v1/`). All routes below require `Authorization: Bearer <wing_api_token>` unless noted; the UI itself is Authentik forward-auth gated (tier 1).

## check-hub-health

**Trigger:** "wing hub health", "is the estate healthy", "hub health"
**Method:** API
**Endpoint:** `GET /api/v1/hub/health`
**Output:** Aggregate hub health JSON for the /hub overview.

## list-systems

**Trigger:** "list systems", "estate inventory", "what systems does Wing know"
**Method:** API
**Endpoint:** `GET /api/v1/hub/systems[/<id>]`
**Output:** The systems inventory (one system with `<id>`, or the full list).

## query-events

**Trigger:** "show wing events", "query the timeline", "what happened recently"
**Method:** API
**Endpoint:** `GET /api/v1/events`
**Output:** Event rows from `wing.db.events` (Ansible tasks + framework actions ingested via Bone).

## list-remediation

**Trigger:** "remediation queue", "open security findings", "what needs remediating"
**Method:** API
**Endpoint:** `GET /api/v1/remediation[/<id>]`
**Output:** Remediation items; `GET /api/v1/remediation/next-id` returns the next REM id.

## list-agents

**Trigger:** "list agents", "AgentKit agents", "show agent sessions"
**Method:** API
**Endpoint:** `GET /api/v1/agents[/<name>]` and `GET /api/v1/agents/<name>/sessions`
**Output:** Agent catalog / detail; session list. `GET /api/v1/agent-sessions/<uuid>` deep-dives one run.

## list-due-pulse-jobs

**Trigger:** "what pulse jobs are due", "scheduled jobs", "pulse due"
**Method:** API
**Endpoint:** `GET /api/v1/pulse_jobs/due`
**Output:** Jobs due to run now. `GET /api/v1/pulse_jobs[/<id>]` lists/gets all registered jobs.

## trigger-deploy

**Trigger:** "trigger a deploy", "deploy from CI", "run the auto-deploy"
**Method:** API
**Endpoint:** `POST /api/v1/deploy-trigger`
**Input:** `{"deploy_uuid":"<uuid4>", ...}` on a trusted branch (`master` is operator-manual).
**Output:** `202 Accepted` `{"deploy_uuid":"...","log_path":"..."}`; wraps `tools/deploy-from-ci.sh` detached (1 deploy at a time). This is a real deploy.

## list-gdpr-processing

**Trigger:** "GDPR register", "Article 30 records", "data processing activities"
**Method:** API
**Endpoint:** `GET /api/v1/gdpr/processing[/<id>]`
**Output:** The Article-30 processing register; DSAR records at `GET /api/v1/gdpr/dsar[/<id>]`, breaches at `/gdpr/breaches[/<id>]`.
