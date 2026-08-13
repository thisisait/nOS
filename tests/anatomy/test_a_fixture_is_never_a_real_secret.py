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

import collections
import math
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


#: A credential-shaped literal sitting in NO key position at all.
#:
#: THE BLIND SPOT, measured 2026-08-13 when GitGuardian mailed about the public
#: repo. `SECRET_KEY` above requires `KEY: 'value'` — a key in a data position.
#: The 2026-08-06 sanitising fixed the fixture's keyed occurrence and left a
#: SECOND copy of the same live-then value as a bare element of an array:
#:
#:     for (const secret of [
#:         '0c05…c751',        <- no key precedes it; this gate could not see it
#:
#: It stayed published for eight further days, and because the fixture no longer
#: produced that string, the assertion hunting for it could never fail again:
#: one secret exposed, one test green and vacuous, from the same half-fix.
#:
#: SEPARATING SECRETS FROM BINARY FIXTURES BY MEASUREMENT, not by an exception
#: list. Shannon entropy over the literal, measured the same day:
#:
#:     the retired key that leaked            3.85
#:     `openssl rand -hex 32`, 12 samples     3.69 – 3.87   (how this estate mints)
#:     hex-encoded PNG in test_devlog_media   2.40, 2.90    (legitimate fixtures)
#:
#: A floor of 3.5 clears both PNGs and sits below every minted key, so binary
#: test data stays legal without being named — and a fixture nobody has written
#: yet is covered on the day it lands.
BARE_LITERAL = re.compile(r"""['"]([A-Za-z0-9+/=_\-]{32,})['"]""")
HEX_ONLY = re.compile(r"^[0-9a-fA-F]+$")
HEX_ENTROPY_FLOOR = 3.5
#: Base64-ish alphabets carry more symbols, so the same randomness scores
#: higher; the floor rises with it and mixed case is required, which excludes
#: the snake_case identifiers and slash-bearing paths that dominate these files
#: (50 literals ≥32 chars, of which 48 are paths or env-var names).
B64_ENTROPY_FLOOR = 4.0


def _entropy(value: str) -> float:
    counts = collections.Counter(value)
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _looks_like_a_credential(value: str) -> bool:
    if HEX_ONLY.match(value):
        return _entropy(value) > HEX_ENTROPY_FLOOR
    mixed = (
        re.search(r"[a-z]", value)
        and re.search(r"[A-Z]", value)
        and re.search(r"\d", value)
    )
    return bool(mixed) and _entropy(value) > B64_ENTROPY_FLOOR


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


def test_the_classifier_tells_a_minted_key_from_a_binary_fixture():
    """Positive control for the entropy floor, so the rule below is not vacuous.

    A random 32-byte hex key — what `openssl rand -hex 32` yields and what every
    Pattern-B secret in this estate is — must be classified as a credential; the
    PNG header that opens every image fixture must not. No real secret appears
    here: the key is generated, and the PNG bytes are a public file-format magic.
    """
    import random

    rng = random.Random(20260813)
    minted = "".join(rng.choice("0123456789abcdef") for _ in range(64))
    assert _looks_like_a_credential(minted), (
        f"a freshly minted 64-hex key scores {_entropy(minted):.2f}, below the "
        f"{HEX_ENTROPY_FLOOR} floor. The floor has drifted above what this "
        "estate actually mints, so the gate below now passes everything."
    )
    png = "89504e470d0a1a0a0000000d494844520000000100000001080600000" "01f15c489"
    assert not _looks_like_a_credential(png), (
        "the PNG magic header now reads as a credential; legitimate binary "
        "fixtures would have to be renamed to satisfy a secret gate."
    )


def test_no_fixture_holds_a_credential_shaped_literal_without_a_key():
    offenders = []
    for path in _fixture_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in BARE_LITERAL.finditer(text):
            value = match.group(1)
            if _looks_like_a_placeholder(value):
                continue
            if not _looks_like_a_credential(value):
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(
                f"  {path.relative_to(REPO)}:{line}  "
                f"{value[:6]}…{value[-4:]} ({len(value)} chars, "
                f"entropy {_entropy(value):.2f})"
            )
    assert not offenders, (
        "a credential-shaped literal sits in a fixture with no key to name it. "
        "The keyed gate above cannot see this position, and that is exactly "
        "where the 2026-08-06 sanitising left a second copy of a live secret — "
        "published for eight more days, while the assertion that quoted it "
        "silently stopped being able to fail. Read such needles OUT of the "
        "fixture instead of repeating them, so the two cannot drift:\n"
        + "\n".join(offenders)
    )
