"""Box Management API for nOS."""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Header

app = FastAPI(title="nOS Bone API", version="0.2.0")

# Track B (2026-04-26): operational endpoints now require Authentik-issued
# JWTs with capability scopes. The legacy BONE_SECRET / X-API-Key channel is
# retired (decision O4); the only places that read it from env are Bone's
# own boot-time guard (auth.py:assert_configured) and the events.py HMAC
# fallback secret. See files/bone/auth.py for the verifier.
SERVICE_REGISTRY_PATH = os.getenv(
    "SERVICE_REGISTRY_PATH",
    os.path.expanduser("~/projects/default/service-registry.json"),
)
PLAYBOOK_DIR = os.getenv("PLAYBOOK_DIR", os.path.expanduser("~/nOS"))
VERSION_FILE = os.path.join(PLAYBOOK_DIR, "VERSION")
BOOT_TIME = time.time()


# -- Auth --------------------------------------------------------------------
# JWT-based scope checks. The dependency factory `require_scope(...)` lives
# in auth.py; importing it here gives every route a one-liner gate.

try:  # noqa: SIM105
    from auth import require_scope, assert_configured as _assert_auth_configured
    _assert_auth_configured()
    _AUTH_READY = True
except Exception as _auth_err:  # noqa: BLE001
    # Boot-time auth failures are loud — Bone refuses to serve operational
    # routes if its JWT auth isn't wired up. We still expose /api/health so
    # docker compose's healthcheck can report the underlying issue via a
    # response body, instead of just hanging the container in a restart loop.
    _AUTH_READY = False
    _AUTH_INIT_ERROR = str(_auth_err)

    def require_scope(*scopes: str):  # type: ignore[no-redef]
        async def _dep():
            raise HTTPException(
                status_code=503,
                detail=f"Bone JWT auth not initialized: {_AUTH_INIT_ERROR}",
            )
        return _dep


# -- Helpers -----------------------------------------------------------------


def _read_registry() -> list[dict]:
    path = Path(SERVICE_REGISTRY_PATH)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("services", [])


async def _check_health(client: httpx.AsyncClient, svc: dict) -> dict:
    url = svc.get("url", "")
    if not url:
        return {**svc, "healthy": None, "error": "no url"}
    health_url = url.rstrip("/") + "/api/health"
    try:
        resp = await client.get(health_url, timeout=5, follow_redirects=True)
        return {**svc, "healthy": resp.status_code < 400}
    except Exception as exc:  # noqa: BLE001
        return {**svc, "healthy": False, "error": str(exc)}


# -- Endpoints ---------------------------------------------------------------


@app.get("/api/health")
async def health():
    """Aggregated health of all registered services."""
    services = _read_registry()
    if not services:
        return {"status": "ok", "services": [], "healthy": 0, "unhealthy": 0}

    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        results = await asyncio.gather(
            *[_check_health(client, s) for s in services]
        )

    healthy = sum(1 for r in results if r.get("healthy") is True)
    unhealthy = sum(1 for r in results if r.get("healthy") is False)
    return {
        "status": "ok" if unhealthy == 0 else "degraded",
        "services": results,
        "healthy": healthy,
        "unhealthy": unhealthy,
    }


@app.get("/api/services")
async def services():
    """Return service-registry.json content."""
    path = Path(SERVICE_REGISTRY_PATH)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="service-registry.json not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/status")
async def status():
    """Box identity and basic status."""
    version = "unknown"
    version_path = Path(VERSION_FILE)
    if version_path.is_file():
        version = version_path.read_text(encoding="utf-8").strip()

    services = _read_registry()
    uptime_seconds = time.time() - BOOT_TIME

    return {
        "instance_name": "nOS",
        "version": version,
        "uptime": round(uptime_seconds),
        "hostname": socket.gethostname(),
        "services_count": len(services),
    }


@app.post("/api/run-tag")
async def run_tag(
    tag: str,
    _=Depends(require_scope("nos:run-tag")),
):
    """Trigger ansible-playbook with a specific tag (requires API key)."""
    # Strict allow-list: must start with a letter, then alphanumeric + `_-,`.
    # Rejects values that would parse as ansible-playbook flags (e.g. starting
    # with `-`). subprocess.Popen is invoked with a list-form `cmd` and
    # shell=False so even loose validation can't reach a shell, but we keep
    # the validator strict so CodeQL's command-injection check is satisfied
    # without having to mark the alert as "won't fix".
    if not tag or not re.match(r"^[A-Za-z][A-Za-z0-9_,-]{0,99}$", tag):
        raise HTTPException(status_code=400, detail="Invalid tag format")

    cmd = [
        "ansible-playbook", "main.yml",
        "--tags", tag,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=PLAYBOOK_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        stdout, _ = proc.communicate(timeout=600)
        return {
            "tag": tag,
            "returncode": proc.returncode,
            "output": stdout[-4000:] if len(stdout) > 4000 else stdout,
        }
    except subprocess.TimeoutExpired:
        proc.kill()
        raise HTTPException(status_code=504, detail="Playbook execution timed out")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500, detail="ansible-playbook not found in PATH"
        )


# ============================================================================
# State & Migration Framework (agent 7) ------------------------------------
# Additive routes. Helper logic lives in state.py / migrations.py /
# upgrades.py / coexistence.py / events.py — all sibling modules in
# ~/bone/. Do not restructure the original routes above.
# ============================================================================

# Deferred imports so existing deployments without the new sibling modules
# or PyYAML continue booting. The new endpoints will 500 until files land.
try:  # noqa: SIM105
    import state as _nos_state  # type: ignore
    import migrations as _nos_migrations  # type: ignore
    import upgrades as _nos_upgrades  # type: ignore
    import patches as _nos_patches  # type: ignore
    import coexistence as _nos_coexistence  # type: ignore
    import events as _nos_events  # type: ignore
    _FRAMEWORK_READY = True
except Exception as _framework_err:  # noqa: BLE001
    _FRAMEWORK_READY = False
    _FRAMEWORK_IMPORT_ERROR = str(_framework_err)


def _require_framework() -> None:
    if not _FRAMEWORK_READY:
        raise HTTPException(
            status_code=503,
            detail=f"State framework modules not loaded: {_FRAMEWORK_IMPORT_ERROR}",
        )


def _status_from_payload(payload: dict, default: int = 200) -> int:
    if isinstance(payload, dict) and isinstance(payload.get("status"), int):
        return payload["status"]
    if isinstance(payload, dict) and payload.get("error"):
        return 400
    return default


# ---- /api/state ------------------------------------------------------------


@app.get("/api/state")
async def state_root(_=Depends(require_scope("nos:state:read"))):
    _require_framework()
    return _nos_state.read_state()


@app.post("/api/state")
async def state_push(
    body: dict | None = None,
    _=Depends(require_scope("nos:state:write")),
):
    """Accept a state snapshot from pazny.state_manager (end-of-run report).

    JWT scope `nos:state:write` is required (Track B, 2026-04-26). The
    snapshot is already on disk in ~/.nos/state.yml that the role wrote
    first, so this endpoint is mostly a "telemetry trigger" + "remote
    operator can poke a state push without ssh" affordance.
    """
    _require_framework()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="body must be a JSON object")
    try:
        return _nos_state.write_state(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"state write failed: {exc}")


@app.get("/api/state/services")
async def state_services(_=Depends(require_scope("nos:state:read"))):
    _require_framework()
    return _nos_state.get_services()


@app.get("/api/state/services/{service_id}")
async def state_service(service_id: str, _=Depends(require_scope("nos:state:read"))):
    _require_framework()
    svc = _nos_state.get_service(service_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="service not in state")
    return svc


# ---- /api/migrations -------------------------------------------------------


@app.get("/api/migrations")
async def migrations_list(_=Depends(require_scope("nos:migrations:read"))):
    _require_framework()
    return _nos_migrations.split_pending_applied()


@app.get("/api/migrations/{migration_id}")
async def migrations_get(migration_id: str, _=Depends(require_scope("nos:migrations:read"))):
    _require_framework()
    rec = _nos_migrations.get_by_id(migration_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="migration not found")
    return rec


@app.post("/api/migrations/{migration_id}/preview")
async def migrations_preview(migration_id: str, _=Depends(require_scope("nos:migrations:read"))):
    _require_framework()
    payload = _nos_migrations.preview(migration_id)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "preview failed"))
    return payload


@app.post("/api/migrations/{migration_id}/apply")
async def migrations_apply(
    migration_id: str,
    body: dict | None = None,
    _=Depends(require_scope("nos:migrations:apply")),
):
    _require_framework()
    dry_run = bool((body or {}).get("dry_run"))
    payload = _nos_migrations.apply(migration_id, dry_run=dry_run)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "apply failed"))
    return payload


@app.post("/api/migrations/{migration_id}/rollback")
async def migrations_rollback(migration_id: str, _=Depends(require_scope("nos:migrations:apply"))):
    _require_framework()
    payload = _nos_migrations.rollback(migration_id)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "rollback failed"))
    return payload


# ---- /api/upgrades ---------------------------------------------------------


@app.get("/api/upgrades")
async def upgrades_matrix(_=Depends(require_scope("nos:upgrades:read"))):
    _require_framework()
    return _nos_upgrades.matrix()


@app.get("/api/upgrades/{service}")
async def upgrades_service(service: str, _=Depends(require_scope("nos:upgrades:read"))):
    _require_framework()
    data = _nos_upgrades.for_service(service)
    if data is None:
        raise HTTPException(status_code=404, detail="service recipes not found")
    return data


@app.get("/api/upgrades/{service}/{recipe_id}")
async def upgrades_recipe(service: str, recipe_id: str, _=Depends(require_scope("nos:upgrades:read"))):
    _require_framework()
    rec = _nos_upgrades.get_recipe(service, recipe_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    return rec


@app.post("/api/upgrades/{service}/{recipe_id}/plan")
async def upgrades_plan(service: str, recipe_id: str, _=Depends(require_scope("nos:upgrades:read"))):
    _require_framework()
    payload = _nos_upgrades.plan(service, recipe_id)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "plan failed"))
    return payload


@app.post("/api/upgrades/{service}/{recipe_id}/apply")
async def upgrades_apply(service: str, recipe_id: str, _=Depends(require_scope("nos:upgrades:apply"))):
    _require_framework()
    payload = _nos_upgrades.apply(service, recipe_id)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "apply failed"))
    return payload


# ---- /api/patches ---------------------------------------------------------


@app.get("/api/patches")
async def patches_list(_=Depends(require_scope("nos:patches:read"))):
    _require_framework()
    return _nos_patches.list_all()


@app.get("/api/patches/{patch_id}")
async def patches_get(patch_id: str, _=Depends(require_scope("nos:patches:read"))):
    _require_framework()
    rec = _nos_patches.get_by_id(patch_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="patch not found")
    return rec


@app.post("/api/patches/{patch_id}/plan")
async def patches_plan(patch_id: str, _=Depends(require_scope("nos:patches:read"))):
    _require_framework()
    payload = _nos_patches.plan(patch_id)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "plan failed"))
    return payload


@app.post("/api/patches/{patch_id}/apply")
async def patches_apply(patch_id: str, _=Depends(require_scope("nos:patches:apply"))):
    _require_framework()
    payload = _nos_patches.apply(patch_id)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "apply failed"))
    return payload


# ---- /api/coexistence -----------------------------------------------------


@app.get("/api/coexistence")
async def coexistence_list(_=Depends(require_scope("nos:coexistence:read"))):
    _require_framework()
    return _nos_coexistence.list_tracks()


@app.post("/api/coexistence/{service}/provision")
async def coexistence_provision(
    service: str,
    body: dict,
    _=Depends(require_scope("nos:coexistence:write")),
):
    _require_framework()
    payload = _nos_coexistence.provision(service, body or {})
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "provision failed"))
    return payload


@app.post("/api/coexistence/{service}/cutover")
async def coexistence_cutover(
    service: str,
    body: dict,
    _=Depends(require_scope("nos:coexistence:write")),
):
    _require_framework()
    target_tag = str((body or {}).get("target_tag", ""))
    if not target_tag:
        raise HTTPException(status_code=400, detail="target_tag is required")
    payload = _nos_coexistence.cutover(service, target_tag)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "cutover failed"))
    return payload


@app.post("/api/coexistence/{service}/cleanup/{tag}")
async def coexistence_cleanup(
    service: str,
    tag: str,
    body: dict | None = None,
    _=Depends(require_scope("nos:coexistence:write")),
):
    _require_framework()
    force = bool((body or {}).get("force"))
    payload = _nos_coexistence.cleanup(service, tag, force=force)
    status = _status_from_payload(payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload.get("error", "cleanup failed"))
    return payload


# ---- /api/events + /api/v1/events (aliased) -------------------------------
# Plugin's documented URL is /api/v1/events but main.py historically used the
# unversioned form. Keep both registered so existing tests + the callback
# plugin both work without a config flag.


@app.post("/api/events")
@app.post("/api/v1/events")
async def events_ingest(
    x_wing_timestamp: str = Header(default=""),
    x_wing_signature: str = Header(default=""),
    body: dict | None = None,
):
    """HMAC-authenticated (not API-key) event ingestion from the callback
    plugin. Writes directly to Wing's events.db.
    """
    _require_framework()
    # Rebuild raw body from the parsed dict — FastAPI doesn't give us the raw
    # bytes by default without a Request dep. Use a canonical JSON encoding
    # so the callback plugin can reproduce the signature on its side.
    raw = json.dumps(body or {}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ok, err = _nos_events.verify_hmac(
        x_wing_timestamp, x_wing_signature, raw
    )
    if not ok:
        raise HTTPException(status_code=401, detail=f"HMAC check failed: {err}")

    # The callback plugin sends batches as {"events": [event, event, ...]}.
    # Iterate, validate each, insert each. Single-event payloads are also
    # accepted for backwards compat with hand-curl tests.
    payload = body or {}
    if "events" in payload and isinstance(payload["events"], list):
        events = payload["events"]
    else:
        events = [payload]

    accepted_ids: list[int] = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise HTTPException(status_code=400,
                                detail=f"events[{idx}]: not a JSON object")
        verr = _nos_events.validate_payload(ev)
        if verr is not None:
            raise HTTPException(status_code=400,
                                detail=f"events[{idx}]: {verr}")
        try:
            accepted_ids.append(_nos_events.insert_event(ev))
        except _nos_events.WingDBNotReady as exc:
            # Transient — Wing hasn't been initialised yet (e.g. early in a
            # blank reset where Bone deploys before pazny.wing). 503 so the
            # callback plugin retries from its fallback queue on next run.
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500,
                                detail=f"events[{idx}] insert failed: {exc}")
    return {"accepted": True, "count": len(accepted_ids), "ids": accepted_ids}


@app.get("/api/events")
async def events_list(
    run_id: str | None = None,
    type: str | None = None,
    since: str | None = None,
    migration_id: str | None = None,
    upgrade_id: str | None = None,
    limit: int = 100,
    _=Depends(require_scope("nos:state:read")),
):
    """Paginated event query. Wing also serves its own /api/v1/events
    directly from SQLite — this route is a Bone-side convenience for CLI
    users.

    Anatomy P0.1b (2026-05-04): direct sqlite3 access moved to
    ``clients.wing.query_events``. CI lint enforces no
    ``sqlite3.connect.*wing\\.db`` outside that module.
    """
    _require_framework()
    from clients import wing as _wing
    rows = _wing.query_events(
        run_id=run_id,
        type=type,
        since=since,
        migration_id=migration_id,
        upgrade_id=upgrade_id,
        limit=limit,
    )
    return {"items": rows, "count": len(rows)}


# ── Qdrant proxy — /api/v1/embeddings/{upsert,search,health} ─────────────────
# Bone owns the Qdrant API key (passed via plist env QDRANT_API_KEY); agents
# and plugin runners reach Qdrant ONLY through these endpoints, so the key
# never leaves the host. Returns 503 when install_qdrant=false (URL empty).

try:
    from clients import qdrant_client as _qdrant
except ImportError:  # pragma: no cover — only triggers in degraded env
    _qdrant = None


def _qdrant_or_503():
    if _qdrant is None:
        raise HTTPException(status_code=503, detail="qdrant client module not loaded")
    client = _qdrant.get()
    if not client.is_configured():
        raise HTTPException(status_code=503, detail="QDRANT_URL is empty (install_qdrant=false)")
    return client


@app.get("/api/v1/embeddings/health")
async def embeddings_health(_=Depends(require_scope("nos:embeddings:read"))):
    """Probe Qdrant /healthz — uniform path agents can use as a precondition."""
    client = _qdrant_or_503()
    try:
        return client.health()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"qdrant unhealthy: {exc}")


@app.post("/api/v1/embeddings/upsert")
async def embeddings_upsert(
    body: dict | None = None,
    _=Depends(require_scope("nos:embeddings:write")),
):
    """Upsert N points into a Qdrant collection.

    Body shape:
      {"collection": "agent_outputs",
       "points": [{"id": "...", "vector": [..768..], "payload": {...}}, ...]}
    """
    client = _qdrant_or_503()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    collection = body.get("collection")
    raw_points = body.get("points")
    if not isinstance(collection, str) or not collection:
        raise HTTPException(status_code=400, detail="collection (str) is required")
    if not isinstance(raw_points, list) or not raw_points:
        raise HTTPException(status_code=400, detail="points (non-empty list) is required")
    try:
        points = [
            _qdrant.Point(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload"),
            )
            for p in raw_points
        ]
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid point: {exc}")
    try:
        return client.upsert(collection, points)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"qdrant upsert failed: {exc}")


@app.post("/api/v1/embeddings/search")
async def embeddings_search(
    body: dict | None = None,
    _=Depends(require_scope("nos:embeddings:read")),
):
    """k-NN search over a Qdrant collection.

    Body shape:
      {"collection": "agent_outputs",
       "vector":  [..768..],
       "limit":   10,                # optional, default 10
       "filter":  {...} | null}      # optional Qdrant filter object
    """
    client = _qdrant_or_503()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    collection = body.get("collection")
    vector = body.get("vector")
    if not isinstance(collection, str) or not collection:
        raise HTTPException(status_code=400, detail="collection (str) is required")
    if not isinstance(vector, list) or not vector:
        raise HTTPException(status_code=400, detail="vector (non-empty list) is required")
    limit = int(body.get("limit") or 10)
    filt = body.get("filter")
    try:
        return client.search(collection, vector, limit=limit, filter=filt)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"qdrant search failed: {exc}")
