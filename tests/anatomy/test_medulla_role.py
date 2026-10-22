"""roles/pazny.medulla builds the one workspace binary; thalamus_bin is a copy of it.

WHY. Row medulla-skeleton (ssot/doctrine/medulla.md §1, §3: the thalamus is absorbed first). The
build moved out of pazny.thalamus: the medulla links the thalamus crate, so a change anywhere in
the workspace (root Cargo.toml/Cargo.lock, medulla/src) must rebuild, and the plist's
`thalamus_bin` stays the path launchd runs — now a copy of the medulla. Offline: YAML shape,
and the hash task run on a copy of the workspace.
"""
from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import subprocess

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.medulla"
THALAMUS = REPO / "roles" / "pazny.thalamus"


def _tasks(role: pathlib.Path, name: str) -> list[dict]:
    assert (role / "tasks" / name).is_file(), f"roles/{role.name} has no tasks/{name}"
    return yaml.safe_load((role / "tasks" / name).read_text()) or []


def _build(name: str) -> str:
    return next(t["ansible.builtin.shell"] for t in _tasks(ROLE, name) if "build" in t.get("name", "").lower())


def _links(name: str) -> list[dict]:
    return [t["ansible.builtin.file"] for t in _tasks(ROLE, name)
            if t.get("ansible.builtin.file", {}).get("state") == "link"]


def test_the_build_is_locked_and_builds_the_workspace():
    for name in ("macos.yml", "linux.yml"):
        sh = _build(name)
        for word in ("--locked", "--release", "-p medulla", "CARGO_TARGET_DIR", "{{ medulla_bin | quote }}"):
            assert word in sh, (name, word, sh)
    assert "/files/anatomy/thalamus/Cargo.toml') | quote }}" in _build("macos.yml")
    assert "/files/anatomy/thalamus') | quote }}:/src:ro -w /src " in _build("linux.yml")


def test_the_binary_is_where_the_plist_looks():
    assert (ROLE / "defaults" / "main.yml").is_file(), "roles/pazny.medulla has no defaults/main.yml"
    d = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    assert d["medulla_bin_dir"] == "{{ thalamus_home }}/bin" and d["medulla_bin"] == "{{ medulla_bin_dir }}/medulla"
    # The same dir, spelled in thalamus vars: include_role keeps medulla_* private to the role.
    assert yaml.safe_load((THALAMUS / "defaults" / "main.yml").read_text())["thalamus_bin"] == "{{ thalamus_home }}/bin/thalamus"


def test_the_thalamus_role_includes_the_medulla_build():
    for name in ("macos.yml", "linux.yml"):
        tasks = _tasks(THALAMUS, name)
        inc = [t for t in tasks if t.get("ansible.builtin.include_role", {}).get("name") == "pazny.medulla"]
        assert len(inc) == 1, name
        assert set(inc[0]["ansible.builtin.include_role"]["apply"]["tags"]) >= {"thalamus", "medulla"}
        assert set(inc[0]["tags"]) >= {"thalamus", "medulla"}, "without tags --tags thalamus never reaches the role"
        assert not [t for t in tasks if "cargo" in str(t)], f"{name} still builds"


def _hash(play: pathlib.Path) -> str:
    t = next(t for t in _tasks(ROLE, "main.yml") if "hash the" in t.get("name", "").lower())
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["quote"] = shlex.quote
    sh = env.from_string(t["ansible.builtin.shell"]).render(playbook_dir=str(play))
    r = subprocess.run(["/bin/bash", "-c", sh], capture_output=True, text=True, check=True, env=dict(os.environ))
    return r.stdout.strip()


def test_the_source_hash_covers_the_whole_workspace(tmp_path):
    ws = tmp_path / "files/anatomy/thalamus"
    shutil.copytree(REPO / "files/anatomy/thalamus", ws, ignore=shutil.ignore_patterns("target", "tests"))
    seen = {_hash(tmp_path)}
    for rel in ("Cargo.toml", "Cargo.lock", "medulla/src/main.rs", "medulla/Cargo.toml",
                "thalamus/src/cli.rs", "thalamus/Cargo.toml", "contract/src/lib.rs", "contract/Cargo.toml"):
        with (ws / rel).open("a") as f:
            f.write("\n")
        h = _hash(tmp_path)
        assert h not in seen, f"a change to {rel} does not rebuild the medulla"
        seen.add(h)


def test_thalamus_bin_is_a_copy_the_kernel_names_as_itself():
    """A symlink would move the exe path: proc_pidpath and /proc/<pid>/exe resolve it (serve.rs).

    launchd's process would read .../bin/medulla, so a path-keyed TCC client entry (the
    removable-volume grant) would re-prompt, and a peer named `{{ thalamus_bin }}` in
    NOS_DECIDER_EXES would stop matching. A copy keeps today's path, bytes and signature.
    """
    for name in ("macos.yml", "linux.yml"):
        tasks = _tasks(ROLE, name)
        assert not _links(name), f"{name}: thalamus_bin is a link to the medulla"
        at = next((i for i, t in enumerate(tasks) if t.get("ansible.builtin.copy", {}).get("dest") == "{{ thalamus_bin }}"), None)
        assert at is not None, f"{name}: nothing installs thalamus_bin"
        cp = tasks[at]["ansible.builtin.copy"]
        assert cp["src"] == "{{ medulla_bin }}" and cp["remote_src"] is True, (name, cp)
        if name == "macos.yml":  # the signed bytes are what is copied
            sign = next(i for i, t in enumerate(tasks) if "sign the binary" in t.get("name", "").lower())
            assert sign < at, "thalamus_bin is copied before the medulla is signed"
