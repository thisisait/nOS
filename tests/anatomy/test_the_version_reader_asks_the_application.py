"""`tools/app-version.py` asks the APPLICATION, never the tag it is checking.

WHY THIS GATE EXISTS AT ALL. The tool's entire value is that an image tag and an
application version are different numbers. `nfrastack/freescout:2.1.5-php8.3`
bundles FreeScout **1.8.230**; the pin's comment claimed 1.8.231; the image was
published a week BEFORE 1.8.231 was released, so the claim was impossible from
the day it was written. REM-142 was closed on it and REM-193 filed on it, and
two advisories the queue believed patched stayed live for six weeks (REM-218).

So the one thing this tool must never do is derive the answer from the tag. A
probe that ran `docker inspect --format {{.Config.Image}}` and parsed the
version out would report MATCH for every service forever, and it would look
exactly like a working tool. That is the estate's signature defect — a check
that goes green by asking the thing it was supposed to be independent of — and
it would be especially cheap to introduce here, because for three of the four
services the tag genuinely IS the version.

WHAT IS PINNED.

  1. Every probe runs INSIDE the container and reads the application: a file
     the app ships, or the binary's own `--version`. No probe may mention the
     image, the tag, or `inspect`.
  2. The tool cannot change anything — no mutating docker verb, no filesystem
     write. A reader that could also bump would be asked to certify its bump.
  3. An unreadable probe is UNKNOWN carrying a reason, never a quiet pass.
  4. It exits 0 on a MISMATCH, because reporting is the job.

WHAT IT CANNOT SEE. Whether a probe reads the RIGHT file — an app that keeps a
stale `VERSION` next to its real one would fool it. And it says nothing about
services not in the table; absence there is not a claim of health.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/app-version.py"

#: Words that mean "you are reading the packaging, not the program".
FROM_THE_TAG = ("inspect", "{{.Config.Image}}", "image", "tag")

MUTATING_DOCKER = ("start", "stop", "restart", "rm", "kill", "run", "pull",
                   "push", "create", "update", "compose", "cp", "commit")

WRITE_FS = ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rename",
            "replace", "chmod")


def source() -> str:
    return TOOL.read_text(encoding="utf-8")


def services() -> dict:
    """The SERVICES table, read from the AST so importing the tool (and its
    docker calls) is never needed to inspect its declarations."""
    for node in ast.walk(ast.parse(source())):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "SERVICES":
            return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", "") == "SERVICES":
                    return ast.literal_eval(node.value)
    raise AssertionError("tools/app-version.py no longer declares SERVICES")


def test_the_tool_this_gate_describes_exists():
    assert TOOL.is_file()


def test_every_probe_asks_the_application_and_not_the_tag():
    offenders = []
    for name, spec in services().items():
        argv = " ".join(str(a) for a in spec["argv"]).lower()
        for word in FROM_THE_TAG:
            if word.lower() in argv:
                offenders.append(f"{name}: probe mentions {word!r} — {argv[:70]}")
    assert not offenders, (
        "a probe that reads the image would report MATCH for every service "
        "forever, which is precisely the failure this tool exists to catch:\n  "
        + "\n  ".join(offenders))


def test_every_service_declares_whether_its_tag_tracks_the_app():
    """`tag_tracks_app` is the field that stops a deliberate difference reading
    as an error. nfrastack ships FreeScout 1.8.x inside images numbered 2.x —
    that is upstream's choice, not a defect."""
    missing = [n for n, s in services().items()
               if not isinstance(s.get("tag_tracks_app"), bool)]
    assert not missing, (
        "these entries do not say whether the tag tracks the application "
        "version, so the tool cannot tell a real split from a wrong pin: "
        + ", ".join(missing))
    for name, spec in services().items():
        assert spec.get("pin"), f"{name} names no pin variable to read the claim from"
        assert spec.get("container"), f"{name} names no container"


def test_it_cannot_change_anything():
    src = source()
    mutating = [v for v in MUTATING_DOCKER if f'"{v}"' in src]
    assert not mutating, (
        "a reader that can pull or restart will be asked to 'just bump it and "
        "re-measure', and then it is certifying its own work: " + ", ".join(mutating))
    writes = [v for v in WRITE_FS if v in src]
    assert not writes, "the reader must leave no artifact: " + ", ".join(writes)


def test_a_probe_that_cannot_answer_is_unknown_and_carries_a_reason():
    p = subprocess.run([sys.executable, str(TOOL), "--json"],
                       capture_output=True, text=True, timeout=180, cwd=REPO)
    assert p.returncode == 0, (
        f"reporting is the job; a MISMATCH is news, not a failure\n{p.stderr}")
    report = json.loads(p.stdout)
    assert {r["service"] for r in report["services"]} == set(services())
    for r in report["services"]:
        assert r["verdict"] in ("MATCH", "MISMATCH", "UNKNOWN", "UNCLAIMED")
        if r["verdict"] == "UNKNOWN":
            assert r.get("error"), f"{r['service']} is UNKNOWN with no reason given"
        else:
            assert r.get("app_version"), (
                f"{r['service']} reached a verdict without reading a version")
