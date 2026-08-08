"""Anatomy gate — HMAC secrets are auto-generated high-entropy
(SEC-3, 2026-05-23).

Pre-SEC-3, bone_secret + wing_events_hmac_secret + nos_deploy_hmac_secret
defaulted to `{{ global_password_prefix }}_pw_<svc>`. With the default
"changeme" prefix, this is `changeme_pw_bone` — 15 chars, ~50 bits
real entropy (operator's choice of prefix is in the practical
attacker dictionary). Any HMAC-validating endpoint (Bone /api/v1/events,
Wing deploy-trigger) becomes brute-forceable.

Fix: main.yml's lazy-regen block now replaces prefix-derived values
with `openssl rand -hex 32` (256-bit) on first run. Values persist
to ~/.nos/secrets.yml; subsequent runs reuse them. Operator-set
overrides in credentials.yml still win (length-and-shape check, not
absolute replacement).

This gate pins:
  * bone_secret, nos_deploy_hmac_secret, wing_events_hmac_secret all
    appear in the lazy-regen block.
  * Each uses `openssl rand -hex 32` (or stronger).
  * Each has the `_pw_` regen-trigger pattern (catches prefix-derived
    defaults) AND a length floor.
  * ~/.nos/secrets.yml template persists all three.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
SECRETS_TPL = REPO / "templates/secrets.yml.j2"


HMAC_VARS = ["bone_secret", "nos_deploy_hmac_secret", "wing_events_hmac_secret"]


def test_lazy_regen_covers_all_hmac_secrets():
	src = MAIN.read_text()
	# Locate the lazy-regen set_fact block.
	idx = src.find('"Lazy-regenerate placeholder APP_KEYs / tokens')
	assert idx > 0, "lazy-regen set_fact block missing"
	# bone_secret + nos_deploy_hmac_secret must be openssl-rand-generated
	# directly. wing_events_hmac_secret is a sibling set_fact that mirrors
	# bone_secret (both sides of the same symmetric channel share the key);
	# accept that as "openssl rand" indirectly.
	for var in ("bone_secret", "nos_deploy_hmac_secret"):
		pat = re.compile(rf"^\s*{re.escape(var)}:\s*.*openssl rand", re.MULTILINE)
		assert pat.search(src, idx), \
			f"{var} must have an openssl-rand regen entry after the lazy-regen block start"
	# wing_events_hmac_secret either openssl-rand or mirrors bone_secret.
	#
	# READ THE TASK, NOT THE LINE (2026-08-08). This was a single-line regex
	# requiring `{{ bone_secret }}` on the same physical line as the key. That
	# held only while the assignment was a one-line `{% if %}` ternary; when the
	# reconciler grew a fourth condition — adopt the live key when the current
	# one is on the retired ring, see
	# test_a_rotated_secret_leaves_no_verifier_behind.py — it became a YAML block
	# scalar and this gate went red on a change that STRENGTHENED it.
	#
	# The assertion is unchanged: the value must still resolve to an
	# openssl-rand mint or to bone_secret. Only the scope moved, from one line to
	# the task, which is the smallest change that stops the gate mistaking
	# formatting for meaning. Note this is NOT a relaxation to fit an edit — a
	# reconciler that mirrored neither would still fail.
	wing_idx = src.find("wing_events_hmac_secret:", idx)
	assert wing_idx > 0, \
		"no wing_events_hmac_secret assignment after the lazy-regen block start"
	# The task ends at the next task header; anything after that belongs to
	# someone else and must not be allowed to satisfy this.
	wing_end = src.find("\n    - name:", wing_idx)
	wing_task = src[wing_idx : wing_end if wing_end != -1 else len(src)]
	assert re.search(r"openssl rand|\{\{\s*bone_secret\s*\}\}", wing_task), \
		"wing_events_hmac_secret must either openssl-rand-regen or mirror bone_secret"


def test_hmac_regen_triggers_on_prefix_derived_defaults():
	"""The regen ternary MUST fire when the value still matches the
	prefix-derived shape `*_pw_*` OR is shorter than 32 chars. Without
	this, an operator running upgrade-from-old would keep the weak
	prefix-derived secret silently."""
	src = MAIN.read_text()
	for var in ("bone_secret", "nos_deploy_hmac_secret"):
		# Each line of form `<var>: "{% if '_pw_' in ... or ... | length < 32 %}{{ openssl ... }}...`
		m = re.search(rf"{var}:\s*\"\{{%[^\"]+openssl rand -hex 32[^\"]+\}}\"", src)
		assert m, f"{var} lazy-regen line not found"
		line = m.group(0)
		assert "_pw_" in line, f"{var} regen must trigger on `_pw_` substring"
		assert "32" in line, f"{var} regen must use -hex 32 (256-bit secret)"


def test_secrets_template_persists_hmac_values():
	"""~/.nos/secrets.yml must round-trip the regen'd values so future
	playbook runs reuse them (else every run rotates the HMAC and
	breaks live Bone/Wing channel mid-flight)."""
	src = SECRETS_TPL.read_text()
	for var in HMAC_VARS:
		assert f"{var}:" in src, f"secrets.yml.j2 must persist {var}"


def test_default_credentials_still_carries_legacy_template():
	"""Backwards-compat: default.config.yml + default.credentials.yml
	keep the prefix-derived template (so fresh installs and ad-hoc
	`ansible-playbook --tags X` runs that bypass main.yml's lazy-regen
	still have a value for the var). The lazy-regen replaces it on
	first execution of main.yml."""
	src = (REPO / "default.config.yml").read_text()
	# The prefix-derived template must still be the default (it's the
	# pre-regen state).
	assert 'bone_secret: "{{ global_password_prefix }}_pw_bone"' in src
