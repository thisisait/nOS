"""
Qdrant client for Bone — thin wrapper over the REST API.

Bone exposes /api/v1/embeddings/upsert and /api/v1/embeddings/search; both
proxy to Qdrant via this module so the API key never leaves the host. When
QDRANT_URL is empty (install_qdrant=false in default.config.yml), every
public call raises NotConfigured — Bone's route handlers catch that and
return HTTP 503 so consumers learn quickly that the substrate is absent.

Reads:
  QDRANT_URL       — e.g. http://127.0.0.1:6333  (empty = disabled)
  QDRANT_API_KEY   — service.api_key (required when URL is set)
  QDRANT_TIMEOUT   — request timeout in seconds (default 10)

Public surface:
  QdrantClient.is_configured() -> bool
  QdrantClient.health() -> dict       # GET /healthz, raises on non-200
  QdrantClient.list_collections() -> list[str]
  QdrantClient.upsert(collection, points: list[Point]) -> dict
  QdrantClient.search(collection, vector, limit=10, filter=None) -> list[dict]
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


class NotConfigured(RuntimeError):
    """Raised when QDRANT_URL is empty — substrate not deployed."""


@dataclass
class Point:
    """Qdrant upsert payload point. `vector` must match collection dim."""

    id: str | int
    vector: list[float]
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "vector": self.vector}
        if self.payload is not None:
            out["payload"] = self.payload
        return out


class QdrantClient:
    """Module-level singleton instantiated lazily. Call get() to fetch it."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.url = (url if url is not None else os.environ.get("QDRANT_URL", "")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("QDRANT_API_KEY", "")
        self.timeout = timeout if timeout is not None else float(os.environ.get("QDRANT_TIMEOUT", "10"))

    # ── Configuration & health ────────────────────────────────────────────
    def is_configured(self) -> bool:
        return bool(self.url)

    def _require(self) -> None:
        if not self.is_configured():
            raise NotConfigured("QDRANT_URL is empty — install_qdrant=false")

    def _headers(self) -> dict[str, str]:
        h = {"content-type": "application/json"}
        if self.api_key:
            h["api-key"] = self.api_key
        return h

    def health(self) -> dict[str, Any]:
        """GET /healthz — unauthenticated; useful for guards in handlers."""
        self._require()
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.url}/healthz")
            r.raise_for_status()
            return {"status": "ok", "raw": r.text}

    # ── Collection ops ────────────────────────────────────────────────────
    def list_collections(self) -> list[str]:
        self._require()
        with httpx.Client(timeout=self.timeout, headers=self._headers()) as c:
            r = c.get(f"{self.url}/collections")
            r.raise_for_status()
            return [it["name"] for it in r.json().get("result", {}).get("collections", [])]

    def collection_info(self, collection: str) -> dict[str, Any]:
        self._require()
        with httpx.Client(timeout=self.timeout, headers=self._headers()) as c:
            r = c.get(f"{self.url}/collections/{collection}")
            r.raise_for_status()
            return r.json().get("result", {})

    # ── Point ops ─────────────────────────────────────────────────────────
    def upsert(self, collection: str, points: list[Point]) -> dict[str, Any]:
        self._require()
        body = {"points": [p.to_dict() for p in points]}
        with httpx.Client(timeout=self.timeout, headers=self._headers()) as c:
            r = c.put(f"{self.url}/collections/{collection}/points?wait=true", json=body)
            r.raise_for_status()
            return r.json().get("result", {})

    def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 10,
        with_payload: bool = True,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._require()
        body: dict[str, Any] = {"vector": vector, "limit": limit, "with_payload": with_payload}
        if filter is not None:
            body["filter"] = filter
        with httpx.Client(timeout=self.timeout, headers=self._headers()) as c:
            r = c.post(f"{self.url}/collections/{collection}/points/search", json=body)
            r.raise_for_status()
            return r.json().get("result", [])


_singleton: QdrantClient | None = None


def get() -> QdrantClient:
    """Lazy singleton — env vars are read on first call, then cached."""
    global _singleton
    if _singleton is None:
        _singleton = QdrantClient()
    return _singleton
