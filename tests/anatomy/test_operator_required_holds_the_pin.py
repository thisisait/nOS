"""§loop-pin-bump-gate + §loop-requires-operator + §loop-verdict-vacuity.

The ledger stamps `requires_operator` on the KIND of pin move that is not
automatable (major crossing, downgrade, or a pin no oracle can read offline),
and the DRIVER honours it — the two halves the roadmap named separately settle
here together. The vacuity half is the same check read from the other side: a
nonsense version bump is held, not landed as an information-free pass.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BONE = ROOT / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import ledger  # noqa: E402 — after sys.path setup, same pattern as test_loop_ledger.py


def _diff(key, old, new):
    return (
        "--- a/default.config.yml\n+++ b/default.config.yml\n"
        "@@ -1 +1 @@\n"
        f'-{key}: "{old}"\n+{key}: "{new}"\n'
    )


def test_patch_step_is_automatable():
    assert ledger.pin_bump_needs_operator(_diff("freescout_version", "2.2.5", "2.2.8")) is False
    assert ledger.pin_bump_needs_operator(_diff("gitea_version", "1.27.0", "1.27.1")) is False


def test_major_crossing_is_held():
    # Kuma 1->2: ten days, zero monitors. The precedent this row is paid for.
    assert ledger.pin_bump_needs_operator(_diff("kuma_version", "1", "2")) is True


def test_downgrade_is_held():
    assert ledger.pin_bump_needs_operator(_diff("pg_version", "17", "16")) is True


def test_unreadable_pin_is_held():
    assert ledger.pin_bump_needs_operator(_diff("app_version", "1.2.3", "latest")) is True


def test_vacuity_sentinel_across_a_major_is_held():
    # The §loop-verdict-vacuity probe: 9.9.9-nonexistent no longer lands as a
    # vacuous pass when it crosses a major (the offline half of the oracle).
    assert ledger.pin_bump_needs_operator(_diff("wordpress_version", "6.8.2", "9.9.9-nonexistent")) is True


def test_diff_headers_do_not_match_as_assignments():
    # `--- a/x` / `+++ b/x` must never be read as a value change.
    assert ledger.pin_bump_needs_operator(_diff("svc_version", "3.1.0", "3.2.0")) is False


def test_driver_holds_an_operator_required_row():
    """loop-pr.land() returns without acting when requires_operator is set."""
    spec2 = importlib.util.spec_from_file_location("loop_pr", ROOT / "tools/loop-pr.py")
    loop_pr = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(loop_pr)
    logged = []
    row = {"weakness_id": "rem:TEST", "state": "ready", "uuid": "x" * 36,
           "requires_operator": 1}
    rc = loop_pr.land(row, base="dev", gate_set="live", rejudge=False,
                      timeout=1, act=True, log=logged.append)
    assert rc == 0
    assert any("requires an operator" in line for line in logged)
