"""Every Jinja template in the repo parses.

gitea-base's compose extension carried `{% if autologin %}` inside a YAML
comment. Jinja does not know YAML comments: the tag opened a block that never
closed, the loader marked the plugin degraded, and the extension (SSO form
hide, basic auth for the API) did not render for four months while every
converge was green (2026-06-09 → 2026-09-30).
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest

REPO = Path(__file__).resolve().parents[2]
SKIP = ("node_modules", ".ci-venv", ".git", ".claude/worktrees")


def _skipped(path: Path) -> bool:
    # Path components relative to REPO: a substring of the absolute path hid every
    # template inside an agent worktree, and `.git` hid roles/pazny.gitea + gitlab.
    rel = "/" + path.relative_to(REPO).as_posix() + "/"
    return any(f"/{s}/" in rel for s in SKIP)


TEMPLATES = sorted(p for p in REPO.rglob("*.j2") if not _skipped(p))
ENV = jinja2.Environment(extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"])


def test_there_are_templates_to_check():
    assert len(TEMPLATES) > 150, len(TEMPLATES)


def test_the_skip_matches_components_not_substrings():
    assert not _skipped(REPO / "roles/pazny.gitea/templates/compose.yml.j2")
    assert _skipped(REPO / ".claude/worktrees/agent-x/roles/a.j2")
    assert _skipped(REPO / "files/anatomy/face/node_modules/a.j2")


@pytest.mark.parametrize("path", TEMPLATES, ids=[str(p.relative_to(REPO)) for p in TEMPLATES])
def test_the_template_parses(path):
    try:
        ENV.parse(path.read_text(encoding="utf-8"))
    except jinja2.TemplateSyntaxError as e:
        pytest.fail(f"{path.relative_to(REPO)}:{e.lineno}: {e.message} — a Jinja tag inside a comment still counts")
