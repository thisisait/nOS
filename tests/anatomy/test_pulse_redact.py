"""Anatomy gate — the Pulse output scrub, held to files/anatomy/contracts/redact.yml.

Subprocess output forwarded by Pulse to Wing can carry secrets (env dumps, CLI
password flags, Authorization headers in tracebacks). `pulse.redact.scrub_text`
is the contract's algorithm; medulla/src/pulse/redact.rs is the same algorithm
and its own tests read the same fixture, so the two cannot drift apart.
"""

from __future__ import annotations

import json
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PULSE_PKG = REPO / "files/anatomy/pulse"
SPEC = REPO / "files/anatomy/contracts/redact.yml"
FIXTURE = REPO / "files/anatomy/contracts/redact.fixture.json"

if str(PULSE_PKG) not in sys.path:
	sys.path.insert(0, str(PULSE_PKG))

from pulse.redact import scrub_text  # type: ignore[import-not-found]  # noqa: E402

FX = json.loads(FIXTURE.read_text(encoding="utf-8"))
SPEC_DOC = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
PAIRS = [(sec, i, o) for sec in SPEC_DOC["sections"] if sec != "clean" for i, o in FX[sec]]


def test_the_spec_names_this_fixture_and_these_files():
	assert REPO / SPEC_DOC["fixture"] == FIXTURE
	assert SPEC_DOC["contract_version"] == FX["contract_version"]
	for side in ("producer", "consumer"):
		for path in SPEC_DOC[side]["code"]:
			assert (REPO / path).is_file(), f"{side} names a missing file: {path}"
	assert set(SPEC_DOC["sections"]) == set(FX) - {"contract_version", "why"}


def test_every_section_holds():
	bad = [(sec, i, o, scrub_text(i)) for sec, i, o in PAIRS if scrub_text(i) != o]
	bad += [("clean", c, c, scrub_text(c)) for c in FX["clean"] if scrub_text(c) != c]
	assert not bad, "\n".join(f"[{s}] {i!r}\n   want {w!r}\n    got {g!r}" for s, i, w, g in bad)


def test_scrub_is_idempotent():
	moved = [o for _, _, o in PAIRS if scrub_text(o) != o]
	assert not moved, f"scrubbing an expected value changed it again: {moved}"


def test_the_fixture_is_not_trivial():
	assert all(len(FX[s]) >= 5 for s in SPEC_DOC["sections"])
	assert sum(i != o for _, i, o in PAIRS) >= 80


def test_safe_on_empty_and_none():
	assert scrub_text("") == ""
	assert scrub_text(None) == ""


def test_daemon_applies_scrub_before_posting():
	"""Both tails and the daemon-exception message pass through scrub_text."""
	src = (PULSE_PKG / "pulse/daemon.py").read_text()
	assert "from . import redact" in src
	for site in ("redact.scrub_text(result.stdout_tail", "redact.scrub_text(result.stderr_tail",
	             'redact.scrub_text(f"daemon exception: {e}"'):
		assert site in src, f"daemon.py must call {site}…)"
