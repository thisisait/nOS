"""Gate — an HMAC-signed notification must be posted to Bone, never to Wing.

THE FEE THIS PINS: docs/hidden_fees/18-a-report-that-reaches-nobody.md.

`pulse-run-agent.sh` — the bridge every scheduled agent runs through — signed
its finishing notification with Bone's secret and posted it to Wing. Wing's
`NotificationsPresenter` exposes GET under Bearer auth and states in its own
docblock that "creation stays on the Bone HMAC path (POST is not exposed here)",
so every agent report came back 401. The script printed one WARN to stderr and
exited 0, because the agent had genuinely done its work.

Measured on the live estate the day it was found: of every `notifications` row
ever written, `e2e-mock-agent` had 29 and `conductor` 2 — and `librarian`,
`surveyor`, `scout` and `remediator` had none, ever. The e2e path posted to
Bone, so the coverage was real and proved the wrong door.

WHY THIS GATE IS SHAPED AT THE CLASS AND NOT THE INSTANCE. One `sed` fixes the
instance. What produced it survives that fix: the variable is called
`WING_EVENTS_HMAC_SECRET` and holds `bone_secret`, so every call site reads as
though Wing were the destination. Until that name changes, the next person
writing a notification sender starts from the same wrong premise — which is
exactly what happened here, next door to a correct `nos-notify.sh` and to
`drift-watch.sh`'s own comment "(Bone; 9000 is Wing)".

So: no shell script anywhere may aim a notification POST at a Wing URL or at
port 9000. Bone is loopback-only and canonical on 8099.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SEARCH_ROOTS = ("files/anatomy/scripts", "tools")

#: Bone's canonical loopback port. Wing is 9000 and is not an ingestion door.
BONE_PORT = "8099"
WING_PORT = "9000"

NOTIFICATION_PATH = "/api/v1/notifications"


def _shell_scripts() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for root in SEARCH_ROOTS:
        base = REPO / root
        if base.is_dir():
            out.extend(sorted(base.rglob("*.sh")))
    return out


def _posting_lines(text: str) -> list[str]:
    """Lines that name the notification ingestion path."""
    return [ln for ln in text.splitlines()
            if NOTIFICATION_PATH in ln and not ln.lstrip().startswith("#")]


@pytest.mark.parametrize("script", _shell_scripts(), ids=lambda p: p.name)
def test_no_script_posts_a_notification_to_wing(script: pathlib.Path) -> None:
    text = script.read_text(encoding="utf-8")
    for line in _posting_lines(text):
        assert "WING_API_URL" not in line, (
            f"{script.relative_to(REPO)} aims a notification at Wing "
            f"($WING_API_URL). Wing serves GET here under Bearer auth and "
            f"refuses POST with 401 — creation is Bone's, on {BONE_PORT}.\n"
            f"  {line.strip()}"
        )
        assert f":{WING_PORT}" not in line, (
            f"{script.relative_to(REPO)} aims a notification at port "
            f"{WING_PORT} (Wing). Bone is {BONE_PORT}.\n  {line.strip()}"
        )


def test_the_agent_bridge_uses_the_house_bone_pattern() -> None:
    """The bridge is the one every scheduled agent runs through, so it gets a
    named check rather than only the sweep above."""
    bridge = REPO / "files/anatomy/scripts/pulse-run-agent.sh"
    assert bridge.exists(), f"the agent bridge moved: {bridge}"
    text = bridge.read_text(encoding="utf-8")

    assert re.search(r'BONE_URL="\$\{BONE_API_URL:-http://127\.0\.0\.1:8099\}"', text), (
        "pulse-run-agent.sh must resolve Bone the way the operator run-tools "
        "and deploy-from-ci.sh already do: "
        'BONE_URL="${BONE_API_URL:-http://127.0.0.1:8099}"'
    )

    posting = _posting_lines(text)
    assert posting, "the bridge no longer posts a notification at all"
    assert any("$BONE_URL" in ln for ln in posting), (
        "the bridge signs with Bone's secret; it must post to Bone's URL"
    )


def test_the_failure_path_says_the_report_did_not_arrive() -> None:
    """A warning that only reports an HTTP code is what hid this.

    The agent had done its work and the wrapper exited 0, so the single
    stderr line was the entire difference between a delivered report and a
    lost one. It has to say which door it tried and what the consequence was.
    """
    text = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text(encoding="utf-8")
    # Join shell line-continuations first: a warning long enough to be useful
    # is a warning that wraps, and the first version of this gate failed on a
    # correct message because it read one physical line.
    text = re.sub(r"\\\n\s*", " ", text)
    warn = [ln for ln in text.splitlines() if "notification POST" in ln and "echo" in ln]
    assert warn, "the notification failure path lost its warning"
    joined = " ".join(warn)
    assert "$BONE_URL" in joined, "the warning must name the door it tried"
    assert re.search(r"did NOT reach|never reached|not reach", joined), (
        "the warning must say the operator did not get the report — an HTTP "
        "code alone is what let this run for months"
    )


def test_wing_still_declares_that_creation_is_not_its_job() -> None:
    """If Wing ever DOES expose POST, this gate's premise changes and someone
    must revisit it deliberately rather than discover it by 401."""
    presenter = REPO / "files/anatomy/wing/app/Presenters/Api/NotificationsPresenter.php"
    assert presenter.exists(), f"the presenter moved: {presenter}"
    text = presenter.read_text(encoding="utf-8")
    assert "POST is not exposed here" in text, (
        "NotificationsPresenter no longer declares that creation stays on the "
        "Bone HMAC path. If POST is now served here, revisit "
        "docs/hidden_fees/18 and this gate together — the fee was created by "
        "two doors disagreeing about which one ingests."
    )
