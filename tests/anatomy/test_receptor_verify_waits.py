"""The receptor's verify waits for the socket to ANSWER, not only to exist.

Client reinstall 2026-10-16: the flush_handlers restart left the old socket file
in place for a moment, `[ -S sock ]` passed at once and curl got nothing
(code=000000) — a converge failed on a receptor that answered 200 a second later.
Runs the task's real shell with stub curl/stat on PATH."""
from __future__ import annotations

import os
import socket
import subprocess
import tempfile
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
TASK = "[pazny.receptor] Verify — the socket answers this login as a person"


def _script(sock: str) -> str:
    tasks = yaml.safe_load((REPO / "roles/pazny.receptor/tasks/main.yml").read_text())
    t = next(t for t in tasks if t.get("name") == TASK)
    return jinja2.Template(t["ansible.builtin.shell"]).render(receptor_socket=sock)


def _run(tmp_path: Path, answers: list[str]) -> str:
    sock = Path(tempfile.mkdtemp(prefix="rcv", dir="/tmp")) / "r.sock"  # AF_UNIX caps the path near 104 bytes
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(sock))
    os.chmod(sock, 0o600)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (tmp_path / "answers").write_text("\n".join(answers) + "\n")
    # curl answers the next line of `answers` (the last one repeats); a failed connect prints 000 and exits 7.
    (bin_ / "curl").write_text(
        "#!/bin/sh\nf=\"$(dirname \"$0\")/../answers\"\na=$(head -1 \"$f\")\n"
        "[ $(wc -l < \"$f\") -gt 1 ] && sed -i.b 1d \"$f\"\n"
        "printf '%s' \"$a\"\n[ \"$a\" = 000 ] && exit 7\nexit 0\n")
    (bin_ / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for f in ("curl", "sleep"):
        (bin_ / f).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}
    out = subprocess.run(["bash", "-c", _script(str(sock))], env=env, capture_output=True, text=True, timeout=60)
    s.close()
    return out.stdout


def test_a_socket_that_answers_late_still_passes(tmp_path):
    assert "code=200" in _run(tmp_path, ["000", "000", "502", "200"])


def test_a_socket_that_never_answers_fails(tmp_path):
    out = _run(tmp_path, ["000"])
    assert "code=200" not in out and "mode=600" in out
