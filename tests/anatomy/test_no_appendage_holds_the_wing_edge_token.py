"""No container compose renders WING_EDGE_TOKEN: it alone makes Wing's Latte pages believe X-Authentik-*.

WHY (roadmap `edge-token-forges-tier`, 2026-10-07). face's compose carried the token,
so a compromised face could forge a Tier-1 identity to Wing's pages (/admin halt).
Only the edge (Traefik, a file provider, no compose) and the verifier (Wing, a host
daemon) hold it. Every role compose template is RENDERED with the token as a sentinel;
a sentinel in the output is red, a template that does not render is red too.
"""
from __future__ import annotations

from pathlib import Path

from test_docker_sock_only_behind_proxy import _env, _vars

REPO = Path(__file__).resolve().parents[2]
SENTINEL = "SENTINEL-wing-edge-token-0f3a"


def composes() -> list[Path]:
    return sorted(p for p in REPO.glob("roles/pazny.*/templates/**/*.j2") if "compose" in p.name)


def leaks(text: str) -> bool:
    return SENTINEL in _env().from_string(text).render(**{**_vars("Darwin"), "wing_edge_token": SENTINEL})


def test_the_detector_sees_the_measured_shape():
    assert leaks('WING_EDGE_TOKEN: "{{ wing_edge_token | default(\'\') }}"\n')
    assert not leaks('NOS_WING_BFF_TOKEN: "{{ face_bff_wing_api_token }}"\n')
    assert any(p.parent.parent.name == "pazny.face" for p in composes()), "the gate never scans face"


def test_no_compose_renders_the_wing_edge_token():
    bad, blind = [], []
    for path in composes():
        try:
            if leaks(path.read_text(encoding="utf-8")):
                bad.append(str(path.relative_to(REPO)))
        except Exception as e:  # noqa: BLE001
            blind.append(f"{path.relative_to(REPO)}: {e!r}")
    assert not blind, "templates the gate cannot render (blind, not green):\n  " + "\n  ".join(blind)
    assert not bad, ("a container holds Wing's edge token and could forge a Tier-1 identity to Wing's "
                     "pages; talk to /api/v1 with a scoped bearer (face: face-bff):\n  " + "\n  ".join(bad))
