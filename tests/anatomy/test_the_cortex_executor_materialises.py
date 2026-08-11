"""Every cortex handler must load, and the registry must refuse to be short.

WHY EXECUTION AND NOT GREP. Twenty-four hours before this file was written,
`AskOperatorTool` shipped with a missing `use` statement: `php -l` clean, eight
dedicated grep-based tests green, and the class could not be instantiated. The
lesson was recorded as *a lint is not a load*, and this gate is the cortex
executor's version of it — it requires each class for real and asks PHP whether
it exists afterwards.

WHAT ELSE IT PINS, AND WHY EACH ONE IS HERE

  * **The registry's coverage gate actually refuses.** `assertCoversPublished()`
    is what makes Wing fail closed when KEAP publishes a dispatchable opcode
    nobody wrote a handler for. A gate that only checked the method EXISTS
    would pass against a body that returns early — so this calls it with a
    published opcode that has no handler and requires the throw.

  * **Mutating opcodes are excluded from coverage.** KEAP publishes 14, seven of
    them mutating; P1 refuses mutating stages at the door. Demanding handlers
    for verbs the executor will not run would be a gate insisting on dead code,
    so the exclusion is asserted rather than assumed.

  * **A capability may not be addable by data.** The handler map is a literal in
    `common.neon` and a class per verb. This checks the two agree — a handler
    class nobody registered is unreachable, and a registration with no class
    fatals the container at boot.

WHAT IT DOES NOT COVER. Whether a handler's body does anything useful.

THIS PARAGRAPH USED TO BE WRONG, and the correction is left here rather than the
sentence deleted. It claimed five of the seven verbs were late-bound because the
upstream served nothing for them, citing a 2026-08-09 sweep in which several
`/agent/v1/…` paths answered 401 to both bearers. The 401s were real; the
conclusion was not — the probe tested the paths a design document named, and a
401 from the forward-auth catch-all on an unrouted path is byte-identical to a
scope refusal. The real blocker was ours: the executor dispatched stages
independently, so a verb defined over its input had no input.

The claim is DESCRIBED and not quoted, deliberately. `test_cortex_blocker_is_
named_correctly.py` forbids the phrasings by regex, and reproducing one inside a
correction fails that gate — which it duly did on the first attempt, the third
time this repository has watched a check match the prose written about its own
defect.

Fixed 2026-08-11. `embed` alone is late-bound now, for the one genuinely upstream
reason. `test_cortex_blocker_is_named_correctly.py` gates that sentence in the
handler sources — and NOT here, because its `_php_sources()` scans handlers and
the client only. The retired claim survived three days next door to the gate
written to retire it, which is the most exact possible demonstration of why that
gate should read wider.
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
CORTEX = WING / "app/Cortex"
NEON = WING / "app/config/common.neon"

pytestmark = pytest.mark.skipif(
    shutil.which("php") is None, reason="php not installed on this runner"
)

PRELUDE = [
    "app/Cortex/CortexStageResult.php",
    "app/Cortex/ResolvedStage.php",
    "app/Cortex/CortexContext.php",
    "app/Cortex/Handler/CortexHandlerInterface.php",
    "app/Cortex/Handler/LateBoundHandler.php",
    "app/Model/KeapCortexClient.php",
    "app/Cortex/CortexOpcodeRegistry.php",
    "app/Cortex/CortexCapability.php",
    "app/Cortex/CortexBindingGate.php",
]


def registered_handlers() -> list[str]:
    src = NEON.read_text(encoding="utf-8")
    names = re.findall(r"- @App\\Cortex\\Handler\\(\w+)", src)
    assert names, (
        "no cortex handlers found in common.neon's registry factory — the block "
        "moved or was renamed. Point this gate at the new shape rather than "
        "letting it iterate an empty list and pass."
    )
    return sorted(set(names))


def php(script: str, tmp_path: Path) -> subprocess.CompletedProcess:
    requires = "\n".join(f"require '{WING}/{p}';" for p in PRELUDE)
    f = tmp_path / "probe.php"
    f.write_text(f"<?php\n{requires}\n{script}\n", encoding="utf-8")
    return subprocess.run(["php", "-d", "error_reporting=E_ALL", str(f)],
                          capture_output=True, text=True, timeout=60)


def test_the_registry_is_not_empty():
    assert len(registered_handlers()) == 7, (
        f"{len(registered_handlers())} handlers registered; P1 is exactly the 7 "
        "non-mutating opcodes KEAP publishes. If that set changed, change this "
        "number deliberately — a floor of zero passes vacuously.")


@pytest.mark.parametrize("handler", registered_handlers())
def test_each_registered_handler_materialises(handler: str, tmp_path: Path):
    path = CORTEX / "Handler" / f"{handler}.php"
    assert path.is_file(), (
        f"common.neon registers {handler} but {path.relative_to(REPO)} is "
        "missing — the container would fatal at boot.")
    out = php(textwrap.dedent(f"""\
        require '{path}';
        $c = 'App\\\\Cortex\\\\Handler\\\\{handler}';
        echo class_exists($c, false) ? 'OK' : 'MISSING';
    """), tmp_path)
    assert out.stdout.strip() == "OK", (
        f"{handler} does not load.\nstdout: {out.stdout}\nstderr: {out.stderr}")


def test_the_coverage_gate_actually_throws(tmp_path: Path):
    """Call it with an uncovered published opcode and require the refusal."""
    out = php(textwrap.dedent("""\
        $reg = new App\\Cortex\\CortexOpcodeRegistry([]);
        try {
            $reg->assertCoversPublished([['name' => 'get', 'mutating' => false]]);
            echo 'NO-THROW';
        } catch (\\RuntimeException $e) {
            echo str_contains($e->getMessage(), 'get') ? 'THREW' : 'THREW-VAGUE';
        }
    """), tmp_path)
    assert out.stdout.strip() == "THREW", (
        "assertCoversPublished did not refuse an uncovered non-mutating opcode, "
        f"or did not name it.\nstdout: {out.stdout}\nstderr: {out.stderr}")


def test_mutating_opcodes_are_not_demanded(tmp_path: Path):
    out = php(textwrap.dedent("""\
        $reg = new App\\Cortex\\CortexOpcodeRegistry([]);
        try {
            $reg->assertCoversPublished([['name' => 'insert', 'mutating' => true]]);
            echo 'OK';
        } catch (\\RuntimeException $e) {
            echo 'THREW';
        }
    """), tmp_path)
    assert out.stdout.strip() == "OK", (
        "coverage demanded a handler for a MUTATING opcode. P1 refuses mutating "
        "stages at the door, so this would be a gate insisting on dead code."
        f"\nstdout: {out.stdout}\nstderr: {out.stderr}")


def test_a_token_without_all_three_axes_has_no_capability(tmp_path: Path):
    """The brain token must not open the executor."""
    out = php(textwrap.dedent("""\
        $C = 'App\\Cortex\\CortexCapability';
        $none = $C::fromToken(['name' => 'default']);
        $half = $C::fromToken(['cortex_verbs' => 'get', 'cortex_namespaces' => 'tax']);
        $full = $C::fromToken(['cortex_verbs' => 'get', 'cortex_namespaces' => 'tax',
                               'cortex_tenants' => 'default']);
        echo ($none === null ? 'a' : '-') . ($half === null ? 'b' : '-')
           . ($full !== null ? 'c' : '-');
    """), tmp_path)
    assert out.stdout.strip() == "abc", (
        "a token with no cortex columns, or with only some axes granted, was "
        "given a capability. Every token that predates this feature has NULL "
        "columns, including the brain token — they must all be refused."
        f"\nstdout: {out.stdout}\nstderr: {out.stderr}")


def test_a_qualified_namespace_grant_does_not_widen(tmp_path: Path):
    """`db:wing` must not reach `db:gdpr`."""
    out = php(textwrap.dedent("""\
        $c = App\\Cortex\\CortexCapability::fromToken([
            'cortex_verbs' => 'get', 'cortex_namespaces' => 'db:wing',
            'cortex_tenants' => 'default']);
        echo ($c->allowsNamespace('db:wing') ? 'y' : 'n')
           . ($c->allowsNamespace('db:gdpr') ? 'y' : 'n')
           . ($c->allowsNamespace('db') ? 'y' : 'n');
    """), tmp_path)
    assert out.stdout.strip() == "ynn", (
        "a `db:wing` grant reached another db namespace. The qualified form "
        "exists precisely so a token that may read events cannot read the GDPR "
        f"store.\nstdout: {out.stdout}\nstderr: {out.stderr}")


def test_a_late_bound_handler_reports_absence_not_emptiness(tmp_path: Path):
    """Empty rows would be indistinguishable from a query that matched nothing.

    Probes `embed`, which on 2026-08-11 became the ONLY late-bound verb. This
    probed `rank` until then, and rank's unblocking broke it in a way worth
    recording: the probe constructs the handler directly, so the moment rank
    gained a `KeapCortexClient` dependency the test died on an ArgumentCountError
    rather than on its subject. A direct `new` is the right shape here — it keeps
    the probe free of the DI container — but it means this test must always name
    a handler that takes nothing, and `embed` is the one whose blocker is
    genuinely upstream (KEAP computes no embedding for supplied text).
    """
    out = php(textwrap.dedent(f"""\
        require '{CORTEX}/Handler/EmbedHandler.php';
        $h = new App\\Cortex\\Handler\\EmbedHandler();
        $r = $h->execute(
            new App\\Cortex\\ResolvedStage(0, 'embed', false, [], []),
            new App\\Cortex\\CortexContext('t', 'default', 'cx-test'));
        $a = $r->toArray();
        echo ($a['code'] ?? 'NONE');
    """), tmp_path)
    assert out.stdout.strip() == "late_binding_unavailable", (
        "a handler with no upstream route returned a plain empty result, which "
        "reads as 'the query matched nothing'. Absence must not render as calm."
        f"\nstdout: {out.stdout}\nstderr: {out.stderr}")
