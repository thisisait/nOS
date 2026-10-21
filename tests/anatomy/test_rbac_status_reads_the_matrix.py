"""`tools/rbac-status.py` prints the permission matrix and every drift from it.

WHY. Tier 1 is decided in six places and four restate the group names as
literals (the permissions doctrine, §4); no reader printed capability x role,
so a literal that drifted (GitLab's `groups | last` dropping nos-providers) was
found only by an audit. The genome (state/genome/permissions.yml) is the one
list; the reader compares each enforcement point's literal against it.

PINNED. Every genome capability is printed with its roles; a planted literal that
disagrees is named with file:line; a point it cannot read is UNKNOWN, never ok;
on this checkout only the out-of-repo point (KEAP) is UNKNOWN, so a parser that
loses its literal goes red here. Exit 0 on every path. No live source is read.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/rbac-status.py"
GENOME = "state/genome/permissions.yml"
ENDUSER = "files/anatomy/wing/app/Security/EndUser.php"


def _run(*args: str) -> tuple[int, dict]:
    assert TOOL.is_file(), "no reader prints the permission matrix: tools/rbac-status.py is missing"
    p = subprocess.run([sys.executable, str(TOOL), "--json", *args],
                       capture_output=True, text=True, timeout=60)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else {})


def _fixture(tmp: pathlib.Path) -> pathlib.Path:
    (tmp / GENOME).parent.mkdir(parents=True)
    shutil.copy(REPO / GENOME, tmp / GENOME)
    (tmp / ENDUSER).parent.mkdir(parents=True)
    (tmp / ENDUSER).write_text(
        "<?php\nfinal class EndUser\n{\n"
        "\tpublic const TOKEN_NAME = 'face-bff';\n"
        "\tpublic const THALAMUS = 'thalamus';\n"
        "\tpublic const OPERATOR_GROUPS = ['nos-admins'];\n}\n", encoding="utf-8")
    return tmp


def test_the_reader_prints_every_capability_with_its_roles():
    import yaml
    genome = yaml.safe_load((REPO / GENOME).read_text(encoding="utf-8"))
    rc, out = _run()
    assert rc == 0
    matrix = out.get("matrix") or {}
    for cap, roles in genome["capabilities"].items():
        assert cap in matrix, f"{cap} is in the genome but the reader does not print it"
        assert matrix[cap] == roles, f"{cap}: reader prints {matrix[cap]}, genome holds {roles}"


def test_a_planted_drift_is_named_with_file_and_line(tmp_path):
    rc, out = _run("--root", str(_fixture(tmp_path)))
    assert rc == 0
    where = [d["at"] for d in out.get("drift", [])]
    assert f"{ENDUSER}:6" in where, f"planted OPERATOR_GROUPS drift not named; drift at {where}"


def test_an_unreadable_source_is_unknown_never_ok(tmp_path):
    rc, out = _run("--root", str(_fixture(tmp_path)))
    assert rc == 0
    points = {p["id"]: p["status"] for p in out.get("points", [])}
    assert points, "the reader listed no enforcement points"
    # The fixture holds only EndUser.php: every other point's source is absent.
    assert points.get("face-tier-ts") == "UNKNOWN", points
    assert points.get("wing-enduser") == "drift", points
    assert "ok" not in {s for k, s in points.items() if k != "wing-enduser-doors"}, points


def test_on_this_checkout_only_the_out_of_repo_point_is_unknown():
    rc, out = _run()
    assert rc == 0
    unknown = sorted(p["id"] for p in out.get("points", []) if p["status"] == "UNKNOWN")
    assert unknown == ["keap-internal"], f"a parser lost its literal: {unknown}"


TIERS_BLOCK = (
    "authentik_rbac_tiers:\n"
    "  - {tier: 1, groups: [nos-providers, nos-admins]}\n"
    "  - {tier: 2, groups: [nos-providers, nos-admins, nos-managers]}\n"
    "  - {tier: 3, groups: [nos-providers, nos-admins, nos-managers, nos-users]}\n"
    "  - {tier: 4, groups: [nos-providers, nos-admins, nos-managers, nos-users, nos-guests]}\n")


def _scratch(tmp: pathlib.Path, files: dict[str, str]) -> dict[str, str]:
    """A scratch root: the genome, the tier block, the planted files. Returns point -> status."""
    assert TOOL.is_file(), "no reader prints the permission matrix: tools/rbac-status.py is missing"
    for rel, text in {GENOME: (REPO / GENOME).read_text(encoding="utf-8"),
                      "default.config.yml": TIERS_BLOCK, **files}.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text, encoding="utf-8")
    rc, out = _run("--root", str(tmp))
    assert rc == 0
    return {p["id"]: p["status"] for p in out.get("points", [])}


def test_a_const_over_several_lines_is_read_and_a_non_literal_is_unknown(tmp_path):
    pts = _scratch(tmp_path, {
        ENDUSER: "<?php\nfinal class EndUser\n{\n\tpublic const TOKEN_NAME = 'face-bff';\n"
                 "\tpublic const THALAMUS = 'thalamus';\n\tpublic const OPERATOR_GROUPS = [\n"
                 "\t\t'nos-providers',\n\t\t'nos-admins',\n\t];\n}\n",
        "files/anatomy/face/src/lib/security/tier.ts": "export const WRITE_GROUPS = groupsFor(2);\n"})
    assert pts.get("wing-enduser") == "ok", f"a correct multi-line OPERATOR_GROUPS reads as {pts.get('wing-enduser')}"
    assert pts.get("face-write-groups") == "UNKNOWN", f"a non-literal const reads as {pts.get('face-write-groups')}"
