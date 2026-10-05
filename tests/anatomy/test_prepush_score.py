"""Gate: tools/prepush-score.py scores the exact push range before nos-push pushes.

Row operator-session-threat-model child (2), doctrine
ssot/doctrine/session-threat-model.md. Deterministic signals come first and carry
file:line; the local model only adds per-aspect scores, and a model that fails
is UNAVAILABLE, never a number. No live model: the call is stubbed.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "prepush-score.py"
FAKE_SECRET = "sk-FAKEnotreal0123456789abcdefABCDEF0123456789"


def _tool():
    spec = importlib.util.spec_from_file_location("_prepush_score", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "dev")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    _write(tmp_path, "tools/thing.py", "def limit():\n    return 3\n")
    _write(tmp_path, "tests/anatomy/test_thing.py",
           "import tools.thing  # tools/thing.py\n\ndef test_limit():\n"
           "    assert limit() == 3\n    assert limit() < 5\n")
    _write(tmp_path, "README.txt", "hello\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _commit(repo: Path, files: dict[str, str]) -> tuple[str, str]:
    base = _git(repo, "rev-parse", "HEAD")
    for rel, text in files.items():
        _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return base, _git(repo, "rev-parse", "HEAD")


def _signals(report: dict, aspect: str) -> list[dict]:
    return [s for s in report["signals"] if aspect in s["aspects"]]


def test_a_gate_weakened_with_its_code_fires_laundering(repo):
    base, head = _commit(repo, {
        "tools/thing.py": "def limit():\n    return 9\n",
        "tests/anatomy/test_thing.py": "import tools.thing  # tools/thing.py\n\n"
                                       "def test_limit():\n    assert limit() == 9\n",
    })
    report = _tool().collect(repo, base, head)
    hits = _signals(report, "laundering")
    assert hits and report["det"]["laundering"] >= 50
    assert any(s["file"] == "tests/anatomy/test_thing.py" and s["line"] > 0 for s in hits)


def test_a_launch_agent_fires_persistence(repo):
    base, head = _commit(repo, {
        "roles/x/templates/com.example.helper.plist.j2":
            "<plist><dict><key>RunAtLoad</key><true/></dict></plist>\n",
    })
    report = _tool().collect(repo, base, head)
    assert any("persistence" in s["label"] for s in _signals(report, "session"))


def test_a_secret_path_read_fires_secrets(repo):
    base, head = _commit(repo, {
        "tools/peek.py": "import os\nopen(os.path.expanduser('~/.nos/secrets.yml')).read()\n",
    })
    report = _tool().collect(repo, base, head)
    hits = _signals(report, "secrets")
    assert hits and hits[0]["file"] == "tools/peek.py" and hits[0]["line"] == 2


def test_the_checker_changing_is_its_own_top_signal(repo):
    base, head = _commit(repo, {"tools/prepush-score.py": "print('trust me')\n"})
    report = _tool().collect(repo, base, head)
    top = report["signals"][0]
    assert "checker" in top["label"] and "session" in top["aspects"]


def test_a_clean_range_scores_no_signals(repo):
    base, head = _commit(repo, {"tools/thing.py": "def limit():\n    \"\"\"Three.\"\"\"\n    return 3\n"})
    report = _tool().collect(repo, base, head)
    assert report["signals"] == [] and set(report["det"].values()) == {0}


@pytest.mark.parametrize("reply", [
    RuntimeError("connection refused"),
    "not json at all",
    json.dumps({"wider": {"score": 140, "reason": "x"}}),
])
def test_a_failed_model_is_unavailable_not_a_number(repo, reply):
    mod = _tool()
    base, head = _commit(repo, {"README.txt": "hi\n"})
    report = mod.collect(repo, base, head)

    def call(model, prompt):
        if isinstance(reply, Exception):
            raise reply
        return reply

    result = mod.ask_model(report, "stub:1b", call=call)
    assert result["status"] == "UNAVAILABLE" and "scores" not in result
    text = mod.render(report, result, {"checker": "a" * 64, "prompt": "b" * 64})
    model_rows = [ln for ln in text.splitlines() if "model" in ln and "UNAVAILABLE" in ln]
    assert model_rows, text


def test_nos_push_scores_before_it_pushes():
    src = (REPO / "tools" / "nos-push").read_text()
    score = src.find("prepush-score.py")
    push = src.find('git -C "$REPO_DIR" push')
    assert 0 < score < push, "nos-push must run the scorer before git push"
    assert "--strict" in src


def test_the_scorer_never_prints_or_records_a_secret(repo, tmp_path, capsys, monkeypatch):
    mod = _tool()
    base, head = _commit(repo, {
        "tools/peek.py": f"import os\nTOKEN = '{FAKE_SECRET}'\n"
                         "open(os.path.expanduser('~/.nos/secrets.yml')).read()\n",
        "credentials.yml": f"gitea_api_token: {FAKE_SECRET}\n",
    })
    seen = []

    def echo(model, prompt):  # a model that parrots its whole input back
        seen.append(prompt)
        return json.dumps({a: {"score": 50, "reason": prompt[-300:]} for a, _ in mod.ASPECTS})

    monkeypatch.setattr(mod, "_ollama", echo)
    log = tmp_path / "events" / "prepush-scores.jsonl"
    rc = mod.main(["--repo", str(repo), "--range", f"{base}..{head}", "--model", "stub:1b",
                   "--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 0 and seen
    assert FAKE_SECRET not in seen[0], "the secret reached the model"
    assert FAKE_SECRET not in out
    assert FAKE_SECRET not in log.read_text()
    assert re.search(r"secrets", out)


def test_a_model_scoring_zero_against_strong_signals_is_not_a_score(repo):
    """hermes3:8b, 2026-10-04: 0 on all six aspects against 62 signals, printed as a verdict."""
    mod = _tool()
    base, head = _commit(repo, {"tools/prepush-score.py": "# changed\n"})
    report = mod.collect(repo, base, head)
    assert report["det"]["session"] >= 40
    zeros = json.dumps({a: {"score": 0, "reason": "fine"} for a, _ in mod.ASPECTS})
    result = mod.ask_model(report, "stub:1b", call=lambda m, p: zeros)
    assert result["status"] == "UNAVAILABLE" and "evidence ignored" in result["why"]
