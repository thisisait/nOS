"""One tool result of non-UTF-8 bytes must not be able to kill a session.

MEASURED 2026-08-17, the surveyor's first live run. Sixth tool call:

    verb=tree args=[/Users/pazny/wing]

`tree` walked a filesystem, filesystems are not UTF-8, and the bytes it
returned went straight into the conversation. From there:

  * `json_encode` refuses the whole request body — not the offending field,
    the body — so the primary backend threw `Malformed UTF-8 characters`;
  * `serveFallback` built the fallback client and it threw the SAME error,
    because the poison is in the conversation, not in the provider;
  * the session ended `stop_reason: error` at 13,054 input tokens with no
    report;
  * and the audit row that would explain it is the literal `0` — what
    `json_encode` returns on failure — so the ONE event a reader needs is
    the one event that did not record.

A single unlucky byte from an ordinary read-only command, and every path out
fails identically. That is not a provider problem and no retry helps.

TWO CAUSES, one fix. The obvious cause is the filesystem. The second is ours:
`MAX_OUTPUT_BYTES` truncates with `substr()` at 8 KiB, which can land
mid-codepoint and MANUFACTURE invalid UTF-8 from output that was clean. So
the substitution has to run AFTER the truncation, and this gate pins that
order — a fix applied before the cut would look right and still ship the bug.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "files/anatomy/wing/app/AgentKit/Tools/BashReadOnlyTool.php"


def _src() -> str:
    return TOOL.read_text(encoding="utf-8")


def test_the_output_path_this_gate_describes_still_exists():
    """Positive control — a renamed constant would make the order check below
    silently vacuous."""
    src = _src()
    assert "MAX_OUTPUT_BYTES" in src, "the output cap is gone; this gate's premise has changed"
    assert "$combined" in src, "the combined-output variable is gone"


def test_a_tool_result_is_forced_into_valid_utf8():
    src = _src()
    assert "mb_check_encoding" in src, (
        "the tool no longer checks its output's encoding. One `tree`, `cat` or "
        "`grep` over a file with non-UTF-8 bytes again kills the session on "
        "every provider at once."
    )
    assert "mb_convert_encoding" in src, "nothing substitutes the invalid bytes"


def test_the_substitution_runs_AFTER_the_truncation():
    """Order is the whole fix. `substr()` at a byte offset can cut a multi-byte
    codepoint in half and produce invalid UTF-8 from valid output — so a
    substitution placed before the cut fixes the filesystem's bytes and then
    reintroduces the same defect one line later."""
    src = _src()
    cut = src.index("MAX_OUTPUT_BYTES) .")          # inside the truncation branch
    fix = src.index("mb_check_encoding")
    assert fix > cut, (
        "the UTF-8 substitution happens before the 8 KiB truncation. The cut "
        "can split a codepoint, so the result can still be unencodable — and "
        "it would look fixed."
    )


@pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH")
def test_the_substitution_actually_makes_a_payload_encodable():
    """A reader, not the code under test: run PHP and confirm the round trip.

    Asserting that two function names appear in a file is a claim about the
    source. This is a claim about the behaviour.
    """
    probe = r"""
$bad = "before " . chr(0xFF) . chr(0xFE) . " after";
if (mb_check_encoding($bad, 'UTF-8')) { echo "CONTROL-FAILED"; exit(1); }
if (json_encode(['c' => $bad]) !== false) { echo "CONTROL-FAILED"; exit(1); }
$fixed = mb_convert_encoding($bad, 'UTF-8', 'UTF-8');
if (!mb_check_encoding($fixed, 'UTF-8')) { echo "NOT-FIXED"; exit(1); }
if (json_encode(['c' => $fixed]) === false) { echo "STILL-UNENCODABLE"; exit(1); }
echo "OK";
"""
    out = subprocess.run(["php", "-r", probe], capture_output=True, text=True)
    assert out.stdout.strip() == "OK", (
        f"the substitution PHP uses does not do what the fix assumes: "
        f"{out.stdout.strip()!r} {out.stderr.strip()!r}"
    )
    assert out.returncode == 0


def test_the_model_is_told_where_its_commands_run():
    """The other half of the same run, and a different bug with one symptom.

    The tool has been anchored to `NOS_REPO_ROOT` since 2026-08-16, and the
    surveyor STILL spent its entire session under ~/wing: `cat
    ~/wing/app/CLAUDE.md`, `ls ~/wing`, `cat ~/wing/CLAUDE.md` — absolute,
    confident, wrong. Nothing had told it where it stood, so it reasoned from
    the only path it had ever seen: the deployed location of its own
    definition. Anchoring the TOOL and informing the MODEL are two jobs.
    """
    src = _src()
    assert "cwdNotice" in src, (
        "the tool schema no longer tells the model its working directory; an "
        "agent has no way to learn where the checkout is."
    )
    notice = src[src.index("private static function cwdNotice"):]
    notice = notice[: notice.index("public function schema")]
    assert "NOS_REPO_ROOT" in notice, "the notice does not resolve the same root the spawn uses"
    assert "is_dir(" in notice, (
        "the notice does not check the root exists, so it can confidently "
        "announce a directory the commands will not run in."
    )
    assert "unset" in notice, (
        "there is no branch for the unset case — an agent would be told "
        "nothing rather than told to establish where it is."
    )
