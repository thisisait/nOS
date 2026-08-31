"""The voice loop, held to the claims it makes about itself.

WHY THIS EXISTS. An adversarial review on 2026-08-31 found the feature shipped
with ~1000 lines and no gate of its own: `--selfcheck` was good and nothing ran
it, and the reader probed the WRONG PYTHON for parakeet — so a perfectly
converged estate would have reported its own deliverable absent for ever. Both
are the estate's own recurring shape (a detector reading the wrong artifact),
which is exactly the class a gate is supposed to hold.

WHAT IT PINS, and each is behaviour or an artifact, never prose:

  1. the listener's own selfcheck RUNS — turn segmentation and a retention
     sweep against real files with real mtimes;
  2. the reader probes the VENV interpreter, not the one it happens to run in;
  3. the retention horizon is ONE number — the role default, the plist, and
     both Article-30 records agree, because a horizon declared twice is a
     register that lies the day someone edits one of them;
  4. every settings row the fixture seeds is a column the table declares, and
     every one names a reader — a config row nothing reads is how a toggle ends
     up half-armed, and this estate has paid for that shape more than once;
  5. EVERY opcode the cortex registry publishes can be SAID, in every declared
     language — because the verbaliser refuses a chain it has no words for
     rather than reading syntax aloud, so an untaught opcode is a silent loss
     of the spoken answer;
  6. a chain is verbalised or refused, never read as syntax — driven, including
     the refusal, and including the spelled identifier ("02.02" said as a
     number names a different node than the screen does);
  7. the microphone has exactly ONE switch.

CI-safe: no microphone, no model, no network, no launchd.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LISTENER = REPO / "files/anatomy/ears/ears-listen.py"
READER = REPO / "tools/caddy-status.py"
DEFAULTS = REPO / "roles/pazny.ears/defaults/main.yml"
PLIST = REPO / "roles/pazny.ears/templates/ears-listen.plist.j2"
FIXTURE = REPO / "state/fixtures/caddy.seed.yml"
TABLE = REPO / "state/keap-tables/caddy.table.yml"
WORDING = REPO / "files/anatomy/ears/wording.yml"


def test_the_listener_selfcheck_passes():
    """Its own asserts, run — not merely present. Covers the turn state machine,
    the wake-phrase variants, and a real retention sweep on real files."""
    assert LISTENER.is_file(), f"{LISTENER.relative_to(REPO)} is gone"
    run = subprocess.run([sys.executable, str(LISTENER), "--selfcheck"],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, f"selfcheck failed:\n{run.stdout}\n{run.stderr}"
    assert "OK" in run.stdout, f"selfcheck printed no verdict: {run.stdout!r}"


def test_the_reader_probes_the_interpreter_the_listener_runs_on():
    """The measured defect: `find_spec` in the reader's own interpreter answers
    about the WRONG python. parakeet lives in ~/ears/venv because that is where
    the role puts it, so that is where the question has to be asked."""
    src = READER.read_text()
    assert "venv" in src and 'import parakeet_mlx' in src, (
        "the ear probe no longer names the venv or the module — if it went back "
        "to find_spec in this process, a converged estate reports ear: ABSENT "
        "for ever")
    assert "importlib.util.find_spec(\"parakeet_mlx\")" not in src, (
        "the ear probe is asking THIS interpreter again (the 2026-08-31 defect)")


def test_the_retention_horizon_is_declared_once():
    """Role default, plist, and both agent Article-30 records — one number.

    Not a style rule: a retention horizon that disagrees with its register is a
    compliance claim nobody can act on, and the estate already owns one that was
    measured in days and could never fire."""
    defaults = yaml.safe_load(DEFAULTS.read_text())
    horizon = defaults["ears_retention_days"]
    assert isinstance(horizon, int) and horizon > 0

    assert "{{ ears_retention_days }}" in PLIST.read_text(), (
        "the plist hardcodes a horizon instead of rendering the role default — "
        "two numbers, and the daemon would win")

    for agent in ("jeff", "jeff-cloud"):   # the persona this estate ships
        doc = yaml.safe_load((REPO / f"files/anatomy/agents/{agent}/agent.yml").read_text())
        declared = doc["gdpr"]["retention_days"]
        assert declared == horizon, (
            f"{agent}/agent.yml declares retention_days: {declared} while the "
            f"listener enforces {horizon} — the register is the thing an "
            f"auditor reads, so it must be the thing that is true")


def test_every_seeded_setting_is_a_declared_column_with_a_reader():
    rows = yaml.safe_load(FIXTURE.read_text())["caddy"]
    columns = {c["key"] for c in yaml.safe_load(TABLE.read_text())["schema"]["columns"]}
    assert rows, "the settings fixture is empty"

    for row in rows:
        unknown = set(row) - columns
        assert not unknown, (
            f"settings row {row.get('slug')!r} carries {sorted(unknown)}, which "
            f"caddy.table.yml does not declare — KEAP would reject the seed on "
            f"the converge, not here")
        assert row.get("read_by", "").strip(), (
            f"settings row {row.get('slug')!r} names no reader. A config row "
            f"nobody reads is a switch in front of the operator that flips "
            f"nothing — say `nobody` and why, or delete the row")


def test_the_launcher_and_the_speech_half_check_themselves():
    """Both selfchecks RUN. Answer splitting, the rating scale, verbalisation."""
    for script in (REPO / "files/anatomy/ears/caddy.py",):
        run = subprocess.run([sys.executable, str(script), "--selfcheck"],
                             capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, f"{script.name} selfcheck failed:\n{run.stderr}"


def test_every_opcode_the_cortex_registry_publishes_can_be_SAID():
    """The wording table against the REGISTRY, not against a memory of it.

    An opcode nobody taught this file to say cannot be spoken — and the
    verbaliser refuses the whole chain rather than reading raw syntax, which
    means a new opcode silently makes some answers unspeakable. So the gate
    reads cortex-opcodes.ts, the artifact that defines the set, and holds every
    name in it to an entry in every declared language.
    """
    registry = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"
    wording = yaml.safe_load(WORDING.read_text())
    opcodes = set(re.findall(r"^\s*name:\s*'([a-z]+)'", registry.read_text(), re.M))
    assert len(opcodes) >= 14, f"only {len(opcodes)} opcodes parsed — the registry moved"

    namespaces = set(re.findall(r"CORTEX_NAMESPACES\s*=\s*\[([^\]]+)\]",
                                registry.read_text())[0].replace("'", "").split(","))
    namespaces = {n.strip() for n in namespaces if n.strip()}

    for lang in wording["languages"]:
        missing_ops = sorted(o for o in opcodes
                             if lang not in (wording["opcodes"].get(o) or {}))
        assert not missing_ops, (
            f"opcodes with no {lang} wording: {missing_ops}. A chain using one "
            f"cannot be read aloud at all — the verbaliser refuses rather than "
            f"speak syntax, so this is a silent loss of the spoken answer.")
        missing_ns = sorted(n for n in namespaces
                            if lang not in (wording["namespaces"].get(n) or {}))
        assert not missing_ns, f"namespaces with no {lang} wording: {missing_ns}"


def test_a_chain_is_verbalised_or_refused_never_read_as_syntax():
    """Behavioural: drive the verbaliser, including the failure it must have."""
    sys.path.insert(0, str(REPO / "files/anatomy/ears"))
    import speech                                            # noqa: PLC0415

    wording = speech.load_wording(WORDING)
    cs = speech.verbalise("@input | map(tax:02.02) | rank()", "cs", wording)
    assert "nula dva tečka nula dva" in cs, (
        f"the identifier was not spelled: {cs!r} — a synthesiser reading "
        f"'02.02' as a number names a different node than the screen does")
    assert "|" not in cs and "tax:" not in cs, f"syntax leaked into speech: {cs!r}"

    mutating = speech.verbalise('@input | insert(db:partners, ?commit=true)', "en", wording)
    assert mutating.rstrip().endswith(wording["mutating_suffix"]["en"].strip()), (
        f"a mutating chain did not end by saying so: {mutating!r}")

    with pytest.raises(speech.Unspeakable):
        speech.verbalise("@input | frobnicate(tax:01)", "en", wording)

    assert speech.detect_lang("kolik je otevřených highs") == "cs"
    assert speech.detect_lang("how many open highs") == "en"


@pytest.mark.parametrize("switch", ["--on", "--off"])
def test_the_microphone_has_exactly_one_switch(switch):
    """`ears_always_listen` + a converge, and nothing else.

    A second way to start the ear means the next converge silently closes it —
    and the estate's standing rule is that either the playbook does it or the
    operator runs nos, with nothing in between. Pinned because the CLI HAD these
    flags on the day it was written."""
    src = LISTENER.read_text()
    assert f'"{switch}"' not in src, (
        f"ears-listen grew {switch} back — two switches for one microphone, and "
        f"the converge silently wins")
