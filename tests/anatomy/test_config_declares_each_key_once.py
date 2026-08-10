"""Anatomy gate: the committed config layer declares every top-level key once.

WHY THIS EXISTS. On 2026-08-10, commit a0b35b50 inserted a comment block above
`nos_retired_services` in default.config.yml and consumed the leading `#` of
the doc line it displaced:

    nos_retired_services: services nOS no longer ships. The render path is

That is a live scalar key, duplicating the real list declaration eleven lines
below. YAML last-wins kept the runtime value correct (still `['puter']`), so
nothing failed at converge — but `yamllint .` errors on key-duplicates and the
CI lint job went red 29 minutes after a commit titled "fix(ci): three jobs red
since 2026-08-08, none of them noticed".

The failure shape is worth a standing gate rather than a one-off fix: a
comment-edit that de-comments a `key:`-shaped line produces a syntactically
valid file whose earlier declaration is silently shadowed. Last-wins was
HARMLESS this time only because the stray key came first. Had the mangled line
landed AFTER the real declaration, the estate's retired-service list would have
become an English sentence and prune-retired.yml would have iterated its words.

This duplicates yamllint's `key-duplicates` check on purpose: the lint job and
the pytest job are separate CI jobs, and the incident proved the lint job's
red can go unwatched. A duplicate key in the config SoT is a pytest-grade
defect, not a style warning.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

# The committed config layer — the two files every install reads. Operator
# overrides (config.yml, credentials.yml) are gitignored and not gated here.
COMMITTED_CONFIG = ("default.config.yml", "default.credentials.yml")


class _DuplicateKey(Exception):
    pass


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of last-wins."""


def _no_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise _DuplicateKey(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1}"
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


@pytest.mark.parametrize("name", COMMITTED_CONFIG)
def test_committed_config_has_no_duplicate_keys(name: str) -> None:
    path = REPO / name
    assert path.is_file(), f"{name} is gone; the config layering starts here"
    try:
        yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except _DuplicateKey as exc:
        pytest.fail(
            f"{name}: {exc}. A duplicated top-level key means one declaration "
            "silently shadows the other (YAML last-wins). The usual cause is a "
            "comment edit that stripped a leading '#' from a 'key:'-shaped doc "
            "line — see commit a0b35b50 for the incident this gate pins."
        )
