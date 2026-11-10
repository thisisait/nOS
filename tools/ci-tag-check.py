#!/usr/bin/env python3
"""`ansible-playbook main.yml --check --tags <tag>`, red only on an evaluation error.

  tools/ci-tag-check.py --list          # the tags (tools/ci-tag-check.yml) as a JSON matrix
  tools/ci-tag-check.py authentik [-e ...]

Check mode on a clean runner halts at the first task that needs a real effect (infra
bring-up: nothing was rendered, docker is absent on purpose). That halt is the lane's frontier, not
a defect: it is printed and the run is green. Red = an undefined variable, a missing
file/template/include, an unknown filter/module, or a parse error — the 2026-11-10 class
(`--tags authentik`: 'nos_plugin_ctx' is undefined).
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
TAGS = REPO / "tools" / "ci-tag-check.yml"
SANDBOX = ["-e", "allow_weak_prefix=true", "-e", "@profiles/core.yml",
           "-e", '{"install_thalamus": false}',
           # No docker: `check_mode: false` compose tasks must start nothing on the runner.
           "-e", "docker_bin=/nonexistent/docker", "-e", "nos_docker_bin=/nonexistent/docker",
           "-e", "nos_allow_no_docker=true"]
EVAL = re.compile(r"is undefined|has no attribute|Finalization of task args|Error while resolving value"
                  r"|Could not find or access|Unable to retrieve file contents|Could not find specified file"
                  r"|template error|Syntax error in template|No filter named|No test named"
                  r"|couldn't resolve module/action|conflicting action statements")
FATAL = re.compile(r"^fatal: \[[^\]]+\]: FAILED! => (\{.*\})\s*$")
TASK = re.compile(r"^TASK \[(.*)\] \*+")


def classify(rc: int, lines: list[str]) -> tuple[bool, str]:
    """(red, why) from the default callback's output."""
    task, fatals = "?", []
    for line in lines:
        if m := TASK.match(line):
            task = m.group(1)
        elif m := FATAL.match(line):
            try:
                msg = str(json.loads(m.group(1)).get("msg", ""))
            except ValueError:
                msg = m.group(1)
            fatals.append((task, msg))
    if rc == 0:
        return False, "completed"
    if re.search(r"unreachable=[1-9]", "".join(lines)):
        return True, "host unreachable"
    for task, msg in fatals:
        if EVAL.search(msg):
            return True, f"evaluation error at [{task}]: {msg.splitlines()[0][:300]}"
    if not fatals:  # rc != 0 and no task failed: a parse/load error before any task ran
        err = next((l.strip() for l in lines if "ERROR" in l), f"rc={rc}, no task failed")
        return True, f"playbook did not load: {err[:300]}"
    task, msg = fatals[0]
    return False, f"frontier [{task}]: {(msg.splitlines() or [''])[0][:200]}"


def main(argv: list[str]) -> int:
    tags = yaml.safe_load(TAGS.read_text(encoding="utf-8"))["tags"]
    if argv[:1] == ["--list"]:
        print(json.dumps(sorted(tags)))
        return 0
    tag, extra = argv[0], argv[1:]
    cmd = ["ansible-playbook", "main.yml", "--check", "--tags", tag, *SANDBOX,
           "-e", json.dumps(tags.get(tag) or {}), *extra]
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    for line in proc.stdout:  # stream, never filter: a long run must not look frozen
        sys.stdout.write(line)
        lines.append(line)
    red, why = classify(proc.wait(), lines)
    print(f"::{'error' if red else 'notice'}::--check --tags {tag}: {why}")
    return 1 if red else 0


def _selfcheck() -> None:
    ok = ['TASK [a] ***', 'fatal: [localhost]: FAILED! => {"msg": "Stacks [infra] will not become ready."}']
    assert classify(2, ok) == (False, "frontier [a]: Stacks [infra] will not become ready.")
    bad = ['TASK [b] ***', 'fatal: [localhost]: FAILED! => {"msg": "Task failed: Finalization of task args'
           ' for \'x\' failed: \'nos_plugin_ctx\' is undefined"}']
    assert classify(2, bad)[0] and "[b]" in classify(2, bad)[1]
    assert classify(4, ["[ERROR]: couldn't parse"])[0]
    assert classify(0, []) == (False, "completed")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selfcheck"]:
        _selfcheck()
        sys.exit(0)
    sys.exit(main(sys.argv[1:]) if sys.argv[1:] else 2)
