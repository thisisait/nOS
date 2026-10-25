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
PAIRS = [(sec, i, o) for sec in SPEC_DOC["sections"] if sec not in ("clean", "known_values") for i, o in FX[sec]]


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


def test_known_values_go_under_any_key():
	bad = [(c, scrub_text(c["in"], known=c["known"])) for c in FX["known_values"]
	       if scrub_text(c["in"], known=c["known"]) != c["out"] or scrub_text(c["out"], known=c["known"]) != c["out"]]
	assert not bad, "\n".join(f"{c['in']!r} known {c['known']!r}\n   want {c['out']!r}\n    got {g!r}" for c, g in bad)


def test_the_daemon_scrubs_the_values_it_handed_the_job(monkeypatch):
	"""A resolved secret: reference and a literal under a secret-shaped key, printed under keys
	no pattern calls secret, in both tails and in the daemon-exception message."""
	from unittest.mock import MagicMock

	from pulse import daemon, secrets
	from pulse.runners.subprocess import RunResult

	ref, lit = "fake-resolved-value-1", "fake-literal-value-2"
	monkeypatch.setattr(secrets, "load_store", lambda: {"fake_name": ref})
	env = {"WING_API_TOKEN": "secret:fake_name", "MAIL_PASSWORD": lit, "NOS_AGENT_NAME": "plain"}
	out = f"url?x={ref}&y={lit} agent=plain"
	results = iter([RunResult(0, 0.01, out, f"echo {lit}", False)])

	def execute(command, args, *, timeout_s, env=None, cwd=None):
		r = next(results, None)
		if r is None:
			raise RuntimeError(f"boom {ref}")
		return r

	monkeypatch.setattr(daemon.sp_runner, "execute", execute)
	monkeypatch.setattr(daemon, "paused_hold", lambda job: None)
	d = daemon.PulseDaemon(MagicMock(dry_run=False), wing=MagicMock())
	for _ in range(2):
		d._run_in_thread("j", "r", "/bin/true", [], 5.0, dict(env))
	first, second = (c.kwargs for c in d.wing.post_run_finish.call_args_list)
	assert first["stdout_tail"] == "url?x=<REDACTED>&y=<REDACTED> agent=plain"
	assert first["stderr_tail"] == "echo <REDACTED>"
	assert second["stderr_tail"] == "daemon exception: boom <REDACTED>"


def test_daemon_applies_scrub_before_posting():
	"""Both tails and the daemon-exception message pass through scrub_text."""
	src = (PULSE_PKG / "pulse/daemon.py").read_text()
	assert "from . import redact" in src
	for site in ("redact.scrub_text(result.stdout_tail, known)", "redact.scrub_text(result.stderr_tail, known)",
	             'redact.scrub_text(f"daemon exception: {e}", known)'):
		assert site in src, f"daemon.py must call {site}"
