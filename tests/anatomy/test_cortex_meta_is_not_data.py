"""Rows are data; what a handler has to SAY rides `meta`. Never the same channel.

THE LIVE PROOF THIS ENCODES (operator-verified, 2026-08-12). Two defects, one
root: rows carried data and handler bookkeeping in a single keyspace with no
contract.

  1. `map` appended its truncation NOTE into `$rows`. Piped, that note became
     the next stage's input — an id-less pseudo-row — and a later `map` over it
     minted `upstream_unreachable`, the one absence code the executor calls
     page-worthy, while KEAP answered every probe.
  2. `filter where=tax` kept 5/5 rows, because every row carried `ns: "tax"` —
     a value the HANDLER wrote. The caller's predicate matched the pipeline's
     own handwriting.

The contract now has names: `CortexStageResult::$meta` for what the handler
says (truncation, unanswered inputs), `CortexRowProvenance::KEYS` for the marks
handlers leave on rows, and `filter`'s `where` is provenance-blind.

WHAT THIS CANNOT COVER. Handlers needing a live KeapCortexClient (map,
classify, get) are checked structurally — the client is final and unstubbable
offline, so their "no pseudo-rows" guarantee is asserted against source shape,
with the executable proof left to the live chain (tools/… executor probe).
FilterHandler has no upstream, so its half runs for real.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
HANDLER = WING / "app/Cortex/Handler"

pytestmark = pytest.mark.skipif(
    shutil.which("php") is None, reason="php not installed on this runner"
)

PRELUDE = [
    "app/Cortex/CortexStageResult.php",
    "app/Cortex/CortexContext.php",
    "app/Cortex/CortexRowProvenance.php",
    "app/Cortex/ResolvedStage.php",
    "app/Cortex/Handler/CortexHandlerInterface.php",
    "app/Cortex/Handler/FilterHandler.php",
]


def php(script: str, tmp_path: Path) -> subprocess.CompletedProcess:
    requires = "\n".join(f"require '{WING}/{p}';" for p in PRELUDE)
    f = tmp_path / "probe.php"
    f.write_text(f"<?php\n{requires}\n{script}\n", encoding="utf-8")
    return subprocess.run(["php", "-d", "error_reporting=E_ALL", str(f)],
                          capture_output=True, text=True, timeout=60)


def test_meta_rides_the_result_not_the_rows(tmp_path: Path) -> None:
    out = php(textwrap.dedent("""\
        $r = App\\Cortex\\CortexStageResult::read(
            [['id' => 'x']], 3, ['truncated_input' => 7]);
        $a = $r->toArray();
        echo count($a['rows']) === 1
            && ($a['meta']['truncated_input'] ?? null) === 7 ? 'OK' : 'BAD';
        // Empty meta must not even appear — absent, not declared-empty.
        $b = App\\Cortex\\CortexStageResult::read([])->toArray();
        echo array_key_exists('meta', $b) ? '-LEAK' : '-CLEAN';
    """), tmp_path)
    assert out.stdout.strip() == "OK-CLEAN", (
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )


def test_where_is_provenance_blind(tmp_path: Path) -> None:
    """The live defect, executed: rows whose only 'tax' is the handler-written
    `ns` mark must NOT be kept by `where=tax`; a row whose DATA says tax must."""
    out = php(textwrap.dedent("""\
        $h = new App\\Cortex\\Handler\\FilterHandler();
        $stage = App\\Cortex\\ResolvedStage::fromAst([
            'index' => 1, 'opcode' => 'filter', 'mutating' => false,
            'operands' => [], 'params' => ['where' => 'tax'],
        ]);
        $ctx = new App\\Cortex\\CortexContext('t', 'default', 'cx-test', null, [
            ['id' => '01', 'name' => 'Taxonomy of forms', 'ns' => 'tax'],
            ['id' => '02', 'name' => 'Cosmology', 'ns' => 'tax'],
            ['id' => '03', 'name' => 'Cosmology', 'ns' => 'tax',
             'mappedFrom' => 'tax:01'],
        ], true);
        $r = $h->execute($stage, $ctx);
        // Only row 01 has 'tax' in its DATA (the name); 02/03 carry it solely
        // in provenance (ns, mappedFrom).
        echo count($r->rows) === 1 && $r->rows[0]['id'] === '01' ? 'OK' : 'KEPT-' . count($r->rows);
    """), tmp_path)
    assert out.stdout.strip() == "OK", (
        "`where` matched handler-written provenance (ns/mappedFrom) — the "
        "filter is matching the pipeline's own handwriting again.\n"
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )


def test_every_handler_written_mark_is_declared() -> None:
    """The additive rule from CortexRowProvenance: a handler that writes a new
    mark declares it. Checked by sweeping handler sources for the row-attach
    idioms (`$row + [...]`, `$child['k'] = ...`) and requiring each attached
    key to be either declared provenance or an entity fact a handler merely
    copies (id/name/resolvedName/surface)."""
    prov = re.findall(
        r"'([A-Za-z]+)',",
        (WING / "app/Cortex/CortexRowProvenance.php").read_text(encoding="utf-8"),
    )
    assert "ns" in prov and "classifiedAs" in prov, "KEYS list moved — repoint"
    offenders = []
    for f in sorted(HANDLER.glob("*.php")):
        src = f.read_text(encoding="utf-8")
        # The MARK-ATTACHING idioms only: `$row + ['k' => …, 'k2' => …]` (keys
        # added onto a passing-through row) and `$child['k'] = …`. Rows a stage
        # CONSTRUCTS whole (`$rows[] = [...]` in get/resolve) are that stage's
        # data output, not marks — the first cut of this sweep read those too
        # and flagged resolve's own record fields as undeclared provenance.
        attached: list[str] = []
        for m in re.finditer(r"\$row \+ \[(?s:(.*?))\]", src):
            attached += re.findall(r"'(\w+)' =>", m.group(1))
        attached += re.findall(r"\$child\['(\w+)'\] = ", src, re.M)
        for key in attached:
            if key not in prov:
                offenders.append(f"{f.name}: {key}")
    assert not offenders, (
        "handler writes row key(s) not declared in CortexRowProvenance::KEYS "
        "and not a copied entity fact — declare or justify:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


def test_no_handler_appends_a_note_row() -> None:
    """The pseudo-row shape itself, banned at the source level: a handler must
    not append a row whose content is its own commentary. `'note' =>` inside a
    `$rows[] = [` block is the exact bytes both regressions shipped as."""
    offenders = []
    for f in sorted(HANDLER.glob("*.php")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\$rows\[\]\s*=\s*\[(?s:(.*?))\];", src):
            if "'note'" in m.group(1):
                offenders.append(f.name)
    assert not offenders, (
        "a handler appends a commentary row into $rows — that flows downstream "
        "as INPUT and (proved live 2026-08-12) mints upstream_unreachable "
        f"against a healthy KEAP. Use CortexStageResult meta: {offenders}"
    )


def test_get_answers_an_outage_the_same_way_in_both_namespaces() -> None:
    src = (HANDLER / "GetHandler.php").read_text(encoding="utf-8")
    assert src.count("upstreamUnreachable") >= 2, (
        "GetHandler no longer answers a null node fetch with a typed absence in "
        "BOTH arms — the tax: fallback-row inconsistency is back (an unreachable "
        "KEAP flowing on as data that 'executed')."
    )
    # The fallback-ROW shape itself is banned by test_no_handler_appends_a_note_
    # row above; matching the phrase 'resolution only' here re-caught this
    # file's own historical docblock, the recorded failure mode of gates that
    # grep the prose written about their subject.
