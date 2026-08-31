"""A routed service names its edge mode; it does not inherit one.

`dynamic/services.yml.j2` renders `traefik_auth_modes.get(s.id, 'proxy')`. An id
nobody lists is therefore GATED — the safe direction, and the reason the three
services found this way had never been exposed. But a default is not a decision,
and CLAUDE.md already names this as the silent path: "`traefik_auth_modes` falls
through to `proxy` for an id nobody listed".

MEASURED 2026-08-31: 46 routed, non-skipped manifest services; 43 listed;
`snappymail`, `smtp_stalwart` and `backrest` inheriting.

WHY IT IS A WIRING DEFECT AND NOT A TIDINESS ONE. In all three cases the intent
was already written down — in the plugin manifest. snappymail's says "no native
OIDC support — Authentik gates access at the proxy layer"; smtp-stalwart's
explains that mail speaks SASL and declares no authentik block on purpose;
backrest's carries a full `authentik: mode: forward_auth` block. The renderer
reads `roles/pazny.traefik/vars/main.yml` and none of that. Two files, one
question, nothing joining them — so the estate had the answer three times and
used a default instead.

BACKREST IS WHY THE DIRECTION MATTERS. Its own auth is disabled
(`sec-backrest-auth`: `POST /v1.Backrest/GetConfig` from inside
`devops-gitea-1` answered 200, `auth:disabled`). Until that row closes, this
middleware is the only thing in front of it — and it was being supplied by a
line nobody had written.

THIS GATE DOES NOT JUDGE THE MODE. `test_access_facet_reconciled.py` decides
whether a mode is *right* and knows the default means gated. This one asks only
that a human chose it.

Retro-verified 2026-08-31 by removing the three entries.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TRAEFIK_VARS = REPO / "roles/pazny.traefik/vars/main.yml"
MANIFEST = REPO / "state/manifest.yml"


def _vars() -> dict:
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", TRAEFIK_VARS.read_text(encoding="utf-8"))
    return yaml.safe_load(raw) or {}


def _routed_ids() -> list[str]:
    v = _vars()
    skipped = set(v.get("traefik_skip_ids") or [])
    services = (yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {})["services"]
    return [s["id"] for s in services
            if s.get("domain_var") and s["id"] not in skipped]


def test_every_routed_service_names_its_mode() -> None:
    modes = _vars().get("traefik_auth_modes") or {}
    inheriting = [i for i in _routed_ids() if i not in modes]
    assert not inheriting, (
        "these routed services have no entry in traefik_auth_modes, so the "
        "renderer's `.get(id, 'proxy')` decides for them. That is the safe "
        "direction and it is still not a decision — and for backrest, whose own "
        "auth is disabled, the inherited middleware is the only gate there is:\n  "
        + "\n  ".join(inheriting))


def test_the_gate_has_a_population() -> None:
    """Guard against the vacuous pass: a manifest or vars parse that silently
    yields nothing would make the assertion above trivially true."""
    routed, modes = _routed_ids(), (_vars().get("traefik_auth_modes") or {})
    assert len(routed) >= 40, f"only {len(routed)} routed services parsed — check the reader"
    assert len(modes) >= 40, f"only {len(modes)} auth modes parsed — check the reader"


def test_the_default_is_still_the_gated_one() -> None:
    """If the template's fallback ever became `none`, every unlisted id would go
    from gated to open and this file's premise would invert. Read from the
    template, not restated."""
    tpl = (REPO / "roles/pazny.traefik/templates/dynamic/services.yml.j2")
    if not tpl.is_file():
        tpl = next(REPO.glob("roles/pazny.traefik/templates/**/services.yml.j2"), None)
        assert tpl is not None, "services.yml.j2 not found — the premise is unreadable"
    body = tpl.read_text(encoding="utf-8")
    found = re.search(r"traefik_auth_modes.*?\|\s*default\(\s*'([a-z]+)'\s*\)", body, re.S) \
        or re.search(r"traefik_auth_modes\.get\(\s*[^,]+,\s*'([a-z]+)'\s*\)", body)
    assert found, "cannot find the fallback in services.yml.j2 — read it by hand"
    assert found.group(1) == "proxy", (
        f"the renderer's fallback is now {found.group(1)!r}; an unlisted id would "
        "no longer be gated, which inverts everything this file assumes")
