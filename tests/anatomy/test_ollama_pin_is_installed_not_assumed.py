"""A pin above the cellar is installed by the role, not by a hand.

Until 2026-09-30 the role could only LINK a pin keg that was already in the
cellar; advancing ollama_version past it failed the converge unless someone
ran `brew upgrade` first (which `brew pin` itself blocks). The install task
runs under a stub `brew` for the three states that matter.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.ollama/tasks/main.yml"


def _task() -> dict:
    tasks = yaml.safe_load(ROLE.read_text(encoding="utf-8"))
    return next(t for t in tasks if t.get("name") == "[Ollama] Install the pin keg when the cellar lacks it")


def _run(tmp: Path, pin: str, cellar: list[str], stable: str) -> tuple[str, list[str]]:
    cel = tmp / "Cellar" / "ollama"
    for v in cellar:
        (cel / v).mkdir(parents=True, exist_ok=True)
    log = tmp / "brew.log"
    brew = tmp / "brew"
    brew.write_text(f"""#!/bin/bash
echo "$*" >> "{log}"
case "$1" in
  --cellar) echo "{cel}";;
  info) echo '{{"formulae":[{{"versions":{{"stable":"{stable}"}}}}]}}';;
esac
exit 0
""")
    brew.chmod(brew.stat().st_mode | stat.S_IEXEC)
    script = jinja2.Environment().from_string(_task()["ansible.builtin.shell"]).render(ollama_version=pin)
    r = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{tmp}:/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    return r.stdout.strip(), calls


def test_a_pin_already_in_the_cellar_is_left_alone(tmp_path: Path) -> None:
    out, calls = _run(tmp_path, "0.35.0", ["0.34.0", "0.35.0"], "0.35.0")
    assert out == "present 0.35.0" and not any(c.startswith("upgrade") for c in calls)


def test_a_pin_core_offers_is_installed_and_repinned(tmp_path: Path) -> None:
    out, calls = _run(tmp_path, "0.35.0", ["0.34.0"], "0.35.0")
    assert out.endswith("installed 0.35.0"), out
    verbs = [c.split()[0] for c in calls]
    assert verbs.index("unpin") < verbs.index("upgrade") < verbs.index("pin"), calls


def test_a_pin_core_does_not_offer_is_reported_not_forced(tmp_path: Path) -> None:
    out, calls = _run(tmp_path, "0.35.0", ["0.34.0"], "0.34.4")
    assert out == "unavailable pin=0.35.0 core=0.34.4"
    assert not any(c.startswith(("upgrade", "unpin")) for c in calls), calls


def test_a_shadowing_tap_skips_the_install() -> None:
    assert any("_ollama_shadow" in w for w in _task()["when"])


def _remember(after: dict, before: str) -> str:
    tasks = yaml.safe_load(ROLE.read_text(encoding="utf-8"))
    expr = next(t for t in tasks if t.get("name") == "[Ollama] Remember the linked keg after an optional pin switch")["ansible.builtin.set_fact"]["ollama_linked_keg"]
    env = jinja2.Environment()
    return env.from_string(expr).render(_ollama_keg_after_link=after, _ollama_keg={"stdout": before}).strip()


def test_an_executed_re_resolve_wins_over_the_stale_reading() -> None:
    """2026-09-30: 0.35.0 was linked, the refusal said 0.34.0 — an executed
    result has no `skipped` key and the old default read it as skipped."""
    assert _remember({"stdout": "0.35.0\n", "rc": 0}, "0.34.0") == "0.35.0"
    assert _remember({"skipped": True}, "0.34.0") == "0.34.0"
    assert _remember({"stdout": "", "rc": 0}, "0.34.0") == "0.34.0"


def test_the_re_resolve_also_follows_an_install() -> None:
    tasks = yaml.safe_load(ROLE.read_text(encoding="utf-8"))
    t = next(t for t in tasks if t.get("name") == "[Ollama] Re-resolve the LINKED keg after switching to the pin")
    assert any("_ollama_pin_install" in w for w in t["when"])
