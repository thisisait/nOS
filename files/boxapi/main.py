"""Box Management API for devBoxNOS."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Header

app = FastAPI(title="devBoxNOS Box API", version="0.1.0")

BOXAPI_SECRET = os.getenv("BOXAPI_SECRET", "")
SERVICE_REGISTRY_PATH = os.getenv(
    "SERVICE_REGISTRY_PATH",
    os.path.expanduser("~/projects/default/service-registry.json"),
)
PLAYBOOK_DIR = os.getenv("PLAYBOOK_DIR", os.path.expanduser("~/mac-dev-playbook"))
VERSION_FILE = os.path.join(PLAYBOOK_DIR, "VERSION")
BOOT_TIME = time.time()


# -- Auth --------------------------------------------------------------------


def _verify_api_key(x_api_key: str = Header(default="")) -> None:
    if not BOXAPI_SECRET:
        raise HTTPException(status_code=500, detail="BOXAPI_SECRET not configured")
    if x_api_key != BOXAPI_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API key")


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
        "instance_name": "devBoxNOS",
        "version": version,
        "uptime": round(uptime_seconds),
        "hostname": socket.gethostname(),
        "services_count": len(services),
    }


@app.post("/api/run-tag")
async def run_tag(
    tag: str,
    _: None = Depends(_verify_api_key),
):
    """Trigger ansible-playbook with a specific tag (requires API key)."""
    if not tag or not tag.replace("-", "").replace("_", "").replace(",", "").isalnum():
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
