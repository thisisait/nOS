"""Anatomy gate: the hidden_fees/01 narrative names the layer it measured.

WHAT WENT WRONG, 2026-08-10. Probe E measured "switched off but running" on
`default.config.yml` alone. All sixteen services it named are `install_*: true`
in the operator's `config.yml`, so they run because they are enabled — while
the one service actually switched off there (`install_mailpit: false`,
`iiab-mailpit-1` up, both mailpit fragments on disk) was invisible to the
probe. The wrong mechanism then propagated verbatim into four places:

  * docs/hidden_fees/01 ("Sixteen." as the measured number),
  * tasks/stacks/prune-disabled.yml's header ("The operator's switch switched
    nothing off"),
  * the REM-159/184/185 queue amendments (same sentence, same sixteen),
  * the REM-168 resolved_by note ("install_homeassistant is false ... and the
    container is UP — see docs/hidden_fees/01").

The exposure conclusions in those amendments stand — the services ARE running,
and the ORIGINAL mitigation claims committed the same wrong-layer error in the
reassuring direction — but the causal story was false, and a false mechanism
in a security queue is precisely the "talked out of being counted" shape the
amendments themselves warn about, pointed the other way.

This gate pins the corrected narrative so the falsified sentence cannot be
copied forward again (the estate's tally line was wrong three times by exactly
that route). It pins PHRASES, deliberately: the defect was prose, the fix is
prose, and the regression vector is a reader restoring the more dramatic
version of the story.
"""

from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FEE = REPO / "docs/hidden_fees/01-disabled-service-overrides.md"
TASK = REPO / "tasks/stacks/prune-disabled.yml"
QUEUE = REPO / "docs/llm/security/remediation-queue.json"

# The falsified mechanism sentence, verbatim as it propagated. The services it
# was written about are up because config.yml ENABLES them.
FALSE_MECHANISM = "The operator's switch switched nothing off"


def test_the_fee_doc_names_the_measured_instance() -> None:
    text = FEE.read_text(encoding="utf-8")
    assert "mailpit" in text, (
        "docs/hidden_fees/01 no longer names mailpit — the one service on the "
        "measuring host that was genuinely switched off (config.yml) with its "
        "fragments still merged and its container up. Without the real "
        "instance, the doc's number reverts to the wrong-layer sixteen."
    )
    assert "the operator's config.yml" in text, (
        "docs/hidden_fees/01 does not mention the operator's config.yml "
        "override layer (a bare 'config.yml' would match inside "
        "'default.config.yml'). The original 'sixteen' was measured on the "
        "committed default alone; the doc must say which layer a number came "
        "from or it will drift again."
    )


def test_the_false_mechanism_sentence_is_gone() -> None:
    for path in (FEE, TASK, QUEUE):
        assert FALSE_MECHANISM not in path.read_text(encoding="utf-8"), (
            f"{path.relative_to(REPO)} still carries the sentence "
            f"'{FALSE_MECHANISM}'. It was written about services whose "
            "resolved flag is TRUE (config.yml enables them) — the switch was "
            "never flipped on this host. The measured instance of the "
            "lingering-fragment mechanism is mailpit."
        )


def test_the_queue_amendments_name_the_enabling_layer() -> None:
    """REM-159/184/185: exposure stands, mechanism corrected.

    Each amendment must attribute the running container to config.yml enabling
    the service, not to a fragment that outlived a flip that never happened.
    """
    items = {
        it["id"]: it
        for it in json.loads(QUEUE.read_text(encoding="utf-8"))["items"]
    }
    for rem in ("REM-159", "REM-184", "REM-185"):
        detail = items[rem].get("remediation_detail", "")
        assert "DISPOSITION AMENDED" in detail, (
            f"{rem} lost its amendment — the row is back to claiming "
            "mitigation from a flag that is true on the live host"
        )
        amendment = detail.split("DISPOSITION AMENDED", 1)[1]
        # Not a bare "config.yml" — that is a substring of "default.config.yml"
        # and would pass on the falsified text this gate exists to keep out.
        assert "the operator's config.yml" in amendment, (
            f"{rem}'s amendment does not name the operator's config.yml as "
            "the layer that enables the service. The container is up because "
            "the operator runs it, and the row's original sin was reading the "
            "committed default as if it were the resolved value."
        )
        assert "FULLY EXPOSED" in amendment, (
            f"{rem}'s amendment dropped the exposure conclusion. That half was "
            "always correct: the service is running, so no disposition may "
            "lean on install_*=false."
        )
