"""An authentik blueprint must render an `entries` LIST, never a bare key.

WHAT IT COST. Measured on the live estate 2026-08-31:
`authentik_blueprints_blueprintinstance` held `custom/50-mfa-policy.yaml` at
`status = 'error'`, and had done since the row was written. The cause is not a
typo — it is a shape. With `enforce_mfa: false` (the default, and correct for
every non-gov install) the template rendered

    entries:

with nothing under it. YAML loads that as `None`, and authentik's
`Importer.from_string` raises `EntryInvalidError` on a non-list rather than
treating it as empty. The file's own header called this a "harmless no-op". It
was not a no-op; it was a failed import.

WHY IT MATTERS MORE THAN ONE BLUEPRINT. The estate cannot tell this apart from
a real blueprint failure — same table, same status, same colour. A permanent
red for a feature that is deliberately off is the exact thing that teaches an
operator to stop reading a status column, and then the next red is invisible
too. It is the same defect the Prometheus scrape targets carried
(prometheus.yml.j2: "a standing false positive is not monitoring").

WHAT THIS CHECKS. It RENDERS each template — with every gating flag off, which
is the state that produced the defect — and asserts the result parses and its
`entries` is a list. Grepping for `entries: []` would pass a template whose
`{% if %}` never reaches that branch, and the whole point is that the empty
branch is the one nobody exercises.
"""

from __future__ import annotations

import pathlib
import sys

import jinja2
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "files/anatomy"))
from module_utils.load_plugins import _jinja_env  # noqa: E402  the loader's own env
BLUEPRINTS = ROOT / "files/anatomy/plugins/authentik-base/blueprints"

#: The flags these templates gate on, at their emptiest — the state that
#: produced the live failure. Everything NOT named here resolves to
#: ChainableUndefined below, which is the honest default: a variable the play
#: does not set is exactly what an unconfigured estate has.
EMPTY_CONTEXT = {
    "enforce_mfa": False,
    "_all_clients": [],
    "authentik_rbac_tiers": {},
    "authentik_app_tiers": {},
    "authentik_agent_clients": [],
}


class _AuthentikTags(yaml.SafeLoader):
    """SafeLoader that tolerates authentik's blueprint tags.

    Blueprints carry `!Find`, `!KeyOf`, `!Env`, `!Format` and friends — custom
    tags resolved by authentik's own loader, meaningless here. This gate is
    about the SHAPE of `entries`, so an unknown tag becomes None rather than a
    parse error that would mask the thing being checked.
    """


_AuthentikTags.add_multi_constructor("!", lambda loader, suffix, node: None)


class _Placeholder(jinja2.ChainableUndefined):
    """An unset variable renders as a token, not as nothing.

    ChainableUndefined stringifies to `""`, which turns `name: {{ unset }}`
    into `name:` — a YAML mapping to null, or worse a parse error two lines
    on. The gate would then fail on its own synthetic context instead of on
    the defect. A non-empty token keeps the document well-formed so the only
    thing left to fail is the `entries` shape.
    """

    def __str__(self) -> str:  # noqa: D105
        return "unset"


def _templates() -> list[pathlib.Path]:
    return sorted(BLUEPRINTS.glob("*.yaml.j2"))


def test_the_blueprint_dir_is_where_this_gate_thinks() -> None:
    assert _templates(), (
        f"no *.yaml.j2 under {BLUEPRINTS.relative_to(ROOT)} — the templates moved "
        "and this gate is now guarding an empty directory")


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_entries_is_a_list_with_every_flag_off(template: pathlib.Path) -> None:
    # The plugin loader's env, not a bare one: these templates use the ansible
    # filter set (`| bool`, `| to_json`, …) that `_register_ansible_filters`
    # installs, and a bare Environment fails on the filter rather than on the
    # defect this gate is about.
    env = _jinja_env()
    env.undefined = _Placeholder
    try:
        rendered = env.from_string(template.read_text(encoding="utf-8")).render(EMPTY_CONTEXT)
    except jinja2.TemplateError as exc:
        pytest.fail(f"{template.name} does not render with every flag off: {exc}")

    try:
        doc = yaml.load(rendered, Loader=_AuthentikTags)
    except yaml.YAMLError as exc:
        pytest.fail(f"{template.name} renders invalid YAML with every flag off: {exc}")

    assert isinstance(doc, dict), f"{template.name} renders {type(doc).__name__}, not a mapping"
    entries = doc.get("entries", "MISSING")
    assert isinstance(entries, list), (
        f"{template.name} renders `entries` as {type(entries).__name__} with every "
        "flag off. authentik's Importer.from_string raises EntryInvalidError on "
        "anything but a list, so the blueprint instance sits at status='error' "
        "forever — a standing red for a feature that is deliberately switched "
        "off. Render `entries: []` in the else branch."
    )


#: The same templates with their sources POPULATED. Without this half, wrapping
#: every blueprint in `{% if false %}...{% else %}entries: []` would pass the
#: gate above while shipping an estate that provisions nothing at all.
POPULATED_CONTEXT = dict(
    EMPTY_CONTEXT,
    enforce_mfa=True,
    # `_all_clients` is COMPUTED inside 10-oidc-apps from these two, and only
    # when the engine is not tofu — passing `_all_clients` directly would be
    # overwritten by the template's own `{% set %}` and prove nothing.
    authentik_engine="blueprint",
    inputs={"clients": [{"slug": "demo", "name": "Demo", "client_id": "cid",
                         "client_secret": "sec", "redirect_uris": ["https://demo/"],
                         "tier": 3, "mode": "native_oidc"}]},
    authentik_oidc_apps=[],
    authentik_rbac_tiers={"1": {"group": "nos-admins"}},
    authentik_agent_clients=[{"name": "conductor", "client_id": "agent-conductor",
                              "client_secret": "sec", "scopes": ["read"]}],
    authentik_agent_scopes=[{"name": "read", "scope_name": "nos.read",
                             "description": "read", "expression": "return {}"}],
)


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_entries_is_still_populated_when_the_sources_are(template: pathlib.Path) -> None:
    env = _jinja_env()
    env.undefined = _Placeholder
    rendered = env.from_string(template.read_text(encoding="utf-8")).render(POPULATED_CONTEXT)
    doc = yaml.load(rendered, Loader=_AuthentikTags)
    entries = doc.get("entries", "MISSING")
    assert isinstance(entries, list), (
        f"{template.name} renders `entries` as {type(entries).__name__} even with "
        "its sources populated")
    assert entries, (
        f"{template.name} renders an EMPTY entries list with every source "
        "populated — the empty-branch guard is swallowing the real content, so "
        "this blueprint would provision nothing on a live estate")
