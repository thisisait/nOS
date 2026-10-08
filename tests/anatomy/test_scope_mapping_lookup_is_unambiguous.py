"""Authentik scope mappings are looked up by identity, never by scope_name.

10-oidc-apps.yaml.j2 declares a nOS mapping ("nOS roles") with
``scope_name: profile`` and then attached the stock one with
``!Find [authentik_providers_oauth2.scopemapping, [scope_name, profile]]``.
Two mappings now share that scope_name; the Find resolved to "nOS roles", so
no OIDC provider ever carried the stock profile mapping (preferred_username,
nickname, name). Gitea refused auto-registration ("doesn't return required
fields: nickname") and HedgeDoc 500'd ("id and username are undefined") for
every identity (thisisait/nOS#52).

A scope_name is not an identity. Find stock mappings by ``managed`` and nOS
mappings by ``name``.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
FIND_BY_SCOPE = re.compile(
    r"!Find\s*\[\s*authentik_providers_oauth2\.scopemapping\s*,\s*\[\s*scope_name\s*,"
)


def _blueprints():
    for root in (REPO / "files", REPO / "roles"):
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".j2", ".yaml", ".yml"} and "blueprint" in str(path):
                yield path


def test_blueprints_exist():
    assert any(True for _ in _blueprints()), "gate went blind: no blueprint files found"


def test_no_scope_mapping_is_found_by_scope_name():
    offenders = []
    for path in _blueprints():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FIND_BY_SCOPE.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert not offenders, (
        "scope_name is ambiguous once a nOS mapping shares it — use "
        "[managed, goauthentik.io/providers/oauth2/scope-<x>] or [name, …]:\n  "
        + "\n  ".join(offenders)
    )


#: The tofu path (terraform/authentik) carries the same lookup as data sources.
TF_SCOPE_LOOKUP = re.compile(
    r'data\s+"authentik_property_mapping_provider_scope"\s+"[^"]+"\s*\{[^}]*\bscope_name\s*=',
    re.S,
)


def test_no_tofu_scope_mapping_data_source_is_found_by_scope_name():
    tf_files = sorted((REPO / "terraform").rglob("*.tf"))
    assert tf_files, "gate went blind: no terraform files found"
    offenders = [
        f"{p.relative_to(REPO)}: {m.group(0).splitlines()[0]}"
        for p in tf_files
        for m in TF_SCOPE_LOOKUP.finditer(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "data source looks a scope mapping up by scope_name — ambiguous once "
        "nos_roles shares it; use managed = \"goauthentik.io/providers/oauth2/scope-<x>\":\n  "
        + "\n  ".join(offenders)
    )
