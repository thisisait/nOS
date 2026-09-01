"""Anatomy gate: the disabled half of hidden_fees/01 has a reconciler, and it is safe.

`prune-retired.yml` removes the compose override of a service that LEFT nOS. Its
own header says the DISABLED case — `install_<svc>: false`, service still shipped
— "is not handled here". Measured 2026-08-10 on the RESOLVED config
(default.config.yml + the operator's config.yml, which wins): ONE service on
this host was genuinely switched off with its container up — mailpit — because
the render path is create-only and the orchestrator keeps merging the fragment
written on the converge that had the service on. (A same-day first measurement
said sixteen; it read the committed default alone, and all sixteen are enabled
in config.yml — running legitimately, not zombies.)

WHY IT IS A SECURITY GATE. Nine rows in the remediation queue argue mitigation
from that flag — "MITIGATED: install_gitlab=false" — three of them HIGH. Those
claims read the committed default while the resolved flag is true, and a row
whose resolved flag really is false while the container runs is an open exposure
that has been talked out of being counted. Either way the flag is not evidence;
only the reconciled estate is.

THE TWO FALSE POSITIVES THIS MUST NEVER PRODUCE, and they are the reason most of
this file exists rather than a one-line "the task is imported" check:

  1. AUTO-ENABLED DEPENDENCIES. `main.yml` flips install_postgresql /
     install_mariadb to true at run time from other flags, so `false` in
     default.config.yml is their correct default. Pruning postgresql's fragment
     would tear down the database the whole estate runs on. Verified 2026-08-10
     under both flag semantics: postgresql's fragment is never in the report.
  2. TIER-2 MANIFEST APPS. `apps/<name>.yml` owns their bring-up, so the toggle
     is not what would have switched them off.

Both lists are DERIVED — from main.yml's own auto-enable tasks and from the
apps/ directory — so a fourth dependency or a new manifest app needs no edit.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = REPO / "tasks/stacks/prune-disabled.yml"
RETIRED = REPO / "tasks/stacks/prune-retired.yml"
CONFIG = REPO / "default.config.yml"
ORCHESTRATORS = (REPO / "tasks/stacks/core-up.yml", REPO / "tasks/stacks/stack-up.yml")


@pytest.fixture(scope="module")
def tasks() -> list[dict]:
    return yaml.safe_load(TASK.read_text(encoding="utf-8"))


def test_the_reconciler_exists_and_parses(tasks) -> None:
    assert tasks and len(tasks) >= 6, (
        "prune-disabled.yml lost its body. The disabled half of hidden_fees/01 "
        "is the one that does not fail loudly, so its absence is silent."
    )


def test_both_orchestrators_import_it(tasks) -> None:
    """A reconciler only one stack path runs is a reconciler for half the estate."""
    for path in ORCHESTRATORS:
        text = path.read_text(encoding="utf-8")
        assert "prune-disabled.yml" in text, (
            f"{path.relative_to(REPO)} does not import prune-disabled.yml, so "
            "services in the stacks it brings up keep their fragments forever."
        )
        assert "prune-retired.yml" in text, "the retired half went missing"


def test_removal_is_opt_in_and_the_report_is_not(tasks) -> None:
    """The report must run unconditionally; only the deletion may be gated.

    The complaint in hidden_fees/01 is that this case is SILENT. A reconciler
    whose report also waits for the opt-in leaves it silent for everyone who has
    not opted in — which is everyone, on day one.
    """
    report = [t for t in tasks if "REPORT" in str(t.get("name", ""))]
    remove = [t for t in tasks if t.get("ansible.builtin.file", {}).get("state") == "absent"]
    assert report, "no REPORT task — the fee stays invisible"
    assert remove, "no removal task — the fee stays unpaid"

    report_when = str(report[0].get("when", ""))
    assert "prune_disabled_overrides" not in report_when, (
        "the REPORT is gated on the opt-in flag. Then nothing is louder until "
        "someone already knew to look, which is the defect this closes."
    )
    remove_when = str(remove[0].get("when", ""))
    assert "prune_disabled_overrides" in remove_when, (
        "the removal is NOT gated. Every resolved-disabled service would be "
        "torn down on the first converge after this lands; the estate's "
        "destructive-op doctrine is report first, act on an explicit token."
    )


def test_the_flag_is_declared_and_defaults_to_false(tasks) -> None:
    cfg = CONFIG.read_text(encoding="utf-8")
    m = re.search(r"^prune_disabled_overrides:\s*(\S+)", cfg, re.M)
    assert m, "prune_disabled_overrides is not declared in default.config.yml"
    assert m.group(1) == "false", (
        "the default flipped to true. That is the intended END state, but it "
        "must be a deliberate change with the operator seeing the list first — "
        "and this gate's docstring updated to say the obligation is discharged."
    )


def test_auto_enabled_dependencies_are_derived_not_listed(tasks) -> None:
    """The postgresql trap, pinned.

    A hard-coded exclusion list is a fourth place the same fact lives. Reading
    main.yml's own auto-enable tasks means a fourth dependency is covered the
    day it is written.
    """
    body = TASK.read_text(encoding="utf-8")
    assert "main.yml" in body and "regex_findall" in body, (
        "the auto-enabled set is no longer read from main.yml. If it became a "
        "literal list, the next dependency added there will be pruned here."
    )
    # And main.yml must still declare them in the shape the reconciler reads.
    main = (REPO / "main.yml").read_text(encoding="utf-8")
    found = re.findall(r"^\s*install_([a-z0-9_]+):\s*true\s*$", main, re.M)
    assert "postgresql" in found and "mariadb" in found, (
        "main.yml no longer auto-enables postgresql/mariadb in a shape this "
        f"reconciler can read (found: {found}). It would prune the database."
    )


def test_manifest_apps_are_derived_from_the_directory(tasks) -> None:
    body = TASK.read_text(encoding="utf-8")
    assert "apps" in body and "_manifest_apps" in body, (
        "Tier-2 manifest apps are no longer excluded. Their bring-up belongs to "
        "apps/<name>.yml, so an install_<name> toggle is not what switched them "
        "off, and comparing the two is a guess."
    )


def test_the_match_is_separator_insensitive(tasks) -> None:
    """`code-server.yml` sits beside `qgis_server.yml`; one spelling misses the other.

    Moved into `filter_plugins/nos_prune_guard.py` on 2026-09-01 along with the
    rest of the selection, so this asserts the BEHAVIOUR rather than the inline
    Jinja that used to carry it — a stronger check than the `[-_]?` substring
    it replaces, which a refactor could satisfy while matching nothing.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "nos_prune_guard", REPO / "filter_plugins/nos_prune_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for svc, fragment in (
        ("qgis_server", "/stacks/engineering/overrides/qgis_server.yml"),
        ("smtp_stalwart", "/stacks/infra/overrides/smtp_stalwart.yml"),
        # The same name spelled the other way must match too.
        ("code_server", "/stacks/devops/overrides/code-server.yml"),
        ("uptime_kuma", "/stacks/iiab/overrides/uptime-kuma-base.yml"),
    ):
        plan = mod.nos_prune_plan(
            disabled=[svc],
            on_disk_flags={"install_" + svc: False},
            overrides={fragment: []},
            containers=[],
        )
        assert plan["fragments"] == [fragment], (
            f"the fragment match went back to a single separator: {svc} no "
            f"longer matches {fragment}. Fragments are named by whatever the "
            "role chose — a hyphen-only mapping silently leaves underscore-named "
            "fragments (qgis_server, smtp_stalwart) merged."
        )


def test_it_does_not_claim_to_touch_data(tasks) -> None:
    """Reversibility is the whole reason removing the fragment is acceptable."""
    body = TASK.read_text(encoding="utf-8")
    assert "remove-orphans" in body, (
        "the header no longer explains why removing the fragment is enough. It "
        "is enough BECAUSE every orchestrator runs `up -d --remove-orphans`; if "
        "that stopped being true, this reconciler leaves running orphans behind."
    )
    for path in ORCHESTRATORS:
        assert "--remove-orphans" in path.read_text(encoding="utf-8"), (
            f"{path.relative_to(REPO)} no longer passes --remove-orphans, so a "
            "pruned fragment leaves its container running — the reconciler would "
            "report success while changing nothing about what is up."
        )


def test_the_retired_header_still_points_here(tasks) -> None:
    """The sibling names this gap; if it stops, the two can drift apart."""
    text = RETIRED.read_text(encoding="utf-8")
    assert "DISABLED" in text, (
        "prune-retired.yml no longer records that it excludes the disabled case. "
        "That sentence is what made this file necessary and findable."
    )
