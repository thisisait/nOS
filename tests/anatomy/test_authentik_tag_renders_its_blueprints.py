"""`--tags authentik` renders every blueprint it applies and verifies.

2026-11-10: `nos --tags ...,authentik` applied and verified 47-estate-brand, but the
blueprints are plugin renders (authentik-base) done by the loader's pre_compose hook,
tagged `anatomy` only, so the file was never written and the verify went red on a
converged estate. The walk is test_a_declared_tag_can_be_reached's own.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_tag_walk", Path(__file__).with_name("test_a_declared_tag_can_be_reached.py"))
_walk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_walk)

LOADER = ("tasks/stacks/core-up.yml", "[Core] Plugin loader — pre_compose hook")


def test_the_authentik_tag_reaches_the_plugin_render():
    alive = _walk._analyse().alive
    assert (*LOADER, "authentik") in alive, (
        "--tags authentik does not run the plugin loader's pre_compose hook, so the "
        "authentik-base blueprints it applies are never rendered")


def test_every_applied_blueprint_has_a_template():
    handler = (REPO / "roles/pazny.authentik/handlers/main.yml").read_text(encoding="utf-8")
    names = set(re.findall(r"\b(\d\d-[a-z0-9-]+)\b", handler.split("for bp in", 1)[1].split("; do", 1)[0]))
    homes = [REPO / "files/anatomy/plugins/authentik-base/blueprints", REPO / "roles/pazny.authentik/templates/blueprints"]
    missing = sorted(n for n in names if not any((h / f"{n}.yaml.j2").is_file() for h in homes))
    assert names and not missing, f"the apply handler names blueprints no template renders: {missing}"
