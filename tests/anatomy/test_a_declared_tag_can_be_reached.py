"""A tag you declare on a task must be a tag that can select it.

THE DEFECT, THREE TIMES IN ONE DAY (2026-08-05):

  1. `--tags uptime-kuma` did not reconverge Kuma's monitors. The task declares
     that tag; it sits in `roles/pazny.apps_runner/tasks/post.yml`, entered
     through an include in `apps-up.yml` carrying `['apps','tier2',
     'apps-runner']`. A dynamic include is ITSELF tag-filtered, so the filter
     stops at the door and never sees the tag inside.
  2. Same file, three more: `authentik`, `iam`, `portainer` — all declared, none
     reachable.
  3. `--tags coexist-provision`, `coexist-cutover`, `coexist-cleanup`: task
     files complete, tagged, documented in four places, imported by NOTHING.
     `files/anatomy/bone/coexistence.py` calls all three via `invoke_playbook`,
     so three Bone endpoints ran a playbook that matched no task and returned
     rc=0 — the operator-supervises-agents path reporting success for work it
     had not done.

The shape is the one this repo keeps finding: two representations of one fact
(here "this tag reaches this task" — the declaration, and the include chain)
with nothing comparing them. A declared tag that cannot be selected is worse
than no tag, because it is documented, copied into runbooks, and called by
Bone.

HOW THE ANALYSIS WORKS. Walk from `main.yml` and carry two things per task:

  inherited — tags pushed down. `import_*` and `block:` push their own tags
              onto children; `include_role` pushes only what `apply:` declares
              (the quirk CLAUDE.md documents); `include_tasks` pushes its own.
  gate      — the constraint a dynamic include imposes. `import_*` is expanded
              at parse time and imposes none. A dynamic include only fires when
              --tags matches ITS selectors, so its children can never be reached
              by a tag the include does not carry: gate ∩= selectors(include).

A tag `t` declared on a task is ALIVE on a path when the gate admits it, and
DEAD when it does not. A task can be reached by several paths, so a tag is
reported only when it is dead on every one of them.

`always` is exempt in both directions: a task carrying it runs under every
filter, so nothing about it can be unreachable.

WHAT THIS DOES NOT CHECK. Reachability, not effect. `--tags uptime-kuma` can
now enter the file; whether the task's `when:` then holds is a different
question and belongs to a converge. That distinction is the standing division
of labour: pytest owns the shape, `--tags verify` owns the effect.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
STATIC = {"import_tasks", "import_role",
          "ansible.builtin.import_tasks", "ansible.builtin.import_role"}
DYNAMIC = {"include_tasks", "include_role",
           "ansible.builtin.include_tasks", "ansible.builtin.include_role"}
TOP = None  # gate sentinel: unconstrained


def _tags(obj) -> set[str]:
    raw = obj.get("tags") if isinstance(obj, dict) else None
    if raw is None:
        return set()
    if isinstance(raw, str):
        return {raw}
    return {str(x) for x in raw if isinstance(x, (str, int))}


def _load(path: Path) -> list:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return doc if isinstance(doc, list) else []


def _task_file(spec, base: Path) -> Path | None:
    if not isinstance(spec, str) or "{{" in spec:
        return None
    for cand in (REPO / spec, base / spec):
        if cand.is_file():
            return cand
    return None


def _role_file(value) -> Path | None:
    name = value.get("name") if isinstance(value, dict) else value
    entry = (value.get("tasks_from") if isinstance(value, dict) else None) or "main.yml"
    if not isinstance(name, str) or "{{" in name or "{{" in str(entry):
        return None
    path = REPO / "roles" / name / "tasks" / str(entry)
    if path.suffix != ".yml":
        path = path.with_suffix(".yml")
    return path if path.is_file() else None


class Walker:
    def __init__(self) -> None:
        self.alive: set[tuple[str, str, str]] = set()
        self.dead: set[tuple[str, str, str]] = set()
        self.entered: set[str] = set()
        self._seen: set = set()

    def record(self, path: Path, task: dict, own: set[str], gate) -> None:
        if "always" in own:
            return
        where = str(path.relative_to(REPO))
        name = str(task.get("name", "?"))[:90]
        for tag in own:
            key = (where, name, tag)
            if gate is TOP or tag in gate:
                self.alive.add(key)
            else:
                self.dead.add(key)

    def walk(self, tasks: list, path: Path, inherited: frozenset, gate, depth: int = 0) -> None:
        if depth > 30:
            return
        for task in tasks:
            if not isinstance(task, dict):
                continue
            own = _tags(task)
            selectors = frozenset(own | inherited)
            self.record(path, task, own, gate)

            for key in ("block", "rescue", "always"):
                if isinstance(task.get(key), list):
                    self.walk(task[key], path, selectors, gate, depth + 1)

            for key, value in task.items():
                if key in STATIC:
                    child = (_role_file(value) if "import_role" in key
                             else _task_file(value if isinstance(value, str)
                                             else (value or {}).get("file"), path.parent))
                    if child:
                        self.enter(child, selectors, gate, depth)
                elif key in DYNAMIC:
                    passed = selectors if gate is TOP else frozenset(set(gate) & selectors)
                    if "include_role" in key:
                        child = _role_file(value)
                        pushed = frozenset(_tags((value or {}).get("apply")
                                                 if isinstance(value, dict) else None))
                    else:
                        child = _task_file(value if isinstance(value, str)
                                           else (value or {}).get("file"), path.parent)
                        pushed = selectors
                    if child:
                        self.enter(child, pushed, passed, depth)

    def enter(self, path: Path, inherited: frozenset, gate, depth: int) -> None:
        key = (str(path), inherited, None if gate is TOP else gate)
        if key in self._seen:
            return
        self._seen.add(key)
        self.entered.add(str(path.relative_to(REPO)))
        self.walk(_load(path), path, inherited, gate, depth + 1)


def _analyse() -> Walker:
    walker = Walker()
    doc = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))
    for play in doc if isinstance(doc, list) else []:
        if not isinstance(play, dict):
            continue
        for section in ("pre_tasks", "tasks", "post_tasks", "handlers"):
            if isinstance(play.get(section), list):
                walker.walk(play[section], REPO / "main.yml", frozenset(), TOP, 0)
    return walker


def test_the_walk_actually_reaches_the_playbook():
    """Positive control — a walk that visits nothing proves nothing below."""
    walker = _analyse()
    assert len(walker.entered) > 80, (
        f"the tag walk only entered {len(walker.entered)} files; it is not "
        f"covering the playbook and every assertion below is vacuous"
    )
    for landmark in ("tasks/stacks/stack-up.yml",
                     "tasks/stacks/apps-up.yml",
                     "roles/pazny.uptime_kuma/tasks/monitors.yml",
                     "tasks/coexistence-provision.yml"):
        assert landmark in walker.entered, f"the walk never reached {landmark}"
    assert walker.alive, "no tag was found reachable — the walk is not recording"


def test_every_declared_tag_can_select_its_task():
    walker = _analyse()
    unreachable = sorted(walker.dead - walker.alive)
    assert not unreachable, (
        "these tags are declared on a task that `--tags <tag>` can never select, "
        "on any path from main.yml. Either a dynamic include on the way in does "
        "not carry the tag (add it there), or nothing imports the file at all "
        "(give it an entry point beside its siblings) — or the declaration is "
        "decorative and should go:\n"
        + "\n".join(f"  --tags {tag:22} {where}\n{'':29}{name}"
                    for where, name, tag in unreachable)
    )


def test_bone_only_invokes_tags_that_exist():
    """Bone drives the playbook by tag; a tag it names must be selectable.

    This is the half that pytest can see of "agents drive, operator supervises".
    Bone's coexistence endpoints named three tags no task carried, and the run
    came back rc=0 — a success marker written by the code that attempted the
    work rather than by anything that read the result.
    """
    import re

    walker = _analyse()
    selectable = {tag for _, _, tag in walker.alive}
    source = (REPO / "files/anatomy/bone/coexistence.py").read_text(encoding="utf-8")
    invoked = set(re.findall(r"invoke_playbook\(\s*[\"']([a-z0-9-]+)[\"']", source))
    assert invoked, "no invoke_playbook tags found — this gate has gone blind"
    missing = sorted(invoked - selectable)
    assert not missing, (
        f"Bone invokes the playbook with {missing}, and no task in main.yml's "
        f"reachable graph carries those tags. The run matches nothing, exits 0, "
        f"and the endpoint reports success."
    )
