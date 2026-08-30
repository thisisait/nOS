"""Every committed agent manifest must load through the REAL loader.

WHAT IT WOULD HAVE CAUGHT, and the estate paid for the absence on 2026-08-29.

An over-engineering sweep deleted `final class VaultRequirement` from
`app/AgentKit/Agent.php`. It shared that file with `RosterEntry`, the
coordinator surface that WAS dead, and went out with it. But
`AgentLoader::load()` still constructs a `VaultRequirement` for every entry in
a manifest's `vault: required_credentials:` block — and all eight agent
manifests carry one.

The full suite stayed green. 5 174 gates, and not one of them loaded a real
manifest through the real loader: the schema gate parses the YAML against a
JSON-Schema, the naming gate greps class names, the tool-scope gates construct
their subjects directly. Every check looked at a piece.

The estate found out the way it always does when nothing asks — a converge
pushed the source to the host and the next five scheduled agent runs died:

    conductor:self-test-001       rc=1  Class "App\\AgentKit\\VaultRequirement" not found
    librarian:judge-lint-queue    rc=1  (same)
    librarian:brief-taxonomy      rc=1  (same)
    surveyor:surface-survey       rc=1  (same)

Sixteen hours between the deletion and the first failure, and the only reason
it was that short is that somebody happened to converge.

A CEILING FOUND WHILE WRITING THIS. `Agent.php` declares four classes and
PSR-4 resolves only the one named after the file; the other three exist solely
because something loads `Agent` first. That holds in production, and it held
here once the harness did the same — but a future caller that constructs a
`ToolSpec` without having touched `Agent` fatals exactly the way
`VaultRequirement` did. Splitting the file into four is the fix. Not this
gate's job, and not done here.

WHY THIS SHAPE. The gate does not assert what the loader returns — the schema
gate owns that. It asserts that constructing an Agent from each committed
manifest RUNS: every class the construction path touches exists, every
constructor signature still matches. That is the one thing a per-file check
cannot see, and it is exactly what a deletion breaks.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AGENTS = REPO / "files/anatomy/agents"
VENDOR = WING / "vendor/autoload.php"

pytestmark = pytest.mark.skipif(
    shutil.which("php") is None or not VENDOR.exists(),
    reason="php or the wing vendor tree is absent — declare "
           "files/anatomy/wing/vendor/autoload.php in NOS_TEST_PROVIDES to bind this",
)

NAMES = sorted(p.name for p in AGENTS.iterdir()
               if p.is_dir() and (p / "agent.yml").is_file())

PHP = r"""
require __DIR__ . '/vendor/autoload.php';
// Agent.php declares four classes (Agent, ToolSpec, VaultRequirement,
// SubscriptionSpec) and PSR-4 resolves only the one named after the file.
// Production always touches Agent before the loader runs, which parses the
// file and brings the other three with it; a harness that skips that step
// fatals on ToolSpec and blames the tree. Mirror production, do not work
// around it.
class_exists(App\AgentKit\Agent::class);
$root = $argv[1];
$out = [];
foreach (array_slice($argv, 2) as $name) {
    try {
        $loader = new App\AgentKit\AgentLoader($root . '/files/anatomy/agents');
        $agent  = $loader->load($name);
        $out[$name] = ['ok' => true, 'creds' => count($agent->requiredCredentials)];
    } catch (\Throwable $e) {
        $out[$name] = ['ok' => false, 'error' => get_class($e) . ': ' . $e->getMessage()];
    }
}
echo json_encode($out);
"""


def _load_all() -> dict:
    done = subprocess.run(
        ["php", "-r", PHP, str(REPO), *NAMES],
        capture_output=True, text=True, timeout=120, cwd=WING,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
             "HOME": str(pathlib.Path.home()),
             "NOS_REPO_ROOT": str(REPO)})
    assert done.returncode == 0, (
        "the loader harness itself did not run — a fatal error before any "
        f"manifest was tried:\n{done.stderr[-800:]}")
    return json.loads(done.stdout)


def test_there_are_manifests_to_load() -> None:
    """Positive control. An empty agents/ directory must not read as green —
    that is the failure this whole file exists to refuse."""
    assert len(NAMES) >= 5, f"only {len(NAMES)} agent manifests found: {NAMES}"


def test_every_manifest_constructs() -> None:
    results = _load_all()
    broken = {n: r["error"] for n, r in results.items() if not r["ok"]}
    assert not broken, (
        "an agent manifest cannot be loaded by the code that loads it:\n  "
        + "\n  ".join(f"{n}: {e}" for n, e in broken.items())
        + "\nA missing class here is not a lint — every scheduled run of that "
          "agent dies at the first line of work.")


def test_the_vault_block_actually_reaches_an_object() -> None:
    """The specific path the deletion broke. Eight manifests declare
    `vault.required_credentials`; if the loader silently returned an empty
    list, this gate would pass while the block meant nothing."""
    results = _load_all()
    declared = [n for n in NAMES
                if "required_credentials" in (AGENTS / n / "agent.yml").read_text(encoding="utf-8")]
    assert declared, "no manifest declares required_credentials — re-scope this gate"
    for name in declared:
        assert results[name]["creds"] > 0, (
            f"{name} declares vault.required_credentials and the loader built "
            "none — the block is being parsed and dropped")
