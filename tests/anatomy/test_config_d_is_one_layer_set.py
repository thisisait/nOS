"""The defaults are one layer set: config.d/*.yml in order, then default.config.yml.

default.config.yml outgrew one file (3658 lines, ~900 vars), so it is split by
domain into config.d/NN-<domain>.yml, loaded BEFORE the remainder and before
config.yml. YAML cannot include, so the set is spelled in two places that this
gate pins to one rule: main.yml (vars_files + the preflight YAML check) and
tools/nos_identity.default_layers() (every Python reader). A variable is declared
exactly once across the set, so file order can never change a value. Nothing
reads config.d/ on its own (a partial view is not the defaults), and the number
of files that still open default.config.yml directly may only go down — the
checklist lives in the roadmap row default-config-split.
"""
from __future__ import annotations

import collections
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

#: Files still opening default.config.yml as a file (measured 2026-10-04 after
#: the machinery landed). Rerouting a reader through nos_identity lowers it.
DIRECT_READERS_MAX = 311
SUFFIXES = {".py", ".yml", ".yaml", ".sh", ".php", ".j2", ".js", ".ts", ".json", ""}
SKIP_PARTS = {".git", "node_modules", "docs", ".ci-venv", "dist", "vendor", "build"}
#: The only code allowed to open config.d/ by name: the helper and this gate.
CONFIG_D_OPENERS = {"tools/nos_identity.py", "tests/anatomy/test_config_d_is_one_layer_set.py",
                    "main.yml", "tasks/stacks/prune-disabled.yml",   # Ansible has no helper to import
                    "tests/anatomy/test_image_pin_hygiene.py"}       # names a file as an exemption KEY, reads via ni
CONFIG_D = re.compile(r"(?<![\w/])config\.d/(\*|[\w-]+\.ya?ml)")   # a domain file or the glob, by name


def _code_files():
    # Tracked files only: an rglob counted __pycache__ and build leftovers, 611 in
    # the operator's checkout vs 311 in a clean worktree (2026-10-04).
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    for rel in filter(None, tracked.decode().split("\0")):
        p = REPO / rel
        if p.is_file() and p.suffix in SUFFIXES and not (SKIP_PARTS | {"config.d"}) & set(p.parts):
            try:
                yield p, p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue


def test_the_set_has_a_domain_file_and_the_remainder():
    layers = ni.default_layers()
    assert layers[-1] == REPO / "default.config.yml" and len(layers) >= 2, layers
    assert layers[:-1] == sorted(REPO.glob("config.d/*.yml")), "default_layers() is not config.d/*.yml in lexical order"
    assert all(p.is_file() for p in layers)


def test_every_variable_is_declared_exactly_once_across_the_set():
    where = collections.defaultdict(list)
    for p in ni.default_layers():
        for k in re.findall(r"^([A-Za-z_][A-Za-z0-9_]*):", p.read_text(encoding="utf-8"), re.M):
            where[k].append(p.name)
    dup = {k: v for k, v in where.items() if len(v) > 1}
    assert not dup, f"declared more than once — the later file silently wins: {dup}"
    assert len(where) > 800, "the set parsed to almost nothing — the regex or the files moved"


def test_main_yml_loads_exactly_the_shared_set():
    play = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))[0]
    rel = [str(p.relative_to(REPO)) for p in ni.default_layers()]
    assert play["vars_files"][:len(rel)] == rel, f"vars_files {play['vars_files']} != default_layers() {rel}"
    assert play["vars_files"][len(rel)] == "default.credentials.yml", "credentials no longer follow the defaults"
    stat = next(t for t in play["pre_tasks"] if str(t.get("name", "")).startswith("[Preflight] Stat config files"))
    checked = [str(x).replace("{{ playbook_dir }}/", "") for x in stat["loop"]]
    assert checked[:len(rel)] == rel, f"the preflight YAML check lists {checked}, not the shared set"


def test_the_merged_set_resolves_like_one_file():
    merged = ni.default_config()
    assert merged["global_password_prefix"] and "nos_identities" in merged and "macos_dock_autohide" in merged
    text = ni.default_config_text()
    assert text.count("global_password_prefix:") == 1 and "macos_dock_autohide:" in text


def test_nothing_but_the_helper_opens_config_d():
    bad = sorted(str(p.relative_to(REPO)) for p, t in _code_files()
                 if CONFIG_D.search(t) and str(p.relative_to(REPO)) not in CONFIG_D_OPENERS)
    assert not bad, f"a reader opens a domain file by name — route it through nos_identity: {bad}"


def test_direct_readers_of_the_remainder_only_shrink():
    direct = sorted(str(p.relative_to(REPO)) for p, t in _code_files() if "default.config.yml" in t)
    assert len(direct) <= DIRECT_READERS_MAX, (
        f"{len(direct)} files open default.config.yml directly, ratchet {DIRECT_READERS_MAX}; "
        f"route the new one through nos_identity.default_config(): {direct}")
    assert len(direct) >= DIRECT_READERS_MAX * 0.8, (
        f"{len(direct)} direct readers, ratchet {DIRECT_READERS_MAX}: lower the ratchet to what was measured")
