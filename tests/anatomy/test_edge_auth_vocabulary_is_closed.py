"""Anatomy gate: an edge-auth mode the template does not understand is an OPEN route.

`roles/pazny.traefik/templates/dynamic/services.yml.j2:81` decides the whole
thing with one comparison:

    {% if _auth == 'proxy' %}   middlewares: [authentik@file, ...]
    {% else %}                  middlewares: [                ...]

So `proxy` gates and EVERYTHING ELSE does not — `oidc` deliberately, `none`
deliberately, and a typo silently. There is no error branch, because a template
cannot tell a considered `oidc` from a fat-fingered `porxy`.

MEASURED 2026-08-11, on this file's author. Closing REM-192 meant flipping
FreeScout's edge to gated, and the first edit wrote `forward_auth` — the word
the DOCTRINE uses, and the word the plugin's own `authentik.mode` field takes.
The map's vocabulary is `proxy|oidc|none`. The value would have fallen through
the `{% else %}`, leaving the route ungated while the plugin, the tofu registry,
the queue row and the commit message all said it was gated. Four documents
agreeing with each other and none of them agreeing with Traefik.

`test_access_facet_reconciled.py` caught it that time, but indirectly — by
noticing an unattached provider. This gate names the actual rule, so the next
person gets told what is wrong rather than what it caused.

WHAT THIS CANNOT DO: verify that a service marked `oidc` really offers
Authentik on its login page. That is a live fact about a running service and it
belongs in `tools/discovery-scan.py` (probe F). Shape here, effect there.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
VARS = REPO / "roles/pazny.traefik/vars/main.yml"
TEMPLATE = REPO / "roles/pazny.traefik/templates/dynamic/services.yml.j2"


@pytest.fixture(scope="module")
def modes() -> dict[str, str]:
    data = yaml.safe_load(VARS.read_text(encoding="utf-8")) or {}
    return data.get("traefik_auth_modes") or {}


def _template_vocabulary() -> set[str]:
    """The values the TEMPLATE actually branches on — derived, not restated.

    A hard-coded {'proxy','oidc','none'} here would be a second declaration of
    the same law, and the one that goes stale when the template grows a third
    branch. So the accepted set is: whatever the template compares `_auth`
    against, plus its own `.get(id, DEFAULT)` fallback.
    """
    text = TEMPLATE.read_text(encoding="utf-8")
    compared = set(re.findall(r"_auth\s*==\s*'([a-z_]+)'", text))
    fallback = set(re.findall(r"traefik_auth_modes\.get\([^,]+,\s*'([a-z_]+)'\)", text))
    return compared | fallback


def test_the_template_still_decides_with_a_comparison() -> None:
    """Guard the guard: if the branch changed shape, the derivation is blind."""
    vocab = _template_vocabulary()
    assert "proxy" in vocab, (
        "the template no longer compares _auth against 'proxy'. Re-read "
        f"{TEMPLATE.relative_to(REPO)} — this gate derives the legal vocabulary "
        "from that comparison and has just gone blind."
    )


def test_every_declared_mode_is_one_the_template_understands(modes) -> None:
    vocab = _template_vocabulary()
    # `oidc` and `none` never reach a comparison — they are the {% else %} — so
    # they are legal by intent rather than by syntax, and named here for that
    # reason. Anything ELSE outside the template's vocabulary is a typo that
    # renders as "ungated" with no warning anywhere.
    intentional_else = {"oidc", "none"}
    legal = vocab | intentional_else

    strays = {sid: mode for sid, mode in modes.items() if mode not in legal}
    assert not strays, (
        "traefik_auth_modes carries value(s) the template does not understand: "
        f"{strays}. The template gates on `_auth == 'proxy'` and sends every "
        f"other value down the ungated branch, so these routes are OPEN while "
        f"the declaration says otherwise. Legal: {sorted(legal)}.\n"
        "This is exactly how REM-192's fix was nearly shipped ungated: the "
        "doctrine word is `forward_auth`, this map's word is `proxy`."
    )


def test_the_doctrine_word_is_never_used_here(modes) -> None:
    """The specific confusion, pinned by name.

    `forward_auth` is correct in `plugin.yml`'s `authentik.mode` and in every
    document. It is WRONG here, and wrong in the direction that opens a route.
    Worth its own assertion so the failure message says the word out loud.
    """
    offenders = [sid for sid, mode in modes.items() if mode in ("forward_auth", "forwardauth")]
    assert not offenders, (
        f"{offenders} use `forward_auth` in traefik_auth_modes. That is the "
        "plugin/doctrine spelling; this map's equivalent is `proxy`. The "
        "template does not recognise it and the route renders WITHOUT "
        "authentik@file — ungated, while four other files say it is gated."
    )


def test_the_gated_value_actually_attaches_authentik(modes) -> None:
    """`proxy` must still be the value that pulls in the middleware."""
    text = TEMPLATE.read_text(encoding="utf-8")
    branch = text[text.index("{% if _auth == 'proxy' %}"):]
    head = branch[: branch.index("{% else %}")]
    assert "authentik@file" in head, (
        "the `proxy` branch no longer attaches authentik@file. Every service "
        f"marked proxy ({sum(1 for m in modes.values() if m == 'proxy')} of them) "
        "would be silently ungated."
    )
    tail = branch[branch.index("{% else %}"):]
    assert "authentik@file" not in tail[: tail.index("{% endif %}")], (
        "the non-proxy branch now attaches authentik@file too, which would "
        "stack forward-auth on native_oidc services — the documented "
        "double-login anti-pattern (see test_forward_auth_does_not_stack.py)."
    )
