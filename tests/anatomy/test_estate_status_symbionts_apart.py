"""estate-status --identity: symbiont daemons are shown apart and never counted.

Operator 2026-10-22: the daemons nOS hosts but does not own (ollama, alloy, dnsmasq,
hermes, openclaw, backrest: software_owner symbiont with a launchd label) are
reported for information in their own section. The transplant numbers (host
runtimes, run as operator/root/other) count self-owned organs only, because the
medulla absorbs those and never the symbionts (ssot/doctrine/medulla.md).
"""

import importlib.util
import os
import plistlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402

ME = os.getuid()
SYMBIONTS = [r for r in nos_identity.services()
             if r.get("software_owner") == "symbiont" and r.get("launchd_label")]


def load():
    spec = importlib.util.spec_from_file_location("estate_status", REPO / "tools" / "estate-status.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_symbiont_daemon_is_reported_apart_and_not_counted(tmp_path):
    mod = load()
    assert SYMBIONTS, "the manifest lost its symbiont daemons"
    sym = SYMBIONTS[0]
    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    (tmp_path / "Library/LaunchDaemons").mkdir(parents=True)
    argv = [f"/opt/homebrew/opt/{sym['id']}/bin/{sym['id']}", "--keep-in-foreground"]
    (agents / f"{sym['launchd_label']}.plist").write_bytes(plistlib.dumps(
        {"Label": sym["launchd_label"], "ProgramArguments": argv}))
    res = mod.Result()
    mod.axis_identity(res, root=tmp_path, home=home, ps_lines=[f"{ME} pazny {' '.join(argv)}"])
    got = [x for x in res.lines if x.axis == "identity"]
    mine = [x for x in got if x.subject == sym["id"]]
    assert len(mine) == 1, f"no identity line for the symbiont {sym['id']}: {got}"
    assert "symbiont" in mine[0].detail and f"runs as pazny uid {ME}" in mine[0].detail, mine[0]
    summary = [x for x in got if x.subject == "summary"][0].detail
    assert "run as operator 0, root 0, other 0" in summary, summary
    assert [x for x in got if x.subject == "symbionts"], "no symbionts summary line"
