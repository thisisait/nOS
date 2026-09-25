"""Run the report-chain generator's validator in CI, where it was never run.

`tools/test_report_chain_synth_gen.py` checks that every table, column,
relation and opcode the generated chains reference actually exists — and the
first time anyone ran it, on 2026-09-25, it found the generator validating
against a schema nine days stale (four real tables missing: `invoice-line`,
`pending-invoice-verify`, `party-registry-status`, `invoice-review`; plus
`invoice.book_owner`). The cause was commits stranded on a branch based at the
v0.12 release point, and the check is what made it visible.

It had never run in CI. The pytest job is `python3 -m pytest tests/`; that file
lives under tools/, where the only thing referencing it is a gate that treats it
as a tool needing documented flags. A validator nobody runs is a validator that
reports nothing — this estate's recurring shape.

Left as a subprocess rather than an import: the file is deliberately a
standalone script with module-level asserts and no framework, and it is owned
by a parallel work stream. This gates it without restructuring it.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "tools" / "test_report_chain_synth_gen.py"


def test_the_generated_chains_match_the_live_schema():
    assert CHECK.is_file(), f"{CHECK} is gone — did it move? point this gate at it"
    p = subprocess.run([sys.executable, str(CHECK)], cwd=ROOT,
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, (
        "the synthesized report-prepare chains reference schema that does not "
        f"exist:\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}"
    )
