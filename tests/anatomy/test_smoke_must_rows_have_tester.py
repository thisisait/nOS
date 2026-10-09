"""Anatomy CI gate — a release MUST with SSO has a `tester` smoke row.

v0.16 MUST (3) is "forum SSO works" (roadmap row rel-016). Until 2026-10-09 the
only evidence was three plugin e2e probes that need tester tokens; the reader
that owns end-to-end truth, `tools/nos-smoke.py --strict`, knew nos-forum only
as the manifest baseline GET / — a 302 to Authentik would have passed it in
legacy mode and said nothing about the login landing. A MUST whose proof lives
outside the strict smoke is a MUST the release gate never reads.

The list is explicit on purpose: one row per release MUST that names SSO, not
a sweep over every `oidc:` service (that would go red on ~40 rows nobody
promised for this release). Add an id when a release promises its SSO.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402

#: manifest id -> why. rel-016 MUST (3): "forum SSO works".
MUST_HAVE_TESTER_ROW = {"nos_forum": "rel-016 MUST (3): forum SSO works"}


def _smoke():
    spec = importlib.util.spec_from_file_location("_smoke", REPO / "tools" / "nos-smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rendered_catalog(service: dict) -> list[dict]:
    """Render the catalog the way the runner does, with the service on."""
    smoke = _smoke()
    catalog = yaml.safe_load((REPO / "state" / "smoke-catalog.yml").read_text(encoding="utf-8"))
    defaults = catalog.get("smoke_defaults") or {}
    domain = f"{service['id'].replace('_', '-')}.test.local"
    vars_dict = {
        "tenant_domain": "test.local",
        service["install_flag"]: True,
        service["domain_var"]: domain,
    }
    manifest = {"services": [service]}
    rows = smoke.merge_catalog(
        smoke.derive_from_manifest(manifest, vars_dict, defaults),
        catalog.get("smoke_endpoints") or [],
        defaults,
        vars_dict,
    )
    return [r for r in rows if domain in r["url"]]


def test_every_sso_must_has_a_tester_row():
    services = {s["id"]: s for s in nos_identity.services()}
    for sid, why in MUST_HAVE_TESTER_ROW.items():
        row = services[sid]
        assert row.get("oidc", "none") != "none", (
            f"{sid} is listed as an SSO MUST ({why}) but its manifest row has no oidc mode")
        rows = _rendered_catalog(row)
        tester = [r for r in rows if r.get("auth") == "tester" and r.get("_source") == "catalog"]
        assert tester, (
            f"{sid}: {why} — but state/smoke-catalog.yml has no `auth: tester` row for it; "
            f"nos-smoke --strict reads only {[r['id'] for r in rows]} and cannot judge the login landing")
        for r in tester:
            strict = r.get("expect_strict") or r.get("expect")
            assert strict and all(c in (200, 204) for c in strict), (
                f"{r['id']}: a tester row that accepts {strict} in strict mode never "
                "needs the login to land — declare expect_strict: [200]")
