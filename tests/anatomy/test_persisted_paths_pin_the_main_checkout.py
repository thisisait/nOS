"""Anatomy CI gate — what outlives a converge points at the main checkout.

MEASURED 2026-09-02. Every repo-pathed Pulse job in the estate — 24 of them,
ten agent runs among them — pointed at `/Users/pazny/projects/nOS-obs`, a
worktree on a feature branch, because the catalog stores an absolute
`playbook_dir` and the last converge to touch it wins. The tofu drift job's
verdict flipped with it three days running: `101 to add` from the worktree,
`no drift` from the main checkout, and no way to tell from the record which
tree either answer was about.

The same path is baked into the launchd plists — pulse's WorkingDirectory,
bone's and ears's PLAYBOOK_DIR, and wing's NOS_REPO_ROOT, which is the root
AgentKit agents WRITE into.

THE RULE, and it is a two-line rule because a converge writes two kinds of path:

    used during THIS run      playbook_dir        you are converging this tree
    PERSISTED past the run    nos_main_checkout   the estate's code, not a branch

A role template is rendered TO DISK, so it is always the second kind. That makes
the scan derived rather than curated: no allow-list to fall out of date, and a
plist added next year is covered the day it lands.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PREFLIGHT = REPO / "tasks" / "preflight-checkout-current.yml"
CATALOG_TASK = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"


def _uncommented(path: pathlib.Path) -> list[tuple[int, str]]:
    """Comments naming the variable are not uses of it."""
    out = []
    for n, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = ln.strip()
        if stripped.startswith(("#", "<!--", "{#")):
            continue
        out.append((n, ln))
    return out


def test_no_rendered_template_embeds_the_running_tree():
    offenders = []
    for tpl in sorted(REPO.glob("roles/*/templates/**/*.j2")):
        for n, ln in _uncommented(tpl):
            if "playbook_dir" in ln:
                offenders.append(f"{tpl.relative_to(REPO)}:{n}")
    assert not offenders, (
        "a rendered template embeds playbook_dir, so a converge from a worktree "
        "writes that worktree's path into something that outlives the run — a "
        "launchd plist, a compose build context. Use nos_main_checkout:\n  "
        + "\n  ".join(offenders))


def test_the_pulse_catalog_is_pinned():
    """The catalog literal-substitutes this one value into every job's command
    and env, so it alone decides which tree 24 scheduled jobs execute."""
    src = "\n".join(ln for _, ln in _uncommented(CATALOG_TASK))
    m = re.search(r"NOS_PLAYBOOK_DIR:\s*\"?\{\{\s*([a-z_]+)", src)
    assert m, "the catalog no longer passes NOS_PLAYBOOK_DIR; re-read this gate"
    assert m.group(1) == "nos_main_checkout", (
        f"the Pulse catalog is pinned to {m.group(1)!r}. With playbook_dir, one "
        "converge from a worktree re-points every scheduled job and every agent "
        "at a feature branch, silently, until some later converge moves them "
        "back")


def test_the_fact_is_resolved_absolutely():
    """`--git-common-dir` is answered RELATIVE from a worktree, so a dirname of
    it lands somewhere else entirely. `--path-format=absolute` also removes the
    need to branch: a main checkout resolves to its own root."""
    src = "\n".join(ln for _, ln in _uncommented(PREFLIGHT))
    assert "nos_main_checkout" in src, (
        "nothing resolves nos_main_checkout; the persisted paths above have no "
        "value to point at")
    assert "--path-format=absolute" in src, (
        "the resolution does not force an absolute path. From a worktree git "
        "answers --git-common-dir relatively, and the dirname of a relative "
        "path is not the main checkout")


def test_a_non_repo_install_falls_back_to_this_tree():
    """A tarball install is not a worktree problem. Resolving to empty would
    write bare paths into the plists — the silent-corruption branch."""
    src = "\n".join(ln for _, ln in _uncommented(PREFLIGHT))
    block = src[src.index("nos_main_checkout:"):]
    block = block[:block.index("tags:")]
    assert "playbook_dir" in block, (
        "the fallback for a checkout that is not a git repo is not "
        "playbook_dir. There it IS the estate's checkout, and an empty value "
        "would render paths like '/files/anatomy/pulse' into launchd")
