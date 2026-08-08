"""A tool that fatals on load passes every grep ever written about it.

WHAT HAPPENED, 2026-08-08. `AskOperatorTool` shipped with `schema(): ToolSchema`
and no `use App\\AgentKit\\LLMClient\\ToolSchema;`. Inside the
`App\\AgentKit\\Tools` namespace the unqualified name resolves to
`App\\AgentKit\\Tools\\ToolSchema`, which does not exist. Every other tool in
that directory carries the import; this one did not.

`php -l` passes — the SYNTAX is fine. The class simply cannot load:

    PHP Fatal error: Could not check compatibility between
    App\\AgentKit\\Tools\\AskOperatorTool::schema(): App\\AgentKit\\Tools\\ToolSchema
    and App\\AgentKit\\Tools\\ToolInterface::schema(): App\\AgentKit\\LLMClient\\ToolSchema,
    because class App\\AgentKit\\Tools\\ToolSchema is not available

The tool was registered in `common.neon` both as a service and in the
`ToolRegistry` factory setup, so the registry — assembled once per Wing process
and consulted by every agent session — would have fataled on the next converge.

THE REAL LESSON IS ABOUT THE TEST, NOT THE IMPORT. The tool's dedicated gate,
`test_an_agent_cannot_answer_itself.py`, is eight tests that `read_text()` the
file and run regexes over the string. All eight were green against a class that
cannot be instantiated. The estate's marquee security property — an agent must
not be able to approve itself — was asserted about a file that does not run.

An adversarial reviewer found it in under twelve minutes. Eight green tests did
not, and could not.

So this file executes PHP. It requires each registered tool the way the runtime
would and asserts the class materialises. No composer needed: the four base
files the interface depends on are required by hand, which is exactly enough to
provoke the covariance check that catches this class of defect.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING_APP = REPO / "files/anatomy/wing/app"
NEON = WING_APP / "config/common.neon"
TOOLS_DIR = WING_APP / "AgentKit/Tools"

#: Loaded first so the interface's return type resolves. Order matters.
PRELUDE = [
    "AgentKit/LLMClient/ToolSchema.php",
    "AgentKit/Tools/ToolResult.php",
    "AgentKit/Tools/ToolContext.php",
    "AgentKit/Tools/ToolInterface.php",
]

pytestmark = pytest.mark.skipif(
    shutil.which("php") is None, reason="php not installed on this runner"
)


def registered_tools() -> list[str]:
    """Class short-names registered in the ToolRegistry factory setup."""
    src = NEON.read_text(encoding="utf-8")
    names = re.findall(r"register\(@App\\AgentKit\\Tools\\(\w+)\)", src)
    assert names, (
        "no tools found in common.neon's ToolRegistry setup — the registry "
        "block moved or was renamed; point this gate at the new shape rather "
        "than letting it pass vacuously."
    )
    return names


def test_the_registry_is_not_empty():
    """A gate that iterates an empty list is a gate that always passes."""
    assert len(registered_tools()) >= 5, (
        f"only {len(registered_tools())} tools registered; the estate has had "
        "at least five since MigrationWriteTool. If tools were removed, update "
        "this floor deliberately."
    )


@pytest.mark.parametrize("tool", registered_tools())
def test_the_tool_class_materialises(tool: str, tmp_path: Path):
    """Require the file for real and assert the class exists afterwards."""
    path = TOOLS_DIR / f"{tool}.php"
    assert path.is_file(), (
        f"common.neon registers {tool} but {path.relative_to(REPO)} does not "
        "exist. The registry would throw at session start."
    )

    requires = "\n".join(f"require '{WING_APP}/{p}';" for p in PRELUDE)
    script = tmp_path / "load.php"
    script.write_text(textwrap.dedent(f"""\
        <?php
        {requires}
        require '{path}';
        echo class_exists('App\\\\AgentKit\\\\Tools\\\\{tool}', false) ? 'OK' : 'MISSING';
    """), encoding="utf-8")

    proc = subprocess.run(
        ["php", "-d", "error_reporting=E_ALL", str(script)],
        capture_output=True, text=True, timeout=60,
    )
    combined = (proc.stdout + proc.stderr).strip()
    assert proc.returncode == 0 and "OK" in proc.stdout, (
        f"{tool} does not load.\n\n{combined}\n\n"
        "php -l would pass this — a missing `use` is valid syntax. Only "
        "executing the file provokes the check that catches it."
    )


def test_every_tool_imports_the_schema_it_returns():
    """The specific slip, kept as a fast signal beside the slow one.

    The load test above is authoritative. This one names the actual mistake so
    a failure reads as 'you forgot the import' rather than 'PHP said something
    about covariance'.
    """
    missing = []
    for tool in registered_tools():
        src = (TOOLS_DIR / f"{tool}.php").read_text(encoding="utf-8")
        if "ToolSchema" in src and "use App\\AgentKit\\LLMClient\\ToolSchema;" not in src:
            missing.append(tool)
    assert not missing, (
        f"tool(s) referencing ToolSchema without importing it: {missing}. "
        "Unqualified, it resolves to App\\AgentKit\\Tools\\ToolSchema, which "
        "does not exist."
    )
