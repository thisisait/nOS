"""A template renders the host it runs on, never the maintainer's.

alloy-syslog tailed `/Users/<maintainer>/...` literally: on any other account
every daemon log was a silent empty glob. Hermes' memory seed named the
maintainer's address to every fork's agent. A .j2 derives home and identity
from facts/config; a literal home or the maintainer's address is red.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
OPERATOR = re.compile(r"/Users/[a-z][\w.-]*|pazny\.develop@|@pazny\.eu")


def test_no_template_names_the_operator() -> None:
    files = subprocess.run(["git", "ls-files", "*.j2"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.split()
    hits = [f"{f}:{n}" for f in files
            for n, line in enumerate((REPO / f).read_text(encoding="utf-8").splitlines(), 1)
            if OPERATOR.search(line)]
    assert not hits, "template names a literal home or the maintainer:\n" + "\n".join(hits)


def test_committed_defaults_carry_no_git_identity():
    """A fork inherited the maintainer's git name and e-mail and Gitea admin
    address from default.credentials.yml (2026-10-05). Identity lives in the
    operator's gitignored credentials.yml; the committed defaults stay empty."""
    import yaml
    creds = yaml.safe_load((REPO / "default.credentials.yml").read_text())
    for key in ("git_user_name", "git_user_email", "gitea_admin_email"):
        assert creds.get(key, "") == "", f"{key} has a committed default"


def test_an_empty_gitea_admin_email_falls_back():
    post = (REPO / "roles/pazny.gitea/tasks/post.yml").read_text()
    assert "@localhost', true)" in post, "default() without true keeps an empty string"
