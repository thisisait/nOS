"""No plugin Pulse job carries a token that holds pulse.write.

pulse.write registers the commands the operator's Pulse runs; a job holding it
can rewrite every job, its own included. Measured 2026-11-03: gitleaks' nightly
scan ran with wing_api_token, the only pulse.write row, to POST findings.
The roster is read from the mint task (roles/pazny.wing/tasks/post.yml).
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = REPO / "roles/pazny.wing/tasks/post.yml"
PLUGINS = REPO / "files/anatomy/plugins"


def pulse_write_tokens() -> set[str]:
    """Vars minted by provision-token.php with pulse.write among --scopes."""
    out = set()
    for task in yaml.safe_load(POST.read_text(encoding="utf-8")) or []:
        argv = ((task or {}).get("ansible.builtin.command") or {}).get("argv") or []
        if not any("provision-token.php" in str(a) for a in argv):
            continue
        token = next((a for a in argv if str(a).startswith("--token=")), "")
        scopes = next((a for a in argv if str(a).startswith("--scopes=")), "")
        var = re.search(r"\{\{\s*([a-z0-9_]+)\s*\}\}", token)
        if var and "pulse.write" in scopes.split("=", 1)[1].split(","):
            out.add(var.group(1))
    return out


def test_the_roster_names_the_catalog_token():
    assert "wing_api_token" in pulse_write_tokens(), "mint parser broke — no pulse.write holder found"


def test_no_plugin_job_env_holds_a_pulse_write_token():
    held = pulse_write_tokens()
    bad = []
    for plugin in sorted(PLUGINS.glob("*/plugin.yml")):
        doc = yaml.safe_load(plugin.read_text(encoding="utf-8")) or {}
        for job in ((doc.get("pulse") or {}).get("jobs") or []):
            for key, value in (job.get("env") or {}).items():
                names = set(re.findall(r"\{\{\s*([a-z0-9_]+)\s*\}\}|secret:([a-z0-9_]+)", str(value)))
                if held & {n for pair in names for n in pair if n}:
                    bad.append(f"{plugin.parent.name}:{job.get('name')} {key}")
    assert not bad, f"plugin jobs carrying a pulse.write token (mint the job its own): {bad}"
