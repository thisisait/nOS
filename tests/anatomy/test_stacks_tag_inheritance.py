"""Anatomy gate: stack-up + core-up compose flow tagged for --tags <svc>
inheritance (A17, 2026-05-20).

Pre-A17 bug: per-service role tags (e.g. `tags: ['woodpecker']`) trigger
the role render task — which writes a new compose override — but the
`docker compose up` task in stack-up.yml / core-up.yml had NO tags, so
the container kept running with stale env / image. Operators believed
`--tags <svc>` had no effect when in fact it half-worked.

Fix: every task in the compose-up flow (set_fact for _remaining_stacks,
override enumeration, `docker compose up`, async wait, fail-fast assert)
carries `tags: ['stacks', 'always']` (or `['core', 'always']` in
core-up.yml). The `always` tag makes the task run on every play, the
`stacks`/`core` tag lets operators target the family explicitly. Opt-out
via `--skip-tags stacks` or `--skip-tags core`.

This gate pins the tag set on every load-bearing task in both files.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _tagged_tasks(path: pathlib.Path) -> list[dict]:
	"""Return the parsed task list from a top-level Ansible task file."""
	return yaml.safe_load(path.read_text()) or []


# ── tasks/stacks/stack-up.yml ────────────────────────────────────────────


STACK_UP_REQUIRED_TASKS = (
	"[Stacks] Build list of remaining (non-core) active stacks",
	"[Stacks] Enumerate compose overrides per remaining stack",
	"[Stacks] Build stack name -> overrides list map",
	"[Stacks] Fire docker compose up --wait per stack (async, parallel)",
	"[Stacks] Wait for parallel stack-up jobs to finish",
	"[Stacks] Flatten async_status results (item = stack name)",
	"[Stacks] Dump failed-stack output (visibility for rc!=0)",
	"[Stacks] Assert all parallel stacks reached up --wait (fail-fast)",
)


def test_stack_up_compose_flow_carries_always_tag():
	tasks = _tagged_tasks(REPO / "tasks/stacks/stack-up.yml")
	by_name = {t.get("name", ""): t for t in tasks if isinstance(t, dict)}
	missing = []
	for name in STACK_UP_REQUIRED_TASKS:
		t = by_name.get(name)
		assert t is not None, f"task missing: {name}"
		tags = t.get("tags") or []
		if "always" not in tags or "stacks" not in tags:
			missing.append((name, tags))
	assert not missing, (
		"stack-up.yml tasks missing ['stacks', 'always'] tag set — "
		f"--tags <svc> won't trigger compose-up for these: {missing}"
	)


# ── tasks/stacks/core-up.yml ─────────────────────────────────────────────


CORE_UP_REQUIRED_TASKS = (
	"[Core] Enumerate infra compose overrides",
	"[Core] Enumerate observability compose overrides",
	"[Core] Re-enumerate infra compose overrides (after plugin loader)",
	"[Core] Re-enumerate observability compose overrides (after plugin loader)",
	"[Core] Start INFRA stack (docker compose up --wait)",
	"[Core] Infra stack result",
	"[Core] Start OBSERVABILITY stack (docker compose up --wait)",
	"[Core] Observability stack result",
)


def test_core_up_compose_flow_carries_always_tag():
	tasks = _tagged_tasks(REPO / "tasks/stacks/core-up.yml")
	by_name = {t.get("name", ""): t for t in tasks if isinstance(t, dict)}
	missing = []
	for name in CORE_UP_REQUIRED_TASKS:
		t = by_name.get(name)
		assert t is not None, f"task missing: {name}"
		tags = t.get("tags") or []
		if "always" not in tags or "core" not in tags:
			missing.append((name, tags))
	assert not missing, (
		"core-up.yml tasks missing ['core', 'always'] tag set — "
		f"--tags <svc> won't trigger compose-up for these: {missing}"
	)


# ── Operator-side documentation ──────────────────────────────────────────


def test_claude_md_documents_skip_tags_opt_out():
	"""CLAUDE.md must document that operators can use `--skip-tags stacks`
	or `--skip-tags core` to opt out of compose-up when they want only a
	render (e.g. for a syntax-check or a config-only review). Pinned here
	so the doctrine doesn't drift away from the implementation."""
	src = (REPO / "CLAUDE.md").read_text()
	# Either explicit mention of --skip-tags, OR a tagged-runs explanation
	# is acceptable; just need SOMETHING that points operators to the
	# opt-out path.
	assert (
		"--skip-tags stacks" in src
		or "--skip-tags core" in src
		or "A17" in src
	), (
		"CLAUDE.md doesn't reference the A17 tag-inheritance rule "
		"or --skip-tags opt-out — operators won't know how to "
		"disable the implicit compose-up"
	)
