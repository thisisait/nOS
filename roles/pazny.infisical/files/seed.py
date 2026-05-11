#!/usr/bin/env python3
"""Infisical bootstrap + project + secret seeder.

Called by roles/pazny.infisical/tasks/seed.yml. Reads a JSON config from
the CLI arg (path), runs the headless flow:

    1. If no admin token in config → invoke `infisical bootstrap` to
       create admin user + organization, capture machine identity token.
       (One-shot; CLI errors gracefully if already bootstrapped, in which
       case we expect the operator to have the persisted token from a
       prior run.)
    2. For each project in the layout:
       a. GET workspaces, look up by slug — if exists, reuse id.
       b. Otherwise POST /api/v2/workspace to create.
       c. For each secret in the project:
            PATCH /api/v3/secrets/raw/<key>   (update existing)
            on 404 → POST /api/v3/secrets/raw/<key>  (create)

Output: JSON to stdout with `{token, projects_created, secrets_upserted,
errors}` so Ansible can register the result.

Idempotent: re-runs do not error on existing org/projects; secrets are
upserted on every call so Infisical mirrors Ansible's canonical values.

Standalone-runnable: only stdlib + the `infisical` CLI binary on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any


def _http(method: str, url: str, token: str | None = None,
          body: dict | None = None, timeout: int = 15) -> tuple[int, dict]:
    """JSON-in, JSON-out request. Returns (status, parsed_body | {})."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"error": f"network: {exc.reason}"}


def _run_bootstrap(domain: str, email: str, password: str,
                   org_name: str) -> tuple[bool, str, dict]:
    """Invoke `infisical bootstrap` CLI. Returns (success, token, raw)."""
    cmd = [
        "infisical", "bootstrap",
        "--domain", domain,
        "--email", email,
        "--password", password,
        "--organization", org_name,
        "--output", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)  # nosec B603
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, "", {"stdout": out, "stderr": err, "rc": proc.returncode}
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return False, "", {"stdout": out, "stderr": err, "parse_error": True}
    # The CLI returns: { identity: { credentials: { token: "..." }, ... }, ... }
    token = (
        payload.get("identity", {}).get("credentials", {}).get("token")
        or payload.get("machineIdentity", {}).get("token")
        or payload.get("token")
        or ""
    )
    return bool(token), token, payload


def _list_workspaces(domain: str, token: str) -> list[dict]:
    """Return all workspaces visible to the admin token."""
    status, body = _http("GET", f"{domain}/api/v1/workspace", token=token)
    if status != 200:
        return []
    return body.get("workspaces") or []


def _create_workspace(domain: str, token: str, project: dict) -> dict | None:
    body = {
        "projectName": project["name"],
        "slug": project["slug"],
        "projectDescription": project.get("description", ""),
        "type": "secret-manager",
        "shouldCreateDefaultEnvs": True,
    }
    status, payload = _http("POST", f"{domain}/api/v2/workspace",
                            token=token, body=body)
    if status not in (200, 201):
        return None
    return payload.get("project") or payload.get("workspace")


def _resolve_environment_slug(project: dict) -> str:
    """Infisical defaults: dev / staging / prod. We push to `prod`."""
    envs = project.get("environments") or []
    for slug in ("prod", "production"):
        if any(e.get("slug") == slug for e in envs):
            return slug
    # Fall back to the first env if `prod` is missing (shouldn't happen
    # with shouldCreateDefaultEnvs=true, but defensive).
    return envs[0]["slug"] if envs else "prod"


def _upsert_secret(domain: str, token: str, project_id: str, env_slug: str,
                   key: str, value: str) -> str:
    """PATCH first, POST on 404. Returns 'updated' | 'created' | 'error:<msg>'."""
    body_common = {
        "workspaceId": project_id,
        "environment": env_slug,
        "secretPath": "/",
        "secretValue": value or "",
    }
    # PATCH
    status, payload = _http("PATCH",
                            f"{domain}/api/v3/secrets/raw/{key}",
                            token=token, body=body_common)
    if status == 200:
        return "updated"
    # On any 404-ish (secret not found), try POST
    if status == 404:
        status2, payload2 = _http("POST",
                                  f"{domain}/api/v3/secrets/raw/{key}",
                                  token=token, body=body_common)
        if status2 in (200, 201):
            return "created"
        return f"error:create({status2}):{(payload2 or {}).get('message','')[:80]}"
    return f"error:patch({status}):{(payload or {}).get('message','')[:80]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Infisical with org/projects/secrets.")
    parser.add_argument("--config", required=True,
                        help="Path to JSON config (admin, projects, token state).")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    domain = cfg["domain"].rstrip("/")
    org = cfg["org_name"]
    email = cfg["admin_email"]
    password = cfg["admin_password"]
    projects = cfg.get("projects") or []
    token = (cfg.get("admin_token") or "").strip()

    result: dict[str, Any] = {
        "bootstrapped": False,
        "token": token,
        "projects": {},
        "errors": [],
    }

    if not token:
        ok, token, raw = _run_bootstrap(domain, email, password, org)
        if not ok:
            stderr = (raw.get("stderr") or "").lower()
            # "Already bootstrapped" / "user already exists" path — when
            # the operator wiped ~/.nos/secrets.yml but PG still has the
            # admin row. Surface this loudly: seed cannot continue without
            # a token, and there's no way for the playbook to recover the
            # original one. The KMS self-heal addresses the most common
            # case (kms_root_config can be reseeded); admin user can't
            # be similarly nuked without losing every project + secret.
            if "already" in stderr or "exists" in stderr:
                result["errors"].append(
                    "admin already bootstrapped but no token persisted; "
                    "manually retrieve via UI or wipe with -e blank=true"
                )
            else:
                result["errors"].append(f"bootstrap failed: {raw}")
            print(json.dumps(result))
            return 2
        result["bootstrapped"] = True
        result["token"] = token

    # Index existing workspaces by slug (idempotent project ensure).
    existing = {w.get("slug"): w for w in _list_workspaces(domain, token)}

    for p in projects:
        slug = p["slug"]
        if slug in existing:
            project_obj = existing[slug]
            ensure_state = "exists"
        else:
            project_obj = _create_workspace(domain, token, p)
            ensure_state = "created" if project_obj else "error"
            if project_obj:
                existing[slug] = project_obj
        if not project_obj:
            result["errors"].append(f"project {slug}: create failed")
            result["projects"][slug] = {"state": "error", "secrets": {}}
            continue

        project_id = project_obj.get("id") or project_obj.get("_id") or ""
        env_slug = _resolve_environment_slug(project_obj)
        secret_results: dict[str, str] = {}
        for key, value in (p.get("secrets") or {}).items():
            if not key:
                continue
            secret_results[key] = _upsert_secret(
                domain, token, project_id, env_slug, key, str(value))
        result["projects"][slug] = {
            "state": ensure_state,
            "id": project_id,
            "env": env_slug,
            "secrets": secret_results,
        }

    print(json.dumps(result))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
