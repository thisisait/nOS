"""Anatomy gate — gitleaks nightly-scan uses the 8.x positional repo form.

gitleaks 8.18 redesigned the CLI: the repo/source is now a POSITIONAL arg
(`gitleaks git [flags] [repo]`); the old `--source=<dir>` flag was removed and
now returns "unknown flag". With the legacy `--source=` form the binary exits
2 *before scanning anything*, so every nightly Pulse scan failed silently —
zero findings ingested, no notification ever emitted, Wing Inbox stayed empty.

The script was fixed to call `gitleaks git "$SCAN_DIR" --report-format=json
--report-path=... --exit-code=0 ...`. This gate is a pure text/regex check
over the shell script (no live gitleaks needed) so the regression can't
silently come back:

  1. The removed `--source` flag never appears in a gitleaks invocation.
  2. The scan dir is passed POSITIONALLY to `gitleaks git`/`gitleaks dir`.
  3. The downstream parser contract survives: `--report-format=json`,
     `--report-path`, and `--exit-code=0` are all still passed.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "files/anatomy/plugins/gitleaks/skills/run-gitleaks.sh"


def _gitleaks_invocation(src: str) -> str:
    """Return the line-continued `gitleaks git|dir ...` command block.

    Joins the backslash-continued invocation into a single logical line so a
    regex can see all of its flags at once.
    """
    # Anchor on the real command (positional $SCAN_DIR) so a prose mention of
    # `gitleaks git [flags]` inside an explanatory comment can't be matched.
    m = re.search(
        r'gitleaks\s+(?:git|dir)\s+"?\$\{?SCAN_DIR\}?"?.*?'
        r"(?=\n\s*(?:then|fi|echo|[A-Z_]+=|#)|\n\n)",
        src, re.DOTALL)
    assert m, "no `gitleaks git|dir \"$SCAN_DIR\" ...` invocation found in run-gitleaks.sh"
    # Collapse line continuations into one logical line.
    return re.sub(r"\\\s*\n\s*", " ", m.group(0))


def test_script_exists():
    assert SCRIPT.is_file(), f"missing scan skill: {SCRIPT}"


def test_no_removed_source_flag_in_invocation():
    """The gitleaks invocation must not carry the removed --source flag.

    Comments in the script legitimately *mention* `--source=` to explain the
    breakage, so the check is scoped to the actual command, not the whole file.
    """
    invocation = _gitleaks_invocation(SCRIPT.read_text())
    assert "--source" not in invocation, (
        "gitleaks 8.x removed --source; the repo/source is positional. "
        f"Offending invocation:\n{invocation}"
    )


def test_scan_dir_passed_positionally():
    """`gitleaks git "$SCAN_DIR"` (or `gitleaks dir ...`) — dir is positional."""
    src = SCRIPT.read_text()
    pat = re.compile(r'gitleaks\s+(?:git|dir)\s+"?\$\{?SCAN_DIR\}?"?')
    assert pat.search(src), (
        'expected positional form `gitleaks git "$SCAN_DIR"` '
        "(or `gitleaks dir ...`) with the scan dir as a positional arg"
    )


def test_parser_contract_flags_present():
    """Downstream parser contract: JSON report + report-path + exit-code 0."""
    invocation = _gitleaks_invocation(SCRIPT.read_text())
    assert re.search(r"--report-format[=\s]+json", invocation), \
        "--report-format=json missing — Wing parser expects JSON output"
    assert re.search(r"--report-path[=\s]", invocation), \
        "--report-path missing — script reads the JSON report from this file"
    assert re.search(r"--exit-code[=\s]*0", invocation), \
        "--exit-code=0 missing — script signals exit status itself via ingest result"
