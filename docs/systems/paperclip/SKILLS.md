# Paperclip — Skills

> Paperclip exposes **no external HTTP admin API** in nOS. Its invocable surface is the
> in-container `pnpm paperclipai` CLI, run through `docker compose exec`. Every command
> below is verified against `roles/pazny.paperclip/tasks/post.yml`. The end-user surface
> is the browser UI (better-auth); agent-to-agent orchestration happens inside Paperclip,
> not through a documented nOS endpoint.

## Authentication

- **Method:** None (container exec — the operator/playbook runs `pnpm paperclipai` inside the container; there is no stored token or bearer for agents to hold)
- **Prefix:** `docker compose -p devops exec -T paperclip pnpm paperclipai`
- **Container:** `devops-paperclip-1`

---

## onboard

**Trigger:** "initialize paperclip", "onboard a fresh paperclip instance"
**Method:** CLI (container exec)
**Command:**
```bash
docker compose -p devops exec -T paperclip \
  pnpm paperclipai onboard --yes --data-dir /paperclip
```
**Input:** None (non-interactive)
**Output:** Writes `/paperclip/instances/default/config.json`; success line `Configuration ready`. Skip if that config already exists.

---

## register-allowed-hostname

**Trigger:** "paperclip returns no response", "register a paperclip hostname", "add allowed host to paperclip"
**Method:** CLI (container exec)
**Command:**
```bash
docker compose -p devops exec -T paperclip \
  pnpm paperclipai allowed-hostname paperclip.<tenant_domain>
```
**Input:** the hostname to allow
**Output:** Registers the hostname so Paperclip serves requests carrying that `Host`. Without it Paperclip closes the TCP connection with no HTTP response. Idempotent on an existing hostname.

---

## bootstrap-ceo

**Trigger:** "create the first paperclip admin", "bootstrap paperclip CEO", "get the paperclip invite url"
**Method:** CLI (container exec)
**Command:**
```bash
docker compose -p devops exec -T paperclip \
  pnpm paperclipai auth bootstrap-ceo \
  --data-dir /paperclip --base-url "https://paperclip.<tenant_domain>"
```
**Input:** None
**Output:** Creates the first CEO admin and prints an `Invite URL`. First-run only — guard on `SELECT COUNT(*) FROM account` being `0` (re-running when an account exists reports `already exists`).
