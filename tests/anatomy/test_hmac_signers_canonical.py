"""Anatomy gate: every HMAC signer must canonicalise the way Bone verifies.

Bone does not verify the bytes it received. `files/anatomy/bone/main.py` re-serialises
the PARSED body before checking the signature:

    raw = json.dumps(body or {}, separators=(",", ":"), sort_keys=True).encode("utf-8")

`json.dumps` defaults to **ensure_ascii=True**, so every non-ASCII character is
escaped to `\\uXXXX`. A shell signer that pipes through plain `jq --sort-keys -c`
emits the raw UTF-8 byte instead, signs different bytes than Bone verifies, and
gets a 401 it cannot debug — the secret matches, the timestamp is fine, the JSON
is valid, and the only difference is an encoding nobody looks at.

Two defects, one path, found 2026-07-27 while reviewing why gitleaks logged
"notification POST returned HTTP 401 — findings ingested OK, audit only" every
single night:

  * `jq -a` missing. The gitleaks body carries "…and N more." whenever a scan
    finds more than three — so the case that mattered was never ASCII. On a
    Czech-operated estate this is every title with diacritics.
  * `echo` used to pipe the JSON. `echo` expands the `\\n` inside a JSON string
    into a literal control character, jq then refuses the input, and the compact
    body comes back EMPTY — signed and POSTed as nothing.

Neither is visible in a green suite, in a log, or in a manual test with ASCII
input. Hence this gate. `jq -a --sort-keys -c` was verified byte-identical to
Python's `json.dumps(sort_keys=True, separators=(",", ":"))` for both an
ellipsis and a Czech diacritic before it was adopted.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SEARCH_ROOTS = [REPO / "tools", REPO / "files" / "anatomy"]


def _signers() -> list[pathlib.Path]:
    """Shell scripts that sign a Wing/Bone HMAC."""
    out: list[pathlib.Path] = []
    for root in SEARCH_ROOTS:
        for path in root.rglob("*.sh"):
            if "X-Wing-Signature" in path.read_text(errors="replace"):
                out.append(path)
    return sorted(out)


def test_there_are_signers_to_check() -> None:
    """A gate that finds nothing passes everything."""
    assert _signers(), "no HMAC signers found — this gate is measuring nothing"


def test_every_signer_escapes_non_ascii() -> None:
    """`jq -a` or the signature breaks on the first non-ASCII character."""
    offenders: list[str] = []
    for path in _signers():
        for ln, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if "jq" not in line or "sort-keys" not in line:
                continue
            if not re.search(r"jq\s+(-a\b|--ascii-output)", line):
                offenders.append(f"{path.relative_to(REPO)}:{ln} {line.strip()}")
    assert not offenders, (
        "an HMAC signer canonicalises without `jq -a`. Bone verifies against Python "
        "json.dumps output, which escapes non-ASCII to \\uXXXX — so the first accented "
        "character produces a 401 whose cause is invisible (secret matches, timestamp "
        "fine, JSON valid). Offenders:\n  " + "\n  ".join(offenders)
    )


def test_no_signer_pipes_its_body_through_echo() -> None:
    """`echo` expands \\n inside a JSON string and jq then rejects the body."""
    offenders: list[str] = []
    for path in _signers():
        for ln, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if "sort-keys" not in line:
                continue
            if re.search(r'echo\s+"\$', line):
                offenders.append(f"{path.relative_to(REPO)}:{ln} {line.strip()}")
    assert not offenders, (
        "an HMAC signer pipes its JSON body through `echo`, which expands the \\n "
        "inside a JSON string into a literal control character. jq refuses the input, "
        "the compact body is EMPTY, and an empty body is what gets signed and POSTed. "
        "Use printf '%s'. Offenders:\n  " + "\n  ".join(offenders)
    )


def test_bone_still_reserialises_so_this_gate_is_still_needed() -> None:
    """If Bone ever verifies the RAW body, these rules stop being load-bearing.

    Pinned so the gate cannot outlive its reason and quietly enforce a rule that
    no longer matches the verifier.
    """
    main = (REPO / "files" / "anatomy" / "bone" / "main.py").read_text(errors="replace")
    assert re.search(r"json\.dumps\(.*sort_keys=True", main), (
        "Bone no longer re-serialises the body before verifying the HMAC. If it now "
        "verifies the raw bytes, revisit this gate: `jq -a` would no longer be required "
        "(and the two sides must not disagree about which one is canonical)."
    )
