"""Anatomy gate: every lazy-regenerate guard must be able to fire.

MEASURED 2026-08-11. A new credential was declared as
`placeholder-regenerated-on-first-run` and given a regeneration guard modelled on
its neighbours — except one clause short:

    {% if '_pw_' in (x) or (x | length) < 32 %}  {{ openssl rand -hex 32 }}  {% else %}  {{ x }}

The placeholder is 36 characters and contains no `_pw_`. Both tests passed, the
`{% else %}` branch ran, and the literal string `placeholder-regenerated-on-first-run`
was written into `api_tokens` as a live bearer. A chain authenticated with the
word "placeholder" executed against the taxonomy and returned rows.

WHAT MAKES THIS WORTH A GATE RATHER THAN A FIX. Nothing failed. The token
worked, the converge was green, the smoke passed, and the only symptom was a
length nobody had a reason to look at. Every sibling line in that block tests for
`'placeholder' in …`; this one omitted it, and the omission was invisible
precisely because the credential functioned.

WHAT IS PINNED. Any variable whose committed default announces itself as a
placeholder must have a regeneration guard that TESTS for that word. Length and
`_pw_` are not enough: a placeholder long enough to look like a secret is exactly
the case that slips through, and "make the placeholder short" is a fix that
depends on the next author choosing a short one.

WHAT THIS CANNOT DO: prove the regenerated value ever reaches the service that
uses it. That is `--tags verify`'s job and, for this one, the live 401 the old
placeholder now receives.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CREDS = REPO / "default.credentials.yml"
PLAYBOOK = REPO / "main.yml"

PLACEHOLDER = "placeholder"


def _declared_placeholders() -> dict[str, str]:
    """Committed defaults that call themselves placeholders."""
    data = yaml.safe_load(CREDS.read_text(encoding="utf-8")) or {}
    return {
        k: v for k, v in data.items()
        if isinstance(v, str) and PLACEHOLDER in v.lower()
    }


def _guard_for(var: str) -> str | None:
    """The lazy-regenerate expression for this variable, if main.yml has one."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    m = re.search(rf"^\s*{re.escape(var)}:\s*\"(\{{%.*?)\"\s*$", text, re.M)
    return m.group(1) if m else None


def test_there_are_placeholders_to_check() -> None:
    """Guard the guard: an empty subject set would make every test below vacuous."""
    found = _declared_placeholders()
    assert found, (
        "no committed default announces itself as a placeholder any more. Either "
        "every secret is now generated at declaration time (excellent — delete "
        "this gate) or the naming convention changed and this gate has gone blind."
    )


@pytest.mark.parametrize("var", sorted(_declared_placeholders()))
def test_a_placeholder_default_has_a_guard_that_tests_for_it(var: str) -> None:
    guard = _guard_for(var)
    assert guard is not None, (
        f"{var} is declared as a placeholder in default.credentials.yml and has "
        "no lazy-regenerate expression in main.yml. The placeholder is what the "
        "estate will use."
    )
    assert PLACEHOLDER in guard, (
        f"{var}'s regeneration guard does not test for the word "
        f"'{PLACEHOLDER}':\n\n  {guard[:200]}\n\n"
        "Length and `_pw_` tests are not enough — a placeholder long enough to "
        "look like a secret passes both and is used verbatim. That is measured, "
        "not hypothetical: cortex_executor_token shipped as the literal string "
        "`placeholder-regenerated-on-first-run` and authenticated real chains."
    )


def test_the_regeneration_actually_produces_entropy() -> None:
    """A guard that fires into another constant would be the same defect twice."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    for var in _declared_placeholders():
        guard = _guard_for(var)
        if guard is None:
            continue                                    # covered by the test above
        assert "openssl rand" in guard or "lookup(" in guard, (
            f"{var}'s guard fires but does not generate anything random:\n  {guard[:200]}"
        )
