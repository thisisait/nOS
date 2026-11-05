"""No Ansible copy/template/file task writes under the checkout's state/ or events/.

WHY (repo-body-plan I-11, 2026-10-07). apps_runner wrote
state/smoke-catalog.runtime.yml into the checkout: a runtime fact in the
source tree, one `git status` away from being committed. ~/.nos is the
runtime home. The task YAML is parsed (not grepped) and each task's dest/path
is read.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MODULES = {"copy", "template", "file"}
INTO_CHECKOUT = re.compile(
    r"\{\{\s*(playbook_dir|nos_main_checkout)\s*\}\}/(state|events)(/|$)")


def _tasks(node):
    if isinstance(node, list):
        for x in node:
            yield from _tasks(x)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"):
            yield from _tasks(node.get(key))


def _task_files():
    for base in ("roles", "tasks", "handlers"):
        yield from (REPO / base).rglob("*.yml")
    yield from REPO.glob("*.yml")


def offenders(paths) -> list[str]:
    out = []
    for f in paths:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError):
            continue
        for task in _tasks(doc):
            for mod, args in task.items():
                if mod.rsplit(".", 1)[-1] not in MODULES or not isinstance(args, dict):
                    continue
                dest = str(args.get("dest") or args.get("path") or "")
                if INTO_CHECKOUT.search(dest):
                    out.append(f"{f}: {task.get('name', mod)} -> {dest}")
    return out


def test_the_parser_sees_a_write_into_the_checkout(tmp_path):
    """Positive control: the shape this gate exists for is found."""
    bad = tmp_path / "t.yml"
    bad.write_text("- block:\n  - ansible.builtin.copy:\n      dest: '{{ playbook_dir }}/state/x.yml'\n")
    assert offenders([bad])


def test_no_task_writes_into_checkout_state_or_events():
    found = offenders(_task_files())
    assert not found, (
        "a converge writes runtime state into the checkout; write it under "
        f"{{{{ nos_state_dir }}}} (~/.nos) instead: {found}")


# ── OpenTofu state (2026-11-05). terraform.tfstate sat gitignored, 0600 and
# secret-bearing in terraform/authentik/ of whichever checkout converged, so a
# second clone started stateless and planned to re-create 13 live providers.
TOFU_TASKS = REPO / "tasks" / "tofu-authentik.yml"


def _tofu_task(pred):
    hits = [t for t in _tasks(yaml.safe_load(TOFU_TASKS.read_text())) if pred(t)]
    assert len(hits) == 1, f"expected one matching task in {TOFU_TASKS.name}, got {len(hits)}"
    return hits[0]


def _cmd(t):
    return str(t.get("ansible.builtin.command") or t.get("ansible.builtin.shell") or "")


def test_tofu_state_lives_under_nos_home_not_the_checkout():
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni
    m = re.search(r'^tofu_authentik_state_dir:\s*"([^"]+)"', ni.default_config_text(), re.M)
    assert m and "playbook_dir" not in m.group(1) and m.group(1).endswith("/.nos/tofu/authentik"), m
    assert re.search(r'backend\s+"local"\s*\{', (REPO / "terraform/authentik/versions.tf").read_text())
    init = _cmd(_tofu_task(lambda t: _cmd(t).startswith("tofu init")))
    assert "-backend-config=path={{ tofu_authentik_state_dir }}/terraform.tfstate" in init, init


def _move(tmp_path, src_files, dst_files):
    src, dst = tmp_path / "src", tmp_path / "dst"
    for d, files in ((src, src_files), (dst, dst_files)):
        d.mkdir()
        for name, body in files.items():
            (d / name).write_text(body)
    script = _tofu_task(lambda t: "SRC" in (t.get("environment") or {}))["ansible.builtin.shell"]
    return src, dst, subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                    env={"PATH": "/usr/bin:/bin", "SRC": str(src), "DST": str(dst)})


def test_tofu_state_is_moved_never_copied(tmp_path):
    src, dst, r = _move(tmp_path, {"terraform.tfstate": "a", "terraform.tfstate.backup": "b"}, {})
    assert r.returncode == 0, r.stderr
    assert not list(src.iterdir()), "a copy left behind diverges from the one tofu writes"
    assert (dst / "terraform.tfstate").read_text() == "a" and (dst / "terraform.tfstate.backup").read_text() == "b"


def test_tofu_state_move_drops_an_identical_twin(tmp_path):
    src, dst, r = _move(tmp_path, {"terraform.tfstate": "a"}, {"terraform.tfstate": "a"})
    assert r.returncode == 0, r.stderr
    assert not (src / "terraform.tfstate").exists() and (dst / "terraform.tfstate").read_text() == "a"


def test_tofu_state_move_refuses_two_different_states(tmp_path):
    src, dst, r = _move(tmp_path, {"terraform.tfstate": "old"}, {"terraform.tfstate": "new"})
    assert r.returncode != 0 and "REFUSE" in (r.stdout + r.stderr)
    assert (src / "terraform.tfstate").read_text() == "old" and (dst / "terraform.tfstate").read_text() == "new"
