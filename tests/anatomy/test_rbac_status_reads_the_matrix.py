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


def test_a_per_tier_point_is_read_from_what_its_line_says(tmp_path):
    pts = _scratch(tmp_path, {
        "roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2":
            "UNIX_REALM_GROUPS = {{ authentik_rbac_tiers | map(attribute='groups') | flatten | unique | list | to_json }}\n",
        "roles/pazny.receptor/templates/identity-map.yml.j2":
            "{%- set _ = ns.logins.update({u.name: {'username': u.name, 'groups': "
            "(authentik_rbac_tiers | selectattr('tier', 'equalto', u.tier | int) | first).groups}}) -%}\n"})
    # A realm keeping every group holds the whole set: ok, not a drift assumed from the line's place.
    assert pts.get("jupyterhub-unix-realm") == "ok", pts.get("jupyterhub-unix-realm")
    # A login given its tier's CUMULATIVE groups holds tier 1's: drift, not UNKNOWN.
    assert pts.get("receptor-identity-map") == "drift", pts.get("receptor-identity-map")


def test_a_tier_expression_that_drops_a_group_is_never_ok(tmp_path):
    expr = "(authentik_rbac_tiers | selectattr('tier', 'equalto', {n}) | first).groups"
    pts = _scratch(tmp_path, {
        "roles/pazny.thalamus/templates/thalamus.env.j2":
            f"NOS_TIER1_GROUPS={{{{ {expr.format(n=1)} | first }}}}\n"
            f"NOS_TIER2_GROUPS={{{{ {expr.format(n=2)}[0] }}}}\n",
        "roles/pazny.thalamus/templates/thalamus.plist.j2":
            f"<string>{{{{ {expr.format(n=1)} | random }}}}</string>\n"
            f"<string>{{{{ {expr.format(n=2)}[-1] }}}}</string>\n"})
    assert pts.get("thalamus-tier1-env") == "drift", f"`| first` reads as {pts.get('thalamus-tier1-env')}"
    assert pts.get("thalamus-tier2-env") == "drift", f"`[0]` reads as {pts.get('thalamus-tier2-env')}"
    assert pts.get("thalamus-tier1-plist") == "UNKNOWN", f"an unmodelled filter reads as {pts.get('thalamus-tier1-plist')}"
    assert pts.get("thalamus-tier2-plist") == "drift", f"`[-1]` reads as {pts.get('thalamus-tier2-plist')}"


def test_the_genome_models_what_the_doctrine_inventories():
    """permissions.md §3/§4 + Bone loopauth: bearer scopes, loop identities, app tiers, the DGX group."""
    rc, out = _run()
    assert rc == 0
    matrix = out.get("matrix") or {}
    for cap in ("loop:read", "loop:propose", "loop:judge", "loop:forget", "wing.halt", "pulse.write",
                "app.reach:twofauth"):
        assert cap in matrix, f"{cap} is enforced today but the genome does not hold it"
    assert "door:face-bff" in matrix.get("wing.operator", []), "the face BFF bearer holds wing.operator"
    assert any("operator-local" in r for r in matrix.values()), "operator-local is a role holding nothing"
    points = {p["id"]: p["status"] for p in out.get("points", [])}
    for pid in ("bone-loop-identities", "wing-reserved-scopes", "app-tiers"):
        assert points.get(pid) == "ok", f"{pid}: {points.get(pid)}"
    assert points.get("dgx-keap-identity") == "drift", "nos-maintainers is a group the genome does not hold"


def test_a_planted_bearer_loop_or_app_tier_drift_is_named(tmp_path):
    pts = _scratch(tmp_path, {
        "files/anatomy/bone/loopauth.py":
            'LOOP_SCOPES = frozenset({"read", "propose", "judge", "forget"})\n'
            "IDENTITIES = {\n"
            '    "agent:proposer": ("P", frozenset({"read", "propose", "judge"})),\n'
            '    "engine:evaluator": ("J", frozenset({"read", "judge"})),\n'
            '    "operator": ("O", frozenset({"read", "forget"})),\n}\n',
        "files/anatomy/wing/bin/provision-token.php":
            "<?php\nif (in_array('wing.halt', $requested, true) && $name !== 'face-bff') {\n}\n",
        "apps/twofauth.yml": "authentik:\n  tier: 3\nnginx:\n  rbac_tier: 1\n"})
    for pid in ("bone-loop-identities", "wing-reserved-scopes", "app-tiers"):
        assert pts.get(pid) == "drift", f"planted {pid} drift reads as {pts.get(pid)}"
