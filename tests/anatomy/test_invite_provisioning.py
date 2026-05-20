"""Anatomy gates for the A18 invite-flow Cesta B Hybrid (2026-05-20).

Pins:
  * Wing-side InfisicalClient + StalwartProvisioner PHP classes
    structure (constructor envs, isConfigured() gate, write methods).
  * Path/key validation regex — username + secret key must follow the
    same shape across both clients so a single username flows through
    without re-validation downstream.
  * UsersPresenter wiring (DI + maybeProvisionCredentials call before
    redirect).
  * Schema column user_invitations.provisioning_json + idempotent
    init-db.php ALTER sweep.
  * wing.plist.j2 propagates the env trio (Infisical + Stalwart +
    NOS_INVITE_PROVISIONING_ENABLED).
  * Stalwart role pinned to v0.16+ with the JMAP-era image name.

These pins exist because A18 weaves four layers (role + plugin + PHP
+ schema). A future PR that drops one of them silently degrades the
invite flow without surfacing the regression — these tests fail loud.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── Wing PHP — InfisicalClient ───────────────────────────────────────────

INFISICAL = REPO / "files/anatomy/wing/app/Model/InfisicalClient.php"


def test_infisical_client_present():
	assert INFISICAL.is_file()


def test_infisical_client_php_syntax_clean():
	if shutil.which("php") is None:
		pytest.skip("php not on PATH — CI pytest-only image; local dev runs the lint")
	r = subprocess.run(["php", "-l", str(INFISICAL)], capture_output=True, text=True)
	assert r.returncode == 0, r.stderr


def test_infisical_client_reads_env_for_token_and_project():
	src = INFISICAL.read_text()
	assert "INFISICAL_API_URL" in src
	assert "INFISICAL_API_TOKEN" in src
	assert "INFISICAL_USERS_PROJECT_ID" in src
	assert "INFISICAL_USERS_ENVIRONMENT" in src


def test_infisical_client_is_configured_gate():
	"""isConfigured() must return false when either token or project_id
	is empty — graceful-degradation contract."""
	src = INFISICAL.read_text()
	assert "public function isConfigured(): bool" in src
	# Both fields must be in the gate condition.
	assert "bearerToken" in src
	assert "projectId" in src


def test_infisical_client_validates_username():
	"""Username goes into Infisical paths + Bone audit events; reject
	anything that could escape the path."""
	src = INFISICAL.read_text()
	assert "assertUsernameSafe" in src
	# Pattern must match the Stalwart provisioner's local-part regex
	# so a single username flows through both without re-validation.
	assert re.search(
		r"\^\[a-z0-9\]\[a-z0-9\._-\]\{0,\d+\}\$",
		src,
	)


def test_infisical_client_rejects_consecutive_dots():
	"""Security review C5 (2026-05-20): the character-class regex alone
	allows `a..b` — could collide with downstream consumers that path-
	canonicalize `..` as parent traversal. Reject outright."""
	src = INFISICAL.read_text()
	assert "str_contains($username, '..')" in src


def test_infisical_client_validates_tenant():
	"""Security review C3 (2026-05-20): tenant goes into the secret path
	(`/users/<tenant>/<username>`), so a malicious tenant slug like
	`../escape` would be a path-injection vector. Tighten matching the
	presenter's tenant regex."""
	src = INFISICAL.read_text()
	assert "assertTenantSafe" in src


def test_infisical_client_three_public_methods():
	"""Surface must stay small: createUserFolder, upsertSecret,
	listUserSecrets, isConfigured. Adding more risks turning this into a
	general-purpose Infisical client instead of the invite-flow helper."""
	src = INFISICAL.read_text()
	publics = re.findall(r"public function (\w+)\(", src)
	# Allow constructor + the four documented methods.
	assert set(publics) - {"__construct"} == {
		"isConfigured", "createUserFolder", "upsertSecret", "listUserSecrets",
	}, f"unexpected public methods: {publics}"


def test_infisical_client_methods_take_tenant_param():
	"""Security review C3: path is `/users/<tenant>/<username>` — every
	write method must accept tenant as the first arg so cross-tenant
	collision is impossible by construction."""
	src = INFISICAL.read_text()
	assert "public function createUserFolder(string $tenant, string $username)" in src
	assert "public function upsertSecret(string $tenant, string $username, string $key, string $value)" in src
	assert "public function listUserSecrets(string $tenant, string $username)" in src


def test_infisical_client_suppresses_response_body_in_exceptions():
	"""Security review C6: raw response body fragments must NOT propagate
	into RuntimeException messages — they can include peer-tenant
	metadata or other users' secret names that would flow into Wing's
	/events row + launchd.err.log."""
	src = INFISICAL.read_text()
	# Must NOT include `substr((string) $raw, 0, 500)` in any error path.
	assert "substr((string) $raw, 0, 500)" not in src
	# Must reference the redacted-body marker so future PRs that re-add
	# raw bodies fail this gate visibly.
	assert "body suppressed" in src


# ── Wing PHP — StalwartProvisioner ──────────────────────────────────────

STALWART = REPO / "files/anatomy/wing/app/Model/StalwartProvisioner.php"


def test_stalwart_provisioner_present():
	assert STALWART.is_file()


def test_stalwart_provisioner_php_syntax_clean():
	if shutil.which("php") is None:
		pytest.skip("php not on PATH")
	r = subprocess.run(["php", "-l", str(STALWART)], capture_output=True, text=True)
	assert r.returncode == 0, r.stderr


def test_stalwart_provisioner_targets_jmap_endpoint():
	"""v0.16+ replaced REST management API with JMAP — the provisioner
	must POST to /jmap, not /api/admin/* or similar."""
	src = STALWART.read_text()
	assert "JMAP_PATH = '/jmap'" in src
	# JMAP requires the `using` capability array.
	assert "JMAP_USING" in src
	assert "urn:stalwart:jmap" in src


def test_stalwart_provisioner_uses_principal_set():
	"""Account creation is a Principal/set methodCall in v0.16."""
	src = STALWART.read_text()
	assert "'Principal/set'" in src


def test_stalwart_provisioner_reads_env_for_admin():
	src = STALWART.read_text()
	assert "STALWART_API_URL" in src
	assert "STALWART_ADMIN_USER" in src
	assert "STALWART_ADMIN_PASSWORD" in src


def test_stalwart_provisioner_uses_basic_auth():
	"""JMAP management API accepts HTTP Basic on admin creds (per v0.16
	docs). Mirroring this here so a regression to no-auth or query-string
	tokens fails CI."""
	src = STALWART.read_text()
	assert "CURLAUTH_BASIC" in src
	assert "CURLOPT_USERPWD" in src


def test_stalwart_provisioner_validates_password_min_length():
	"""≥12 chars — Stalwart hashes server-side, but a 4-char password
	would let an operator typo make /jmap accept garbage."""
	src = STALWART.read_text()
	assert "strlen($password) < 12" in src


def test_stalwart_provisioner_rejects_consecutive_dots():
	"""Security review C5: RFC 5321 forbids `..` in local-part anyway,
	and downstream consumers could canonicalize as parent traversal."""
	src = STALWART.read_text()
	assert "str_contains($local, '..')" in src


def test_stalwart_provisioner_suppresses_response_body():
	"""Security review C6: Stalwart's notCreated response echoes the
	existing principal's `name` — leaking peer-user emails into Wing
	logs. Sanitize."""
	src = STALWART.read_text()
	# Raw response slice must NOT be in any error path.
	assert "substr((string) $raw, 0, 500)" not in src
	# notCreated path must use the calibrated `reason=<type>` form
	# rather than echoing the whole error object.
	assert "reason=" in src
	# Must reject any free-form error type — only allow the canonical
	# alphabetic slug.
	assert "preg_match('/^[a-zA-Z][a-zA-Z0-9_]{0,63}$/'" in src


# ── UsersPresenter wiring ────────────────────────────────────────────────

PRESENTER = REPO / "files/anatomy/wing/app/Presenters/UsersPresenter.php"


def test_users_presenter_imports_both_clients():
	src = PRESENTER.read_text()
	assert "use App\\Model\\InfisicalClient;" in src
	assert "use App\\Model\\StalwartProvisioner;" in src


def test_users_presenter_constructor_injects_both_clients():
	"""DI must wire InfisicalClient + StalwartProvisioner so the
	presenter doesn't `new` them inline (would bypass test seams)."""
	src = PRESENTER.read_text()
	# Both must appear in the constructor signature with the `private`
	# promotion.
	assert "private InfisicalClient $infisical" in src
	assert "private StalwartProvisioner $stalwart" in src


def test_users_presenter_provisions_before_redirect():
	"""maybeProvisionCredentials must be called AFTER the Authentik
	invitation lands and BEFORE redirect — otherwise the events row +
	provisioning_json snapshot are racy."""
	src = PRESENTER.read_text()
	idx_invoke = src.find("$this->maybeProvisionCredentials(")
	idx_redirect = src.find("$this->redirect('Users:created'")
	assert idx_invoke > 0
	assert idx_redirect > idx_invoke


def test_users_presenter_gated_by_env_toggle():
	"""NOS_INVITE_PROVISIONING_ENABLED env must be the master gate so
	legacy installs aren't surprised. Removing this gate silently flips
	the extension on for every operator."""
	src = PRESENTER.read_text()
	assert "NOS_INVITE_PROVISIONING_ENABLED" in src


def test_users_presenter_graceful_degradation_on_downstream_failure():
	"""Each downstream client failure must be caught as RuntimeException
	and recorded in result.errors — never propagate up to abort the
	Authentik invitation that already succeeded."""
	src = PRESENTER.read_text()
	# The provisioning method must catch RuntimeException explicitly.
	assert "catch (RuntimeException $e)" in src
	# And there must be at least 2 such catches (one per downstream).
	assert src.count("catch (RuntimeException $e)") >= 2


def test_users_presenter_emits_provisioned_event():
	"""user_invitation_provisioned event is the audit-trail join point."""
	src = PRESENTER.read_text()
	assert "'user_invitation_provisioned'" in src


def test_users_presenter_idempotency_preflight():
	"""Security review C4: before provisioning, query Infisical for
	existing user secrets — if any are present, this is a re-invite and
	we must skip the whole block (otherwise we generate a new password
	that orphans the existing Stalwart mailbox)."""
	src = PRESENTER.read_text()
	# Must call listUserSecrets before the create/upsert pair.
	assert "listUserSecrets($tenant, $localPart)" in src
	# Must emit the dedicated skip event on re-invite.
	assert "'user_invitation_provisioning_skipped'" in src
	# `already_provisioned` must be the skip reason slug.
	assert "'already_provisioned'" in src


def test_users_presenter_namespaces_by_tenant():
	"""Security review C3: Infisical paths are `/users/<tenant>/<user>/`,
	never the old flat `/users/<user>/`. Every call site must pass
	$tenant explicitly so cross-tenant collision is impossible."""
	src = PRESENTER.read_text()
	# All three Infisical calls must pass $tenant as the first arg.
	assert "createUserFolder($tenant, $localPart)" in src
	assert "upsertSecret($tenant, $localPart, 'mailbox_password'" in src


def test_users_presenter_uses_tenant_domain_env_for_mailbox():
	"""Security review C7: the Stalwart mailbox domain MUST come from
	the operator's configured mail domain (TENANT_DOMAIN env), NOT from
	email_hint's @-suffix — email_hint is just where the operator might
	forward the enrollment URL to (gmail.com etc.), the mailbox itself
	lives on the local mail domain."""
	src = PRESENTER.read_text()
	# Must read TENANT_DOMAIN, not split email_hint's domain part.
	assert "getenv('TENANT_DOMAIN')" in src
	# Must pass that var to createMailbox, not `$domain` from email_hint.
	assert "$this->stalwart->createMailbox(" in src
	# The old buggy pattern (using email-hint domain) must be gone.
	# Confirm the call site reads $mailboxDomain (the env-sourced one).
	assert "$mailboxDomain" in src


def test_users_presenter_sanitizes_error_messages():
	"""Security review C6: even though the underlying clients redact,
	defense-in-depth strips any non-whitelisted chars from the error
	messages before stashing them in provisioning_json / events row."""
	src = PRESENTER.read_text()
	assert "sanitizeErrorMessage" in src
	# The whitelist must allow only printable safe chars; anything else
	# collapses to a generic placeholder.
	assert "preg_replace" in src
	assert "(redacted)" in src


def test_users_presenter_no_localpart_dot_dot():
	"""Local-part with `..` is rejected at the presenter level too, so
	the InfisicalClient/StalwartProvisioner regexes are belt-and-suspenders."""
	src = PRESENTER.read_text()
	assert "str_contains($localPart, '..')" in src


# ── Schema + idempotent ALTER ────────────────────────────────────────────


def test_user_invitations_schema_has_provisioning_column():
	src = (REPO / "files/anatomy/wing/db/schema-extensions.sql").read_text()
	assert "provisioning_json" in src
	# Must be NOT NULL with '{}' default — never write NULLs so listAll
	# code path doesn't need null-checks.
	assert "provisioning_json   TEXT NOT NULL DEFAULT '{}'" in src


def test_init_db_alters_provisioning_column_on_legacy_dbs():
	"""Legacy DBs (pre-A18) must get the column added via the idempotent
	sweep — otherwise UPDATE in setProvisioningResult() crashes with
	`no such column`."""
	src = (REPO / "files/anatomy/wing/bin/init-db.php").read_text()
	# The sweep must call addMissingColumns on the user_invitations table
	# with provisioning_json.
	m = re.search(
		r"addMissingColumns\(\$db,\s*'user_invitations',\s*\[(.*?)\]",
		src,
		re.DOTALL,
	)
	assert m, "user_invitations addMissingColumns sweep not present"
	assert "provisioning_json" in m.group(1)


def test_repository_has_set_provisioning_result():
	src = (REPO / "files/anatomy/wing/app/Model/UserInvitationRepository.php").read_text()
	assert "public function setProvisioningResult(int $rowId, array $result): void" in src


# ── Env wiring (wing.plist.j2) ──────────────────────────────────────────


def test_wing_plist_carries_all_provisioning_envs():
	src = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
	# Master toggle must always be present (gated on the var).
	assert "NOS_INVITE_PROVISIONING_ENABLED" in src
	# Infisical block — gated on install_infisical so a Wing-only host
	# doesn't carry empty Infisical envs.
	assert "INFISICAL_API_URL" in src
	assert "INFISICAL_API_TOKEN" in src
	assert "INFISICAL_USERS_PROJECT_ID" in src
	# Stalwart block — gated on install_smtp_stalwart.
	assert "STALWART_API_URL" in src
	assert "STALWART_ADMIN_USER" in src
	assert "STALWART_ADMIN_PASSWORD" in src


def test_default_config_declares_toggle_and_users_project():
	src = (REPO / "default.config.yml").read_text()
	assert "nos_invite_provisioning_enabled: false" in src
	assert "infisical_users_project_id:" in src
	assert "infisical_users_environment:" in src


def test_default_config_seeds_nos_users_infisical_project():
	"""Seed.py auto-creates the `nos-users` project on first run; the
	operator then copies its UUID into infisical_users_project_id."""
	src = (REPO / "default.config.yml").read_text()
	assert "slug: nos-users" in src


# ── DI registration (common.neon) ───────────────────────────────────────


def test_di_registers_both_clients():
	src = (REPO / "files/anatomy/wing/app/config/common.neon").read_text()
	assert "App\\Model\\InfisicalClient" in src
	assert "App\\Model\\StalwartProvisioner" in src


# ── Stalwart role v0.16 upgrade pins ────────────────────────────────────


def test_stalwart_role_pinned_to_v0_16_or_newer():
	"""v0.16+ is the JMAP-era. Anything older would break the
	StalwartProvisioner JMAP path."""
	src = (REPO / "roles/pazny.smtp_stalwart/defaults/main.yml").read_text()
	# Pin must be the new image name (stalwartlabs/stalwart, not
	# stalwartlabs/mail-server) AND a v0.16+ tag.
	m = re.search(r"stalwart_image:\s*\"stalwartlabs/stalwart:v(\d+)\.(\d+)\.\d+\"", src)
	assert m, "stalwart_image must use the new stalwartlabs/stalwart image name"
	major, minor = int(m.group(1)), int(m.group(2))
	assert (major, minor) >= (0, 16), \
		f"stalwart_image must be v0.16+ for JMAP support (got v{major}.{minor})"


def test_stalwart_role_exposes_admin_port_for_wing():
	"""Wing reaches /jmap on stalwart_port_admin (defaults 8080). The
	default must be declared so wing.plist.j2's `default(8080)` lines
	up with what compose.yml.j2 actually publishes."""
	src = (REPO / "roles/pazny.smtp_stalwart/defaults/main.yml").read_text()
	assert "stalwart_port_admin:" in src


def test_stalwart_compose_publishes_admin_port_to_localhost():
	"""Wing is on host launchd — it reaches Stalwart via 127.0.0.1, NOT
	via Traefik (would add TLS + cert validation for no security gain on
	a server-internal call)."""
	src = (REPO / "roles/pazny.smtp_stalwart/templates/compose.yml.j2").read_text()
	assert "127.0.0.1:{{ stalwart_port_admin }}:8080" in src


def test_stalwart_compose_uses_v016_env_vars():
	"""v0.11 used MAIL_DOMAIN/MAIL_HOSTNAME/MAIL_ADMIN_USER/MAIL_ADMIN_PASS;
	v0.16 replaced them with STALWART_RECOVERY_ADMIN + STALWART_PUBLIC_URL.
	Reverting to MAIL_* would break first-boot on the new image."""
	src = (REPO / "roles/pazny.smtp_stalwart/templates/compose.yml.j2").read_text()
	assert "STALWART_RECOVERY_ADMIN" in src
	assert "STALWART_PUBLIC_URL" in src
	assert "MAIL_ADMIN_USER" not in src
	assert "MAIL_ADMIN_PASS" not in src


def test_stalwart_compose_traefik_route_scoped_to_admin_path():
	"""Security review C2 (2026-05-20): the public Traefik router must
	carry `PathPrefix(/admin)` so the JMAP management endpoint stays
	internal-only. Without this, forward-auth gates ACCESS only — any
	Tier-4 guest (Kiwix/Jellyfin user) lands on /jmap with a valid
	Authentik session and can brute-force the admin Basic-auth at HTTP
	speed. Wing reaches /jmap via 127.0.0.1:<stalwart_port_admin>,
	never publicly."""
	src = (REPO / "roles/pazny.smtp_stalwart/templates/compose.yml.j2").read_text()
	# The route rule must include the admin-path scope alongside Host(...).
	assert "PathPrefix(`/admin`)" in src
	# And the Host alone (no path constraint) must NOT match — that
	# would defeat the whole point.
	m = re.search(
		r"routers\.smtp-stalwart-webadmin\.rule=Host\([^)]+\)(\s*&&\s*PathPrefix\(`[^`]+`\))?",
		src,
	)
	assert m and m.group(1), \
		"Stalwart webadmin route must combine Host() with a PathPrefix() — Host-only exposes /jmap publicly"


def test_anatomy_plist_files_locked_to_0600():
	"""Security review C1 (2026-05-20): Wing / Bone / Pulse plists embed
	admin tokens (Infisical, Stalwart, Authentik bootstrap, Bone HMAC,
	deploy HMAC). 0644 lets any peer process (Spotlight, backup agents,
	other launchd jobs, Full-Disk-Access apps) read the whole credential
	surface. Pin 0600 for all three so a regression is loud."""
	for role in ("wing", "bone", "pulse"):
		main_yml = REPO / f"roles/pazny.{role}/tasks/main.yml"
		src = main_yml.read_text()
		# Find the launchd-plist render task and confirm its mode.
		m = re.search(
			r"src:\s*" + role + r"\.plist\.j2.*?mode:\s*'(\d+)'",
			src,
			re.DOTALL,
		)
		assert m, f"pazny.{role}/tasks/main.yml: launchd plist render task not found or has no mode"
		assert m.group(1) == "0600", \
			f"pazny.{role}/tasks/main.yml: plist mode must be 0600 (got {m.group(1)})"


def test_stalwart_compose_uses_v016_volume_layout():
	"""v0.16 reshuffled /opt/stalwart-mail/{etc,logs,queue} into
	/etc/stalwart + /var/lib/stalwart. The role must mount the new
	paths or Stalwart can't find its config.json."""
	src = (REPO / "roles/pazny.smtp_stalwart/templates/compose.yml.j2").read_text()
	assert ":/etc/stalwart" in src
	assert ":/var/lib/stalwart" in src
	assert "/opt/stalwart-mail" not in src
