"""Anatomy gate for the pazny.gitea admin-provisioning bug fix
(2026-05-18).

The Gitea CLI refuses to run as root. The post.yml task used to call
`docker compose exec` without `-u git`, so every CLI invocation (list,
create, change-password) silently failed under `failed_when: false`.
Result: admin user was never created, login failed for the operator
2 days after install, the role looked green every run.

This gate pins three things:
  1. Every `gitea admin user` call carries `-u git` (otherwise root errs).
  2. The post.yml task surfaces an unexpected admin-list rc instead of
     swallowing it via failed_when:false (the actual root cause of the
     2-day delay in surfacing the bug).
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_gitea_admin_exec_uses_git_user():
	"""Every `docker compose exec ... gitea admin user` invocation MUST
	pass `-u git`. The Gitea CLI checks effective UID and exits with
	a fatal log if root."""
	src = (REPO / "roles/pazny.gitea/tasks/post.yml").read_text()
	# Find every occurrence of "exec ... gitea gitea admin user".
	pattern = re.compile(r"exec[^\n]*?gitea\s+gitea\s+admin\s+user", re.MULTILINE)
	matches = pattern.findall(src)
	assert matches, "no `gitea admin user` exec found — post.yml restructured?"
	for m in matches:
		assert "-u git" in m, (
			f"gitea exec missing `-u git` — CLI will fail as root: {m!r}"
		)


def test_gitea_post_surfaces_unexpected_admin_list_failure():
	"""The post.yml task swallows admin-list failure via
	`failed_when: false` so subsequent create/update tasks can branch
	on rc. A diagnostic fail must catch *unexpected* return codes
	(anything other than 0 = found, 1 = grep miss) so the next
	silent-failure regression surfaces immediately."""
	src = (REPO / "roles/pazny.gitea/tasks/post.yml").read_text()
	assert "Diagnose admin-list call" in src
	# The condition must reject rc not in [0, 1].
	assert "rc | default(0) not in [0, 1]" in src
