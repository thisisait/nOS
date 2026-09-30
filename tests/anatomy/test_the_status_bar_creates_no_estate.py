"""The tmux status bar never creates ~/.nos.

~/.nos is the estate's side-car. The status bar ran `mkdir -p ~/.nos`, so a
leave that removed it saw it back within seconds while nos-cc was open
(2026-09-30). Run the script against an empty HOME and look.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_an_estate_less_home_stays_estate_less(tmp_path: Path) -> None:
    env = {**os.environ, "HOME": str(tmp_path), "TMPDIR": str(tmp_path / "t")}
    env.pop("NOS_STATUSLINE_CACHE", None)
    (tmp_path / "t").mkdir()
    subprocess.run(["bash", str(REPO / "tools/nos-statusline.sh")], env=env,
                   capture_output=True, text=True, timeout=120)
    assert not (tmp_path / ".nos").exists(), "the status bar recreated ~/.nos"
