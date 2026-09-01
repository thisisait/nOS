"""Anatomy CI gate — a retention window declared as a var must reach the artifact.

`loki_retention` and `tempo_retention` were declared in FOUR places each
(default.config.yml, the role defaults, both role READMEs, plus a row in
docs/systems/*/README.md claiming the value) and consumed in ZERO. Both
provisioning templates hardcoded the number:

    retention_period: 744h   # 31 days
    block_retention: 168h    # 7 days

So an operator who set `loki_retention: "2160h"` in config.yml got a converge
that reported changed, a doc table that agreed with them, and a Loki that kept
deleting at 31 days. The var was documentation of a constant, not a control.

The gate RENDERS each template with a distinctive value and asserts that value
lands in the parsed YAML at the key it is supposed to steer. A hardcoded
literal fails it — that is the state this was written against.
"""

from __future__ import annotations

import pathlib

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

# template, var name, sentinel value, path into the parsed YAML
CASES = [
    (
        PLUGINS / "loki-base" / "provisioning" / "local-config.yaml.j2",
        "loki_retention",
        "2160h",
        ("limits_config", "retention_period"),
    ),
    (
        PLUGINS / "tempo-base" / "provisioning" / "tempo.yaml.j2",
        "tempo_retention",
        "336h",
        ("compactor", "compaction", "block_retention"),
    ),
]


def _render(path: pathlib.Path, **extra) -> dict:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    rendered = env.from_string(path.read_text()).render(**extra)
    return yaml.safe_load(rendered)


@pytest.mark.parametrize("path,var,sentinel,keys", CASES, ids=lambda v: getattr(v, "name", None))
def test_the_var_steers_the_rendered_window(path, var, sentinel, keys):
    doc = _render(path, **{var: sentinel})
    node = doc
    for key in keys:
        assert key in node, f"{path.name}: missing {'.'.join(keys)}"
        node = node[key]
    assert str(node) == sentinel, (
        f"{path.name} renders {'.'.join(keys)}={node!r} while {var}={sentinel!r} — "
        f"the variable does not reach the config."
    )


@pytest.mark.parametrize("path,var,sentinel,keys", CASES, ids=lambda v: getattr(v, "name", None))
def test_the_default_survives_an_undefined_var(path, var, sentinel, keys):
    """The templates also render outside a play (docs tooling, this gate) — an
    undefined var must fall back, not emit an empty scalar."""
    doc = _render(path)
    node = doc
    for key in keys:
        node = node[key]
    assert node, f"{path.name}: {'.'.join(keys)} renders empty when {var} is undefined"
