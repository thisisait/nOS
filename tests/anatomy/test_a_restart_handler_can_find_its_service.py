"""A restart against the base compose file finds nothing, quietly.

WHAT HAPPENED, 2026-08-08, on the converge that first shipped ntfy auth.

    $ docker compose -f ~/stacks/iiab/docker-compose.yml -p iiab restart ntfy
    no such service: ntfy

Stack base files declare `services: {}` — every real service definition arrives
as an override that the orchestrator passes with its own `-f` flag. Naming the
base file alone therefore hides every service in the project. `pazny.ntfy`'s
`Restart ntfy` handler did exactly that, under `failed_when: false`, so it had
never restarted anything since the role was written. The config it was supposed
to activate simply never took effect.

That mattered the day the role started rendering a config change that MUST be
read to work: ntfy went on running with auth unconfigured while the play
believed it had reloaded.

THE GENERALISATION THAT IS WRONG, recorded because it was briefly acted on:
`docker compose -p <project> exec -T <service>` is FINE — measured rc=0 — since
compose resolves a running container from the project label when no `-f` is
given. Seven calls in `pazny.calibre_web` and the rest of `pazny.ntfy` depend on
that and are correct. The defect is naming a base compose file with `-f`, not
the compose CLI. A gate that banned `compose exec` would have rewritten working
code for a reason that does not exist.

WHAT THIS PINS: a restart/exec that names a stack BASE file explicitly. Those
are the calls that cannot see a service.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
ROLES = REPO / "roles"

#: `-f …/docker-compose.yml` — the base file the orchestrator overlays overrides
#: onto. Matching the literal filename keeps this narrow: a role naming a
#: RENDERED override with -f is doing something else and is not covered.
BASE_F = re.compile(r"-f\s+[\"']?[^\"'\s]*docker-compose\.yml[\"']?[^\n]*\b(restart|exec)\b")


def command_strings(node) -> list[str]:
    """Every string VALUE in a parsed YAML document.

    Parsed, not grepped. The first version of this gate scanned raw text and
    failed on the comment block in `pazny.ntfy/handlers/main.yml` that QUOTES
    the broken command in order to explain it — the fifth time in one day that a
    gate on this feature punished its own documentation. A YAML parser drops
    comments by definition, so the question "is this a comment?" stops being
    something the gate has to be clever about.
    """
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in command_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in command_strings(v)]
    return []


def yaml_sources() -> list[Path]:
    return sorted(p for p in ROLES.rglob("*.yml"))


def test_no_compose_call_names_a_base_file_to_reach_a_service():
    offenders = []
    for path in yaml_sources():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue  # not our business; the yamllint gate owns malformed files
        for value in command_strings(doc):
            m = BASE_F.search(value)
            if m:
                offenders.append(f"{path.relative_to(REPO)}  {m.group(0).strip()[:80]}")
    assert not offenders, (
        "compose call(s) naming a stack BASE file while trying to reach a "
        "service:\n  " + "\n  ".join(offenders)
        + "\n\nThe base file declares `services: {}` — every definition is an "
        "override the orchestrator adds with its own -f. This answers "
        "`no such service`, and under failed_when:false it answers it silently. "
        "Use the project form (`compose -p <proj> exec -T <svc>`) or the "
        "container id from a label filter."
    )


def test_the_ntfy_handler_is_not_silenced():
    """A restart that cannot happen must not report success.

    `failed_when: false` on this handler is what turned a broken command into
    months of nothing. The handler may still tolerate an absent container — that
    is a real, benign state — but it must not swallow a failure to restart one
    that exists.
    """
    src = (ROLES / "pazny.ntfy/handlers/main.yml").read_text(encoding="utf-8")
    handler = src[src.find("- name: Restart ntfy") :]
    assert "failed_when: false" not in handler, (
        "the ntfy restart handler silences its own failure again. It spent "
        "months answering `no such service: ntfy` into a void because of "
        "exactly this line."
    )


def test_the_config_is_probed_before_users_are_created():
    """The handler flushes at end of play; post.yml runs long before that.

    A config rendered during the role is unread by the container when post.yml
    executes, and Docker's single-file bind mount can additionally serve a stale
    inode after `template` renames over the target — measured the same day: host
    726 bytes, container 689, truncated mid-value, every ntfy CLI call answering
    `yaml: line 22: found unexpected end of stream`.

    So post.yml must ASK the container whether its config parses rather than
    assume the render reached it.
    """
    src = (ROLES / "pazny.ntfy/tasks/post.yml").read_text(encoding="utf-8")
    probe = src.find("Probe whether the running config parses")
    create = src.find("Create/reconverge users")
    assert probe != -1, (
        "post.yml no longer probes the running config before provisioning "
        "users. The first converge that shipped auth failed exactly here, with "
        "the reason hidden by no_log."
    )
    assert probe < create, (
        "the config probe runs AFTER user creation, so the users are still "
        "created against whatever config the container happened to boot with."
    )


def test_the_password_carrying_task_is_not_the_verdict():
    """`no_log` and `failed_when` must not meet on the same task.

    The loop that creates users carries passwords, so `no_log: true` is
    mandatory. That makes it the WORST possible task to fail the play: the
    operator gets `censored due to no_log` and nothing else, which is precisely
    what the failed converge produced. Its exit is not the verdict; the
    secret-free VERIFY read is.
    """
    src = (ROLES / "pazny.ntfy/tasks/post.yml").read_text(encoding="utf-8")
    start = src.find("Create/reconverge users")
    end = src.find("- name:", start + 10)
    task = src[start:end]
    assert "no_log: true" in task, "the user-creation loop no longer hides its passwords"
    assert "failed_when: false" in task, (
        "the password-carrying task can fail the play again. Its failure is "
        "censored, so it can only ever say 'something went wrong'. Let the "
        "VERIFY step — which carries no secret — be the one that judges."
    )
