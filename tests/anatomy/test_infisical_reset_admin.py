"""Anatomy gate — Infisical admin reset recovery path (SEC-5, 2026-05-23).

Operator's live 2026-05-23 lockout: Infisical PG had admin email
pazny.develop@gmail.com (from a stale prior bootstrap) but
default.credentials.yml resolves admin@pazny.eu now. No token persisted
in ~/.nos/secrets.yml. SRP-based password verification means a raw
JSON POST to /api/v3/auth/login fails ("Invalid credentials") even
with the correct prefix-derived password. seed.py returns exit 2 with
"admin already bootstrapped but no token persisted" — the only recovery
path was blank=true (destroys all infra state).

SEC-5 ships `roles/pazny.infisical/tasks/reset-admin.yml` — a tag-gated
break-glass that:
  1. Pre-checks projects + secrets counts; refuses without
     `infisical_reset_force=true` if non-empty.
  2. TRUNCATEs users + organizations + dependent tables in PG.
  3. Re-invokes seed.py bootstrap; canonical admin@<tld> with
     prefix-derived password is created from scratch.

Pinned: the task file exists, tag-gated invocation in core-up.yml,
explicit safety gate on non-empty data, FK-safe cascade truncate,
post-reset re-bootstrap.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
RESET = REPO / "roles/pazny.infisical/tasks/reset-admin.yml"
COREUP = REPO / "tasks/stacks/core-up.yml"


def test_reset_admin_task_exists():
	assert RESET.is_file(), "reset-admin.yml break-glass missing"


def test_reset_gated_by_tag_never_in_normal_run():
	"""The reset MUST be tag-gated AND carry `tags: ['never', ...]` so
	a default `ansible-playbook main.yml` (no --tags) never accidentally
	wipes the Infisical admin. Only operator-explicit invocation."""
	src = COREUP.read_text()
	# Find the reset-admin include block.
	idx = src.find("pazny.infisical reset-admin")
	assert idx > 0, "reset-admin include missing from core-up.yml"
	block = src[idx:idx + 800]
	assert "'never'" in block, \
		"reset-admin include must carry tag 'never' so it doesn't run by default"
	assert "'infisical-reset-admin' in ansible_run_tags" in block, \
		"reset-admin must additionally gate on explicit --tags invocation"


def test_reset_refuses_non_empty_data_without_force():
	"""Operator's safety net: if projects > 0 OR secrets > 0, the reset
	must fail loud and require `infisical_reset_force=true` to proceed.
	Prevents accidental data loss when re-using the recovery path on a
	non-empty install."""
	src = RESET.read_text()
	assert "_infisical_projects_count" in src
	assert "_infisical_secrets_count" in src
	# The fail task must check the counts AND the force flag.
	assert "infisical_reset_force" in src
	# Fail message must surface the count + the override flag.
	assert "ansible.builtin.fail:" in src


def test_reset_uses_cascade_truncate_for_fk_safety():
	"""PostgreSQL TRUNCATE on FK-joined tables needs CASCADE. RESTART
	IDENTITY is belt-and-suspenders (avoids sequence drift on next
	bootstrap)."""
	src = RESET.read_text()
	assert "TRUNCATE" in src
	assert "CASCADE" in src
	assert "RESTART IDENTITY" in src
	# Must truncate at least users + organizations (the two root tables).
	assert "users," in src
	assert "organizations," in src


def test_reset_clears_persisted_secrets_then_rebootstraps():
	"""After PG wipe, the operator's ~/.nos/secrets.yml still has the
	stale admin_token + machine-identity creds — those would shortcut
	seed.py's bootstrap and leave the playbook in a broken state.
	Clear them first, then re-run seed.yml."""
	src = RESET.read_text()
	# Clear fact must zero all four stale values.
	for var in (
		"infisical_admin_token",
		"infisical_machine_id_client_id",
		"infisical_machine_id_client_secret",
		"infisical_users_project_id",
	):
		assert f"{var}: " in src, f"reset must clear {var}"
	# Must re-render secrets.yml with the cleared values.
	assert 'src: "secrets.yml.j2"' in src
	# Must re-include seed.yml to recreate the canonical admin + projects.
	assert "include_tasks: seed.yml" in src
