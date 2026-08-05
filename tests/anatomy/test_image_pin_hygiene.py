"""Anatomy CI gate — image-pin hygiene (supply-chain reproducibility).

C1 (2026-05-25) pinned every floating Docker tag to a fixed version. This gate
stops the drift coming back: no version declaration may carry a floating image
tag (latest/main/master/stable/edge/nightly/develop) unless it is in EXCEPTIONS
with a documented reason.

IT READ THE WRONG FILE UNTIL 2026-08-05, and the miss was live. The scan covered
`roles/pazny.*/defaults/main.yml` only — the layer `default.config.yml` OUTRANKS.
So `qgis_version` passed on the role default's `LTR` while the config declared
`latest`, and `docker ps` showed `kartoza/qgis-server:latest` running. The gate
certified a pin the estate was not using, by reading the copy that could not win.
`face_version: latest` was invisible for the same reason.

The 38 shadowed pins were deleted the same day (`test_a_pin_is_declared_once`),
which is what makes this fixable rather than a second allowlist: there is now one
declaration per pin, and BOTH files are scanned so a pin declared in either place
is seen. Scanning only one of two files is how a gate loses scope silently — the
same shape as a ratchet that stops being re-measured.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

FLOATING = {"latest", "main", "master", "stable", "edge", "nightly", "develop"}
VERSION_KEY_SUFFIXES = ("_version", "_image_version", "_tag")

# (source, var) -> reason. `source` is the role name, or "default.config.yml"
# for a pin declared there. Each is a DELIBERATE non-pin, not drift.
EXCEPTIONS = {
    # Moved here with the pin itself when the 38 shadows were deleted.
    ("default.config.yml", "dotfiles_repo_version"): "git repo branch ref (dotfiles), not a Docker image tag",
    ("default.config.yml", "freepbx_version"): "excluded service (abandoned image, unfixable CVEs)",
    ("default.config.yml", "face_version"): "nos/face is built locally from the vendored tree; the tag names a local build, not a registry pull",
    # qgis_version LEFT this list the same day it joined it. It was listed as
    # "UNPINNED, pin it on a supervised converge" and then digest-pinned to the
    # image the host was already running — `latest@sha256:f825a561…` — which
    # freezes it without changing what runs. This gate going red on the removal
    # is the gate working.
    # mcp_grafana_version LEFT this list 2026-08-05. The exception said "pin
    # once confirmed"; confirming it showed there is no versioned tag to pin to
    # — mcp/grafana publishes only `latest`, last pushed 2026-07-08, seven days
    # before the 0.17.1 fix REM-150 wants. So it is digest-pinned instead:
    # `latest@sha256:9362bcf…`, which freezes the resident image without
    # changing it. This gate going red on the removal is the gate working.
    ("pazny.mcp_gateway", "mcpo_version"): "ghcr.io/open-webui/mcpo publishes only main/latest — no semver tag exists",
}


def _sources() -> list[tuple[str, pathlib.Path]]:
    """Every file a pin may be declared in — the winning layer FIRST.

    `default.config.yml` is a vars_files entry and outranks role defaults, so
    omitting it (as this gate did until 2026-08-05) means checking a value the
    estate does not run.
    """
    out = [("default.config.yml", REPO / "default.config.yml")]
    out += [(f.parent.parent.name, f)
            for f in sorted((REPO / "roles").glob("pazny.*/defaults/main.yml"))]
    return out


def _floating_tags() -> list[tuple[str, str, str]]:
    found = []
    for source, f in _sources():
        try:
            m = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(m, dict):
            continue
        for k, v in m.items():
            if not isinstance(v, str) or not k.endswith(VERSION_KEY_SUFFIXES):
                continue
            if v.strip().lower() in FLOATING:
                found.append((source, k, v.strip()))
    return found


def test_the_winning_layer_is_scanned():
    """Positive control for the 2026-08-05 miss.

    Reading only role defaults is what let `qgis_version: latest` run in
    production under a green gate. If default.config.yml ever drops out of the
    scan again, this fails before the coverage loss can be mistaken for health.
    """
    assert any(src == "default.config.yml" for src, _ in _sources()), (
        "default.config.yml is not scanned, so every pin that lives only there "
        "is unchecked — which is now most of them"
    )
    text = (REPO / "default.config.yml").read_text()
    assert "_version:" in text, "default.config.yml parsed but holds no pins?"


def test_no_unexpected_floating_image_tags():
    floating = _floating_tags()
    unexpected = [(r, k, v) for (r, k, v) in floating if (r, k) not in EXCEPTIONS]
    assert not unexpected, (
        "Floating image tags in role defaults (pin to a fixed version, or add to "
        f"EXCEPTIONS with a reason): {unexpected}"
    )


def test_exceptions_still_apply():
    """Keep EXCEPTIONS honest — drop an entry once its tag gets pinned, so the
    allowlist can't quietly grant a free pass to a service that's since moved on."""
    floating = {(r, k) for (r, k, _) in _floating_tags()}
    stale = [e for e in EXCEPTIONS if e not in floating]
    assert not stale, f"EXCEPTIONS entries no longer floating (remove them): {stale}"


def test_no_floating_tags_in_base_stack_templates():
    """Base stack templates (templates/stacks/*/docker-compose.yml.j2) carry the
    shared-infra service definitions that the role-defaults scan above never
    sees. The 2026-06-10 review found tecnativa/docker-socket-proxy:latest there
    — the one container guarding docker.sock (= root on host) was the one image
    still floating. Literal `image: ...:<floating>` lines are banned; a Jinja
    `{{ var | default('x.y.z') }}` tag is fine (the default is checked too)."""
    bad = []
    for f in sorted((REPO / "templates" / "stacks").glob("*/docker-compose.yml.j2")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            s = line.strip()
            if not s.startswith("image:"):
                continue
            tag = s.split(":")[-1].strip().strip("\"'").lower()
            if tag in FLOATING:
                bad.append((str(f.relative_to(REPO)), n, s))
    assert not bad, f"Floating image tags in base stack templates: {bad}"
