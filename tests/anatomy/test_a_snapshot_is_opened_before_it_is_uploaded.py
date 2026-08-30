"""The keap-db backup must OPEN its snapshot before shipping it.

MEASURED 2026-08-30, from `~/.nos/backup.log` — 29 nights of the nightly job:

    2026-08-13   no `pages=` line   uploaded 296 MB   logged `keap-db: OK`
    2026-08-30   no `pages=` line   uploaded 310 MB   logged `keap-db: OK`
    every other night                        347 MB   logged `keap-db: OK`

`pages=` is what the in-container node backup prints when it FINISHES. On those
two nights it printed nothing — it died mid-copy — and both truncated files were
compressed, encrypted, uploaded, and recorded as a good backup.

The restore drill found the second one seven hours later:

    keap-db: fetching 2026-08-30/keap-db.gz
    Error: in prepare, file is not a database (26)
    keap-db: UNREADABLE
    ==== nOS restore drill FAILED ====

The first was never noticed by anything.

WHY IT PASSED. The producer branched on `docker exec … test -s "$ctmp"` — the
file exists and is non-empty — and the code's own comment defended it: *"the
pipeline above reports rc for the `while`, not for node"*. That is true, and it
is the whole defect: the backup pipeline ends in `| while read …`, so node's
exit code belonged to the loop and nobody ever saw it. **The success marker was
written by the attempting code**, which is the failure shape this estate has a
doctrine about, sitting in the one place where being wrong is unrecoverable.

Size alone would have caught both nights. Nothing reads size either.

WHAT IS ASSERTED HERE is the shape; the effect was measured live against
`iiab-keap-1` before this file was written:

    live keap.db      rc=0  "snapshot verified nodes/relations/objects=1711/5084/345"
    truncated to 40M  rc=1  "database disk image is malformed"
    5 KB of urandom   rc=1  "file is not a database"   ← the drill's own error
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "roles/pazny.backup/files/backup.sh"


def _body() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _keap_step() -> str:
    """`run_keap_db` only — bounded at the next top-level function.

    A first draft ran to end-of-file and picked up a `rm -f "${tmp}"` from a
    later step, then reported the keap cleanup as incomplete.
    """
    src = _body()
    start = src.index("run_keap_db() {")
    nxt = re.search(r"\n[a-z_]+\(\) \{", src[start + 1:])
    return src[start:start + 1 + nxt.start()] if nxt else src[start:]


def _upload_branch(step: str) -> str:
    """The `if` that decides whether to ship — the one asking `test -s`, not
    the earlier probe that asks whether the container is up at all. A first
    draft matched the probe and reported a correct script as broken."""
    m = re.search(r"if docker exec[^\n]*test -s.*?; then", step, re.S)
    assert m, "the upload branch no longer asks `test -s` at all — re-read this gate"
    return m.group(0)


def test_a_verifier_exists_and_opens_the_file() -> None:
    """`stat` answers "is there a file". Only opening it answers "is it a
    database", and that is the difference the two bad nights turned on."""
    src = _body()
    assert "keap_verify_js()" in src, "the snapshot verifier is gone"
    verifier = src[src.index("keap_verify_js()"):src.index("KEAPVERIFYJS\n}")]
    assert "DatabaseSync" in verifier and "count(*)" in verifier, (
        "the verifier no longer opens the snapshot and counts rows — a check "
        "that only stats the file is the one that shipped a truncated backup")
    assert "process.exit(1)" in verifier, "it cannot fail, so it is not a check"


def test_the_upload_does_not_branch_on_test_s_alone() -> None:
    step = _keap_step()
    branch = _upload_branch(step)
    assert "keap_verify_js" in branch, (
        "the snapshot is uploaded on `test -s` alone. That accepted a "
        "truncated file on 2 of 29 nights and logged `keap-db: OK` for both.")


#: A pipeline's rc is its LAST stage. Anything here at the end of the verify
#: pipeline swallows the verdict — `tee` and `cat` always succeed, a `while`
#: reports the loop. The first draft of the FIX ended in `| tee -a LOG_FILE`
#: and would have discarded the verifier's exit code exactly the way the bug
#: discarded node's; this gate did not catch it, so it was rewritten to.
RC_SWALLOWERS = ("tee", "while", "cat", "true", "sed", "awk", "grep")


def test_the_verify_pipeline_ends_where_its_exit_code_is_read() -> None:
    """THE ROOT CAUSE, pinned — and the trap the fix itself fell into once.

    `backup.sh` does not `set -o pipefail`, so a verifier whose pipeline ends
    in anything that always succeeds is decoration. The branch must end at the
    command that carries node's verdict.
    """
    branch = _upload_branch(_keap_step())
    # The verify pipeline is the substitution or the last &&-clause; take
    # everything after the last `docker exec` and look at what follows it.
    after = branch.rsplit("docker exec", 1)[-1]
    # The command NAME only: a stage can end `cat)"; then`, and a first draft
    # compared the whole token and let `cat` through.
    stages = [re.match(r"[a-z_]+", seg.strip().lstrip("\\ ")) for seg in after.split("|")[1:]]
    offenders = [m.group(0) for m in stages if m and m.group(0) in RC_SWALLOWERS]
    assert not offenders, (
        f"the verify pipeline continues past `docker exec` into {offenders}, "
        "whose exit code the `if` will read instead of node's — the same way "
        "the bug hid. Use a command substitution and log the output.\n" + branch)
    assert 'vout="$(' in branch or "$(keap_verify_js" in branch, (
        "the verifier's output is not captured, so either it is piped (rc lost) "
        "or it is never logged (an operator sees a failure with no reason)")


def test_the_failure_message_says_what_was_wrong() -> None:
    """`produced nothing` is what it used to say, and it was wrong twice: the
    file existed both times. An operator reading the log has to be able to tell
    "missing" from "corrupt"."""
    step = _keap_step()
    assert "NOT A READABLE DATABASE" in step, (
        "the fallback message still claims the snapshot was absent, which is "
        "not what a failed verify means")


def test_the_scratch_files_are_all_cleaned_up() -> None:
    """Three temp paths in the container now, not two. A leaked verifier
    script is a stale copy of a check, which is worse than none."""
    # `docker exec … rm -f` only. The host-sqlite3 fallback in the same
    # function removes its own `${tmp}`, which has nothing to do with the
    # container's three paths — a first draft demanded all three there and
    # reported a correct script as broken.
    removals = re.findall(r'docker exec [^\n]*rm -f ([^\n]*)', _keap_step())
    assert removals, "nothing is cleaned up inside the container"
    for line in removals:
        for path in ("${ctmp}", "${cjs}", "${cvjs}"):
            assert path in line, (
                f"a container cleanup forgets {path}: {line.strip()}")
