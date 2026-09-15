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
  4. The FAKE_hmac pulse.test.ts fixture is allowlisted; a minted HMAC still fires.
"""

from __future__ import annotations

import json
import pathlib
import re
import secrets
import shutil
import subprocess
import tomllib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "files/anatomy/plugins/gitleaks/skills/run-gitleaks.sh"
CONFIG = REPO / ".gitleaks.toml"
PULSE_FIXTURE = REPO / "files/anatomy/face/src/lib/anatomy/pulse.test.ts"
GITLEAKS = shutil.which("gitleaks")
_HMAC_ASSIGN = re.compile(r"WING_EVENTS_HMAC_SECRET:\s*'([^']+)'")


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


def _allowlist_regexes(toml_text: str) -> list[str]:
    cfg = tomllib.loads(toml_text)
    blocks = []
    if "allowlist" in cfg:
        blocks.append(cfg["allowlist"])
    blocks.extend(cfg.get("allowlists") or [])
    regexes: list[str] = []
    for block in blocks:
        regexes.extend(block.get("regexes") or [])
    return regexes


def _fixture_hmac_secret() -> str:
    text = PULSE_FIXTURE.read_text(encoding="utf-8")
    match = _HMAC_ASSIGN.search(text)
    assert match, f"pulse.test.ts no longer assigns WING_EVENTS_HMAC_SECRET: {PULSE_FIXTURE}"
    return match.group(1)


def _gitleaks_dir(target: pathlib.Path, config: pathlib.Path, report: pathlib.Path) -> list[dict]:
    subprocess.run(
        [
            GITLEAKS, "dir", str(target),
            "--config", str(config),
            "--no-banner",
            "--exit-code=0",
            "--report-format=json",
            "--report-path", str(report),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = report.read_text(encoding="utf-8") if report.exists() else "[]"
    data = json.loads(raw or "[]")
    return data or []


def test_fake_hmac_fixture_is_allowlisted():
    """The pulse.test.ts HMAC fixture must be covered by a verified-FP regex.

    Allowlisting a real-shaped secret is the failure this gate exists to catch.
    """
    secret = _fixture_hmac_secret()
    assert secret.startswith("FAKE_"), (
        "pulse.test.ts HMAC fixture is no longer self-declaring; rename it, "
        "do not allowlist a credential-shaped value"
    )
    regexes = _allowlist_regexes(CONFIG.read_text(encoding="utf-8"))
    assert regexes, ".gitleaks.toml has no allowlist regexes"
    covering = [rx for rx in regexes if re.search(rx, secret)]
    assert covering, (
        f"FAKE_hmac fixture is not allowlisted: {secret!r}. "
        "Add a format-anchored verified-FP regex; do not path-allowlist the file "
        "(that would hide a later real secret in the same fixture)."
    )
    minted = secrets.token_hex(32)
    leaked = [rx for rx in regexes if re.search(rx, minted)]
    assert not leaked, (
        f"allowlist regex {leaked!r} matches a minted 64-hex secret; "
        "real credentials must never be allowlisted"
    )


def test_allowlist_without_the_fake_rule_no_longer_covers_the_fixture():
    """RED control: drop the FAKE_ regexes and the fixture is uncovered."""
    secret = _fixture_hmac_secret()
    regexes = [
        rx for rx in _allowlist_regexes(CONFIG.read_text(encoding="utf-8"))
        if "FAKE_" not in rx
    ]
    assert not any(re.search(rx, secret) for rx in regexes), (
        "the fixture is still covered after dropping FAKE_ regexes — "
        "this gate cannot go red when the allowlist is missing"
    )


@pytest.mark.skipif(not GITLEAKS, reason="gitleaks binary not on PATH")
def test_gitleaks_quiets_the_fake_hmac_fixture_and_still_fires_on_a_real_shape(tmp_path):
    """T1: fixture file is quiet; a real-shaped HMAC against the same config fires.

    RED: config with no allowlist still reports a real-shaped sample (and the
    taxonomy FP). FAKE_ values are also a gitleaks 8.30+ stopword, so the live
    HIGH-without-allowlist control is the real-shaped sample, not the fixture.
    """
    secret = _fixture_hmac_secret()
    fixture_findings = _gitleaks_dir(PULSE_FIXTURE, CONFIG, tmp_path / "fixture.json")
    assert not any((f.get("Secret") or "") == secret for f in fixture_findings), (
        f"allowlisted fixture still HIGH: {fixture_findings!r}"
    )

    minted = secrets.token_hex(32)
    sample = tmp_path / "real-shaped.txt"
    sample.write_text(f"WING_EVENTS_HMAC_SECRET: '{minted}'\n", encoding="utf-8")
    with_allowlist = _gitleaks_dir(sample, CONFIG, tmp_path / "real.json")
    assert any((f.get("Secret") or "") == minted for f in with_allowlist), (
        "real-shaped HMAC was not detected — the allowlist has swallowed "
        f"generic-api-key: {with_allowlist!r}"
    )

    bare = tmp_path / "bare.toml"
    bare.write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
    without = _gitleaks_dir(sample, bare, tmp_path / "real-bare.json")
    assert any((f.get("Secret") or "") == minted for f in without), (
        "real-shaped HMAC silent even with an empty allowlist; detector is broken"
    )
