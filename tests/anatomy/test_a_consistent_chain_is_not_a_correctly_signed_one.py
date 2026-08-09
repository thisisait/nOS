"""The audit chain must check WHICH key signed it, not only that it is consistent.

WHAT FIFTEEN GREEN NIGHTS HID. `bin/verify-audit-chain.php` walks the events
table and asks whether each row's hash follows from the last. That question has
a blind spot big enough to drive the whole control through: a writer holding a
RETIRED secret signs every row with it, each row verifies against its
predecessor, and the verifier prints `{"ok":true}` forever.

Measured on the live estate, 2026-08-09, by attributing each row to a ring member:

    retired key   173948 rows   2026-07-24T20:49 .. 2026-08-08T07:24
    current key      152 rows   2026-08-08T07:25 .. 2026-08-08T07:28

Every row of the chain — all of it — was signed with a retired credential for
fifteen days. The nightly `wing:audit-chain-verify` job returned exit 0 on each
of those nights. What finally produced a break was not tampering: it was the
Wing daemon being restarted so it re-read its plist (the launchd drift fix in
`roles/pazny.wing/tasks/main.yml`), picking up the current secret, and signing
the next row differently. The control only ever notices a key CHANGE — and a
writer stuck on one wrong key never changes.

WHY THAT IS SEVERE AND NOT PEDANTRY. `AuditChain`'s own header records that the
secret was rotated because *"the value leaked into a public commit."* The
rotation ran, reported success, and the writer never adopted it — so for fifteen
days the tamper-evident log was signed with the leaked key, which is the exact
state the rotation existed to end. Anyone holding that key could have re-signed
a suffix and the verifier would have agreed.

Verified before shipping, against the pre-rotation chain reconstructed on a
throwaway copy:

    old verifier  {"ok":true,"checked":173948}                      exit 0
    new verifier  {"ok":false,...,"stale_key":"…RETIRED key…"}      exit 2

WHAT THIS GATE PINS. Two things, both of which were wrong:

  1. the tail's elected key is compared against the CURRENT ring member;
  2. the cached verdict — what the Wing header badge renders — accounts for it.
     The first draft computed the stale-key check AFTER the verdict write, so
     the badge would have shown green while the process exited 2. A cached
     verdict that disagrees with the verdict is this defect wearing a hat.

It reads comment-stripped source, because the file necessarily discusses
`$break`, `retired` and `ok` at length in prose and a text match would fail it
for explaining itself.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERIFY = REPO / "files/anatomy/wing/bin/verify-audit-chain.php"


def code() -> str:
    """The file with comments and docblocks removed."""
    src = VERIFY.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)      # block + docblocks
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)      # whole-line //
    src = re.sub(r"(?<![:'\"])//[^\n'\"]*$", "", src, flags=re.M)   # trailing //
    return src


def test_the_verifier_exists():
    assert VERIFY.exists(), f"{VERIFY} is gone — the control has no verifier"


def test_the_tail_key_is_compared_against_the_current_one():
    src = code()
    assert re.search(r"\$keyRing\s*\[\s*0\s*\]", src), (
        "nothing in verify-audit-chain.php compares anything to $keyRing[0], the "
        "CURRENT key. Without that the chain can be entirely signed with a "
        "retired credential and still verify — which it was, for 173948 rows "
        "across fifteen nights of green.")
    assert re.search(r"\$tailIsCurrent", src), (
        "the tail-key verdict has no name in the code; the check that catches a "
        "writer stuck on a retired key must exist as its own decision")


def test_a_stale_tail_key_is_not_a_success():
    src = code()
    m = re.search(r"if\s*\(\s*!\s*\$tailIsCurrent\s*\)(.{0,900})", src, flags=re.S)
    assert m, "no branch acts on $tailIsCurrent — computing it and ignoring it is worse than not computing it"
    branch = m.group(1)
    assert re.search(r"exit\s*\(\s*[1-9]", branch), (
        "a chain signed with a retired key exits 0 — the nightly job would keep "
        "reporting success for the exact condition this check was added to find")


def test_the_cached_verdict_agrees_with_the_exit_code():
    """The badge and the exit code must be one verdict, not two."""
    src = code()
    m = re.search(r"\$verdictOk\s*=\s*([^;]+);", src)
    assert m, "no $verdictOk assignment found — the cached verdict is what the UI renders"
    expr = m.group(1)
    assert "$tailIsCurrent" in expr, (
        "$verdictOk is computed from $break alone, so the Wing header badge would "
        "render a calm green while this process exits 2 on a stale key. Fold "
        "$tailIsCurrent into it — and compute it BEFORE the write, which is where "
        "the first draft of this fix had it wrong.")


def test_the_stale_key_check_is_computed_before_the_verdict_is_written():
    src = code()
    where_computed = src.find("$tailIsCurrent =")
    where_written = src.find("$verdictOk =")
    assert where_computed != -1 and where_written != -1
    assert where_computed < where_written, (
        "$tailIsCurrent is computed after $verdictOk is written, so the cached "
        "verdict cannot possibly include it")
