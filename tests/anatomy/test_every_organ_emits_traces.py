"""Each host organ must put a span emitter in its request path.

WHY THIS GATE EXISTS. Measured 2026-08-31: Tempo held 950 traces and every
single one was an AgentKit `agent.session`. The estate had a working collector
(Alloy on 4318), a working store (Tempo), and a Grafana datasource pointed at
it — and the three daemons that serve the estate's own control surface emitted
nothing at all, so `grafana-mcp` could not answer "why was that call slow" for
Wing, Bone or the cortex.

The failure mode this pins is a QUIET one, which is why prose could not hold
it. Nothing goes red when an organ stops tracing: the collector keeps
accepting, the datasource keeps resolving, the dashboards keep rendering, and
the only symptom is an absence — and absence is never success (CLAUDE.md).
The three emitters are also three separate hand-rolled files in three
languages, so one of them can be dropped in a refactor without the other two
noticing.

WHAT IT CHECKS. Not that a trace arrived — that would need a live Tempo and
would be a `--tags verify` job, not pytest's (division of labour, CLAUDE.md).
It checks the shape only: the emitter module exists, and the organ's request
entry point actually calls it. Both halves are needed — the Wing emitter
existed for months while nothing called it from a presenter.

THE CALL HALF READS CODE, NOT TEXT (2026-09-01). It used to be `call in body`,
a substring match over the whole file — which a commented-out `# otel.install
(app)` satisfies just as well as a live one, and a commented-out call is
precisely how this gets dropped in a refactor. Bone is parsed as an AST; cortex
and Wing have their comments stripped first. Same rule as the security queue's
detectors: read the artifact, never the prose about it.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: organ → (emitter module, request entry point, the call the entry point must make)
ORGANS = {
    "wing":   ("files/anatomy/wing/app/AgentKit/Telemetry/OtelExporter.php",
               "files/anatomy/wing/app/Presenters/BasePresenter.php",
               # The CONSTRUCTION, not the class name: `use App\AgentKit\
               # Telemetry\OtelExporter;` is an import and satisfies a bare
               # name match while exporting nothing.
               "new OtelExporter("),
    "bone":   ("files/anatomy/bone/otel.py",
               "files/anatomy/bone/main.py",
               "otel.install(app)"),
    "cortex": ("files/anatomy/cortex/server/otel.ts",
               "files/anatomy/cortex/server/index.ts",
               "traceRequests()"),
}


@pytest.mark.parametrize("organ", sorted(ORGANS))
def test_organ_has_a_span_emitter(organ: str) -> None:
    emitter, _, _ = ORGANS[organ]
    path = ROOT / emitter
    assert path.is_file(), f"{organ}: emitter {emitter} is gone — nothing can produce a span"
    body = path.read_text(encoding="utf-8")
    assert "/v1/traces" in body, (
        f"{organ}: {emitter} no longer posts to the OTLP traces endpoint")
    assert "service.name" in body, (
        f"{organ}: {emitter} sends no service.name — Tempo cannot attribute the span")


def _strip_comments(body: str) -> str:
    """Drop `//` and `/* */` comments. Crude — a `//` inside a string literal
    goes too — which is fine here: the only thing asked of the result is
    whether a call survives it, and no organ writes its own call site into a
    string."""
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return "\n".join(re.sub(r"//.*", "", line) for line in body.splitlines())


def _python_calls_it(source: str, dotted: str) -> bool:
    """True when `dotted` (e.g. `otel.install`) is CALLED, per the AST."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (f"{func.value.id}.{func.attr}"
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                else func.id if isinstance(func, ast.Name) else "")
        if name == dotted:
            return True
    return False


@pytest.mark.parametrize("organ", sorted(ORGANS))
def test_the_request_path_calls_it(organ: str) -> None:
    _, entry, call = ORGANS[organ]
    path = ROOT / entry
    assert path.is_file(), f"{organ}: request entry point {entry} is gone"
    body = path.read_text(encoding="utf-8")
    found = (_python_calls_it(body, "otel.install") if entry.endswith(".py")
             else call in _strip_comments(body))
    assert found, (
        f"{organ}: {entry} does not call `{call}` — the emitter exists but nothing "
        f"fires it, which looks identical to being instrumented until you query Tempo")
