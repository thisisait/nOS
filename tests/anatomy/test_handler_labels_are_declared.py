"""Anatomy gate: a launchd handler names a label something declares.

2026-10-06: two `Restart openclaw` handlers (main.yml, roles/pazny.openclaw)
kicked com.openclaw.agent, retired when `openclaw gateway install` began
writing ai.openclaw.gateway. Nothing notified them, so nothing failed: a
dead handler waiting for the day someone wires a notify to it.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LABEL = re.compile(r"\b((?:com|ai|eu|homebrew|sh|org|io)\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)\b")
DECL = re.compile(r'^[a-z_]+_launchd_label:\s*"([^"]+)"', re.M)
# macOS's own daemons: no nOS file declares them, the OS does.
SYSTEM = {"com.openssh.sshd"}


def _declared() -> set[str]:
	import sys
	sys.path.insert(0, str(REPO / "tools"))
	import nos_identity
	files = [*nos_identity.default_layers(), *REPO.glob("roles/*/defaults/main.yml")]
	out = {m for f in files for m in DECL.findall(f.read_text(encoding="utf-8"))}
	manifest = yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))
	out |= {r["launchd_label"] for r in manifest.get("services", []) if r.get("launchd_label")}
	return out | SYSTEM


def _handlers():
	for play in yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8")):
		for h in play.get("handlers") or []:
			yield "main.yml", h
	for f in sorted(REPO.glob("roles/*/handlers/main.yml")):
		for h in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
			yield str(f.relative_to(REPO)), h


def test_a_handler_kicks_only_a_declared_label():
	declared, bad = _declared(), []
	for where, h in _handlers():
		body = yaml.safe_dump({k: v for k, v in h.items() if k != "name"})
		if "launchctl" not in body:
			continue
		bad += [f"{where}: {h.get('name')} -> {l}" for l in set(LABEL.findall(body))
		        if not l.endswith(".plist") and l not in declared]
	assert not bad, "handler names an undeclared launchd label: " + "; ".join(sorted(bad))


def test_the_gate_sees_a_planted_dead_label():
	body = yaml.safe_dump({"shell": 'launchctl kickstart -k "gui/501/com.openclaw.agent"'})
	assert set(LABEL.findall(body)) - _declared() == {"com.openclaw.agent"}
