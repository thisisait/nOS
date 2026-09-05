"""`nos dtt <verb>` dispatches to a tool that exists, before the converge path.

The systemic answer to "tools/foo.py doesn't exist when I'm checked out on dev":
the installed `nos` reaches the DataTables tools from $NOS_SRC via `nos dtt`.
This pins the wiring so a verb can't point at a tool that was renamed/deleted,
and so the dtt branch stays ahead of the ansible-playbook exec (a dtt call must
never fall through into a converge).
"""

from __future__ import annotations

import os
import re

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_NOS = os.path.join(_REPO, "tools", "nos")


def _src() -> str:
    return open(_NOS, encoding="utf-8").read()


def test_every_dtt_verb_maps_to_a_real_tool():
    src = _src()
    # lines like:   capture) tool="dtt-capture.py" ;;
    pairs = re.findall(r'^\s*(\w+)\)\s*tool="([^"]+)"', src, re.M)
    assert pairs, "no `nos dtt` verb→tool map found — the dispatch shape changed"
    verbs = {v for v, _ in pairs}
    # the verbs the header + skill promise
    for expected in ("capture", "seed", "status", "update", "verify", "extract"):
        assert expected in verbs, f"`nos dtt {expected}` is documented but not wired"
    for verb, tool in pairs:
        assert os.path.isfile(os.path.join(_REPO, "tools", tool)), (
            f"nos dtt {verb} -> tools/{tool}, which does not exist")


def test_dtt_branch_is_before_the_converge_exec():
    src = _src()
    dtt = src.find('= "dtt" ]')
    conv = src.find("exec \"${ARGS[@]}\"")
    assert 0 < dtt < conv, (
        "the `nos dtt` branch must run and exit BEFORE the ansible-playbook exec "
        "— a dtt call must never fall through into a converge")


def test_dtt_runs_from_nos_src_not_cwd():
    # It must invoke the tool at $NOS_SRC/tools/, not a bare relative path — that
    # is what makes it work from any shell/branch/cwd.
    assert 'exec "$DTT_PY" "$NOS_SRC/tools/$tool"' in _src(), \
        "nos dtt must run the tool from $NOS_SRC, not the caller's directory"


def test_dtt_resolves_a_yaml_capable_python():
    # The tools need PyYAML; a bare pyenv python3 may lack it. The wrapper must
    # verify `import yaml` when picking the interpreter, and prefer NOS_PY.
    src = _src()
    assert "import yaml" in src, \
        "nos dtt must pick a python that can import yaml (the tools need PyYAML)"
    assert "${NOS_PY:-}" in src, "nos dtt should prefer a recorded NOS_PY"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
