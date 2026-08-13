"""A register can be complete and false. This gate reads the values.

MEASURED 2026-08-13, before the change this file accompanies:

    records in the Article-30 register            79
    records declaring ANY processor                0
    records declaring a transfer outside the EU    0

while eight agent ceremonies had been sending estate content to a US-hosted
model every night since the runtime shipped. The register was not neglected —
`test_gdpr_register_coverage.py` was green throughout, because it checks
COMPLETENESS (does every plugin yield a record) and PARITY (does every record
trace to a plugin) and never once a VALUE. Nothing asked whether `processors:
[]` was true.

THE OMISSION WAS STRUCTURAL, NOT CLERICAL. `nos_gdpr.all_records()` swept
`files/anatomy/plugins/` and `apps/`. Agent definitions live in
`files/anatomy/agents/`, which is neither, so no amount of care inside the
sweep could have found them; the register was answering a question that did
not include the agents.

WHAT THIS PINS, and why it cannot be satisfied by editing itself: the premise
is the EXISTENCE OF A CEREMONY FILE. `files/anatomy/agents/<name>.yml` with a
`pulse:` block is what `discover-pulse-catalog.py` globs to register a
scheduled job, and that job runs `pulse-run-agent.sh`, which runs `claude` —
a hosted model. So an agent with a ceremony has a processor, necessarily. To
make this gate pass falsely you would have to delete the ceremony, at which
point the claim is true again.

The converse is deliberately NOT asserted. `inspektor` ships as an AgentKit
contract with `runner_status: deferred` and no ceremony file; its empty
processor list is correct, and its own record carries the note that arming it
means rewriting the record first.
"""

from __future__ import annotations

import pathlib

import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import nos_gdpr  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files" / "anatomy" / "agents"


def _agents_with_a_ceremony() -> set[str]:
    """Agents whose flat profile declares a Pulse job — i.e. that actually run."""
    out: set[str] = set()
    for f in sorted(AGENTS.glob("*.yml")):
        try:
            m = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if isinstance(m, dict) and m.get("pulse"):
            out.add(f.stem)
    return out


def _agent_records() -> dict[str, dict]:
    return {
        r["id"].removeprefix("agent_"): r
        for r in nos_gdpr.records_from_agents(AGENTS)
    }


def test_the_sweep_reaches_the_agents_at_all():
    """Positive control. A zero-length sweep would make every check below pass."""
    records = _agent_records()
    assert len(records) >= 8, (
        f"only {len(records)} agent record(s) found. If `records_from_agents` "
        "has stopped reading `files/anatomy/agents/<name>/agent.yml`, the "
        "register is back to the shape it had on 2026-08-13: complete, green, "
        "and silent about every prompt that leaves this host."
    )


def test_every_running_ceremony_declares_a_processor():
    ceremonies = _agents_with_a_ceremony()
    assert ceremonies, "no agent declares a `pulse:` ceremony; the premise is gone"
    records = _agent_records()

    missing_record = sorted(ceremonies - records.keys())
    assert not missing_record, (
        "agent(s) run a scheduled ceremony but have no Article-30 record: "
        f"{missing_record}. The ceremony sends estate content to a hosted "
        "model; that is a transfer to a processor and it must be recorded "
        "before it runs, not after someone asks."
    )

    silent = sorted(
        name for name in ceremonies if not records[name]["processors"]
    )
    assert not silent, (
        f"ceremony/ies declaring NO processor while they run: {silent}. "
        "`processors: []` is a claim, not a default — and it was the estate's "
        "standing claim for every record until 2026-08-13."
    )


def test_every_running_ceremony_admits_the_transfer_leaves_the_eu():
    """`eu_residency` defaults to TRUE in nos_gdpr — an all-local-FOSS default
    that is wrong for anything calling a US-hosted model. A record that simply
    omits the field therefore reads as 'stays in the EU' and is believed."""
    records = _agent_records()
    offenders = sorted(
        name
        for name in _agents_with_a_ceremony()
        if name in records and not records[name]["transfers_outside_eu"]
    )
    assert not offenders, (
        f"ceremony/ies recorded as not leaving the EU: {offenders}. The default "
        "is what makes this worth asserting: omit the field and the register "
        "says the processing stayed home."
    )


def test_a_processor_entry_names_who_and_where():
    """A processor with no country cannot support a transfer assessment."""
    thin = []
    for name, rec in _agent_records().items():
        for p in rec["processors"]:
            if not p.get("name") or not p.get("country"):
                thin.append(f"{name}: {p!r}")
    assert not thin, (
        "processor entries missing a name or a country:\n  " + "\n  ".join(thin)
    )
