"""A test fixture that holds a real credential publishes it.

WHAT HAPPENED, 2026-08-05 13:03 → 2026-08-06 03:01 (found), commit 710be435.

Building the face's Anatomy/Pulse view, a pulse_jobs row was needed as a test
fixture, so a real one was copied out of the live database. Two of its three env
values were replaced with obvious placeholders — `wing_live_token_value_here_…`
and `hunter2hunter2hunter2` — and the third was not. That third was
`WING_EVENTS_HMAC_SECRET`, byte-identical to the live `bone_secret`, and
`thisisait/nOS` is a PUBLIC repository.

The sanitising was real and it was incomplete, which is the ordinary shape of
this mistake: nobody pastes a secret on purpose, they miss one of three.

WHAT CAUGHT IT was the nightly gitleaks job, fourteen hours later, and it caught
it correctly — `exit 1`, one new finding, notification emitted. Nothing was
broken about the detector. But fourteen hours is fourteen hours of a public
push, and gitleaks cannot run before the commit exists. This gate runs in the
same pytest sweep as everything else, so it fails while the value is still in
a working tree.

WHAT THIS CHECKS, and why it is host-independent: not "is this string the live
secret" — CI has no `~/.nos/secrets.yml` and a host-dependent gate is one that
passes everywhere it matters least. Instead: a fixture value assigned to a
secret-shaped KEY must LOOK like a placeholder. A 64-hex blob does not. The
rule is cheap to satisfy (say `FAKE_…` and the gate is happy) and it is exactly
the discipline that was applied to two of the three values already.

SCOPE: fixtures and test files only. Production code reads secrets from the
environment and is covered by other gates; this is about the one place where
writing a literal credential is a normal-looking thing to do.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Where fixtures live. Vendored trees and build output are excluded — they are
#: not ours to edit and node_modules would dominate the runtime.
FIXTURE_GLOBS = (
    "files/anatomy/face/src/**/*.test.ts",
    "files/anatomy/face/src/**/*.spec.ts",
    "tests/**/*.py",
    "tests/**/*.ts",
)
EXCLUDE_PARTS = {"node_modules", ".svelte-kit", "build", "dist", "__pycache__"}

#: A key whose value is a credential, in a DATA position.
#:
#: The first draft matched seven prose lines — `assert re.search(r"^gitlab_api_
#: token:", …)` and friends — because the value class allowed newlines, so it
#: swallowed an assertion message on the following line. Two constraints fix it
#: and both are true of every real credential:
#:   * the value is on ONE line (`[^'"\n]`)
#:   * the key sits at the start of a line or after `{` or `,` — a dict/object
#:     key, not a word inside a regex or an assertion string
SECRET_KEY = re.compile(
    r"(?:^|[{,])\s*['\"]?"
    r"([A-Za-z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|APIKEY|API_KEY|PRIVATE_KEY)"
    r"[A-Za-z0-9_]*)['\"]?\s*[:=]\s*['\"]([^'\"\n]{16,})['\"]",
    re.IGNORECASE | re.MULTILINE,
)

#: Any of these in the VALUE marks it as deliberately not real. Deliberately
#: generous: the goal is to make honesty easy, not to police wording.
PLACEHOLDER_MARKERS = (
    "fake", "dummy", "example", "placeholder", "sample", "test", "notreal",
    "not_a_real", "not-a-real", "changeme", "redacted", "xxx", "here",
    "hunter2", "s3cret", "secret_value", "your-", "your_", "<", "{{",
)


#: Keys that hold a REFERENCE to a credential rather than the credential —
#: `"token_var": "grafana_admin_api_token"` names a variable, and pointing at a
#: secret is the correct pattern, not a leak of one.
REFERENCE_KEY_SUFFIXES = ("_var", "_name", "_env", "_path", "_ref", "_key")


def _fixture_files() -> list[Path]:
    seen: set[Path] = set()
    for pattern in FIXTURE_GLOBS:
        for path in REPO.glob(pattern):
            if EXCLUDE_PARTS & set(path.parts):
                continue
            if path.is_file():
                seen.add(path)
    return sorted(seen)


def _looks_like_a_placeholder(value: str) -> bool:
    low = value.lower()
    if any(marker in low for marker in PLACEHOLDER_MARKERS):
        return True
    # A repeated run (aaaa…, 0000…) is nobody's real credential.
    if len(set(value)) <= 4:
        return True
    # Prose, not a credential. Every secret this estate mints is a single
    # unbroken run of characters; a value with a space is a sentence that
    # happened to sit beside a secret-shaped key.
    if " " in value:
        return True
    return False


def test_the_sweep_actually_reads_fixtures():
    """Positive control — an empty file list makes the gate below vacuous."""
    files = _fixture_files()
    assert len(files) > 50, (
        f"only {len(files)} fixture files matched; the globs have stopped "
        f"finding tests and this gate is blind"
    )
    assert any(p.name == "pulse.test.ts" for p in files), (
        "the file this gate was written for is not in the sweep"
    )


def test_no_fixture_assigns_a_credential_shaped_literal():
    offenders = []
    for path in _fixture_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in SECRET_KEY.finditer(text):
            key, value = match.group(1), match.group(2)
            if key.lower().endswith(REFERENCE_KEY_SUFFIXES):
                continue
            if _looks_like_a_placeholder(value):
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(
                f"  {path.relative_to(REPO)}:{line}  {key} = "
                f"{value[:6]}…{value[-4:]} ({len(value)} chars)"
            )
    assert not offenders, (
        "a test fixture assigns something credential-shaped to a secret-shaped "
        "key. On 2026-08-05 that was the live bone_secret, pushed to a PUBLIC "
        "repo and found fourteen hours later by the nightly gitleaks run. If "
        "the value is not real, say so in the value itself — `FAKE_…` is "
        "enough, and it is what two of that fixture's three values already "
        "did:\n" + "\n".join(offenders)
    )
