"""anatomy-graph-gen --refreeze writes the layout pin as UTF-8, not \\u escapes.

2026-10-20: the refreeze wrote graphLayout.force.pin.json with json.dumps
defaults, so the comment's § ≤ — became \\u00a7 \\u2264 \\u2014 and every
refreeze showed a noisy diff. The vitest repin (JSON.stringify) keeps them.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PIN = REPO / "files/anatomy/face/src/lib/anatomy/graphLayout.force.pin.json"


def _gen():
    spec = importlib.util.spec_from_file_location("_gen", REPO / "tools" / "anatomy-graph-gen.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def test_the_refreeze_writer_keeps_the_literal_characters():
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    out = _gen().pin_json(pin)
    assert json.loads(out) == pin
    for ch in "§≤—":
        assert ch in out, f"the refreeze writer escaped {ch!r}"
    assert "\\u" not in out


def test_the_committed_pin_holds_utf8_not_escapes():
    assert "\\u" not in PIN.read_text(encoding="utf-8"), (
        "graphLayout.force.pin.json carries \\u escapes — a refreeze used json.dumps defaults")
