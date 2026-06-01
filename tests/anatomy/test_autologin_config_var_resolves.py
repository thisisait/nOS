"""Anatomy gate — every autologin.enabled expr is `| bool`-terminated and
resolves to a real bool.

sso-autologin-plan.md §"Globální mechanismus" + §"Testy / gates":

  > `enabled` je vždy Jinja string … zakončený `| bool`. Důvod `| bool`:
  > `_deep_render` vrací string; bez explicitní koerce by `"false"`
  > (neprázdný string) Jinja vyhodnotila jako truthy → tiché selhání.

The loader's `_deep_render` (load_plugins.py:232) pre-renders harvested
Jinja into strings. A bare boolean expression would land in the blueprint
as the literal string "false" — which is truthy. The trailing `| bool`
coerces "true"/"false"/"yes"/"no" to a real bool BEFORE the blueprint
consumes it. This gate pins both halves:

  1. Every `autologin.enabled` string ends with `| bool`.
  2. Rendering it through the loader's Jinja path yields a clean
     bool-ish "True"/"False" for true/false/yes/no global inputs (no typo,
     no loose-string truthiness leak).

Batch 0: no autologin blocks → vacuous pass.
"""

from __future__ import annotations

import pathlib

import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

# global-flag values → expected coerced result (the | bool render output).
_GLOBAL_INPUTS = {
    True: "True",
    False: "False",
    "true": "True",
    "false": "False",
    "yes": "True",
    "no": "False",
}


def _autologin_enableds() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        data = yaml.safe_load(p.read_text())
        a = (data or {}).get("authentik")
        if not isinstance(a, dict):
            continue
        al = a.get("autologin")
        if isinstance(al, dict) and isinstance(al.get("enabled"), str):
            out.append((p.parent.name, al["enabled"]))
    return out


def test_autologin_enabled_ends_with_bool_filter():
    failures: list[str] = []
    for name, expr in _autologin_enableds():
        # Strip the surrounding {{ }} and whitespace, assert the last filter
        # in the pipeline is `bool`.
        inner = expr.strip()
        if inner.startswith("{{") and inner.endswith("}}"):
            inner = inner[2:-2].strip()
        # last pipe segment
        last = inner.rsplit("|", 1)[-1].strip()
        if last != "bool":
            failures.append(f"{name}: enabled does not end with `| bool`: {expr!r}")
    assert not failures, (
        "autologin.enabled exprs missing mandatory `| bool` coercion:\n"
        + "\n".join(f"  {f}" for f in failures))


def test_autologin_enabled_resolves_to_bool():
    failures: list[str] = []
    for name, expr in _autologin_enableds():
        for global_val, expected in _GLOBAL_INPUTS.items():
            rendered = load_plugins._render_string(expr, {"sso_autologin": global_val})
            if str(rendered).strip() not in ("True", "False"):
                failures.append(
                    f"{name}: enabled did not render to a clean bool with "
                    f"sso_autologin={global_val!r} → {rendered!r} ({expr!r})")
    assert not failures, (
        "autologin.enabled exprs did not resolve to a real bool:\n"
        + "\n".join(f"  {f}" for f in failures))
