"""Gate: a playbook step running a tool that needs `requests` uses the tools venv.

2026-10-01: the Linux wet-test failed the account walk — tools/nos-first-login.py
imports tools/nos_sso.py, which imports requests, and the runner's python3 has
none. tasks/tools-venv.yml builds ~/.nos/tools-venv before any stack comes up.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


THIRD_PARTY = {"requests": "requests", "jinja2": "jinja2", "yaml": "pyyaml"}  # import → pip name


def _third_party(tool: Path, seen=None) -> set:
    """Third-party modules a tool needs, following `from x import` AND the
    importlib loads (nos-first-login reads e2e-plan.py that way — the first
    version of this gate missed jinja2 through exactly that path)."""
    seen = seen if seen is not None else set()
    if tool in seen or not tool.is_file():
        return set()
    seen.add(tool)
    src = tool.read_text(encoding="utf-8")
    found = {m for m in THIRD_PARTY if re.search(rf"^\s*(import {m}\b|from {m}\b)", src, re.M)}
    deps = re.findall(r"^\s*from ([\w]+) import", src, re.M) + \
        [p[:-3] for p in re.findall(r'"([\w-]+\.py)"', src)]
    for d in deps:
        found |= _third_party(REPO / "tools" / f"{d}.py", seen)
    return found


def _needs_requests(tool: Path) -> bool:
    return bool(_third_party(tool))


def _commands(node):
    """Every command/shell/script invocation in a task file — parsed, not grepped."""
    if isinstance(node, list):
        for n in node:
            yield from _commands(n)
    elif isinstance(node, dict):
        for key in ("ansible.builtin.command", "ansible.builtin.shell", "command", "shell"):
            if key in node:
                yield str(node[key])
        for key in ("block", "rescue", "always"):
            yield from _commands(node.get(key))


def test_every_requests_tool_step_uses_the_tools_python():
    import yaml
    bad = []
    for f in list((REPO / "tasks").rglob("*.yml")) + list((REPO / "roles").rglob("tasks/*.yml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        for cmd in _commands(doc):
            for tool in re.findall(r"tools/([\w-]+\.py)", cmd):
                need = _third_party(REPO / "tools" / tool)
                # Ansible itself requires PyYAML + Jinja2, so its interpreter
                # carries those; requests only the tools venv does.
                ok = "nos_tools_python" in cmd or (
                    "ansible_playbook_python" in cmd and need <= {"yaml", "jinja2"})
                if need and not ok:
                    bad.append(f"{f.relative_to(REPO)}: {tool} needs {sorted(need)}")
    assert not bad, "a requests tool runs on a bare python3:\n" + "\n".join(bad)


def test_the_venv_exists_before_the_stacks_and_carries_requests():
    main = (REPO / "main.yml").read_text(encoding="utf-8")
    assert main.index("import_tasks: tasks/tools-venv.yml") < main.index("import_tasks: tasks/stacks/core-up.yml")
    reqs = (REPO / "tools/requirements.txt").read_text().lower()
    need = _third_party(REPO / "tools/nos-first-login.py") | _third_party(REPO / "tools/woodpecker-token.py")
    assert need >= {"requests", "jinja2", "yaml"}, f"the detector lost its positive case: {need}"
    assert all(THIRD_PARTY[m] in reqs for m in need), f"tools/requirements.txt lacks one of {need}"
