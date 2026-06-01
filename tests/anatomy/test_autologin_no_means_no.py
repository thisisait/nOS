"""Anatomy gate — HARD SAFETY: supports:no means NO autologin, ever.

sso-autologin-plan.md §"Testy / gates" (TVRDÁ POJISTKA):

  > plugin s `autologin.supports: no` nesmí mít `enabled` rezolvující na
  > true při ŽÁDNÉ kombinaci svc/min_tier/global override. Projde
  > n8n/hedgedoc/open-webui/firefly/erpnext/jellyfin/freescout(bez modulu)
  > a fail-fastne na jakémkoli flipu.

`supports` carries the upstream truth from research — n8n/hedgedoc/
open-webui/erpnext/jellyfin cannot force-OIDC upstream, so honesty
demands their `enabled` expression resolve to False no matter what the
operator flips (per-service, per-min-tier, or global). This is the gate
that prevents a false promise: a `supports: no` plugin whose `enabled`
could be flipped true would auto-redirect a service that has no working
auto-redirect, hiding a login screen behind a dead OIDC flow.

We render the `enabled` Jinja expression through the SAME path the loader
uses (_render_string → the Ansible-parity filter env with the `bool`
filter) under every override combination, including the canonical
precedence chain (per-svc, per-min-tier, global all turned on at once),
and assert it never resolves truthy.

Batch 0 has no autologin blocks → vacuous pass; starts biting once a
supports:no plugin with a flippable `enabled` lands.
"""

from __future__ import annotations

import itertools
import pathlib
import re

import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

_VAR_RE = re.compile(r"\b(sso_autologin(?:_[a-z0-9_]+)?)\b")
_TRUTHY_VALUES = [True, "true", "yes", "1", "on", "True"]


def _autologin_blocks() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        data = yaml.safe_load(p.read_text())
        a = (data or {}).get("authentik")
        if isinstance(a, dict) and isinstance(a.get("autologin"), dict):
            out.append((p.parent.name, a))
    return out


def _coerce(rendered: str) -> bool:
    # The enabled expr ends with `| bool` → render is "True"/"False".
    # Be defensive: treat any non-bool-ish leftover via the same bool filter.
    s = str(rendered).strip().lower()
    return s in ("true", "yes", "y", "1", "on")


def test_autologin_no_means_no():
    failures: list[str] = []
    blocks = _autologin_blocks()
    for name, authentik in blocks:
        al = authentik["autologin"]
        if al.get("supports") != "no":
            continue
        enabled = al.get("enabled")
        if not isinstance(enabled, str):
            # supports:no with no enabled expr is also fine (defaults false),
            # but if present it MUST be a string we can render.
            continue

        # Collect every sso_autologin* var name the expression references so
        # we can try flipping each (per-svc, per-min-tier, global) to truthy.
        var_names = set(_VAR_RE.findall(enabled))
        # Always include the global + a generic min-tier + the plausible
        # per-service name even if the author hard-coded false, so a future
        # rename can't sneak a flippable path past the gate.
        var_names |= {"sso_autologin"}

        var_list = sorted(var_names)
        # Try the full power set of (var -> each truthy value). For a small
        # number of vars this is cheap and exhaustive; cap to keep it bounded.
        for truthy in _TRUTHY_VALUES:
            # Single-var flips.
            for v in var_list:
                ctx = {v: truthy}
                if _coerce(load_plugins._render_string(enabled, ctx)):
                    failures.append(
                        f"{name}: supports:no but enabled resolved TRUE with "
                        f"{v}={truthy!r} → {enabled!r}")
            # All-on at once (the precedence-chain worst case).
            ctx_all = {v: truthy for v in var_list}
            if _coerce(load_plugins._render_string(enabled, ctx_all)):
                failures.append(
                    f"{name}: supports:no but enabled resolved TRUE with ALL "
                    f"overrides={truthy!r} → {enabled!r}")
            # Pairwise combos (catches an OR across two vars).
            for combo in itertools.combinations(var_list, 2):
                ctx_pair = {v: truthy for v in combo}
                if _coerce(load_plugins._render_string(enabled, ctx_pair)):
                    failures.append(
                        f"{name}: supports:no but enabled resolved TRUE with "
                        f"{combo}={truthy!r} → {enabled!r}")

    assert not failures, (
        "HARD SAFETY VIOLATION — a supports:no service can be flipped to "
        "autologin enabled:\n" + "\n".join(f"  {f}" for f in failures))
