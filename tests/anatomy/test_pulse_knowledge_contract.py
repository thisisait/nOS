"""Anatomy gate — the Pulse knowledge nodes must describe the Pulse that exists.

`docs/systems/pulse/SKILLS.md` and the `pulse` row in `state/manifest.yml` are
not prose: both are ingested into the cortex store (keap_docs_gen /
keap_selfmodel_gen) and answered to agents as fact. A wrong sentence there is
not a typo, it is a wrong answer with provenance attached.

Three claims are pinned here because all three were false, and each failure mode
is one an agent cannot detect at read time:

1. **Blast radius of the reconverge command.** Every task in
   `tasks/stacks/{core,stack}-up.yml` carries `always`, which no `--tags`
   selection can deselect. `--tags pulse` alone therefore recreates the whole
   estate before the first `pazny.pulse` task and blocks on the STRICT health
   wait — so on a host with one restart-looping container the play dies before
   the plist the card promised is re-rendered.
2. **Substitution of unset `NOS_*` vars.** `discover-pulse-catalog.py::_expand`
   substitutes every KNOWN token unconditionally, empty value included; the
   leave-it-literal guard was REMOVED as a bug in 2026-05-25. A card claiming
   the opposite turns "I never exported the var" into "the var is set to empty"
   and sends a reader diagnosing an empty bearer to the wrong place.
3. **Where liveness comes from.** The row deliberately carries no `port_var`,
   no `domain_var` and no http `health_check` — Pulse binds no socket, and
   inventing an endpoint would describe a surface that does not exist. That
   makes the launchd/systemd probe the row's ONLY liveness declaration, so the
   probe has to actually run on both supported platforms.

The premises (1) and (2) rest on are read from the play and the script here, not
restated — if the `always` tags or `_expand` ever change, this test says so
instead of silently blessing a card that has become right by accident.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

from module_utils import nos_state_lib as lib

REPO = pathlib.Path(__file__).resolve().parents[2]
SKILLS = REPO / "docs" / "systems" / "pulse" / "SKILLS.md"
CORE_UP = REPO / "tasks" / "stacks" / "core-up.yml"
STACK_UP = REPO / "tasks" / "stacks" / "stack-up.yml"
DISCOVER = REPO / "files" / "anatomy" / "scripts" / "discover-pulse-catalog.py"
MANIFEST = REPO / "state" / "manifest.yml"

COMPOSE_UP_TASKS = [
    (CORE_UP, "[Core] Start INFRA stack (docker compose up -d)"),
    (CORE_UP, "[Core] Start OBSERVABILITY stack (docker compose up -d)"),
    (STACK_UP, "[Stacks] Fire docker compose up -d per stack (async, parallel start)"),
]


def _card(name: str) -> str:
    """The body of one `## <name>` skill card, up to the next `## ` heading."""
    text = SKILLS.read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(name)}\s*$(.*?)(?=^## |\Z)", text,
                  re.MULTILINE | re.DOTALL)
    assert m, f"docs/systems/pulse/SKILLS.md has no '## {name}' card"
    return m.group(1)


def _task_tags(path: pathlib.Path, task_name: str) -> list[str]:
    """Tags of one named task — line-scanned, so Jinja in sibling values cannot
    break the read the way yaml.safe_load would."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith("- name:") and task_name in ln), None)
    assert start is not None, f"{path.name} has no task named {task_name!r}"
    for ln in lines[start + 1:]:
        if ln.startswith("- name:"):
            break
        m = re.match(r"\s*tags:\s*\[(?P<body>.*)\]\s*$", ln)
        if m:
            return re.findall(r"['\"]([^'\"]+)['\"]", m.group("body"))
    return []


# ── 1. reconverge-pulse: the estate-wide blast radius ─────────────────────────

def test_compose_up_really_is_tag_proof():
    """Premise: the compose-up flow runs whatever --tags asks for."""
    for path, task in COMPOSE_UP_TASKS:
        assert "always" in _task_tags(path, task), (
            f"{path.name}:{task!r} no longer carries the 'always' tag. The "
            f"reconverge card's --skip-tags advice is derived from it — re-read "
            f"the flow before relaxing this."
        )


def test_reconverge_card_skips_the_compose_up_flow():
    body = _card("reconverge-pulse")
    cmd = next((ln for ln in body.splitlines()
                if ln.strip().startswith("ansible-playbook")), "")
    assert cmd, "reconverge-pulse card has no ansible-playbook command"
    assert "--skip-tags" in cmd, (
        "reconverge-pulse documents a bare `--tags pulse`. Because the compose-up "
        "tasks carry 'always', that recreates infra + observability + all six "
        "wave-2 stacks BEFORE the first pazny.pulse task and blocks on the STRICT "
        "health wait; one unhealthy container and the plist is never re-rendered. "
        "Document `--tags pulse --skip-tags stacks,core`."
    )
    skipped = cmd.split("--skip-tags", 1)[1].split()[0]
    assert {"stacks", "core"} <= set(skipped.split(",")), (
        f"--skip-tags {skipped} does not cover both waves: 'core' skips "
        f"infra+observability, 'stacks' skips the six wave-2 stacks."
    )


def test_reconverge_card_says_why_the_skip_is_there():
    """A bare flag invites removal. The card must carry the reason."""
    body = _card("reconverge-pulse")
    assert "always" in body, (
        "reconverge-pulse must name the `always` tag as the reason for "
        "--skip-tags, or the next editor will drop the flag as noise."
    )


def test_pulse_role_tasks_survive_the_skip():
    """The advice only works because pazny.pulse is not itself tagged core/stacks."""
    text = (REPO / "main.yml").read_text(encoding="utf-8")
    m = re.search(r"name: pazny\.pulse\b.*?tags:\s*\[(?P<body>[^\]]*)\]",
                  text, re.DOTALL)
    assert m, "main.yml no longer imports pazny.pulse with an explicit tags list"
    tags = set(re.findall(r"['\"]([^'\"]+)['\"]", m.group("body")))
    assert "pulse" in tags
    assert not (tags & {"core", "stacks", "always"}), (
        f"pazny.pulse now carries {tags & {'core', 'stacks', 'always'}} — "
        f"`--skip-tags stacks,core` would skip the role itself. Fix the card."
    )


# ── 2. preview-pulse-catalog: what an unset NOS_* var does ────────────────────

def _discover():
    spec = importlib.util.spec_from_file_location("discover_pulse_catalog", DISCOVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_expand_blanks_a_known_token_whose_env_is_unset():
    """Premise: substitution is unconditional — empty value included."""
    mod = _discover()
    subs = {"{{ wing_api_token }}": ""}
    assert mod._expand("--token={{ wing_api_token }}", subs) == "--token="
    # …and a token the table does not know stays literal. That, not "unset",
    # is the only case where a placeholder survives.
    assert mod._expand("{{ not_in_table }}", subs) == "{{ not_in_table }}"


def test_preview_card_does_not_claim_unset_leaves_the_token():
    body = _card("preview-pulse-catalog")
    assert "leave the token in place" not in body, (
        "preview-pulse-catalog states the inverse of _expand: an unset NOS_* var "
        "substitutes the EMPTY STRING (the leave-it-literal guard was removed as "
        "a bug on 2026-05-25). A reader told otherwise misreads `--token=` as a "
        "value rather than as an unexported var."
    )


def test_preview_card_states_the_real_rule():
    body = _card("preview-pulse-catalog").lower()
    assert "empty string" in body, (
        "preview-pulse-catalog must say that an unset NOS_* var substitutes the "
        "empty string — the whole reason a bare preview shows blanks."
    )


# ── 3. Liveness: no socket, so the unit probe must actually run ───────────────

def test_pulse_row_declares_no_socket_surface():
    """The omission is correct and deliberate — pin it so nobody 'completes' it."""
    text = MANIFEST.read_text(encoding="utf-8")
    m = re.search(r"^  - id: pulse\s*$(.*?)(?=^  - id: )", text,
                  re.MULTILINE | re.DOTALL)
    assert m, "state/manifest.yml has no `pulse` service row"
    row = m.group(1)
    body = "\n".join(ln for ln in row.splitlines() if not ln.strip().startswith("#"))
    for field in ("port_var:", "domain_var:", "health_check:"):
        assert field not in body, (
            f"the pulse row grew a {field} — Pulse binds no socket; it CALLS Wing "
            f"on loopback. An http health_check here would describe a surface "
            f"that does not exist."
        )
    assert "version_source: launchd" in body


def test_launchd_version_source_probes_the_linux_unit_too():
    """`version_source: launchd` is a host-daemon declaration, not a macOS one.

    pazny.pulse installs `<label>.service` as a systemd --user unit on the Linux
    port. Without a systemd probe the row reports healthy/installed = null for a
    daemon that is loaded and ticking — indistinguishable from never installed,
    on a row whose only liveness declaration this is.
    """
    svc = {"id": "pulse", "version_source": "launchd",
           "launchd_label": "eu.thisisait.nos.pulse", "stack": None}

    calls: list[list[str]] = []

    def fake_which(cmd):
        return None if cmd == "launchctl" else f"/usr/bin/{cmd}"

    def fake_run(cmd, timeout=10):
        calls.append(cmd)
        assert cmd[:2] == ["systemctl", "--user"]
        assert "eu.thisisait.nos.pulse.service" in cmd
        return (0, "loaded\n", "")

    orig_which, orig_run = lib._which, lib._run
    try:
        lib._which, lib._run = fake_which, fake_run
        entry = lib.introspect_service(svc)
    finally:
        lib._which, lib._run = orig_which, orig_run

    assert calls, "no systemd probe ran on a launchctl-less host"
    assert entry["healthy"] is True
    assert entry["installed"] == "loaded"


def test_systemd_probe_is_an_honest_unknown_when_it_cannot_ask():
    """No systemctl (macOS) or an unreachable user bus must stay None, never False."""
    orig_which, orig_run = lib._which, lib._run
    try:
        lib._which = lambda cmd: None
        assert lib.introspect_systemd_user_loaded("eu.thisisait.nos.pulse") is None

        lib._which = lambda cmd: f"/usr/bin/{cmd}"
        lib._run = lambda cmd, timeout=10: (1, "", "Failed to connect to bus")
        assert lib.introspect_systemd_user_loaded("eu.thisisait.nos.pulse") is None
    finally:
        lib._which, lib._run = orig_which, orig_run


def test_check_pulse_daemon_card_names_the_probe_that_runs_on_each_platform():
    # The claim under test is the ATTRIBUTION prose, not the two-line command
    # block above it — the old card printed both commands and then credited
    # `nos_state` to a launchd-only signal.
    body = next(ln for ln in _card("check-pulse-daemon").splitlines()
                if ln.startswith("**Output:**"))
    assert "launchctl" in body and "systemctl" in body, (
        "check-pulse-daemon attributes nos_state's `healthy` to a probe; it must "
        "name both halves, or the Linux reader is told a launchd command speaks "
        "for their host."
    )
