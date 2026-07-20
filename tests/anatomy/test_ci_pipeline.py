"""Anatomy gates for the Woodpecker CI pipeline + Gitea/Woodpecker
autowiring (Anatomy A16, 2026-05-17).

Pins:
  * `.woodpecker.yml` shape — required steps + secret references
  * pazny.gitea post-repo task — repo creation + GitHub pull-mirror
  * pazny.woodpecker post-repo task — repo activation
  * Defaults + credentials stubs declared in both roles
  * Stack-up wires both post.yml entries
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── .woodpecker.yml ──────────────────────────────────────────────────────


def test_woodpecker_yml_present():
	p = REPO / ".woodpecker/tests.yml"
	assert p.is_file(), ".woodpecker.yml missing"


def test_woodpecker_yml_parses_as_yaml():
	data = yaml.safe_load((REPO / ".woodpecker/tests.yml").read_text())
	assert isinstance(data, dict)
	assert "steps" in data, "pipeline missing 'steps' top-level key"


def test_woodpecker_pipeline_carries_required_test_steps():
	"""Pipeline MUST run the four canonical anatomy checks (composer
	validate, php -l, pytest, ansible syntax) on every push. Missing
	one of these is the difference between "CI green" and "actually
	tested" — pin it here so a future PR can't quietly drop a step."""
	data = yaml.safe_load((REPO / ".woodpecker/tests.yml").read_text())
	steps = data["steps"]
	required = {"composer-validate", "php-lint", "pytest-anatomy", "ansible-syntax"}
	missing = required - set(steps.keys())
	assert not missing, f"required pipeline steps missing: {missing}"


def test_pytest_step_runs_anatomy_tests():
	data = yaml.safe_load((REPO / ".woodpecker/tests.yml").read_text())
	step = data["steps"]["pytest-anatomy"]
	cmds = "\n".join(step.get("commands", []))
	assert "tests/anatomy/" in cmds


def test_ansible_syntax_step_uses_pinned_floor():
	"""ansible-core floor MUST match requirements.yml (2.20.x today).
	A pipeline running 2.18 against a playbook tested on 2.20 would
	produce false-negatives."""
	data = yaml.safe_load((REPO / ".woodpecker/tests.yml").read_text())
	step = data["steps"]["ansible-syntax"]
	cmds = "\n".join(step.get("commands", []))
	assert "ansible-core" in cmds
	# Must pin upper bound to avoid silent 2.24 surprise.
	assert ">=2.20" in cmds and "<" in cmds


# ── Gitea autowiring ─────────────────────────────────────────────────────


def test_gitea_post_repo_task_present():
	p = REPO / "roles/pazny.gitea/tasks/post-repo.yml"
	assert p.is_file()
	src = p.read_text()
	# Must check for existing repo before creating (idempotent).
	assert "Check if nOS repo already exists" in src
	# Must use the migrate API with mirror: true (not just /repos POST).
	assert "/api/v1/repos/migrate" in src
	assert "mirror: true" in src


def test_gitea_post_repo_uses_admin_basic_auth():
	"""A19 (2026-05-24): the nOS repo-autowire MUST use Gitea Admin Basic auth
	over 127.0.0.1 — NOT a pre-provisioned gitea_api_token (wiped by blank=true
	→ 401 on the first post-blank run) and NOT the public domain (Cloudflare /
	Traefik round-trip). Mirrors woodpecker post-oauth.yml. Single-run robust."""
	src = (REPO / "roles/pazny.gitea/tasks/post-repo.yml").read_text()
	# Admin Basic auth, local port — the robust path.
	assert "gitea_admin_user" in src and "gitea_admin_password" in src
	assert "b64encode" in src
	assert "127.0.0.1" in src
	# The stale-token + public-domain anti-patterns must be gone (the rationale
	# comment may still NAME gitea_api_token; what must not exist is its USE as
	# an auth header or the public-domain URL).
	assert "token {{ gitea_api_token" not in src
	assert "{{ gitea_domain }}" not in src


def test_gitea_defaults_declare_autowire_vars():
	src = (REPO / "roles/pazny.gitea/defaults/main.yml").read_text()
	for var in ("install_gitea_autowire_nos",
	             "gitea_nos_repo_owner",
	             "gitea_nos_repo_name",
	             "gitea_nos_repo_clone_url",
	             "gitea_nos_repo_mirror_interval"):
		assert var in src, f"missing default: {var}"


def test_gitea_post_yml_conditionally_includes_post_repo():
	src = (REPO / "roles/pazny.gitea/tasks/post.yml").read_text()
	assert "post-repo.yml" in src
	assert "install_gitea_autowire_nos" in src


# ── Woodpecker autowiring ────────────────────────────────────────────────


def test_woodpecker_post_repo_task_present():
	p = REPO / "roles/pazny.woodpecker/tasks/post-repo.yml"
	assert p.is_file()
	src = p.read_text()
	# Idempotent activation: must check existing state + skip on 200.
	assert "Check if repo is already activated" in src
	# Activation uses forge_remote_id query param (Woodpecker v3 convention).
	assert "forge_remote_id" in src
	# A16 (2026-05-20): forge cache must be refreshed BEFORE activate —
	# on first run Woodpecker doesn't know about Gitea repos yet so the
	# activate POST would 404. flush=true forces a Gitea sync first.
	assert "flush=true" in src
	# The refresh task MUST come BEFORE the activate POST so the order
	# is correct on fresh installs. Match on the real URL line (not the
	# explanation comment, which mentions /api/repos?forge_remote_id too).
	# The host is matched loosely: 84649c17 moved both calls off the public
	# domain onto `_woodpecker_api` (loopback) because public-domain DNS is
	# fatal here — the ordering is the invariant, the host is not.
	refresh_pos = src.find("flush=true")
	activate_pos = src.find('url: "{{ _woodpecker_api }}/api/repos?forge_remote_id')
	assert 0 < refresh_pos < activate_pos, (
		"refresh task must precede activate task — order matters on "
		"fresh installs (Woodpecker repo cache is empty)"
	)


def test_woodpecker_post_yml_present():
	p = REPO / "roles/pazny.woodpecker/tasks/post.yml"
	assert p.is_file()
	src = p.read_text()
	assert "post-repo.yml" in src
	assert "install_woodpecker_autowire_nos" in src


def test_woodpecker_defaults_declare_autowire_vars():
	src = (REPO / "roles/pazny.woodpecker/defaults/main.yml").read_text()
	for var in ("install_woodpecker_autowire_nos",
	             "woodpecker_nos_repo_owner",
	             "woodpecker_nos_repo_name"):
		assert var in src


# ── Credentials stubs ────────────────────────────────────────────────────


def test_credentials_stubs_declared():
	src = (REPO / "default.credentials.yml").read_text()
	for var in ("gitea_api_token", "woodpecker_api_token"):
		assert var in src


# ── Stack-up wiring ──────────────────────────────────────────────────────


def test_stack_up_wires_woodpecker_post():
	"""Without the include_role entry in stack-up.yml, the post-repo
	task never runs. Was missing in the draft — caught by this gate
	before the first live run."""
	src = (REPO / "tasks/stacks/stack-up.yml").read_text()
	assert "pazny.woodpecker post" in src
	assert "tasks_from: post.yml" in src and "name: pazny.woodpecker" in src


# ── End-of-playbook token reminder ───────────────────────────────────────


def test_final_summary_carries_token_hint_section():
	"""final-summary.yml MUST surface a calibrated operator hint when the one
	still-manual autowire token is missing (woodpecker_api_token, when
	install_woodpecker_autowire_nos is on). Catches a regression where the hint
	section was accidentally removed.

	A19 (2026-05-24): authentik_bootstrap_token is playbook-generated +
	blueprint-pinned, and the gitea repo-autowire now uses Admin Basic auth —
	so neither is a missing token the summary nags about. Only the OAuth-derived
	Woodpecker PAT remains operator-provided."""
	src = (REPO / "tasks/final-summary.yml").read_text()
	assert "OPERATOR ACTION REQUIRED — MISSING TOKEN" in src
	# The one still-manual autowire token must be referenced.
	assert "woodpecker_api_token" in src
	# Retired prerequisites must NOT reappear as an operator-action block (the
	# rationale comment may still NAME gitea_api_token — what must be gone is the
	# "Gitea API token" instruction section and the fetch-tool 2-pass).
	assert "Gitea API token" not in src
	assert "fetch-authentik-bootstrap-token.py" not in src


def test_final_summary_hint_is_conditional_not_unconditional():
	"""Hint must only fire when something is missing — otherwise it
	noise-pollutes every successful playbook completion. Pinned via
	the presence of the conditional set blocks."""
	src = (REPO / "tasks/final-summary.yml").read_text()
	assert "_need_wp_token" in src
	# A19: gitea now uses admin Basic auth (no token), so _need_gitea_token is
	# retired — only the Woodpecker PAT can be missing. Hint must NOT be
	# unconditional, and must not resurrect the gitea-token guard.
	assert "_need_gitea_token" not in src
	assert "{% if _need_wp_token %}" in src
