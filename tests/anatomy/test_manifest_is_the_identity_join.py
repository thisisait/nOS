"""The manifest row carries the flag -> fragment hop, so nobody guesses it.

MEASURED 2026-09-01. `filter_plugins/nos_prune_guard.py::_sep_insensitive`
derives the compose fragment from the flag suffix. `install_calibreweb` ->
`calibreweb` cannot match `calibre-web.yml`; `install_openwebui` cannot match
`open-webui.yml`; and no separator rule whatever gets from `offline_maps` to
`tileserver.yml`. Those three fragments are unreachable from their flags.

This gate asserts the reader answers, and that the answer REACHES the fragment
through the real prune planner — not that the manifest contains a string.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))

from filter_plugins.nos_prune_guard import nos_prune_plan  # noqa: E402
from nos_identity import by_flag, fragment_path, fragment_stem  # noqa: E402

#: flag -> fragment stem. The three the guess cannot reach, plus one it can,
#: so a reader that returned a constant would still fail.
UNREACHABLE_BY_GUESS = {
    "install_calibreweb": "calibre-web",
    "install_openwebui": "open-webui",
    "install_offline_maps": "tileserver",
    "install_gitea": "gitea",
}


def test_the_reader_returns_the_fragment_stem():
    for flag, stem in UNREACHABLE_BY_GUESS.items():
        row = by_flag(flag)
        assert row is not None, f"{flag} has no manifest row"
        assert fragment_stem(row) == stem, f"{flag} -> {fragment_stem(row)} != {stem}"


def _rendered_fragments() -> dict[str, list[str]]:
    """Every fragment a role actually renders, from the parsed role tasks.

    The `dest:` of each template task, not a grep of it — the stack and the
    stem are literal inside the Jinja. Feeding the planner THIS (rather than a
    path built from the same stem it is testing) is what stops the assert from
    being a tautology.
    """
    out: dict[str, list[str]] = {}
    for path in sorted(REPO.glob("roles/pazny.*/tasks/*.yml")):
        for task in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            dest = (task.get("template") or task.get("ansible.builtin.template") or {})
            dest = dest.get("dest", "") if isinstance(dest, dict) else ""
            if "/overrides/" not in dest or not dest.endswith(".yml"):
                continue
            stack, stem = dest.split("/overrides/")
            out[f"{stack.rsplit('/', 1)[-1]}/overrides/{stem}"] = [stem[:-4]]
    return out


def test_the_stem_reaches_a_prune_plan():
    rendered = _rendered_fragments()
    for flag in UNREACHABLE_BY_GUESS:
        row = by_flag(flag)
        stem, path = fragment_stem(row), fragment_path(row)
        # The FLAG SUFFIX is what prune-disabled.yml passes — feeding the stem
        # here would let the separator guess answer and prove nothing.
        svc = flag[len("install_"):]
        plan = nos_prune_plan(
            disabled=[svc],
            on_disk_flags={flag: False},
            overrides=rendered,
            containers=[f"{row['stack']}-{stem}-1"],
        )
        assert plan["fragments"] == [path], f"{flag} -> {stem}: {plan['fragments']}"
        assert plan["containers"] == [f"{row['stack']}-{stem}-1"], f"{flag}: {plan}"


def test_a_service_with_no_fragment_of_its_own_says_so():
    # Tier-2 apps merge into apps/overrides/auto.yml; a stem here would name a
    # file that never exists, and a prune keyed on it would silently do nothing.
    assert fragment_stem(by_flag("install_qdrant")) is None
    assert fragment_path(by_flag("install_qdrant")) is None
