"""Batch 4 break-glass gate — the offline Authentik recovery-key INPUT
(`authentik_recovery_break_glass_secret`) persists stably to ~/.nos/secrets.yml
across re-runs, and is NEVER a blueprint seed.

docs/sso-autologin-plan.md §"Bezpečnost: break-glass + lockout" (layer 3):

  > `authentik_core.recoverytoken` model NEEXISTUJE v Authentik blueprint
  > schématu … Recovery tokens lze vytvořit VÝHRADNĚ CLI příkazem
  > `docker compose run --rm server create_recovery_key <username>`.
  > Co nOS udělá: vygeneruje `authentik_recovery_key` jako náhodné bajty na
  > first blank-run, uloží do `~/.nos/secrets.yml` … a dokumentuje CLI postup.
  > Gate: test_recovery_key_persists_across_reruns (stabilita klíče napříč
  > re-runy). Žádný test ověřující `recoverytoken` v blueprintu.

What this gate pins (all static + a functional re-run simulation — no live
playbook, no Authentik, no Docker):

  1. The break-glass wiring task exists, is gated behind `install_authentik`,
     and persists the secret to ~/.nos/secrets.yml via a NAME-keyed
     `lineinfile` (so a re-run rewrites the same line in place — never a
     duplicate key, never drift).
  2. The secret is generate-IF-ABSENT (a value already present passes the
     guard untouched) → stable across re-runs.
  3. The whole thing is BLUEPRINT-FREE: no `recoverytoken`, no blueprint seed
     (that would be unsatisfiable per the plan).
  4. main.yml imports the task AFTER the secrets.yml.j2 render so the template
     re-render cannot clobber the appended key.
  5. Functional: simulate two consecutive runs over a temp secrets.yml and
     assert the persisted secret is byte-identical the second time.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = REPO / "tasks" / "authentik-recovery-key.yml"
MAIN = REPO / "main.yml"
SECRETS_TMPL = REPO / "templates" / "secrets.yml.j2"

VAR = "authentik_recovery_break_glass_secret"


def _task_text() -> str:
    assert TASK.exists(), f"break-glass wiring task missing: {TASK}"
    return TASK.read_text()


def _main_text() -> str:
    return MAIN.read_text()


def test_break_glass_task_is_valid_yaml_and_present():
    text = _task_text()
    doc = yaml.safe_load(text)
    assert isinstance(doc, list) and doc, "task file must be a non-empty task list"
    # The persist step must reference the var and target ~/.nos/secrets.yml.
    assert VAR in text, f"{VAR} not referenced in {TASK}"
    assert ".nos/secrets.yml" in text, "persist target ~/.nos/secrets.yml missing"


def test_persist_uses_name_keyed_lineinfile():
    """A NAME-keyed lineinfile guarantees in-place rewrite (no dup key) →
    stability across re-runs. We assert the regexp anchors on the var name."""
    text = _task_text()
    doc = yaml.safe_load(text)
    persist = [
        t for t in doc
        if isinstance(t, dict) and "ansible.builtin.lineinfile" in t
    ]
    assert persist, "expected an ansible.builtin.lineinfile persist task"
    li = persist[0]["ansible.builtin.lineinfile"]
    assert li.get("path", "").endswith(".nos/secrets.yml"), \
        "lineinfile must target ~/.nos/secrets.yml"
    regexp = li.get("regexp", "")
    assert VAR in regexp and regexp.startswith("^"), \
        f"lineinfile.regexp must anchor on `^{VAR}:` for idempotent rewrite, got {regexp!r}"
    line = li.get("line", "")
    assert line.startswith(f"{VAR}:"), \
        f"lineinfile.line must set `{VAR}:`, got {line!r}"


def test_secret_is_generate_if_absent():
    """The set_fact guard must regenerate ONLY when the value is a placeholder
    or too short — a value loaded from secrets.yml passes through untouched."""
    text = _task_text()
    doc = yaml.safe_load(text)
    setfacts = [
        t for t in doc
        if isinstance(t, dict) and "ansible.builtin.set_fact" in t
    ]
    assert setfacts, "expected a generate-if-absent set_fact"
    expr = setfacts[0]["ansible.builtin.set_fact"][VAR]
    # The else-branch must re-emit the existing value (idempotent reuse).
    assert f"{{{{ {VAR} }}}}" in expr or f"{VAR} }}}}" in expr, \
        "guard must reuse the existing value in its else-branch (stable re-run)"
    # The if-branch must be a fresh random generator, not a prefix-derived one.
    assert "openssl rand" in expr, "fresh value must be high-entropy openssl-rand"
    assert "_pw_" in expr, "guard must treat the prefix-derived `_pw_` form as a placeholder"


def _task_code_only() -> str:
    """The task text with `#`-comment lines stripped — the executable surface.

    The header legitimately *mentions* `recoverytoken`/blueprint to document
    why they are NOT used; only the executable steps must be clean of them.
    """
    out = []
    for ln in _task_text().splitlines():
        if ln.lstrip().startswith("#"):
            continue
        out.append(ln)
    return "\n".join(out).lower()


def test_no_blueprint_recoverytoken_in_executable_surface():
    """The plan: a `recoverytoken` blueprint seed is UNSATISFIABLE. The
    executable steps must NOT reference it, and must NOT touch a blueprint."""
    code = _task_code_only()
    assert "recoverytoken" not in code, \
        "executable steps must NOT seed authentik_core.recoverytoken (not in blueprint schema)"
    assert "blueprint" not in code, \
        "executable steps must NOT write a blueprint — recovery keys are CLI-only"
    # And nothing in the task may invoke the CLI / a container itself; this is
    # pure secret persistence (the operator runs the CLI manually).
    for forbidden in ("docker compose run", "create_recovery_key", "community.docker"):
        assert forbidden not in code, \
            f"task must be inert secret persistence — it must NOT run `{forbidden}`"


def test_main_gates_and_orders_the_import():
    """main.yml imports the task gated behind install_authentik AND after the
    secrets.yml.j2 render (else the template clobbers the appended key)."""
    text = _main_text()
    assert "tasks/authentik-recovery-key.yml" in text, \
        "main.yml must import tasks/authentik-recovery-key.yml"

    import_idx = text.index("tasks/authentik-recovery-key.yml")
    tmpl_idx = text.index("src: \"secrets.yml.j2\"")
    assert import_idx > tmpl_idx, \
        "the recovery-key import must come AFTER the secrets.yml.j2 render"

    # Confirm the import is gated behind install_authentik (within a small
    # window after the import line).
    window = text[import_idx:import_idx + 400]
    assert re.search(r"when:\s*install_authentik", window), \
        "the recovery-key import must be gated behind install_authentik"


def test_main_secrets_template_does_not_carry_the_key():
    """The break-glass key is appended by lineinfile, NOT by the main template
    (we must not edit it). If it ever lands in the template too, the two write
    paths would race — this gate keeps the contract honest."""
    text = SECRETS_TMPL.read_text()
    assert VAR not in text, (
        f"{VAR} must NOT be in secrets.yml.j2 — it is owned by the lineinfile "
        "persist in tasks/authentik-recovery-key.yml"
    )


# --- Functional: simulate two consecutive runs and assert stability ---------

_PW = re.compile(r"^[0-9a-f]{64}$")


def _simulate_run(existing: str | None) -> str:
    """Mirror the task's generate-if-absent + persist logic in Python.

    `existing` is the value loaded from ~/.nos/secrets.yml at the start of the
    run (None on first run). Returns the value persisted at the end of the run.
    """
    import secrets as pysecrets

    val = existing or ""
    # set_fact guard: regenerate only if placeholder ('_pw_') or < 32 chars.
    if "_pw_" in val or len(val) < 32:
        val = pysecrets.token_hex(32)  # mirrors `openssl rand -hex 32`
    return val


def test_secret_is_stable_across_reruns(tmp_path):
    secrets_file = tmp_path / "secrets.yml"

    # ── Run 1: no persisted value yet → generate + persist ──
    first = _simulate_run(existing=None)
    assert _PW.match(first), "first-run value must be 64 hex chars (openssl rand -hex 32)"
    # lineinfile append (name-keyed): write the key.
    secrets_file.write_text(f'{VAR}: "{first}"\n')

    # ── Run 2: early include_vars loads the persisted value → guard reuses it ──
    loaded = yaml.safe_load(secrets_file.read_text())[VAR]
    second = _simulate_run(existing=loaded)
    assert second == first, "secret must be byte-identical across re-runs (idempotent reuse)"

    # lineinfile is name-keyed → the file still holds exactly one key, same value.
    after = yaml.safe_load(secrets_file.read_text())
    assert after[VAR] == first
    assert list(after.keys()).count(VAR) == 1, "no duplicate keys across re-runs"


def test_prefix_derived_placeholder_is_replaced_then_stable(tmp_path):
    """A first-enable run may inherit a `_pw_`-style placeholder; it must be
    replaced with real entropy ONCE, then stay stable."""
    placeholder = "changeme_pw_authentik_recovery"
    run1 = _simulate_run(existing=placeholder)
    assert run1 != placeholder and _PW.match(run1), \
        "placeholder must be replaced with high-entropy random on first enable"
    run2 = _simulate_run(existing=run1)
    assert run2 == run1, "value must be stable on the following run"
