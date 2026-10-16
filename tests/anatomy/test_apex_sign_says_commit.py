"""apex-sign --confirm ends by printing the commit that records the signature.

2026-10-16 the operator signed and pushed: --confirm had only written the digest into
ruling.yml, the push carried the old one, and origin/dev held a ruling its signature
did not match. The signature exists only once it is committed, so the tool says how.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_confirm_prints_the_commit_that_records_it(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("apex_sign", REPO / "tools/apex-sign.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ruling = tmp_path / "files/anatomy/apex/ruling.yml"
    ruling.parent.mkdir(parents=True)
    ruling.write_text("nodes: {}\nsigned_digest: 0000\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "RULING", ruling)
    monkeypatch.setattr(sys, "argv", ["apex-sign.py", "--confirm"])
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "git commit" in out and "files/anatomy/apex/ruling.yml" in out, out
