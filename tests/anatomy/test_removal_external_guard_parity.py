"""The removal-set external-paths guard must EQUAL the deploy gate.

2026-07-22, first live `nos --remove=data`: removal-set applied the SSD path
overrides because its guard checked only "external_storage_root is non-empty"
— which is true BY DEFAULT — while the deploy applies them only under
`configure_external_storage` (main.yml import of tasks/external-storage.yml).
On a platform-path estate the removal therefore deleted absent /Volumes/SSD1TB
paths, the real ~/nos/platform data survived, and the R5 verify — measuring
the same wrong list — stayed green over the survivors (Infisical crashlooped
on a rotated encryption key against its surviving DB).

The rule this pins: whatever condition decides where data is WRITTEN must be
the same condition deciding where data is REMOVED. If the deploy gate ever
changes, this test drags the removal guard along.
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _removal_set_include_when():
    tasks = yaml.safe_load((REPO / "tasks" / "removal-set.yml").read_text())
    for task in tasks:
        include = task.get("include_tasks") or task.get(
            "ansible.builtin.include_tasks"
        )
        if "external-paths" in str(include or ""):
            when = task.get("when")
            assert when is not None, "external-paths include has no guard at all"
            return when if isinstance(when, list) else [when]
    raise AssertionError("removal-set.yml no longer includes external-paths.yml")


def test_removal_guard_keys_on_the_deploy_flag():
    when = _removal_set_include_when()
    assert any("configure_external_storage" in str(c) for c in when), (
        "removal-set applies external-path overrides without the deploy's "
        "configure_external_storage gate — on a platform-path estate the "
        "removal list points at paths the deploy never wrote (2026-07-22 bug)"
    )


def test_deploy_gate_still_uses_the_same_flag():
    main = (REPO / "main.yml").read_text()
    m = re.search(
        r"import_tasks:\s*tasks/external-storage\.yml\s*\n\s*when:\s*(.+)", main
    )
    assert m, "main.yml no longer imports tasks/external-storage.yml with a when"
    assert "configure_external_storage" in m.group(1), (
        "deploy gate renamed — update BOTH main.yml and tasks/removal-set.yml "
        "and this test together; the two conditions must stay identical"
    )
