"""Minimal HTTP client for Wing API (Bearer-token auth).

Only the endpoints Pulse needs in PoC: list due jobs, post run start, post
run finish. Wing implements these endpoints in PHP — schema stub is in
``files/anatomy/wing/db/schema-extensions.sql`` (pulse_jobs / pulse_runs);
PHP presenters land in a follow-up commit alongside the first non-agentic
job registration.

Until Wing exposes the endpoints (PoC stub phase), the client tolerates
404/405 by returning empty results — letting the daemon idle-tick safely
on a fresh blank rather than crash-looping.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("pulse.wing")


class WingClient:
    """Sync HTTP client. Pulse's tick is single-threaded — no need for async."""

    def __init__(self, base_url: str, token: str, timeout_s: float = 5.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "nos-pulse/0.1",
                "Accept": "application/json",
            },
            timeout=timeout_s,
        )

    def close(self) -> None:
        self._client.close()

    # ── Job discovery ───────────────────────────────────────────────────

    def list_due_jobs(self) -> list[dict[str, Any]]:
        """Return jobs whose `next_fire_at` <= now and `paused` is false.

        Tolerates 404/405 (endpoint not yet implemented) by returning [].
        """
        try:
            r = self._client.get("/api/v1/pulse_jobs/due")
        except httpx.HTTPError as e:
            log.warning("list_due_jobs: transport error %s", e)
            return []
        if r.status_code in (404, 405):
            log.debug("list_due_jobs: endpoint not implemented yet (%d)",
                      r.status_code)
            return []
        if r.status_code != 200:
            log.warning("list_due_jobs: HTTP %d %s", r.status_code, r.text[:200])
            return []
        try:
            data = r.json()
        except Exception as e:  # noqa: BLE001 — JSON parse fragility
            log.warning("list_due_jobs: JSON parse error %s", e)
            return []
        # Wing response shape (2026-05-07): {"generated_at": "...",
        # "jobs": [...]}. The dict wrapper lets future Wing versions add
        # metadata (e.g. catalog_version, hmac signature) without breaking
        # the contract. Pulse only needs the list.
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return data["jobs"]
        if isinstance(data, list):
            # Tolerate the older un-wrapped shape for the cutover window.
            return data
        log.warning("list_due_jobs: unexpected payload shape %r", type(data))
        return []

    # ── Run lifecycle ───────────────────────────────────────────────────

    def post_run_start(self, job_id: str, run_id: str,
                       fired_at_iso: str) -> bool:
        return self._post("/api/v1/pulse_runs/start", {
            "job_id": job_id,
            "run_id": run_id,
            "fired_at": fired_at_iso,
        })

    def post_run_finish(self, run_id: str, *, finished_at_iso: str,
                        exit_code: int, stdout_tail: str = "",
                        stderr_tail: str = "") -> bool:
        return self._post("/api/v1/pulse_runs/finish", {
            "run_id": run_id,
            "finished_at": finished_at_iso,
            "exit_code": exit_code,
            "stdout_tail": stdout_tail[-2000:],
            "stderr_tail": stderr_tail[-2000:],
        })

    # ── internal ────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict[str, Any]) -> bool:
        try:
            r = self._client.post(path, json=payload)
        except httpx.HTTPError as e:
            log.warning("POST %s transport error %s", path, e)
            return False
        if r.status_code in (200, 201, 204):
            return True
        if r.status_code in (404, 405):
            log.debug("POST %s not implemented yet (%d)", path, r.status_code)
            return False
        log.warning("POST %s -> HTTP %d %s", path, r.status_code, r.text[:200])
        return False
