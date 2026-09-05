"""A host tool that forges KEAP identity must carry the proxy secret (2026-09-05).

KEAP's SEC-02 proxy-trust (P1) makes `/api/*` trust X-Authentik-* headers ONLY
when `x-keap-proxy-secret` matches — checked before any identity header is read.
Browser traffic gets the secret from Traefik's keap-proxy@file middleware; a
host-side tool hitting the loopback publish (127.0.0.1:8091) is NOT behind
Traefik, so it must present the secret itself or every call 401s.

When the secret landed, ~11 host tools that build X-Authentik-* headers by hand
broke at once — including tools/roadmap-status.py, so the roadmap could not even
be read. The fix routed them all through tools/keap_api.py (human_headers /
proxy_header), which resolves the secret once from the running container.

This gate keeps it that way: any tool that constructs an X-Authentik-* identity
header (only ever meaningful for KEAP's /api) MUST also reference the shared
helper or the secret header — otherwise it is a call that will 401 in prod. A
host tool sends X-Authentik-* for exactly one reason, so the presence of that
header is the trigger; the remedy is always `from keap_api import human_headers`.
"""

from __future__ import annotations

import os
from glob import glob

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# A host tool that reaches KEAP's human /api surface: the loopback publish AND
# an /api/ path (NOT /agent/v1 — that's the Bearer surface, not proxy-gated).
def _talks_to_keap_api(txt: str) -> bool:
    return "8091" in txt and "/api/" in txt


# Any of these means the tool routes through the shared, secret-carrying path.
_OK = ("human_headers", "proxy_header", "keap_api", "x-keap-proxy-secret")

# Files that trip the loose (8091 + /api/) trigger but do NOT call KEAP's
# identity-gated human /api — cleared with the reason, mirroring
# test_jinja_heredoc_antipattern.py's ALLOWED_FILES idiom. The trigger can't
# separate these by regex (real callers also build the URL by concatenation),
# so the clearance is explicit and reviewable. Add here ONLY when the /api hit
# is Ollama, another service, /agent (Bearer), or prose — never to silence a
# real KEAP /api caller (fix that with `from keap_api import human_headers`).
_ALLOWED = {
    "tools/estate-status.py":                 "KEAP probe is /agent/v1/health; the /api hits are bone/wing",
    "tools/local-model-bench.py":             "KEAP via /agent (Bearer); /api/generate is Ollama",
    "tools/keap-linked-data/resolve-typing.py": "/api/graph is a docstring note; live writes are /agent/v1 (Bearer)",
    "files/anatomy/scripts/keap-lint.py":     "calls /agent/v1/lint/run (Bearer); /api/lint is a docstring",
    "files/anatomy/scripts/keap-features-sync.py": "KEAP via /agent (Bearer); /api/embed is Ollama",
    "files/anatomy/scripts/keap-embed-sync.py": "KEAP via /agent (Bearer); /api/embed is Ollama",
}


def _candidates() -> list[str]:
    out: set[str] = set()
    for pat in ("tools/**/*.py", "files/anatomy/scripts/*.py"):
        for f in glob(os.path.join(_REPO, pat), recursive=True):
            out.add(os.path.abspath(f))
    # keap_api.py IS the helper — exempt itself.
    out.discard(os.path.join(_REPO, "tools", "keap_api.py"))
    hits = []
    for f in sorted(out):
        rel = os.path.relpath(f, _REPO)
        if rel in _ALLOWED:
            continue
        txt = open(f, encoding="utf-8", errors="ignore").read()
        if _talks_to_keap_api(txt):
            hits.append((rel, txt))
    return hits


_CASES = _candidates()


@pytest.mark.parametrize("relpath,txt", _CASES, ids=[r for r, _ in _CASES])
def test_identity_header_carries_proxy_secret(relpath, txt):
    assert any(k in txt for k in _OK), (
        f"{relpath} calls KEAP's /api on 127.0.0.1:8091 but never references the "
        f"proxy secret — it will 401 since KEAP P1. Route it through "
        f"tools/keap_api.py: `from keap_api import human_headers` and use "
        f"`human_headers(...)` for the request headers."
    )


def test_gate_sees_identity_builders():
    """A green vacuum (walker finds nothing) is not a pass."""
    assert _CASES, "no KEAP /api callers found — walker broken, not tree"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
