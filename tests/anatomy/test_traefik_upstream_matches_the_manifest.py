"""The Traefik upstream's compose alias is the manifest row, not a second copy.

`services.yml.j2` renders `{{ _cu.svc | default(id|replace('_','-')) }}:{{ port }}`,
and `traefik_container_upstreams` carried a hand-maintained `svc:` exception
table. MEASURED 2026-09-01: 5 of its 9 overrides (`open-webui`, `uptime-kuma`,
`calibre-web`, `qgis-server`, `code-server`) were byte-identical to the default
— a second spelling of a fact the manifest already holds.

The manifest holds it as `container_name`: `iiab-tileserver-1` minus the
`<stack>-` prefix and the `-N` suffix IS the compose service name Traefik dials.
A stale `svc:` here is a 502 with nothing joining the two files.

CEILING: only the 7 rows carrying a single `container_name` are checkable.
`woodpecker`/`authentik` are multi-container (`container_names`) — no single
answer to derive, so their overrides stay hand-written and unchecked.

Retro-verified 2026-09-01: `offline_maps: { svc: tileserver }` → `{ }` makes the
effective svc `offline-maps` while the row says `tileserver`; RED.
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

TRAEFIK_VARS = REPO / "roles/pazny.traefik/vars/main.yml"


def _upstreams() -> dict:
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", TRAEFIK_VARS.read_text(encoding="utf-8"))
    return (yaml.safe_load(raw) or {}).get("traefik_container_upstreams") or {}


def _compose_service_name(row: dict) -> str | None:
    """`<stack>-<compose service>-<n>` → the compose service. None if unknowable."""
    cn = row.get("container_name")
    if not cn:
        return None
    m = re.fullmatch(rf"(?:{re.escape(row.get('stack', ''))}-)?(.+?)(?:-\d+)?", cn)
    return m.group(1) if m else None


def test_every_derivable_upstream_agrees_with_its_row() -> None:
    rows = {s["id"]: s for s in ni.services()}
    checked, wrong = 0, []
    for sid, up in _upstreams().items():
        row = rows.get(sid)
        assert row is not None, f"traefik_container_upstreams.{sid} is not a manifest id"
        derived = _compose_service_name(row)
        if derived is None:
            continue
        checked += 1
        effective = up.get("svc", sid.replace("_", "-"))
        if effective != derived:
            wrong.append(f"{sid}: dials {effective!r}, row says {derived!r} ({row['container_name']})")
    assert not wrong, (
        "the Traefik upstream alias disagrees with the manifest container_name — "
        "one of the two is stale and the render is a 502:\n  " + "\n  ".join(wrong))
    assert checked >= 7, f"only {checked} rows carry a container_name — coverage shrank"
