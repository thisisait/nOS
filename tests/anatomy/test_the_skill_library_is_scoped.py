"""Main holds the whole library; an agent holds only what named it.

WHY THIS IS A GATE. Before 2026-08-27 the estate had one skill, rendered by
`roles/pazny.hermes` into one consumer's directory, and it had drifted — four
references to `~/projects/mac-dev-playbook`, a repository name retired in the
nOS rebrand. Nobody read it back because nothing was on the other end.

The library replaces that with a shelf and a distribution rule, and the rule is
the part worth pinning:

  * **main** is a harness a human is driving. It gets EVERY skill, and that must
    stay an invariant rather than a list — the moment it becomes an enumeration
    somebody adds a skill and forgets a shelf.
  * **agent** is an autonomous runner. It gets only skills whose
    `metadata.nos.audience` names it. `audience: []` therefore means
    operator-only, NOT nobody, and the two must never collapse: `[]` reaching an
    agent is a runner holding a procedure nobody scoped to it.

THE SPECIFIC REGRESSION THIS WATCHES FOR is the one the estate keeps paying:
one truth in two spellings. `pazny.hermes` rendering its own copy while the
library links another would put two nOS skills on one shelf under two names,
neither knowing about the other — the cAdvisor scrape, the dual agent
declaration, the `install_bone` divergence, again.

WHAT IT CANNOT SEE. Whether a skill is CORRECT, whether the link is on disk
(that is `tools/skill-status.py` against a real host), or whether a model uses
it well. Upstream's own caveat applies and is worth repeating: different models
will use a skill to different effect. A skill is a prompt; the gates are what
hold.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LIBRARY = REPO / "files/anatomy/skills"
CONFIG = REPO / "default.config.yml"
DISTRIBUTOR = REPO / "tasks/skills.yml"

#: Numbers that were true once and rot silently inside a procedure. The old
#: skill carried "47+ containers"; a model reads that as fact with no way to
#: check it.
MOVING_NUMBER = re.compile(r"\b\d{2,}\+?\s+(containers?|plugins?|services?|roles?|gates?)\b",
                           re.I)


def _skills() -> list[tuple[str, dict, str]]:
    out = []
    for path in sorted(LIBRARY.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{path} has no frontmatter"
        fm = yaml.safe_load(text.split("---")[1]) or {}
        out.append((path.parent.name, fm, text))
    return out


def _consumers() -> list[dict]:
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    return doc.get("nos_skill_consumers") or []


def test_the_library_is_not_empty():
    assert _skills(), (
        f"{LIBRARY.relative_to(REPO)} holds no SKILL.md. If the library was "
        "deliberately emptied, the distributor and this gate go with it.")


@pytest.mark.parametrize("name", [n for n, _, _ in _skills()])
def test_every_skill_declares_an_audience(name):
    """Absent and empty are different. `[]` is a decision (operator-only);
    a missing key is an author who did not think about it, and the distributor
    would silently treat it as `[]` — right by luck, not by declaration."""
    fm = dict(_skills())[name] if False else next(f for n, f, _ in _skills() if n == name)
    nos = (fm.get("metadata") or {}).get("nos")
    assert nos is not None and "audience" in nos, (
        f"{name}: metadata.nos.audience is missing. Write `audience: []` if the "
        "skill is operator-only — main receives it either way, and an explicit "
        "empty list says somebody chose.")
    assert isinstance(nos["audience"], list), f"{name}: audience must be a list"


@pytest.mark.parametrize("name", [n for n, _, _ in _skills()])
def test_an_audience_names_a_declared_agent(name):
    """An audience naming a consumer that does not exist reaches nobody, and
    looks exactly like one that reaches somebody."""
    fm = next(f for n, f, _ in _skills() if n == name)
    audience = ((fm.get("metadata") or {}).get("nos") or {}).get("audience") or []
    known = {c.get("id") for c in _consumers()}
    unknown = sorted(set(audience) - known)
    assert not unknown, (
        f"{name}: audience names {unknown}, which is not in nos_skill_consumers "
        f"({sorted(known)}). The link would never be made and nothing would say so.")


@pytest.mark.parametrize("name", [n for n, _, _ in _skills()])
def test_a_skill_carries_no_moving_number(name):
    """The retired skill said '47+ containers'. A count in a procedure is a
    fact with an expiry date and no expiry mechanism — name the reader instead."""
    text = next(t for n, _, t in _skills() if n == name)
    hits = MOVING_NUMBER.findall(text)
    assert not hits, (
        f"{name} states a count that moves ({hits}). Point at the reader that "
        "answers — tools/red-status.py, tools/rem-status.py, docker ps.")


@pytest.mark.parametrize("name", [n for n, _, _ in _skills()])
def test_a_skill_says_when_not_to_use_it(name):
    """A procedure with no refusal clause gets applied to everything and stops
    discriminating, which is worse than not being there."""
    text = next(t for n, _, t in _skills() if n == name).lower()
    assert "when not to use" in text, (
        f"{name} has no 'When NOT to use' section.")


def test_main_takes_the_whole_library_as_an_invariant():
    """Read from the distributor's own condition, not from its comments. If the
    `main` branch ever starts consulting the audience, main stops being 'every
    skill' and becomes another list to keep in step."""
    src = DISTRIBUTOR.read_text(encoding="utf-8")
    cond = re.search(r"item\.1\.kind == 'main' or item\.1\.id in \(item\.0\.audience[^\n]*", src)
    assert cond, (
        "the link task's audience condition is gone or reshaped. It must read "
        "'main takes everything, or the agent is named' — see the file's header.")


def test_the_hermes_role_no_longer_renders_its_own_copy():
    """The migration seam. Two owners of one skill is the defect this estate
    pays for most often; the role must not resurrect its template."""
    # PARSE THE TASKS, do not grep the file. The first cut matched the literal
    # `skills/nos/SKILL.md.j2` anywhere in the text and failed on the migration
    # COMMENT that explains why the template is gone — a detector reporting a
    # description as the fact, which is this repository's most repeated defect
    # and the third instance found in a single day (2026-08-27).
    role = REPO / "roles/pazny.hermes/tasks/main.yml"
    tasks = yaml.safe_load(role.read_text(encoding="utf-8")) or []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        tmpl = task.get("template") or task.get("ansible.builtin.template")
        if isinstance(tmpl, dict) and "skills/" in str(tmpl.get("src", "")):
            raise AssertionError(
                f"pazny.hermes renders a skill again ({tmpl['src']}). The library "
                "owns nos-devops and links it onto Hermes's shelf; a second copy "
                "under a second name is one truth in two spellings, with nothing "
                "able to notice they disagree.")
    template = REPO / "roles/pazny.hermes/templates/skills/nos/SKILL.md.j2"
    assert not template.exists(), (
        f"{template.relative_to(REPO)} is back. It moved to "
        "files/anatomy/skills/nos-devops/SKILL.md on 2026-08-27.")


def test_the_hermes_shelf_agrees_with_the_role_default():
    """A literal path here and a role default there is one truth twice.

    `nos_skill_consumers` cannot say `{{ hermes_config_dir }}`: that var is a
    role default, role defaults load during stack-up, and the eager `{{ vars }}`
    resolve at main.yml:1345 happens first — referencing it aborts the run even
    behind `| default()` (CLAUDE.md's documented trap; test_config_stock_jinja_only
    caught exactly this on 2026-08-27, minutes after it was written).

    So the literal stays, and this makes the coupling loud instead of silent.
    Same move as `install_bone`: when two expressions must agree and the
    language cannot make one derive from the other, a gate holds them together.
    """
    role_defaults = REPO / "roles/pazny.hermes/defaults/main.yml"
    doc = yaml.safe_load(role_defaults.read_text(encoding="utf-8")) or {}
    declared = str(doc.get("hermes_config_dir", ""))
    shelf = next((c for c in _consumers() if c.get("id") == "hermes"), None)
    if shelf is None:
        pytest.skip("hermes is not a declared skill consumer")

    def tail(p: str) -> str:
        return p.replace("{{ ansible_facts['env']['HOME'] }}", "~").strip()

    assert tail(shelf["dir"]) == tail(declared) + "/skills", (
        f"the hermes shelf is {tail(shelf['dir'])!r} but pazny.hermes puts its "
        f"config at {tail(declared)!r}. The skills would be linked into a "
        "directory Hermes does not read, and nothing at runtime would say so.")


def test_a_consumer_declares_its_kind():
    consumers = _consumers()
    assert consumers, "nos_skill_consumers is empty — nothing would be linked"
    for c in consumers:
        assert c.get("kind") in ("main", "agent"), (
            f"consumer {c.get('id')!r} has kind {c.get('kind')!r}; only 'main' "
            "(full library) and 'agent' (named skills only) exist")
        assert c.get("id") and c.get("dir"), f"consumer {c} is missing id or dir"
