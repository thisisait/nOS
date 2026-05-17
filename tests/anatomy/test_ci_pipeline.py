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
	p = REPO / ".woodpecker.yml"
	assert p.is_file(), ".woodpecker.yml missing"


def test_woodpecker_yml_parses_as_yaml():
	data = yaml.safe_load((REPO / ".woodpecker.yml").read_text())
	assert isinstance(data, dict)
	assert "steps" in data, "pipeline missing 'steps' top-level key"


def test_woodpecker_pipeline_carries_required_test_steps():
	"""Pipeline MUST run the four canonical anatomy checks (composer
	validate, php -l, pytest, ansible syntax) on every push. Missing
	one of these is the difference between "CI green" and "actually
	tested" — pin it here so a future PR can't quietly drop a step."""
	data = yaml.safe_load((REPO / ".woodpecker.yml").read_text())
	steps = data["steps"]
	required = {"composer-validate", "php-lint", "pytest-anatomy", "ansible-syntax"}
	missing = required - set(steps.keys())
	assert not missing, f"required pipeline steps missing: {missing}"


def test_pytest_step_runs_anatomy_tests():
	data = yaml.safe_load((REPO / ".woodpecker.yml").read_text())
	step = data["steps"]["pytest-anatomy"]
	cmds = "\n".join(step.get("commands", []))
	assert "tests/anatomy/" in cmds


def test_ansible_syntax_step_uses_pinned_floor():
	"""ansible-core floor MUST match requirements.yml (2.20.x today).
	A pipeline running 2.18 against a playbook tested on 2.20 would
	produce false-negatives."""
	data = yaml.safe_load((REPO / ".woodpecker.yml").read_text())
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


def test_gitea_post_repo_requires_token():
	"""install_gitea_autowire_nos=true MUST fail closed if the operator
	hasn't provisioned gitea_api_token. Silent skip would leave the
	mirror unconfigured with no diagnostic."""
	src = (REPO / "roles/pazny.gitea/tasks/post-repo.yml").read_text()
	assert "gitea_api_token" in src
	assert "ansible.builtin.fail" in src


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
	"""final-summary.yml MUST surface a calibrated operator hint when any
	of the three high-impact tokens is missing (authentik_bootstrap_token
	when wing+authentik installed; gitea_api_token / woodpecker_api_token
	when the matching autowire toggle is on). Catches a regression where
	the hint section was accidentally removed."""
	src = (REPO / "tasks/final-summary.yml").read_text()
	assert "OPERATOR ACTION REQUIRED — MISSING TOKENS" in src
	# All three tokens must be referenced.
	assert "authentik_bootstrap_token" in src
	assert "gitea_api_token" in src
	assert "woodpecker_api_token" in src
	# Hint must point to fetch-authentik-bootstrap-token.py — the
	# canonical operator path documented in tools/.
	assert "fetch-authentik-bootstrap-token.py" in src


def test_final_summary_hint_is_conditional_not_unconditional():
	"""Hint must only fire when something is missing — otherwise it
	noise-pollutes every successful playbook completion. Pinned via
	the presence of the conditional set blocks."""
	src = (REPO / "tasks/final-summary.yml").read_text()
	assert "_need_gitea_token" in src
	assert "_need_wp_token" in src
	# The wrapping `{% if _need_gitea_token or _need_wp_token or ...%}`
	# must include the authentik bootstrap path too.
	assert "_have_authentik_bootstrap" in src
