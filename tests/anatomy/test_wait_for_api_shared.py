"""Anatomy gate: the canonical "Wait for API" loop is a SHARED include, not
copy-pasted per role (tech-debt: copy-paste-wait-for-api).

History: ~8 service post.yml files each carried an independent inline
`ansible.builtin.uri` GET-until-ready block. They drifted apart — retries
(12/15/20), status codes ([200] vs [200,302] vs [200,303]) and, worst, the
2026-05-08 `failed_when: false` removal (a ~25-min iiab cascade masked by the
silent absorb) reached only 4 of the roles that needed it.

Fix: roles/pazny._common_tasks/tasks/wait_for_api.yml is the single
parameter-driven implementation (url, status_codes, retries, delay, headers,
hard-fail) + a templated set_fact that aliases the result back under each
caller's own register var so every downstream `<name>.status` gate keeps
working verbatim. Every converted role delegates via include_role.

This gate pins:
  1. the shared helper exists and carries the load-bearing pieces;
  2. each converted role's "Wait for API" delegates to the shared role with
     the right register-alias + hard-fail intent;
  3. no service post.yml regresses to an inline copy-pasted `uri` wait block.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

SHARED = REPO / "roles" / "pazny._common_tasks" / "tasks" / "wait_for_api.yml"


# ── per-role contract: (post.yml path, register-alias, status codes, hard-fail) ──
# These are the behavioural facts the inline blocks used to encode; the include
# call must reproduce them exactly, else a copy-paste drift has re-opened.
ROLE_CONTRACT = {
	"pazny.n8n": {"register": "_n8n_ready", "codes": [200], "hard_fail": False},
	"pazny.metabase": {"register": "_mb_ready", "codes": [200], "hard_fail": False},
	"pazny.calibre_web": {"register": "_cw_ready", "codes": [200, 302], "hard_fail": False},
	"pazny.homeassistant": {"register": "_ha_ready", "codes": [200, 302], "hard_fail": True},
	"pazny.jellyfin": {"register": "_jf_ready", "codes": [200], "hard_fail": True},
	"pazny.open_webui": {"register": "_owui_ready", "codes": [200], "hard_fail": True},
	"pazny.puter": {"register": "_puter_ready", "codes": [200], "hard_fail": True},
	"pazny.portainer": {"register": "_portainer_ready", "codes": [200, 303], "hard_fail": False},
}


def _tasks(path: pathlib.Path) -> list[dict]:
	return yaml.safe_load(path.read_text()) or []


def _wait_blocks(path: pathlib.Path) -> list[dict]:
	"""All top-level tasks whose name contains 'Wait for API'."""
	return [
		t
		for t in _tasks(path)
		if isinstance(t, dict) and "Wait for API" in (t.get("name") or "")
	]


# ── 1. shared helper exists + carries the load-bearing pieces ────────────────


def test_shared_helper_exists():
	assert SHARED.is_file(), f"missing shared wait helper: {SHARED}"


def test_shared_helper_is_a_uri_loop_with_aliasing():
	tasks = _tasks(SHARED)
	assert tasks, "shared helper has no tasks"
	uri = next((t for t in tasks if "ansible.builtin.uri" in t), None)
	assert uri is not None, "shared helper must perform an ansible.builtin.uri GET"

	# retry-loop knobs are parameter-driven (templated), not hard-coded
	for key in ("until", "retries", "delay"):
		assert key in uri, f"shared uri task missing retry knob: {key}"
	assert "{{ wait_retries" in str(uri["retries"]), "retries must be parameterised"
	assert "{{ wait_delay" in str(uri["delay"]), "delay must be parameterised"

	# hard-fail intent flows through a wait_hard_fail-gated failed_when
	assert "wait_hard_fail" in str(uri.get("failed_when", "")), (
		"shared uri task must honour wait_hard_fail in failed_when"
	)

	# register: can't be templated, so the result is aliased into the caller's
	# var name via a templated-key set_fact — this is what keeps every
	# downstream `<name>.status` read working without edits.
	sf = next((t for t in tasks if "ansible.builtin.set_fact" in t), None)
	assert sf is not None, "shared helper must alias the result via set_fact"
	keys = list((sf["ansible.builtin.set_fact"] or {}).keys())
	assert any("wait_register_as" in str(k) for k in keys), (
		"set_fact must use the templated {{ wait_register_as }} key so the "
		f"caller's own register var is what gets populated; got keys {keys}"
	)


# ── 2. each converted role delegates with the right contract ─────────────────


def test_each_role_delegates_to_shared_helper():
	for role, want in ROLE_CONTRACT.items():
		post = REPO / "roles" / role / "tasks" / "post.yml"
		blocks = _wait_blocks(post)
		assert blocks, f"{role}: no 'Wait for API' task found"
		# the PRIMARY wait must delegate (portainer also has a re-wait; both
		# must delegate, but we assert the one that owns the role's register).
		primary = None
		for b in blocks:
			inc = b.get("ansible.builtin.include_role") or {}
			v = b.get("vars") or {}
			if v.get("wait_register_as") == want["register"]:
				primary = (b, inc, v)
				break
		assert primary is not None, (
			f"{role}: no Wait-for-API include delegating to the shared helper "
			f"with wait_register_as={want['register']}"
		)
		b, inc, v = primary
		assert inc.get("name") == "pazny._common_tasks", (
			f"{role}: Wait for API must include_role pazny._common_tasks, "
			f"got {inc.get('name')!r}"
		)
		assert inc.get("tasks_from") == "wait_for_api.yml", (
			f"{role}: must include tasks_from wait_for_api.yml"
		)
		assert v.get("wait_status_codes") == want["codes"], (
			f"{role}: status codes drifted — want {want['codes']}, "
			f"got {v.get('wait_status_codes')}"
		)
		assert bool(v.get("wait_hard_fail")) == want["hard_fail"], (
			f"{role}: wait_hard_fail drifted — the 2026-05-08 fail-loud fix "
			f"must stay {want['hard_fail']} (got {v.get('wait_hard_fail')})"
		)


def test_every_wait_block_in_converted_roles_is_an_include():
	"""Anti-regression: not a single 'Wait for API' task in a converted role
	may be an inline copy-pasted `uri` block again."""
	offenders = []
	for role in ROLE_CONTRACT:
		post = REPO / "roles" / role / "tasks" / "post.yml"
		for b in _wait_blocks(post):
			if "ansible.builtin.uri" in b:
				offenders.append((role, b.get("name")))
			elif "ansible.builtin.include_role" not in b:
				offenders.append((role, b.get("name")))
	assert not offenders, (
		"copy-pasted inline 'Wait for API' uri block(s) re-introduced "
		f"instead of delegating to pazny._common_tasks: {offenders}"
	)
