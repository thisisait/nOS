"""A refusal in pazny.wing must gather its evidence even under --check.

MEASURED 2026-08-29 on a healthy host, running `ansible-playbook main.yml
--tags wing --check`:

    fatal: frankenphp at /opt/homebrew/bin/frankenphp did not report the
           pinned version 1.12.4 (rc=0).  Reported:

`frankenphp --version` prints exactly `FrankenPHP v1.12.4`. And one task
further down, after that was fixed:

    fatal: Wing daemon did not bind 127.0.0.1:9000 within 20 seconds

while `curl http://127.0.0.1:9000/` returned 403 — the daemon answering, on the
port the message names.

Both are the same mechanism. `command` and `uri` do not execute under `--check`;
the registered result comes back empty, `| default(0)` turns the absence into a
zero, and the refusal reads that zero as a measurement. **A preflight that
cannot distinguish NOT MEASURED from MEASURED BAD is this estate's signature
defect, and here it points the wrong way** — a dry run inventing failures a
converge does not have is how people learn to stop dry-running.

`check_mode: false` on a READ is the fix: it is already the idiom in 145 places
in this tree, and a version probe or a GET changes nothing.

SCOPE, and it is deliberately narrow. A scan of `roles/` and `tasks/` finds
seventeen more refusals of the same shape, in restore, patch, dnsmasq, ollama,
superset and removal-verify paths. None of them was measured — a full `--check`
of `main.yml` stops at task 29 needing sudo, so nothing here proves those
seventeen are ever reached in a dry run. They are named in
`docs/hidden_fees/36` rather than edited on suspicion. This gate covers the
role where the defect was actually observed.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.wing/tasks"

#: Modules that perform NO work under `--check` and hand back an empty result.
BLIND_IN_CHECK = {"command", "shell", "raw", "script", "uri",
                  "ansible.builtin.command", "ansible.builtin.shell",
                  "ansible.builtin.raw", "ansible.builtin.script",
                  "ansible.builtin.uri"}
DECIDERS = {"fail", "assert", "ansible.builtin.fail", "ansible.builtin.assert"}


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        if any(k in node for k in ("name", "block", "when", "register")):
            yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from _tasks(node[key])


def test_no_wing_refusal_reads_a_result_a_dry_run_never_produced() -> None:
    offences = []
    for path in sorted(ROLE.rglob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not doc:
            continue
        tasks = list(_tasks(doc))
        # Registers filled by a module that does nothing under --check, and
        # whose task did not opt out of check mode.
        blind = {t["register"]: t.get("name", "?") for t in tasks
                 if (set(t) & BLIND_IN_CHECK) and "register" in t
                 and t.get("check_mode") is not False}
        for task in tasks:
            decider = set(task) & DECIDERS
            if not decider:
                continue
            # The DECISION only, never the message. `fail:` interpolates its
            # diagnostic into `msg:`, where a missing register already renders
            # its own `default('(diagnose task skipped)')` — honest, and not a
            # verdict. Reading msg as a condition reported that as an offence,
            # which would have taught the next reader to delete this gate.
            condition = str(task.get("when", ""))
            body = task[decider.pop()]
            if isinstance(body, dict) and "that" in body:      # assert
                condition += str(body["that"])
            for register, source in blind.items():
                if register in condition:
                    offences.append(
                        f"{path.relative_to(REPO)}: {task.get('name', '?')!r} "
                        f"decides on ${register}, filled by {source!r} which "
                        "runs nothing under --check")
    assert not offences, (
        "a dry run of this role would refuse on evidence it never gathered:\n  "
        + "\n  ".join(offences)
        + "\nAdd `check_mode: false` to the reading task — it is a read, and "
          "the alternative is a --check that invents failures.")


def test_the_two_measured_probes_still_opt_out() -> None:
    """Named individually so a reflow of the scan above cannot quietly drop the
    two cases that were actually observed failing."""
    body = (ROLE / "main.yml").read_text(encoding="utf-8")
    for marker in ("did not report the pinned", "did not bind 127.0.0.1"):
        assert marker in body, f"the {marker!r} refusal is gone — re-scope this gate"
    assert body.count("check_mode: false") >= 2, (
        "pazny.wing has fewer than two check-mode opt-outs; the frankenphp "
        "version read and the daemon health probe both need one")
