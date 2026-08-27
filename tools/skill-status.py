#!/usr/bin/env python3
"""What is on the shelf, who should be holding it, and who actually is.

WHY THIS EXISTS. `tasks/skills.yml` links the library onto each reader's shelf,
and a task that reports `changed` has said only that Ansible did something — not
that a reader can now find the procedure. The distribution and the check must be
different pieces of code or the check is the distributor grading itself, which
is this estate's most expensive recurring defect.

So this reads from the other end: it walks the consumer directories on disk and
asks what is there, then compares with what the library's own frontmatter says
should be.

    tools/skill-status.py
    tools/skill-status.py --json

THE VERDICTS, and MISPLACED is the one that earns the tool:

    ok          the skill is linked where its audience says it belongs
    MISSING     it belongs there and is not there — a converge has not run,
                or the consumer's parent directory did not exist when it did
    MISPLACED   it is there and its audience does NOT name that agent. This is
                the failure that matters: an autonomous runner holding a
                procedure nobody scoped to it. Usually a stale link left behind
                when an audience was narrowed.
    BROKEN      a link pointing at nothing
    FOREIGN     something in the shelf that this library did not put there —
                reported, never touched; another tool may own it

WHAT IT WILL NOT DO. Create a link, repair one, or delete a stray. Repair
belongs to a converge. Exit 0 whatever it finds.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
LIBRARY = REPO / "files/anatomy/skills"
CONFIG = REPO / "default.config.yml"
HOME = pathlib.Path(os.path.expanduser("~"))


def consumers() -> list[dict]:
    """The shelves, read from default.config.yml rather than restated here.

    A second list would drift from the one the playbook uses, and the drift
    would be invisible precisely because both halves would look right.
    """
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    out = []
    for entry in doc.get("nos_skill_consumers") or []:
        raw = str(entry.get("dir", ""))
        # The config carries Jinja for HOME and hermes_config_dir; resolve the
        # two spellings this file can honestly resolve, and skip anything else
        # rather than guess a path and report a false MISSING against it.
        path = (raw.replace("{{ ansible_facts['env']['HOME'] }}", str(HOME))
                   .replace("{{ hermes_config_dir | default(ansible_facts['env']['HOME'] "
                            "+ '/.hermes') }}", str(HOME / ".hermes")))
        row = {"id": entry.get("id"), "kind": entry.get("kind"), "dir": path,
               "resolvable": "{{" not in path}
        out.append(row)
    return out


def library() -> list[dict]:
    out = []
    for skill in sorted(LIBRARY.glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        audience, err = [], ""
        try:
            fm = yaml.safe_load(text.split("---")[1]) or {}
            audience = ((fm.get("metadata") or {}).get("nos") or {}).get("audience") or []
        except (IndexError, yaml.YAMLError) as exc:
            err = f"frontmatter unreadable ({exc})"
        out.append({"name": skill.parent.name, "src": str(skill.parent),
                    "audience": list(audience), "error": err})
    return out


def survey() -> dict:
    skills, shelves, findings = library(), consumers(), []
    names = {s["name"] for s in skills}

    for shelf in shelves:
        d = pathlib.Path(shelf["dir"])
        if not shelf["resolvable"]:
            findings.append({"shelf": shelf["id"], "skill": None, "verdict": "UNKNOWN",
                             "detail": f"path {shelf['dir']!r} has unresolved Jinja"})
            continue
        present = {}
        if d.is_dir():
            for child in sorted(d.iterdir()):
                target = os.path.realpath(child) if child.is_symlink() else None
                present[child.name] = {"link": child.is_symlink(), "target": target,
                                       "broken": child.is_symlink() and not child.exists()}
        shelf["exists"] = d.is_dir()
        shelf["parent_exists"] = d.parent.is_dir()

        for skill in skills:
            entitled = shelf["kind"] == "main" or shelf["id"] in skill["audience"]
            here = present.get(skill["name"])
            if entitled and here is None:
                verdict = "MISSING" if shelf["parent_exists"] else "n/a"
                detail = ("belongs here and is absent" if shelf["parent_exists"] else
                          "harness not installed — the shelf is correctly absent")
            elif not entitled and here is not None:
                verdict, detail = "MISPLACED", (
                    f"audience is {skill['audience'] or '[] (operator-only)'} and does "
                    f"not name {shelf['id']!r}; an autonomous runner is holding a "
                    "procedure nobody scoped to it")
            elif here is not None and here["broken"]:
                verdict, detail = "BROKEN", f"link points at {here['target']}, which is gone"
            elif here is not None and here["target"] != os.path.realpath(skill["src"]):
                verdict, detail = "MISPLACED", (
                    f"link points at {here['target']}, not the library entry")
            elif here is not None:
                verdict, detail = "ok", ""
            else:
                continue
            findings.append({"shelf": shelf["id"], "skill": skill["name"],
                             "verdict": verdict, "detail": detail})

        for extra in set(present) - names:
            findings.append({"shelf": shelf["id"], "skill": extra, "verdict": "FOREIGN",
                             "detail": "not from this library — reported, not touched"})

    return {"library": skills, "shelves": shelves, "findings": findings}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    r = survey()
    if args.json:
        print(json.dumps(r, indent=2))
        return 0

    print(f"skill library — {len(r['library'])} skill(s) at "
          f"{LIBRARY.relative_to(REPO)}")
    for s in r["library"]:
        who = ", ".join(s["audience"]) if s["audience"] else "operator-only (main gets it anyway)"
        print(f"  {s['name']:<22} agents: {who}")
        if s["error"]:
            print(f"  {'':<22} {s['error']}")

    print("\nshelves:")
    for sh in r["shelves"]:
        state = ("present" if sh.get("exists") else
                 "absent (parent exists)" if sh.get("parent_exists") else
                 "harness not installed")
        print(f"  {sh['id']:<10} {sh['kind']:<6} {state:<24} {sh['dir']}")

    # FOREIGN is collapsed per shelf. Hermes alone bundles ~28 upstream skills,
    # and printing one line each buries the two verdicts an operator must act on
    # under a wall nobody reads to the bottom of. The count and a sample keep it
    # honest without drowning the finding — full detail is in --json.
    interesting = [f for f in r["findings"] if f["verdict"] not in ("ok", "n/a", "FOREIGN")]
    foreign: dict[str, list[str]] = {}
    for f in r["findings"]:
        if f["verdict"] == "FOREIGN":
            foreign.setdefault(f["shelf"], []).append(f["skill"])

    print(f"\n{len(interesting)} finding(s):" if interesting
          else "\nno findings — every entitled shelf holds what it should")
    for f in interesting:
        print(f"  {f['verdict']:<10} {f['shelf']}/{f['skill']}")
        if f["detail"]:
            print(f"             {f['detail']}")

    for shelf, names in sorted(foreign.items()):
        sample = ", ".join(sorted(names)[:4])
        more = f" +{len(names) - 4} more" if len(names) > 4 else ""
        print(f"  FOREIGN    {shelf}: {len(names)} not from this library "
              f"({sample}{more}) — another owner's, left alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
