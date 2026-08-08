"""A key rotation must not leave a verifier signing against the retired key.

WHAT HAPPENED, measured 2026-08-08 on the live estate.

`alert-relay:relay-firing` had failed **53 consecutive times** overnight, every
run ending:

    alert-relay: POST /notifications HTTP 401:
        b'{"detail":"HMAC check failed: invalid signature"}'
    alert-relay: UNDELIVERED (high) NosCriticalCveFoundHigh — will retry next run
    alert-relay: 7 notification(s) did not reach Bone

Not a desync between the caller and `secrets.yml` — those matched byte for byte.
The three values, by sha256 prefix:

    ~/.nos/secrets.yml   bone_secret              ff6bad9d…   <- callers sign with this
    ~/.nos/secrets.yml   bone_secret_retired      672fd2db…
    ~/.nos/secrets.yml   wing_events_hmac_secret  672fd2db…   <- == the RETIRED key
    bone.plist           WING_EVENTS_HMAC_SECRET  672fd2db…   <- so Bone verifies with it

`roles/pazny.bone/templates/bone.plist.j2` renders
`wing_events_hmac_secret | default(bone_secret)`, so whatever
`wing_events_hmac_secret` holds is what Bone runs. A `bone_secret_rotate=true`
run mints a new `bone_secret` and prepends the outgoing one to
`bone_secret_retired` (`main.yml` § Chain-key rotation) — and never touches
`wing_events_hmac_secret`. The reconciler that was supposed to keep them
together had four conditions, and none of them could fire on a rotation:

    '_pw_' in cur          — an unrendered template
    len(cur) < 32          — an unset value
    cur == bone_secret     — sets it to what it already equals: a NO-OP branch
    (else) keep cur        — a persisted 64-hex value that merely DIFFERS

A rotated secret lands in the last row and is preserved forever. The missing
condition is the one this file pins: **if the current value is on the retired
ring, it is a stale copy of a rotated key, not an operator override.**

WHY IT WAS INVISIBLE FOR AS LONG AS IT WAS. The job was honest — it exits 2 and
prints UNDELIVERED, exactly as the estate's rule requires. Nobody read it,
because the channel that would have carried the complaint is the channel that
was down. This is the failure mode a notification spine has and a log does not,
and it argues for the reader being somewhere other than the thing being read.

WHAT THIS GATE DOES NOT COVER, stated so nobody reads a green run as more than
it is: Bone has no retired-ring acceptance at all. Wing's plist carries
`WING_EVENTS_HMAC_SECRET_RETIRED` (`roles/pazny.wing/templates/wing.plist.j2`)
and `files/anatomy/bone/events.py::verify_hmac` has no equivalent — it compares
against one secret. So a rotation is still a hard cutover on Bone's side with no
grace window; this gate only ensures both sides cut over to the SAME key.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
BONE_PLIST = REPO / "roles/pazny.bone/templates/bone.plist.j2"
BONE_EVENTS = REPO / "files/anatomy/bone/events.py"


def reconciler_block() -> str:
    """The set_fact task that decides wing_events_hmac_secret."""
    src = MAIN.read_text(encoding="utf-8")
    start = src.find("Lazy-regenerate Wing events HMAC")
    assert start != -1, (
        "main.yml no longer has the 'Lazy-regenerate Wing events HMAC' task. "
        "It is what keeps Bone's verifier and the signing callers on one key — "
        "if it was renamed, point this gate at the new name; if it was deleted, "
        "read this file's docstring before deciding that was safe."
    )
    end = src.find("\n    - name:", start)
    return src[start : end if end != -1 else len(src)]


def test_the_reconciler_adopts_a_retired_key_forward():
    """The clause whose absence took the alert channel down for a night."""
    block = reconciler_block()
    assert "bone_secret_retired" in block, (
        "the wing_events_hmac_secret reconciler does not consult "
        "bone_secret_retired.\n"
        "Without it a rotated secret is indistinguishable from a deliberate "
        "operator override, so it is preserved — and Bone, whose plist renders "
        "`wing_events_hmac_secret | default(bone_secret)`, keeps verifying with "
        "the key every caller has already stopped signing with.\n"
        "Measured cost the one time this happened: 53 consecutive 401s and 7 "
        "undelivered alerts, one of them a CVE-high."
    )


def test_bones_plist_still_prefers_the_var_this_gate_watches():
    """The gate is only meaningful while Bone reads that variable.

    If the plist is ever changed to render `bone_secret` directly, the whole
    class of defect disappears and this gate becomes theatre — so it must fail
    loudly and be re-read rather than quietly passing against a dead premise.
    """
    src = BONE_PLIST.read_text(encoding="utf-8")
    m = re.search(r"WING_EVENTS_HMAC_SECRET</key>\s*\n\s*<string>(.*?)</string>", src)
    assert m, "bone.plist.j2 no longer renders WING_EVENTS_HMAC_SECRET as expected"
    rendered = m.group(1)
    assert "wing_events_hmac_secret" in rendered, (
        "bone.plist.j2 no longer renders wing_events_hmac_secret — if Bone now "
        "reads bone_secret directly that is a genuine simplification, but this "
        "gate's premise is gone and its docstring needs rewriting rather than "
        "the assertion being relaxed."
    )


def test_bone_has_no_retired_ring_and_that_is_recorded_here():
    """Asymmetry, asserted so it cannot be forgotten or silently half-fixed.

    Wing tolerates a rotation window; Bone does not. This test passes today by
    recording that fact. When Bone gains retired-ring acceptance it will FAIL,
    which is the intended prompt to delete it and drop the caveat from the
    docstring above — a gate that outlives its own subject is how a caveat
    becomes folklore.
    """
    src = BONE_EVENTS.read_text(encoding="utf-8")
    verifier = src[src.find("def verify_hmac") : src.find("def validate_payload")]
    assert "RETIRED" not in verifier.upper(), (
        "files/anatomy/bone/events.py::verify_hmac now mentions a retired ring. "
        "If Bone accepts retired keys during a rotation window, the asymmetry "
        "this file documents is closed: delete this test and update the "
        "docstring's 'what this gate does not cover' paragraph."
    )
