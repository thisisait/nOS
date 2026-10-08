"""The brew bin dir has one declared mode, so the macOS idempotence pass can be green.

Measured on run 37368276781 (macos-15, 2026-10-05) and on the live macOS 26
host (~/.nos/ansible.log, 10-06 and 10-07): every converge reports `changed`
for "Ensure proper permissions and ownership on homebrew_brew_bin_path dirs."
`tasks/nos-cli.yml` set `{{ homebrew_prefix }}/bin` to 0755 while
`roles/pazny.mac.homebrew` sets the same directory to 0775, so each run flips
it twice and the second pass can never show changed=0. Two declarations of one
fact; this pins that the brew bin dir has at most one declared mode across all
task files. (The missing `-e allow_weak_prefix` on the second pass is pinned
by test_ci_converges_share_sandbox_flags.)
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK_FILES = list((REPO / "tasks").rglob("*.yml")) + list((REPO / "roles").glob("*/tasks/*.yml"))

# How the brew bin dir is spelled in task `path:` values.
BREW_BIN = re.compile(r"homebrew_brew_bin_path|nos_cli_install_dir|homebrew_prefix\s*}}\s*/bin\b|homebrew_prefix\s*\+\s*'/bin'")


def _walk(node, out: list[dict]) -> None:
    if isinstance(node, dict):
        for key in ("file", "ansible.builtin.file"):
            args = node.get(key)
            if isinstance(args, dict) and args.get("state") == "directory" and "mode" in args \
                    and BREW_BIN.search(str(args.get("path", ""))):
                out.append({"name": node.get("name"), "mode": str(args["mode"])})
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def test_the_brew_bin_dir_has_one_declared_mode() -> None:
    found: list[dict] = []
    for path in TASK_FILES:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        _walk(doc, found)
    modes = {f["mode"] for f in found}
    assert len(modes) <= 1, (
        "the brew bin dir is given two modes, so both tasks report changed on every run: "
        f"{found}"
    )
