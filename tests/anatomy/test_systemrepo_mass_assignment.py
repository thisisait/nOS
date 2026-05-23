"""Anatomy gate — SystemRepository write whitelisting + HubPresenter
POST auth gate (SEC-7, 2026-05-23).

Audit finding: HubPresenter declared `publicActions = ['systems',
'health']`, but `systems` action handled both GET (read, legitimately
public) AND POST (upsert into the registry). Combined with
`SystemRepository::upsert($data)` passing the entire decoded JSON body
to Nette `->insert($data)`, any client able to reach 127.0.0.1:9000
could:
  - Forge arbitrary registry rows (id, name, url, ...).
  - Subvert actionHealth's "URL must be in DB" SSRF guard by
    pre-inserting a malicious URL.
  - Write to internal columns (health_status, scan_priority, ...) the
    operator/agent should never control.

Two layers of structural fix:
  1. SystemRepository::upsert filters body via WRITABLE_FIELDS allowlist
     before insert/update. Health/audit columns silently dropped.
  2. HubPresenter::startup() bypasses requireTokenAuth ONLY for
     GET /systems; POST hits the standard Bearer-auth path because
     `systems` is no longer in $publicActions.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_systemrepo_has_writable_fields_whitelist():
	"""WRITABLE_FIELDS constant must enumerate only the install-shape
	columns Ansible's nos_apps_render + service_registry tasks
	legitimately write. Health / audit / scan_* columns explicitly
	excluded."""
	src = (REPO / "files/anatomy/wing/app/Model/SystemRepository.php").read_text()
	assert "WRITABLE_FIELDS" in src, "SystemRepository must declare WRITABLE_FIELDS constant"
	# Extract the constant body.
	m = re.search(r"WRITABLE_FIELDS\s*=\s*\[(.*?)\];", src, re.DOTALL)
	assert m, "WRITABLE_FIELDS array literal not found"
	body = m.group(1)
	# Allowed: install-shape fields.
	for col in ("id", "name", "type", "category", "stack", "domain", "url", "port", "enabled"):
		assert f"'{col}'" in body, f"WRITABLE_FIELDS missing expected column '{col}'"
	# Banned: health + audit + scan + sensitive columns.
	for col in ("health_status", "health_http_code", "created_at", "scan_priority"):
		assert f"'{col}'" not in body, (
			f"WRITABLE_FIELDS MUST NOT include '{col}' — owned by setHealth() "
			f"or the DB, not by operator/agent input"
		)


def test_systemrepo_upsert_filters_via_array_intersect():
	"""The whitelist must be APPLIED — `array_intersect_key($data,
	array_flip(WRITABLE_FIELDS))` is the canonical PHP filter idiom."""
	src = (REPO / "files/anatomy/wing/app/Model/SystemRepository.php").read_text()
	# upsert() body must contain the intersect_key call referencing the
	# whitelist constant.
	m = re.search(r"public function upsert\(.*?\)\s*:\s*void\s*\{(.*?)\n\t\}", src, re.DOTALL)
	assert m, "upsert() method not found"
	body = m.group(1)
	assert "array_intersect_key" in body, \
		"upsert() must filter input via array_intersect_key against WRITABLE_FIELDS"
	assert "WRITABLE_FIELDS" in body, \
		"upsert() must reference the WRITABLE_FIELDS whitelist"
	# Insert/update must use the FILTERED variable, not the raw $data.
	# Search for `->insert($filtered)` and `->update($filtered)` patterns.
	assert "->insert($filtered)" in body, "upsert() must insert FILTERED data, not raw $data"
	assert "->update($filtered)" in body, "upsert() must update FILTERED data, not raw $data"


def test_hubpresenter_drops_systems_from_public_actions():
	"""`systems` action must NOT be in $publicActions — POST is no
	longer a no-auth surface. GET is recovered via method-aware
	startup() override."""
	src = (REPO / "files/anatomy/wing/app/Presenters/Api/HubPresenter.php").read_text()
	m = re.search(r"\$publicActions\s*=\s*\[(.*?)\]", src)
	assert m, "publicActions array not found"
	allowed = m.group(1)
	assert "'systems'" not in allowed, \
		"HubPresenter must NOT include 'systems' in publicActions (POST = unauthenticated write surface)"
	# health stays public (read-only).
	assert "'health'" in allowed


def test_hubpresenter_startup_bypasses_auth_only_for_get():
	"""GET /systems is public; POST /systems is Bearer-authed. The
	startup() override implements this with an explicit GET-only short
	circuit; everything else falls through to BaseApiPresenter."""
	src = (REPO / "files/anatomy/wing/app/Presenters/Api/HubPresenter.php").read_text()
	# Must override startup().
	assert "public function startup(): void" in src
	# Must check method == 'GET' before short-circuiting.
	m = re.search(r"public function startup\(\): void\s*\{(.*?)\n\t\}", src, re.DOTALL)
	assert m
	body = m.group(1)
	assert "'GET'" in body
	# Must call parent::startup() in the non-GET branch.
	assert "parent::startup()" in body, \
		"non-GET requests must fall through to BaseApiPresenter::startup (requireTokenAuth)"
