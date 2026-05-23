"""Anatomy gate — Wing edge-trust signature (SEC-6, 2026-05-23).

Pre-SEC-6 trust model: BasePresenter trusted X-Authentik-Username +
X-Authentik-Groups unconditionally. Wing's Caddyfile bound `:9000`
(all interfaces) so any local UID, any docker container with
host-gateway DNS, or any LAN-reachable client could direct-curl
`Authorization` headers and bypass RBAC entirely.

Defense in depth:
  Layer 1 — Caddyfile binds 127.0.0.1 (Wing.Caddyfile.j2). Only the
            local loopback reaches the listener. host.docker.internal
            still resolves to loopback inside Docker Desktop on macOS,
            so Traefik continues to reach it.
  Layer 2 — BasePresenter::enforceEdgeTrust() validates
            X-Wing-Edge-Token against WING_EDGE_TOKEN env. Traefik
            wing-edge@file middleware injects it on every legitimate
            request. Direct-loopback requests bypass Traefik and
            arrive without the header → 403.

This gate pins both layers + the lazy-regen of wing_edge_token.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_wing_caddyfile_explicitly_binds_loopback():
	"""Caddyfile uses `bind 127.0.0.1` inside the :9000 server block.
	The bare `:9000` site address alone makes FrankenPHP bind all
	interfaces (IPv6 wildcard *:9000)."""
	src = (REPO / "roles/pazny.wing/templates/wing.Caddyfile.j2").read_text()
	# The server block + explicit bind line.
	assert ":9000 {" in src, "Wing Caddyfile must declare :9000 server block"
	# Must contain `bind 127.0.0.1` somewhere inside the :9000 block.
	# Extract the block.
	m = re.search(r":9000\s*\{(.*?)\n\}", src, re.DOTALL)
	assert m, ":9000 server block boundaries not found"
	block = m.group(1)
	assert re.search(r"^\s*bind\s+127\.0\.0\.1\b", block, re.MULTILINE), \
		"Wing :9000 block must contain `bind 127.0.0.1` (else binds all interfaces)"


def test_base_presenter_validates_edge_token():
	src = (REPO / "files/anatomy/wing/app/Presenters/BasePresenter.php").read_text()
	# Must declare enforceEdgeTrust method.
	assert "enforceEdgeTrust" in src
	# Must read WING_EDGE_TOKEN env.
	assert "getenv('WING_EDGE_TOKEN')" in src
	# Must read X-Wing-Edge-Token header.
	assert "X-Wing-Edge-Token" in src
	# Must use timing-safe compare.
	assert "hash_equals" in src
	# Must call enforceEdgeTrust from startup().
	startup_match = re.search(r"public function startup\(\): void\s*\{(.*?)\n\t\}", src, re.DOTALL)
	assert startup_match, "BasePresenter::startup() override not found"
	startup_body = startup_match.group(1)
	assert "enforceEdgeTrust" in startup_body, \
		"startup() must call enforceEdgeTrust"
	assert "parent::startup()" in startup_body, \
		"startup() must call parent::startup() for Nette lifecycle"


def test_base_presenter_graceful_when_token_unset():
	"""Fresh install pre-regen: WING_EDGE_TOKEN env may be empty. The
	validator MUST NOT 403 in that case (else the operator's first run
	can't reach Wing to set up). Subsequent runs after lazy-regen
	populates the value will activate the gate."""
	src = (REPO / "files/anatomy/wing/app/Presenters/BasePresenter.php").read_text()
	# Look for the explicit empty-string short-circuit.
	# Pattern: `if ($expected === '') { return; }` or similar
	m = re.search(r"function enforceEdgeTrust.*?\}", src, re.DOTALL)
	assert m
	body = m.group(0)
	assert "=== ''" in body or '== ""' in body or "empty(" in body, \
		"enforceEdgeTrust must short-circuit when WING_EDGE_TOKEN is empty"


def test_traefik_middleware_injects_edge_token():
	src = (REPO / "roles/pazny.traefik/templates/dynamic/middlewares.yml.j2").read_text()
	# Middleware named wing-edge declared.
	assert "wing-edge:" in src
	# Uses customRequestHeaders (REPLACES client-sent headers).
	assert "customRequestHeaders:" in src
	# Sets the X-Wing-Edge-Token header from the var.
	assert "X-Wing-Edge-Token:" in src
	assert "wing_edge_token" in src


def test_traefik_services_attaches_wing_edge_to_wing_router_only():
	src = (REPO / "roles/pazny.traefik/templates/dynamic/services.yml.j2").read_text()
	# Conditional Jinja that appends wing-edge@file only when service id == 'wing'.
	# Pattern in the template:
	#   {% set _extra_mw = ['wing-edge@file'] if s.id == 'wing' else [] %}
	assert "'wing-edge@file'" in src
	assert "s.id == 'wing'" in src


def test_credentials_template_declares_wing_edge_token():
	src = (REPO / "default.credentials.yml").read_text()
	assert "wing_edge_token:" in src


def test_lazy_regen_includes_wing_edge_token():
	src = (REPO / "main.yml").read_text()
	# Must regen wing_edge_token via openssl rand -hex 32.
	m = re.search(
		r"^\s*wing_edge_token:\s*\".*openssl rand -hex 32",
		src,
		re.MULTILINE,
	)
	assert m, "main.yml lazy-regen must include wing_edge_token with openssl rand -hex 32"


def test_wing_plist_exposes_edge_token_env():
	src = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
	assert "WING_EDGE_TOKEN" in src
	assert "{{ wing_edge_token" in src


def test_secrets_template_persists_wing_edge_token():
	src = (REPO / "templates/secrets.yml.j2").read_text()
	assert "wing_edge_token:" in src
