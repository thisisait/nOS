"""Anatomy gate: every `{{ token }}` a Pulse job's env carries must be substitutable.

WHY. `files/anatomy/plugins/*/plugin.yml` declares Pulse jobs, and their `env:`
values carry **bare Jinja-looking tokens that Ansible never renders**. The
catalog builder `files/anatomy/scripts/discover-pulse-catalog.py` performs a
LITERAL string substitution over a hardcoded table: `"{{ mail_host }}"` →
`_env("NOS_MAIL_HOST")`, with the `NOS_*` values Ansible-rendered by
`roles/pazny.wing/tasks/post.yml` at task time (see the A9.4 and Phase-6
comments there).

That means a token with no table entry is NOT an error and NOT an empty string —
it is passed through **verbatim**, so the job is registered holding the literal
seven characters `{{ foo }}` as its env value and fails only when it next fires,
somewhere far from the manifest that caused it.

This gate pins the join: manifest token ⟷ substitution table ⟷ NOS_* export.

HISTORY, because it cost a session. On 2026-07-27 a converge run with
`--tags keap,cortex` left **zero** cortex Pulse jobs registered, and the first
diagnosis was "`cortex_fanout_url` is an undefined Ansible var — add it to
default.config.yml". That was wrong on both counts: the name is a substitution
token, not a var (adding it to a vars file would have done nothing), and the
wiring was already complete on all three sides. The real cause was the tag
selection — the catalog is rebuilt by `pazny.wing`'s post.yml, which runs under
`['wing', 'security']` and so never ran. The gate below is what makes the first
diagnosis unnecessary next time: it proves the three-sided join is intact, so a
missing job points at the run, not the wiring.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"
CATALOG = REPO / "files" / "anatomy" / "scripts" / "discover-pulse-catalog.py"
WING_POST = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"


def _pulse_env_lines(text: str) -> list[tuple[int, str]]:
    """(line, text) for every interpolated value under a top-level `pulse:` block.

    The schema is `pulse:` → `jobs:` → per-job `env:` — NOT a `pulse_jobs:` key,
    which is what the prose in CLAUDE.md calls it. A first draft of this gate
    searched for `pulse_jobs:`, matched nothing in any manifest, and therefore
    reported a clean run over the very defect it was written for; hence
    `test_scoper_actually_sees_the_env_lines` below.

    Scoped by indentation rather than parsed as YAML on purpose: manifests carry
    Jinja that is not valid YAML scalar content everywhere.
    """
    out: list[tuple[int, str]] = []
    in_pulse = in_env = False
    env_indent = 0
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if re.match(r"^pulse:", line):
            in_pulse, in_env = True, False
            continue
        if in_pulse and indent == 0 and re.match(r"^[a-zA-Z_]\w*:", line):
            in_pulse = in_env = False
        if not in_pulse:
            continue
        if re.match(r"^env:", stripped):
            in_env, env_indent = True, indent
            continue
        if in_env:
            if stripped and indent <= env_indent and not stripped.startswith("#"):
                in_env = False
            elif "{{" in line:
                out.append((ln, line))
    return out


def _tokens(line: str) -> list[str]:
    """The literal `{{ name }}` tokens in a line, normalised to single spacing."""
    return ["{{ " + m.strip() + " }}" for m in re.findall(r"\{\{(.*?)\}\}", line)]


def _substitution_table() -> set[str]:
    return set(re.findall(r'"(\{\{[^"]*?\}\})"\s*:', CATALOG.read_text()))


def test_scoper_actually_sees_the_env_lines() -> None:
    """Pin the scoper: a gate that reads nothing passes everything."""
    blocks = _pulse_env_lines((PLUGINS / "cortex-base" / "plugin.yml").read_text())
    assert blocks, "the scoper found no pulse env lines in cortex-base — it is reading the wrong key"
    assert any("CORTEX_API_URL" in line for _, line in blocks), (
        "the scoper missed CORTEX_API_URL, the env this gate is about"
    )


def test_every_pulse_env_token_has_a_substitution() -> None:
    """A token absent from the table is passed through verbatim into the job."""
    table = _substitution_table()
    assert table, "the substitution table could not be parsed — this gate is measuring nothing"
    offenders: list[str] = []
    for manifest in sorted(PLUGINS.glob("*/plugin.yml")):
        for ln, line in _pulse_env_lines(manifest.read_text(errors="replace")):
            for tok in _tokens(line):
                if tok not in table:
                    offenders.append(f"{manifest.parent.name}/plugin.yml:{ln} {tok}")
    assert not offenders, (
        "A Pulse job's env carries a token with no entry in discover-pulse-catalog.py's "
        "substitution table. The catalog does a LITERAL replace, so the token is not "
        "rendered and not blanked — the job is registered holding the raw Jinja text and "
        "fails when it fires. Add the token to the table AND export the matching NOS_* "
        "from roles/pazny.wing/tasks/post.yml. Offenders:\n  " + "\n  ".join(offenders)
    )


def test_every_substitution_has_an_ansible_side() -> None:
    """A table entry whose NOS_* nobody exports silently substitutes to ''.

    `_env(name, "")` defaults to the empty string, so a missing export is
    indistinguishable at run time from "the operator left it unset" — which is
    how a fan-out target, a token or a URL becomes quietly empty.
    """
    table_pairs = re.findall(r'"\{\{[^"]*?\}\}"\s*:\s*_env\(\s*"([A-Z0-9_]+)"', CATALOG.read_text())
    assert table_pairs, "no NOS_* names parsed out of the substitution table"
    exported = set(re.findall(r"^\s*(NOS_[A-Z0-9_]+):", WING_POST.read_text(), re.M))
    missing = sorted({n for n in table_pairs if n not in exported})
    assert not missing, (
        "discover-pulse-catalog.py substitutes these NOS_* names, but "
        "roles/pazny.wing/tasks/post.yml exports none of them — they resolve to '' and "
        "the job runs with an empty value rather than failing. Missing:\n  "
        + "\n  ".join(missing)
    )


def test_the_cortex_fanout_join_is_intact_end_to_end() -> None:
    """The specific three-sided join whose absence emptied the cortex job set."""
    assert "{{ cortex_fanout_url }}" in _substitution_table(), (
        "the cortex fan-out token lost its substitution entry"
    )
    post = WING_POST.read_text()
    assert re.search(r"^\s*NOS_CORTEX_FANOUT_URL:", post, re.M), (
        "roles/pazny.wing/tasks/post.yml no longer exports NOS_CORTEX_FANOUT_URL"
    )
    assert "install_cortex" in post.split("NOS_CORTEX_FANOUT_URL:", 1)[1].split("\n", 1)[0], (
        "the fan-out URL must render to '' when the organ is not installed — that empty "
        "string is what makes the consolidator degrade to a single target instead of "
        "POSTing captures at a port nothing binds"
    )
