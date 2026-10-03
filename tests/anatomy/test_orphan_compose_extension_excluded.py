"""Anatomy CI gate — a plugin compose extension without its base is left out of `up`.

MEASURED 2026-10-03: nos-forum-base.yml (core-up pre_compose) sat in
iiab/overrides without nos_forum.yml (the role renders it in stack-up), and
`docker compose -p iiab up` refused all 22 iiab services: `service "nos-forum"
has neither an image nor a build context`. Same class as Puter 07-20.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("nos_prune_guard", REPO / "filter_plugins/nos_prune_guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

BASE = {"services": {}, "networks": {"iiab_net": {}}}
FORUM = {"services": {"nos-forum": {"image": "nos-forum:local", "networks": ["iiab_net"]}}}
FORUM_EXT = {"services": {"nos-forum": {"environment": {"_NOS_PLUGIN": "nos-forum-base"}}}}
KIWIX = {"services": {"kiwix": {"image": "kiwix-serve:3", "networks": ["iiab_net"]}}}


def _stack(tmp: pathlib.Path, with_base: bool) -> pathlib.Path:
    stack = tmp / "iiab"
    (stack / "overrides").mkdir(parents=True)
    (stack / "docker-compose.yml").write_text(yaml.safe_dump(BASE))
    frags = {"kiwix.yml": KIWIX, "nos-forum-base.yml": FORUM_EXT}
    if with_base:
        frags["nos_forum.yml"] = FORUM
    for name, doc in frags.items():
        (stack / "overrides" / name).write_text(yaml.safe_dump(doc))
    return stack


def _f_list(stacks: pathlib.Path) -> list[str]:
    found = {"iiab": [{"path": str(p)} for p in sorted((stacks / "iiab/overrides").glob("*.yml"))]}
    split = guard.nos_split_orphans(found, str(stacks))
    return sorted(pathlib.Path(f["path"]).name for f in split["keep"]["iiab"])


def test_extension_without_its_base_is_left_out(tmp_path):
    _stack(tmp_path, with_base=False)
    assert _f_list(tmp_path) == ["kiwix.yml"]


def test_extension_with_its_base_is_merged(tmp_path):
    _stack(tmp_path, with_base=True)
    assert _f_list(tmp_path) == ["kiwix.yml", "nos-forum-base.yml", "nos_forum.yml"]


def test_base_compose_file_counts_as_a_definition():
    docs = {"/s/docker-compose.yml": FORUM, "/s/overrides/nos-forum-base.yml": FORUM_EXT}
    assert guard.orphan_fragments(docs) == []


@pytest.mark.live
@pytest.mark.skipif(not shutil.which("docker"), reason="docker CLI not on PATH")
def test_compose_refuses_the_unfiltered_list_and_accepts_the_filtered_one(tmp_path):
    """Retro-verify: the unfiltered -f list is the 2026-10-03 error. `config` parses only."""
    stack = _stack(tmp_path, with_base=False)

    def config(files):
        args = ["docker", "compose", "-f", str(stack / "docker-compose.yml")]
        for f in files:
            args += ["-f", str(stack / "overrides" / f)]
        return subprocess.run(args + ["-p", "iiab", "config", "-q"], capture_output=True, text=True)

    broken = config(["kiwix.yml", "nos-forum-base.yml"])
    assert "neither an image nor a build context" in broken.stderr
    assert config(_f_list(tmp_path)).returncode == 0


@pytest.mark.parametrize("path,anchor", [
    ("tasks/stacks/stack-up.yml", "[Stacks] Fire docker compose up -d per stack (async, parallel start)"),
    ("tasks/stacks/core-up.yml", "[Core] Docker external-volume mount preflight"),
])
def test_orchestrators_filter_before_up(path, anchor):
    names = [t.get("name", "") for t in yaml.safe_load((REPO / path).read_text())]
    split = next(i for i, n in enumerate(names) if "Exclude orphan compose extensions" in n)
    merge = next(i for i, n in enumerate(names) if "Merge only fragments whose services are defined" in n)
    assert split < merge < names.index(anchor)
    tasks = yaml.safe_load((REPO / path).read_text())
    assert "nos_split_orphans" in str(tasks[split])


def test_red_status_names_the_orphan(tmp_path, monkeypatch):
    _stack(tmp_path, with_base=False)
    spec = importlib.util.spec_from_file_location("red_status", REPO / "tools/red-status.py")
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    monkeypatch.setattr(rs, "STACKS_DIR", tmp_path)
    orphans = rs.orphan_extensions()
    assert [pathlib.Path(p).name for p in orphans] == ["nos-forum-base.yml"]
    assert any("nos-forum-base.yml" in line for line in rs.reds({"orphan_extensions": orphans}))
