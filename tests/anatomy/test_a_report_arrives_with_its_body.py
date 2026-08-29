"""A filed report that stored nothing is not a filed report.

MEASURED 2026-08-29, session `461db38c`. The surveyor POSTed a complete survey
— `result_json.report_markdown`, "## Surveyor report", ranked findings, the lot
— and the stored row came back `length(result_json) = 0`. The event existed, so
the deliverable check passed, so the run was satisfied. Every surface agreed and
the work was gone.

TWO SPELLINGS, ONE FIELD. `EventRepository::insert()` read the body from
`$payload['result']`; every agent PROMPT in this estate says
`result_json.report_markdown`, because that is what the column is called. Neither
side was wrong on its own and nothing compared them. The comment directly beneath
the fix records the same defect from 2026-05-05, one field along: "Bone POST
handler accepted `source` in JSON but the INSERT silently dropped it."

So this file pins both halves, by INSERTING through the real repository and
reading the row back:

  * either spelling arrives and is stored;
  * a body that is absent, or empty, does not satisfy a ceremony that owes one —
    an artifact nobody can read is the same as no artifact.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"

pytestmark = pytest.mark.skipif(
    not AUTOLOAD.is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\Model\EventRepository;
use Nette\Database\Connection;
use Nette\Database\Explorer;
use Nette\Database\Structure;
use Nette\Database\Conventions\DiscoveredConventions;
use Nette\Caching\Storages\MemoryStorage;

$db = sys_get_temp_dir() . '/nos-events-' . bin2hex(random_bytes(4)) . '.db';
$init = getenv('NOS_INIT_DB');
exec(sprintf('php %s --data-dir=%s 2>&1', escapeshellarg($init), escapeshellarg(dirname($db))), $o, $rc);
// init-db writes wing.db in the given dir; use that.
$db = dirname($db) . '/wing.db';

$conn = new Connection('sqlite:' . $db);
$storage = new MemoryStorage();
$structure = new Structure($conn, $storage);
$explorer = new Explorer($conn, $structure, new DiscoveredConventions($structure), $storage);
$repo = new EventRepository($explorer);

$out = [];
foreach ([
    'legacy_result'   => ['result'      => ['report_markdown' => '## from result']],
    'agent_spelling'  => ['result_json' => ['report_markdown' => '## from result_json']],
    'no_body'         => [],
] as $label => $extra) {
    $id = $repo->insert(array_merge([
        'ts' => gmdate('c'), 'type' => 'conductor_report', 'run_id' => 'r-' . $label,
        'actor_action_id' => 's-' . $label,
    ], $extra));
    $row = $conn->fetch('SELECT result_json FROM events WHERE id = ?', $id);
    $out[$label] = $row->result_json;
}
echo json_encode($out);
"""


def _probe() -> dict:
    p = WING / "events-body-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", p.name], cwd=WING, capture_output=True, text=True, timeout=90,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                 "HOME": str(Path.home()),
                 "NOS_INIT_DB": str(WING / "bin/init-db.php")},
        )
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr or out.stdout
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_agent_spelling_is_stored() -> None:
    """`result_json` is what four agent prompts tell the model to send."""
    got = _probe()["agent_spelling"]
    assert got, "an agent's report body was dropped on insert — this is 461db38c"
    assert "from result_json" in got


def test_the_in_process_spelling_still_works() -> None:
    """AuditEmitter and Runner send `result`; the fix must not move the goalposts."""
    got = _probe()["legacy_result"]
    assert got and "from result" in got


def test_no_body_stores_null_rather_than_an_empty_object() -> None:
    """Absent and empty must stay tellable apart at the column."""
    assert _probe()["no_body"] in (None, "")


def test_the_deliverable_check_requires_a_body() -> None:
    """The Runner's reader is what turns a stored NULL into a refusal. Read the
    predicate rather than the prose around it: an existence-only check is what
    let 461db38c through."""
    src = (REPO / "files/anatomy/wing/app/AgentKit/Runner.php").read_text(encoding="utf-8")
    i = src.index("deliverableEvent === null")
    body = src[i:i + 1400]
    assert "result_json" in body, (
        "the deliverable reader no longer looks at the artifact's body; an "
        "empty report satisfies again"
    )
    for empty in ("'[]'", "'{}'"):
        assert empty in body, f"an artifact of {empty} counts as filed"
