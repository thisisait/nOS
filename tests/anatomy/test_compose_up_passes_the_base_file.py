"""A `compose up` without the stack's base file refuses the whole project.

WHAT HAPPENED, measured 2026-08-13 on the live estate.

`roles/pazny.mcp_gateway/tasks/post.yml` restarted the grafana sidecar with

    docker compose -p iiab $(find overrides -name '*.yml' ...) up -d mcp-grafana

— the overrides and nothing else. The networks are declared in
`iiab/docker-compose.yml`, so compose rejected the project outright:

    service "nodered" refers to undefined network iiab_net: invalid compose project

That restart is the ONLY step that delivers the Grafana service-account token.
Ordering makes it load-bearing: the stack-level `up` creates the container from
a freshly rendered override holding `placeholder-set-in-post`, and only THEN
does post.yml mint a token and sed it into the file. So the container kept the
placeholder — and `failed_when: false` on the task meant the refusal never
surfaced. Thirty tokens had accumulated on the `mcp-gateway` service account,
one per converge, none of which ever reached the process; Grafana answered the
toolset `401 Invalid API key`, and mcpo reported `healthy` throughout.

WHY A GATE AND NOT A NOTE. `up` is the one compose verb that needs the file
set — `exec`, `restart` and `stop` find containers by project label, which is
why the dozen other call sites in this repo are correct without it. The
mistake is therefore invisible by comparison with its neighbours, and its
symptom appears three layers away, in a container's environment.

SCOPE, measured rather than assumed: of the executed `up -d` sites in
`roles/`, `pazny.woodpecker` already passes the base file first (the canonical
form, copied from `tasks/stacks/stack-up.yml`), and `pazny.mariadb`'s is prose
inside an operator-facing error message, not a command. mcp_gateway was the
only offender — an isolated defect, not a class.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Found by the VERB, then read backwards to its `compose`. The first draft
#: matched forwards from `compose` across a bounded number of lines and found
#: nothing — both real invocations wrap over four or more continuation lines.
#: The positive control below is what caught that, which is the whole reason it
#: is here: a sweep that silently matches zero files is a gate that passes
#: because it looked nowhere.
UP_VERB = re.compile(r"\bup\s+-d\b")
#: `compose` as the COMMAND WORD. The second draft used `rfind("compose")` and
#: flagged the one correct call site in the repo, because the last `compose`
#: before the verb is the one inside `docker-compose.yml` — the window then
#: began after the very filename it was looking for. Excluding a preceding `-`
#: and a following `.` keeps the command and drops the filename.
COMPOSE_WORD = re.compile(r"(?<![-\w])compose(?![-\w.])")
#: How far back an invocation may reasonably reach. `>`-folded YAML scalars put
#: the flags on their own lines; measured 2026-08-13 the two real invocations
#: span 121 and 198 chars, so 800 leaves room for a longer one without reaching
#: the previous task.
LOOKBEHIND = 800

#: Prose gives itself away by its surroundings, not by its wording — an
#: indented block inside a `fail:`/`debug:` message is documentation telling an
#: operator what to type. Anything reached via `ansible.builtin.shell`/`command`
#: is a command.
EXECUTORS = ("ansible.builtin.shell", "ansible.builtin.command", "shell:", "command:")


def _task_files() -> list[pathlib.Path]:
    return sorted(
        p for p in (REPO / "roles").glob("pazny.*/tasks/*.yml") if p.is_file()
    )


def _is_executed(text: str, at: int) -> bool:
    """Is this `up` inside a shell/command block rather than a message?"""
    head = text[:at]
    last_exec = max((head.rfind(tok) for tok in EXECUTORS), default=-1)
    if last_exec < 0:
        return False
    # A `fail:`/`debug:`/`msg:` opened after the last executor means we have
    # left the command and are inside operator-facing prose.
    for marker in ("ansible.builtin.fail", "ansible.builtin.debug", "msg:"):
        if head.rfind(marker) > last_exec:
            return False
    return True


def _strip_comments(block: str) -> str:
    """Drop `#` lines before judging an invocation — defensive, not load-bearing.

    Measured: with it removed the mutation below is still caught, because the
    window starts at the `compose` command word and the explaining comment sits
    above the `shell:` key, out of reach. It stays because a comment written
    INSIDE a shell block that happened to name the base file would otherwise be
    read as evidence that the command passes it, and the whole point of this
    gate is that only what runs counts.

    (An earlier revision of this docstring claimed comment contamination WAS
    the bug that made draft three pass its mutation. It was not: the mutation
    string omitted the YAML line-continuation backslash, so nothing was ever
    mutated and the gate was never asked the question.)
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )


def _invocations(text: str):
    """Yield (offset, invocation-text) for every executed `compose … up -d`."""
    for match in UP_VERB.finditer(text):
        window = text[max(0, match.start() - LOOKBEHIND): match.start()]
        starts = [m.start() for m in COMPOSE_WORD.finditer(window)]
        if not starts:
            continue
        if not _is_executed(text, match.start()):
            continue
        yield match.start(), _strip_comments(window[starts[-1]:]) + match.group(0)


def test_every_executed_compose_up_passes_a_base_compose_file():
    offenders = []
    for path in _task_files():
        text = path.read_text(encoding="utf-8")
        for offset, invocation in _invocations(text):
            if "docker-compose.yml" not in invocation:
                line = text[:offset].count("\n") + 1
                offenders.append(f"  {path.relative_to(REPO)}:{line}")
    assert not offenders, (
        "a `docker compose … up -d` runs without the stack's base "
        "`docker-compose.yml`. The base file declares the networks, so compose "
        "refuses the entire project — and every such site in this repo sits "
        "behind `failed_when: false`, which is how the mcp-grafana token spent "
        "a month being minted, persisted, and never delivered:\n"
        + "\n".join(offenders)
    )


def test_the_sweep_sees_the_call_sites_it_is_meant_to_guard():
    """Positive control: if the regex stops matching, the gate above is vacuous."""
    found = 0
    for path in _task_files():
        found += sum(1 for _ in _invocations(path.read_text(encoding="utf-8")))
    assert found >= 2, (
        f"only {found} executed `compose up` site(s) matched; the pattern has "
        "stopped finding the commands it guards (there were 2 on 2026-08-13: "
        "pazny.mcp_gateway and pazny.woodpecker)."
    )
